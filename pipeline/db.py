"""SQLite catalog: WAL, short transactions, claims, FTS5."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "assets.db"
LICENSE = "original, generated for Kyle Durepos"
ET = timezone(timedelta(hours=-5), name="America/Toronto")

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA busy_timeout=8000;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS specs (
  spec_index INTEGER PRIMARY KEY,
  spec_id TEXT NOT NULL UNIQUE,
  batch_id TEXT NOT NULL,
  cell_index INTEGER NOT NULL DEFAULT 0,
  category TEXT NOT NULL,
  subcategory TEXT NOT NULL,
  subject TEXT NOT NULL,
  variant TEXT NOT NULL,
  style_pack TEXT NOT NULL,
  tags TEXT NOT NULL,
  description TEXT NOT NULL,
  prompt TEXT,
  negative TEXT,
  style_prefix TEXT,
  target_w INTEGER,
  target_h INTEGER,
  tileable INTEGER NOT NULL DEFAULT 0,
  perspective TEXT,
  pivot_x REAL,
  pivot_y REAL,
  has_alpha_intended INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS batches (
  batch_index INTEGER PRIMARY KEY,
  batch_id TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL,
  grid_w INTEGER NOT NULL DEFAULT 1,
  grid_h INTEGER NOT NULL DEFAULT 1,
  n_cells INTEGER NOT NULL DEFAULT 1,
  style_pack TEXT NOT NULL,
  category TEXT NOT NULL,
  prompt TEXT NOT NULL,
  negative TEXT,
  aspect_ratio TEXT NOT NULL DEFAULT '1:1',
  filename_hint TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  claimed_by TEXT,
  claimed_at TEXT,
  lease_until TEXT,
  generated_path TEXT,
  ingested_at TEXT,
  error TEXT,
  queue_pos INTEGER,
  genre TEXT
);

CREATE TABLE IF NOT EXISTS claims (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_id TEXT NOT NULL,
  worker_id TEXT NOT NULL,
  shard_id INTEGER NOT NULL,
  shards INTEGER NOT NULL,
  claimed_at TEXT NOT NULL,
  lease_until TEXT NOT NULL,
  released_at TEXT,
  status TEXT NOT NULL DEFAULT 'claimed'
);

CREATE TABLE IF NOT EXISTS assets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  slug TEXT NOT NULL UNIQUE,
  path TEXT NOT NULL,
  thumb_path TEXT,
  category TEXT,
  subcategory TEXT,
  subject TEXT,
  style_pack TEXT,
  tags TEXT,
  description TEXT,
  prompt TEXT,
  negative TEXT,
  style_prefix TEXT,
  width INTEGER,
  height INTEGER,
  has_alpha INTEGER,
  palette TEXT,
  dominant_colors TEXT,
  tileable INTEGER DEFAULT 0,
  pivot TEXT,
  frame_info TEXT,
  license TEXT,
  generator TEXT,
  created_at TEXT,
  sha256 TEXT UNIQUE,
  phash TEXT,
  status TEXT NOT NULL DEFAULT 'ok',
  qa_notes TEXT,
  batch_id TEXT,
  spec_id TEXT,
  shard_id INTEGER,
  source_sheet TEXT
);

CREATE INDEX IF NOT EXISTS idx_assets_cat ON assets(category, style_pack, status);
CREATE INDEX IF NOT EXISTS idx_assets_subject ON assets(subject);
CREATE INDEX IF NOT EXISTS idx_assets_phash ON assets(phash);
CREATE INDEX IF NOT EXISTS idx_assets_batch ON assets(batch_id);
CREATE INDEX IF NOT EXISTS idx_assets_alpha ON assets(has_alpha, tileable, width, height);
CREATE INDEX IF NOT EXISTS idx_batches_status ON batches(status, batch_index);
CREATE INDEX IF NOT EXISTS idx_specs_batch ON specs(batch_id, cell_index);

CREATE VIRTUAL TABLE IF NOT EXISTS assets_fts USING fts5(
  slug,
  description,
  tags,
  subject,
  category,
  subcategory,
  style_pack,
  content='assets',
  content_rowid='id'
);

CREATE TABLE IF NOT EXISTS embeddings (
  asset_id INTEGER PRIMARY KEY REFERENCES assets(id) ON DELETE CASCADE,
  model TEXT,
  dim INTEGER,
  vector BLOB,
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT
);

CREATE TRIGGER IF NOT EXISTS assets_ai AFTER INSERT ON assets BEGIN
  INSERT INTO assets_fts(rowid, slug, description, tags, subject, category, subcategory, style_pack)
  VALUES (new.id, new.slug, new.description, new.tags, new.subject, new.category, new.subcategory, new.style_pack);
END;
CREATE TRIGGER IF NOT EXISTS assets_ad AFTER DELETE ON assets BEGIN
  INSERT INTO assets_fts(assets_fts, rowid, slug, description, tags, subject, category, subcategory, style_pack)
  VALUES ('delete', old.id, old.slug, old.description, old.tags, old.subject, old.category, old.subcategory, old.style_pack);
END;
CREATE TRIGGER IF NOT EXISTS assets_au AFTER UPDATE ON assets BEGIN
  INSERT INTO assets_fts(assets_fts, rowid, slug, description, tags, subject, category, subcategory, style_pack)
  VALUES ('delete', old.id, old.slug, old.description, old.tags, old.subject, old.category, old.subcategory, old.style_pack);
  INSERT INTO assets_fts(rowid, slug, description, tags, subject, category, subcategory, style_pack)
  VALUES (new.id, new.slug, new.description, new.tags, new.subject, new.category, new.subcategory, new.style_pack);
END;
"""


