#!/usr/bin/env python3
"""Append a new wave of asset categories to the live queue without touching existing rows.

Builds specs/batches for categories that are not yet in the batches table, across
every style pack in style_packs.json, then inserts them in one short BEGIN IMMEDIATE
transaction. queue_pos continues after the current max and is round-robin interleaved
across category × style × genre.

Does not claim work, does not rebuild the DB, does not update existing rows,
and does not call GenerateImage.

    nice -n 15 python3 /workspace/game-assets/append_categories.py
    nice -n 15 python3 /workspace/game-assets/append_categories.py --dry-build
"""
from __future__ import annotations

import argparse
import json
import sys

from append_styles import (
    append_jsonl,
    assign_queue_pos,
    backup_db,
    insert_rows,
    reindex,
    summarize,
    write_taxonomy,
)
from build_specs import (
    PACKS_PATH,
    perspective_for,
    pivot_for,
    subject_label,
    tags_for,
)
from db import ROOT, init_db, snapshot_progress

NEW_CATEGORIES = [
    "vehicles",
    "buildings",
    "furniture",
    "foliage",
    "creatures",
    "portraits",
    "weapons",
    "decals",
    "markers",
    "terrain",
]

# --- vehicles ---
VEHICLE_MOUNTS = [
    "riding_horse", "pack_mule", "desert_camel", "trail_pony",
    "riding_elk", "pack_yak", "saddled_lizard", "wool_llama",
]
VEHICLE_LAND = [
    "travel_wagon", "market_barrow", "steam_tricycle", "scooter_cycle",
    "rickshaw", "snow_sledge", "hand_trolley", "orchard_cart",
]
VEHICLE_LARGE = [
    ("sky_barge", "air"),
    ("gyrocopter", "air"),
    ("trade_galleon", "water"),
    ("river_ferry", "water"),
    ("clockwork_locomotive", "heavy"),
    ("siege_tower", "heavy"),
]

# --- buildings (exterior singles) ---
BUILDINGS = [
    ("village_cottage", "dwelling"),
    ("stilt_house", "dwelling"),
    ("thatched_longhouse", "dwelling"),
    ("hill_windmill", "work"),
    ("timber_granary", "work"),
    ("watermill", "work"),
    ("covered_market", "work"),
    ("coastal_lighthouse", "landmark"),
    ("stone_watchtower", "landmark"),
    ("roadside_inn", "civic"),
    ("hillside_shrine", "civic"),
    ("gatehouse", "civic"),
]

# --- furniture ---
FURNITURE_SMALL = [
    "footstool", "nightstand", "coat_rack", "wall_mirror",
    "washbasin", "towel_rail", "umbrella_stand", "folding_screen",
    "spice_shelf", "rug_roll", "hanging_planter", "oil_lamp_stand",
    "jewelry_casket", "laundry_basket", "fire_irons", "coat_pegs",
    "boot_tray", "candle_sconce", "wall_clock", "key_hooks",
    "writing_slope", "sewing_basket", "tea_tray", "floor_cushion",
    "window_box", "broom_set", "hat_stand", "letter_rack",
    "soap_dish", "incense_shelf", "boot_jack", "quilt_rack",
]
FURNITURE_MEDIUM = [
    "dining_table", "armchair", "rocking_chair", "chaise_lounge",
    "tall_bookshelf", "sideboard", "kitchen_hutch", "longcase_clock",
]
FURNITURE_LARGE = ["four_poster_bed", "tall_wardrobe", "stone_hearth"]

# --- foliage ---
FOLIAGE_SMALL = [
    "fern_frond", "potted_herb", "climbing_ivy", "cactus_pad",
    "lily_pad", "cattail", "dandelion", "sunflower",
    "tulip_cluster", "moss_clump", "clover_patch", "reed_bundle",
    "succulent_rosette", "hanging_moss", "flower_box", "berry_sprig",
    "vine_coil", "thistle", "lavender_bundle", "daisy_cluster",
    "bamboo_shoot", "kelp_frond", "aloe_rosette", "poppy_cluster",
    "wheat_stalk", "corn_stalk", "pumpkin_vine", "tea_bush",
    "pepper_plant", "basil_pot", "wild_rose", "fern_basket",
]
FOLIAGE_MEDIUM = ["round_hedge", "flowering_shrub", "berry_thicket", "ornamental_topiary"]
FOLIAGE_TREES = [
    "copper_beech", "lantern_tree", "baobab",
    "cedar_spire", "mangrove_clump", "twisted_olive",
]

