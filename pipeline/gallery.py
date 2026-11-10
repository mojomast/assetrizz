#!/usr/bin/env python3
"""Live read-only gallery for the game asset library.

Binds to 127.0.0.1 only. Opens assets.db with mode=ro and a short timeout
so it never blocks the generator workers. Does not touch the queue, claims,
workers, or schema.

Restart:
  pkill -f /workspace/game-assets/gallery.py
  mkdir -p /workspace/game-assets/logs
  nohup nice -n 15 python3 -u /workspace/game-assets/gallery.py --host 127.0.0.1 --port 8792 \\
    >> /workspace/game-assets/logs/gallery.log 2>&1 &
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import sqlite3
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path("/workspace/game-assets").resolve()
DB_PATH = ROOT / "assets.db"
DB_URI = f"file:{DB_PATH}?mode=ro"
BUSY_TIMEOUT_MS = 1500
CONNECT_TIMEOUT_S = 1.5
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8792
PAGE_SIZE = 100
CANONICAL_CATEGORIES = [
    "icons", "tiles", "props", "characters", "enemies", "ui", "vfx", "backgrounds",
    "vehicles", "buildings", "furniture", "foliage", "creatures", "portraits",
    "weapons", "decals", "markers", "terrain",
]
MAX_LIMIT = 200

LIST_FIELDS = (
    "id", "slug", "path", "thumb_path", "category", "subcategory", "subject",
    "style_pack", "tags", "description", "width", "height", "has_alpha",
    "tileable", "license", "status", "created_at", "batch_id",
)
JSON_FIELDS = ("tags",)


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_URI, uri=True, timeout=CONNECT_TIMEOUT_S)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=ON")
    con.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    return con


def row_to_dict(row: sqlite3.Row, *, full: bool = False) -> dict:
    if full:
        d = {k: row[k] for k in row.keys()}
        for k in ("tags", "palette", "dominant_colors", "pivot", "frame_info", "qa_notes"):
            if d.get(k):
                try:
                    d[k] = json.loads(d[k])
                except (TypeError, ValueError):
                    pass
    else:
        d = {k: row[k] for k in LIST_FIELDS if k in row.keys()}
        for k in JSON_FIELDS:
            if d.get(k):
                try:
                    d[k] = json.loads(d[k])
                except (TypeError, ValueError):
                    pass
    thumb = d.get("thumb_path") or d.get("path")
    path = d.get("path")
    if thumb:
        d["thumb_url"] = "/file/" + thumb.lstrip("/")
    if path:
        d["image_url"] = "/file/" + path.lstrip("/")
    return d


def fts_query(raw: str) -> str | None:
    tokens = re.findall(r"[A-Za-z0-9_]+", raw or "")
    if not tokens:
        return None
    return " AND ".join(f'"{t}"' for t in tokens[:24])


def _filters(qs: dict) -> tuple[str, list, str]:
    where = ["1=1"]
    args: list = []
    join = ""
    q = (qs.get("q") or [""])[0].strip()
    status = (qs.get("status") or ["ok"])[0].strip() or "ok"
    if status != "any":
        where.append("a.status = ?")
        args.append(status)
    style = (qs.get("style") or qs.get("style_pack") or [""])[0].strip()
    if style:
        where.append("a.style_pack = ?")
        args.append(style)
    category = (qs.get("category") or [""])[0].strip()
    if category:
        where.append("a.category = ?")
        args.append(category)
    subcategory = (qs.get("subcategory") or [""])[0].strip()
    if subcategory:
        where.append("a.subcategory = ?")
        args.append(subcategory)
    if q:
        fts = fts_query(q)
        if fts:
            join = "JOIN assets_fts ON assets_fts.rowid = a.id"
            where.append("assets_fts MATCH ?")
            args.append(fts)
    return " AND ".join(where), args, join


def search_assets(qs: dict) -> dict:
    try:
        limit = int((qs.get("limit") or [str(PAGE_SIZE)])[0])
        offset = int((qs.get("offset") or ["0"])[0])
        before_id = int(qs["before_id"][0]) if qs.get("before_id") and qs["before_id"][0] else None
        since_id = int(qs["since_id"][0]) if qs.get("since_id") and qs["since_id"][0] else None
    except (TypeError, ValueError) as exc:
        raise ValueError("bad numeric param") from exc
    limit = max(1, min(limit, MAX_LIMIT))
    offset = max(0, offset)

    where, args, join = _filters(qs)
    if since_id is not None:
        where = f"{where} AND a.id > ?"
        args = list(args) + [since_id]
        # Newest first so the client can prepend in order after reversing, or
        # just iterate and prepend one-by-one from the end. We return newest first.
        order = "a.created_at DESC, a.id DESC"
        page_sql_args = args + [limit]
        page_limit = "LIMIT ?"
        offset_clause = ""
    elif before_id is not None:
        where = f"{where} AND a.id < ?"
        args = list(args) + [before_id]
        order = "a.created_at DESC, a.id DESC"
        page_sql_args = args + [limit]
        page_limit = "LIMIT ?"
        offset_clause = ""
    else:
        order = "a.created_at DESC, a.id DESC"
        page_sql_args = args + [limit, offset]
        page_limit = "LIMIT ?"
        offset_clause = "OFFSET ?"

    cols = ", ".join(f"a.{c}" for c in LIST_FIELDS)
    sql = f"""
        SELECT {cols}
          FROM assets a
          {join}
         WHERE {where}
         ORDER BY {order}
         {page_limit} {offset_clause}
    """
    count_sql = f"SELECT COUNT(*) FROM assets a {join} WHERE {where}"
    # For since/before, total should still be the unfiltered-by-cursor count.
    total_where, total_args, total_join = _filters(qs)

    con = connect()
    try:
        try:
            rows = con.execute(sql, page_sql_args).fetchall()
            total = con.execute(
                f"SELECT COUNT(*) FROM assets a {total_join} WHERE {total_where}",
                total_args,
            ).fetchone()[0]
            max_id = con.execute("SELECT COALESCE(MAX(id), 0) FROM assets").fetchone()[0]
        except sqlite3.OperationalError:
            if not (qs.get("q") or [""])[0].strip():
                raise
            # FTS syntax or tokenizer issue: fall back to LIKE.
            like = f"%{(qs.get('q') or [''])[0].strip()}%"
            where, args, _join = _filters({k: v for k, v in qs.items() if k != "q"})
            where = f"{where} AND (a.description LIKE ? OR a.tags LIKE ? OR a.subject LIKE ? OR a.slug LIKE ? OR a.category LIKE ? OR a.subcategory LIKE ? OR a.style_pack LIKE ?)"
            like_args = list(args) + [like] * 7
            if since_id is not None:
                where = f"{where} AND a.id > ?"
                like_args.append(since_id)
                page_sql_args = like_args + [limit]
                offset_clause = ""
            elif before_id is not None:
                where = f"{where} AND a.id < ?"
                like_args.append(before_id)
                page_sql_args = like_args + [limit]
                offset_clause = ""
            else:
                page_sql_args = like_args + [limit, offset]
                offset_clause = "OFFSET ?"
            rows = con.execute(
                f"""SELECT {cols} FROM assets a WHERE {where}
                    ORDER BY a.created_at DESC, a.id DESC LIMIT ? {offset_clause}""",
                page_sql_args,
            ).fetchall()
            total = con.execute(
                f"SELECT COUNT(*) FROM assets a WHERE {where.replace(' AND a.id > ?', '').replace(' AND a.id < ?', '')}",
                like_args[: len(like_args) - (1 if since_id or before_id else 0)],
            ).fetchone()[0]
            max_id = con.execute("SELECT COALESCE(MAX(id), 0) FROM assets").fetchone()[0]
    finally:
        con.close()

    results = [row_to_dict(r) for r in rows]
    return {
        "count": len(results),
        "total": total,
        "max_id": max_id,
        "limit": limit,
        "offset": offset,
        "results": results,
    }


def asset_detail(asset_id: int) -> dict | None:
    con = connect()
    try:
        row = con.execute("SELECT * FROM assets WHERE id = ?", (asset_id,)).fetchone()
    finally:
        con.close()
    if row is None:
        return None
    return row_to_dict(row, full=True)


def stats(qs: dict | None = None) -> dict:
    qs = qs or {}
    where, args, join = _filters(qs)
    con = connect()
    try:
        total_ok = con.execute("SELECT COUNT(*) FROM assets WHERE status='ok'").fetchone()[0]
        total_rejected = con.execute("SELECT COUNT(*) FROM assets WHERE status='rejected'").fetchone()[0]
        total_all = con.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
        max_id = con.execute("SELECT COALESCE(MAX(id), 0) FROM assets").fetchone()[0]
        filtered = con.execute(
            f"SELECT COUNT(*) FROM assets a {join} WHERE {where}", args
        ).fetchone()[0]
        counts = {
            r[0]: r[1]
            for r in con.execute(
                "SELECT style_pack, COUNT(*) n FROM assets WHERE status='ok' "
                "GROUP BY style_pack"
            )
        }
        pack_path = ROOT / "style_packs.json"
        pack_ids = []
        if pack_path.exists():
            try:
                pack_ids = list(json.loads(pack_path.read_text()).keys())
            except (OSError, ValueError):
                pack_ids = []
        if not pack_ids:
            pack_ids = sorted(counts)
        extra = [s for s in sorted(counts) if s not in pack_ids]
        styles = [{"style_pack": s, "n": int(counts.get(s, 0))} for s in pack_ids + extra]
        cat_counts = {
            r[0]: r[1]
            for r in con.execute(
                "SELECT category, COUNT(*) n FROM assets WHERE status='ok' "
                "GROUP BY category"
            )
        }
        extra_cats = [c for c in sorted(cat_counts) if c not in CANONICAL_CATEGORIES]
        categories = [
            {"category": c, "n": int(cat_counts.get(c, 0))}
            for c in CANONICAL_CATEGORIES + extra_cats
        ]
        subcategories = [
            {"category": r[0], "subcategory": r[1], "n": r[2]}
            for r in con.execute(
                "SELECT category, subcategory, COUNT(*) n FROM assets WHERE status='ok' "
                "GROUP BY category, subcategory ORDER BY category, subcategory"
            )
        ]
    finally:
        con.close()
    return {
        "total": total_ok,
        "total_ok": total_ok,
        "total_rejected": total_rejected,
        "total_all": total_all,
        "filtered": filtered,
        "max_id": max_id,
        "styles": styles,
        "categories": categories,
        "subcategories": subcategories,
    }


def safe_path(rel: str) -> Path | None:
    if not rel or "\x00" in rel:
        return None
    rel = rel.lstrip("/")
    # Disallow absolute and Windows drive paths before resolve.
    candidate = Path(rel)
    if candidate.is_absolute():
        return None
    try:
        resolved = (ROOT / rel).resolve()
    except (OSError, ValueError):
        return None
    if not resolved.is_relative_to(ROOT):
        return None
    if not resolved.is_file():
        return None
    return resolved


HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Game Asset Library</title>
<style>
  :root {
    --bg: #0c0d12;
    --bg-raised: #161821;
    --bg-hover: #1e2130;
    --line: #2a2e3f;
    --text: #e8e6df;
    --muted: #9a97a8;
    --accent: #e6b84f;
    --accent-2: #7ad0c8;
    --danger: #e07a6a;
    --shadow: 0 16px 40px rgba(0,0,0,.45);
    --check-a: #1b1d28;
    --check-b: #12131a;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; background: var(--bg); color: var(--text);
    font: 14px/1.45 "Segoe UI", system-ui, -apple-system, sans-serif; }
  header {
    position: sticky; top: 0; z-index: 20;
    background: rgba(12,13,18,.92); backdrop-filter: blur(12px);
    border-bottom: 1px solid var(--line);
    padding: 12px 20px 14px;
  }
  .bar { display: flex; flex-wrap: wrap; gap: 10px 14px; align-items: center; }
  h1 { margin: 0; font-size: 16px; font-weight: 650; letter-spacing: .02em; }
  h1 span { color: var(--accent); }
  .count { color: var(--muted); font-variant-numeric: tabular-nums; }
  .count b { color: var(--text); font-weight: 650; }
  .new-chip {
    display: none; border: 0; cursor: pointer;
    background: var(--accent); color: #1a1406; font-weight: 700;
    border-radius: 999px; padding: 4px 10px; font-size: 12px;
  }
  .new-chip.show { display: inline-flex; }
  input[type=search], select {
    background: var(--bg-raised); color: var(--text);
    border: 1px solid var(--line); border-radius: 8px;
    padding: 7px 10px; min-width: 0;
  }
  input[type=search] { flex: 1 1 220px; min-width: 180px; }
  select { flex: 0 1 auto; }
  input:focus, select:focus { outline: 2px solid var(--accent); outline-offset: 1px; }
  .status { color: var(--muted); font-size: 12px; margin-left: auto; }
  .status.live { color: var(--accent-2); }
  .status.err { color: var(--danger); }
  main { padding: 16px 20px 80px; }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(132px, 1fr));
    gap: 12px;
  }
  .card {
    background: var(--bg-raised); border: 1px solid var(--line);
    border-radius: 10px; overflow: hidden; cursor: pointer;
    display: flex; flex-direction: column; min-width: 0;
    transition: border-color .15s, transform .15s;
  }
  .card:hover, .card:focus { border-color: var(--accent); transform: translateY(-1px); outline: none; }
  .card.fresh { box-shadow: 0 0 0 1px var(--accent-2); }
  .thumb {
    aspect-ratio: 1; display: grid; place-items: center;
    background-color: var(--check-b);
    background-image:
      linear-gradient(45deg, var(--check-a) 25%, transparent 25%),
      linear-gradient(-45deg, var(--check-a) 25%, transparent 25%),
      linear-gradient(45deg, transparent 75%, var(--check-a) 75%),
      linear-gradient(-45deg, transparent 75%, var(--check-a) 75%);
    background-size: 16px 16px;
    background-position: 0 0, 0 8px, 8px -8px, -8px 0;
  }
  .thumb img {
    max-width: 100%; max-height: 100%; object-fit: contain;
    image-rendering: auto;
  }
  .thumb img.pixel { image-rendering: pixelated; }
  .meta { padding: 7px 8px 8px; min-height: 46px; }
  .meta .name { font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .meta .sub { color: var(--muted); font-size: 11px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .empty, .end { text-align: center; color: var(--muted); padding: 40px 12px; }
  #sentinel { height: 1px; }
  dialog {
    border: 1px solid var(--line); border-radius: 14px;
    background: var(--bg-raised); color: var(--text);
    padding: 0; max-width: min(920px, 96vw); width: 920px;
    box-shadow: var(--shadow);
  }
  dialog::backdrop { background: rgba(0,0,0,.72); }
  .dlg { display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(260px, .9fr); }
  @media (max-width: 720px) { .dlg { grid-template-columns: 1fr; } }
  .dlg-art {
    min-height: 280px; display: grid; place-items: center; padding: 20px;
    background-color: var(--check-b);
    background-image:
      linear-gradient(45deg, var(--check-a) 25%, transparent 25%),
      linear-gradient(-45deg, var(--check-a) 25%, transparent 25%),
      linear-gradient(45deg, transparent 75%, var(--check-a) 75%),
      linear-gradient(-45deg, transparent 75%, var(--check-a) 75%);
    background-size: 20px 20px;
    background-position: 0 0, 0 10px, 10px -10px, -10px 0;
  }
  .dlg-art img { max-width: 100%; max-height: min(70vh, 640px); object-fit: contain; }
  .dlg-art img.pixel { image-rendering: pixelated; }
  .dlg-info { padding: 18px 18px 16px; border-left: 1px solid var(--line); display: flex; flex-direction: column; gap: 10px; }
  .dlg-info h2 { margin: 0; font-size: 18px; word-break: break-word; }
  .kv { display: grid; grid-template-columns: 86px 1fr; gap: 4px 8px; font-size: 13px; }
  .kv dt { color: var(--muted); }
  .kv dd { margin: 0; word-break: break-word; }
  .tags { display: flex; flex-wrap: wrap; gap: 6px; }
  .tags span { background: #262a3a; border-radius: 999px; padding: 2px 8px; font-size: 11px; color: #d4d1c8; }
  .path { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; background: #0c0d12; padding: 8px; border-radius: 8px; word-break: break-all; }
  .actions { display: flex; gap: 8px; margin-top: auto; }
  button {
    background: var(--accent); color: #1a1406; border: 0; border-radius: 8px;
    padding: 8px 12px; font-weight: 700; cursor: pointer;
  }
  button.ghost { background: transparent; color: var(--text); border: 1px solid var(--line); font-weight: 600; }
  button:hover { filter: brightness(1.08); }
</style>
</head>
<body>
<header>
  <div class="bar">
    <h1>Game Asset <span>Library</span></h1>
    <div class="count" id="counter">Loading…</div>
    <button class="new-chip" id="newChip" type="button"></button>
    <span class="status" id="status">connecting</span>
  </div>
  <div class="bar" style="margin-top:10px">
    <input type="search" id="q" placeholder="Search names, tags, subjects…" autocomplete="off">
    <select id="style"><option value="">All styles</option></select>
    <select id="category"><option value="">All categories</option></select>
    <select id="subcategory"><option value="">All subcategories</option></select>
  </div>
</header>
<main>
  <div class="grid" id="grid"></div>
  <div id="sentinel"></div>
  <div class="end" id="end" hidden>End of results</div>
  <div class="empty" id="empty" hidden>No assets match these filters.</div>
</main>
<dialog id="dlg">
  <div class="dlg">
    <div class="dlg-art" id="dlgArt"></div>
    <div class="dlg-info">
      <h2 id="dlgName"></h2>
      <dl class="kv" id="dlgKv"></dl>
      <div class="tags" id="dlgTags"></div>
      <div class="path" id="dlgPath"></div>
      <div class="actions">
        <button type="button" id="copyBtn">Copy path</button>
        <button type="button" class="ghost" id="closeBtn">Close</button>
      </div>
    </div>
  </div>
</dialog>
<script>
(() => {
  const PAGE = 100;
  const POLL_MS = 10000;
  const grid = document.getElementById("grid");
  const counter = document.getElementById("counter");
  const statusEl = document.getElementById("status");
  const emptyEl = document.getElementById("empty");
  const endEl = document.getElementById("end");
  const qEl = document.getElementById("q");
  const styleEl = document.getElementById("style");
  const catEl = document.getElementById("category");
  const subEl = document.getElementById("subcategory");
  const newChip = document.getElementById("newChip");
  const dlg = document.getElementById("dlg");
  const copyBtn = document.getElementById("copyBtn");
  const closeBtn = document.getElementById("closeBtn");

  let items = [];
  let total = 0;
  let libraryTotal = 0;
  let loading = false;
  let done = false;
  let searchTimer = 0;
  let unseenNew = [];
  let facets = { styles: [], categories: [], subcategories: [] };
  let openId = null;

  const fmt = (n) => Number(n||0).toLocaleString("en-US");
  const isPixel = (a) => { const s=a.style_pack||""; return s.startsWith("pixel") || s.includes("8bit") || (a.width||0) <= 64; };
  const params = () => {
    const p = new URLSearchParams();
    if (qEl.value.trim()) p.set("q", qEl.value.trim());
    if (styleEl.value) p.set("style", styleEl.value);
    if (catEl.value) p.set("category", catEl.value);
    if (subEl.value) p.set("subcategory", subEl.value);
    return p;
  };

  function setStatus(text, cls) {
    statusEl.textContent = text;
    statusEl.className = "status" + (cls ? " " + cls : "");
  }

  function renderCounter() {
    const filterNote = (qEl.value || styleEl.value || catEl.value || subEl.value)
      ? ` · showing ${fmt(total)}`
      : "";
    counter.innerHTML = `<b>${fmt(libraryTotal)}</b> assets${filterNote}`;
  }

  function fillSelect(el, rows, valueKey, allLabel, keep) {
    const prev = keep || el.value;
    el.innerHTML = "";
    const all = document.createElement("option");
    all.value = "";
    all.textContent = allLabel;
    el.appendChild(all);
    for (const row of rows) {
      const opt = document.createElement("option");
      opt.value = row[valueKey];
      opt.textContent = `${row[valueKey]} (${fmt(row.n)})`;
      el.appendChild(opt);
    }
    if ([...el.options].some(o => o.value === prev)) el.value = prev;
  }

  function updateSubcats() {
    const cat = catEl.value;
    let rows = facets.subcategories || [];
    if (cat) rows = rows.filter(r => r.category === cat);
    // Merge same subcategory names when viewing all categories.
    if (!cat) {
      const map = new Map();
      for (const r of rows) {
        const k = r.subcategory || "(none)";
        map.set(k, (map.get(k)||0) + r.n);
      }
      rows = [...map.entries()].map(([subcategory, n]) => ({ subcategory, n }));
    }
    fillSelect(subEl, rows, "subcategory", "All subcategories", subEl.value);
  }

  function cardEl(a, fresh) {
    const el = document.createElement("article");
    el.className = "card" + (fresh ? " fresh" : "");
    el.tabIndex = 0;
    el.dataset.id = a.id;
    const src = a.thumb_url || a.image_url;
    const pix = isPixel(a) ? " pixel" : "";
    const name = a.subject || a.slug || ("#" + a.id);
    const sub = [a.style_pack, a.category, a.subcategory].filter(Boolean).join(" · ");
    el.innerHTML = `<div class="thumb"><img src="${src}" alt="" loading="lazy" class="${pix.trim()}"></div>
      <div class="meta"><div class="name" title="${name}">${name}</div><div class="sub">${sub}</div></div>`;
    el.addEventListener("click", () => openAsset(a.id));
    el.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openAsset(a.id); }});
    return el;
  }

  function renderAll() {
    grid.innerHTML = "";
    const frag = document.createDocumentFragment();
    for (const a of items) frag.appendChild(cardEl(a, false));
    grid.appendChild(frag);
    emptyEl.hidden = items.length > 0;
    endEl.hidden = !done || items.length === 0;
  }

  function prepend(newItems) {
    const nearTop = window.scrollY < 120;
    if (!nearTop) {
      unseenNew = newItems.concat(unseenNew);
      newChip.textContent = `${unseenNew.length} new`;
      newChip.classList.add("show");
      items = newItems.concat(items);
      return;
    }
    unseenNew = [];
    newChip.classList.remove("show");
    const frag = document.createDocumentFragment();
    for (const a of newItems) frag.appendChild(cardEl(a, true));
    grid.insertBefore(frag, grid.firstChild);
    items = newItems.concat(items);
    setTimeout(() => {
      for (const el of grid.querySelectorAll(".card.fresh")) el.classList.remove("fresh");
    }, 2500);
  }

  newChip.addEventListener("click", () => {
    unseenNew = [];
    newChip.classList.remove("show");
    renderAll();
    window.scrollTo({ top: 0, behavior: "smooth" });
  });

  async function fetchJSON(url) {
    const res = await fetch(url);
    if (!res.ok) throw new Error(res.status + " " + res.statusText);
    return res.json();
  }

  async function loadFacets() {
    const data = await fetchJSON("/api/stats");
    facets = data;
    libraryTotal = data.total_ok ?? data.total ?? 0;
    fillSelect(styleEl, data.styles || [], "style_pack", "All styles", styleEl.value);
    fillSelect(catEl, data.categories || [], "category", "All categories", catEl.value);
    updateSubcats();
    renderCounter();
  }

  async function loadPage(reset) {
    if (loading) return;
    if (reset) { done = false; items = []; unseenNew = []; newChip.classList.remove("show"); }
    if (done) return;
    loading = true;
    try {
      const p = params();
      p.set("limit", String(PAGE));
      if (!reset && items.length) p.set("before_id", String(items[items.length-1].id));
      const data = await fetchJSON("/api/assets?" + p.toString());
      total = data.total;
      if (data.max_id && !libraryTotal) libraryTotal = data.total;
      const batch = data.results || [];
      if (reset) {
        items = batch;
        renderAll();
      } else {
        const seen = new Set(items.map(i => i.id));
        const fresh = batch.filter(a => !seen.has(a.id));
        items = items.concat(fresh);
        const frag = document.createDocumentFragment();
        for (const a of fresh) frag.appendChild(cardEl(a, false));
        grid.appendChild(frag);
        emptyEl.hidden = items.length > 0;
      }
      if (batch.length < PAGE) done = true;
      endEl.hidden = !done || items.length === 0;
      renderCounter();
      setStatus("live", "live");
    } catch (err) {
      setStatus("error", "err");
      console.warn(err);
    } finally {
      loading = false;
    }
  }

  async function pollNew() {
    try {
      await loadFacets();
      const p = params();
      const newest = items.length ? Math.max(...items.map(i => i.id), ...(unseenNew.map(i => i.id))) : 0;
      if (!newest) return;
      p.set("since_id", String(newest));
      p.set("limit", "200");
      const data = await fetchJSON("/api/assets?" + p.toString());
      total = data.total;
      renderCounter();
      const seen = new Set(items.map(i => i.id));
      const fresh = (data.results || []).filter(a => !seen.has(a.id))
        .sort((a,b) => (a.id < b.id ? 1 : -1)); // already newest first
      // Prepend oldest-of-the-new first so visual order stays newest at top
      // after inserting each at the beginning? results are newest first;
      // prepend() inserts the whole block at the top in given order.
      if (fresh.length) prepend(fresh);
      setStatus("live", "live");
    } catch (err) {
      setStatus("retrying", "err");
    }
  }

  async function openAsset(id) {
    openId = id;
    let a = items.find(x => x.id === id);
    try {
      const full = await fetchJSON("/api/asset/" + id);
      a = full;
    } catch (_) {}
    if (!a) return;
    const name = a.subject || a.slug || ("#" + a.id);
    document.getElementById("dlgName").textContent = name;
    const art = document.getElementById("dlgArt");
    const pix = isPixel(a) ? " pixel" : "";
    const src = a.image_url || a.thumb_url;
    art.innerHTML = `<img src="${src}" alt="${name}" class="${pix.trim()}">`;
    const tags = Array.isArray(a.tags) ? a.tags : [];
    document.getElementById("dlgTags").innerHTML = tags.map(t => `<span>${t}</span>`).join("");
    const path = a.path || "";
    document.getElementById("dlgPath").textContent = path;
    copyBtn.dataset.path = path;
    const size = (a.width && a.height) ? `${a.width} × ${a.height}` : "—";
    const rows = [
      ["Name", name],
      ["Style", a.style_pack || "—"],
      ["Category", [a.category, a.subcategory].filter(Boolean).join(" / ") || "—"],
      ["Tags", tags.length ? tags.join(", ") : "—"],
      ["Size", size],
      ["Path", path || "—"],
      ["Created", a.created_at || "—"],
    ];
    document.getElementById("dlgKv").innerHTML = rows.map(([k,v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("");
    if (!dlg.open) dlg.showModal();
  }

  copyBtn.addEventListener("click", async () => {
    const path = copyBtn.dataset.path || "";
    try {
      await navigator.clipboard.writeText(path);
      copyBtn.textContent = "Copied";
      setTimeout(() => { copyBtn.textContent = "Copy path"; }, 1200);
    } catch {
      copyBtn.textContent = "Copy failed";
      setTimeout(() => { copyBtn.textContent = "Copy path"; }, 1200);
    }
  });
  closeBtn.addEventListener("click", () => dlg.close());
  dlg.addEventListener("click", (e) => { if (e.target === dlg) dlg.close(); });

  document.addEventListener("keydown", (e) => {
    if (!dlg.open) return;
    if (e.key === "Escape") dlg.close();
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    const idx = items.findIndex(a => a.id === openId);
    if (idx < 0) return;
    const next = e.key === "ArrowRight" ? idx + 1 : idx - 1;
    if (next >= 0 && next < items.length) openAsset(items[next].id);
  });

  const observer = new IntersectionObserver((entries) => {
    if (entries.some(e => e.isIntersecting)) loadPage(false);
  }, { rootMargin: "600px" });
  observer.observe(document.getElementById("sentinel"));

  let filterLock = false;
  async function onFilterChange() {
    if (filterLock) return;
    updateSubcats();
    await loadPage(true);
  }
  styleEl.addEventListener("change", onFilterChange);
  catEl.addEventListener("change", () => { subEl.value = ""; onFilterChange(); });
  subEl.addEventListener("change", onFilterChange);
  qEl.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => loadPage(true), 250);
  });

  (async () => {
    try {
      await loadFacets();
      await loadPage(true);
    } catch (err) {
      setStatus("error", "err");
      emptyEl.hidden = false;
      emptyEl.textContent = "Could not load the library.";
    }
    setInterval(pollNew, POLL_MS);
  })();
})();
</script>
</body>
</html>
"""


class GalleryHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))
        sys.stderr.flush()

    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None, cache: str | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        if cache:
            self.send_header("Cache-Control", cache)
        else:
            self.send_header("Cache-Control", "no-store")
        if extra:
            for k, v in extra.items():
                self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code: int, obj: dict):
        body = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode()
        self._send(code, body, "application/json; charset=utf-8")

    def _err_from_exc(self, exc: BaseException):
        if isinstance(exc, ValueError):
            return self._json(400, {"error": str(exc)})
        if isinstance(exc, sqlite3.OperationalError):
            # Typically a lock/timeout; do not stall workers, just tell the client to retry.
            return self._json(503, {"error": "catalog busy, retry"})
        sys.stderr.write("gallery error: %s\n%s\n" % (exc, traceback.format_exc()))
        return self._json(500, {"error": "internal error"})

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        u = urlparse(self.path)
        path = unquote(u.path)
        qs = parse_qs(u.query)
        try:
            if path in ("/", "/index.html", "/gallery"):
                return self._send(200, HTML.encode("utf-8"), "text/html; charset=utf-8")
            if path in ("/health", "/api/health"):
                return self._json(200, {"ok": True, "service": "game-assets-gallery", "root": str(ROOT)})
            if path in ("/stats", "/api/stats"):
                return self._json(200, stats(qs))
            if path in ("/search", "/api/search", "/api/list", "/api/assets"):
                return self._json(200, search_assets(qs))
            if path.startswith("/api/asset/"):
                rest = path[len("/api/asset/"):].strip("/")
                if not rest.isdigit():
                    return self._json(400, {"error": "bad id"})
                row = asset_detail(int(rest))
                if row is None:
                    return self._json(404, {"error": "not found"})
                return self._json(200, row)
            if path.startswith("/file/"):
                return self._serve_file(path[len("/file/"):])
            if path.startswith("/thumb/"):
                return self._serve_by_id(path[len("/thumb/"):], thumb=True)
            if path.startswith("/image/"):
                return self._serve_by_id(path[len("/image/"):], thumb=False)
            return self._json(404, {
                "error": "not found",
                "routes": ["/", "/health", "/api/stats", "/api/assets", "/api/search", "/api/asset/<id>", "/file/<path>"],
            })
        except Exception as exc:
            return self._err_from_exc(exc)

    def _serve_by_id(self, raw_id: str, *, thumb: bool):
        raw_id = raw_id.strip("/")
        if not raw_id.isdigit():
            return self._json(400, {"error": "bad id"})
        con = connect()
        try:
            row = con.execute(
                "SELECT path, thumb_path FROM assets WHERE id = ?", (int(raw_id),)
            ).fetchone()
        finally:
            con.close()
        if row is None:
            return self._json(404, {"error": "not found"})
        rel = (row["thumb_path"] if thumb and row["thumb_path"] else row["path"]) or ""
        return self._serve_file(rel)

    def _serve_file(self, rel: str):
        rel = unquote(rel).lstrip("/")
        target = safe_path(rel)
        if target is None:
            # Distinguish traversal from missing: if the resolved path would escape, 403.
            try:
                tentative = (ROOT / rel.lstrip("/")).resolve()
                escaped = not tentative.is_relative_to(ROOT)
            except (OSError, ValueError):
                escaped = True
            if escaped or not rel:
                return self._json(403, {"error": "forbidden"})
            return self._json(404, {"error": "not found"})
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        data = target.read_bytes()
        self._send(200, data, ctype, cache="public, max-age=3600")


class GalleryServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    ap = argparse.ArgumentParser(description="Read-only live gallery for the game asset library")
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = ap.parse_args()
    httpd = GalleryServer((args.host, args.port), GalleryHandler)
    print(f"gallery on http://{args.host}:{args.port}/  (db={DB_PATH})", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("gallery stopping", flush=True)
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
