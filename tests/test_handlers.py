from __future__ import annotations

import json
from pathlib import Path

from assetrizz_plugin.tools import handle_scene_safe, handle_search_safe, tool_specs


def _load(raw: str) -> dict:
    assert isinstance(raw, str)
    body = json.loads(raw)
    assert isinstance(body, dict)
    return body


def test_search_and_scene_handlers(plugin_env):
    stats = _load(handle_search_safe({"op": "stats"}))
    assert stats["ok"] is True
    assert stats["total_ok"] == 5
    found = _load(handle_search_safe({"op": "search", "q": "ranger", "style": "pixel_32"}))
    assert found["ok"] is True
    assert found["items"][0]["slug"].endswith("ranger_front")
    got = _load(handle_search_safe({"op": "get", "slug": found["items"][0]["slug"]}))
    assert got["ok"] is True
    assert got["asset"]["id"] == 4

    created = _load(
        handle_scene_safe({"op": "create", "name": "level", "width": 48, "height": 32, "background": "#112211"})
    )
    assert created["ok"] is True
    tiled = _load(
        handle_scene_safe(
            {
                "op": "tile",
                "slug": "pixel_32/tiles/floor/grass_base",
                "x": 0,
                "y": 0,
                "tile_w": 48,
                "tile_h": 32,
            }
        )
    )
    assert tiled["ok"] is True
    placed = _load(
        handle_scene_safe(
            {"op": "place", "slug": "pixel_32/characters/humanoid/ranger_front", "x": 8, "y": 4, "z": 3}
        )
    )
    assert placed["ok"] is True
    listed = _load(handle_scene_safe({"op": "list"}))
    assert listed["scene"]["layer_count"] == 2
    rendered = _load(handle_scene_safe({"op": "render"}))
    assert rendered["ok"] is True
    assert Path(rendered["png"]).is_file()
    assert "data" not in rendered  # do not embed the PNG
    bad = _load(handle_scene_safe({"op": "place", "slug": "/etc/passwd", "x": 0, "y": 0}))
    assert bad["ok"] is False
    assert bad["code"] in {"invalid_args", "path_escape", "not_found"}
    assert bad["fix"]


def test_all_specs_return_strings_on_success_and_error(plugin_env):
    handle_scene_safe({"op": "create", "name": "wire", "width": 32, "height": 32})
    for spec in tool_specs():
        if spec["name"] == "assetrizz_search":
            raw = spec["handler"]({"op": "stats"})
        else:
            raw = spec["handler"]({"op": "list"})
        body = _load(raw)
        assert body["ok"] is True
        raw_err = spec["handler"]({"op": "nope"})
        err = _load(raw_err)
        assert err["ok"] is False
        assert err["code"] == "invalid_op"