# --- creatures (non-hostile) ---
CREATURE_ANIMALS = [
    "house_cat", "herding_dog", "backyard_chicken", "farm_duck",
    "spotted_fawn", "river_otter", "hearth_fox", "barn_owl",
    "garden_hare", "pygmy_goat", "capybara", "meadow_lark",
    "hedgehog", "tortoise", "alpaca", "pond_carp",
]
CREATURE_VIEWS = ["idle_front", "idle_side"]
CREATURE_SMALL = [
    "song_sparrow", "barn_swallow", "garden_moth", "honeybee",
    "tree_frog", "field_mouse", "tide_hermit", "garden_snail",
]
CREATURE_LARGE = ["woolly_aurochs", "river_strider", "moss_mammoth", "desert_walker"]

# --- portraits (original busts, not real people) ---
PORTRAITS = [
    ("village_baker", "civilian"),
    ("ferry_captain", "civilian"),
    ("orchard_hand", "civilian"),
    ("tea_host", "civilian"),
    ("lamp_lighter", "civilian"),
    ("well_keeper", "civilian"),
    ("net_mender", "civilian"),
    ("path_marker_npc", "civilian"),
    ("market_weaver", "trade"),
    ("dye_merchant", "trade"),
    ("seed_vendor", "trade"),
    ("spice_runner", "trade"),
    ("sail_patcher", "trade"),
    ("broth_cook", "trade"),
    ("kite_maker", "trade"),
    ("river_pilot", "trade"),
    ("night_watch", "watch"),
    ("bell_keeper", "watch"),
    ("dune_guide", "watch"),
    ("ice_cutter", "watch"),
    ("star_warden", "watch"),
    ("gate_sentry", "watch"),
    ("harbor_lookout", "watch"),
    ("trail_ranger", "watch"),
    ("map_apprentice", "craft"),
    ("kiln_worker", "craft"),
    ("roof_tiler", "craft"),
    ("herb_runner", "craft"),
    ("ink_apprentice", "craft"),
    ("mask_carver", "craft"),
    ("brass_tuner", "craft"),
    ("stone_setter", "craft"),
]

# --- full-size weapons (not inventory icons) ---
WEAPONS_MID = [
    "boarding_cutlass", "hunting_longbow", "repeating_crossbow", "war_scythe",
    "boarding_pike", "grappling_hook", "wind_javelin", "tower_pavise",
    "riding_lance", "boarding_axe", "short_recurve", "flanged_mace",
    "ceremonial_halberd", "battle_fan", "chained_dart", "bronze_kopis",
]
WEAPONS_LARGE = ["siege_ballista", "field_trebuchet", "battering_ram", "shipboard_culverin"]

# --- decals (blood-free) ---
DECAL_GROUND = [
    "boot_print_left", "boot_print_right", "bare_footprint", "paw_print",
    "hoof_print", "claw_scratch", "wagon_rut_dash", "wheel_track",
    "slither_trail", "tire_tread", "crampon_print", "cane_tip_dot",
    "staff_butt_print", "jump_dust", "skid_mark", "drag_line",
]
DECAL_SCORCH = [
    "soot_smear", "scorch_ring", "ash_pile", "ember_spot",
    "smoke_stain", "heat_score", "weld_burn", "candle_wax_drip",
    "torch_streak", "chimney_soot", "steam_ring", "frost_bloom",
    "water_ring", "oil_spot", "ink_splatter", "mud_splatter",
]
DECAL_NATURE = [
    "fallen_leaf_decal", "petal_scatter", "pine_needle_scatter", "pollen_dust",
    "dripping_water", "wet_paw", "moss_stain", "lichen_patch",
    "salt_crust", "sand_ripple_decal", "snow_melt_ring", "seed_husks",
    "feather_drop", "puddle_outline", "dew_spots", "cobweb_corner",
]
DECAL_WEAR = [
    "cracked_plaster", "chipped_paint", "rust_streak", "scratched_metal",
    "worn_stone", "peeling_poster_edge", "nail_hole", "bolt_shadow",
    "drip_streak", "scuff_arc", "dent_ring", "chalk_arrow",
    "water_damage", "sun_fade_patch", "torn_paper_corner", "tape_residue",
]
DECAL_TILEABLE = ["repeating_scorch", "repeating_moss", "repeating_cracks", "repeating_mud"]

