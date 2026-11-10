#!/usr/bin/env python3
"""Build a deterministic combinatorial spec + batch queue (thousands of assets)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from db import LICENSE, ROOT, connect, init_db, set_meta, snapshot_progress

PACKS_PATH = ROOT / "style_packs.json"

# --- taxonomy (singular OGA-style tags; original subjects only; no IP) ---

ICON_WEAPONS = [
    "iron_sword", "longsword", "dagger", "battle_axe", "war_hammer", "wooden_bow",
    "crossbow", "spear", "halberd", "oak_staff", "crystal_wand", "spiked_mace",
    "scimitar", "flail", "sling", "throwing_knife", "trident", "wooden_club",
    "rapier", "shortbow",
]
ICON_ARMOR = [
    "leather_helm", "iron_helm", "plate_helm", "leather_chest", "chain_shirt",
    "plate_chest", "leather_boots", "iron_boots", "leather_glove", "iron_gauntlet",
    "wooden_shield", "iron_shield", "tower_shield", "travel_cloak", "mage_robe",
]
ICON_POTIONS = [
    "health_potion", "mana_potion", "stamina_potion", "poison_vial", "antidote",
    "invisibility_potion", "strength_elixir", "fire_resist_potion", "ice_resist_potion",
    "luck_potion",
]
ICON_FOOD = [
    "red_apple", "loaf_of_bread", "cheese_wheel", "cooked_meat", "fresh_fish",
    "forest_mushroom", "berry_cluster", "honey_jar", "stew_bowl", "carrot",
]
ICON_TOOLS = [
    "pickaxe", "hatchet", "smith_hammer", "fishing_rod", "shovel", "sickle",
    "coil_of_rope", "oil_lantern", "wood_torch", "compass",
]
ICON_VALUABLES = [
    "gold_coin", "silver_coin", "gold_bar", "cut_ruby", "cut_sapphire",
    "cut_emerald", "cut_amethyst", "pearl", "plain_ring", "bead_necklace",
    "simple_crown", "iron_key", "brass_key", "lockpick", "folded_map",
    "sealed_scroll", "bound_book", "wax_letter",
]
ICON_MISC = [
    "backpack", "belt_pouch", "empty_bottle", "raw_crystal", "animal_bone",
    "feather", "herb_bundle", "round_bomb", "arrow_bundle", "quiver",
]
ICON_VARIANTS = ["plain", "ornate", "worn"]

TILE_FLOORS = [
    "grass", "tall_grass", "dirt", "dirt_path", "cobblestone", "stone_floor",
    "wood_plank", "sand", "gravel", "snow", "ice", "shallow_water", "deep_water",
    "lava", "mud", "mossy_stone", "brick_floor", "dungeon_stone", "metal_plate",
    "crystal_floor", "fallen_leaves", "flower_meadow", "farm_soil", "carpet",
]
TILE_WALLS = [
    "stone_wall", "brick_wall", "wood_wall", "cave_wall", "metal_wall",
    "hedge", "wood_fence", "windowed_wall",
]
TILE_VARIANTS = ["base", "variant_a", "variant_b"]

PROPS = [
    ("chest", "closed"), ("chest", "open"),
    ("barrel", "plain"), ("crate", "plain"),
    ("clay_vase", "plain"), ("cooking_pot", "plain"),
    ("wooden_table", "plain"), ("wooden_chair", "plain"),
    ("simple_bed", "plain"), ("bookshelf", "plain"),
    ("anvil", "plain"), ("campfire", "lit"),
    ("canvas_tent", "plain"), ("signpost", "blank"),
    ("gravestone", "plain"), ("stone_well", "plain"),
    ("small_fountain", "plain"), ("lamp_post", "lit"),
    ("candle", "lit"), ("cauldron", "plain"),
    ("stone_altar", "plain"), ("wooden_throne", "plain"),
    ("mushroom_cluster", "plain"), ("oak_tree", "plain"),
    ("pine_tree", "plain"), ("round_bush", "plain"),
    ("small_rock", "plain"), ("boulder", "plain"),
    ("crystal_formation", "plain"), ("hand_cart", "plain"),
    ("scarecrow", "plain"), ("mailbox", "plain"),
]
# large props generated as singles
LARGE_PROPS = {"oak_tree", "pine_tree", "canvas_tent", "small_fountain", "stone_well", "boulder"}

CHARACTERS = [
    "wanderer", "knight", "archer", "mage", "cleric", "rogue", "merchant",
    "blacksmith", "farmer", "miner", "sailor", "scholar", "bard", "ranger",
    "alchemist", "child_villager", "village_elder", "town_guard",
]
CHAR_VIEWS = ["front", "three_quarter", "side", "back"]

ENEMIES = [
    "green_slime", "cave_bat", "forest_spider", "striped_snake", "grey_wolf",
    "sewer_rat", "pale_ghost", "bone_skeleton", "forest_goblin", "tusked_orc",
    "walking_mushroom", "living_armor", "small_imp", "willow_wisp",
    "scout_drone", "armored_beetle", "cave_jellyfish", "shadow_blob",
    "stone_golem", "fire_sprite",
]
ENEMY_VARIANTS = ["idle_front", "idle_side", "alert"]

UI_ITEMS = [
    ("button", "up"), ("button", "down"), ("button", "hover"), ("button", "disabled"),
    ("panel", "light"), ("panel", "dark"),
    ("frame", "simple"), ("frame", "ornate"),
    ("bar_track", "plain"), ("health_fill", "plain"), ("mana_fill", "plain"), ("xp_fill", "plain"),
    ("item_slot", "empty"), ("item_slot", "selected"),
    ("checkbox", "off"), ("checkbox", "on"),
    ("slider_track", "plain"), ("slider_knob", "plain"),
    ("icon_close", "plain"), ("icon_plus", "plain"),
    ("icon_inventory", "plain"), ("icon_settings", "plain"),
    ("icon_map", "plain"), ("icon_pause", "plain"), ("icon_play", "plain"),
    ("cursor", "pointer"), ("cursor", "sword"),
    ("tooltip", "plain"), ("tab", "active"), ("tab", "inactive"),
    ("scrollbar", "plain"), ("window_header", "plain"),
    ("dialogue_box", "plain"), ("nameplate", "plain"),
    ("minimap_frame", "plain"), ("icon_button", "blank"),
]

VFX = [
    "explosion", "smoke_puff", "spark_burst", "sword_slash", "impact_star",
    "heal_burst", "mana_sparkle", "flame_loop", "ice_burst", "lightning_arc",
    "poison_cloud", "level_up_burst", "dust_kick", "water_splash",
    "shield_hit", "magic_circle", "stun_stars", "confetti",
]
VFX_FRAMES = ["f1", "f2", "f3", "f4"]

BACKGROUNDS = [
    "forest_clearing", "mountain_valley", "desert_dunes", "snowy_peaks",
    "ocean_coast", "cave_interior", "dungeon_hall", "village_street",
    "tavern_interior", "castle_hall", "night_camp", "sci_fi_corridor",
    "star_field", "cozy_cottage", "misty_swamp", "volcanic_plain",
]
PARALLAX_BIOMES = ["forest", "mountains", "coast", "desert", "night_town"]
PARALLAX_LAYERS = ["sky", "far", "mid", "near"]


def subject_label(slug: str) -> str:
    return slug.replace("_", " ")


FEET_CATEGORIES = {
    "characters", "enemies", "props",
    "vehicles", "buildings", "furniture", "foliage", "creatures",
    "weapons", "terrain",
}

CANONICAL_CATEGORIES = [
    "icons", "tiles", "props", "characters", "enemies", "ui", "vfx", "backgrounds",
    "vehicles", "buildings", "furniture", "foliage", "creatures", "portraits",
    "weapons", "decals", "markers", "terrain",
]


def pivot_for(category: str) -> tuple[float, float]:
    if category in FEET_CATEGORIES:
        return (0.5, 1.0)
    return (0.5, 0.5)


def perspective_for(pack: dict, category: str) -> str:
    if category in ("tiles",):
        return "orthographic top-down"
    if category in ("ui", "icons", "markers"):
        return "orthographic front view, facing camera"
    if category == "decals":
        return "orthographic top-down or front-on as a flat decal, facing camera"
    if category == "portraits":
        return "front-facing bust portrait, head and shoulders, facing camera"
    if category in ("backgrounds",):
        return "wide scenic view, no UI, no watermark"
    if category in ("characters", "enemies", "creatures"):
        return "side-view full body" if pack.get("pixel") else "full-body three-quarter view"
    if category in ("buildings", "terrain"):
        return "three-quarter exterior view, full structure visible, no interior cutaway"
    if category == "vehicles":
        return "three-quarter view, full vehicle or mount visible, wheels or feet toward the bottom"
    if category == "weapons":
        return "three-quarter view, full-size weapon, complete silhouette"
    if category == "foliage":
        return "three-quarter view, full plant visible, roots or pot at the bottom"
    if category == "furniture":
        return "three-quarter view, full piece visible, feet toward the bottom"
    return pack.get("perspective", "three-quarter view")


def tags_for(category, subcategory, subject, variant, style, w, h, tileable) -> list[str]:
    tags = [
        category[:-1] if category.endswith("s") and category not in ("props", "backgrounds") else category,
        subcategory, subject, variant, style,
        f"{w}x{h}", ".png",
    ]
    if style.startswith("pixel"):
        tags += ["pixelart", "pixel"]
    if "16bit" in style:
        tags += ["16-bit", "snes-like"]
    if style == "pixel_32":
        tags += ["32px"]
    if style == "hand_painted_fantasy":
        tags += ["painterly", "fantasy"]
    if style == "flat_vector_ui":
        tags += ["vector", "flat", "ui", "gui"]
    if style == "lowpoly_render":
        tags += ["lowpoly", "rendered"]
    if style == "dark_scifi":
        tags += ["scifi", "sci-fi", "dark"]
    if style == "cozy_cartoon":
        tags += ["cartoon", "cozy"]
    if style == "retro_8bit" or "8bit" in style:
        tags += ["pixelart", "pixel", "8-bit"]
    if style == "ink_watercolor":
        tags += ["ink", "watercolor", "sumi-e", "brush"]
    if style == "paper_cutout":
        tags += ["papercraft", "cutout", "layered"]
    if style == "claymation":
        tags += ["clay", "claymation", "stop-motion"]
    if style == "cel_shaded_anime":
        tags += ["cel", "cel-shaded", "anime-inspired"]
    if style == "vaporwave_synth":
        tags += ["vaporwave", "synth", "retro-futurist"]
    if style == "gothic_woodcut":
        tags += ["woodcut", "engraving", "gothic", "hatch"]
    if style == "isometric_voxel":
        tags += ["voxel", "isometric", "blocky"]
    if style == "stained_glass":
        tags += ["stained-glass", "leaded", "jewel"]
    if style == "chalk_crayon":
        tags += ["chalk", "crayon", "pastel"]
    if style == "art_deco_poster":
        tags += ["art-deco", "deco", "poster"]
    if style == "ukiyo_e_inspired":
        tags += ["ukiyo-e-inspired", "woodblock"]
    if style == "blueprint_line":
        tags += ["blueprint", "technical", "line-art"]
    if style == "cyberpunk_neon":
        tags += ["cyberpunk", "neon"]
    if style == "storybook_gouache":
        tags += ["gouache", "storybook"]
    if style == "monochrome_1bit" or "1bit" in style:
        tags += ["pixelart", "pixel", "1-bit", "monochrome"]
    if tileable:
        tags += ["tileable", "seamless", "tile"]
    if category == "tiles":
        tags += ["top-down", "overhead"]
    if category in ("characters", "enemies"):
        tags += ["sprite", "character"]
    if category == "vfx":
        tags += ["vfx", "fx", "effect"]
    if category == "backgrounds":
        tags += ["background", "scene"]
    if category == "vehicles":
        tags += ["vehicle", "mount", "transport"]
    if category == "buildings":
        tags += ["building", "structure", "exterior"]
    if category == "furniture":
        tags += ["furniture", "interior", "decor"]
    if category == "foliage":
        tags += ["foliage", "plant", "tree"]
    if category == "creatures":
        tags += ["creature", "animal", "pet", "critter", "sprite"]
    if category == "portraits":
        tags += ["portrait", "bust", "npc"]
    if category == "weapons":
        tags += ["weapon", "sprite", "full-size"]
    if category == "decals":
        tags += ["decal", "overlay", "stain"]
    if category == "markers":
        tags += ["marker", "map", "minimap", "waypoint"]
    if category == "terrain":
        tags += ["terrain", "landmark", "feature"]
    # unique, singular-ish, stable order
    seen, out = set(), []
    for t in tags:
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def build_all(packs: dict) -> tuple[list[dict], list[dict]]:
    specs: list[dict] = []
    # collect raw rows first, then group into batches
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

    styles = list(packs.keys())
    for style in styles:
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

    # --- group into batches ---
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
        # pad empty cells if needed
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
        nonlocal batches
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
        # unused cells have no specs
        batches.append(batch)

    # icon / prop / ui / enemy sheets: 4x4
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
            gw = 4
            gh = 4
            add_batch("sheet", group, gw, gh, "1:1",
                      lambda p, rs, w, h, t=title, c=cell: sheet_prompt(p, rs, w, h, t, c))

    # character turnarounds: 2x2 (front, three_quarter, side, back)
    for key, rows in turnarounds.items():
        rows = sorted(rows, key=lambda r: CHAR_VIEWS.index(r["variant"]) if r["variant"] in CHAR_VIEWS else 99)
        style = rows[0]["style_pack"]
        pack = packs[style]
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

    # VFX: 1 subject x 4 frames as 2x2, grouped further into 4x4 of 4 effects when possible?
    # Keep 2x2 per effect so frame order stays obvious (f1..f4).
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

    # singles: tiles, large props, backgrounds
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
            # For tiles we still mention magenta less strongly — they should be opaque and edge-to-edge.
            aspect = "1:1"
            kind = "tile"
        elif row["category"] == "backgrounds":
            prompt = (
                f"A wide 16:9 2D game background of {label}. {row['description']} "
                f"Cinematic but clear, no frame, no UI, no watermark, no typography, original location. "
                f"{pack['style_prefix']}. Fill the entire frame (ignore the magenta instruction for this background plate)."
            )
            aspect = "16:9"
            kind = "background"
        else:
            prompt = (
                f"A single {pack['title']} game prop: {label}, centered, full object visible, "
                f"standing on an implied ground but with a flat solid magenta background {chroma}, "
                f"no floor plane, no text. {pack['style_prefix']}."
            )
            aspect = "1:1"
            kind = "single"
        add_batch(kind, [row], 1, 1, aspect, lambda p, rs, w, h, pr=prompt: pr)

    # drop kind_hint from persisted specs
    for s in specs:
        s.pop("kind_hint", None)
    return specs, batches


def export_prompts(batches: list[dict], path: Path) -> None:
    with path.open("w") as f:
        for b in batches:
            rec = {k: b[k] for k in b if k != "rows"}
            rec["spec_ids"] = [r["spec_id"] for r in b["rows"]]
            rec["subjects"] = [f"{r['subject']}/{r['variant']}" for r in b["rows"]]
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def export_specs_jsonl(specs: list[dict], path: Path) -> None:
    with path.open("w") as f:
        for i, s in enumerate(specs):
            rec = dict(s)
            rec["spec_index"] = i
            rec["tags"] = s["tags"]
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def persist(conn, specs, batches, packs, shards=4):
    conn.execute("BEGIN IMMEDIATE")
    # Fresh queue only when empty, so reruns do not wipe claims/assets.
    n = conn.execute("SELECT COUNT(*) AS c FROM batches").fetchone()["c"]
    if n:
        conn.commit()
        return False
    conn.executemany(
        """
        INSERT INTO batches(batch_index, batch_id, kind, grid_w, grid_h, n_cells,
                            style_pack, category, prompt, negative, aspect_ratio,
                            filename_hint, status)
        VALUES (:batch_index, :batch_id, :kind, :grid_w, :grid_h, :n_cells,
                :style_pack, :category, :prompt, :negative, :aspect_ratio,
                :filename_hint, :status)
        """,
        [{k: b[k] for k in (
            "batch_index","batch_id","kind","grid_w","grid_h","n_cells",
            "style_pack","category","prompt","negative","aspect_ratio",
            "filename_hint","status"
        )} for b in batches],
    )
    rows = []
    for i, s in enumerate(specs):
        rec = dict(s)
        rec["spec_index"] = i
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
    set_meta(conn, "shards", shards)
    set_meta(conn, "license", LICENSE)
    set_meta(conn, "style_packs", list(packs.keys()))
    conn.commit()
    return True


def main():
    shards = 4
    if "--shards" in sys.argv:
        shards = int(sys.argv[sys.argv.index("--shards") + 1])
    packs = json.loads(PACKS_PATH.read_text())
    # Never rebuild or overwrite exports once a live queue exists.
    # New style packs are appended by append_styles.py.
    probe = init_db()
    existing = probe.execute("SELECT COUNT(*) AS c FROM batches").fetchone()["c"]
    probe.close()
    if existing:
        print(json.dumps({
            "error": "batches already exist; refusing to rebuild",
            "existing_batches": existing,
            "hint": "use nice -n 15 python3 /workspace/game-assets/append_styles.py to add new packs",
        }, indent=2))
        return
    specs, batches = build_all(packs)
    (ROOT / "taxonomy.json").write_text(json.dumps({
        "style_packs": list(packs.keys()),
        "counts": {
            "specs": len(specs),
            "batches": len(batches),
            "by_category": {c: sum(1 for s in specs if s["category"] == c)
                            for c in sorted(set(s["category"] for s in specs))},
            "by_style": {st: sum(1 for s in specs if s["style_pack"] == st)
                         for st in packs},
            "by_kind": {k: sum(1 for b in batches if b["kind"] == k)
                        for k in sorted(set(b["kind"] for b in batches))},
        },
        "shard_rule": "A worker started with --shard N --shards S claims pending batches where batch_index % S == N.",
        "default_shards": shards,
    }, indent=2) + "\n")
    export_specs_jsonl(specs, ROOT / "specs.jsonl")
    export_prompts(batches, ROOT / "prompts.jsonl")
    conn = init_db()
    inserted = persist(conn, specs, batches, packs, shards=shards)
    progress = snapshot_progress(conn)
    conn.close()
    print(json.dumps({
        "specs": len(specs),
        "batches": len(batches),
        "inserted": inserted,
        "shards": shards,
        "progress": progress,
    }, indent=2))


if __name__ == "__main__":
    main()
