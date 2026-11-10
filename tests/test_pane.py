from __future__ import annotations

from assetrizz_plugin.pane import health, preview, scene_view, search_view, status
from assetrizz_plugin.scene import create_scene, tile_fill


def test_pane_health_and_scene_preview(plugin_env):
    body = health()
    assert body["ok"] is True
    assert body["library_ok"] is True
    missing = scene_view()
    assert missing["ok"] is False
    assert missing["code"] == "no_scene"
    create_scene(32, 32, name="pane", background="#000000")
    tile_fill({"slug": "pixel_32/tiles/floor/grass_base", "x": 0, "y": 0, "tile_w": 32, "tile_h": 32})
    view = scene_view()
    assert view["ok"] is True
    assert view["scene"]["id"] == "pane"
    shot = preview("pane", max_px=64)
    assert shot["ok"] is True
    assert shot["mime"] == "image/jpeg"
    assert shot["data"]
    unchanged = preview("pane", max_px=64, since=shot["sha256"])
    assert unchanged["ok"] is True
    assert unchanged.get("unchanged") is True
    found = search_view({"q": "grass"})
    assert found["items"]
    st = status()
    assert st["current"] == "pane"
    assert st["stats"]["total_ok"] == 5
