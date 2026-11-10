#!/usr/bin/env python3
"""Append a new wave of style packs to the live queue without touching existing rows.

Builds specs/batches for styles that are in style_packs.json but not yet in the
batches table, using a fresh subject catalog, then inserts them in one short
BEGIN IMMEDIATE transaction. queue_pos continues after the current max and is
round-robin interleaved across style × category × genre.

Does not claim work, does not rebuild the DB, does not update existing rows,
and does not call GenerateImage.

    nice -n 15 python3 /workspace/game-assets/append_styles.py
    nice -n 15 python3 /workspace/game-assets/append_styles.py --dry-build
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

from build_specs import (
    PACKS_PATH,
    perspective_for,
    pivot_for,
    subject_label,
    tags_for,
)
from db import LICENSE, ROOT, connect, init_db, set_meta, snapshot_progress
from reorder_queue import variety_order

NEW_STYLE_IDS = [
    "ink_watercolor",
    "paper_cutout",
    "claymation",
    "cel_shaded_anime",
    "retro_8bit",
    "vaporwave_synth",
    "gothic_woodcut",
    "isometric_voxel",
]

ICON_WEAPONS = [
    "moon_glaive", "hooked_kris", "coral_harpoon", "clockwork_handgun",
    "folding_fan_blade", "meteor_chain", "glass_rapier", "thorn_whip",
    "storm_chakram", "lantern_polearm", "gear_axe", "sun_disk",
]
ICON_ARMOR = [
    "reed_helm", "scale_coif", "mosaic_mask", "quilted_gambeson",
    "copper_pectoral", "river_sandals", "kite_shield", "travel_sash",
]
ICON_POTIONS = [
    "moonlight_phial", "bottled_storm", "sleeping_sand",
    "growth_tonic", "vinegar_ward", "bottled_echo",
]
ICON_FOOD = [
    "rice_dumpling", "grilled_skewer", "coconut_cup", "pepper_loaf",
    "candied_citrus", "seaweed_wrap", "spiced_nuts", "plum_tart",
]
ICON_TOOLS = [
    "jeweler_loupe", "mortar_pestle", "pulley_block", "tuning_fork",
    "chalk_line", "bellows", "spyglass", "seed_bag",
]
ICON_VALUABLES = [
    "amber_cabochon", "soapstone_bead", "trade_shell", "signet_seal",
    "music_box", "hourglass", "prayer_bell", "ink_stone",
    "pocket_astrolabe", "velvet_pouch",
]
ICON_MISC = [
    "wind_chime", "puzzle_box", "clay_whistle", "moth_wing",
    "dried_starfish", "signal_mirror", "charm_bundle", "spare_cog",
]
ICON_VARIANTS = ["plain", "ornate"]

TILE_FLOORS = [
    "kelp_mat", "boardwalk", "mosaic_tile", "terracotta", "basalt",
    "ripple_sand", "salt_flat", "mushroom_cap", "root_tangle", "aurora_ice",
    "rust_grate", "marble_inlay", "packed_clay", "pollen_field", "tar_pit",
    "stained_glass_floor", "cork", "lunar_dust",
]
TILE_WALLS = [
    "adobe_wall", "lattice_screen", "coral_wall", "bookshelf_wall",
    "iron_rivet_wall", "bamboo_wall", "ice_block_wall", "tapestry_wall",
]
TILE_VARIANTS = ["base", "variant_a"]

PROPS = [
    ("spice_rack", "plain"), ("spinning_wheel", "plain"),
    ("birdcage", "plain"), ("gong", "plain"),
    ("loom", "plain"), ("tea_set", "plain"),
    ("music_stand", "plain"), ("fish_drying_rack", "plain"),
    ("sundial", "plain"), ("incense_burner", "lit"),
    ("hanging_lantern", "lit"), ("millstone", "plain"),
    ("water_trough", "plain"), ("notice_board", "blank"),
    ("wheelbarrow", "plain"), ("kite", "plain"),
    ("clay_oven", "plain"), ("pulley_crane", "plain"),
    ("wind_chime_stand", "plain"), ("stacked_scrolls", "plain"),
    ("willow_tree", "plain"), ("pagoda_gate", "plain"),
    ("observatory_dome", "plain"), ("reef_arch", "plain"),
]
LARGE_PROPS = {"willow_tree", "pagoda_gate", "observatory_dome", "reef_arch"}

CHARACTERS = [
    "cartographer", "glassblower", "beekeeper", "gondolier",
    "mask_maker", "balloonist", "herbalist", "bell_ringer",
    "dune_runner", "ice_fisher", "puppeteer", "stargazer",
    "ferry_pilot", "roof_tinker", "orchard_keeper", "ink_scribe",
]
CHAR_VIEWS = ["front", "three_quarter", "side", "back"]

ENEMIES = [
    "paper_crane_spirit", "lantern_moth", "tide_crab", "rust_mite",
    "pollen_bee", "ink_blot", "clockwork_owl", "sand_lizard",
    "coral_urchin", "kettle_imp", "moss_turtle", "glass_fox",
    "storm_puff", "ribbon_eel", "chalk_golem", "teapot_elemental",
]
ENEMY_VARIANTS = ["idle_front", "idle_side", "alert"]

UI_ITEMS = [
    ("button", "up"), ("button", "down"), ("button", "hover"), ("button", "disabled"),
    ("panel", "light"), ("panel", "dark"),
    ("frame", "simple"), ("frame", "ornate"),
    ("bar_track", "plain"), ("stamina_fill", "plain"), ("focus_fill", "plain"), ("heat_fill", "plain"),
    ("item_slot", "empty"), ("item_slot", "selected"),
    ("checkbox", "off"), ("checkbox", "on"),
    ("slider_track", "plain"), ("slider_knob", "plain"),
    ("icon_close", "plain"), ("icon_plus", "plain"),
    ("icon_journal", "plain"), ("icon_craft", "plain"),
    ("icon_camp", "plain"), ("icon_hint", "plain"),
    ("cursor", "pointer"), ("cursor", "hand"),
    ("tooltip", "plain"), ("tab", "active"), ("tab", "inactive"),
    ("scrollbar", "plain"), ("window_header", "plain"), ("dialogue_box", "plain"),
]

VFX = [
    "petal_burst", "ink_splash", "ripple_ring", "clockwork_spark",
    "sand_swirl", "bubble_pop", "origami_fold", "lantern_flare",
    "pollen_drift", "frost_crack", "ribbon_twirl", "tea_steam",
    "echo_wave", "mosaic_shatter",
]
VFX_FRAMES = ["f1", "f2", "f3", "f4"]

BACKGROUNDS = [
    "tide_pool", "bamboo_grove", "rooftop_garden", "salt_mine",
    "balloon_harbor", "sunken_colonnade", "winter_market", "desert_observatory",
    "tea_house", "clockwork_foundry", "lichen_canyon", "lantern_festival_street",
    "glacier_cave", "orchard_at_dusk",
]
PARALLAX_BIOMES = ["tide_marsh", "bamboo_hills", "rooftop_city", "salt_flats", "lantern_harbor"]
PARALLAX_LAYERS = ["sky", "far", "mid", "near"]


def build_wave(packs: dict, style_ids: list[str]) -> tuple[list[dict], list[dict]]:
    specs: list[dict] = []
    raw: list[dict] = []

    def add(style, category, subcategory, subject, variant, *, tileable=False, kind_hint=None, extra_desc=""):
        pack = packs[style]
        tw, th = pack["sizes"][category]
        px, py = pivot_for(category)
        label = subject_label(subject)
        var_l = subject_label(variant)
        desc = f"{label} ({var_l}), {pack['title']} {category} / {subcategory}"
        if extra_desc:
            desc = f"{desc}. {extra_desc}"
        if tileable:
            desc += ". Seamless tileable texture."
        spec_id = f"{style}/{category}/{subcategory}/{subject}_{variant}"
        raw.append({
            "spec_id": spec_id,
            "category": category,
            "subcategory": subcategory,
            "subject": subject,
            "variant": variant,
            "style_pack": style,
            "tags": tags_for(category, subcategory, subject, variant, style, tw, th, tileable),
            "description": desc,
            "negative": pack["negative"],
            "style_prefix": pack["style_prefix"],
            "target_w": tw,
            "target_h": th,
            "tileable": int(tileable),
            "perspective": perspective_for(pack, category),
            "pivot_x": px,
            "pivot_y": py,
            "has_alpha_intended": 0 if (tileable or category == "backgrounds") else 1,
            "kind_hint": kind_hint,
        })

    for style in style_ids:
        if style not in packs:
            raise KeyError(f"missing style pack: {style}")
        for sub, items in (
            ("weapon", ICON_WEAPONS),
            ("armor", ICON_ARMOR),
            ("potion", ICON_POTIONS),
            ("food", ICON_FOOD),
            ("tool", ICON_TOOLS),
            ("valuable", ICON_VALUABLES),
            ("misc", ICON_MISC),
        ):
            for subj in items:
                for var in ICON_VARIANTS:
                    add(style, "icons", sub, subj, var, kind_hint="icon_sheet")

        for subj in TILE_FLOORS:
            for var in TILE_VARIANTS:
                add(style, "tiles", "floor", subj, var, tileable=True, kind_hint="tile_single")
        for subj in TILE_WALLS:
            for var in TILE_VARIANTS:
                add(style, "tiles", "wall", subj, var, tileable=True, kind_hint="tile_single")

        for subj, var in PROPS:
            hint = "prop_single" if subj in LARGE_PROPS else "prop_sheet"
            add(style, "props", "object", subj, var, kind_hint=hint)

        for subj in CHARACTERS:
            for var in CHAR_VIEWS:
                add(
                    style, "characters", "humanoid", subj, var, kind_hint="turnaround",
                    extra_desc="Original stylized character, not a real person.",
                )

        for subj in ENEMIES:
            for var in ENEMY_VARIANTS:
                add(style, "enemies", "creature", subj, var, kind_hint="enemy_sheet")

        for subj, var in UI_ITEMS:
            add(style, "ui", "widget", subj, var, kind_hint="ui_sheet")

        for subj in VFX:
            for var in VFX_FRAMES:
                add(style, "vfx", "effect", subj, var, kind_hint="vfx_sheet")

        for subj in BACKGROUNDS:
            add(style, "backgrounds", "scene", subj, "wide", kind_hint="bg_single",
                extra_desc="Wide environment plate, no characters in the foreground.")
        for biome in PARALLAX_BIOMES:
            for layer in PARALLAX_LAYERS:
                add(
                    style, "backgrounds", "parallax", f"{biome}_{layer}", layer,
                    kind_hint="bg_single",
                    extra_desc=f"Parallax {layer} layer for a {subject_label(biome)} biome; empty of gameplay characters; consistent horizon.",
                )

    batches: list[dict] = []
    grouped: dict[tuple, list[dict]] = {}
    singles: list[dict] = []
    turnarounds: dict[tuple, list[dict]] = {}
    vfx_groups: dict[tuple, list[dict]] = {}
    SHEET_KINDS = {"icon_sheet", "prop_sheet", "ui_sheet", "enemy_sheet"}

    for row in raw:
        hint = row["kind_hint"]
        if hint == "turnaround":
            key = (row["style_pack"], row["category"], row["subject"])
            turnarounds.setdefault(key, []).append(row)
        elif hint == "vfx_sheet":
            key = (row["style_pack"], row["subject"])
            vfx_groups.setdefault(key, []).append(row)
        elif hint in SHEET_KINDS:
            key = (row["style_pack"], row["category"], row["subcategory"], hint)
            grouped.setdefault(key, []).append(row)
        else:
            singles.append(row)

    def chunk(lst, n):
        for i in range(0, len(lst), n):
            yield lst[i : i + n]

    def sheet_prompt(pack, rows, grid_w, grid_h, title, cell_desc) -> str:
        names = []
        for i, r in enumerate(rows):
            col = i % grid_w
            rowi = i // grid_w
            names.append(
                f"row {rowi+1} col {col+1}: {subject_label(r['subject'])}, {subject_label(r['variant'])}"
            )
        while len(names) < grid_w * grid_h:
            names.append(f"row {len(names)//grid_w+1} col {len(names)%grid_w+1}: leave this cell empty, only magenta")
        listing = "; ".join(names)
        chroma = pack["chroma"]
        return (
            f"{title} arranged in a regular {grid_w} by {grid_h} grid on a flat solid magenta background {chroma}. "
            f"Each item is centered in its own cell with wide empty magenta margins on all four sides, "
            f"a thick magenta gutter between every cell, nothing crossing cell borders, and no item touching a neighbor or the cell edge. "
            f"No labels, no numbers, no captions, no watermark. {cell_desc} "
            f"{pack['style_prefix']}. Cells, in row-major order: {listing}."
        )

    def add_batch(kind, rows, grid_w, grid_h, aspect, prompt_builder):
        pack = packs[rows[0]["style_pack"]]
        style = rows[0]["style_pack"]
        cat = rows[0]["category"]
        batch_index = len(batches)
        batch_id = f"b{batch_index:05d}_{style}_{cat}_{kind}"
        prompt = prompt_builder(pack, rows, grid_w, grid_h)
        batch = {
            "batch_index": batch_index,
            "batch_id": batch_id,
            "kind": kind,
            "grid_w": grid_w,
            "grid_h": grid_h,
            "n_cells": grid_w * grid_h,
            "style_pack": style,
            "category": cat,
            "genre": rows[0]["subcategory"],
            "prompt": prompt,
            "negative": pack["negative"],
            "aspect_ratio": aspect,
            "filename_hint": f"{batch_id}.png",
            "status": "pending",
            "rows": rows,
        }
        for i, r in enumerate(rows):
            r["batch_id"] = batch_id
            r["cell_index"] = i
            r["prompt"] = prompt
            specs.append(r)
        batches.append(batch)

    for key, rows in grouped.items():
        style, category, subcategory, hint = key
        pack = packs[style]
        if hint == "icon_sheet":
            title = f"A 4x4 grid of sixteen {pack['title']} game item icons"
            cell = "Each icon is a single centered object, readable as a small inventory icon, no scene, no hands."
        elif hint == "prop_sheet":
            title = f"A 4x4 grid of sixteen {pack['title']} game world props"
            cell = "Each cell is a single prop, standing upright, feet toward the bottom of the cell, no environment."
        elif hint == "ui_sheet":
            title = f"A 4x4 grid of sixteen {pack['title']} game user-interface pieces"
            cell = "Each cell is one UI widget or icon, clean and usable in a game HUD, no sample text inside unless the widget is a blank empty panel."
        else:
            title = f"A 4x4 grid of sixteen {pack['title']} game enemy creatures"
            cell = "Each cell is one small original creature sprite, full body, standing, not a famous character."
        for group in chunk(rows, 16):
            add_batch(
                "sheet", group, 4, 4, "1:1",
                lambda p, rs, w, h, t=title, c=cell: sheet_prompt(p, rs, w, h, t, c),
            )

    for key, rows in turnarounds.items():
        rows = sorted(rows, key=lambda r: CHAR_VIEWS.index(r["variant"]) if r["variant"] in CHAR_VIEWS else 99)
        pack = packs[rows[0]["style_pack"]]
        subj = subject_label(rows[0]["subject"])
        title = f"A 2x2 character turnaround sheet of one original {pack['title']} {subj}"
        cell = (
            f"Same single original character in all four cells, consistent outfit, palette, proportions and face. "
            f"Full body, feet at the bottom of each cell, no floor. Not a real person and not a copyrighted character."
        )
        add_batch(
            "turnaround", rows, 2, 2, "1:1",
            lambda p, rs, w, h, t=title, c=cell: sheet_prompt(p, rs, w, h, t, c),
        )

    for key, rows in vfx_groups.items():
        rows = sorted(rows, key=lambda r: VFX_FRAMES.index(r["variant"]) if r["variant"] in VFX_FRAMES else 99)
        style, subject = key
        pack = packs[style]
        label = subject_label(subject)
        title = f"A 2x2 animation sheet of a {pack['title']} {label} visual effect"
        cell = (
            "Four chronological frames of the same effect, row-major f1 f2 / f3 f4, same center anchor, "
            "transparent-ready magenta background, no typography."
        )
        add_batch(
            "vfx", rows, 2, 2, "1:1",
            lambda p, rs, w, h, t=title, c=cell: sheet_prompt(p, rs, w, h, t, c),
        )

    for row in singles:
        pack = packs[row["style_pack"]]
        chroma = pack["chroma"]
        label = f"{subject_label(row['subject'])}, {subject_label(row['variant'])}"
        if row["category"] == "tiles":
            prompt = (
                f"A seamless tileable top-down {label} terrain texture for a 2D game, even lighting, "
                f"the pattern must repeat cleanly on all four edges, no objects, no characters, no text, "
                f"edge-to-edge surface only. {pack['style_prefix']}."
            )
            aspect, kind = "1:1", "tile"
        elif row["category"] == "backgrounds":
            prompt = (
                f"A wide 16:9 2D game background of {label}. {row['description']} "
                f"Cinematic but clear, no frame, no UI, no watermark, no typography, original location. "
                f"{pack['style_prefix']}. Fill the entire frame (ignore the magenta instruction for this background plate)."
            )
            aspect, kind = "16:9", "background"
        else:
            prompt = (
                f"A single {pack['title']} game prop: {label}, centered, full object visible, "
                f"standing on an implied ground but with a flat solid magenta background {chroma}, "
                f"no floor plane, no text. {pack['style_prefix']}."
            )
            aspect, kind = "1:1", "single"
        add_batch(kind, [row], 1, 1, aspect, lambda p, rs, w, h, pr=prompt: pr)

    for s in specs:
        s.pop("kind_hint", None)
    return specs, batches


def reindex(batches: list[dict], specs: list[dict], start_batch: int, start_spec: int) -> None:
    for i, b in enumerate(batches):
        new_index = start_batch + i
        new_id = f"b{new_index:05d}_{b['style_pack']}_{b['category']}_{b['kind']}"
        b["batch_index"] = new_index
        b["batch_id"] = new_id
        b["filename_hint"] = f"{new_id}.png"
        for r in b["rows"]:
            r["batch_id"] = new_id
    for i, s in enumerate(specs):
        s["spec_index"] = start_spec + i


def assign_queue_pos(batches: list[dict], start_pos: int) -> None:
    items = [
        {
            "category": b["category"],
            "style_pack": b["style_pack"],
            "genre": b.get("genre") or b["category"],
            "batch": b,
        }
        for b in batches
    ]
    ordered = variety_order(items)
    for i, it in enumerate(ordered):
        it["batch"]["queue_pos"] = start_pos + i


def backup_db(src: Path) -> Path:
    backup_dir = ROOT / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%dT%H%M%S")
    dest = backup_dir / f"assets.db.bak-wave2-{stamp}"
    source = connect(src)
    dest_conn = connect(dest)
    try:
        source.backup(dest_conn)
        dest_conn.commit()
    finally:
        dest_conn.close()
        source.close()
    return dest


def append_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def write_taxonomy(conn, packs: dict) -> None:
    styles = [r[0] for r in conn.execute("SELECT DISTINCT style_pack FROM batches ORDER BY style_pack")]
    # Keep JSON file order when possible
    pack_order = [s for s in packs if s in set(styles)] + [s for s in styles if s not in packs]
    by_cat = {r[0]: r[1] for r in conn.execute("SELECT category, COUNT(*) FROM specs GROUP BY category")}
    by_style = {r[0]: r[1] for r in conn.execute("SELECT style_pack, COUNT(*) FROM specs GROUP BY style_pack")}
    by_kind = {r[0]: r[1] for r in conn.execute("SELECT kind, COUNT(*) FROM batches GROUP BY kind")}
    (ROOT / "taxonomy.json").write_text(json.dumps({
        "style_packs": pack_order,
        "counts": {
            "specs": conn.execute("SELECT COUNT(*) FROM specs").fetchone()[0],
            "batches": conn.execute("SELECT COUNT(*) FROM batches").fetchone()[0],
            "by_category": {k: by_cat[k] for k in sorted(by_cat)},
            "by_style": {s: by_style.get(s, 0) for s in pack_order},
            "by_kind": {k: by_kind[k] for k in sorted(by_kind)},
        },
        "shard_rule": "A worker started with --shard N --shards S claims pending batches where COALESCE(queue_pos, batch_index) % S == N.",
        "default_shards": 4,
    }, indent=2) + "\n")


def insert_rows(conn, specs: list[dict], batches: list[dict], all_pack_ids: list[str]) -> None:
    conn.execute("BEGIN IMMEDIATE")
    existing_ids = {r[0] for r in conn.execute("SELECT batch_id FROM batches")}
    existing_specs = {r[0] for r in conn.execute("SELECT spec_id FROM specs")}
    overlap_b = [b["batch_id"] for b in batches if b["batch_id"] in existing_ids]
    overlap_s = [s["spec_id"] for s in specs if s["spec_id"] in existing_specs]
    if overlap_b or overlap_s:
        conn.rollback()
        raise RuntimeError(
            f"refusing to insert; {len(overlap_b)} batch_id and {len(overlap_s)} spec_id collisions"
        )
    conn.executemany(
        """
        INSERT INTO batches(batch_index, batch_id, kind, grid_w, grid_h, n_cells,
                            style_pack, category, prompt, negative, aspect_ratio,
                            filename_hint, status, queue_pos, genre)
        VALUES (:batch_index, :batch_id, :kind, :grid_w, :grid_h, :n_cells,
                :style_pack, :category, :prompt, :negative, :aspect_ratio,
                :filename_hint, :status, :queue_pos, :genre)
        """,
        [{k: b[k] for k in (
            "batch_index", "batch_id", "kind", "grid_w", "grid_h", "n_cells",
            "style_pack", "category", "prompt", "negative", "aspect_ratio",
            "filename_hint", "status", "queue_pos", "genre",
        )} for b in batches],
    )
    rows = []
    for s in specs:
        rec = dict(s)
        rec["tags"] = json.dumps(s["tags"])
        rows.append(rec)
    conn.executemany(
        """
        INSERT INTO specs(spec_index, spec_id, batch_id, cell_index, category, subcategory,
                          subject, variant, style_pack, tags, description, prompt, negative,
                          style_prefix, target_w, target_h, tileable, perspective,
                          pivot_x, pivot_y, has_alpha_intended)
        VALUES (:spec_index, :spec_id, :batch_id, :cell_index, :category, :subcategory,
                :subject, :variant, :style_pack, :tags, :description, :prompt, :negative,
                :style_prefix, :target_w, :target_h, :tileable, :perspective,
                :pivot_x, :pivot_y, :has_alpha_intended)
        """,
        rows,
    )
    set_meta(conn, "license", LICENSE)
    set_meta(conn, "style_packs", all_pack_ids)
    conn.commit()


def summarize(specs, batches) -> dict:
    return {
        "specs": len(specs),
        "batches": len(batches),
        "by_style": {st: sum(1 for b in batches if b["style_pack"] == st)
                     for st in sorted({b["style_pack"] for b in batches})},
        "by_category": {c: sum(1 for b in batches if b["category"] == c)
                        for c in sorted({b["category"] for b in batches})},
        "by_kind": {k: sum(1 for b in batches if b["kind"] == k)
                    for k in sorted({b["kind"] for b in batches})},
        "queue_pos": {
            "min": min(b["queue_pos"] for b in batches),
            "max": max(b["queue_pos"] for b in batches),
        },
        "batch_index": {
            "min": min(b["batch_index"] for b in batches),
            "max": max(b["batch_index"] for b in batches),
        },
        "spec_index": {
            "min": min(s["spec_index"] for s in specs),
            "max": max(s["spec_index"] for s in specs),
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Append new style packs to the live queue")
    ap.add_argument("--dry-build", action="store_true", help="Build in memory and print counts; do not write the DB")
    ap.add_argument("--skip-backup", action="store_true", help="Skip the sqlite backup (already taken this run)")
    args = ap.parse_args()

    packs = json.loads(PACKS_PATH.read_text())
    missing_defs = [s for s in NEW_STYLE_IDS if s not in packs]
    if missing_defs:
        print(json.dumps({"error": "style packs missing from style_packs.json", "missing": missing_defs}, indent=2))
        sys.exit(2)

    conn = init_db()
    already = {r[0] for r in conn.execute("SELECT DISTINCT style_pack FROM batches")}
    to_add = [s for s in NEW_STYLE_IDS if s not in already]
    if not to_add:
        print(json.dumps({"error": "new style packs already present in batches; nothing to append", "styles": NEW_STYLE_IDS}, indent=2))
        conn.close()
        sys.exit(1)

    start_batch = int(conn.execute("SELECT COALESCE(MAX(batch_index), -1) FROM batches").fetchone()[0]) + 1
    start_spec = int(conn.execute("SELECT COALESCE(MAX(spec_index), -1) FROM specs").fetchone()[0]) + 1
    start_pos = int(conn.execute("SELECT COALESCE(MAX(queue_pos), -1) FROM batches WHERE queue_pos IS NOT NULL").fetchone()[0]) + 1
    # Keep new work after the live non-negative queue, even if a parked negative max somehow won
    start_pos = max(
        start_pos,
        int(conn.execute("SELECT COALESCE(MAX(queue_pos), -1) FROM batches WHERE queue_pos >= 0").fetchone()[0]) + 1,
    )

    specs, batches = build_wave({k: packs[k] for k in to_add}, to_add)
    reindex(batches, specs, start_batch, start_spec)
    assign_queue_pos(batches, start_pos)
    summary = summarize(specs, batches)

    if args.dry_build:
        conn.close()
        print(json.dumps({"dry_build": True, "styles": to_add, **summary}, indent=2))
        return

    backup_path = None
    if not args.skip_backup:
        backup_path = backup_db(ROOT / "assets.db")

    try:
        insert_rows(conn, specs, batches, list(packs.keys()))
    except Exception:
        conn.close()
        raise

    # Append exports; do not rewrite historical jsonl.
    append_jsonl(ROOT / "specs.jsonl", [
        {k: s[k] for k in s} | {"tags": s["tags"]}
        for s in specs
    ])
    prompt_recs = []
    for b in batches:
        rec = {k: b[k] for k in b if k != "rows"}
        rec["spec_ids"] = [r["spec_id"] for r in b["rows"]]
        rec["subjects"] = [f"{r['subject']}/{r['variant']}" for r in b["rows"]]
        prompt_recs.append(rec)
    append_jsonl(ROOT / "prompts.jsonl", prompt_recs)
    write_taxonomy(conn, packs)
    progress = snapshot_progress(conn)

    pending_by_style = [
        {"style_pack": r[0], "n": r[1]}
        for r in conn.execute(
            "SELECT style_pack, COUNT(*) FROM batches WHERE status='pending' GROUP BY style_pack ORDER BY style_pack"
        )
    ]
    # Simulate claim visibility for a few shard layouts without claiming.
    claim_preview = {}
    for shards in (4, 8, 12, 16):
        per = {}
        for shard in range(min(4, shards)):
            n = conn.execute(
                """
                SELECT COUNT(*) FROM batches
                 WHERE status='pending' AND (COALESCE(queue_pos, batch_index) % ?)=?
                   AND style_pack IN ({})
                """.format(",".join("?" * len(to_add))),
                (shards, shard, *to_add),
            ).fetchone()[0]
            per[str(shard)] = n
        claim_preview[str(shards)] = per

    conn.close()
    print(json.dumps({
        "inserted": True,
        "backup": str(backup_path) if backup_path else None,
        "styles": to_add,
        **summary,
        "pending_by_style": pending_by_style,
        "new_claim_preview_first_shards": claim_preview,
        "progress": {
            "pending_batches": progress.get("pending_batches"),
            "claimed_batches": progress.get("claimed_batches"),
            "ingested_batches": progress.get("ingested_batches"),
            "batch_total": progress.get("batch_total"),
            "spec_total": progress.get("spec_total"),
            "ingested_count": progress.get("ingested_count"),
        },
    }, indent=2))


if __name__ == "__main__":
    main()