# --- map markers ---
MARKER_POI = [
    "inn_marker", "shrine_marker", "market_marker", "fountain_marker",
    "well_marker", "academy_marker", "workshop_marker", "harbor_marker",
    "camp_marker", "ruins_marker", "cave_marker", "overlook_marker",
    "garden_marker", "bath_marker", "tower_marker", "gate_marker",
]
MARKER_TRAVEL = [
    "path_dot", "fork_marker", "bridge_marker", "ferry_marker",
    "pass_marker", "trailhead_marker", "plain_pennant", "anchor_marker",
    "balloon_dock_marker", "tunnel_marker", "stairs_marker", "dock_marker",
    "ford_marker", "switchback_marker", "milepost_marker", "compass_rose_small",
]
MARKER_RESOURCE = [
    "ore_marker", "timber_marker", "fish_shoal_marker", "spring_marker",
    "herb_marker", "quarry_marker", "clay_pit_marker", "beehive_marker",
    "orchard_marker", "grain_marker", "crystal_marker", "salvage_marker",
    "wind_site_marker", "hunt_ground_marker", "salt_marker", "peat_marker",
]
MARKER_STATUS = [
    "party_pin", "ally_pin", "task_pin", "player_start",
    "remembered_pin", "danger_pin", "quiet_pin", "locked_pin",
    "unlocked_pin", "rest_pin", "trade_pin", "story_pin",
    "craft_pin", "help_pin", "home_pin", "gathering_pin",
]
MARKER_LANDMARK = [
    "capital_marker", "fortress_marker", "lighthouse_marker", "mountain_peak_marker",
    "volcano_marker", "desert_oasis_marker", "glacier_marker", "canyon_marker",
    "archipelago_marker", "forest_heart_marker", "swamp_marker", "crater_marker",
    "sky_dock_marker", "clocktower_marker", "observatory_marker", "great_statue_marker",
]

# --- terrain features ---
TERRAIN = [
    ("boulder_cluster", "rock"),
    ("sandstone_arch", "rock"),
    ("hanging_cliff", "rock"),
    ("mesa_stack", "landform"),
    ("cave_mouth", "landform"),
    ("steam_geyser", "landform"),
    ("dry_wash", "landform"),
    ("ice_floe", "landform"),
    ("rope_bridge", "crossing"),
    ("stone_arch_bridge", "crossing"),
    ("wooden_pier", "crossing"),
    ("ancient_stairs", "crossing"),
]


def _expect(name: str, seq, n: int) -> None:
    if len(seq) != n:
        raise RuntimeError(f"{name} has {len(seq)} items, expected {n}")


def validate_catalogs() -> None:
    _expect("VEHICLE_MOUNTS", VEHICLE_MOUNTS, 8)
    _expect("VEHICLE_LAND", VEHICLE_LAND, 8)
    _expect("VEHICLE_LARGE", VEHICLE_LARGE, 6)
    _expect("BUILDINGS", BUILDINGS, 12)
    _expect("FURNITURE_SMALL", FURNITURE_SMALL, 32)
    _expect("FURNITURE_MEDIUM", FURNITURE_MEDIUM, 8)
    _expect("FURNITURE_LARGE", FURNITURE_LARGE, 3)
    _expect("FOLIAGE_SMALL", FOLIAGE_SMALL, 32)
    _expect("FOLIAGE_MEDIUM", FOLIAGE_MEDIUM, 4)
    _expect("FOLIAGE_TREES", FOLIAGE_TREES, 6)
    _expect("CREATURE_ANIMALS", CREATURE_ANIMALS, 16)
    _expect("CREATURE_SMALL", CREATURE_SMALL, 8)
    _expect("CREATURE_LARGE", CREATURE_LARGE, 4)
    _expect("PORTRAITS", PORTRAITS, 32)
    _expect("WEAPONS_MID", WEAPONS_MID, 16)
    _expect("WEAPONS_LARGE", WEAPONS_LARGE, 4)
    _expect("DECAL_GROUND", DECAL_GROUND, 16)
    _expect("DECAL_SCORCH", DECAL_SCORCH, 16)
    _expect("DECAL_NATURE", DECAL_NATURE, 16)
    _expect("DECAL_WEAR", DECAL_WEAR, 16)
    _expect("DECAL_TILEABLE", DECAL_TILEABLE, 4)
    _expect("MARKER_POI", MARKER_POI, 16)
    _expect("MARKER_TRAVEL", MARKER_TRAVEL, 16)
    _expect("MARKER_RESOURCE", MARKER_RESOURCE, 16)
    _expect("MARKER_STATUS", MARKER_STATUS, 16)
    _expect("MARKER_LANDMARK", MARKER_LANDMARK, 16)
    _expect("TERRAIN", TERRAIN, 12)


