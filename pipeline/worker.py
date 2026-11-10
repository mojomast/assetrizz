#!/usr/bin/env python3
"""Shard worker entry point.

One-liner (replace N with 0, 1, 2 or 3 when using four workers):

    nice -n 15 python3 /workspace/game-assets/worker.py --shard N --shards 4

This (1) ingests any raw images already in work/shard-N/raw/{batch_id}.png,
(2) claims the next pending batches for that shard, and (3) writes prompts to
work/shard-N/queue.jsonl and work/shard-N/NEXT.md for the agent to generate.
Image generation is remote (GenerateImage); this process stays light and sequential.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from db import ROOT, claim_batches, init_db, now_iso, snapshot_progress
from ingest import ingest_staging

DEFAULT_SHARDS = 4
DEFAULT_CLAIM = 4


def work_dir(shard_id: int) -> Path:
    d = ROOT / "work" / f"shard-{shard_id}"
    (d / "raw").mkdir(parents=True, exist_ok=True)
    (d / "staging").mkdir(parents=True, exist_ok=True)
    (d / "logs").mkdir(parents=True, exist_ok=True)
    return d


def write_queue(wd: Path, claimed: list, specs_by_batch: dict, shard_id: int, shards: int, worker_id: str) -> Path:
    queue_path = wd / "queue.jsonl"
    next_md = wd / "NEXT.md"
    records = []
    with queue_path.open("w") as f:
        for b in claimed:
            rec = dict(b)
            rec["specs"] = specs_by_batch.get(b["batch_id"], [])
            rec["save_as"] = f"{b['batch_id']}.png"
            rec["copy_to"] = str((wd / "raw" / f"{b['batch_id']}.png"))
            rec["shard_id"] = shard_id
            rec["shards"] = shards
            rec["worker_id"] = worker_id
            rec["generate_tool"] = "cursor.GenerateImage"
            rec["aspect_ratio"] = b["aspect_ratio"]
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            records.append(rec)

    lines = [
        f"# Shard {shard_id} of {shards} — next generations",
        f"",
        f"Worker: `{worker_id}`  ",
        f"Updated: {now_iso()} (America/Toronto)",
        f"",
        f"For each item below, call GenerateImage with the given `description`, `filename`, and `aspect_ratio`.",
        f"Then **copy** the returned file to the `copy_to` path (must be named `{{batch_id}}.png`).",
        f"After all files are in place, run:",
        f"",
        f"```",
        f"nice -n 15 python3 /workspace/game-assets/worker.py --shard {shard_id} --shards {shards}",
        f"```",
        f"",
        f"That ingests the raw files and claims the next batch.",
        f"",
    ]
    if not records:
        lines.append("_No pending batches left for this shard._")
    for i, rec in enumerate(records, 1):
        subjects = ", ".join(
            f"{s.get('subject')}/{s.get('variant')}" for s in rec["specs"]
        )
        lines += [
            f"## {i}. `{rec['batch_id']}`",
            f"",
            f"- kind: {rec['kind']} ({rec['grid_w']}x{rec['grid_h']})",
            f"- style: {rec['style_pack']} / {rec['category']}",
            f"- aspect_ratio: `{rec['aspect_ratio']}`",
            f"- filename: `{rec['save_as']}`",
            f"- copy_to: `{rec['copy_to']}`",
            f"- subjects: {subjects}",
            f"",
            f"<details><summary>prompt</summary>",
            f"",
            f"```",
            rec["prompt"],
            f"```",
            f"",
            f"</details>",
            f"",
        ]
    next_md.write_text("\n".join(lines) + "\n")
    return queue_path


def main():
    ap = argparse.ArgumentParser(description="Claim work + ingest raw images for one shard")
    ap.add_argument("--shard", type=int, required=True, help="Shard index N (0-based)")
    ap.add_argument("--shards", type=int, default=DEFAULT_SHARDS, help="Total workers (default 4)")
    ap.add_argument("--claim", type=int, default=DEFAULT_CLAIM, help="How many batches to claim")
    ap.add_argument("--worker-id", default=None)
    ap.add_argument("--lease-min", type=int, default=30)
    ap.add_argument("--no-ingest", action="store_true")
    ap.add_argument("--no-claim", action="store_true")
    args = ap.parse_args()

    if args.shard < 0 or args.shard >= args.shards:
        print(f"error: shard must be 0..{args.shards-1}", file=sys.stderr)
        sys.exit(2)

    worker_id = args.worker_id or f"shard-{args.shard}"
    wd = work_dir(args.shard)
    conn = init_db()

    ingest_summary = None
    if not args.no_ingest:
        ingest_summary = ingest_staging(args.shard, wd, worker_id, rebuild_manifest=True, shards=args.shards)

    claimed_rows = []
    if not args.no_claim:
        claimed_rows = claim_batches(
            conn,
            shard_id=args.shard,
            shards=args.shards,
            worker_id=worker_id,
            limit=args.claim,
            lease_minutes=args.lease_min,
        )

    specs_by_batch = {}
    for row in claimed_rows:
        specs = [dict(s) for s in conn.execute(
            "SELECT spec_id, cell_index, category, subcategory, subject, variant, target_w, target_h, tileable "
            "FROM specs WHERE batch_id=? ORDER BY cell_index",
            (row["batch_id"],),
        ).fetchall()]
        specs_by_batch[row["batch_id"]] = specs

    claimed = [dict(r) for r in claimed_rows]
    write_queue(wd, claimed, specs_by_batch, args.shard, args.shards, worker_id)
    progress = snapshot_progress(conn)
    conn.close()

    out = {
        "worker_id": worker_id,
        "shard": args.shard,
        "shards": args.shards,
        "work_dir": str(wd),
        "queue": str(wd / "queue.jsonl"),
        "next_md": str(wd / "NEXT.md"),
        "claimed": [c["batch_id"] for c in claimed],
        "claimed_count": len(claimed),
        "ingest": None if ingest_summary is None else {k: ingest_summary[k] for k in ingest_summary if k not in ("progress",)},
        "progress": progress,
        "one_liner": f"nice -n 15 python3 /workspace/game-assets/worker.py --shard {args.shard} --shards {args.shards}",
    }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
