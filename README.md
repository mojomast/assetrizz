<p align="center">
  <img src="docs/banner.jpg" alt="assetrizz — an original 2D game asset library" width="100%">
</p>

# assetrizz

A searchable library of **14,641 original 2D game assets** in **23 consistent style packs** and **18 categories**, plus the pipeline that built it.

[![assets](https://img.shields.io/badge/assets-14%2C641-brightgreen)](#style-gallery)
[![styles](https://img.shields.io/badge/styles-23-blue)](#style-gallery)
[![categories](https://img.shields.io/badge/categories-18-blueviolet)](#whats-inside)
[![license](https://img.shields.io/badge/license-original-informational)](#license-and-originality)

Every image is original, generated for Kyle Durepos, and tagged for search. No real people, no logos, and no trademarked or copyrighted characters.

- [Why it's awesome](#why-its-awesome)
- [What's inside](#whats-inside)
- [Style gallery](#style-gallery)
- [Quick start: use the assets](#quick-start-use-the-assets)
- [Hermes plugin: search and compose](#hermes-plugin-search-and-compose)
- [Generate your own: the pipeline](#generate-your-own-the-pipeline)
- [Adding styles and categories](#adding-styles-and-categories)
- [Asset metadata](#asset-metadata)
- [Roadmap](#roadmap)
- [License and originality](#license-and-originality)

## Why it's awesome

- **Original and tagged.** All 14,641 accepted assets are generated works, each with a slug, description, tags, palette, and SHA-256. Nothing here is scraped from an existing game.
- **A locked style-pack system.** Twenty-three packs share the same categories and naming, so a health potion or a floor tile exists in many looks without mixing visual languages. Each pack pins a style prefix, palette, light direction, and chroma key.
- **Production-ready sprites.** Assets are transparent PNGs. Tiles carry a `tileable` flag; sprites carry a pivot. Pixel packs are snapped to their palette and grid.
- **A real catalog, not just a folder dump.** The SQLite database includes an FTS5 index over slugs, descriptions, tags, subjects and categories. `assets/manifest.jsonl` is a portable, one-object-per-line copy of the same accepted-asset metadata.
- **A queue that scales.** The generator is a sharded, lease-based queue. Workers claim batches with `BEGIN IMMEDIATE` so many can run in parallel without overlapping work.

## What's inside

```
assetrizz/
├── README.md
├── docs/banner.jpg
├── docs/example-scene.png      # composed sample (see the Hermes plugin)
├── assets/
│   ├── manifest.jsonl          # one JSON object per accepted asset
│   ├── stats.json              # counts by style and category
│   ├── contact_sheets/         # milestone-1000, 2000, 3000, 14000
│   └── <style>/<category>/<subcategory>/<name>.png
├── db/
│   ├── assets.db.xz            # compressed catalog (4.7 MB)
│   └── restore.sh              # writes db/assets.db (gitignored)
├── plugin/                     # installable Hermes plugin (not the 14,641 PNGs)
└── pipeline/                   # style packs, queue, ingest, search, gallery
    ├── style_packs.json
    ├── PIPELINE.md
    ├── db.py
    ├── worker.py
    ├── ingest.py
    ├── process.py
    ├── query.py
    ├── serve.py
    ├── gallery.py
    ├── append_styles.py
    ├── append_styles_wave3.py
    ├── append_categories.py
    └── ...
```

**14,641 accepted PNGs** across the 18 categories below. Paths in the database and manifest are repo-relative (`assets/...`). Thumbnail paths (`thumbs/...`) refer to the original pipeline tree and are not shipped in this repository.

| Category | What's in it | Count |
|---|---|---:|
| `icons` | Weapons, armor, potions, food, tools, valuables, misc | 3,548 |
| `tiles` | Floor and wall tiles, often tileable | 1,004 |
| `props` | World objects | 550 |
| `characters` | Characters, including 2×2 turnarounds | 1,097 |
| `enemies` | Hostile creatures | 931 |
| `ui` | Interface widgets and frames | 673 |
| `vfx` | Effects, including 4-frame sheets | 1,022 |
| `backgrounds` | 16:9 plates and parallax layers | 525 |
| `vehicles` | Mounts and craft | 241 |
| `buildings` | Exteriors | 131 |
| `furniture` | Interior furnishings | 669 |
| `foliage` | Plants and trees | 672 |
| `creatures` | Non-hostile animals | 636 |
| `portraits` | Original busts; no real people | 444 |
| `weapons` | Full-size sprites, not icons | 247 |
| `decals` | Blood-free stains and prints | 979 |
| `markers` | Map and world-map pins | 1,142 |
| `terrain` | Rocks, cliffs, bridges | 130 |
| **Total** |  | **14,641** |

Milestone contact sheets live in [`assets/contact_sheets/`](assets/contact_sheets/).

## Style gallery

Counts are from [`assets/stats.json`](assets/stats.json). The sample images are real files in `assets/`.

| id | Name | Look | Count | Samples |
|---|---|---|---:|---|
| `pixel_16bit` | 16-bit pixel | SNES-era 16-color pixel art, hard 1px outlines | 882 | <img src="assets/pixel_16bit/icons/potion/health_potion_plain.png" alt="health potion plain" width="72">&nbsp;<img src="assets/pixel_16bit/tiles/floor/stone_floor_base.png" alt="stone floor base" width="72">&nbsp;<img src="assets/pixel_16bit/props/object/gravestone_plain.png" alt="gravestone plain" width="72"> |
| `pixel_32` | 32px pixel | Richer 32-color pixel art | 872 | <img src="assets/pixel_32/icons/weapon/iron_sword_plain.png" alt="iron sword plain" width="72">&nbsp;<img src="assets/pixel_32/tiles/floor/stone_floor_base.png" alt="stone floor base" width="72">&nbsp;<img src="assets/pixel_32/props/object/boulder_plain.png" alt="boulder plain" width="72"> |
| `hand_painted_fantasy` | Hand-painted fantasy | Painterly high fantasy | 849 | <img src="assets/hand_painted_fantasy/icons/weapon/iron_sword_plain.png" alt="iron sword plain" width="72">&nbsp;<img src="assets/hand_painted_fantasy/tiles/floor/stone_floor_base.png" alt="stone floor base" width="72">&nbsp;<img src="assets/hand_painted_fantasy/props/object/crystal_formation_plain.png" alt="crystal formation plain" width="72"> |
| `flat_vector_ui` | Flat vector UI | Clean geometric UI | 937 | <img src="assets/flat_vector_ui/icons/weapon/iron_sword_plain.png" alt="iron sword plain" width="72">&nbsp;<img src="assets/flat_vector_ui/tiles/floor/stone_floor_base.png" alt="stone floor base" width="72">&nbsp;<img src="assets/flat_vector_ui/props/object/crystal_formation_plain.png" alt="crystal formation plain" width="72"> |
| `lowpoly_render` | Low-poly render look | Faceted studio-style low-poly render | 868 | <img src="assets/lowpoly_render/icons/weapon/iron_sword_plain.png" alt="iron sword plain" width="72">&nbsp;<img src="assets/lowpoly_render/tiles/floor/stone_floor_base.png" alt="stone floor base" width="72">&nbsp;<img src="assets/lowpoly_render/props/object/crystal_formation_plain.png" alt="crystal formation plain" width="72"> |
| `dark_scifi` | Dark sci-fi | Gunmetal with restrained neon | 883 | <img src="assets/dark_scifi/icons/weapon/iron_sword_plain.png" alt="iron sword plain" width="72">&nbsp;<img src="assets/dark_scifi/tiles/floor/stone_floor_base.png" alt="stone floor base" width="72">&nbsp;<img src="assets/dark_scifi/props/object/clay_vase_plain.png" alt="clay vase plain" width="72"> |
| `cozy_cartoon` | Cozy cartoon | Warm, rounded cottagecore cartoon | 854 | <img src="assets/cozy_cartoon/icons/weapon/iron_sword_plain.png" alt="iron sword plain" width="72">&nbsp;<img src="assets/cozy_cartoon/tiles/floor/stone_floor_base.png" alt="stone floor base" width="72">&nbsp;<img src="assets/cozy_cartoon/props/object/cauldron_plain.png" alt="cauldron plain" width="72"> |
| `ink_watercolor` | Ink watercolor | Sumi-e ink wash with mineral watercolor blooms | 613 | <img src="assets/ink_watercolor/icons/weapon/glass_rapier_plain.png" alt="glass rapier plain" width="72">&nbsp;<img src="assets/ink_watercolor/props/object/wind_chime_stand_plain.png" alt="wind chime stand plain" width="72">&nbsp;<img src="assets/ink_watercolor/furniture/small/coat_rack_plain.png" alt="coat rack plain" width="72"> |
| `paper_cutout` | Paper cutout | Layered construction-paper craft | 500 | <img src="assets/paper_cutout/icons/weapon/glass_rapier_plain.png" alt="glass rapier plain" width="72">&nbsp;<img src="assets/paper_cutout/props/object/wind_chime_stand_plain.png" alt="wind chime stand plain" width="72">&nbsp;<img src="assets/paper_cutout/characters/humanoid/ink_scribe_side.png" alt="ink scribe side" width="72"> |
| `claymation` | Claymation | Soft matte plasticine, stop-motion clay | 647 | <img src="assets/claymation/icons/weapon/thorn_whip_plain.png" alt="thorn whip plain" width="72">&nbsp;<img src="assets/claymation/props/object/wind_chime_stand_plain.png" alt="wind chime stand plain" width="72">&nbsp;<img src="assets/claymation/furniture/small/oil_lamp_stand_plain.png" alt="oil lamp stand plain" width="72"> |
| `cel_shaded_anime` | Cel-shaded anime | Generic cel shading, hard color holds, no existing IP | 677 | <img src="assets/cel_shaded_anime/icons/tool/tuning_fork_plain.png" alt="tuning fork plain" width="72">&nbsp;<img src="assets/cel_shaded_anime/props/object/wind_chime_stand_plain.png" alt="wind chime stand plain" width="72">&nbsp;<img src="assets/cel_shaded_anime/characters/humanoid/ferry_pilot_side.png" alt="ferry pilot side" width="72"> |
| `retro_8bit` | Retro 8-bit | Generic 4-color 8-bit pixel (not a console library) | 518 | <img src="assets/retro_8bit/icons/armor/quilted_gambeson_plain.png" alt="quilted gambeson plain" width="72">&nbsp;<img src="assets/retro_8bit/characters/humanoid/stargazer_three_quarter.png" alt="stargazer three quarter" width="72">&nbsp;<img src="assets/retro_8bit/creatures/animal/tortoise_idle_front.png" alt="tortoise idle front" width="72"> |
| `vaporwave_synth` | Vaporwave synth | Chrome, sunset peach and electric cyan — subject pink is never #FF00FF | 636 | <img src="assets/vaporwave_synth/icons/weapon/glass_rapier_plain.png" alt="glass rapier plain" width="72">&nbsp;<img src="assets/vaporwave_synth/props/object/birdcage_plain.png" alt="birdcage plain" width="72">&nbsp;<img src="assets/vaporwave_synth/characters/humanoid/glassblower_side.png" alt="glassblower side" width="72"> |
| `gothic_woodcut` | Gothic woodcut | Medieval engraving, dense hatch on cream | 608 | <img src="assets/gothic_woodcut/icons/weapon/glass_rapier_plain.png" alt="glass rapier plain" width="72">&nbsp;<img src="assets/gothic_woodcut/props/object/wind_chime_stand_plain.png" alt="wind chime stand plain" width="72">&nbsp;<img src="assets/gothic_woodcut/furniture/small/coat_rack_plain.png" alt="coat rack plain" width="72"> |
| `isometric_voxel` | Isometric voxel | Chunky cubic voxels, 30° isometric | 568 | <img src="assets/isometric_voxel/icons/weapon/glass_rapier_plain.png" alt="glass rapier plain" width="72">&nbsp;<img src="assets/isometric_voxel/props/object/wind_chime_stand_plain.png" alt="wind chime stand plain" width="72">&nbsp;<img src="assets/isometric_voxel/characters/humanoid/ferry_pilot_side.png" alt="ferry pilot side" width="72"> |
| `stained_glass` | Stained glass | Jewel-tone glass with heavy black lead came | 591 | <img src="assets/stained_glass/icons/weapon/glass_rapier_plain.png" alt="glass rapier plain" width="72">&nbsp;<img src="assets/stained_glass/props/object/wind_chime_stand_plain.png" alt="wind chime stand plain" width="72">&nbsp;<img src="assets/stained_glass/furniture/small/coat_rack_plain.png" alt="coat rack plain" width="72"> |
| `chalk_crayon` | Chalk crayon | Dusty chalk and wax crayon, handmade edges | 548 | <img src="assets/chalk_crayon/icons/weapon/glass_rapier_plain.png" alt="glass rapier plain" width="72">&nbsp;<img src="assets/chalk_crayon/props/object/music_stand_plain.png" alt="music stand plain" width="72">&nbsp;<img src="assets/chalk_crayon/furniture/small/coat_rack_plain.png" alt="coat rack plain" width="72"> |
| `art_deco_poster` | Art deco poster | 1920s geometric gold, black, cream and teal, no type | 411 | <img src="assets/art_deco_poster/icons/tool/tuning_fork_plain.png" alt="tuning fork plain" width="72">&nbsp;<img src="assets/art_deco_poster/props/object/wind_chime_stand_plain.png" alt="wind chime stand plain" width="72">&nbsp;<img src="assets/art_deco_poster/furniture/small/coat_pegs_plain.png" alt="coat pegs plain" width="72"> |
| `ukiyo_e_inspired` | Ukiyo-e inspired | Original woodblock look, not a copy of any real print | 420 | <img src="assets/ukiyo_e_inspired/icons/weapon/glass_rapier_plain.png" alt="glass rapier plain" width="72">&nbsp;<img src="assets/ukiyo_e_inspired/props/object/wind_chime_stand_plain.png" alt="wind chime stand plain" width="72">&nbsp;<img src="assets/ukiyo_e_inspired/furniture/small/coat_rack_plain.png" alt="coat rack plain" width="72"> |
| `blueprint_line` | Blueprint line | White and cyan technical line art, no typography | 411 | <img src="assets/blueprint_line/icons/armor/kite_shield_plain.png" alt="kite shield plain" width="72">&nbsp;<img src="assets/blueprint_line/props/object/millstone_plain.png" alt="millstone plain" width="72">&nbsp;<img src="assets/blueprint_line/portraits/civilian/ferry_captain_bust.png" alt="ferry captain bust" width="72"> |
| `cyberpunk_neon` | Cyberpunk neon | Dark metal with cyan, lime and amber neon, no brands | 372 | <img src="assets/cyberpunk_neon/icons/weapon/glass_rapier_plain.png" alt="glass rapier plain" width="72">&nbsp;<img src="assets/cyberpunk_neon/props/object/birdcage_plain.png" alt="birdcage plain" width="72">&nbsp;<img src="assets/cyberpunk_neon/furniture/small/coat_rack_plain.png" alt="coat rack plain" width="72"> |
| `storybook_gouache` | Storybook gouache | Opaque gouache picture-book painting | 489 | <img src="assets/storybook_gouache/icons/tool/tuning_fork_plain.png" alt="tuning fork plain" width="72">&nbsp;<img src="assets/storybook_gouache/props/object/wind_chime_stand_plain.png" alt="wind chime stand plain" width="72">&nbsp;<img src="assets/storybook_gouache/furniture/small/coat_rack_plain.png" alt="coat rack plain" width="72"> |
| `monochrome_1bit` | Monochrome 1-bit | Strict two-color 1-bit pixel art | 487 | <img src="assets/monochrome_1bit/icons/weapon/hooked_kris_plain.png" alt="hooked kris plain" width="72">&nbsp;<img src="assets/monochrome_1bit/buildings/work/timber_granary_exterior.png" alt="timber granary exterior" width="72">&nbsp;<img src="assets/monochrome_1bit/props/object/water_trough_plain.png" alt="water trough plain" width="72"> |
|  |  |  | **14,641** |  |

## Quick start: use the assets

Browse the folders, or search the catalog.

**Browse.** Assets are at `assets/<style_pack>/<category>/<subcategory>/<name>.png`. For example, `assets/pixel_32/icons/weapon/iron_sword_plain.png`.

**Restore the database** (once, from the repo root):

```bash
bash db/restore.sh
```

That decompresses `db/assets.db.xz` to `db/assets.db` and leaves the `.xz` in place. The uncompressed file is gitignored. If `db/assets.db` already exists, the script stops without overwriting it.

**Search with SQL and FTS5:**

```python
import sqlite3

con = sqlite3.connect("db/assets.db")
con.row_factory = sqlite3.Row

rows = con.execute(
    """
    SELECT a.slug, a.path, a.style_pack, a.category, a.description
      FROM assets a
      JOIN assets_fts f ON f.rowid = a.id
     WHERE assets_fts MATCH 'health potion'
       AND a.status = 'ok'
     LIMIT 10
    """
).fetchall()

for row in rows:
    print(f"{row['style_pack']:24} {row['path']}")
```

Tileable floors and walls:

```python
tiles = con.execute(
    """
    SELECT path, style_pack, width, height
      FROM assets
     WHERE status = 'ok' AND tileable = 1 AND category = 'tiles'
     ORDER BY style_pack, path
    """
).fetchall()
```

**Or use the manifest** with `jq` — no database restore required:

```bash
# how many pixel_32 icons?
jq -s 'map(select(.style_pack=="pixel_32" and .category=="icons")) | length' \
  assets/manifest.jsonl

# list every tileable asset path
jq -r 'select(.tileable==1) | .path' assets/manifest.jsonl

# one style pack's subjects
jq -r 'select(.style_pack=="stained_glass") | [.category,.subject,.path] | @tsv' \
  assets/manifest.jsonl
```

The `pipeline/query.py` and `pipeline/serve.py` CLIs talk to a database file next to the scripts (`pipeline/assets.db`) and were written for the live working tree. For this repo, prefer the restored `db/assets.db` or the manifest, as in the examples above. `query.py --category` currently accepts the original eight categories: `icons`, `tiles`, `props`, `characters`, `enemies`, `ui`, `vfx`, `backgrounds`. The other ten categories are fully present in the catalog and can be filtered with SQL (`category = 'portraits'`) or `jq`.


## Hermes plugin: search and compose

The [`plugin/`](plugin/) directory is a native Hermes plugin. The agent searches the library and composes scenes; you can watch the current scene in a dark Desktop pane.

Install **only** that directory — a root install is refused so Hermes does not copy the 1.65 GB asset tree into the plugins folder:

```bash
git clone https://github.com/mojomast/assetrizz
hermes plugins install mojomast/assetrizz/plugin
```

Point **Settings → Plugins → assetrizz → Library path** (or `ASSETRIZZ_LIBRARY`) at the checkout if it is not auto-detected. The folder must contain `assets/` and `db/assets.db.xz`. The first search decompresses the catalog automatically; you can also run `bash db/restore.sh`.

Tools:

- `assetrizz_search` — `op=search`, `op=get`, `op=stats` (FTS over slugs, tags, descriptions, styles, categories)
- `assetrizz_scene` — `op=create`, `place`, `tile`, `move`, `scale`, `flip`, `layer`, `remove`, `list`, `clear`, `render`, `save`, `load`

Skill id for `skill_view`: `assetrizz:assetrizz-composer`. Hermes `>=0.23.0` is required for the pane (`ctx.rest`). The two tools still run when the pane is unavailable. Render writes a PNG under the plugin data / export directory; the tool result is a path, not an embedded image. Assets can only be read from the library root.

An example scene composed from real `pixel_32` tiles, trees, a roadside inn, a ranger, and a hare:

<p align="center">
  <img src="docs/example-scene.png" alt="Example assetrizz scene: a pixel_32 meadow path with an inn, trees, a ranger and a hare" width="640">
</p>

Full install notes, disclosure, and developer commands are in [`plugin/README.md`](plugin/README.md). Scene JSON for the example is at [`docs/example-scene.json`](docs/example-scene.json).

## Generate your own: the pipeline

The generator lives in `pipeline/`. A longer walkthrough is in [`pipeline/PIPELINE.md`](pipeline/PIPELINE.md). In the live working tree the database sat beside the scripts and accepted files were written under `library/`; this repository ships the accepted library under `assets/` and the catalog under `db/`.

**Style packs** in `pipeline/style_packs.json` lock a `style_prefix`, palette, light direction, typical sizes, and a chroma key of `#FF00FF`. Sheets (4×4 for small items, 2×2 for larger ones, plus turnarounds and VFX) are generated as one image and sliced on ingest. Tiles, backgrounds, buildings, trees and other large subjects stay singles.

**Workers** claim and ingest work for one shard:

```bash
nice -n 15 python3 pipeline/worker.py --shard N --shards 4
```

Real flags, from `worker.py`:

| Flag | Default | Role |
|---|---|---|
| `--shard` | required | 0-based shard index |
| `--shards` | `4` | Total shard count; every worker must use the same value |
| `--claim` | `4` | How many pending batches to claim |
| `--worker-id` | `shard-{N}` | Worker label stored on the claim; defaults to `shard-` plus `--shard` |
| `--lease-min` | `30` | Claim lease in minutes |
| `--no-ingest` | off | Claim only; do not ingest |
| `--no-claim` | off | Ingest only; do not claim |

A worker first ingests any finished images in its staging dir (`work/shard-N/raw/{batch_id}.png` by default), then claims pending batches where `COALESCE(queue_pos, batch_index) % shards == shard`. Claims run in a `BEGIN IMMEDIATE` transaction, so overlapping shard splits stay safe. Stale leases are returned to `pending` on the next worker start. Do not change `--shards` mid-run.

Generation is done on a flat magenta `#FF00FF` background, with no ground plane. After a sheet or single lands in `raw/`, rerun the same worker command to ingest it. `ingest.py` can also be run on its own: `--shard`, `--shards`, `--staging`, `--worker-id`.

**Post-process** (`process.py`) is Pillow/numpy only. It chroma-keys magenta (or a uniform corner), trims, fits the canvas, nearest-neighbour scales and palette-snaps pixel packs, writes thumbs, extracts a palette, dHash-dedupes, and flags QA problems such as empty images, checkerboards, or leftover magenta.

**Search and preview tools** (flags from the scripts):

```bash
# CLI search (JSON out). --category accepts the original eight categories listed above.
python3 pipeline/query.py "health potion" --category icons --style pixel_32 --alpha
python3 pipeline/query.py --tileable --category tiles --style pixel_16bit
python3 pipeline/query.py --stats

# Read-only HTTP search, default 127.0.0.1:8790
python3 pipeline/serve.py --host 127.0.0.1 --port 8790
# GET /search?q=sword&category=icons&style=pixel_32&alpha=true

# Read-only live gallery, default 127.0.0.1:8792
python3 pipeline/gallery.py --host 127.0.0.1 --port 8792
```

`gallery.py` in this snapshot is still pointed at the live working tree (`/workspace/game-assets`). Use it there, or browse `assets/` and the restored database directly.

## Adding styles and categories

New looks and new subject matter are appended to a live queue; existing rows are not rewritten.

1. Define the pack in `pipeline/style_packs.json` — title, description, style prefix, palette, sizes for each category, light, outline, and chroma key.
2. Add its id to the append script you intend to run. `append_styles.py` reads `NEW_STYLE_IDS` (the second wave of eight packs). `append_styles_wave3.py` appends the third wave. `append_categories.py` reads `NEW_CATEGORIES` (vehicles, buildings, furniture, foliage, creatures, portraits, weapons, decals, markers, terrain).
3. Dry-run, then write:

```bash
python3 pipeline/append_styles.py --dry-build
python3 pipeline/append_categories.py --dry-build
```

Both scripts (and the wave-3 style script) also accept `--skip-backup` if a SQLite backup has already been taken. Without that flag they back up the database before inserting. `build_specs.py` is a no-op if batches already exist, so it will not wipe a live queue.

## Asset metadata

Each accepted asset has a row in `assets` (status `ok`) and a matching line in `assets/manifest.jsonl`. Prompts are kept in the database but omitted from the manifest. Fields in the manifest:

| Field | Contents |
|---|---|
| `slug` | Stable id, e.g. `pixel_32/icons/weapon/iron_sword_plain` |
| `path` | Repo-relative PNG path, e.g. `assets/pixel_32/icons/weapon/iron_sword_plain.png` |
| `category` / `subcategory` / `subject` | Taxonomy |
| `style_pack` | One of the 23 pack ids |
| `tags` | JSON array of searchable tags |
| `description` | Short English description |
| `width` / `height` | Pixel size |
| `tileable` | `1` if the image is meant to tile, else `0` |
| `pivot` | JSON object like `{ "x": 0.5, "y": 0.5 }`, in 0–1 coordinates |
| `frame_info` | Sheet or single metadata (batch, grid, cell, source size) |
| `license` | `original, generated for Kyle Durepos` |
| `sha256` | Content hash of the PNG |
| `palette` | Extracted hex colours |

The database also stores prompt, negative, style prefix, thumbnail path, phash, QA notes, batch and spec ids, and queue tables (`specs`, `batches`, `claims`). FTS5 is indexed over `slug`, `description`, `tags`, `subject`, `category`, `subcategory`, and `style_pack`.

## Roadmap

- [x] **Hermes plugin** — `plugin/` with `assetrizz_search` and `assetrizz_scene`, a dark compose pane, and a catalog-ready layout *(on `feat/hermes-plugin`; not catalog-submitted yet)*
- [ ] Live verification on a Hermes Desktop host, then an authorized catalog pin
- [ ] Release-hosted asset packs *(planned)*

## License and originality

Every asset in this library is an original generated work made for Kyle Durepos. The license field on each database row and manifest line is:

```
original, generated for Kyle Durepos
```

Do not prompt for, imitate, or include real people, trademarks, logos, real flags, or copyrighted characters from existing games, films, or comics. Portraits in this library are invented faces. Style packs that evoke a period or medium (ukiyo-e, art deco, 8-bit, and so on) are original looks, not copies of a specific print, artist, or console library.

See `pipeline/LICENSE.txt` for the full note. Raw model output may have limited copyright protection in some jurisdictions; selection, prompting, post-processing, cataloguing, and arrangement are part of the project workflow.
