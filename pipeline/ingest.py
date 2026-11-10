#!/usr/bin/env python3
"""Ingest raw generations from a worker staging dir into the shared catalog.

Runs sequentially (one raw file at a time). Intended to be invoked under `nice`.
Safe for parallel workers: short IMMEDIATE transactions, unique slugs, WAL.
"""
from __future__ import annotations

import argparse
import io
import json
import shutil
import sqlite3
import sys
from pathlib import Path

from db import (
    LICENSE,
    ROOT,
    connect,
    existing_phashes,
    init_db,
    mark_generated,
    mark_ingested,
    now_iso,
    sha_exists,
    snapshot_progress,
)
from build_specs import FEET_CATEGORIES
from process import (
    contact_sheet,
    finish_sprite,
    hex_to_rgb,
    hamming_hex,
    load_rgba,
    save_png,
    sha256_of,
    slice_grid,
    make_thumb,
)

GENERATOR = "cursor.GenerateImage"
HAMMING_DUP = 2
MANIFEST = ROOT / "manifest.jsonl"


def slugify(spec: dict) -> str:
    return f"{spec['style_pack']}/{spec['category']}/{spec['subcategory']}/{spec['subject']}_{spec['variant']}"


def library_path(spec: dict) -> Path:
    return ROOT / "library" / f"{slugify(spec)}.png"


def thumb_path(spec: dict) -> Path:
    return ROOT / "thumbs" / f"{slugify(spec)}.png"


