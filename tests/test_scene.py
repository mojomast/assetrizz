from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from assetrizz_plugin.library import LibraryError
from assetrizz_plugin.paths import PathError
from assetrizz_plugin.scene import (
    clear_scene,
    compose,
    create_scene,
    flip_layer,
    layer_z,
    list_layers,
    load_scene,
    move_layer,
    place_asset,
    remove_layer,
    render_scene,
    save_scene,
    scale_layer,
    tile_fill,
    SceneError,
)


def test_compose_tile_and_place(plugin_env):
    scene = create_scene(64, 48, name="meadow", background="#102010")
    assert scene["id"] == "meadow"
    tiled = tile_fill(
        {
            "slug": "pixel_32/tiles/floor/grass_base",
            "x": 0,
            "y": 0,
            "tile_w": 64,
            "tile_h": 48,
        }
    )
    assert tiled["ok"] is True
    assert tiled["layer"]["id"] == "L1"
    placed = place_asset({"slug": "pixel_32/props/object/crate_plain", "x": 8, "y": 16, "z": 2})
    assert placed["layer"]["id"] == "L2"
    move_layer({"layer": "L2", "x": 16, "y": 20})
    scale_layer({"layer": "L2", "scale": 1.0})
    flip_layer({"layer": "L2", "flip_x": True})
    layer_z({"layer": "L1", "where": "back"})
    image = compose(list_layers()["scene"])
    assert image.size == (64, 48)
    # Grass fill should make a green-ish pixel in the corner.
    px = image.getpixel((1, 1))
    assert px[1] > px[0] and px[1] > 50
    rendered = render_scene({})
    png = Path(rendered["png"])
    assert png.is_file()
    assert png.resolve().is_relative_to(plugin_env["data"].resolve()) or str(plugin_env["data"]) in str(png)
    saved = Image.open(png)
    assert saved.size == (64, 48)
    saved_doc = save_scene({"as": "meadow-copy"})
    assert Path(saved_doc["path"]).is_file()
    loaded = load_scene({"name": "meadow-copy"})
    assert loaded["scene"]["layer_count"] == 2
    remove_layer({"layer": "L2"})
    assert list_layers()["scene"]["layer_count"] == 1
    clear_scene({})
    assert list_layers()["scene"]["layer_count"] == 0


def test_place_rejects_missing_and_escape(plugin_env):
    create_scene(32, 32, name="safe")
    with pytest.raises(LibraryError):
        place_asset({"slug": "cozy_cartoon/props/object/crate_plain", "x": 0, "y": 0})
    with pytest.raises((LibraryError, PathError, SceneError)):
        place_asset({"slug": "../etc/passwd", "x": 0, "y": 0})


def test_no_scene_without_create(plugin_env):
    with pytest.raises(SceneError) as exc:
        list_layers({})
    assert exc.value.code == "no_scene"
