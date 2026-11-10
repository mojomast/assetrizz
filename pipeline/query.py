#!/usr/bin/env python3
"""Search the asset catalog (FTS5 + filters). Prints JSON."""
from __future__ import annotations

import argparse
import json
import sys

from db import DB_PATH, connect, init_db


def search(
    q: str | None = None,
    *,
    category: str | None = None,
    style: str | None = None,
    size: int | None = None,
    min_size: int | None = None,
    alpha: bool | None = None,
    tileable: bool | None = None,
    status: str = "ok",
    subject: str | None = None,
    limit: int = 30,
    offset: int = 0,
) -> list[dict]:
    conn = init_db()
    where = ["1=1"]
    args: list = []
    join = ""
    if q:
        join = "JOIN assets_fts f ON f.rowid = a.id"
        where.append("assets_fts MATCH ?")
        # rewrite: allow plain words
        args.append(q)
        # After join we need the MATCH on the fts table name
        where[-1] = "f.assets_fts MATCH ?" if False else "assets_fts MATCH ?"
        # FTS5: `assets_fts MATCH` works when querying the fts table; with join use:
        where[-1] = "f.rowid IS NOT NULL AND assets_fts MATCH ?"
    # Fix the FTS clause properly
    if q:
        join = "JOIN assets_fts ON assets_fts.rowid = a.id"
        where = [w for w in where if "MATCH" not in w and w != "f.rowid IS NOT NULL AND assets_fts MATCH ?"]
        where.append("assets_fts MATCH ?")
        # args already has q
    if category:
        where.append("a.category = ?")
        args.append(category)
    if style:
        where.append("a.style_pack = ?")
        args.append(style)
    if subject:
        where.append("a.subject = ?")
        args.append(subject)
    if size:
        where.append("a.width = ? AND a.height = ?")
        args.extend([size, size])
    if min_size:
        where.append("a.width >= ? AND a.height >= ?")
        args.extend([min_size, min_size])
    if alpha is True:
        where.append("a.has_alpha = 1")
    elif alpha is False:
        where.append("a.has_alpha = 0")
    if tileable is True:
        where.append("a.tileable = 1")
    elif tileable is False:
        where.append("a.tileable = 0")
    if status:
        where.append("a.status = ?")
        args.append(status)

    sql = f"""
    SELECT a.id, a.slug, a.path, a.thumb_path, a.category, a.subcategory, a.subject,
           a.style_pack, a.tags, a.description, a.width, a.height, a.has_alpha,
           a.palette, a.dominant_colors, a.tileable, a.pivot, a.frame_info,
           a.license, a.status, a.qa_notes, a.batch_id, a.spec_id, a.created_at
      FROM assets a
      {join}
     WHERE {' AND '.join(where)}
     ORDER BY a.id DESC
     LIMIT ? OFFSET ?
    """
    args.extend([limit, offset])
    try:
        rows = conn.execute(sql, args).fetchall()
    except Exception as e:
        if q:
            # FTS syntax error: fall back to LIKE
            conn.close()
            return search_like(q, category=category, style=style, size=size, min_size=min_size,
                               alpha=alpha, tileable=tileable, status=status, subject=subject,
                               limit=limit, offset=offset)
        raise
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        for k in ("tags", "palette", "dominant_colors", "pivot", "frame_info", "qa_notes"):
            if d.get(k):
                try:
                    d[k] = json.loads(d[k])
                except Exception:
                    pass
        out.append(d)
    return out


