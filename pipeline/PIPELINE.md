# Game asset library

An agent-searchable library of **original** 2D game assets for Kyle Durepos. Assets are generated in named style packs, post-processed (alpha, pixel-snap, thumbs, palette, dedupe), and indexed in SQLite with FTS5.

**License (every row):** `original, generated for Kyle Durepos`  
No real people. No trademarked or copyrighted characters. See `LICENSE.txt` and `RESEARCH.md`.

Unlimited image-generation window: until **5:00 AM America/Toronto on 10 Nov 2026**.

## Start a new worker on shard N (one line)

```bash
nice -n 15 python3 /workspace/game-assets/worker.py --shard N --shards 4
```

Replace `N` with `0`, `1`, `2`, or `3`. Use the same `--shards 4` on every worker. That command ingests any finished images in `work/shard-N/raw/`, claims the next pending batches for that shard (`batch_index % 4 == N`), and writes prompts to `work/shard-N/queue.jsonl` and `work/shard-N/NEXT.md`.

Then, for each claimed batch:

1. Call `GenerateImage` with the prompt, `filename` = `{batch_id}.png`, and the given `aspect_ratio`.
2. The tool usually returns a **JPEG** (often 1024×1024) under `/cursor/stores/user/grok-bot/agents/<agent-id>/assets/<hash>.jpg`, and it may ignore the filename. Convert and copy it:

```bash
python3 -c "from PIL import Image; Image.open('RETURNED_PATH').convert('RGB').save('work/shard-N/raw/BATCH_ID.png')"
```

3. Re-run the same one-liner to ingest and claim more. Do not pass `--claim` if you only want to ingest.

`GenerateImage` has no seed parameter; consistency comes from the locked style prefix, palette snap, and optional later reference images.

Leases last 30 minutes and are reclaimed if a worker dies. Do not change `--shards` mid-run.

## Layout

```
/workspace/game-assets/
  RESEARCH.md          why the pipeline looks like this (with sources)
  README.md            this file
  LICENSE.txt
  style_packs.json     locked style prefixes + palettes + sizes (15 packs)
  taxonomy.json        counts and shard rule (written by build_specs.py)
  specs.jsonl          one record per asset specification
  prompts.jsonl        one record per generation job (sheet or single)
  assets.db            SQLite catalog (WAL): specs, batches, claims, assets, FTS5
  manifest.jsonl       dump of ingested assets (rewritten after each ingest)
  PROGRESS.json        snapshot of counts (source of truth is assets.db)
  library/             accepted PNGs, path = {style}/{category}/{subcategory}/{subject}_{variant}.png
  thumbs/              128px previews, same relative slug
  raw/                 copied source sheets/singles
  rejected/            QA failures (still catalogued with status=rejected)
  contact_sheets/      per-batch previews
  work/shard-N/        per-worker staging (raw/, queue.jsonl, NEXT.md)
  build_specs.py       (re)build the queue if the DB has no batches yet
  append_styles.py     append new style packs to a live queue (does not touch existing rows)
  worker.py            claim + ingest entry point
  ingest.py            ingest only
  query.py             CLI search
  serve.py             read-only HTTP on 127.0.0.1:8790
  db.py / process.py   catalog + post-process
```

## Style packs

| id | look | typical sizes |
|---|---|---|
| `pixel_16bit` | SNES-era 16-color pixel, 1px outline | tiles 16, icons 32, characters 32×48 |
| `pixel_32` | richer 32-color pixel | tiles 32, icons 64, characters 64×96 |
| `hand_painted_fantasy` | painterly high fantasy | icons 256, characters 512×768 |
| `flat_vector_ui` | clean geometric UI | 256 square |
| `lowpoly_render` | faceted studio render | icons 256, characters 512×768 |
| `dark_scifi` | gunmetal + restrained neon | icons 256, characters 512×768 |
| `cozy_cartoon` | warm rounded cottagecore | icons 256, characters 512×768 |
| `ink_watercolor` | sumi-e ink wash + mineral watercolor blooms | icons 256, characters 512×768 |
| `paper_cutout` | layered construction-paper craft | icons 256, characters 512×768 |
| `claymation` | soft matte plasticine, stop-motion clay | icons 256, characters 512×768 |
| `cel_shaded_anime` | generic cel shading, hard color holds, no IP | icons 256, characters 512×768 |
| `retro_8bit` | generic 4-color 8-bit pixel (not a console library) | tiles 16, icons 32, characters 32×48 |
| `vaporwave_synth` | chrome + sunset peach + electric cyan, pink is not #FF00FF | icons 256, characters 512×768 |
| `gothic_woodcut` | medieval engraving, dense hatch on cream | icons 256, characters 512×768 |
| `isometric_voxel` | chunky cubic voxels, 30° isometric | icons 256, characters 512×768 |

Each pack locks a `style_prefix`, palette, light direction, and chroma key (`#FF00FF`).

## Categories

icons (weapons, armor, potions, food, tools, valuables, misc) · tiles (floor/wall, tileable) · props · characters (2×2 turnarounds) · enemies · ui · vfx (4-frame sheets) · backgrounds (16:9 plates + parallax layers)

Sheets (4×4 icons/UI/props/enemies, 2×2 turnarounds and VFX) are generated as one image and sliced. Tiles and backgrounds are singles.

## Query

```bash
python3 /workspace/game-assets/query.py "health potion" --category icons --style pixel_32 --alpha
python3 /workspace/game-assets/query.py --tileable --category tiles --style pixel_16bit
python3 /workspace/game-assets/query.py --stats
python3 /workspace/game-assets/serve.py --port 8790
# GET http://127.0.0.1:8790/search?q=sword&category=icons&style=pixel_32&alpha=true
```

## Database (short)

- `assets` — one row per file: path, thumb, category, subcategory, subject, style_pack, tags JSON, description, prompt, negative, style_prefix, width, height, has_alpha, palette, dominant_colors, tileable, pivot, frame_info, license, generator, created_at, sha256, phash, status, qa_notes, batch_id, spec_id, shard_id.
- `assets_fts` — FTS5 over description, tags, subject, category, subcategory, style_pack, slug.
- `specs` / `batches` / `claims` — generation queue with work leases.
- `embeddings` — reserved. **Do not run CLIP on this box.** A later Orbit bee can fill it.

Post-process is Pillow/numpy only, nice'd and sequential per worker: magenta (or uniform-corner) key, trim, canvas fit, nearest-neighbor + palette snap for pixel packs, thumbs, palette extract, dHash dedupe, QA flags (empty, checkerboard, leftover magenta).

Pending batches are ordered by `queue_pos`, a variety round-robin across category × style pack × genre (subcategory). Each shard (`queue_pos % 4`) therefore sees a mix from the start. Counts of each type are unchanged.

## Resume

Source of truth is `assets.db`, not `PROGRESS.json` (that file is a snapshot rewritten after claims/ingests).

- Already ingested batches have `status=ingested` and will not be claimed again.
- Stale claims (`lease_until` in the past) return to `pending` on the next worker start.
- Re-running `build_specs.py` is a no-op if batches already exist, so it will not wipe progress.
- To continue after a crash: run the same shard one-liner. Put any leftover generated PNGs in `work/shard-N/raw/{batch_id}.png` first.

## Parallel workers

Up to four workers is the intended load. Image generation is remote. Keep slicing/ingest under `nice -n 15` and do not run extra heavy jobs on the box. WAL mode + `BEGIN IMMEDIATE` + short transactions + per-shard staging dirs keep writers from colliding.
