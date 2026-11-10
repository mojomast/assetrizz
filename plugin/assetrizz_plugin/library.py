"""Search and inspect assets (FTS5). Catalog may be bundled; PNGs may be fetched."""

from __future__ import annotations

import json
import lzma
import os
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any

from assetrizz_plugin import BUNDLED_DB_SHA256
from assetrizz_plugin.config import (
    ConfigError,
    asset_mode,
    local_library_dir,
    resolve_library,
    resolve_library_optional,
)
from assetrizz_plugin.errors import LibraryError
from assetrizz_plugin.paths import (
    PathError,
    confine,
    data_home,
    ensure_layout,
    refuse_denied_write,
    relative_posix,
    require_non_root,
)

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
    "sha256",
)
_DESC_LIMIT = 180
_TAG_LIMIT = 12
_LIMIT_MAX = 50
_LIMIT_DEFAULT = 20
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitize_text(value, *, max_len: int | None = None):
    """Strip control characters and newlines from untrusted catalog text.

    Asset names, tags, and descriptions are treated as data, never as
    instructions, even though they come from the local library.
    """
    if value is None:
        return value
    if not isinstance(value, str):
        return value
    text = _CTRL.sub("", value).replace("\r", " ").replace("\n", " ")
    text = " ".join(text.split())
    if max_len is not None and len(text) > max_len:
        text = text[: max_len - 1].rstrip() + "…"
    return text


def sanitize_tags(value, *, limit: int = _TAG_LIMIT):
    if not isinstance(value, list):
        if isinstance(value, str):
            return [sanitize_text(value, max_len=80)] if value else []
        return []
    out = []
    for item in value:
        cleaned = sanitize_text(str(item), max_len=80) if item is not None else ""
        if cleaned:
            out.append(cleaned)
        if len(out) >= limit:
            break
    return out

_LOCK = threading.Lock()
_DB_PATH: Path | None = None
_LIBRARY: Path | None = None
_LIBRARY_READY = False




def reset_cache() -> None:
    """Drop cached library/db paths (tests)."""
    global _DB_PATH, _LIBRARY, _LIBRARY_READY
    with _LOCK:
        _DB_PATH = None
        _LIBRARY = None
        _LIBRARY_READY = False


def cache_root() -> Path:
    root = ensure_layout() / "cache"
    root.mkdir(parents=True, exist_ok=True)
    return require_non_root(root, label="cache")


def plugin_root() -> Path:
    """Installable plugin directory (the folder that contains plugin.yaml)."""
    return Path(__file__).resolve().parent.parent


def bundled_catalog_xz() -> Path:
    return plugin_root() / "db" / "assets.db.xz"


def sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def verify_file_sha256(path: Path, expected: str, *, label: str = "file") -> str:
    got = sha256_file(path)
    if got != expected.strip().lower():
        raise LibraryError(
            f"SHA-256 of {label} did not match the pin.",
            code="hash_mismatch",
            fix="Delete the bad file and restore or download it again. Do not use a mismatched copy.",
        )
    return got


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
    from assetrizz_plugin.paths import refuse_denied_write

    refuse_denied_write(dest, label="catalog db")
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


def restore_catalog_xz(xz: Path, dest: Path, expected_sha256: str) -> Path:
    """Decompress a pinned catalog snapshot into dest (never overwrite an existing db)."""
    dest = dest.expanduser()
    if dest.is_file():
        return dest
    xz = require_non_root(Path(xz), label="catalog snapshot")
    if not xz.is_file():
        raise LibraryError(
            f"No catalog snapshot at {xz}.",
            code="library_missing",
            fix="Reinstall the plugin so plugin/db/assets.db.xz is present, or set a local library.",
        )
    verify_file_sha256(xz, expected_sha256, label="bundled catalog snapshot")
    dest.parent.mkdir(parents=True, exist_ok=True)
    refuse_denied_write(dest, label="catalog db")
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


def restore_bundled_catalog(dest: Path | None = None) -> Path:
    dest = dest if dest is not None else data_home() / "catalog" / "assets.db"
    return restore_catalog_xz(bundled_catalog_xz(), dest, BUNDLED_DB_SHA256)


def current_library_optional() -> Path | None:
    global _LIBRARY, _LIBRARY_READY
    with _LOCK:
        if _LIBRARY_READY:
            return _LIBRARY
        _LIBRARY = resolve_library_optional()
        _LIBRARY_READY = True
        return _LIBRARY


def current_library() -> Path:
    found = current_library_optional()
    if found is None:
        raise ConfigError(
            "No complete local assetrizz library is installed.",
            code="library_missing",
            fix="Leave asset_mode at on_demand, or download a local library from the Assetrizz pane.",
        )
    return found


def current_db() -> Path:
    global _DB_PATH, _LIBRARY, _LIBRARY_READY
    with _LOCK:
        if _DB_PATH is not None and _DB_PATH.is_file():
            return _DB_PATH
        if not _LIBRARY_READY:
            _LIBRARY = resolve_library_optional()
            _LIBRARY_READY = True
        library = _LIBRARY
        dest = data_home() / "catalog" / "assets.db"
        if library is not None:
            _DB_PATH = restore_db(library, dest)
        else:
            _DB_PATH = restore_bundled_catalog(dest)
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
    # Catalog text is untrusted data (tags, names, descriptions).
    if "description" in data:
        data["description"] = sanitize_text(data.get("description") or "", max_len=_DESC_LIMIT if compact else 2000)
    if "tags" in data:
        data["tags"] = sanitize_tags(data.get("tags") or [], limit=_TAG_LIMIT if compact else 40)
    for key in ("subject", "category", "subcategory", "style_pack", "slug", "style"):
        if key in data and isinstance(data[key], str):
            data[key] = sanitize_text(data[key], max_len=240)
    if compact:
        data.pop("qa_notes", None)
    elif "qa_notes" in data:
        notes = data.get("qa_notes")
        if isinstance(notes, list):
            data["qa_notes"] = [sanitize_text(str(n), max_len=240) for n in notes[:8]]
        elif isinstance(notes, str):
            data["qa_notes"] = sanitize_text(notes, max_len=240)
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
    """Return a repo-relative ``assets/...png`` path. No library root required."""
    from assetrizz_plugin.fetch import normalize_asset_rel

    return normalize_asset_rel(stored)


