#!/usr/bin/env python3
"""Compose docs/example-scene.png from real pixel_32 library assets."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugin"
if str(PLUGIN) not in sys.path:
    sys.path.insert(0, str(PLUGIN))


def main() -> int:
    os.environ.setdefault("ASSETRIZZ_LIBRARY", str(ROOT))
    os.environ.setdefault("ASSETRIZZ_HOME", str(ROOT / ".example-scene-data"))
    from assetrizz_plugin.library import reset_cache, stats
    from assetrizz_plugin.scene import (
        create_scene,
        list_layers,
        place_asset,
        render_scene,
        save_scene,
        tile_fill,
    )

    reset_cache()
    info = stats()
    if info["total_ok"] < 100:
        print("library looks empty:", info, file=sys.stderr)
        return 1

    scene = create_scene(640, 320, name="pixel32-meadow", background="#1a3a28")
    # Ground
    tile_fill({"slug": "pixel_32/tiles/floor/grass_base", "x": 0, "y": 0, "tile_w": 640, "tile_h": 320})
    # Flower patches along the top and a dirt path down the middle
    tile_fill({"slug": "pixel_32/tiles/floor/flower_meadow_base", "x": 0, "y": 0, "tile_w": 640, "tile_h": 64})
    tile_fill({"slug": "pixel_32/tiles/floor/dirt_path_base", "x": 256, "y": 0, "tile_w": 128, "tile_h": 320})
    # Water on the far right
    tile_fill({"slug": "pixel_32/tiles/floor/shallow_water_base", "x": 576, "y": 192, "tile_w": 64, "tile_h": 128})
    # Fence along the back-right meadow (avoid known magenta-gap hedge tiles)
    tile_fill({"slug": "pixel_32/tiles/wall/wood_fence_base", "x": 384, "y": 64, "tile_w": 192, "tile_h": 32})
    tile_fill({"slug": "pixel_32/tiles/wall/stone_wall_base", "x": 0, "y": 16, "tile_w": 32, "tile_h": 96})
    # Building and trees (higher z)
    place_asset({"slug": "pixel_32/buildings/civic/roadside_inn_exterior", "x": 24, "y": 48, "z": 4})
    place_asset({"slug": "pixel_32/props/object/oak_tree_plain", "x": 160, "y": 96, "z": 5})
    place_asset({"slug": "pixel_32/props/object/pine_tree_plain", "x": 200, "y": 80, "z": 5})
    place_asset({"slug": "pixel_32/foliage/tree/copper_beech_plain", "x": 400, "y": 48, "z": 5})
    place_asset({"slug": "pixel_32/foliage/bush/flowering_shrub_plain", "x": 480, "y": 96, "z": 4})
    place_asset({"slug": "pixel_32/foliage/bush/round_hedge_plain", "x": 544, "y": 112, "z": 4})
    # Props and characters
    place_asset({"slug": "pixel_32/props/object/mailbox_plain", "x": 128, "y": 176, "z": 6})
    place_asset({"slug": "pixel_32/props/object/crate_plain", "x": 96, "y": 208, "z": 6})
    place_asset({"slug": "pixel_32/props/object/barrel_plain", "x": 120, "y": 224, "z": 6})
    place_asset({"slug": "pixel_32/props/object/chest_closed", "x": 400, "y": 208, "z": 6})
    place_asset({"slug": "pixel_32/characters/humanoid/ranger_front", "x": 288, "y": 160, "z": 8})
    place_asset({"slug": "pixel_32/characters/humanoid/child_villager_three_quarter", "x": 200, "y": 192, "z": 8})
    place_asset({"slug": "pixel_32/creatures/animal/garden_hare_idle_front", "x": 352, "y": 224, "z": 7})
    place_asset({"slug": "pixel_32/creatures/animal/house_cat_idle_side", "x": 80, "y": 240, "z": 7})
    place_asset({"slug": "pixel_32/enemies/creature/walking_mushroom_idle_front", "x": 496, "y": 208, "z": 7})

    rendered = render_scene({})
    saved = save_scene({})
    dest_png = ROOT / "docs" / "example-scene.png"
    dest_json = ROOT / "docs" / "example-scene.json"
    dest_png.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(rendered["png"], dest_png)
    scene_doc = list_layers()["scene"]
    dest_json.write_text(json.dumps(scene_doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "ok": True,
        "png": str(dest_png),
        "json": str(dest_json),
        "layers": scene_doc["layer_count"],
        "size": [scene_doc["width"], scene_doc["height"]],
        "source_png": rendered["png"],
        "library_assets": info["total_ok"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
