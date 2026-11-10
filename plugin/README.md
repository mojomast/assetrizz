# Assetrizz Hermes plugin

Search a local [assetrizz](https://github.com/mojomast/assetrizz) 2D game-asset
library and compose scenes from those assets. The Hermes agent gets two compact
tools; you get a dark compose pane that live-previews what it placed.

This directory is the installable plugin. The 14,641 PNGs and the SQLite
catalog live in the parent repository (or any other download of that tree).
They are **not** copied into `~/.hermes/plugins/`.

- Skill id: `assetrizz:assetrizz-composer` (pass that exact string to `skill_view`)
- Tools: `assetrizz_search`, `assetrizz_scene`
- Requires Hermes `>=0.23.0` (Desktop pane uses `ctx.rest`)
- Version: `0.1.0`
- License: MIT for the plugin code. The assets themselves stay
  “original, generated for Kyle Durepos” — see the [library license](../pipeline/LICENSE.txt).

## Install

1. Clone or download the library (assets + compressed catalog):

   ```bash
   git clone https://github.com/mojomast/assetrizz
   ```

2. Install **only** this `plugin/` directory:

   ```bash
   hermes plugins install mojomast/assetrizz/plugin
   ```

   A root install of `mojomast/assetrizz` is refused on purpose so Hermes does
   not publish the 1.65 GB asset tree into the plugins folder.

3. Point the plugin at the checkout. If you installed from a full clone and
   left `plugin/` inside it, the library is usually auto-detected. Otherwise
   set **Settings → Plugins → assetrizz → Library path**, or:

   ```bash
   export ASSETRIZZ_LIBRARY=/path/to/assetrizz
   ```

   The folder must contain `assets/` and `db/assets.db.xz`. The first search
   decompresses the catalog into `db/assets.db` (or into the plugin data dir
   if the checkout is not writable). You can also run `bash db/restore.sh`
   yourself.

4. Optional: set **Export directory** (`ASSETRIZZ_EXPORT_DIR`) for rendered
   PNGs. It must not be a filesystem root. The default is the plugin data
   `exports/` folder, which survives `hermes plugins update`.

The two tools work without the Desktop pane. On Hermes Desktop 0.23 or newer,
open the **Assetrizz** pane to watch the current scene, browse assets, and
inspect layers. The pane talks only through `ctx.rest` — it never dials
loopback or attaches authorization headers.

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

- **No network.** The plugin does not fetch URLs and holds no credentials
  (`requires_env` is empty).
- **Local files only.** It reads PNG assets and a SQLite catalog from the
  configured library root, confined after symlink resolution. Tool arguments
  cannot point it at an arbitrary path or a filesystem root.
- **Writes.** Scene JSON, previews, and rendered PNGs go under the plugin data
  directory and the optional export directory. The first catalog restore may
  write `db/assets.db` into the library or a copy under plugin data.
- **No secrets** are logged or printed.

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
Pillow compositing, and JSON handler envelopes. They are **not** a live Hermes
Desktop proof — the pane still needs a real host before a catalog submission.

Schema tokens are measured with tiktoken `o200k_base` (and `cl100k_base` for
comparison). Keep the two `op`-style tools; do not split them into many
fine-grained tools.

Bump the version in one place with
`python plugin/scripts/bump_plugin_version.py 0.1.1` (also updates
`pyproject.toml` and `assetrizz_plugin/__init__.py`). Tag, release, catalog
submit, and deploy only with an explicit yes from the owner.
