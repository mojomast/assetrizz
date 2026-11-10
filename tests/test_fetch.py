from __future__ import annotations

import hashlib
import lzma
from pathlib import Path

import pytest

from assetrizz_plugin import ASSET_HOST, ASSET_REF, BUNDLED_DB_SHA256
from assetrizz_plugin.errors import FetchError, LibraryError
from assetrizz_plugin.fetch import (
    assert_allowlisted,
    asset_url,
    fetch_url,
    is_allowlisted_url,
    normalize_asset_rel,
    set_fetcher,
    sha256_bytes,
)
from assetrizz_plugin.library import ensure_asset_file, locate_asset_file, reset_cache, restore_catalog_xz, search


def test_normalize_and_allowlist():
    assert normalize_asset_rel("pixel_32/tiles/floor/grass_base.png") == "assets/pixel_32/tiles/floor/grass_base.png"
    assert normalize_asset_rel("assets/pixel_32/a.png") == "assets/pixel_32/a.png"
    with pytest.raises(FetchError) as exc:
        normalize_asset_rel("../etc/passwd")
    assert exc.value.code == "path_escape"
    with pytest.raises(FetchError):
        normalize_asset_rel("/etc/passwd")
    url = asset_url("assets/pixel_32/tiles/floor/grass_base.png")
    assert url.startswith(f"https://{ASSET_HOST}/mojomast/assetrizz/{ASSET_REF}/assets/")
    assert url.endswith("/grass_base.png")
    assert is_allowlisted_url(url)
    with pytest.raises(FetchError):
        assert_allowlisted("https://example.com/assets/x.png")
    with pytest.raises(FetchError):
        assert_allowlisted(url.replace("/assets/", "/docs/"))
    with pytest.raises(FetchError):
        assert_allowlisted("http://" + ASSET_HOST + "/mojomast/assetrizz/v0.1.0/assets/x.png")


def test_fetch_url_verifies_hash_via_mock():
    payload = b"\x89PNG\r\n\x1a\n" + b"ok"
    digest = sha256_bytes(payload)
    url = asset_url("assets/pixel_32/demo.png")
    set_fetcher(lambda u: payload if u == url else b"nope")
    try:
        assert fetch_url(url, expected_sha256=digest) == payload
        with pytest.raises(FetchError) as exc:
            fetch_url(url, expected_sha256="0" * 64)
        assert exc.value.code == "hash_mismatch"
    finally:
        set_fetcher(None)


def test_ensure_asset_file_fetches_into_cache(plugin_env, monkeypatch):
    monkeypatch.setenv("ASSETRIZZ_OFFLINE", "0")
    monkeypatch.setenv("ASSETRIZZ_ASSET_MODE", "on_demand")
    # Hide the fixture file so the code must fetch.
    rel = "assets/pixel_32/tiles/floor/grass_base.png"
    original = plugin_env["library"] / rel
    payload = original.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    original.unlink()
    reset_cache()
    calls = []

    def _fetch(url: str) -> bytes:
        calls.append(url)
        return payload

    set_fetcher(_fetch)
    try:
        path = ensure_asset_file(rel, digest)
        assert path.is_file()
        assert path.read_bytes() == payload
        assert "cache" in path.parts
        assert calls and is_allowlisted_url(calls[0])
        # Second call hits the cache, no extra fetch.
        again = ensure_asset_file(rel, digest)
        assert again == path
        assert len(calls) == 1
    finally:
        set_fetcher(lambda url: (_ for _ in ()).throw(AssertionError("fetch")))
        monkeypatch.setenv("ASSETRIZZ_OFFLINE", "1")


def test_offline_mode_does_not_fetch(plugin_env, monkeypatch):
    monkeypatch.setenv("ASSETRIZZ_ASSET_MODE", "offline")
    monkeypatch.setenv("ASSETRIZZ_OFFLINE", "0")
    rel = "assets/pixel_32/tiles/floor/grass_base.png"
    payload = (plugin_env["library"] / rel).read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    (plugin_env["library"] / rel).unlink()
    reset_cache()
    set_fetcher(lambda url: payload)
    try:
        with pytest.raises(LibraryError) as exc:
            ensure_asset_file(rel, digest)
        assert exc.value.code == "offline"
        assert locate_asset_file(rel, digest) is None
    finally:
        set_fetcher(lambda url: (_ for _ in ()).throw(AssertionError("fetch")))
        monkeypatch.setenv("ASSETRIZZ_OFFLINE", "1")
        monkeypatch.setenv("ASSETRIZZ_ASSET_MODE", "on_demand")


def test_restore_catalog_xz_verifies_pin(tmp_path):
    src = tmp_path / "mini.db"
    src.write_bytes(b"sqlite-placeholder")
    xz = tmp_path / "mini.db.xz"
    data = lzma.compress(src.read_bytes())
    xz.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    dest = tmp_path / "out" / "assets.db"
    restored = restore_catalog_xz(xz, dest, digest)
    assert restored == dest
    assert dest.read_bytes() == src.read_bytes()
    # Existing dest is left alone.
    dest.write_bytes(b"keep")
    again = restore_catalog_xz(xz, dest, digest)
    assert again.read_bytes() == b"keep"
    # Bad pin
    dest2 = tmp_path / "out2" / "assets.db"
    with pytest.raises(LibraryError) as exc:
        restore_catalog_xz(xz, dest2, "0" * 64)
    assert exc.value.code == "hash_mismatch"
    assert not dest2.exists()


def test_search_still_works_when_png_missing(plugin_env):
    found = search("grass")
    assert found["total"] == 1


def test_bundled_pin_constant_matches_sidecar():
    sidecar = Path(__file__).resolve().parents[1] / "plugin" / "db" / "assets.db.xz.sha256"
    text = sidecar.read_text(encoding="utf-8").split()[0].strip().lower()
    assert text == BUNDLED_DB_SHA256
