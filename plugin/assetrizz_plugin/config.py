"""Library path and export dir resolution.

The library is the assetrizz checkout (or a separate download) that contains
``assets/`` and ``db/assets.db.xz``. It is never chosen from a tool argument.
"""

from __future__ import annotations

import os
from pathlib import Path

from assetrizz_plugin import PLUGIN_ID
from assetrizz_plugin.paths import PathError, data_home, ensure_layout, require_non_root

ENV_LIBRARY = "ASSETRIZZ_LIBRARY"
ENV_EXPORT = "ASSETRIZZ_EXPORT_DIR"

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
    except Exception:
        return None
    return None


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


def resolve_library() -> Path:
    """Locate the asset library. Env, then Hermes settings, then checkout discovery."""
    raw = os.environ.get(ENV_LIBRARY)
    if raw and str(raw).strip():
        path = Path(raw).expanduser()
        resolved = require_non_root(path, label=ENV_LIBRARY)
        if not is_library_root(resolved):
            raise ConfigError(
                f"{ENV_LIBRARY} is {resolved}, but that folder has no assets/ and db/assets.db.xz.",
                code="library_missing",
                fix="Point ASSETRIZZ_LIBRARY at an assetrizz clone, or run bash db/restore.sh there.",
            )
        return resolved
    setting = _hermes_setting("library_path")
    if setting:
        path = Path(setting).expanduser()
        resolved = require_non_root(path, label="library_path")
        if not is_library_root(resolved):
            raise ConfigError(
                f"library_path is {resolved}, but that folder has no assets/ and db/assets.db.xz.",
                code="library_missing",
                fix="Set Settings → Plugins → assetrizz → Library path to your assetrizz clone.",
            )
        return resolved
    discovered = discover_library()
    if discovered is not None:
        return discovered
    raise ConfigError(
        "No assetrizz library found. The plugin reads assets from a repo clone or download; "
        "it does not bundle the 14,641 PNGs.",
        code="library_missing",
        fix=(
            "Clone https://github.com/mojomast/assetrizz and set the Library path setting "
            f"or {ENV_LIBRARY} to that folder."
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
            fix="Re-clone assetrizz or check the Library path setting.",
        )
    return require_non_root(root, label="assets")


def data_root() -> Path:
    return ensure_layout()
