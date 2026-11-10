"""Temp library + plugin data dir for assetrizz plugin tests."""

from __future__ import annotations

import os
import sqlite3
import sys
import hashlib
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugin"
if str(PLUGIN) not in sys.path:
    sys.path.insert(0, str(PLUGIN))


SCHEMA = """
CREATE TABLE assets (
  id INTEGER PRIMARY KEY,
  slug TEXT NOT NULL,
  path TEXT NOT NULL,
  thumb_path TEXT,
  category TEXT,
  subcategory TEXT,
  subject TEXT,
  style_pack TEXT,
  tags TEXT,
  description TEXT,
  width INTEGER,
  height INTEGER,
  has_alpha INTEGER,
  palette TEXT,
  dominant_colors TEXT,
  tileable INTEGER,
  pivot TEXT,
  frame_info TEXT,
  license TEXT,
  status TEXT,
  qa_notes TEXT,
  sha256 TEXT
);
CREATE VIRTUAL TABLE assets_fts USING fts5(
  slug, description, tags, subject, category, subcategory, style_pack,
  content='assets', content_rowid='id'
);
CREATE TRIGGER assets_ai AFTER INSERT ON assets BEGIN
  INSERT INTO assets_fts(rowid, slug, description, tags, subject, category, subcategory, style_pack)
  VALUES (new.id, new.slug, new.description, new.tags, new.subject, new.category, new.subcategory, new.style_pack);
END;
"""


def _png(path: Path, color: tuple[int, int, int, int], size: int = 16) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (size, size), color).save(path)


def _insert(conn: sqlite3.Connection, **row) -> None:
    keys = list(row)
    conn.execute(
        f"INSERT INTO assets ({', '.join(keys)}) VALUES ({', '.join('?' for _ in keys)})",
        [row[k] for k in keys],
    )


@pytest.fixture()
def plugin_env(tmp_path, monkeypatch):
    library = tmp_path / "library"
    assets = library / "assets"
    data = tmp_path / "plugin-data"
    data.mkdir()
    grass = assets / "pixel_32" / "tiles" / "floor" / "grass_base.png"
    path = assets / "pixel_32" / "tiles" / "floor" / "dirt_path_base.png"
    crate = assets / "pixel_32" / "props" / "object" / "crate_plain.png"
    ranger = assets / "pixel_32" / "characters" / "humanoid" / "ranger_front.png"
    _png(grass, (40, 140, 50, 255))
    _png(path, (130, 90, 40, 255))
    _png(crate, (160, 110, 50, 255), 24)
    _png(ranger, (50, 80, 200, 255), 24)
    (library / "db").mkdir()
    db = library / "db" / "assets.db.xz"  # presence for is_library_root; real db written below
    # Write both a real db and a tiny xz so auto-restore can be tested separately.
    conn = sqlite3.connect(library / "db" / "assets.db")
    conn.executescript(SCHEMA)
    rows = [
        dict(
            id=1,
            slug="pixel_32/tiles/floor/grass_base",
            path="assets/pixel_32/tiles/floor/grass_base.png",
            category="tiles",
            subcategory="floor",
            subject="grass",
            style_pack="pixel_32",
            tags='["tiles","floor","grass","tileable"]',
            description="A grass floor tile, tileable.",
            width=16,
            height=16,
            has_alpha=1,
            tileable=1,
            license="original, generated for Kyle Durepos",
            status="ok",
        ),
        dict(
            id=2,
            slug="pixel_32/tiles/floor/dirt_path_base",
            path="assets/pixel_32/tiles/floor/dirt_path_base.png",
            category="tiles",
            subcategory="floor",
            subject="dirt_path",
            style_pack="pixel_32",
            tags='["tiles","floor","dirt","path","tileable"]',
            description="A dirt path floor tile.",
            width=16,
            height=16,
            has_alpha=1,
            tileable=1,
            license="original, generated for Kyle Durepos",
            status="ok",
        ),
        dict(
            id=3,
            slug="pixel_32/props/object/crate_plain",
            path="assets/pixel_32/props/object/crate_plain.png",
            category="props",
            subcategory="object",
            subject="crate",
            style_pack="pixel_32",
            tags='["props","crate","wooden"]',
            description="A plain wooden crate.",
            width=24,
            height=24,
            has_alpha=1,
            tileable=0,
            license="original, generated for Kyle Durepos",
            status="ok",
        ),
        dict(
            id=4,
            slug="pixel_32/characters/humanoid/ranger_front",
            path="assets/pixel_32/characters/humanoid/ranger_front.png",
            category="characters",
            subcategory="humanoid",
            subject="ranger",
            style_pack="pixel_32",
            tags='["characters","ranger","hero"]',
            description="A ranger facing front.",
            width=24,
            height=24,
            has_alpha=1,
            tileable=0,
            license="original, generated for Kyle Durepos",
            status="ok",
        ),
        dict(
            id=5,
            slug="cozy_cartoon/props/object/crate_plain",
            path="assets/cozy_cartoon/props/object/crate_plain.png",
            category="props",
            subcategory="object",
            subject="crate",
            style_pack="cozy_cartoon",
            tags='["props","crate"]',
            description="A cozy cartoon crate.",
            width=16,
            height=16,
            has_alpha=1,
            tileable=0,
            license="original, generated for Kyle Durepos",
            status="ok",
        ),
    ]
    # The cozy cartoon row has no file — used to test missing-file errors on place? 
    # Skip writing that PNG so get() can report exists=false; place should fail.
    def _file_hash(rel: str) -> str | None:
        path = library / rel
        if not path.is_file():
            return None
        return hashlib.sha256(path.read_bytes()).hexdigest()

    for row in rows:
        digest = _file_hash(row["path"])
        if digest:
            row["sha256"] = digest
        _insert(conn, **row)
    conn.commit()
    conn.close()
    # A dummy xz so is_library_root is happy even if db is deleted in a restore test.
    (library / "db" / "assets.db.xz").write_bytes(b"\x00")  # invalid xz; real db already present

    monkeypatch.setenv("ASSETRIZZ_LIBRARY", str(library))
    monkeypatch.setenv("ASSETRIZZ_HOME", str(data))
    monkeypatch.setenv("ASSETRIZZ_OFFLINE", "1")
    monkeypatch.setenv("ASSETRIZZ_ASSET_MODE", "on_demand")
    monkeypatch.delenv("ASSETRIZZ_EXPORT_DIR", raising=False)
    monkeypatch.delenv("ASSETRIZZ_ASSET_REF", raising=False)
    monkeypatch.delenv("ASSETRIZZ_LOCAL_LIBRARY", raising=False)

    from assetrizz_plugin.fetch import set_fetcher
    from assetrizz_plugin.library import reset_cache

    def _forbidden_fetch(url: str) -> bytes:
        raise AssertionError(f"test tried to fetch {url} without a mock fetcher")

    set_fetcher(_forbidden_fetch)
    reset_cache()
    yield {"library": library, "data": data, "assets": assets}
    set_fetcher(None)
    reset_cache()
