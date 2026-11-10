"""Read/write helpers for the assetrizz compose pane.

``dashboard/plugin_api.py`` mounts these at ``/api/plugins/assetrizz/``.
The Desktop pane talks only through ctx.rest. Previews stay under the 512 KiB
JSON budget. Asset bytes are loaded only from the library root.
"""

from __future__ import annotations

import base64
import hashlib
from typing import Any

from assetrizz_plugin import MIN_HERMES, PLUGIN_ID, __version__
from assetrizz_plugin.config import ConfigError, resolve_library
from assetrizz_plugin.library import (
    LibraryError,
    get_asset,
    parse_search_args,
    search,
    stats,
)
from assetrizz_plugin.paths import PathError
from assetrizz_plugin.scene import (
    MAX_ENVELOPE_BYTES,
    PREVIEW_HEADROOM,
    SceneError,
    current_name,
    list_layers,
    list_scenes,
    load_scene,
    preview_bytes,
)

SOFT_CODES = {"no_scene", "library_missing"}


def _fail(exc: BaseException) -> dict[str, Any]:
    code = getattr(exc, "code", None) or "internal"
    fix = getattr(exc, "fix", "") or ""
    return {"ok": False, "error": str(exc), "code": code, "fix": fix}


def health() -> dict[str, Any]:
    body: dict[str, Any] = {
        "ok": True,
        "pane": PLUGIN_ID,
        "version": __version__,
        "min_hermes": MIN_HERMES,
    }
    try:
        library = resolve_library()
        body["library"] = str(library)
        body["library_ok"] = True
    except (ConfigError, PathError) as exc:
        body["library_ok"] = False
        body["library_error"] = str(exc)
        body["fix"] = getattr(exc, "fix", "")
    return body


def status() -> dict[str, Any]:
    body = health()
    body["current"] = current_name()
    body["scenes"] = list_scenes()
    if body.get("library_ok"):
        try:
            info = stats()
            body["stats"] = {
                "total_ok": info["total_ok"],
                "styles": info.get("styles") or [],
                "categories": info.get("categories") or [],
            }
        except Exception as exc:
            body["stats_error"] = str(exc)
    return body


def scene_view(name: str | None = None) -> dict[str, Any]:
    try:
        if name:
            loaded = load_scene({"name": name})
            return {"ok": True, **loaded}
        return list_layers({})
    except (SceneError, ConfigError, LibraryError, PathError) as exc:
        failed = _fail(exc)
        if failed.get("code") in SOFT_CODES:
            failed["scenes"] = list_scenes()
        return failed


def preview(name: str | None = None, *, max_px: int = 960, since: str | None = None) -> dict[str, Any]:
    try:
        meta = preview_bytes(name, max_px=max_px)
    except (SceneError, ConfigError, LibraryError, PathError) as exc:
        return _fail(exc)
    digest = meta["sha256"]
    if since and since == digest:
        return {
            "ok": True,
            "unchanged": True,
            "sha256": digest,
            "revision": meta.get("revision"),
            "scene_id": meta.get("scene_id"),
            "width": meta.get("width"),
            "height": meta.get("height"),
        }
    data = meta["data"]
    b64 = base64.b64encode(data).decode("ascii")
    envelope = {
        "ok": True,
        "unchanged": False,
        "sha256": digest,
        "revision": meta.get("revision"),
        "scene_id": meta.get("scene_id"),
        "mime": meta.get("mime") or "image/jpeg",
        "width": meta.get("width"),
        "height": meta.get("height"),
        "bytes": len(data),
        "data": b64,
    }
    encoded = __import__("json").dumps(envelope, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_ENVELOPE_BYTES:
        return {
            "ok": False,
            "error": "Preview exceeds the 512 KiB JSON relay budget.",
            "code": "payload_too_large",
            "fix": "The PNG is still written under the export directory; open it there.",
        }
    return envelope


def search_view(args: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        return search(**parse_search_args(args or {}))
    except (ConfigError, LibraryError, PathError, ValueError) as exc:
        return _fail(exc)


def asset_view(args: dict[str, Any] | None = None) -> dict[str, Any]:
    args = args or {}
    try:
        asset_id = args.get("id") if args.get("id") is not None else args.get("asset_id")
        return get_asset(
            asset_id=int(asset_id) if asset_id not in (None, "") else None,
            slug=args.get("slug"),
        )
    except (ConfigError, LibraryError, PathError, ValueError) as exc:
        return _fail(exc)


def thumb(args: dict[str, Any] | None = None, *, max_px: int = 96) -> dict[str, Any]:
    """Small JPEG thumbnail of one library asset, budget-checked."""
    from io import BytesIO

    from PIL import Image

    from assetrizz_plugin.library import asset_file, resolve_asset

    args = args or {}
    try:
        asset_id = args.get("id") if args.get("id") is not None else args.get("asset_id")
        asset = resolve_asset(
            asset_id=int(asset_id) if asset_id not in (None, "") else None,
            slug=args.get("slug"),
        )
        image = Image.open(asset["file"])
        if image.mode != "RGBA":
            image = image.convert("RGBA")
        if max(image.size) > max_px:
            ratio = max_px / max(image.size)
            image = image.resize(
                (max(1, int(image.width * ratio)), max(1, int(image.height * ratio))),
                Image.Resampling.NEAREST if max(image.size) <= 128 else Image.Resampling.LANCZOS,
            )
        rgb = Image.new("RGB", image.size, (22, 20, 28))
        rgb.paste(image, mask=image.split()[-1])
        buf = BytesIO()
        rgb.save(buf, format="JPEG", quality=70, optimize=True)
        data = buf.getvalue()
        if int(len(data) * 4 / 3) + PREVIEW_HEADROOM > MAX_ENVELOPE_BYTES:
            return {
                "ok": False,
                "error": "Thumbnail exceeds the JSON relay budget.",
                "code": "payload_too_large",
                "fix": "Use a smaller thumb or skip the image and show the slug.",
            }
        digest = hashlib.sha256(data).hexdigest()
        return {
            "ok": True,
            "slug": asset.get("slug"),
            "mime": "image/jpeg",
            "width": rgb.width,
            "height": rgb.height,
            "sha256": digest,
            "data": base64.b64encode(data).decode("ascii"),
        }
    except (ConfigError, LibraryError, PathError, ValueError, OSError) as exc:
        return _fail(exc)
