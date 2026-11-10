"""Library path, asset mode, and export dir resolution.

Search uses a bundled catalog. PNGs come from a local library, an on-demand
cache, or a user-initiated local download — never from a tool argument.
"""

from __future__ import annotations

import os
from pathlib import Path

from assetrizz_plugin import ASSET_REF, PLUGIN_ID
from assetrizz_plugin.paths import PathError, data_home, ensure_layout, require_non_root

ENV_LIBRARY = "ASSETRIZZ_LIBRARY"
ENV_EXPORT = "ASSETRIZZ_EXPORT_DIR"
ENV_ASSET_REF = "ASSETRIZZ_ASSET_REF"
ENV_ASSET_MODE = "ASSETRIZZ_ASSET_MODE"
ENV_LOCAL_LIBRARY = "ASSETRIZZ_LOCAL_LIBRARY"

# Explicit values that skip checkout discovery so tests and catalog installs
# can force bundled-db + fetch/cache mode even when this file lives in a clone.
SKIP_LIBRARY_DISCOVERY = frozenset({"none", "off", "bundled", "0", "false"})
ASSET_MODES = ("on_demand", "local", "offline")

_PLUGIN_DIR = Path(__file__).resolve().parent


class ConfigError(ValueError):
    def __init__(self, message: str, *, code: str = "library_missing", fix: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.fix = fix


def _hermes_setting(key: str) -> str | None:
    """Read plugins.entries.assetrizz.settings.<key> when the host API exists.

    Uses documented ``load_config_readonly()`` and walks the public config
    tree. Does not import private helpers.
    """
    try:
        from hermes_cli.config import load_config_readonly  # type: ignore
    except Exception:
        return None
    try:
        cfg = load_config_readonly() or {}
        if not isinstance(cfg, dict):
            return None
        plugins = cfg.get("plugins") if isinstance(cfg.get("plugins"), dict) else {}
        entries = plugins.get("entries") if isinstance(plugins.get("entries"), dict) else {}
        entry = entries.get(PLUGIN_ID) if isinstance(entries.get(PLUGIN_ID), dict) else {}
        settings = entry.get("settings") if isinstance(entry.get("settings"), dict) else {}
        value = settings.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (int, float, bool)):
            return str(value)
    except Exception:
        return None
    return None


def asset_ref() -> str:
    raw = os.environ.get(ENV_ASSET_REF)
    if raw and str(raw).strip():
        return str(raw).strip()
    setting = _hermes_setting("asset_ref")
    if setting:
        return setting
    return ASSET_REF


def asset_mode() -> str:
    raw = os.environ.get(ENV_ASSET_MODE)
    if raw and str(raw).strip():
        token = str(raw).strip().lower().replace("-", "_")
    else:
        setting = _hermes_setting("asset_mode")
        token = (setting or "on_demand").strip().lower().replace("-", "_")
    if token not in ASSET_MODES:
        raise ConfigError(
            f"asset_mode must be one of {', '.join(ASSET_MODES)} (got {token!r}).",
            code="invalid_args",
            fix="Set asset_mode to on_demand (default), local, or offline.",
        )
    return token


def is_library_root(path: Path) -> bool:
    """True when ``path`` looks like an assetrizz library root."""
    try:
        resolved = path.expanduser().resolve()
    except Exception:
        return False
    assets = resolved / "assets"
    if not assets.is_dir():
        return False
    return (resolved / "db" / "assets.db.xz").is_file() or (resolved / "db" / "assets.db").is_file()


def discover_library(start: Path | None = None) -> Path | None:
    """Walk upward from the plugin package looking for a checkout with assets + db."""
    here = start if start is not None else _PLUGIN_DIR
    candidates = [here, *here.parents]
    for candidate in candidates:
        if is_library_root(candidate):
            return candidate.resolve()
    return None


def _skip_discovery(token: str) -> bool:
    return token.strip().lower() in SKIP_LIBRARY_DISCOVERY


def local_library_dir() -> Path:
    """User-chosen (or default) directory for a local library download.

    The directory does not have to exist until the user starts a download.
    """
    raw = os.environ.get(ENV_LOCAL_LIBRARY)
    if raw and str(raw).strip():
        path = Path(raw).expanduser()
        return require_non_root(path, label=ENV_LOCAL_LIBRARY)
    setting = _hermes_setting("local_library_dir")
    if setting:
        path = Path(setting).expanduser()
        return require_non_root(path, label="local_library_dir")
    return require_non_root(data_home() / "library", label="local_library_dir")


def resolve_library_optional() -> Path | None:
    """Locate a complete on-disk library, or None when the bundled catalog is enough."""
    raw = os.environ.get(ENV_LIBRARY)
    if raw and str(raw).strip():
        token = str(raw).strip()
        if _skip_discovery(token):
            return None
        path = Path(token).expanduser()
        resolved = require_non_root(path, label=ENV_LIBRARY)
        if not is_library_root(resolved):
            raise ConfigError(
                f"{ENV_LIBRARY} is {resolved}, but that folder has no assets/ and db/assets.db.xz.",
                code="library_missing",
                fix="Point ASSETRIZZ_LIBRARY at an assetrizz clone, download the library from the pane, or set it to none.",
            )
        return resolved
    setting = _hermes_setting("library_path")
    if setting:
        if _skip_discovery(setting):
            return None
        path = Path(setting).expanduser()
        resolved = require_non_root(path, label="library_path")
        if not is_library_root(resolved):
            raise ConfigError(
                f"library_path is {resolved}, but that folder has no assets/ and db/assets.db.xz.",
                code="library_missing",
                fix="Set Library path to a complete clone, or leave it empty and use on-demand fetch.",
            )
        return resolved
    local = local_library_dir()
    if is_library_root(local):
        return local
    discovered = discover_library()
    if discovered is not None:
        return discovered
    return None


def resolve_library() -> Path:
    """Locate a complete on-disk library, or raise with a helpful fix."""
    found = resolve_library_optional()
    if found is not None:
        return found
    raise ConfigError(
        "No complete local assetrizz library is installed. Search still works from the bundled catalog; "
        "PNGs are fetched on demand or from a user-installed local library.",
        code="library_missing",
        fix=(
            "Leave asset_mode at on_demand to fetch single PNGs as you place them, or click "
            "Download library in the Assetrizz pane (or run python -m assetrizz_plugin.cli download)."
        ),
    )


def resolve_export_dir() -> Path:
    """Directory for rendered PNG and saved scene JSON copies requested by the agent."""
    raw = os.environ.get(ENV_EXPORT)
    if raw and str(raw).strip():
        return _prepare_export(Path(raw).expanduser(), label=ENV_EXPORT)
    setting = _hermes_setting("export_dir")
    if setting:
        return _prepare_export(Path(setting).expanduser(), label="export_dir")
    return _prepare_export(data_home() / "exports", label="export_dir")


def _prepare_export(path: Path, label: str) -> Path:
    resolved = require_non_root(path, label=label)
    try:
        resolved.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise PathError(f"Cannot create {label} at {resolved}: {exc}", code="path_escape") from exc
    return resolved


def library_assets_root(library: Path | None = None) -> Path:
    root = (library or resolve_library()) / "assets"
    if not root.is_dir():
        raise ConfigError(
            f"Library has no assets/ folder at {root}.",
            code="library_missing",
            fix="Re-download the library from the pane, or check the Library path setting.",
        )
    return require_non_root(root, label="assets")


def data_root() -> Path:
    return ensure_layout()