def append_manifest(records: list[dict]) -> None:
    if not records:
        return
    with MANIFEST.open("a") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def export_manifest(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT * FROM assets ORDER BY id").fetchall()
    tmp = MANIFEST.with_suffix(".jsonl.tmp")
    with tmp.open("w") as f:
        for r in rows:
            f.write(json.dumps(dict(r), ensure_ascii=False) + "\n")
    tmp.replace(MANIFEST)


def insert_asset(conn: sqlite3.Connection, rec: dict) -> str:
    """Insert or skip. Returns 'ok', 'rejected', 'duplicate', or 'exists'."""
    if sha_exists(conn, rec["sha256"]):
        return "exists"
    # Only auto-reject near-duplicates of a *different* subject. Variants of the
    # same subject (plain/ornate/worn) are often close at 16/32px and should stay.
    rec_subject = rec.get("subject") or ""
    for ph, slug in existing_phashes(conn):
        if rec["phash"] and hamming_hex(rec["phash"], ph) <= HAMMING_DUP:
            other_subject = slug.split("/")[-1].rsplit("_", 1)[0] if "/" in slug else slug
            if rec_subject and (rec_subject == other_subject or slug.endswith("/" + rec_subject) or f"/{rec_subject}_" in "/"+slug):
                notes = json.loads(rec["qa_notes"] or "[]")
                notes.append(f"phash_near_variant:{slug}")
                rec = dict(rec)
                rec["qa_notes"] = json.dumps(notes)
                break
            rec = dict(rec)
            rec["status"] = "rejected"
            rec["qa_notes"] = json.dumps(
                json.loads(rec["qa_notes"] or "[]") + [f"duplicate_of:{slug}"]
            )
            break
    cols = ",".join(rec.keys())
    marks = ",".join(":" + k for k in rec)
    try:
        conn.execute("BEGIN IMMEDIATE")
        # re-check sha inside the lock
        if sha_exists(conn, rec["sha256"]):
            conn.rollback()
            return "exists"
        conn.execute(f"INSERT INTO assets({cols}) VALUES ({marks})", rec)
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        return "exists"
    return rec["status"] if rec["status"] == "rejected" else "ok"


def process_batch(
    conn: sqlite3.Connection,
    batch: dict,
    specs: list[dict],
    raw_path: Path,
    shard_id: int,
    packs: dict,
) -> dict:
    im = load_rgba(raw_path)
    pack = packs[batch["style_pack"]]
    chroma = hex_to_rgb(pack.get("chroma", "#FF00FF"))
    pixel = bool(pack.get("pixel"))
    palette = pack.get("palette") or []
    grid_w, grid_h = int(batch["grid_w"]), int(batch["grid_h"])
    cells = slice_grid(im, grid_w, grid_h) if grid_w * grid_h > 1 else [im]
    key_bg = batch["kind"] not in ("background", "tile")
    # tiles are tileable opaque; backgrounds fill the frame
    results = []
    preview = []
    stats = {"ok": 0, "rejected": 0, "exists": 0, "cells": 0}

    dest_raw = ROOT / "raw" / f"{batch['batch_id']}.png"
    dest_raw.parent.mkdir(parents=True, exist_ok=True)
    if raw_path.resolve() != dest_raw.resolve():
        shutil.copy2(raw_path, dest_raw)
    mark_generated(conn, batch["batch_id"], str(dest_raw.relative_to(ROOT)))

    for spec in specs:
        cell_i = int(spec["cell_index"])
        if cell_i >= len(cells):
            stats["rejected"] += 1
            continue
        cell = cells[cell_i]
        target = (int(spec["target_w"]), int(spec["target_h"]))
        tileable = bool(spec["tileable"])
        anchor = "feet" if spec["category"] in FEET_CATEGORIES else "center"
        finished = finish_sprite(
            cell,
            target=target,
            palette=palette,
            pixel=pixel,
            tileable=tileable,
            chroma=chroma,
            pivot_anchor=anchor,
            key_bg=key_bg and not tileable,
        )
        img = finished["image"]
        slug = slugify(spec)
        out = library_path(spec)
        rejected_dir_file = ROOT / "rejected" / f"{slug}.png"
        status = finished["status"]
        if status == "rejected":
            save_png(img, rejected_dir_file)
            rel_path = str(rejected_dir_file.relative_to(ROOT))
            tpath = None
        else:
            save_png(img, out)
            rel_path = str(out.relative_to(ROOT))
            tp = thumb_path(spec)
            make_thumb(img, tp)
            tpath = str(tp.relative_to(ROOT))
            preview.append(img)

        # hash the saved file
        saved = rejected_dir_file if status == "rejected" else out
        sha = sha256_of(saved)
        rec = {
            "slug": slug,
            "path": rel_path,
            "thumb_path": tpath,
            "category": spec["category"],
            "subcategory": spec["subcategory"],
            "subject": spec["subject"],
            "style_pack": spec["style_pack"],
            "tags": spec["tags"] if isinstance(spec["tags"], str) else json.dumps(spec["tags"]),
            "description": spec["description"],
            "prompt": spec["prompt"] or batch["prompt"],
            "negative": spec["negative"] or pack.get("negative"),
            "style_prefix": spec["style_prefix"] or pack.get("style_prefix"),
            "width": finished["width"],
            "height": finished["height"],
            "has_alpha": int(finished["has_alpha"]),
            "palette": json.dumps(finished["palette"]),
            "dominant_colors": json.dumps(finished["dominant_colors"]),
            "tileable": int(spec["tileable"]),
            "pivot": json.dumps({"x": spec["pivot_x"], "y": spec["pivot_y"]}),
            "frame_info": json.dumps({
                "batch_id": batch["batch_id"],
                "kind": batch["kind"],
                "cell_index": cell_i,
                "grid": [grid_w, grid_h],
                "source_size": list(cell.size),
            }),
            "license": LICENSE,
            "generator": GENERATOR,
            "created_at": now_iso(),
            "sha256": sha,
            "phash": finished["phash"],
            "status": status,
            "qa_notes": json.dumps(finished["qa_notes"]),
            "batch_id": batch["batch_id"],
            "spec_id": spec["spec_id"],
            "shard_id": shard_id,
            "source_sheet": str(dest_raw.relative_to(ROOT)),
        }
        outcome = insert_asset(conn, rec)
        stats["cells"] += 1
        if outcome == "ok":
            stats["ok"] += 1
        elif outcome in ("rejected",):
            stats["rejected"] += 1
        else:
            stats["exists"] += 1
        rec["_outcome"] = outcome
        results.append(rec)

    if preview:
        cs = ROOT / "contact_sheets" / f"{batch['batch_id']}.png"
        try:
            contact_sheet(preview, cs, cols=min(8, max(1, int(batch["grid_w"]))))
        except Exception:
            pass

    mark_ingested(conn, batch["batch_id"])
    return {"batch_id": batch["batch_id"], "stats": stats, "results": results}


def find_raw_for_batch(staging: Path, batch_id: str, filename_hint: str) -> Path | None:
    candidates = [
        staging / "raw" / f"{batch_id}.png",
        staging / "raw" / f"{batch_id}.jpg",
        staging / "raw" / f"{batch_id}.jpeg",
        staging / "raw" / filename_hint,
        staging / f"{batch_id}.png",
        staging / f"{batch_id}.jpg",
        ROOT / "raw" / f"{batch_id}.png",
        ROOT / "raw" / f"{batch_id}.jpg",
        ROOT / "work" / "incoming" / f"{batch_id}.png",
        ROOT / "work" / "incoming" / f"{batch_id}.jpg",
    ]
    for c in candidates:
        if c.is_file():
            return c
    return None


def ingest_staging(shard_id: int | None, staging: Path | None, worker_id: str | None, rebuild_manifest: bool = True, shards: int | None = None) -> dict:
    conn = init_db()
    packs = json.loads((ROOT / "style_packs.json").read_text())
    # Batches this worker can ingest: claimed/generated for this shard or any generated with a raw file
    if shard_id is not None:
        if shards is None:
            shards = int(conn.execute("SELECT value FROM meta WHERE key='shards'").fetchone()["value"])
            # value may be JSON number
            try:
                shards = int(json.loads(str(shards)))
            except Exception:
                shards = int(shards)
        rows = conn.execute(
            """
            SELECT * FROM batches
             WHERE status IN ('claimed','generated')
               AND (queue_pos % ?) = ?
             ORDER BY queue_pos
            """,
            (shards, shard_id),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM batches WHERE status IN ('claimed','generated') ORDER BY batch_index"
        ).fetchall()

    staging = staging or (ROOT / "work" / (f"shard-{shard_id}" if shard_id is not None else "shared"))
    summary = {"ingested_batches": 0, "ok": 0, "rejected": 0, "exists": 0, "missing_raw": 0, "failed": 0, "batches": []}

    for row in rows:
        batch = dict(row)
        raw = find_raw_for_batch(staging, batch["batch_id"], batch["filename_hint"])
        if raw is None:
            summary["missing_raw"] += 1
            continue
        specs = [dict(s) for s in conn.execute(
            "SELECT * FROM specs WHERE batch_id=? ORDER BY cell_index", (batch["batch_id"],)
        ).fetchall()]
        try:
            result = process_batch(conn, batch, specs, raw, shard_id if shard_id is not None else -1, packs)
            st = result["stats"]
            summary["ingested_batches"] += 1
            summary["ok"] += st["ok"]
            summary["rejected"] += st["rejected"]
            summary["exists"] += st["exists"]
            summary["batches"].append({"batch_id": batch["batch_id"], **st})
        except Exception as e:
            mark_ingested(conn, batch["batch_id"], error=str(e)[:500])
            summary["failed"] += 1
            summary["batches"].append({"batch_id": batch["batch_id"], "error": str(e)[:500]})

    if rebuild_manifest:
        export_manifest(conn)
    progress = snapshot_progress(conn)
    conn.close()
    summary["progress"] = progress
    return summary


def main():
    ap = argparse.ArgumentParser(description="Ingest raw sheet/single images for claimed batches")
    ap.add_argument("--shard", type=int, default=None)
    ap.add_argument("--shards", type=int, default=None, help="Total shard count used when claiming (overrides meta)")
    ap.add_argument("--staging", type=Path, default=None, help="Worker staging dir (default work/shard-N)")
    ap.add_argument("--worker-id", default=None)
    args = ap.parse_args()
    summary = ingest_staging(args.shard, args.staging, args.worker_id, shards=args.shards)
    print(json.dumps({k: v for k, v in summary.items() if k != "progress"}, indent=2))
    print(json.dumps({"progress": summary["progress"]}, indent=2))


if __name__ == "__main__":
    main()
