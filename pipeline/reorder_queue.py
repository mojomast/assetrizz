#!/usr/bin/env python3
"""Re-order pending batches so consecutive claims round-robin across
category × style pack × genre (subcategory). Does not change quotas.

Also refreshes sheet/turnaround/vfx prompts with a stronger gutter instruction.
"""
from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict, deque
from pathlib import Path

from db import ROOT, init_db, snapshot_progress

GUTTER_OLD = (
    "One subject per cell, evenly sized cells, generous even margins, nothing crossing cell borders, "
)
GUTTER_NEW = (
    "Each item is centered in its own cell with wide empty magenta margins on all four sides, "
    "a thick magenta gutter between every cell, nothing crossing cell borders, "
    "and no item touching a neighbor or the cell edge. "
)


def genre_for(conn: sqlite3.Connection, batch_id: str, category: str) -> str:
    row = conn.execute(
        "SELECT subcategory FROM specs WHERE batch_id=? ORDER BY cell_index LIMIT 1",
        (batch_id,),
    ).fetchone()
    return (row["subcategory"] if row and row["subcategory"] else category) or "misc"


def variety_order(items: list[dict]) -> list[dict]:
    groups: dict[tuple, deque] = defaultdict(deque)
    for it in items:
        key = (it["category"], it["style_pack"], it["genre"])
        groups[key].append(it)

    used_style: Counter = Counter()
    used_cat: Counter = Counter()
    used_genre: Counter = Counter()
    used_triple: Counter = Counter()

    def score(key):
        cat, style, genre = key
        return (
            used_style[style] + used_cat[cat] + used_genre[genre],
            used_triple[key],
            style,
            cat,
            genre,
        )

    out = []
    while groups:
        key = min(groups, key=score)
        item = groups[key].popleft()
        out.append(item)
        used_style[key[1]] += 1
        used_cat[key[0]] += 1
        used_genre[key[2]] += 1
        used_triple[key] += 1
        if not groups[key]:
            del groups[key]
    return out


def refresh_prompt(prompt: str) -> str:
    if not prompt:
        return prompt
    if GUTTER_NEW in prompt:
        return prompt
    if GUTTER_OLD in prompt:
        return prompt.replace(GUTTER_OLD, GUTTER_NEW, 1)
    # older shorter wording
    needle = "One subject per cell, evenly sized cells, generous even margins, nothing crossing cell borders, "
    if needle in prompt:
        return prompt.replace(needle, GUTTER_NEW, 1)
    return prompt


def main() -> None:
    conn = init_db()
    # genres
    rows = [dict(r) for r in conn.execute("SELECT * FROM batches").fetchall()]
    for r in rows:
        r["genre"] = genre_for(conn, r["batch_id"], r["category"])

    pending = [r for r in rows if r["status"] == "pending"]
    others = [r for r in rows if r["status"] != "pending"]
    ordered = variety_order(pending)

    conn.execute("BEGIN IMMEDIATE")
    # Ingested/claimed/generated keep a queue_pos that does not steal the pending sequence.
    # Pending get 0..N-1 in variety order; shards use queue_pos % shards.
    for r in others:
        pos = r.get("queue_pos")
        if pos is None:
            # park non-pending at a negative slot so they don't collide with the live queue
            pos = -1 - int(r["batch_index"])
        conn.execute(
            "UPDATE batches SET queue_pos=?, genre=? WHERE batch_id=?",
            (pos, r["genre"], r["batch_id"]),
        )
    n_prompt = 0
    for i, r in enumerate(ordered):
        new_prompt = refresh_prompt(r["prompt"])
        if new_prompt != r["prompt"]:
            n_prompt += 1
        conn.execute(
            "UPDATE batches SET queue_pos=?, genre=?, prompt=? WHERE batch_id=?",
            (i, r["genre"], new_prompt, r["batch_id"]),
        )
        if new_prompt != r["prompt"]:
            conn.execute(
                "UPDATE specs SET prompt=? WHERE batch_id=?",
                (new_prompt, r["batch_id"]),
            )
    conn.commit()

    # Rewrite prompts.jsonl from the DB so workers see the new order and wording.
    outp = ROOT / "prompts.jsonl"
    tmp = outp.with_suffix(".jsonl.tmp")
    with tmp.open("w") as f:
        q = conn.execute(
            """
            SELECT b.*, 
                   (SELECT GROUP_CONCAT(spec_id, '||') FROM specs s WHERE s.batch_id=b.batch_id) AS spec_ids
              FROM batches b
             ORDER BY COALESCE(queue_pos, batch_index)
            """
        )
        for row in q:
            rec = {k: row[k] for k in row.keys() if k != "spec_ids"}
            rec["spec_ids"] = (row["spec_ids"] or "").split("||") if row["spec_ids"] else []
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    tmp.replace(outp)

    progress = snapshot_progress(conn)

    # Preview the next few claims per shard
    preview = {}
    shards = int(progress.get("shards") or 4)
    for s in range(shards):
        prev = conn.execute(
            """
            SELECT queue_pos, batch_id, style_pack, category, genre, kind
              FROM batches
             WHERE status='pending' AND (COALESCE(queue_pos, batch_index) % ?) = ?
             ORDER BY COALESCE(queue_pos, batch_index)
             LIMIT 8
            """,
            (shards, s),
        ).fetchall()
        preview[str(s)] = [dict(r) for r in prev]
    conn.close()
    print(json.dumps({
        "pending_reordered": len(ordered),
        "prompts_updated": n_prompt,
        "progress": progress,
        "next_per_shard": preview,
    }, indent=2))


if __name__ == "__main__":
    main()