def search_like(q, **kw):
    conn = init_db()
    like = f"%{q}%"
    where = ["(a.description LIKE ? OR a.tags LIKE ? OR a.subject LIKE ? OR a.slug LIKE ?)"]
    args = [like, like, like, like]
    if kw.get("category"):
        where.append("a.category=?"); args.append(kw["category"])
    if kw.get("style"):
        where.append("a.style_pack=?"); args.append(kw["style"])
    if kw.get("subject"):
        where.append("a.subject=?"); args.append(kw["subject"])
    if kw.get("size"):
        where.append("a.width=? AND a.height=?"); args.extend([kw["size"], kw["size"]])
    if kw.get("min_size"):
        where.append("a.width>=? AND a.height>=?"); args.extend([kw["min_size"], kw["min_size"]])
    if kw.get("alpha") is True:
        where.append("a.has_alpha=1")
    elif kw.get("alpha") is False:
        where.append("a.has_alpha=0")
    if kw.get("tileable") is True:
        where.append("a.tileable=1")
    elif kw.get("tileable") is False:
        where.append("a.tileable=0")
    if kw.get("status"):
        where.append("a.status=?"); args.append(kw["status"])
    args += [kw.get("limit", 30), kw.get("offset", 0)]
    rows = conn.execute(
        f"""SELECT a.id, a.slug, a.path, a.thumb_path, a.category, a.subcategory, a.subject,
                  a.style_pack, a.tags, a.description, a.width, a.height, a.has_alpha,
                  a.palette, a.dominant_colors, a.tileable, a.pivot, a.frame_info,
                  a.license, a.status, a.qa_notes, a.batch_id, a.spec_id, a.created_at
             FROM assets a WHERE {' AND '.join(where)} ORDER BY a.id DESC LIMIT ? OFFSET ?""",
        args,
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        for k in ("tags", "palette", "dominant_colors", "pivot", "frame_info", "qa_notes"):
            if d.get(k):
                try:
                    d[k] = json.loads(d[k])
                except Exception:
                    pass
        out.append(d)
    return out


def stats() -> dict:
    conn = init_db()
    def q(sql):
        return [dict(r) for r in conn.execute(sql).fetchall()]
    out = {
        "total_ok": conn.execute("SELECT COUNT(*) c FROM assets WHERE status='ok'").fetchone()["c"],
        "total_rejected": conn.execute("SELECT COUNT(*) c FROM assets WHERE status='rejected'").fetchone()["c"],
        "by_category": q("SELECT category, COUNT(*) n FROM assets WHERE status='ok' GROUP BY category ORDER BY n DESC"),
        "by_style": q("SELECT style_pack, COUNT(*) n FROM assets WHERE status='ok' GROUP BY style_pack ORDER BY n DESC"),
        "batches": q("SELECT status, COUNT(*) n FROM batches GROUP BY status"),
    }
    conn.close()
    return out


def main():
    ap = argparse.ArgumentParser(description="Query the game asset library")
    ap.add_argument("query", nargs="?", help="FTS5 query (description, tags, subject)")
    ap.add_argument("--category", choices=["icons","tiles","props","characters","enemies","ui","vfx","backgrounds"])
    ap.add_argument("--style", dest="style")
    ap.add_argument("--subject")
    ap.add_argument("--size", type=int, help="Exact square size (e.g. 64)")
    ap.add_argument("--min-size", type=int)
    ap.add_argument("--alpha", action="store_true", help="Require transparency")
    ap.add_argument("--no-alpha", action="store_true")
    ap.add_argument("--tileable", action="store_true")
    ap.add_argument("--not-tileable", action="store_true")
    ap.add_argument("--status", default="ok")
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--json", action="store_true", default=True)
    args = ap.parse_args()
    if args.stats:
        print(json.dumps(stats(), indent=2))
        return
    alpha = True if args.alpha else (False if args.no_alpha else None)
    tileable = True if args.tileable else (False if args.not_tileable else None)
    rows = search(
        args.query,
        category=args.category,
        style=args.style,
        size=args.size,
        min_size=args.min_size,
        alpha=alpha,
        tileable=tileable,
        status=args.status,
        subject=args.subject,
        limit=args.limit,
        offset=args.offset,
    )
    print(json.dumps({"count": len(rows), "results": rows}, indent=2))


if __name__ == "__main__":
    main()
