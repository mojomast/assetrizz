"""Assetrizz tool schemas and handlers.

Two composable tools: assetrizz_search and assetrizz_scene. Every registered
handler returns a JSON string envelope {ok, error, code, fix, ...}.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from assetrizz_plugin import PLUGIN_ID, SKILL_ID, TOOLSET, __version__
from assetrizz_plugin.config import ConfigError
from assetrizz_plugin.library import LibraryError, get_asset, parse_search_args, search, stats
from assetrizz_plugin.paths import PathError
from assetrizz_plugin.register_util import call_register_tool
from assetrizz_plugin.scene import (
    SceneError,
    clear_scene,
    create_scene,
    list_layers,
    list_scenes,
    load_scene,
    layer_z,
    flip_layer,
    move_layer,
    place_asset,
    remove_layer,
    render_scene,
    save_scene,
    scale_layer,
    tile_fill,
)

TOOL_NAMES = ("assetrizz_search", "assetrizz_scene")

SEARCH_OPS = ("search", "get", "stats")
SCENE_OPS = (
    "create",
    "place",
    "move",
    "scale",
    "flip",
    "layer",
    "remove",
    "tile",
    "list",
    "clear",
    "render",
    "save",
    "load",
)


class Code:
    INVALID_OP = "invalid_op"
    INVALID_ARGS = "invalid_args"
    NOT_FOUND = "not_found"
    PATH_ESCAPE = "path_escape"
    LIBRARY_MISSING = "library_missing"
    LIBRARY_ERROR = "library_error"
    NO_SCENE = "no_scene"
    PAYLOAD_TOO_LARGE = "payload_too_large"
    INTERNAL = "internal"


CODE_FIX = {
    Code.INVALID_OP: "Use one of the documented ops for this tool.",
    Code.INVALID_ARGS: "Correct the arguments and call the tool again.",
    Code.NOT_FOUND: "Search the library or list scenes, then use a returned id or slug.",
    Code.PATH_ESCAPE: "Stay inside the library or the plugin data / export directory.",
    Code.LIBRARY_MISSING: (
        "Clone https://github.com/mojomast/assetrizz and set the Library path "
        "setting or ASSETRIZZ_LIBRARY to that folder."
    ),
    Code.LIBRARY_ERROR: "Check the library checkout and restore db/assets.db.xz if needed.",
    Code.NO_SCENE: "Call assetrizz_scene op=create with width and height first.",
    Code.PAYLOAD_TOO_LARGE: "Use the PNG path on disk; do not embed the full image in the tool result.",
    Code.INTERNAL: "Retry the call. If it still fails, run the plugin doctor and inspect the error code.",
}

SCHEMA_SEARCH = {
    "name": "assetrizz_search",
    "description": (
        "Search the local assetrizz 2D game-asset library (FTS over slugs, tags, "
        "descriptions, subjects, styles, categories). op=search filters; op=get "
        "returns one asset by id or slug; op=stats returns library counts. "
        "Does not compose scenes — use assetrizz_scene for that. If deferred, "
        f'tool_search(["assetrizz"]) or skill_view("{SKILL_ID}").'
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "op": {
                "type": "string",
                "enum": list(SEARCH_OPS),
                "description": "search, get, or stats.",
            },
            "q": {
                "type": "string",
                "description": "Free-text query for op=search (tags, subject, description).",
            },
            "style": {"type": "string", "description": "Style pack, e.g. pixel_32 or cozy_cartoon."},
            "category": {
                "type": "string",
                "description": "Category, e.g. tiles, characters, props, foliage.",
            },
            "tags": {"type": "string", "description": "Extra tag text ANDed into the search."},
            "subject": {"type": "string", "description": "Exact subject slug."},
            "tileable": {"type": "boolean", "description": "If set, require or exclude tileable assets."},
            "alpha": {"type": "boolean", "description": "If set, require or exclude transparency."},
            "size": {"type": "integer", "description": "Exact square size in pixels, e.g. 32."},
            "id": {"type": "integer", "description": "Asset id for op=get."},
            "slug": {"type": "string", "description": "Asset slug for op=get."},
            "limit": {"type": "integer", "description": "Max results for op=search (default 20, max 50)."},
            "offset": {"type": "integer", "description": "Search offset for paging."},
        },
        "required": ["op"],
        "additionalProperties": False,
    },
}

SCHEMA_SCENE = {
    "name": "assetrizz_scene",
    "description": (
        "Compose a 2D scene from library assets only. Ops: create, place, move, "
        "scale, flip, layer (z-order), remove, tile (fill a rect), list, clear, "
        "render (PNG under the export dir), save, load. Assets must come from "
        "assetrizz_search — no arbitrary file paths. render returns a filesystem "
        "path, not a full PNG. The Desktop/dashboard pane live-previews the current "
        "scene. If deferred, "
        f'tool_search(["assetrizz"]) or skill_view("{SKILL_ID}").'
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "op": {
                "type": "string",
                "enum": list(SCENE_OPS),
                "description": "Scene action to perform.",
            },
            "scene": {"type": "string", "description": "Scene id. Default: the current scene."},
            "name": {"type": "string", "description": "Scene id for create, save, or load."},
            "width": {"type": "integer", "description": "Scene or tile-fill width in pixels."},
            "height": {"type": "integer", "description": "Scene or tile-fill height in pixels."},
            "background": {
                "type": "string",
                "description": "For create: #RRGGBB, transparent, or a library slug to fill.",
            },
            "slug": {"type": "string", "description": "Library asset slug for place or tile."},
            "asset_id": {"type": "integer", "description": "Library asset id for place or tile."},
            "layer": {"type": "string", "description": "Layer id (L1, L2, …) for move/scale/flip/layer/remove."},
            "x": {"type": "integer", "description": "X position in pixels (top-left)."},
            "y": {"type": "integer", "description": "Y position in pixels (top-left)."},
            "scale": {"type": "number", "description": "Scale factor for place or scale (default 1)."},
            "flip_x": {"type": "boolean", "description": "Horizontal flip."},
            "flip_y": {"type": "boolean", "description": "Vertical flip."},
            "z": {"type": "integer", "description": "Z-order for place or layer. Higher is in front."},
            "where": {
                "type": "string",
                "enum": ["front", "back"],
                "description": "For op=layer, move the layer to front or back.",
            },
            "tile_w": {"type": "integer", "description": "For op=tile, width of the filled rectangle."},
            "tile_h": {"type": "integer", "description": "For op=tile, height of the filled rectangle."},
        },
        "required": ["op"],
        "additionalProperties": False,
    },
}

OUTPUT_SCHEMA = {
    "type": "object",
    "description": "JSON envelope",
    "properties": {
        "ok": {"type": "boolean"},
        "error": {"type": "string"},
        "code": {"type": "string"},
        "fix": {"type": "string"},
    },
}


def dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def err(code: str, message: str, fix: str | None = None, **extra: Any) -> str:
    body = {
        "ok": False,
        "error": message,
        "code": code,
        "fix": fix or CODE_FIX.get(code) or CODE_FIX[Code.INTERNAL],
    }
    body.update(extra)
    return dumps(body)


def _ok(payload: dict[str, Any]) -> str:
    body = dict(payload)
    body.setdefault("ok", True)
    return dumps(body)


def _as_args(args: Any) -> dict[str, Any]:
    if isinstance(args, dict):
        return args
    if isinstance(args, str):
        text = args.strip()
        if text.startswith("{"):
            try:
                loaded = json.loads(text)
            except json.JSONDecodeError:
                return {}
            if isinstance(loaded, dict):
                return loaded
    return {}


def handle_search(args: dict[str, Any] | None = None) -> str:
    payload = _as_args(args)
    op = str(payload.get("op") or "").strip().lower()
    try:
        if op == "search":
            return _ok(search(**parse_search_args(payload)))
        if op == "get":
            asset_id = payload.get("id") if payload.get("id") is not None else payload.get("asset_id")
            return _ok(
                get_asset(
                    asset_id=int(asset_id) if asset_id not in (None, "") else None,
                    slug=payload.get("slug"),
                )
            )
        if op == "stats":
            return _ok(stats())
        return err(Code.INVALID_OP, f"Unknown op {op!r}.", "Use op=search, op=get, or op=stats.")
    except Exception as exc:
        return _from_exc(exc)


def handle_scene(args: dict[str, Any] | None = None) -> str:
    payload = _as_args(args)
    op = str(payload.get("op") or "").strip().lower()
    try:
        if op == "create":
            scene = create_scene(
                payload.get("width"),
                payload.get("height"),
                name=payload.get("name") or payload.get("scene"),
                background=payload.get("background"),
            )
            from assetrizz_plugin.scene import _public

            return _ok({"scene": _public(scene)})
        if op == "place":
            return _ok(place_asset(payload))
        if op == "tile":
            return _ok(tile_fill(payload))
        if op == "move":
            return _ok(move_layer(payload))
        if op == "scale":
            return _ok(scale_layer(payload))
        if op == "flip":
            return _ok(flip_layer(payload))
        if op == "layer":
            return _ok(layer_z(payload))
        if op == "remove":
            return _ok(remove_layer(payload))
        if op == "list":
            listed = list_layers(payload)
            listed["scenes"] = list_scenes()
            return _ok(listed)
        if op == "clear":
            return _ok(clear_scene(payload))
        if op == "render":
            return _ok(render_scene(payload))
        if op == "save":
            return _ok(save_scene(payload))
        if op == "load":
            return _ok(load_scene(payload))
        return err(
            Code.INVALID_OP,
            f"Unknown op {op!r}.",
            "Use create, place, move, scale, flip, layer, remove, tile, list, clear, render, save, or load.",
        )
    except Exception as exc:
        return _from_exc(exc)


def _from_exc(exc: BaseException) -> str:
    if isinstance(exc, (ConfigError, LibraryError, PathError, SceneError)):
        code = getattr(exc, "code", None) or Code.INTERNAL
        fix = getattr(exc, "fix", "") or CODE_FIX.get(code)
        return err(code, str(exc), fix)
    return err(Code.INTERNAL, "The plugin hit an unexpected error.", CODE_FIX[Code.INTERNAL])


def handle_search_safe(args: Any = None) -> str:
    try:
        result = handle_search(args)
    except Exception as exc:
        result = _from_exc(exc)
    return result if isinstance(result, str) else dumps(result)


def handle_scene_safe(args: Any = None) -> str:
    try:
        result = handle_scene(args)
    except Exception as exc:
        result = _from_exc(exc)
    return result if isinstance(result, str) else dumps(result)


def tool_specs() -> list[dict[str, Any]]:
    return [
        {
            "name": "assetrizz_search",
            "schema": SCHEMA_SEARCH,
            "handler": handle_search_safe,
            "description": SCHEMA_SEARCH["description"],
        },
        {
            "name": "assetrizz_scene",
            "schema": SCHEMA_SCENE,
            "handler": handle_scene_safe,
            "description": SCHEMA_SCENE["description"],
        },
    ]


def register_tools(ctx) -> None:
    register = ctx.register_tool
    for spec in tool_specs():
        call_register_tool(
            register,
            name=spec["name"],
            toolset=TOOLSET,
            schema=spec["schema"],
            handler=spec["handler"],
            description=spec["description"],
            output_schema=OUTPUT_SCHEMA,
        )


def measure_schemas() -> dict[str, int]:
    """Token counts for the registered tool schemas (o200k_base and cl100k_base)."""
    import tiktoken

    text = json.dumps(
        [SCHEMA_SEARCH, SCHEMA_SCENE],
        separators=(",", ":"),
        ensure_ascii=False,
    )
    counts = {"chars": len(text)}
    for name in ("o200k_base", "cl100k_base"):
        try:
            enc = tiktoken.get_encoding(name)
        except Exception:
            continue
        counts[name] = len(enc.encode(text))
    return counts
