"""Scene documents, disk store, and Pillow compositing."""

from __future__ import annotations

import json
import re
import threading
import uuid
from io import BytesIO
from pathlib import Path
from typing import Any

from assetrizz_plugin.config import resolve_export_dir
from assetrizz_plugin.library import LibraryError, resolve_asset
from assetrizz_plugin.paths import (
    PathError,
    confine,
    data_home,
    ensure_layout,
    refuse_denied_write,
    require_non_root,
)

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
HEX_RE = re.compile(r"^#?[0-9A-Fa-f]{3}([0-9A-Fa-f]{3})?$")
MAX_DIM = 4096
MIN_DIM = 16
MAX_LAYERS = 200
MAX_SCALE = 8.0
MIN_SCALE = 0.05
# Whole serialized JSON (base64 + envelope) must stay under the reviewed relay budget.
MAX_ENVELOPE_BYTES = 512 * 1024
PREVIEW_HEADROOM = 48 * 1024

_LOCK = threading.RLock()
_CURRENT_NAME = "current"


class SceneError(ValueError):
    def __init__(self, message: str, *, code: str = "invalid_args", fix: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.fix = fix


def _scenes_dir() -> Path:
    root = ensure_layout()
    return root / "scenes"


def _state_path() -> Path:
    return ensure_layout() / "current.json"


def _export_png_path(name: str) -> Path:
    return confine(resolve_export_dir() / f"{name}.png", resolve_export_dir(), label="export")


def _preview_path(name: str) -> Path:
    return confine(ensure_layout() / "previews" / f"{name}.jpg", ensure_layout(), label="preview")


def _validate_name(name: str | None, *, default: str | None = None) -> str:
    text = (name or default or "").strip()
    if not text:
        raise SceneError(
            "Scene name is required.",
            code="invalid_args",
            fix="Pass a name like meadow-01 (letters, numbers, dot, underscore, dash).",
        )
    if not NAME_RE.match(text):
        raise SceneError(
            "Scene name must be 1–64 characters: letters, numbers, dot, underscore, dash.",
            code="invalid_args",
            fix="Use a name like pixel32-meadow.",
        )
    return text


def _parse_hex(color: str) -> tuple[int, int, int, int]:
    text = color.strip()
    if text.lower() in {"transparent", "none"}:
        return (0, 0, 0, 0)
    if not HEX_RE.match(text):
        raise SceneError(
            "Background color must be #RGB, #RRGGBB, or transparent.",
            code="invalid_args",
            fix="Pass background=\"#1a1820\" or a library slug.",
        )
    raw = text[1:] if text.startswith("#") else text
    if len(raw) == 3:
        raw = "".join(ch * 2 for ch in raw)
    r, g, b = int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)
    return (r, g, b, 255)


def _dims(width: Any, height: Any) -> tuple[int, int]:
    try:
        w, h = int(width), int(height)
    except (TypeError, ValueError) as exc:
        raise SceneError(
            "width and height must be integers.",
            code="invalid_args",
            fix=f"Choose a size between {MIN_DIM} and {MAX_DIM} pixels.",
        ) from exc
    if not (MIN_DIM <= w <= MAX_DIM and MIN_DIM <= h <= MAX_DIM):
        raise SceneError(
            f"Scene size must be between {MIN_DIM} and {MAX_DIM} on each side.",
            code="invalid_args",
            fix=f"Try 640x360 or 1280x720 (max {MAX_DIM}).",
        )
    return w, h


def _new_layer_id(scene: dict[str, Any]) -> str:
    used = {str(layer.get("id")) for layer in scene.get("layers") or []}
    n = 1
    while f"L{n}" in used:
        n += 1
    return f"L{n}"


def empty_scene(
    name: str,
    width: int,
    height: int,
    background: str | None = "#141218",
) -> dict[str, Any]:
    bg = _background_spec(background)
    return {
        "id": name,
        "width": width,
        "height": height,
        "background": bg,
        "layers": [],
        "revision": 0,
    }


