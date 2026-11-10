---
name: assetrizz-composer
description: >-
  Search the local assetrizz 2D game-asset library and compose scenes from those
  assets with assetrizz_search and assetrizz_scene. Use when the user wants to
  find sprites, tiles, characters, or props, or to lay out a level or scene.
---

# Assetrizz composer

Skill id: `assetrizz:assetrizz-composer`. Pass that exact string only to
`skill_view`. Do not add a `plugin:` prefix or a slash.

Hermes Tool Search may defer these tools. If `assetrizz_search` and
`assetrizz_scene` are not in your visible tool list, call
`tool_search(["assetrizz"])` or `skill_view("assetrizz:assetrizz-composer")`,
then use them. Do not write your own SQLite or Pillow scripts to do this work.

## Tools

### `assetrizz_search`

- `op=search` — free-text `q` plus optional `style`, `category`, `tags`,
  `subject`, `tileable`, `alpha`, `size`, `limit`, `offset`. Returns compact
  rows (`id`, `slug`, `path`, tags, size). Default 20 results, max 50.
- `op=get` — one asset by `id` or `slug` (full metadata, including palette and
  pivot when present).
- `op=stats` — accepted-asset counts by style and category, plus the resolved
  library path.

Search first. Then pass a returned `slug` or `id` to `assetrizz_scene`.

### `assetrizz_scene`

Assets must come from the library. There is no path argument that can open
arbitrary files.

- `op=create` — `width`, `height`, optional `name`, optional `background`
  (`#RRGGBB`, `transparent`, or a library slug to fill).
- `op=place` — `slug` or `asset_id`, `x`, `y`, optional `scale`, `flip_x`,
  `flip_y`, `z`.
- `op=tile` — fill a rectangle with a (usually tileable) asset: `slug`, `x`,
  `y`, `tile_w`, `tile_h`, optional `scale`.
- `op=move` / `scale` / `flip` / `layer` / `remove` — take a `layer` id
  (`L1`, `L2`, …). `layer` accepts `z` or `where=front|back`.
- `op=list` — current scene layers and saved scenes.
- `op=clear` — remove every layer, keep the canvas size.
- `op=render` — write a PNG under the export directory and refresh the pane
  preview. Returns a filesystem path, not a full image. Do not embed the PNG.
- `op=save` / `op=load` — scene JSON in the plugin data dir; `save` can take
  `as` / `name` to copy.

Sizes are 16–4096 px per side, at most 200 layers, scale 0.05–8.

## Pane

The Assetrizz Desktop / dashboard pane (dark mode) live-previews the current
scene, lists layers, and can browse the library. Open it beside the chat if
the user wants to watch the compose. Tools still work when the pane is closed.

If the pane says the library is missing, ask the user to set **Settings →
Plugins → assetrizz → Library path** (or `ASSETRIZZ_LIBRARY`) to an assetrizz
clone that contains `assets/` and `db/assets.db.xz`. The plugin auto-restores
the catalog from the `.xz` on first use.

## Failure codes

| code | What to do |
|---|---|
| `library_missing` | Point `library_path` / `ASSETRIZZ_LIBRARY` at an assetrizz checkout. |
| `not_found` | Search again and use a returned slug, id, or layer id. |
| `no_scene` | `assetrizz_scene op=create` first. |
| `path_escape` | Stay inside the library and the export / plugin data dir. |
| `payload_too_large` | Use the PNG path on disk; do not embed the image. |
| `invalid_op` / `invalid_args` | Read `fix` and retry with a documented op. |

Every result is a JSON string with `ok` and, on failure, `error`, `code`, and
`fix`.
