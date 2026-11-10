# Assetrizz Hermes plugin

Search the [assetrizz](https://github.com/mojomast/assetrizz) 2D game-asset
catalog and compose scenes from those assets. The Hermes agent gets two compact
tools; you get a dark compose pane that live-previews what it placed and lets
you install a local copy of the library.

This directory is the installable plugin (`subdir: plugin` in the catalog,
or `hermes plugins install mojomast/assetrizz/plugin`). A compressed catalog
(`db/assets.db.xz`, about 4.7 MB, SHA-256 pinned) is bundled here so search
works after a catalog install. The 14,641 PNGs are **not** copied into the
Hermes plugins folder. A root install of `mojomast/assetrizz` is refused on
purpose so Hermes does not publish the 1.65 GB asset tree.

- Skill id: `assetrizz:assetrizz-composer` (pass that exact string to `skill_view`)
- Tools: `assetrizz_search`, `assetrizz_scene`
- Requires Hermes `>=0.23.0` (Desktop pane uses `ctx.rest`)
- Version: `0.1.0`
- License: MIT for the plugin code. The assets themselves stay
  “original, generated for Kyle Durepos” — see the [library license](../pipeline/LICENSE.txt).

## Asset modes

Set **Settings → Plugins → assetrizz → Asset mode** (`asset_mode` /
`ASSETRIZZ_ASSET_MODE`):

| Mode | What happens |
|---|---|
| `on_demand` (default) | Search uses the bundled catalog. When you place, render, or preview an asset, the plugin downloads that one PNG from the pinned GitHub raw URL, verifies its SHA-256 against the catalog, and caches it under the plugin data directory. |
| `local` | Same catalog, but PNGs are read from a library directory you install once (the full 1.65 GB tree or chosen style packs). Missing files may still be fetched one at a time into that directory. |
| `offline` | No network. Search still works; placing or rendering fails unless the PNG is already in the local library or the on-demand cache. Optional `library_path` / `ASSETRIZZ_LIBRARY` still prefers a complete checkout when you have one. |

A bulk download of the library or a style pack is **user-initiated only**. Use
the **Download library** button in the Assetrizz pane (size estimate per pack,
progress, cancel) or run the CLI yourself. It is not a model tool, and the
agent cannot start a 1.65 GB download on its own.

```bash
python -m assetrizz_plugin.cli status
python -m assetrizz_plugin.cli download --style pixel_32
python -m assetrizz_plugin.cli download --all --yes
python -m assetrizz_plugin.cli cancel
python -m assetrizz_plugin.cli remove --yes
```

Downloads use the same pinned tag (`v0.1.0` for this plugin version), SHA-256
verification, at most four concurrent requests, and resume-on-retry (files
already on disk whose hash matches are skipped). The pane shows disk usage for
the local library and the on-demand cache. **Remove local library** (or
`cli remove --yes`) needs confirmation and will not delete the assetrizz
source checkout.

Set **Local library directory** (`local_library_dir` /
`ASSETRIZZ_LOCAL_LIBRARY`) if you want the download somewhere other than the
plugin data `library/` folder. It must not be a filesystem root.

## Install

1. Install **only** this `plugin/` directory:

   ```bash
   hermes plugins install mojomast/assetrizz/plugin
   ```

   Search works immediately from the bundled catalog. You do not need a 1.65 GB
   clone for that.

2. Choose an asset mode (default `on_demand` is fine). To keep a complete local
   copy, open the Assetrizz pane and click **Download library**, or run
   `python -m assetrizz_plugin.cli download --all --yes`.

3. Optional: if you already have a full checkout, set **Library path**
   (`ASSETRIZZ_LIBRARY`) to that folder (`assets/` plus `db/assets.db.xz`).
   Leave it empty to auto-detect a checkout next to this plugin, or set it to
   `none` to force the bundled catalog. The first search may decompress the
   catalog into the plugin data dir (or into a writable library `db/` folder).

4. Optional: set **Export directory** (`ASSETRIZZ_EXPORT_DIR`) for rendered
   PNGs. It must not be a filesystem root. The default is the plugin data
   `exports/` folder, which survives `hermes plugins update`.

The two tools work without the Desktop pane. On Hermes Desktop 0.23 or newer,
open the **Assetrizz** pane to watch the current scene, browse assets, inspect
layers, and download or remove a local library. The pane talks only through
`ctx.rest` — it never dials loopback or attaches authorization headers.

## Use it

Ask the agent to find tiles or characters and lay out a scene, for example:

> Search assetrizz for pixel_32 grass and dirt path tiles, then compose a
> 640×320 meadow with a path, a couple of trees, a ranger, and a hare.
> Render a PNG.

Typical tool flow:

1. `assetrizz_search` `op=stats` or `op=search` with `q`, `style`, `category`.
2. `assetrizz_scene` `op=create` with `width`, `height`, optional `background`.
3. `op=tile` to fill floors or walls; `op=place` for props, characters, foliage.
4. `op=move` / `scale` / `flip` / `layer` / `remove` as needed (`layer=L1`…).
5. `op=render` writes a PNG under the export directory and refreshes the pane.
   The tool result is a **path**, not an embedded image.
6. `op=save` / `op=load` persist scene JSON in the plugin data dir.

Every handler returns a JSON string: `{ok: true, ...}` or
`{ok: false, error, code, fix}`.

An example scene composed from real `pixel_32` assets is at
[`docs/example-scene.png`](../docs/example-scene.png)
([JSON](../docs/example-scene.json)).

## Disclosure

- **Network (on demand and user-initiated downloads only).** In `on_demand` or
  `local` mode the plugin may fetch individual PNGs from
  `https://raw.githubusercontent.com/mojomast/assetrizz/v0.1.0/assets/…`
  (the pin is the `asset_ref` setting; default `v0.1.0`). Requests use the
  Hermes SSRF guard (`create_ssrf_safe_client`, `follow_redirects=False`,
  `trust_env=False`), allowlist only that host and `assets/` prefix, cap the
  body at 5 MiB, time out, and refuse off-host redirects. Each file is checked
  against the SHA-256 stored in the catalog; a mismatch is not kept. There are
  no credentials and `requires_env` is empty.
- **Bulk downloads are not a tool.** Only the pane button or
  `python -m assetrizz_plugin.cli` can start a library or style-pack download.
  A running job can be cancelled; verified files stay on disk so you can
  resume. A background thread exists only while that user-started job runs.
- **Offline / local files.** `offline` mode never touches the network. An
  optional complete checkout (`library_path` / `ASSETRIZZ_LIBRARY`) is used
  first when present. Paths are confined after symlink resolution. Tool
  arguments cannot point the plugin at an arbitrary path or a filesystem root.
  An extra export directory must be set by you (Settings or
  `ASSETRIZZ_EXPORT_DIR`), never by a model argument, and must not be a
  filesystem root.
- **Writes.** Scene JSON, JPEG previews, rendered PNGs, the decompressed
  catalog, the on-demand cache, and (if you download it) the local library
  are written under the plugin data directory and, if you set them, the
  Export directory or `local_library_dir`. Writes also honour Hermes
  `file_safety` when the host provides it. Removing a local library from the
  pane requires confirmation and will not delete the source checkout.
- **Untrusted catalog text.** Asset names, tags, and descriptions are treated
  as data, not instructions (control characters are stripped in tool results
  and the pane uses text nodes, not HTML).
- **No secrets** are logged or printed. No subprocesses are spawned.

The installed plugin (this `plugin/` tree, including the 4.7 MB catalog
snapshot) is a few megabytes. A full local library download is about 1.65 GB
plus the catalog; individual style-pack sizes are listed in the pane.

## Develop

From the repository root, with this `plugin/` directory on `PYTHONPATH`:

```bash
PYTHONPATH=plugin pytest -q tests
python evals/measure_schemas.py
python plugin/desktop/build_plugin.py   # rebuild desktop/plugin.js
hermes plugins doctor plugin --ci
hermes plugins validate plugin --install-deps
```

Standalone / mock-host tests cover registration, FTS search, path confinement,
Pillow compositing, JSON handler envelopes, and on-demand fetch / local
install with a mock HTTP fetcher. They never hit the network and they do not
decompress the real 151 MB catalog. They are **not** a live Hermes Desktop
proof — the pane still needs a real host before a catalog submission.

Schema tokens are measured with tiktoken `o200k_base` (and `cl100k_base` for
comparison). Keep the two `op`-style tools; do not split them into many
fine-grained tools, and do not add a model-callable download tool.

Bump the version in one place with
`python plugin/scripts/bump_plugin_version.py 0.1.1` (also updates
`pyproject.toml` and `assetrizz_plugin/__init__.py`). Tag, release, catalog
submit, and deploy only with an explicit yes from the owner.
