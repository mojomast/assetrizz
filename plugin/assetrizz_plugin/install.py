"""User-initiated local library download and removal.

This module is called from the Desktop pane (ctx.rest routes) and from
``python -m assetrizz_plugin.cli``. It is not registered as a model tool.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from assetrizz_plugin import BUNDLED_DB_SHA256, PLUGIN_ID
from assetrizz_plugin.config import (
    ConfigError,
    asset_mode,
    asset_ref,
    is_library_root,
    local_library_dir,
    resolve_library_optional,
)
from assetrizz_plugin.errors import FetchError, LibraryError
from assetrizz_plugin.library import (
    bundled_catalog_xz,
    cache_root,
    current_db,
    plugin_root,
    sha256_file,
)
from assetrizz_plugin.paths import PathError, data_home, refuse_denied_write, require_non_root

MAX_CONCURRENCY = 4
JOB_NAME = "library_job.json"
PACK_SIZES_NAME = "pack_sizes.json"

_JOB_LOCK = threading.Lock()
_CANCEL = threading.Event()
_WORKER: threading.Thread | None = None


class InstallError(LibraryError):
    def __init__(self, message: str, *, code: str = "invalid_args", fix: str = "") -> None:
        super().__init__(message, code=code, fix=fix)


def _job_path() -> Path:
    return data_home() / JOB_NAME


def _read_job() -> dict[str, Any]:
    path = _job_path()
    if not path.is_file():
        return {"ok": True, "status": "idle"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"ok": True, "status": "idle"}
    if isinstance(data, dict):
        data.setdefault("ok", True)
        return data
    return {"ok": True, "status": "idle"}


def _write_job(data: dict[str, Any]) -> dict[str, Any]:
    path = _job_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    refuse_denied_write(path, label="library job")
    tmp = path.with_name(path.name + ".partial")
    payload = dict(data)
    payload.setdefault("ok", True)
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return payload


def load_pack_sizes() -> dict[str, Any]:
    path = plugin_root() / "db" / PACK_SIZES_NAME
    if not path.is_file():
        return {"total_count": 0, "total_bytes": 0, "packs": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"total_count": 0, "total_bytes": 0, "packs": {}}
    packs = data.get("packs") if isinstance(data, dict) else {}
    if not isinstance(packs, dict):
        packs = {}
    return {
        "total_count": int(data.get("total_count") or 0),
        "total_bytes": int(data.get("total_bytes") or 0),
        "packs": packs,
    }


def format_bytes(n: int) -> str:
    value = float(max(0, int(n)))
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{int(n)} B"


def _dir_usage(path: Path) -> dict[str, int]:
    files = 0
    bytes_ = 0
    if not path.is_dir():
        return {"files": 0, "bytes": 0}
    for root, _dirs, names in os.walk(path, followlinks=False):
        for name in names:
            item = Path(root) / name
            try:
                if item.is_symlink() or not item.is_file():
                    continue
                bytes_ += item.stat().st_size
                files += 1
            except OSError:
                continue
    return {"files": files, "bytes": bytes_}


def _count_pngs(root: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    assets = root / "assets"
    if not assets.is_dir():
        return counts
    try:
        styles = [p for p in assets.iterdir() if p.is_dir()]
    except OSError:
        return counts
    for style in styles:
        n = 0
        for dirpath, _dirnames, names in os.walk(style, followlinks=False):
            n += sum(1 for name in names if name.lower().endswith(".png"))
        counts[style.name] = n
    return counts


def _list_assets(packs: list[str]) -> list[dict[str, str]]:
    import sqlite3

    db = current_db()
    uri = f"file:{db.as_posix()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    except sqlite3.OperationalError:
        conn = sqlite3.connect(os.fspath(db), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        sql = "SELECT path, sha256, style_pack FROM assets WHERE status = 'ok'"
        args: list[Any] = []
        if packs and packs != ["*"]:
            placeholders = ",".join("?" for _ in packs)
            sql += f" AND style_pack IN ({placeholders})"
            args.extend(packs)
        try:
            rows = conn.execute(sql, args).fetchall()
        except sqlite3.OperationalError:
            # Older catalogs without sha256 still list paths; fetch will refuse them.
            sql = sql.replace(", sha256, ", ", NULL AS sha256, ")
            rows = conn.execute(sql, args).fetchall()
    finally:
        conn.close()
    items: list[dict[str, str]] = []
    for row in rows:
        path = (row["path"] or "").strip()
        style = (row["style_pack"] or "").strip()
        sha = (row["sha256"] or "").strip().lower() if row["sha256"] else ""
        if path:
            items.append({"path": path, "style": style, "sha256": sha})
    return items


def _normalize_packs(packs: list[str] | None) -> list[str]:
    sizes = load_pack_sizes()
    known = set(sizes.get("packs") or {})
    if not packs or packs == ["*"] or (len(packs) == 1 and packs[0] in {"*", "all"}):
        return ["*"]
    clean: list[str] = []
    for raw in packs:
        name = str(raw or "").strip()
        if not name or name in clean:
            continue
        if known and name not in known:
            raise InstallError(
                f"Unknown style pack {name!r}.",
                code="invalid_args",
                fix="Use a pack name from the pane list, or pass --all.",
            )
        clean.append(name)
    if not clean:
        raise InstallError(
            "Choose at least one style pack, or download the full library.",
            code="invalid_args",
            fix="Select packs in the pane, or pass --style / --all.",
        )
    return clean


def estimate_packs(packs: list[str] | None) -> dict[str, Any]:
    sizes = load_pack_sizes()
    chosen = _normalize_packs(packs)
    all_packs: dict[str, Any] = sizes.get("packs") or {}
    if chosen == ["*"]:
        keys = list(all_packs)
        count = int(sizes.get("total_count") or 0)
        bytes_ = int(sizes.get("total_bytes") or 0)
    else:
        keys = chosen
        count = 0
        bytes_ = 0
        for key in keys:
            info = all_packs.get(key) or {}
            count += int(info.get("count") or 0)
            bytes_ += int(info.get("bytes") or 0)
    return {
        "packs": keys,
        "all": chosen == ["*"],
        "count": count,
        "bytes": bytes_,
        "label": format_bytes(bytes_),
    }


def _is_plugin_checkout(path: Path) -> bool:
    """True when path is the source monorepo (must never be deleted)."""
    try:
        resolved = path.resolve()
    except OSError:
        return False
    markers = (
        resolved / "plugin" / "plugin.yaml",
        resolved / "plugin" / "assetrizz_plugin" / "__init__.py",
        resolved / ".git",
    )
    if any(marker.exists() for marker in markers):
        return True
    try:
        plugin = plugin_root().resolve()
        if plugin == resolved or plugin.is_relative_to(resolved):
            return True
    except Exception:
        pass
    return False


def _dest_is_removable(dest: Path) -> tuple[bool, str]:
    dest = dest.resolve()
    if _is_plugin_checkout(dest):
        return False, "This directory is the assetrizz source checkout and will not be deleted."
    try:
        home = data_home().resolve()
        if dest == home or dest.is_relative_to(home):
            return True, ""
    except Exception:
        pass
    # Explicit user-chosen dest outside data home: allowed only if it looks like
    # a local library we created (assets/ + db snapshot) and is not a git repo.
    if (dest / ".git").exists():
        return False, "Refusing to delete a git checkout. Remove it yourself if you mean to."
    if is_library_root(dest) or (dest / "assets").is_dir():
        return True, ""
    return False, "The local library directory is empty or is not a library the plugin created."


def library_status() -> dict[str, Any]:
    sizes = load_pack_sizes()
    dest = local_library_dir()
    cache = cache_root()
    local_usage = _dir_usage(dest) if dest.is_dir() else {"files": 0, "bytes": 0}
    cache_usage = _dir_usage(cache)
    present = _count_pngs(dest) if dest.is_dir() else {}
    packs_out = []
    for name, info in sorted((sizes.get("packs") or {}).items()):
        count = int(info.get("count") or 0)
        bytes_ = int(info.get("bytes") or 0)
        have = int(present.get(name) or 0)
        packs_out.append(
            {
                "name": name,
                "count": count,
                "bytes": bytes_,
                "label": format_bytes(bytes_),
                "downloaded": have,
                "complete": bool(count) and have >= count,
            }
        )
    can_remove, reason = _dest_is_removable(dest) if dest.is_dir() else (False, "No local library is installed.")
    optional = resolve_library_optional()
    catalog_ok = True
    catalog_error = ""
    try:
        current_db()
    except Exception as exc:
        catalog_ok = False
        catalog_error = str(exc)
    job = _read_job()
    return {
        "ok": True,
        "asset_mode": asset_mode(),
        "asset_ref": asset_ref(),
        "catalog_ok": catalog_ok,
        "catalog_error": catalog_error,
        "library": str(optional) if optional is not None else "",
        "library_ok": optional is not None,
        "local_library_dir": str(dest),
        "local_present": is_library_root(dest),
        "cache_dir": str(cache),
        "disk": {
            "local_files": local_usage["files"],
            "local_bytes": local_usage["bytes"],
            "local_label": format_bytes(local_usage["bytes"]),
            "cache_files": cache_usage["files"],
            "cache_bytes": cache_usage["bytes"],
            "cache_label": format_bytes(cache_usage["bytes"]),
        },
        "packs": packs_out,
        "total_count": int(sizes.get("total_count") or 0),
        "total_bytes": int(sizes.get("total_bytes") or 0),
        "total_label": format_bytes(int(sizes.get("total_bytes") or 0)),
        "can_remove": can_remove,
        "remove_blocked_reason": reason,
        "job": job,
        "cli": f"python -m {PLUGIN_ID}_plugin.cli",
    }


def _seed_library_root(dest: Path) -> None:
    dest = require_non_root(dest, label="local_library_dir")
    (dest / "assets").mkdir(parents=True, exist_ok=True)
    db_dir = dest / "db"
    db_dir.mkdir(parents=True, exist_ok=True)
    xz = bundled_catalog_xz()
    target = db_dir / "assets.db.xz"
    if xz.is_file() and not target.is_file():
        refuse_denied_write(target, label="local catalog snapshot")
        data = xz.read_bytes()
        import hashlib

        digest = hashlib.sha256(data).hexdigest()
        if digest != BUNDLED_DB_SHA256:
            raise LibraryError(
                "SHA-256 of the bundled catalog snapshot did not match the pin.",
                code="hash_mismatch",
                fix="Reinstall the plugin so plugin/db/assets.db.xz is the pinned snapshot.",
            )
        tmp = target.with_name(target.name + ".partial")
        tmp.write_bytes(data)
        os.replace(tmp, target)
    sidecar = db_dir / "assets.db.xz.sha256"
    if not sidecar.is_file():
        sidecar.write_text(f"{BUNDLED_DB_SHA256}  assets.db.xz\n", encoding="utf-8")


def _one_file(dest: Path, item: dict[str, str]) -> dict[str, Any]:
    from assetrizz_plugin.fetch import asset_url, fetch_url, normalize_asset_rel

    if _CANCEL.is_set():
        return {"status": "cancelled", "path": item["path"]}
    rel = normalize_asset_rel(item["path"])
    expected = (item.get("sha256") or "").strip().lower()
    target = dest / rel
    try:
        require_non_root(dest, label="local_library_dir")
        if target.exists():
            # Resume: a matching hash counts as done; a mismatch is rewritten.
            if expected and target.is_file() and sha256_file(target) == expected:
                size = target.stat().st_size
                return {"status": "skipped", "path": rel, "bytes": size}
            if target.is_file():
                target.unlink()
        if not expected:
            return {
                "status": "error",
                "path": rel,
                "error": "Catalog is missing a SHA-256 for this asset.",
                "code": "hash_mismatch",
            }
        data = fetch_url(asset_url(rel), expected_sha256=expected)
        target.parent.mkdir(parents=True, exist_ok=True)
        refuse_denied_write(target, label="local library asset")
        tmp = target.with_name(target.name + ".partial")
        try:
            tmp.write_bytes(data)
            os.replace(tmp, target)
        except Exception:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
            raise
        return {"status": "fetched", "path": rel, "bytes": len(data)}
    except (LibraryError, FetchError, PathError, ConfigError, OSError) as exc:
        return {
            "status": "error",
            "path": rel,
            "error": str(exc),
            "code": getattr(exc, "code", "fetch_failed"),
        }


def run_download(packs: list[str] | None, *, dest: Path | None = None) -> dict[str, Any]:
    """Download selected packs into dest, resuming files whose SHA-256 already matches.

    Intended for the CLI (foreground) and the pane worker thread — not a model tool.
    """
    chosen = _normalize_packs(packs)
    estimate = estimate_packs(chosen)
    target = require_non_root(dest or local_library_dir(), label="local_library_dir")
    if _is_plugin_checkout(target):
        raise InstallError(
            "Refusing to download into the assetrizz source checkout.",
            code="path_escape",
            fix="Set local_library_dir (or --dest) to a folder under the plugin data directory.",
        )
    refuse_denied_write(target, label="local_library_dir")
    _CANCEL.clear()
    items = _list_assets(estimate["packs"] if not estimate["all"] else ["*"])
    job = {
        "ok": True,
        "status": "running",
        "packs": estimate["packs"],
        "all": estimate["all"],
        "dest": str(target),
        "total": len(items),
        "done": 0,
        "fetched": 0,
        "skipped": 0,
        "errors": 0,
        "bytes": 0,
        "error_items": [],
        "started_at": time.time(),
        "finished_at": None,
        "cancel_requested": False,
        "message": f"Downloading {estimate['count']} assets (~{estimate['label']}).",
    }
    _write_job(job)
    try:
        _seed_library_root(target)
        if not items:
            job["status"] = "done"
            job["message"] = "Nothing to download for the selected packs."
            job["finished_at"] = time.time()
            return _write_job(job)

        def _bump(result: dict[str, Any]) -> None:
            job["done"] = int(job["done"]) + 1
            status = result.get("status")
            if status == "fetched":
                job["fetched"] = int(job["fetched"]) + 1
                job["bytes"] = int(job["bytes"]) + int(result.get("bytes") or 0)
            elif status == "skipped":
                job["skipped"] = int(job["skipped"]) + 1
                job["bytes"] = int(job["bytes"]) + int(result.get("bytes") or 0)
            elif status == "error":
                job["errors"] = int(job["errors"]) + 1
                errs = list(job["error_items"])
                if len(errs) < 12:
                    errs.append({"path": result.get("path"), "error": result.get("error")})
                    job["error_items"] = errs
            if _CANCEL.is_set():
                job["cancel_requested"] = True
            # Keep the pane updated without writing every single file.
            if int(job["done"]) == 1 or int(job["done"]) % 8 == 0 or int(job["done"]) == int(job["total"]):
                _write_job(job)

        workers = min(MAX_CONCURRENCY, max(1, len(items)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_one_file, target, item) for item in items]
            for future in as_completed(futures):
                if _CANCEL.is_set():
                    for pending in futures:
                        pending.cancel()
                    break
                try:
                    result = future.result()
                except Exception as exc:  # pragma: no cover - worker already catches
                    result = {"status": "error", "path": "", "error": str(exc)}
                _bump(result)
        if _CANCEL.is_set():
            job["status"] = "cancelled"
            job["message"] = "Download cancelled. Already-verified files were kept so you can resume."
        elif int(job["errors"]) and int(job["fetched"]) + int(job["skipped"]) == 0:
            job["status"] = "error"
            job["ok"] = False
            job["message"] = "Download failed. See error_items."
        else:
            job["status"] = "done"
            job["message"] = (
                f"Finished: {job['fetched']} downloaded, {job['skipped']} already present, "
                f"{job['errors']} failed, {format_bytes(int(job['bytes']))} on disk this run."
            )
        job["finished_at"] = time.time()
        return _write_job(job)
    except Exception as exc:
        job["status"] = "error"
        job["ok"] = False
        job["error"] = str(exc)
        job["code"] = getattr(exc, "code", "fetch_failed")
        job["finished_at"] = time.time()
        _write_job(job)
        raise


def start_download(packs: list[str] | None, *, dest: Path | None = None) -> dict[str, Any]:
    """Start a background download if none is running. Used by the pane."""
    global _WORKER
    with _JOB_LOCK:
        current = _read_job()
        if current.get("status") == "running" and _WORKER is not None and _WORKER.is_alive():
            raise InstallError(
                "A library download is already running.",
                code="invalid_args",
                fix="Wait for it to finish, or click Cancel and start again.",
            )
        estimate = estimate_packs(packs)
        target = require_non_root(dest or local_library_dir(), label="local_library_dir")

        def _run() -> None:
            try:
                run_download(estimate["packs"] if not estimate["all"] else ["*"], dest=target)
            except Exception:
                pass

        _WORKER = threading.Thread(target=_run, name="assetrizz-library-download", daemon=True)
        _WORKER.start()
        return {
            "ok": True,
            "status": "starting",
            "packs": estimate["packs"],
            "all": estimate["all"],
            "count": estimate["count"],
            "bytes": estimate["bytes"],
            "label": estimate["label"],
            "dest": str(target),
            "message": f"Starting download of {estimate['count']} assets (~{estimate['label']}).",
        }


def cancel_download() -> dict[str, Any]:
    _CANCEL.set()
    job = _read_job()
    job["cancel_requested"] = True
    if job.get("status") == "running":
        job["message"] = "Cancel requested. Already-verified files will be kept."
        _write_job(job)
    return {"ok": True, "status": job.get("status") or "idle", "job": job}


def remove_local_library(*, confirm: bool, dest: Path | None = None) -> dict[str, Any]:
    if not confirm:
        raise InstallError(
            "Deletion needs confirmation.",
            code="invalid_args",
            fix="In the pane, click Remove local library and then Confirm delete. On the CLI, pass --yes.",
        )
    current = _read_job()
    if current.get("status") == "running":
        raise InstallError(
            "A library download is running; cancel it before removing the folder.",
            code="invalid_args",
            fix="Click Cancel, wait for the job to stop, then remove the library.",
        )
    target = require_non_root(dest or local_library_dir(), label="local_library_dir")
    if not target.exists():
        return {"ok": True, "removed": False, "message": "No local library directory is present."}
    allowed, reason = _dest_is_removable(target)
    if not allowed:
        raise InstallError(reason, code="path_escape", fix="Choose a different local_library_dir, or delete it yourself.")
    refuse_denied_write(target, label="local_library_dir")
    shutil.rmtree(target)
    from assetrizz_plugin.library import reset_cache

    reset_cache()
    return {
        "ok": True,
        "removed": True,
        "path": str(target),
        "message": f"Removed the local library at {target}.",
    }


def clear_cache(*, confirm: bool) -> dict[str, Any]:
    if not confirm:
        raise InstallError(
            "Clearing the on-demand cache needs confirmation.",
            code="invalid_args",
            fix="Pass confirm=true, or use the pane's clear-cache control.",
        )
    root = cache_root()
    usage = _dir_usage(root)
    if root.is_dir():
        refuse_denied_write(root, label="cache")
        shutil.rmtree(root)
        root.mkdir(parents=True, exist_ok=True)
    return {
        "ok": True,
        "removed": True,
        "path": str(root),
        "files": usage["files"],
        "bytes": usage["bytes"],
        "message": f"Cleared the on-demand cache ({format_bytes(usage['bytes'])}).",
    }
