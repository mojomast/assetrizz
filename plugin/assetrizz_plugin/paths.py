"""Plugin data directory and path confinement.

State lives under the Hermes plugin data dir (overridable with ASSETRIZZ_HOME).
Every path used by tools or the pane is resolved, including symlinks, and must
stay inside an explicit root. A filesystem root is never a legal root.
"""

from __future__ import annotations

import os
from pathlib import Path

from assetrizz_plugin import PLUGIN_ID

ENV_HOME = "ASSETRIZZ_HOME"


class PathError(ValueError):
    """A path escaped its root, was empty, or the root was a filesystem root."""

    def __init__(self, message: str, *, code: str = "path_escape") -> None:
        super().__init__(message)
        self.code = code


def is_fs_root(path: Path) -> bool:
    resolved = path.expanduser().resolve()
    return resolved == Path(resolved.anchor).resolve()


def require_non_root(path: Path, label: str = "path") -> Path:
    resolved = path.expanduser().resolve()
    if is_fs_root(resolved):
        raise PathError(
            f"{label} must not be a filesystem root ({resolved}). "
            "Choose a directory under your home or plugin data folder.",
            code="path_escape",
        )
    return resolved


def _data_home_fallback() -> Path:
    """Profile-neutral fallback when Hermes APIs are unavailable.

    Does not read the host home environment variable and does not hardcode
    the default Hermes config directory. Prefer get_hermes_home() when the
    host APIs are present (see _hermes_plugin_data_dir).
    """
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg and str(xdg).strip():
        return Path(xdg).expanduser() / "hermes-plugins" / PLUGIN_ID
    return Path.home() / ".local" / "share" / "hermes-plugins" / PLUGIN_ID


def _hermes_plugin_data_dir() -> Path | None:
    """Ask the host for a profile-aware plugin data dir when the API exists.

    Prefers the documented ``plugins.plugin_storage.plugin_data_dir`` and
    ``hermes_constants.get_hermes_home()``. Does not import hermes_cli internals.
    """
    try:
        from plugins.plugin_storage import plugin_data_dir as storage_dir  # type: ignore
    except Exception:
        storage_dir = None
    if callable(storage_dir):
        try:
            path = storage_dir(PLUGIN_ID)
        except Exception:
            path = None
        if path:
            return Path(path)
    try:
        from hermes_constants import get_hermes_home  # type: ignore
    except Exception:
        return None
    try:
        home = get_hermes_home()
    except Exception:
        return None
    if home:
        return Path(home) / "plugin-data" / PLUGIN_ID
    return None


def data_home() -> Path:
    """Resolved plugin data root (ASSETRIZZ_HOME wins)."""
    raw = os.environ.get(ENV_HOME)
    if raw and str(raw).strip():
        path = Path(raw).expanduser()
    else:
        path = _hermes_plugin_data_dir() or _data_home_fallback()
    return require_non_root(path, label=ENV_HOME)


def ensure_layout(root: Path | None = None) -> Path:
    """Create scenes/, exports/, previews/, cache/, and catalog/ under the data root."""
    root = Path(root).resolve() if root is not None else data_home()
    root = require_non_root(root, label="data home")
    for name in ("scenes", "exports", "previews", "cache", "catalog"):
        (root / name).mkdir(parents=True, exist_ok=True)
    return root


def confine(
    path: str | os.PathLike[str] | Path,
    root: Path,
    label: str = "path",
) -> Path:
    """Resolve ``path`` (follow symlinks) and refuse anything outside ``root``."""
    root = require_non_root(Path(root), label="root")
    if not str(path).strip():
        raise PathError(
            f"{label} is empty. Choose a path inside {root}.",
            code="path_escape",
        )
    resolved = Path(path).expanduser().resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise PathError(
            f"{label} must stay inside {root}. "
            f"{path} resolves to {resolved}, which is outside that folder.",
            code="path_escape",
        ) from exc
    return resolved


def relative_posix(path: Path, root: Path) -> str:
    return confine(path, root).relative_to(root.resolve()).as_posix()


def write_denied(path: Path) -> str | None:
    """Hermes write-denylist verdict, or None when the host API is absent."""
    try:
        from agent.file_safety import get_write_denied_error  # type: ignore
    except Exception:
        return None
    try:
        return get_write_denied_error(str(path))
    except Exception:
        return None


def refuse_denied_write(path: Path, label: str = "path") -> Path:
    """Raise PathError when the host refuses writes to this path."""
    denied = write_denied(path)
    if denied:
        raise PathError(str(denied), code="path_escape")
    return path
