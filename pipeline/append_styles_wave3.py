#!/usr/bin/env python3
"""Append a third wave of style packs to the live queue without touching existing rows.

Builds specs/batches for styles that are in style_packs.json but not yet in the
batches table, covering all 18 categories (the original eight plus the later ten),
then inserts them in one short BEGIN IMMEDIATE transaction. A per-category keep
budget lands the wave in the 1,000–1,500 batch range. queue_pos continues after
the current max and is round-robin interleaved across category × style × genre.

Does not claim work, does not rebuild the DB, does not update existing rows,
and does not call GenerateImage.

    nice -n 15 python3 /workspace/game-assets/append_styles_wave3.py
    nice -n 15 python3 /workspace/game-assets/append_styles_wave3.py --dry-build
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict, deque

import append_categories as catwave
import append_styles as stylewave
from append_styles import (
    append_jsonl,
    assign_queue_pos,
    backup_db,
    insert_rows,
    reindex,
    summarize,
    write_taxonomy,
)
from build_specs import PACKS_PATH
from db import ROOT, init_db, snapshot_progress

NEW_STYLE_IDS = [
    "stained_glass",
    "chalk_crayon",
    "art_deco_poster",
    "ukiyo_e_inspired",
    "blueprint_line",
    "cyberpunk_neon",
    "storybook_gouache",
    "monochrome_1bit",
]

# Per style, how many batches to keep in each category (interleaved by genre).
# 169 × 8 styles = 1,352 batches, inside the 1,000–1,500 target.
KEEP_PER_STYLE = {
    "icons": 8,
    "tiles": 32,
    "props": 5,
    "characters": 14,
    "enemies": 2,
    "ui": 2,
    "vfx": 10,
    "backgrounds": 22,
    "vehicles": 8,
    "buildings": 10,
    "furniture": 6,
    "foliage": 8,
    "creatures": 6,
    "portraits": 8,
    "weapons": 6,
    "decals": 6,
    "markers": 6,
    "terrain": 10,
}


def trim_batches(batches: list[dict], keep: dict[str, int]) -> tuple[list[dict], list[dict]]:
    by_key: dict[tuple, list[dict]] = defaultdict(list)
    for b in batches:
        by_key[(b["style_pack"], b["category"])].append(b)
    kept: list[dict] = []
    for (style, cat), group in by_key.items():
        n = keep.get(cat, len(group))
        buckets: dict[str, deque] = defaultdict(deque)
        for b in group:
            buckets[b.get("genre") or cat].append(b)
        out: list[dict] = []
        while buckets and len(out) < n:
            for genre in list(buckets.keys()):
                if not buckets[genre]:
                    del buckets[genre]
                    continue
                out.append(buckets[genre].popleft())
                if len(out) >= n:
                    break
        kept.extend(out)
    specs: list[dict] = []
    for b in kept:
        specs.extend(b["rows"])
    return specs, kept


def main() -> None:
    ap = argparse.ArgumentParser(description="Append wave-3 style packs to the live queue")
    ap.add_argument("--dry-build", action="store_true", help="Build in memory and print counts; do not write the DB")
    ap.add_argument("--skip-backup", action="store_true", help="Skip the sqlite backup (already taken this run)")
    args = ap.parse_args()

    packs = json.loads(PACKS_PATH.read_text())
    missing = [s for s in NEW_STYLE_IDS if s not in packs]
    if missing:
        print(json.dumps({"error": "style packs missing from style_packs.json", "missing": missing}, indent=2))
        sys.exit(2)
    needed_cats = list(KEEP_PER_STYLE)
    missing_sizes = [s for s in NEW_STYLE_IDS if any(c not in packs[s].get("sizes", {}) for c in needed_cats)]
    if missing_sizes:
        print(json.dumps({"error": "new packs missing category sizes", "packs": missing_sizes}, indent=2))
        sys.exit(2)

    conn = init_db()
    already = {r[0] for r in conn.execute("SELECT DISTINCT style_pack FROM batches")}
    to_add = [s for s in NEW_STYLE_IDS if s not in already]
    if not to_add:
        print(json.dumps({
            "error": "new style packs already present in batches; nothing to append",
            "styles": NEW_STYLE_IDS,
        }, indent=2))
        conn.close()
        sys.exit(1)

    start_batch = int(conn.execute("SELECT COALESCE(MAX(batch_index), -1) FROM batches").fetchone()[0]) + 1
    start_spec = int(conn.execute("SELECT COALESCE(MAX(spec_index), -1) FROM specs").fetchone()[0]) + 1
    start_pos = max(
        int(conn.execute("SELECT COALESCE(MAX(queue_pos), -1) FROM batches WHERE queue_pos IS NOT NULL").fetchone()[0]) + 1,
        int(conn.execute("SELECT COALESCE(MAX(queue_pos), -1) FROM batches WHERE queue_pos >= 0").fetchone()[0]) + 1,
    )

    subset = {k: packs[k] for k in to_add}
    specs_a, batches_a = stylewave.build_wave(subset, to_add)
    specs_b, batches_b = catwave.build_wave(subset, to_add)
    # Temporary batch_ids may overlap across the two builders; trim by object, then reindex.
    _ = (specs_a, specs_b)
    specs, batches = trim_batches(batches_a + batches_b, KEEP_PER_STYLE)
    reindex(batches, specs, start_batch, start_spec)
    assign_queue_pos(batches, start_pos)
    summary = summarize(specs, batches)

    if args.dry_build:
        conn.close()
        print(json.dumps({
            "dry_build": True,
            "styles": to_add,
            "keep_per_style": KEEP_PER_STYLE,
            "full_before_trim": len(batches_a) + len(batches_b),
            **summary,
        }, indent=2))
        return

    backup_path = None
    if not args.skip_backup:
        backup_path = backup_db(ROOT / "assets.db", label="wave3")

    try:
        insert_rows(conn, specs, batches, list(packs.keys()))
    except Exception:
        conn.close()
        raise

    append_jsonl(ROOT / "specs.jsonl", [{k: s[k] for k in s} for s in specs])
    prompt_recs = []
    for b in batches:
        rec = {k: b[k] for k in b if k != "rows"}
        rec["spec_ids"] = [r["spec_id"] for r in b["rows"]]
        rec["subjects"] = [f"{r['subject']}/{r['variant']}" for r in b["rows"]]
        prompt_recs.append(rec)
    append_jsonl(ROOT / "prompts.jsonl", prompt_recs)
    write_taxonomy(conn, packs)
    progress = snapshot_progress(conn)

    pending_by_style = [
        {"style_pack": r[0], "n": r[1]}
        for r in conn.execute(
            "SELECT style_pack, COUNT(*) FROM batches WHERE status='pending' GROUP BY style_pack ORDER BY style_pack"
        )
    ]
    new_pending = [
        {"style_pack": r[0], "n": r[1]}
        for r in conn.execute(
            "SELECT style_pack, COUNT(*) FROM batches WHERE status='pending' AND style_pack IN ({}) GROUP BY style_pack ORDER BY style_pack".format(
                ",".join("?" * len(to_add))
            ),
            to_add,
        )
    ]
    claim_preview = {}
    for shards in (4, 8, 12, 16):
        per = {}
        for shard in range(min(4, shards)):
            n = conn.execute(
                """
                SELECT COUNT(*) FROM batches
                 WHERE status='pending' AND (COALESCE(queue_pos, batch_index) % ?)=?
                   AND style_pack IN ({})
                """.format(",".join("?" * len(to_add))),
                (shards, shard, *to_add),
            ).fetchone()[0]
            per[str(shard)] = n
        claim_preview[str(shards)] = per

    conn.close()
    print(json.dumps({
        "inserted": True,
        "backup": str(backup_path) if backup_path else None,
        "styles": to_add,
        **summary,
        "pending_by_style": pending_by_style,
        "pending_new_styles": new_pending,
        "new_claim_preview_first_shards": claim_preview,
        "progress": {
            "pending_batches": progress.get("pending_batches"),
            "claimed_batches": progress.get("claimed_batches"),
            "ingested_batches": progress.get("ingested_batches"),
            "batch_total": progress.get("batch_total"),
            "spec_total": progress.get("spec_total"),
            "ingested_count": progress.get("ingested_count"),
        },
    }, indent=2))


if __name__ == "__main__":
    main()
