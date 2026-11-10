"""Search and inspect assets in the local library (FTS5, auto-restore from .xz)."""

from __future__ import annotations

import json
import lzma
import os
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any

from assetrizz_plugin.config import ConfigError, library_assets_root, resolve_library
from assetrizz_plugin.paths import PathError, confine, data_home, relative_posix, require_non_root

_FTS_TOKEN = re.compile(r"[A-Za-z0-9_]+")
_SLUG_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./-]{0,240}$")
_JSON_FIELDS = ("tags", "palette", "dominant_colors", "pivot", "frame_info", "qa_notes")
_SEARCH_FIELDS = (
    "id",
    "slug",
    "path",
    "category",
    "subcategory",
    "subject",
    "style_pack",
    "tags",
    "description",
    "width",
    "height",
    "has_alpha",
    "tileable",
    "status",
)
_GET_FIELDS = _SEARCH_FIELDS + (
    "palette",
    "dominant_colors",
    "pivot",
    "frame_info",
    "license",
    "thumb_path",
)
_DESC_LIMIT = 180
_TAG_LIMIT = 12
_LIMIT_MAX = 50
_LIMIT_DEFAULT = 20

_LOCK = threading.Lock()
_DB_PATH: Path | None = None
_LIBRARY: Path | None = None


class LibraryError(ValueError):
    def __init__(self, message: str, *, code: str = "library_error", fix: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.fix = fix


def reset_cache() -> None:
    """Drop cached library/db paths (tests)."""
    global _DB_PATH, _LIBRARY
    with _LOCK:
        _DB_PATH = None
        _LIBRARY = None


def _writable_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".assetrizz-write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def restore_db(library: Path, dest_fallback: Path) -> Path:
    """Return a usable assets.db, decompressing db/assets.db.xz if needed.

    Prefers ``library/db/assets.db`` when that folder is writable; otherwise
    writes a copy under the plugin data dir. Never overwrites an existing db.
    """
    library = require_non_root(library, label="library")
    xz = library / "db" / "assets.db.xz"
    local = library / "db" / "assets.db"
    if local.is_file():
        return local
    if not xz.is_file():
        raise LibraryError(
            f"No catalog at {local} and no snapshot at {xz}.",
            code="library_missing",
            fix="Clone assetrizz with db/assets.db.xz, or run bash db/restore.sh in the checkout.",
        )
    if _writable_dir(local.parent):
        dest = local
    else:
        dest = dest_fallback
        dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file():
        return dest
    tmp = dest.with_name(dest.name + ".partial")
    try:
        with lzma.open(xz, "rb") as src, open(tmp, "wb") as out:
            while True:
                chunk = src.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
        os.replace(tmp, dest)
    except Exception:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise
    return dest


def current_library() -> Path:
    global _LIBRARY
    with _LOCK:
        if _LIBRARY is not None and _LIBRARY.is_dir():
            return _LIBRARY
        _LIBRARY = resolve_library()
        return _LIBRARY


def current_db() -> Path:
    global _DB_PATH, _LIBRARY
    with _LOCK:
        if _DB_PATH is not None and _DB_PATH.is_file():
            return _DB_PATH
        library = _LIBRARY or resolve_library()
        _LIBRARY = library
        _DB_PATH = restore_db(library, data_home() / "assets.db")
        return _DB_PATH


def connect() -> sqlite3.Connection:
    path = current_db()
    uri = f"file:{path.as_posix()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    except sqlite3.OperationalError:
        conn = sqlite3.connect(os.fspath(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def fts_query(text: str) -> str:
    """Turn free text into a safe FTS5 MATCH query (quoted tokens AND-ed)."""
    tokens = _FTS_TOKEN.findall(text or "")
    if not tokens:
        return ""
    return " AND ".join(f'"{tok}"' for tok in tokens[:24])


def _decode(row: sqlite3.Row, fields: tuple[str, ...], *, compact: bool) -> dict[str, Any]:
    data = {key: row[key] for key in fields if key in row.keys()}
    for key in _JSON_FIELDS:
        if key not in data:
            continue
        raw = data[key]
        if not raw:
            data[key] = [] if key in ("tags", "palette", "dominant_colors", "qa_notes") else None
            continue
        if isinstance(raw, str):
            try:
                data[key] = json.loads(raw)
            except json.JSONDecodeError:
                pass
    if compact:
        desc = data.get("description")
        if isinstance(desc, str) and len(desc) > _DESC_LIMIT:
            data["description"] = desc[: _DESC_LIMIT - 1].rstrip() + "…"
        tags = data.get("tags")
        if isinstance(tags, list) and len(tags) > _TAG_LIMIT:
            data["tags"] = tags[:_TAG_LIMIT]
        data.pop("qa_notes", None)
    # Normalize flags
    if "has_alpha" in data:
        data["has_alpha"] = bool(data["has_alpha"])
    if "tileable" in data:
        data["tileable"] = bool(data["tileable"])
    if "style_pack" in data:
        data["style"] = data["style_pack"]
    # Rewrite any absolute / escaped path to a repo-relative assets/... path.
    path = data.get("path")
    if isinstance(path, str) and path:
        try:
            data["path"] = asset_relative_path(path)
        except (PathError, LibraryError, ConfigError):
            data.pop("path", None)
    return data


def asset_relative_path(stored: str) -> str:
    """Return a repo-relative ``assets/...`` path confined to the library."""
    library = current_library()
    assets = library_assets_root(library)
    raw = (stored or "").strip().replace("\\", "/")
    if not raw:
        raise LibraryError("Asset has no path.", code="not_found", fix="Search again and use a slug or id.")
    # Historical pipeline paths used library/...; rewrite to assets/...
    if raw.startswith("library/"):
        raw = "assets/" + raw[len("library/") :]
    if raw.startswith("/"):
        # Absolute paths must still resolve under the library.
        confined = confine(raw, library, label="asset path")
        return relative_posix(confined, library)
    if raw.startswith("assets/"):
        confined = confine(library / raw, library, label="asset path")
        return relative_posix(confined, library)
    confined = confine(assets / raw, assets, label="asset path")
    return "assets/" + relative_posix(confined, assets)


def asset_file(stored: str) -> Path:
    library = current_library()
    rel = asset_relative_path(stored)
    path = confine(library / rel, library, label="asset file")
    if path.suffix.lower() != ".png":
        raise LibraryError(
            "Only PNG assets from the library can be opened.",
            code="invalid_args",
            fix="Pass a library slug or id, not an arbitrary file path.",
        )
    if not path.is_file():
        raise LibraryError(
            f"Asset file is missing: {rel}",
            code="not_found",
            fix="Restore the library checkout so assets/ is complete.",
        )
    return path


def _parse_limit(value: Any, default: int = _LIMIT_DEFAULT) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(_LIMIT_MAX, limit))


def _parse_offset(value: Any) -> int:
    try:
        offset = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, offset)


def _boolish(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return None


def search(
    q: str | None = None,
    *,
    style: str | None = None,
    category: str | None = None,
    tags: str | None = None,
    subject: str | None = None,
    tileable: bool | None = None,
    alpha: bool | None = None,
    size: int | None = None,
    min_size: int | None = None,
    limit: int = _LIMIT_DEFAULT,
    offset: int = 0,
    status: str = "ok",
) -> dict[str, Any]:
    """FTS search with filters. Falls back to LIKE when MATCH is rejected."""
    limit = _parse_limit(limit)
    offset = _parse_offset(offset)
    text = " ".join(part for part in (q or "", tags or "") if part).strip()
    match = fts_query(text)
    where = ["1=1"]
    args: list[Any] = []
    join = ""
    if match:
        join = "JOIN assets_fts ON assets_fts.rowid = a.id"
        where.append("assets_fts MATCH ?")
        args.append(match)
    if category:
        where.append("a.category = ?")
        args.append(str(category))
    if style:
        where.append("a.style_pack = ?")
        args.append(str(style))
    if subject:
        where.append("a.subject = ?")
        args.append(str(subject))
    if size:
        where.append("a.width = ? AND a.height = ?")
        args.extend([int(size), int(size)])
    if min_size:
        where.append("a.width >= ? AND a.height >= ?")
        args.extend([int(min_size), int(min_size)])
    if tileable is True:
        where.append("a.tileable = 1")
    elif tileable is False:
        where.append("a.tileable = 0")
    if alpha is True:
        where.append("a.has_alpha = 1")
    elif alpha is False:
        where.append("a.has_alpha = 0")
    if status:
        where.append("a.status = ?")
        args.append(str(status))
    cols = ", ".join(f"a.{name}" for name in _SEARCH_FIELDS)
    sql = f"""
        SELECT {cols}
          FROM assets a
          {join}
         WHERE {' AND '.join(where)}
         ORDER BY a.id ASC
         LIMIT ? OFFSET ?
    """
    count_sql = f"SELECT COUNT(*) AS n FROM assets a {join} WHERE {' AND '.join(where)}"
    conn = connect()
    try:
        try:
            total = int(conn.execute(count_sql, args).fetchone()["n"])
            rows = conn.execute(sql, [*args, limit, offset]).fetchall()
        except sqlite3.OperationalError:
            conn.close()
            return search_like(
                text,
                style=style,
                category=category,
                subject=subject,
                tileable=tileable,
                alpha=alpha,
                size=size,
                min_size=min_size,
                limit=limit,
                offset=offset,
                status=status,
            )
    finally:
        try:
            conn.close()
        except Exception:
            pass
    items = [_decode(row, _SEARCH_FIELDS, compact=True) for row in rows]
    return {"ok": True, "total": total, "count": len(items), "offset": offset, "items": items}


def search_like(
    q: str,
    *,
    style: str | None = None,
    category: str | None = None,
    subject: str | None = None,
    tileable: bool | None = None,
    alpha: bool | None = None,
    size: int | None = None,
    min_size: int | None = None,
    limit: int = _LIMIT_DEFAULT,
    offset: int = 0,
    status: str = "ok",
) -> dict[str, Any]:
    like = f"%{q}%"
    where = ["(a.description LIKE ? OR a.tags LIKE ? OR a.subject LIKE ? OR a.slug LIKE ?)"]
    args: list[Any] = [like, like, like, like]
    if category:
        where.append("a.category = ?")
        args.append(str(category))
    if style:
        where.append("a.style_pack = ?")
        args.append(str(style))
    if subject:
        where.append("a.subject = ?")
        args.append(str(subject))
    if size:
        where.append("a.width = ? AND a.height = ?")
        args.extend([int(size), int(size)])
    if min_size:
        where.append("a.width >= ? AND a.height >= ?")
        args.extend([int(min_size), int(min_size)])
    if tileable is True:
        where.append("a.tileable = 1")
    elif tileable is False:
        where.append("a.tileable = 0")
    if alpha is True:
        where.append("a.has_alpha = 1")
    elif alpha is False:
        where.append("a.has_alpha = 0")
    if status:
        where.append("a.status = ?")
        args.append(str(status))
    cols = ", ".join(f"a.{name}" for name in _SEARCH_FIELDS)
    conn = connect()
    try:
        total = int(
            conn.execute(
                f"SELECT COUNT(*) AS n FROM assets a WHERE {' AND '.join(where)}",
                args,
            ).fetchone()["n"]
        )
        rows = conn.execute(
            f"""SELECT {cols} FROM assets a
                WHERE {' AND '.join(where)}
                ORDER BY a.id ASC LIMIT ? OFFSET ?""",
            [*args, limit, offset],
        ).fetchall()
    finally:
        conn.close()
    items = [_decode(row, _SEARCH_FIELDS, compact=True) for row in rows]
    return {"ok": True, "total": total, "count": len(items), "offset": offset, "items": items}


def get_asset(*, asset_id: int | None = None, slug: str | None = None) -> dict[str, Any]:
    row = _fetch_asset(asset_id=asset_id, slug=slug)
    data = _decode(row, _GET_FIELDS, compact=False)
    try:
        data["exists"] = asset_file(data.get("path") or data["slug"] + ".png").is_file()
    except (LibraryError, PathError, KeyError):
        # Try slug-derived path if the stored path is odd.
        try:
            data["exists"] = asset_file("assets/" + str(data.get("slug")) + ".png").is_file()
        except Exception:
            data["exists"] = False
    return {"ok": True, "asset": data}


def _fetch_asset(*, asset_id: int | None = None, slug: str | None = None) -> sqlite3.Row:
    cols = ", ".join(f"a.{name}" for name in _GET_FIELDS)
    conn = connect()
    try:
        if asset_id is not None:
            row = conn.execute(f"SELECT {cols} FROM assets a WHERE a.id = ?", (int(asset_id),)).fetchone()
        elif slug:
            clean = _clean_slug(slug)
            row = conn.execute(
                f"SELECT {cols} FROM assets a WHERE a.slug = ? OR a.path = ? OR a.path = ?",
                (clean, f"assets/{clean}.png", f"{clean}.png"),
            ).fetchone()
        else:
            raise LibraryError(
                "Provide id or slug.",
                code="invalid_args",
                fix="Pass id (integer) or slug (style/category/.../name).",
            )
    finally:
        conn.close()
    if row is None:
        raise LibraryError(
            "No asset matched that id or slug.",
            code="not_found",
            fix="Call assetrizz_search op=search and use a returned id or slug.",
        )
    return row


def resolve_asset(*, asset_id: int | None = None, slug: str | None = None) -> dict[str, Any]:
    """Asset metadata plus a confined file path for compositing."""
    row = _fetch_asset(asset_id=asset_id, slug=slug)
    data = _decode(row, _GET_FIELDS, compact=False)
    stored = data.get("path") or f"assets/{data['slug']}.png"
    data["file"] = str(asset_file(stored))
    data["path"] = asset_relative_path(stored)
    return data


def _clean_slug(slug: str) -> str:
    text = (slug or "").strip().replace("\\", "/").removesuffix(".png")
    if text.startswith("assets/"):
        text = text[len("assets/") :]
    if not text or ".." in text or text.startswith("/") or not _SLUG_OK.match(text):
        raise LibraryError(
            "Slug is not a library asset slug.",
            code="invalid_args",
            fix="Use a slug from assetrizz_search, such as pixel_32/tiles/floor/grass_base.",
        )
    return text


def stats() -> dict[str, Any]:
    library = current_library()
    db_path = current_db()
    conn = connect()
    try:
        def rows(sql: str) -> list[dict[str, Any]]:
            return [dict(r) for r in conn.execute(sql).fetchall()]

        total_ok = int(conn.execute("SELECT COUNT(*) c FROM assets WHERE status='ok'").fetchone()["c"])
        try:
            total_rejected = int(
                conn.execute("SELECT COUNT(*) c FROM assets WHERE status='rejected'").fetchone()["c"]
            )
        except sqlite3.OperationalError:
            total_rejected = 0
        by_category = rows(
            "SELECT category AS name, COUNT(*) AS n FROM assets WHERE status='ok' "
            "GROUP BY category ORDER BY n DESC"
        )
        by_style = rows(
            "SELECT style_pack AS name, COUNT(*) AS n FROM assets WHERE status='ok' "
            "GROUP BY style_pack ORDER BY n DESC"
        )
    finally:
        conn.close()
    return {
        "ok": True,
        "library": str(library),
        "db": str(db_path),
        "total_ok": total_ok,
        "total_rejected": total_rejected,
        "styles": by_style,
        "categories": by_category,
    }


def parse_search_args(args: dict[str, Any]) -> dict[str, Any]:
    size = args.get("size")
    min_size = args.get("min_size")
    return dict(
        q=args.get("q") or args.get("query") or args.get("text"),
        style=args.get("style") or args.get("style_pack"),
        category=args.get("category"),
        tags=args.get("tags"),
        subject=args.get("subject"),
        tileable=_boolish(args.get("tileable")),
        alpha=_boolish(args.get("alpha")),
        size=int(size) if size not in (None, "") else None,
        min_size=int(min_size) if min_size not in (None, "") else None,
        limit=_parse_limit(args.get("limit")),
        offset=_parse_offset(args.get("offset")),
    )
