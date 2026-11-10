# Catalog submission draft — assetrizz v0.1.0

**Status: ready to open, waiting for Kyle's yes.** The plugin v0.1.0 tag and
GitHub release exist. The catalog branch is on the fork. The catalog PR on
`NousResearch/hermes-agent` has **not** been opened.

- Plugin repo: https://github.com/mojomast/assetrizz
- Merge commit / **catalog pin:** `05339c228f55ac95ad21b5c947db0c6e36207cd4`
- Tag / release: https://github.com/mojomast/assetrizz/releases/tag/v0.1.0
- Fork branch: https://github.com/mojomast/hermes-agent/tree/catalog/assetrizz-v0.1.0
  (commit `04937c4ce1d52d8994e3e07597a49d5885b24600`, YAML-only, off upstream
  `main` at `ec3249919accf7bc51f780dcff663e8f19a0e176`)
- Compare (open this after Kyle's yes; do not open the PR yet):
  https://github.com/NousResearch/hermes-agent/compare/main...mojomast:hermes-agent:catalog/assetrizz-v0.1.0?expand=1
- This file and `catalog/assetrizz.yaml` were added *after* the tag so they
  could carry the real sha. The pin still points at the tagged commit, not at
  this docs follow-up.
- Open mojomast catalog PRs on `NousResearch/hermes-agent`: **4 of 5**
  (#152699 Hermes Plugin Dev, #151946 stitchslop, #150358 Hermagotchi,
  #149691 Eye Of Hermes). Opening this listing now would be the fifth open
  PR. Wait until one lands or closes, and until Kyle says yes.

## Already done

- Merged [mojomast/assetrizz#1](https://github.com/mojomast/assetrizz/pull/1)
  (merge commit `05339c228f55ac95ad21b5c947db0c6e36207cd4`) at 11:04 AM
  America/Toronto on 10 Nov 2026.
- Tagged `v0.1.0` on that commit and published the GitHub release.
- Banner at the pin returns HTTP 200:
  https://raw.githubusercontent.com/mojomast/assetrizz/05339c228f55ac95ad21b5c947db0c6e36207cd4/docs/banner.jpg
  (1280×720). A sample on-demand asset at the tag also returns HTTP 200:
  `https://raw.githubusercontent.com/mojomast/assetrizz/v0.1.0/assets/pixel_32/tiles/floor/grass_base.png`.
- Tools: `assetrizz_search`, `assetrizz_scene`. Hooks: none. Env: none.
  Bulk library download is **not** a tool; it is a pane button and
  `python -m assetrizz_plugin.cli` only.
- Schema cost: **2 tools, 931 tokens** (tiktoken `o200k_base`; 918 on
  `cl100k_base`).
- `hpd_check` was green. `hermes plugins doctor plugin --ci` and
  `hermes plugins validate plugin --install-deps` were green on the release
  tree. Security scan: **safe**. Requires Hermes `>=0.23.0`. Local CLI used
  for those checks: Hermes Agent v0.23.0 (`2bd378ed1b8d`). Validate warned
  that `tools.url_safety.create_ssrf_safe_client` and
  `agent.file_safety.get_write_denied_error` are documented seams but not
  formal plugin APIs; the SSRF guard is required for on-demand fetches, and
  a stdlib fallback exists. Pytest: **41 passed**, all fetches mocked.
- Installed plugin size (the `plugin/` tree, including the 4.7 MB catalog
  snapshot): **5.13 MB**. A full local library download is about **1.65 GB**.
- `scripts/validate_plugin_catalog.py plugin-catalog/assetrizz.yaml` on the
  fork branch: **OK: 1 file(s) valid**.
- Scratch-home install (`HERMES_HOME` throwaway, not the live profile):
  `hermes plugins install mojomast/assetrizz/plugin --ref 05339c228f55ac95ad21b5c947db0c6e36207cd4 --enable --yes-deps`
  finished in **13.3 s**, landed at `$HERMES_HOME/plugins/assetrizz` with no
  `assets/` tree and no PNGs, `pinned=True`,
  `revision=05339c228f55ac95ad21b5c947db0c6e36207cd4`, work tree **5.13 MB**,
  bundled `db/assets.db.xz` SHA-256 matched the pin, the plugin was enabled,
  and `hermes plugins doctor assetrizz --ci` reported **2 tool(s), 0 hook(s)**
  at version 0.1.0. The scratch home was then deleted.
- No extra screenshots (under the 6-shot cap). The example scene is
  `docs/example-scene.png`.

## Still needs Kyle's yes

Open a YAML-only PR from the fork branch to `NousResearch/hermes-agent`,
adding only `plugin-catalog/assetrizz.yaml`. Use the title and body
below. Do not open it while 4 of 5 catalog PRs are already open, and do
not comment on other catalog threads unless asked.

## Catalog entry (already on the fork branch)

The file at
https://github.com/mojomast/hermes-agent/blob/catalog/assetrizz-v0.1.0/plugin-catalog/assetrizz.yaml
is:

```yaml
name: assetrizz
title: Assetrizz
repo: https://github.com/mojomast/assetrizz
sha: "05339c228f55ac95ad21b5c947db0c6e36207cd4"
subdir: plugin
description: >-
  Skill id assetrizz:assetrizz-composer. Search the assetrizz 2D game-asset
  catalog (FTS over slugs, tags, descriptions, styles, and categories) and
  compose scenes from those assets. Tools: assetrizz_search and assetrizz_scene.
  Installs the plugin/ subdirectory only (a root install is refused so the
  1.65 GB PNG tree is never copied into the plugins folder). A compressed
  catalog (about 4.7 MB, SHA-256 pinned) is bundled so search works after
  install. Asset mode is one of on_demand (default: fetch a single PNG from
  GitHub raw when you place, render, or preview it), local (you download the
  full library or chosen style packs once into a directory you pick), or
  offline (local files only, no network). Bulk library downloads are
  user-initiated only — use the Download library button in the Desktop pane
  (size estimate, progress, cancel) or python -m assetrizz_plugin.cli; they
  are not a model tool. Fetches go only to
  raw.githubusercontent.com/mojomast/assetrizz/v0.1.0/assets/…, use the
  Hermes SSRF guard, cap size, and verify SHA-256 from the catalog. Optional
  library_path still prefers a complete checkout when you have one. Rendered
  scenes write PNG and JSON under the plugin data directory and, if you set
  it, the Export directory (must not be a filesystem root; never chosen by a
  tool argument). No credentials, no subprocesses. Hermes Desktop 0.23 or
  newer can show a dark compose pane that live-previews the current scene
  through ctx.rest and lets you install or remove a local library (deletion
  needs confirmation). The two tools still run when that pane is unavailable.
maintainer: mojomast
tier: community
category: tools
requires_hermes: ">=0.23.0"
docs_url: https://github.com/mojomast/assetrizz/tree/v0.1.0/plugin#readme
version: "0.1.0"
image: https://raw.githubusercontent.com/mojomast/assetrizz/05339c228f55ac95ad21b5c947db0c6e36207cd4/docs/banner.jpg
readme: true
platforms: []
known_issues:
  - >-
    Catalog CI does a full git clone of this repo (about 1.65 GB of PNGs)
    with a 600s timeout. A user install of subdir plugin/ is a blobless
    sparse checkout of plugin/ only, so everyday installs stay small.
  - >-
    The Desktop compose pane has not yet been proven on a live Hermes
    Desktop host; the two tools and the mocked pane API tests still run
    without it.
capabilities:
  provides_tools:
    - assetrizz_search
    - assetrizz_scene
  provides_hooks: []
  provides_middleware: []
  requires_env: []
```

## Draft PR title

`plugin-catalog: add assetrizz v0.1.0`

## Draft PR body

```markdown
## plugin-catalog: add assetrizz v0.1.0

Adds `plugin-catalog/assetrizz.yaml` (YAML-only diff).

- **Repo:** https://github.com/mojomast/assetrizz
- **Pinned SHA:** `05339c228f55ac95ad21b5c947db0c6e36207cd4` (tag `v0.1.0`, release: https://github.com/mojomast/assetrizz/releases/tag/v0.1.0)
- **Subdir:** `plugin`
- **Maintainer:** @mojomast (owner of the plugin repo)

### What it does

Two tools plus a dark Desktop compose pane for a 14,641-PNG 2D game-asset
library. Search uses a bundled, SHA-256-pinned catalog (~4.7 MB) so a catalog
install does not need the 1.65 GB checkout. Default `on_demand` mode fetches
a single PNG from GitHub raw at this tag when it is placed, rendered, or
previewed (Hermes SSRF guard, size cap, SHA-256 verified into the plugin
cache). `local` lets the user download the full library or chosen style packs
once; `offline` never touches the network. Bulk downloads are user-initiated
only (pane button or `python -m assetrizz_plugin.cli`), not a model tool.

### Checks run before this PR

- `hpd_check` green; `hermes plugins doctor --ci` and
  `hermes plugins validate --install-deps` green (security scan: safe).
- Pytest 41 passed with mocked fetches (no live network in CI).
- Schema cost: 931 tokens (`o200k_base`), 2 tools, 0 hooks, no env.
- Scratch-home install of `mojomast/assetrizz/plugin` at this SHA: 13.3 s,
  5.13 MB work tree, no PNG library copied, doctor reported 2 tools / 0 hooks.
- `scripts/validate_plugin_catalog.py` on this file: OK.

### Known issue for reviewers

Catalog CI does a full git clone of this repo (~1.65 GB) with a 600 s
timeout. A user install of `subdir: plugin` is a blobless sparse checkout of
`plugin/` only. The Desktop pane has not yet been proven on a live Hermes
Desktop host.
```

## Lesson fixes included in v0.1.0

- Bundled catalog so search works after a subdir install; no 1.65 GB clone required for the tools.
- On-demand fetches allowlisted to the pinned tag, SSRF-guarded, size-capped, SHA-256 verified; tests mock HTTP.
- Three documented asset modes; bulk download is pane/CLI with progress, cancel, disk usage, and confirmed delete (will not delete the source checkout).
- Untrusted catalog text is sanitized and shown via `textContent`, not `innerHTML`.
- `provides_middleware` is not in the plugin manifest.
- Plugin source does not hardcode the Hermes profile path; writes go through `plugin_data_dir` / `get_hermes_home()` and honour `file_safety`.
- Root stub still refuses a root install of the 1.65 GB tree.