def build_wave(packs: dict, style_ids: list[str]) -> tuple[list[dict], list[dict]]:
    validate_catalogs()
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

    portrait_note = (
        "Original stylized bust portrait, invented face, not a real person, "
        "not a celebrity, and not a copyrighted character. Head and shoulders only."
    )
    weapon_note = "Full-size in-world weapon sprite, not a tiny inventory icon, complete silhouette, no hands."
    vehicle_note = "Complete vehicle or mount, empty saddle if a mount, no rider, no logos."
    building_note = "Full exterior only, no interior cutaway, no logos, no readable signage."
    creature_note = "Friendly non-hostile animal, original design, not a copyrighted character."

    for style in style_ids:
        if style not in packs:
            raise KeyError(f"missing style pack: {style}")
        for subj in VEHICLE_MOUNTS:
            add(style, "vehicles", "mount", subj, "idle", kind_hint="sheet_2x2", extra_desc=vehicle_note)
        for subj in VEHICLE_LAND:
            add(style, "vehicles", "land", subj, "idle", kind_hint="sheet_2x2", extra_desc=vehicle_note)
        for subj, sub in VEHICLE_LARGE:
            add(style, "vehicles", sub, subj, "idle", kind_hint="single", extra_desc=vehicle_note)

        for subj, sub in BUILDINGS:
            add(style, "buildings", sub, subj, "exterior", kind_hint="single", extra_desc=building_note)

        for subj in FURNITURE_SMALL:
            add(style, "furniture", "small", subj, "plain", kind_hint="sheet_4x4")
        for subj in FURNITURE_MEDIUM:
            add(style, "furniture", "medium", subj, "plain", kind_hint="sheet_2x2")
        for subj in FURNITURE_LARGE:
            add(style, "furniture", "large", subj, "plain", kind_hint="single")

        for subj in FOLIAGE_SMALL:
            add(style, "foliage", "plant", subj, "plain", kind_hint="sheet_4x4")
        for subj in FOLIAGE_MEDIUM:
            add(style, "foliage", "bush", subj, "plain", kind_hint="sheet_2x2")
        for subj in FOLIAGE_TREES:
            add(style, "foliage", "tree", subj, "plain", kind_hint="single")

        for subj in CREATURE_ANIMALS:
            for var in CREATURE_VIEWS:
                add(style, "creatures", "animal", subj, var, kind_hint="sheet_4x4", extra_desc=creature_note)
        for subj in CREATURE_SMALL:
            add(style, "creatures", "small", subj, "idle", kind_hint="sheet_2x2", extra_desc=creature_note)
        for subj in CREATURE_LARGE:
            add(style, "creatures", "large", subj, "idle", kind_hint="single", extra_desc=creature_note)

        for subj, sub in PORTRAITS:
            add(style, "portraits", sub, subj, "bust", kind_hint="sheet_2x2", extra_desc=portrait_note)

        for subj in WEAPONS_MID:
            add(style, "weapons", "handheld", subj, "upright", kind_hint="sheet_2x2", extra_desc=weapon_note)
        for subj in WEAPONS_LARGE:
            add(style, "weapons", "siege", subj, "upright", kind_hint="single", extra_desc=weapon_note)

        for subj in DECAL_GROUND:
            add(style, "decals", "ground", subj, "plain", kind_hint="sheet_4x4")
        for subj in DECAL_SCORCH:
            add(style, "decals", "scorch", subj, "plain", kind_hint="sheet_4x4")
        for subj in DECAL_NATURE:
            add(style, "decals", "nature", subj, "plain", kind_hint="sheet_4x4")
        for subj in DECAL_WEAR:
            add(style, "decals", "wear", subj, "plain", kind_hint="sheet_4x4")
        for subj in DECAL_TILEABLE:
            add(style, "decals", "tileable", subj, "repeat", tileable=True, kind_hint="tile_single")

        for subj in MARKER_POI:
            add(style, "markers", "poi", subj, "plain", kind_hint="sheet_4x4")
        for subj in MARKER_TRAVEL:
            add(style, "markers", "travel", subj, "plain", kind_hint="sheet_4x4")
        for subj in MARKER_RESOURCE:
            add(style, "markers", "resource", subj, "plain", kind_hint="sheet_4x4")
        for subj in MARKER_STATUS:
            add(style, "markers", "status", subj, "plain", kind_hint="sheet_4x4")
        for subj in MARKER_LANDMARK:
            add(style, "markers", "landmark", subj, "plain", kind_hint="sheet_2x2")

        for subj, sub in TERRAIN:
            add(style, "terrain", sub, subj, "plain", kind_hint="single")

    batches: list[dict] = []
    grouped: dict[tuple, list[dict]] = {}
    singles: list[dict] = []

    for row in raw:
        hint = row["kind_hint"]
        if hint in {"sheet_4x4", "sheet_2x2"}:
            key = (row["style_pack"], row["category"], row["subcategory"], row["variant"], hint)
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
            names.append(
                f"row {len(names)//grid_w+1} col {len(names)%grid_w+1}: leave this cell empty, only magenta"
            )
        listing = "; ".join(names)
        chroma = pack["chroma"]
        return (
            f"{title} arranged in a regular {grid_w} by {grid_h} grid on a flat solid magenta background {chroma}. "
            f"Each item is centered in its own cell with wide empty magenta margins on all four sides, "
            f"a thick magenta gutter between every cell, nothing crossing cell borders, and no item touching a neighbor or the cell edge. "
            f"No labels, no numbers, no captions, no watermark. {cell_desc} "
            f"{pack['style_prefix']}. Cells, in row-major order: {listing}."
        )

    CELL = {
        "vehicles": "Each cell is one complete vehicle or mount, wheels or feet toward the bottom, no rider, no environment, no logos.",
        "buildings": "Each cell is one complete building exterior, sitting on an implied ground but with no visible floor plane.",
        "furniture": "Each cell is one piece of furniture, standing upright, feet toward the bottom of the cell, no room set.",
        "foliage": "Each cell is one plant, bush or tree, roots or pot toward the bottom, no landscape.",
        "creatures": "Each cell is one friendly original animal, full body, standing or perched, not a famous character.",
        "portraits": "Each cell is a different original stylized bust, head and shoulders, invented face, not a real person.",
        "weapons": "Each cell is one full-size weapon sprite, complete silhouette, not an inventory icon, no hands, no logos.",
        "decals": "Each cell is one flat game decal or stain, isolated, blood-free, no typography, ready to overlay.",
        "markers": "Each cell is one simple map or world-map marker, readable at small size, no national flags, no logos, no text.",
        "terrain": "Each cell is one terrain feature, complete and readable, no characters, no logos.",
    }

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
        style, category, subcategory, variant, hint = key
        pack = packs[style]
        title = f"A grid of {pack['title']} game {category} ({subject_label(subcategory)})"
        cell = CELL[category]
        if hint == "sheet_4x4":
            title = f"A 4x4 grid of sixteen {pack['title']} game {category} ({subject_label(subcategory)})"
            for group in chunk(rows, 16):
                add_batch(
                    "sheet", group, 4, 4, "1:1",
                    lambda p, rs, w, h, t=title, c=cell: sheet_prompt(p, rs, w, h, t, c),
                )
        else:
            title = f"A 2x2 grid of four {pack['title']} game {category} ({subject_label(subcategory)})"
            for group in chunk(rows, 4):
                add_batch(
                    "sheet", group, 2, 2, "1:1",
                    lambda p, rs, w, h, t=title, c=cell: sheet_prompt(p, rs, w, h, t, c),
                )

    for row in singles:
        pack = packs[row["style_pack"]]
        chroma = pack["chroma"]
        label = f"{subject_label(row['subject'])}, {subject_label(row['variant'])}"
        if row["tileable"] or row["kind_hint"] == "tile_single":
            prompt = (
                f"A seamless tileable {label} surface decal for a 2D game, even lighting, "
                f"the pattern must repeat cleanly on all four edges, no objects, no characters, no text, "
                f"blood-free, edge-to-edge surface only. {pack['style_prefix']}."
            )
            aspect, kind = "1:1", "tile"
        else:
            prompt = (
                f"A single {pack['title']} game {row['category']}: {label}, centered, full object visible, "
                f"standing on an implied ground but with a flat solid magenta background {chroma}, "
                f"no floor plane, no text, no logos. {row['description']} {pack['style_prefix']}."
            )
            aspect, kind = "1:1", "single"
        add_batch(kind, [row], 1, 1, aspect, lambda p, rs, w, h, pr=prompt: pr)

    for s in specs:
        s.pop("kind_hint", None)
    return specs, batches


