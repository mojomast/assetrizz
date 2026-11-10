from __future__ import annotations

from pathlib import Path

import pytest

from assetrizz_plugin.paths import PathError, confine, data_home, is_fs_root, require_non_root


def test_data_home_uses_assetrizz_home(plugin_env):
    assert data_home() == plugin_env["data"].resolve()


def test_confine_rejects_escape(plugin_env, tmp_path):
    root = plugin_env["library"]
    inside = confine(root / "assets" / "pixel_32" / "tiles" / "floor" / "grass_base.png", root)
    assert inside.is_file()
    with pytest.raises(PathError) as exc:
        confine(tmp_path / "outside.png", root, label="asset")
    assert exc.value.code == "path_escape"


def test_confine_rejects_dotdot(plugin_env, tmp_path):
    root = plugin_env["library"]
    with pytest.raises(PathError):
        confine(root / "assets" / ".." / ".." / ".." / "etc" / "passwd", root)


def test_symlink_escape_rejected(plugin_env, tmp_path):
    root = plugin_env["library"]
    target = tmp_path / "secret.png"
    target.write_bytes(b"nope")
    link = root / "assets" / "escape.png"
    link.symlink_to(target)
    with pytest.raises(PathError):
        confine(link, root / "assets")


def test_filesystem_root_rejected(tmp_path):
    with pytest.raises(PathError):
        require_non_root(Path("/"))
    assert is_fs_root(Path("/"))
