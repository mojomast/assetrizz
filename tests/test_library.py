from __future__ import annotations

import lzma
from pathlib import Path

import pytest

from assetrizz_plugin.library import (
    LibraryError,
    asset_file,
    get_asset,
    reset_cache,
    restore_db,
    search,
    stats,
)
from assetrizz_plugin.paths import PathError


def test_search_fts_and_filters(plugin_env):
    grass = search("grass", style="pixel_32", category="tiles")
    assert grass["ok"] is True
    assert grass["total"] == 1
    assert grass["items"][0]["slug"] == "pixel_32/tiles/floor/grass_base"
    assert grass["items"][0]["path"].startswith("assets/")
    assert ".." not in grass["items"][0]["path"]
    crates = search("crate")
    slugs = {item["slug"] for item in crates["items"]}
    assert "pixel_32/props/object/crate_plain" in slugs
    only_tiles = search(category="tiles", tileable=True)
    assert only_tiles["total"] == 2
    styled = search(style="cozy_cartoon")
    assert styled["total"] == 1


def test_get_asset_by_id_and_slug(plugin_env):
    by_id = get_asset(asset_id=3)
    assert by_id["asset"]["slug"] == "pixel_32/props/object/crate_plain"
    assert by_id["asset"]["exists"] is True
    by_slug = get_asset(slug="pixel_32/characters/humanoid/ranger_front")
    assert by_slug["asset"]["id"] == 4
    missing = get_asset(slug="cozy_cartoon/props/object/crate_plain")
    assert missing["asset"]["exists"] is False


def test_get_unknown_asset(plugin_env):
    with pytest.raises(LibraryError) as exc:
        get_asset(slug="no/such/asset")
    assert exc.value.code == "not_found"


def test_asset_file_rejects_traversal(plugin_env):
    with pytest.raises((LibraryError, PathError)):
        asset_file("../etc/passwd")
    with pytest.raises((LibraryError, PathError)):
        asset_file("/etc/passwd")


def test_stats(plugin_env):
    info = stats()
    assert info["total_ok"] == 5
    names = {row["name"] for row in info["styles"]}
    assert "pixel_32" in names
    assert info["library"] == str(plugin_env["library"].resolve()) or Path(info["library"]).resolve() == plugin_env["library"].resolve()


def test_restore_db_from_xz(plugin_env, tmp_path):
    library = tmp_path / "lib"
    (library / "assets").mkdir(parents=True)
    (library / "db").mkdir()
    src = plugin_env["library"] / "db" / "assets.db"
    dest_xz = library / "db" / "assets.db.xz"
    dest_xz.write_bytes(lzma.compress(src.read_bytes()))
    fallback = tmp_path / "data" / "assets.db"
    restored = restore_db(library, fallback)
    assert restored.is_file()
    assert restored == library / "db" / "assets.db"
    # Second call must not overwrite
    stamp = restored.stat().st_mtime
    again = restore_db(library, fallback)
    assert again == restored
    # If local db exists, leave it
    assert again.stat().st_mtime == stamp