def main() -> None:
    ap = argparse.ArgumentParser(description="Append new categories to the live queue")
    ap.add_argument("--dry-build", action="store_true", help="Build in memory and print counts; do not write the DB")
    ap.add_argument("--skip-backup", action="store_true", help="Skip the sqlite backup (already taken this run)")
    args = ap.parse_args()

    packs = json.loads(PACKS_PATH.read_text())
    missing_sizes = [
        sid for sid, p in packs.items()
        if any(c not in p.get("sizes", {}) for c in NEW_CATEGORIES)
    ]
    if missing_sizes:
        print(json.dumps({
            "error": "style packs missing sizes for new categories",
            "packs": missing_sizes,
            "needed": NEW_CATEGORIES,
        }, indent=2))
        sys.exit(2)

    conn = init_db()
    already = {r[0] for r in conn.execute("SELECT DISTINCT category FROM batches")}
    overlap = [c for c in NEW_CATEGORIES if c in already]
    if overlap:
        print(json.dumps({
            "error": "new categories already present in batches; nothing to append",
            "already": overlap,
            "categories": NEW_CATEGORIES,
        }, indent=2))
        conn.close()
        sys.exit(1)

    start_batch = int(conn.execute("SELECT COALESCE(MAX(batch_index), -1) FROM batches").fetchone()[0]) + 1
    start_spec = int(conn.execute("SELECT COALESCE(MAX(spec_index), -1) FROM specs").fetchone()[0]) + 1
    start_pos = max(
        int(conn.execute("SELECT COALESCE(MAX(queue_pos), -1) FROM batches WHERE queue_pos IS NOT NULL").fetchone()[0]) + 1,
        int(conn.execute("SELECT COALESCE(MAX(queue_pos), -1) FROM batches WHERE queue_pos >= 0").fetchone()[0]) + 1,
    )

    style_ids = list(packs.keys())
    specs, batches = build_wave(packs, style_ids)
    reindex(batches, specs, start_batch, start_spec)
    assign_queue_pos(batches, start_pos)
    summary = summarize(specs, batches)

    if args.dry_build:
        conn.close()
        print(json.dumps({"dry_build": True, "categories": NEW_CATEGORIES, "styles": style_ids, **summary}, indent=2))
        return

    backup_path = None
    if not args.skip_backup:
        backup_path = backup_db(ROOT / "assets.db", label="categories")

    try:
        insert_rows(conn, specs, batches, list(packs.keys()))
    except Exception:
        conn.close()
        raise

    append_jsonl(ROOT / "specs.jsonl", [{k: s[k] for k in s} for s in specs])
    prompt_recs = []
    for b in batches:
        rec = {k: b[k] for k in b if k != "rows"}
        rec["spec_ids"] = [r["spec_id"] for r in b["rows"]]
        rec["subjects"] = [f"{r['subject']}/{r['variant']}" for r in b["rows"]]
        prompt_recs.append(rec)
    append_jsonl(ROOT / "prompts.jsonl", prompt_recs)
    write_taxonomy(conn, packs)
    progress = snapshot_progress(conn)

    pending_by_cat = [
        {"category": r[0], "n": r[1]}
        for r in conn.execute(
            "SELECT category, COUNT(*) FROM batches WHERE status='pending' GROUP BY category ORDER BY category"
        )
    ]
    new_pending = [
        {"category": r[0], "n": r[1]}
        for r in conn.execute(
            "SELECT category, COUNT(*) FROM batches WHERE status='pending' AND category IN ({}) GROUP BY category ORDER BY category".format(
                ",".join("?" * len(NEW_CATEGORIES))
            ),
            NEW_CATEGORIES,
        )
    ]
    claim_preview = {}
    for shards in (4, 8, 12, 16):
        per = {}
        for shard in range(min(4, shards)):
            n = conn.execute(
                """
                SELECT COUNT(*) FROM batches
                 WHERE status='pending' AND (COALESCE(queue_pos, batch_index) % ?)=?
                   AND category IN ({})
                """.format(",".join("?" * len(NEW_CATEGORIES))),
                (shards, shard, *NEW_CATEGORIES),
            ).fetchone()[0]
            per[str(shard)] = n
        claim_preview[str(shards)] = per

    conn.close()
    print(json.dumps({
        "inserted": True,
        "backup": str(backup_path) if backup_path else None,
        "categories": NEW_CATEGORIES,
        "styles": style_ids,
        **summary,
        "pending_by_category": pending_by_cat,
        "pending_new_categories": new_pending,
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
