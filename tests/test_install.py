from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from assetrizz_plugin.errors import LibraryError
from assetrizz_plugin.fetch import asset_url, set_fetcher
from assetrizz_plugin.install import (
    cancel_download,
    clear_cache,
    estimate_packs,
    format_bytes,
    library_status,
    load_pack_sizes,
    remove_local_library,
    run_download,
)
from assetrizz_plugin.library import reset_cache
from assetrizz_plugin.pane import library_download, library_remove, library_view
from assetrizz_plugin.tools import TOOL_NAMES, handle_search_safe


def test_pack_sizes_baked():
    sizes = load_pack_sizes()
    assert sizes["total_count"] == 14641
    assert sizes["total_bytes"] > 1_000_000_000
    assert "pixel_32" in sizes["packs"]
    est = estimate_packs(["pixel_32"])
    assert est["count"] == sizes["packs"]["pixel_32"]["count"]
    assert est["label"]
    assert format_bytes(1536) == "1.5 KB"


def test_download_resume_and_hash(plugin_env, monkeypatch, tmp_path):
    monkeypatch.setenv("ASSETRIZZ_OFFLINE", "0")
    monkeypatch.setenv("ASSETRIZZ_LOCAL_LIBRARY", str(tmp_path / "local-lib"))
    # Restrict the catalog list: only copy two fixture rows' files through the mock.
    payloads = {}
    for png in plugin_env["assets"].rglob("*.png"):
        rel = "assets/" + png.relative_to(plugin_env["assets"]).as_posix()
        payloads[rel] = png.read_bytes()
    grass_rel = "assets/pixel_32/tiles/floor/grass_base.png"

    def _fetch(url: str) -> bytes:
        for rel, data in payloads.items():
            if url.endswith("/" + rel) or rel.split("/")[-1] in url:
                return data
        raise AssertionError(f"unexpected url {url}")

    set_fetcher(_fetch)
    # Pre-seed one file so resume skips it.
    dest = tmp_path / "local-lib"
    already = dest / grass_rel
    already.parent.mkdir(parents=True, exist_ok=True)
    already.write_bytes(payloads[grass_rel])
    try:
        result = run_download(["pixel_32"], dest=dest)
        assert result["status"] == "done"
        assert result["skipped"] >= 1
        assert result["fetched"] >= 1
        crate_out = dest / "assets/pixel_32/props/object/crate_plain.png"
        assert crate_out.is_file()
        assert hashlib.sha256(crate_out.read_bytes()).hexdigest() == hashlib.sha256(
            payloads["assets/pixel_32/props/object/crate_plain.png"]
        ).hexdigest()
        assert result["errors"] == 0
        # Resume everything: second run is all skipped, no errors.
        again = run_download(["pixel_32"], dest=dest)
        assert again["status"] == "done"
        assert again["fetched"] == 0
        assert again["skipped"] >= 2
        assert again["errors"] == 0
        # Destination is a library root (seeded catalog snapshot + assets).
        assert (dest / "db" / "assets.db.xz").is_file() or (dest / "db" / "assets.db").is_file()
    finally:
        set_fetcher(lambda url: (_ for _ in ()).throw(AssertionError("fetch")))
        monkeypatch.setenv("ASSETRIZZ_OFFLINE", "1")


def test_download_hash_mismatch_is_not_kept(plugin_env, monkeypatch, tmp_path):
    monkeypatch.setenv("ASSETRIZZ_OFFLINE", "0")
    dest = tmp_path / "lib"
    set_fetcher(lambda url: b"not-a-real-png")
    try:
        result = run_download(["pixel_32"], dest=dest)
        # Fixture packs have sha256; every fetch should fail verification.
        assert result["fetched"] == 0
        assert result["errors"] >= 1
        pngs = list(dest.rglob("*.png")) if dest.exists() else []
        assert pngs == []
    finally:
        set_fetcher(lambda url: (_ for _ in ()).throw(AssertionError("fetch")))
        monkeypatch.setenv("ASSETRIZZ_OFFLINE", "1")


def test_remove_requires_confirmation_and_skips_checkout(plugin_env, tmp_path, monkeypatch):
    with pytest.raises(LibraryError) as exc:
        remove_local_library(confirm=False)
    assert exc.value.code == "invalid_args"

    checkout = tmp_path / "repo"
    (checkout / "plugin" / "assetrizz_plugin").mkdir(parents=True)
    (checkout / "plugin" / "plugin.yaml").write_text("name: assetrizz\n", encoding="utf-8")
    (checkout / "assets").mkdir()
    (checkout / ".git").mkdir()
    monkeypatch.setenv("ASSETRIZZ_LOCAL_LIBRARY", str(checkout))
    reset_cache()
    with pytest.raises(LibraryError) as exc:
        remove_local_library(confirm=True, dest=checkout)
    assert exc.value.code == "path_escape"
    assert (checkout / "plugin" / "plugin.yaml").is_file()

    safe = tmp_path / "data-lib"
    safe.mkdir()
    (safe / "assets").mkdir()
    (safe / "keep.png").write_text("x", encoding="utf-8")
    monkeypatch.setenv("ASSETRIZZ_LOCAL_LIBRARY", str(safe))
    # default dest under plugin data is allowed; this explicit dest looks like a library and has no .git
    gone = remove_local_library(confirm=True, dest=safe)
    assert gone["removed"] is True
    assert not safe.exists()


def test_pane_library_routes_and_no_model_tool(plugin_env, monkeypatch, tmp_path):
    status = library_view()
    assert status["ok"] is True
    assert status["total_count"] == 14641
    assert "pixel_32" in {row["name"] for row in status["packs"]}
    # Removal without confirm is refused.
    refused = library_remove({"confirm": False})
    assert refused["ok"] is False
    # Bulk download is not a registered tool.
    assert "assetrizz_download" not in TOOL_NAMES
    assert "prefetch" not in json.dumps(TOOL_NAMES)
    raw = handle_search_safe({"op": "prefetch"})
    body = json.loads(raw)
    assert body["ok"] is False
    assert body["code"] == "invalid_op"
    # Starting a download is a pane helper, not a tool, and uses the mock fetcher.
    monkeypatch.setenv("ASSETRIZZ_OFFLINE", "0")
    monkeypatch.setenv("ASSETRIZZ_LOCAL_LIBRARY", str(tmp_path / "pane-lib"))
    by_name = {png.name: png.read_bytes() for png in plugin_env["assets"].rglob("*.png")}
    set_fetcher(lambda url: next(data for name, data in by_name.items() if name in url))
    try:
        started = library_download({"packs": ["pixel_32"]})
        assert started["ok"] is True
        assert started["status"] in {"starting", "running", "done"}
        from assetrizz_plugin import install as install_mod

        if install_mod._WORKER is not None:
            install_mod._WORKER.join(timeout=8)
        cancel_download()
    finally:
        set_fetcher(lambda url: (_ for _ in ()).throw(AssertionError("fetch")))
        monkeypatch.setenv("ASSETRIZZ_OFFLINE", "1")


def test_clear_cache_requires_confirm(plugin_env):
    with pytest.raises(LibraryError):
        clear_cache(confirm=False)
    result = clear_cache(confirm=True)
    assert result["ok"] is True


def test_status_reports_disk(plugin_env):
    info = library_status()
    assert info["asset_mode"] == "on_demand"
    assert info["disk"]["local_label"]
    assert info["catalog_ok"] is True