def now_iso() -> str:
    return datetime.now(ET).strftime("%Y-%m-%dT%H:%M:%S-05:00")


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=8000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(conn: Optional[sqlite3.Connection] = None) -> sqlite3.Connection:
    own = conn is None
    conn = conn or connect()
    conn.executescript(SCHEMA)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(batches)")}
    if "queue_pos" not in cols:
        conn.execute("ALTER TABLE batches ADD COLUMN queue_pos INTEGER")
    if "genre" not in cols:
        conn.execute("ALTER TABLE batches ADD COLUMN genre TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_batches_queue ON batches(status, queue_pos)")
    conn.commit()
    return conn


def set_meta(conn: sqlite3.Connection, key: str, value: Any) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, json.dumps(value) if not isinstance(value, str) else value),
    )


def get_meta(conn: sqlite3.Connection, key: str, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    if not row:
        return default
    try:
        return json.loads(row["value"])
    except Exception:
        return row["value"]


def reclaim_stale(conn: sqlite3.Connection) -> int:
    now = now_iso()
    cur = conn.execute(
        """
        UPDATE batches
           SET status='pending', error=COALESCE(error, 'lease expired')
         WHERE status='claimed' AND lease_until IS NOT NULL AND lease_until < ?
        """,
        (now,),
    )
    return cur.rowcount


def claim_batches(
    conn: sqlite3.Connection,
    *,
    shard_id: int,
    shards: int,
    worker_id: str,
    limit: int,
    lease_minutes: int = 30,
) -> list[sqlite3.Row]:
    """Claim up to `limit` pending batches whose queue_pos % shards == shard_id."""
    if shards < 1 or shard_id < 0 or shard_id >= shards:
        raise ValueError(f"invalid shard {shard_id}/{shards}")
    lease_until = (datetime.now(ET) + timedelta(minutes=lease_minutes)).strftime(
        "%Y-%m-%dT%H:%M:%S-05:00"
    )
    claimed_at = now_iso()
    out: list[sqlite3.Row] = []
    conn.execute("BEGIN IMMEDIATE")
    try:
        reclaim_stale(conn)
        rows = conn.execute(
            """
            SELECT batch_index, batch_id FROM batches
             WHERE status='pending' AND (COALESCE(queue_pos, batch_index) % ?) = ?
             ORDER BY COALESCE(queue_pos, batch_index)
             LIMIT ?
            """,
            (shards, shard_id, limit),
        ).fetchall()
        ids = [r["batch_id"] for r in rows]
        if ids:
            conn.executemany(
                """
                UPDATE batches
                   SET status='claimed', claimed_by=?, claimed_at=?, lease_until=?, error=NULL
                 WHERE batch_id=? AND status='pending'
                """,
                [(worker_id, claimed_at, lease_until, i) for i in ids],
            )
            conn.executemany(
                """
                INSERT INTO claims(batch_id, worker_id, shard_id, shards, claimed_at, lease_until, status)
                VALUES (?, ?, ?, ?, ?, ?, 'claimed')
                """,
                [(i, worker_id, shard_id, shards, claimed_at, lease_until) for i in ids],
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    if not ids:
        return []
    qmarks = ",".join("?" * len(ids))
    out = conn.execute(
        f"SELECT * FROM batches WHERE batch_id IN ({qmarks}) ORDER BY batch_index",
        ids,
    ).fetchall()
    return list(out)


def extend_lease(conn: sqlite3.Connection, batch_id: str, worker_id: str, lease_minutes: int = 30) -> None:
    lease_until = (datetime.now(ET) + timedelta(minutes=lease_minutes)).strftime(
        "%Y-%m-%dT%H:%M:%S-05:00"
    )
    conn.execute(
        """
        UPDATE batches SET lease_until=?
         WHERE batch_id=? AND claimed_by=? AND status='claimed'
        """,
        (lease_until, batch_id, worker_id),
    )
    conn.commit()


def mark_generated(conn: sqlite3.Connection, batch_id: str, generated_path: str) -> None:
    conn.execute(
        "UPDATE batches SET status='generated', generated_path=? WHERE batch_id=? AND status IN ('claimed','generated')",
        (generated_path, batch_id),
    )
    conn.commit()


def mark_ingested(conn: sqlite3.Connection, batch_id: str, error: Optional[str] = None) -> None:
    status = "failed" if error else "ingested"
    conn.execute(
        "UPDATE batches SET status=?, ingested_at=?, error=? WHERE batch_id=?",
        (status, now_iso(), error, batch_id),
    )
    conn.execute(
        "UPDATE claims SET released_at=?, status=? WHERE batch_id=? AND released_at IS NULL",
        (now_iso(), status, batch_id),
    )
    conn.commit()


def counts(conn: sqlite3.Connection) -> dict:
    def scalar(sql: str, *args) -> int:
        row = conn.execute(sql, args).fetchone()
        return int(list(row)[0] if row else 0)

    per_shard: dict[str, dict] = {}
    shards = int(get_meta(conn, "shards") or 4)
    # Live queue uses queue_pos; parked/finished rows with negative queue_pos fall back to batch_index.
    shard_key = "CASE WHEN queue_pos IS NOT NULL AND queue_pos >= 0 THEN queue_pos ELSE batch_index END"
    for s in range(shards):
        per_shard[str(s)] = {
            "pending": scalar(
                f"SELECT COUNT(*) FROM batches WHERE status='pending' AND ({shard_key} % ?)=?",
                shards, s,
            ),
            "claimed": scalar(
                f"SELECT COUNT(*) FROM batches WHERE status='claimed' AND ({shard_key} % ?)=?",
                shards, s,
            ),
            "generated": scalar(
                f"SELECT COUNT(*) FROM batches WHERE status='generated' AND ({shard_key} % ?)=?",
                shards, s,
            ),
            "ingested": scalar(
                f"SELECT COUNT(*) FROM batches WHERE status='ingested' AND ({shard_key} % ?)=?",
                shards, s,
            ),
            "failed": scalar(
                f"SELECT COUNT(*) FROM batches WHERE status='failed' AND ({shard_key} % ?)=?",
                shards, s,
            ),
        }
    next_pending = conn.execute(
        "SELECT MIN(COALESCE(queue_pos, batch_index)) AS i FROM batches WHERE status='pending'"
    ).fetchone()
    current_pack = conn.execute(
        """
        SELECT style_pack FROM batches
         WHERE status IN ('claimed','generated','pending')
         ORDER BY CASE status WHEN 'claimed' THEN 0 WHEN 'generated' THEN 1 ELSE 2 END, batch_index
         LIMIT 1
        """
    ).fetchone()
    return {
        "schema_version": 1,
        "shards": shards,
        "batch_total": scalar("SELECT COUNT(*) FROM batches"),
        "spec_total": scalar("SELECT COUNT(*) FROM specs"),
        "generated_count": scalar("SELECT COUNT(*) FROM batches WHERE status IN ('generated','ingested')")
        + scalar("SELECT COUNT(*) FROM batches WHERE status='failed' AND generated_path IS NOT NULL"),
        "ingested_batches": scalar("SELECT COUNT(*) FROM batches WHERE status='ingested'"),
        "ingested_count": scalar("SELECT COUNT(*) FROM assets WHERE status='ok'"),
        "rejected_count": scalar("SELECT COUNT(*) FROM assets WHERE status='rejected'"),
        "pending_batches": scalar("SELECT COUNT(*) FROM batches WHERE status='pending'"),
        "claimed_batches": scalar("SELECT COUNT(*) FROM batches WHERE status='claimed'"),
        "failed_batches": scalar("SELECT COUNT(*) FROM batches WHERE status='failed'"),
        "current_pack": current_pack["style_pack"] if current_pack else None,
        "next_spec_index": (
            conn.execute(
                """
                SELECT MIN(spec_index) AS i FROM specs
                 WHERE batch_id IN (SELECT batch_id FROM batches WHERE status IN ('pending','claimed','generated'))
                """
            ).fetchone()["i"]
        ),
        "next_batch_index": next_pending["i"] if next_pending else None,
        "per_shard": per_shard,
        "updated_at": now_iso(),
        "license": LICENSE,
        "generate_until": "2026-11-10T05:00:00-05:00",
    }


def snapshot_progress(conn: sqlite3.Connection, path: Path = ROOT / "PROGRESS.json") -> dict:
    data = counts(conn)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(path)
    return data


def existing_phashes(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    rows = conn.execute(
        "SELECT phash, slug FROM assets WHERE phash IS NOT NULL AND status='ok'"
    ).fetchall()
    return [(r["phash"], r["slug"]) for r in rows]


def sha_exists(conn: sqlite3.Connection, sha: str) -> bool:
    return conn.execute("SELECT 1 FROM assets WHERE sha256=?", (sha,)).fetchone() is not None
