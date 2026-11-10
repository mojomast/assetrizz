# assetrizz

An agent-searchable library of **original** 2D game assets, plus the pipeline that builds it. It's headed toward a Hermes plugin.

Today the pipeline lives in `pipeline/`:
- 23 locked style packs (`style_packs.json`), including the earlier fifteen plus stained glass, chalk crayon, art deco poster, ukiyo-e inspired, blueprint line, cyberpunk neon, storybook gouache and monochrome 1-bit
- 18 categories, including vehicles, buildings, furniture, foliage, creatures, portraits, full-size weapons, decals, map markers and terrain, plus the original icons, tiles, props, characters, enemies, UI, VFX and backgrounds
- `append_styles.py` and `append_categories.py` append new packs or categories to a live queue without touching existing rows
- A sharded, claim-safe generation queue in SQLite (`db.py`, `worker.py`)
- Chroma-key and post-processing (`process.py`)
- A FTS5 search index plus a CLI and an HTTP search tool (`query.py`, `serve.py`)
- A live gallery (`gallery.py`)

See `pipeline/PIPELINE.md` for how it works. The generated images and the database aren't in this repo.

## Roadmap

- [ ] Hermes plugin: `plugin.yaml` plus `register(ctx)` tools for searching, fetching and generating assets
- [ ] Dashboard pane for browsing the gallery
- [ ] Release-hosted asset packs

All assets are original. No real people, and no trademarked or copyrighted characters.