def _background_spec(background: str | None) -> dict[str, Any]:
    text = (background or "#141218").strip()
    if not text:
        text = "#141218"
    if HEX_RE.match(text) or text.lower() in {"transparent", "none"}:
        return {"type": "color", "color": text if text.startswith("#") or text.lower() in {"transparent", "none"} else f"#{text}"}
    # Treat as a library slug or "assets/..." path, never an arbitrary filesystem path.
    return {"type": "asset", "slug": text, "mode": "fill"}


def _scene_path(name: str) -> Path:
    return confine(_scenes_dir() / f"{name}.json", data_home(), label="scene")


def _atomic_write(path: Path, data: bytes) -> None:
    refuse_denied_write(path, label="export")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{uuid.uuid4().hex[:8]}.tmp")
    try:
        tmp.write_bytes(data)
        tmp.replace(path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def _load_named(name: str) -> dict[str, Any]:
    path = _scene_path(name)
    if not path.is_file():
        raise SceneError(
            f"No scene named {name!r} is saved.",
            code="not_found",
            fix="Call assetrizz_scene op=create, or op=load with a saved name.",
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SceneError(
            f"Scene {name!r} is not valid JSON.",
            code="invalid_args",
            fix="Recreate the scene with op=create.",
        ) from exc
    if not isinstance(data, dict):
        raise SceneError("Scene file must be a JSON object.", code="invalid_args", fix="Recreate the scene.")
    data["id"] = name
    data.setdefault("layers", [])
    data.setdefault("revision", 1)
    return data


def _save_named(scene: dict[str, Any]) -> Path:
    name = _validate_name(str(scene.get("id") or ""))
    scene = dict(scene)
    scene["id"] = name
    scene["revision"] = int(scene.get("revision") or 0) + 1
    path = _scene_path(name)
    _atomic_write(path, json.dumps(scene, indent=2, ensure_ascii=False).encode("utf-8"))
    _set_current(name)
    return path


def _set_current(name: str) -> None:
    _atomic_write(
        _state_path(),
        json.dumps({"current": name}, ensure_ascii=False).encode("utf-8"),
    )


def current_name() -> str | None:
    path = _state_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    name = data.get("current") if isinstance(data, dict) else None
    return str(name) if name else None


def load_current() -> dict[str, Any]:
    name = current_name()
    if not name:
        raise SceneError(
            "No current scene.",
            code="no_scene",
            fix="Call assetrizz_scene op=create with width and height first.",
        )
    return _load_named(name)


def list_scenes() -> list[dict[str, Any]]:
    rows = []
    current = current_name()
    folder = _scenes_dir()
    if not folder.is_dir():
        return rows
    for path in sorted(folder.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        name = path.stem
        rows.append(
            {
                "id": name,
                "width": data.get("width"),
                "height": data.get("height"),
                "layers": len(data.get("layers") or []),
                "revision": data.get("revision"),
                "current": name == current,
            }
        )
    return rows


def create_scene(
    width: int,
    height: int,
    *,
    name: str | None = None,
    background: str | None = "#141218",
) -> dict[str, Any]:
    w, h = _dims(width, height)
    scene_name = _validate_name(name, default="scene")
    # If the default name is taken, suffix.
    if name is None:
        existing = {p.stem for p in _scenes_dir().glob("*.json")} if _scenes_dir().is_dir() else set()
        base, n = scene_name, 1
        while scene_name in existing:
            n += 1
            scene_name = f"{base}-{n}"
    scene = empty_scene(scene_name, w, h, background)
    _save_named(scene)
    # revision bumped by _save_named from 1 -> 2 if we increment always;
    # start at 0 so first save becomes 1.
    return _load_named(scene_name)


def _target(name: str | None) -> dict[str, Any]:
    if name:
        return _load_named(_validate_name(name))
    return load_current()


def _find_layer(scene: dict[str, Any], layer_id: str) -> dict[str, Any]:
    for layer in scene.get("layers") or []:
        if str(layer.get("id")) == str(layer_id):
            return layer
    raise SceneError(
        f"No layer {layer_id!r} in this scene.",
        code="not_found",
        fix="Call op=list and use a layer id such as L1.",
    )


def _asset_ref(args: dict[str, Any]) -> dict[str, Any]:
    raw_id = args.get("asset_id") if args.get("asset_id") is not None else args.get("id")
    slug = args.get("slug") or args.get("asset")
    # Don't treat a layer id as an asset id: only numeric asset_id.
    asset_id = None
    if raw_id is not None and str(raw_id).isdigit():
        asset_id = int(raw_id)
    if asset_id is None and not slug:
        raise SceneError(
            "Provide slug or asset_id of a library asset.",
            code="invalid_args",
            fix="Search first, then pass slug=\"pixel_32/tiles/floor/grass_base\".",
        )
    asset = resolve_asset(asset_id=asset_id, slug=str(slug) if slug else None)
    return asset


def _num(value: Any, default: float | None = None, *, label: str) -> float:
    if value is None or value == "":
        if default is None:
            raise SceneError(
                f"{label} is required.",
                code="invalid_args",
                fix=f"Pass {label} as a number.",
            )
        return float(default)
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise SceneError(
            f"{label} must be a number.",
            code="invalid_args",
            fix=f"Pass a numeric {label}.",
        ) from exc


def _scale(value: Any, default: float = 1.0) -> float:
    scale = _num(value, default, label="scale")
    if not (MIN_SCALE <= scale <= MAX_SCALE):
        raise SceneError(
            f"scale must be between {MIN_SCALE} and {MAX_SCALE}.",
            code="invalid_args",
            fix="Use 1 for native size, or a value such as 0.5 or 2.",
        )
    return scale


def place_asset(args: dict[str, Any]) -> dict[str, Any]:
    with _LOCK:
        scene = _target(args.get("scene"))
        if len(scene.get("layers") or []) >= MAX_LAYERS:
            raise SceneError(
                f"A scene may have at most {MAX_LAYERS} layers.",
                code="invalid_args",
                fix="Remove unused layers, or start a new scene.",
            )
        asset = _asset_ref(args)
        layer = {
            "id": _new_layer_id(scene),
            "asset_id": asset.get("id"),
            "slug": asset.get("slug"),
            "path": asset.get("path"),
            "x": int(_num(args.get("x"), 0, label="x")),
            "y": int(_num(args.get("y"), 0, label="y")),
            "scale": _scale(args.get("scale"), 1.0),
            "flip_x": bool(args.get("flip_x")),
            "flip_y": bool(args.get("flip_y")),
            "z": int(_num(args.get("z"), len(scene.get("layers") or []), label="z")),
            "visible": True,
        }
        if args.get("tile") or args.get("tile_w") or args.get("tile_h"):
            tw = int(_num(args.get("tile_w") or args.get("width"), 0, label="tile_w"))
            th = int(_num(args.get("tile_h") or args.get("height"), 0, label="tile_h"))
            if tw <= 0 or th <= 0:
                raise SceneError(
                    "tile_w and tile_h must be positive.",
                    code="invalid_args",
                    fix="Pass the width and height of the area to fill, in pixels.",
                )
            layer["tile"] = {"w": tw, "h": th}
        scene.setdefault("layers", []).append(layer)
        _save_named(scene)
        return {"ok": True, "scene": _public(scene), "layer": layer}


def tile_fill(args: dict[str, Any]) -> dict[str, Any]:
    payload = dict(args)
    payload["tile"] = True
    if payload.get("w") and not payload.get("tile_w"):
        payload["tile_w"] = payload.get("w")
    if payload.get("h") and not payload.get("tile_h"):
        payload["tile_h"] = payload.get("h")
    return place_asset(payload)


def _mutate_layer(args: dict[str, Any], editor) -> dict[str, Any]:
    with _LOCK:
        scene = _target(args.get("scene"))
        layer = _find_layer(scene, str(args.get("layer") or args.get("layer_id") or ""))
        editor(scene, layer)
        _save_named(scene)
        return {"ok": True, "scene": _public(scene), "layer": layer}


def move_layer(args: dict[str, Any]) -> dict[str, Any]:
    def edit(_scene: dict[str, Any], layer: dict[str, Any]) -> None:
        if args.get("x") is not None:
            layer["x"] = int(_num(args.get("x"), label="x"))
        if args.get("y") is not None:
            layer["y"] = int(_num(args.get("y"), label="y"))
        if args.get("x") is None and args.get("y") is None:
            raise SceneError("Pass x and/or y.", code="invalid_args", fix="Example: x=32 y=64.")

    return _mutate_layer(args, edit)


def scale_layer(args: dict[str, Any]) -> dict[str, Any]:
    def edit(_scene: dict[str, Any], layer: dict[str, Any]) -> None:
        layer["scale"] = _scale(args.get("scale"))

    return _mutate_layer(args, edit)


def flip_layer(args: dict[str, Any]) -> dict[str, Any]:
    def edit(_scene: dict[str, Any], layer: dict[str, Any]) -> None:
        if args.get("flip_x") is not None:
            layer["flip_x"] = bool(args.get("flip_x"))
        elif args.get("x") is not None:
            layer["flip_x"] = bool(args.get("x"))
        else:
            layer["flip_x"] = not bool(layer.get("flip_x"))
        if args.get("flip_y") is not None:
            layer["flip_y"] = bool(args.get("flip_y"))
        elif args.get("y") is True or args.get("y") is False:
            layer["flip_y"] = bool(args.get("y"))

    if not str(args.get("layer") or args.get("layer_id") or ""):
        raise SceneError("Pass layer (for example L1).", code="invalid_args", fix="op=list to see layer ids.")
    return _mutate_layer(args, edit)


def layer_z(args: dict[str, Any]) -> dict[str, Any]:
    def edit(_scene: dict[str, Any], layer: dict[str, Any]) -> None:
        action = str(args.get("where") or args.get("order") or "").strip().lower()
        if args.get("z") is not None and args.get("z") != "":
            layer["z"] = int(_num(args.get("z"), label="z"))
        elif action in {"front", "top", "raise"}:
            z_vals = [int(item.get("z") or 0) for item in _scene.get("layers") or []]
            layer["z"] = (max(z_vals) + 1) if z_vals else 0
        elif action in {"back", "bottom", "lower"}:
            z_vals = [int(item.get("z") or 0) for item in _scene.get("layers") or []]
            layer["z"] = (min(z_vals) - 1) if z_vals else 0
        else:
            raise SceneError(
                "Pass z, or where=front / where=back.",
                code="invalid_args",
                fix="Example: layer=L1 z=3, or where=front.",
            )

    return _mutate_layer(args, edit)


def remove_layer(args: dict[str, Any]) -> dict[str, Any]:
    with _LOCK:
        scene = _target(args.get("scene"))
        layer_id = str(args.get("layer") or args.get("layer_id") or "")
        _find_layer(scene, layer_id)
        scene["layers"] = [item for item in scene.get("layers") or [] if str(item.get("id")) != layer_id]
        _save_named(scene)
        return {"ok": True, "scene": _public(scene), "removed": layer_id}


def clear_scene(args: dict[str, Any] | None = None) -> dict[str, Any]:
    args = args or {}
    with _LOCK:
        scene = _target(args.get("scene"))
        scene["layers"] = []
        _save_named(scene)
        return {"ok": True, "scene": _public(scene)}


def list_layers(args: dict[str, Any] | None = None) -> dict[str, Any]:
    args = args or {}
    scene = _target(args.get("scene"))
    return {"ok": True, "scene": _public(scene)}


def save_scene(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Write the current scene, optionally under a new name, plus a JSON copy in export_dir."""
    args = args or {}
    with _LOCK:
        scene = _target(args.get("scene") if not args.get("as") else args.get("scene"))
        dest = args.get("as") or args.get("name")
        if dest:
            scene = dict(scene)
            scene["id"] = _validate_name(str(dest))
        path = _save_named(scene)
        export_json = confine(
            resolve_export_dir() / f"{scene['id']}.json",
            resolve_export_dir(),
            label="export json",
        )
        _atomic_write(export_json, path.read_bytes())
        return {
            "ok": True,
            "scene": _public(scene),
            "path": str(path),
            "export": str(export_json),
        }


def load_scene(args: dict[str, Any]) -> dict[str, Any]:
    name = _validate_name(str(args.get("name") or args.get("scene") or args.get("id") or ""))
    with _LOCK:
        scene = _load_named(name)
        _set_current(name)
        return {"ok": True, "scene": _public(scene)}


def _public(scene: dict[str, Any]) -> dict[str, Any]:
    layers = list(scene.get("layers") or [])
    layers_sorted = sorted(layers, key=lambda item: (int(item.get("z") or 0), str(item.get("id") or "")))
    return {
        "id": scene.get("id"),
        "width": scene.get("width"),
        "height": scene.get("height"),
        "background": scene.get("background"),
        "layers": layers_sorted,
        "layer_count": len(layers),
        "revision": scene.get("revision"),
    }


def _open_rgba(path: Path):
    from PIL import Image

    image = Image.open(path)
    if image.mode != "RGBA":
        image = image.convert("RGBA")
    return image


def _tile_image(tile, width: int, height: int):
    from PIL import Image

    if width <= 0 or height <= 0:
        return Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    tw, th = tile.size
    if tw <= 0 or th <= 0:
        return canvas
    for y in range(0, height, th):
        for x in range(0, width, tw):
            canvas.paste(tile, (x, y), tile)
    return canvas


def _scale_image(image, scale: float):
    from PIL import Image

    if abs(scale - 1.0) < 1e-6:
        return image
    w = max(1, int(round(image.width * scale)))
    h = max(1, int(round(image.height * scale)))
    resample = Image.Resampling.NEAREST if max(image.size) <= 256 else Image.Resampling.LANCZOS
    # Pixel-art packs stay sharp; larger painted assets may scale with LANCZOS.
    style_pixel = max(image.size) <= 128
    if style_pixel:
        resample = Image.Resampling.NEAREST
    return image.resize((w, h), resample)


def compose(scene: dict[str, Any]):
    """Return a Pillow RGBA image of the scene. Lazy-imports Pillow."""
    from PIL import Image

    width, height = _dims(scene.get("width"), scene.get("height"))
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    background = scene.get("background") or {"type": "color", "color": "#141218"}
    if isinstance(background, str):
        background = _background_spec(background)
    if background.get("type") == "color":
        canvas.paste(Image.new("RGBA", (width, height), _parse_hex(str(background.get("color") or "#141218"))))
    elif background.get("type") == "asset":
        asset = resolve_asset(slug=str(background.get("slug")))
        fill = _open_rgba(Path(asset["file"]))
        mode = str(background.get("mode") or "fill")
        if mode == "tile":
            canvas.alpha_composite(_tile_image(fill, width, height))
        else:
            canvas.alpha_composite(fill.resize((width, height), Image.Resampling.LANCZOS))
    layers = sorted(
        [layer for layer in scene.get("layers") or [] if layer.get("visible", True)],
        key=lambda item: (int(item.get("z") or 0), str(item.get("id") or "")),
    )
    for layer in layers:
        slug = layer.get("slug")
        asset_id = layer.get("asset_id")
        asset = resolve_asset(
            asset_id=int(asset_id) if asset_id is not None else None,
            slug=str(slug) if slug else None,
        )
        sprite = _open_rgba(Path(asset["file"]))
        if layer.get("flip_x"):
            sprite = sprite.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        if layer.get("flip_y"):
            sprite = sprite.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        sprite = _scale_image(sprite, float(layer.get("scale") or 1.0))
        x = int(layer.get("x") or 0)
        y = int(layer.get("y") or 0)
        tile = layer.get("tile")
        if isinstance(tile, dict):
            tw = int(tile.get("w") or 0)
            th = int(tile.get("h") or 0)
            sprite = _tile_image(sprite, tw, th)
        # Paste with clipping by compositing onto a same-size overlay.
        overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        overlay.paste(sprite, (x, y), sprite)
        canvas.alpha_composite(overlay)
    return canvas


def render_scene(args: dict[str, Any] | None = None) -> dict[str, Any]:
    args = args or {}
    with _LOCK:
        scene = _target(args.get("scene"))
        image = compose(scene)
        name = str(scene["id"])
        png_path = _export_png_path(name)
        refuse_denied_write(png_path, label="export png")
        image.save(png_path, format="PNG", optimize=True)
        preview_meta = write_preview(image, name)
        return {
            "ok": True,
            "scene": _public(scene),
            "png": str(png_path),
            "width": image.width,
            "height": image.height,
            "preview": preview_meta,
        }


def write_preview(image, name: str, *, max_px: int = 960) -> dict[str, Any]:
    """Downscale/compress a JPEG preview that fits the 512 KiB JSON budget."""
    from PIL import Image

    path = _preview_path(name)
    last: bytes | None = None
    used_px = max_px
    quality = 80
    for px in (max_px, 720, 512, 384, 256, 160):
        used_px = px
        frame = image
        if max(frame.size) > px:
            ratio = px / max(frame.size)
            size = (max(1, int(frame.width * ratio)), max(1, int(frame.height * ratio)))
            frame = frame.convert("RGBA").resize(size, Image.Resampling.LANCZOS)
        rgb = Image.new("RGB", frame.size, (20, 19, 27))
        rgb.paste(frame, mask=frame.split()[-1] if frame.mode == "RGBA" else None)
        for quality in (80, 70, 60, 45, 30):
            buf = BytesIO()
            rgb.save(buf, format="JPEG", quality=quality, optimize=True)
            last = buf.getvalue()
            # Base64 expands ~4/3 plus JSON envelope; leave headroom.
            if int(len(last) * 4 / 3) + PREVIEW_HEADROOM <= MAX_ENVELOPE_BYTES:
                refuse_denied_write(path, label="preview")
                path.write_bytes(last)
                return {
                    "path": str(path),
                    "bytes": len(last),
                    "width": rgb.width,
                    "height": rgb.height,
                    "quality": quality,
                    "max_px": used_px,
                    "ok": True,
                }
    if last is None:
        raise SceneError(
            "Could not build a preview.",
            code="payload_too_large",
            fix="Reduce the scene size and render again.",
        )
    # Still too large: refuse rather than exceed the budget.
    raise SceneError(
        "Preview still exceeds the 512 KiB JSON relay budget after downscaling.",
        code="payload_too_large",
        fix="Render the PNG on disk (op=render) and open it locally; do not embed the full image.",
    )


def preview_bytes(name: str | None = None, *, max_px: int = 960) -> dict[str, Any]:
    """Return preview bytes for the pane (rebuild if missing or stale)."""
    import hashlib

    scene = _target(name)
    image = compose(scene)
    meta = write_preview(image, str(scene["id"]), max_px=max_px)
    data = Path(meta["path"]).read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    meta["sha256"] = digest
    meta["data"] = data
    meta["mime"] = "image/jpeg"
    meta["revision"] = scene.get("revision")
    meta["scene_id"] = scene.get("id")
    return meta


def scene_json_path(name: str) -> Path:
    return _scene_path(_validate_name(name))