def cache_path_for(rel: str) -> Path:
    rel = asset_relative_path(rel)
    root = cache_root()
    path = confine(root / rel, root, label="cached asset")
    if path.suffix.lower() != ".png":
        raise LibraryError(
            "Only PNG assets from the library can be opened.",
            code="invalid_args",
            fix="Pass a library slug or id, not an arbitrary file path.",
        )
    return path


def _valid_png(path: Path, expected: str | None, *, delete_bad: bool) -> Path | None:
    if not path.is_file():
        return None
    if path.suffix.lower() != ".png":
        return None
    if not expected:
        return path
    try:
        digest = sha256_file(path)
    except OSError:
        return None
    if digest == expected.strip().lower():
        return path
    if delete_bad:
        try:
            path.unlink()
        except OSError:
            pass
    return None


def locate_asset_file(stored: str, expected_sha256: str | None = None) -> Path | None:
    """Return a local PNG if present (library, local download, or cache). Never fetches."""
    rel = asset_relative_path(stored)
    expected = (expected_sha256 or "").strip().lower() or None
    library = current_library_optional()
    if library is not None:
        try:
            found = _valid_png(
                confine(library / rel, library, label="asset file"),
                expected,
                delete_bad=False,
            )
        except PathError:
            found = None
        if found is not None:
            return found
    try:
        local = local_library_dir()
    except PathError:
        local = None
    if local is not None and local.is_dir() and (library is None or local != library):
        try:
            confined = confine(local / rel, local, label="local library asset")
        except PathError:
            confined = None
        if confined is not None:
            found = _valid_png(confined, expected, delete_bad=False)
            if found is not None:
                return found
    try:
        found = _valid_png(cache_path_for(rel), expected, delete_bad=True)
    except (LibraryError, PathError):
        found = None
    return found


def lookup_sha256(stored: str) -> str | None:
    """SHA-256 from the catalog for this asset path, if the column is present."""
    rel = asset_relative_path(stored)
    conn = connect()
    try:
        try:
            row = conn.execute(
                "SELECT sha256 FROM assets WHERE path = ? OR path = ? LIMIT 1",
                (rel, rel[len("assets/") :]),
            ).fetchone()
        except Exception:
            return None
    finally:
        conn.close()
    if row is None:
        return None
    value = row["sha256"] if "sha256" in row.keys() else None
    if isinstance(value, str) and len(value.strip()) == 64:
        return value.strip().lower()
    return None


def _atomic_write_bytes(dest: Path, data: bytes, expected_sha256: str) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    refuse_denied_write(dest, label="asset file")
    tmp = dest.with_name(dest.name + ".partial")
    try:
        with open(tmp, "wb") as handle:
            handle.write(data)
        from assetrizz_plugin.fetch import sha256_bytes

        if sha256_bytes(data) != expected_sha256.strip().lower():
            raise LibraryError(
                "SHA-256 of the downloaded PNG did not match the catalog.",
                code="hash_mismatch",
                fix="Delete the cached file if any, then retry. Do not use a mismatched file.",
            )
        os.replace(tmp, dest)
    except Exception:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise
    return dest


def ensure_asset_file(stored: str, expected_sha256: str | None = None) -> Path:
    """Return a usable PNG, fetching one allowlisted file when the mode allows it."""
    from assetrizz_plugin.fetch import asset_url, fetch_url

    rel = asset_relative_path(stored)
    expected = (expected_sha256 or lookup_sha256(rel) or "").strip().lower() or None
    found = locate_asset_file(rel, expected)
    if found is not None:
        return found
    if not expected:
        raise LibraryError(
            f"Asset file is missing: {rel}",
            code="not_found",
            fix="Place a verified local copy, or use a catalog snapshot that includes sha256 so the file can be fetched.",
        )
    mode = asset_mode()
    if mode == "local":
        root = local_library_dir()
        root.mkdir(parents=True, exist_ok=True)
        dest = confine(root / rel, root, label="local library asset")
    else:
        dest = cache_path_for(rel)
    data = fetch_url(asset_url(rel), expected_sha256=expected)
    return _atomic_write_bytes(dest, data, expected)


def asset_file(stored: str, expected_sha256: str | None = None) -> Path:
    """Return a confined on-disk PNG, fetching it on demand when allowed."""
    return ensure_asset_file(stored, expected_sha256)


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
    stored = data.get("path") or f"assets/{data.get('slug')}.png"
    expected = data.get("sha256") if isinstance(data.get("sha256"), str) else None
    try:
        located = locate_asset_file(stored, expected)
    except (LibraryError, PathError, KeyError):
        located = None
    data["exists"] = located is not None
    data["source"] = "local" if located is not None else "missing"
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
    expected = data.get("sha256") if isinstance(data.get("sha256"), str) else None
    data["file"] = str(ensure_asset_file(stored, expected))
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
    library = current_library_optional()
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
        "library": str(library) if library is not None else None,
        "asset_mode": asset_mode(),
        "catalog": "local" if library is not None else "bundled",
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
