"""Lightweight image post-process: chroma key, slice, pixel-snap, thumbs, phash, QA.

Pillow + numpy only. Designed to run nice'd and sequentially per worker.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps, ImageStat

MAGENTA = (255, 0, 255)
THUMB_SIZE = 128


def load_rgba(path: Path) -> Image.Image:
    im = Image.open(path)
    if im.mode == "P":
        im = im.convert("RGBA")
    elif im.mode != "RGBA":
        im = im.convert("RGBA")
    return im


def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _key_distance(rgb: np.ndarray, key: tuple[int, int, int]) -> np.ndarray:
    return np.sqrt(np.sum((rgb.astype(np.int32) - np.array(key, dtype=np.int32)) ** 2, axis=2))


def _detect_key_color(rgb: np.ndarray, key: tuple[int, int, int], fuzz: float) -> tuple[tuple[int, int, int], np.ndarray]:
    dist = _key_distance(rgb, key)
    if float((dist < fuzz).mean()) >= 0.04:
        return key, dist
    h, w = rgb.shape[:2]
    rh, rw = max(1, min(6, h // 8)), max(1, min(6, w // 8))
    corners = np.concatenate(
        [
            rgb[0:rh, 0:rw].reshape(-1, 3),
            rgb[0:rh, -rw:].reshape(-1, 3),
            rgb[-rh:, 0:rw].reshape(-1, 3),
            rgb[-rh:, -rw:].reshape(-1, 3),
        ]
    )
    alt = np.median(corners, axis=0)
    alt_dist = _key_distance(rgb, tuple(int(x) for x in alt))
    alt_frac = float((alt_dist < fuzz).mean())
    corner_spread = float(np.mean(np.std(corners.astype(np.float32), axis=0)))
    if alt_frac >= 0.12 and corner_spread < 18:
        return tuple(int(x) for x in alt), alt_dist
    return key, dist


def despill_rgb(rgb: np.ndarray, key: tuple[int, int, int], strength: np.ndarray) -> np.ndarray:
    """Pull the key colour out of fringe pixels (magenta: drop excess R and B toward G)."""
    out = rgb.astype(np.float32)
    k = np.array(key, dtype=np.float32)
    k_w = k / (k.max() + 1e-6)
    other_w = 1.0 - k_w
    other_sum = float(other_w.sum()) + 1e-6
    other = (out * other_w.reshape(1, 1, 3)).sum(axis=2) / other_sum
    stren = np.clip(strength, 0, 1).astype(np.float32)
    for c in range(3):
        if k_w[c] < 0.5:
            continue
        spill = np.clip(out[:, :, c] - other, 0, None)
        out[:, :, c] = out[:, :, c] - spill * stren
    return np.clip(out, 0, 255)


def binary_erode(mask: np.ndarray, times: int = 1) -> np.ndarray:
    m = mask.astype(np.uint8)
    for _ in range(max(0, times)):
        p = np.pad(m, 1, mode="constant")
        neigh = np.stack(
            [
                p[0:-2, 0:-2], p[0:-2, 1:-1], p[0:-2, 2:],
                p[1:-1, 0:-2], p[1:-1, 1:-1], p[1:-1, 2:],
                p[2:, 0:-2], p[2:, 1:-1], p[2:, 2:],
            ],
            axis=0,
        )
        m = neigh.min(axis=0)
    return m.astype(bool)


def erode_alpha_image(im: Image.Image, times: int = 1) -> Image.Image:
    arr = np.asarray(im.convert("RGBA")).copy()
    keep = binary_erode(arr[:, :, 3] >= 128, times)
    arr[~keep, 3] = 0
    arr[~keep, :3] = 0
    return Image.fromarray(arr, "RGBA")


def chroma_key(
    im: Image.Image,
    key: tuple[int, int, int] = MAGENTA,
    fuzz: float = 52.0,
    erode_px: int = 1,
) -> Image.Image:
    """Key a flat backdrop, despill fringe, drop semi-keyed edge pixels, then erode alpha 1px."""
    arr = np.asarray(im.convert("RGBA")).astype(np.int32)
    rgb = arr[:, :, :3]
    key, dist = _detect_key_color(rgb, key, fuzz)
    alpha = arr[:, :, 3]
    hard = dist < fuzz
    # mid-band = semi-keyed / JPEG ringing around the key
    semi = (~hard) & (dist < fuzz * 1.55)
    # despill strength follows closeness to the key
    fade = np.clip((fuzz * 1.8 - dist) / max(fuzz * 0.8, 1.0), 0, 1)
    rgb = despill_rgb(rgb, key, fade)
    # drop keyed + semi-keyed completely (no partial alpha left to snap into red)
    new_a = np.where(hard | semi | (alpha < 200), 0, 255).astype(np.int32)
    # leftover magenta/pink after despill also goes
    k = np.array(key, dtype=np.float32)
    k_w = k / (k.max() + 1e-6)
    if k_w[0] > 0.5 and k_w[2] > 0.5 and k_w[1] < 0.5:
        excess = np.minimum(rgb[:, :, 0], rgb[:, :, 2]) - rgb[:, :, 1]
        new_a = np.where(excess > 36, 0, new_a)
    if erode_px:
        new_a = np.where(binary_erode(new_a >= 128, erode_px), 255, 0)
    arr[:, :, :3] = np.clip(rgb, 0, 255).astype(np.int32)
    arr[:, :, 3] = new_a
    clear = arr[:, :, 3] == 0
    arr[clear, 0] = 0
    arr[clear, 1] = 0
    arr[clear, 2] = 0
    return Image.fromarray(arr.astype(np.uint8), "RGBA")


def leak_palette_colors(palette: list[str], key: tuple[int, int, int] = MAGENTA) -> list[tuple[int, int, int]]:
    """Palette entries that are hot key-leak reds (high R, much higher than G), not dark outlines."""
    if not palette:
        return []
    k = np.array(key, dtype=np.float32)
    out = []
    for h in palette:
        c = np.array(hex_to_rgb(h), dtype=np.float32)
        luma = float(c.dot([0.30, 0.59, 0.11]))
        if luma < 50:
            continue
        # Hot reds near the magenta key (high R vs G, not gold/orange where B << G).
        if (c[0] - c[1]) >= 100 and (c[2] - c[1]) >= -10:
            out.append(tuple(int(x) for x in c))
    return out


def strip_key_leak_edges(im: Image.Image, palette: list[str], key: tuple[int, int, int] = MAGENTA) -> Image.Image:
    """After palette snap, drop silhouette-edge pixels that snapped to key-leak red."""
    leaks = leak_palette_colors(palette, key)
    if not leaks:
        return im
    arr = np.asarray(im.convert("RGBA")).copy()
    a = arr[:, :, 3]
    rgb = arr[:, :, :3]
    h, w = a.shape
    pad = np.pad(a, 1, mode="constant")
    edge = np.zeros_like(a, dtype=bool)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy == 0 and dx == 0:
                continue
            edge |= pad[1 + dy : h + 1 + dy, 1 + dx : w + 1 + dx] < 128
    edge &= a >= 128
    drop = np.zeros_like(a, dtype=bool)
    for c in leaks:
        drop |= edge & (rgb[:, :, 0] == c[0]) & (rgb[:, :, 1] == c[1]) & (rgb[:, :, 2] == c[2])
    arr[drop, 3] = 0
    arr[drop, 0] = 0
    arr[drop, 1] = 0
    arr[drop, 2] = 0
    return Image.fromarray(arr, "RGBA")


def _label_components(mask: np.ndarray) -> tuple[np.ndarray, int]:
    """4-connected component labels (1..n). Light union-find, no scipy."""
    h, w = mask.shape
    parent = np.arange(h * w + 1, dtype=np.int32)

    def find(x):
        # path splitting iterative
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    idx = np.zeros((h, w), dtype=np.int32)
    n = 0
    m = mask.astype(bool)
    for y in range(h):
        row = m[y]
        for x in range(w):
            if not row[x]:
                continue
            n += 1
            i = y * w + x
            idx[y, x] = i + 1
            if x > 0 and m[y, x - 1]:
                union(i, i - 1)
            if y > 0 and m[y - 1, x]:
                union(i, i - w)
    if n == 0:
        return np.zeros((h, w), dtype=np.int32), 0
    roots = {}
    labels = np.zeros((h, w), dtype=np.int32)
    next_id = 0
    ys, xs = np.where(m)
    for y, x in zip(ys.tolist(), xs.tolist()):
        r = find(y * w + x)
        if r not in roots:
            next_id += 1
            roots[r] = next_id
        labels[y, x] = roots[r]
    return labels, next_id


def trim_and_pad(im: Image.Image, pad: int = 2, min_alpha: int = 8) -> Image.Image:
    arr = np.asarray(im)
    a = arr[:, :, 3]
    ys, xs = np.where(a > min_alpha)
    if len(xs) == 0:
        return im
    left, right = int(xs.min()), int(xs.max()) + 1
    top, bottom = int(ys.min()), int(ys.max()) + 1
    cropped = im.crop((left, top, right, bottom))
    if pad <= 0:
        return cropped
    canvas = Image.new("RGBA", (cropped.width + pad * 2, cropped.height + pad * 2), (0, 0, 0, 0))
    canvas.paste(cropped, (pad, pad), cropped)
    return canvas


def fit_canvas(im: Image.Image, w: int, h: int, pixel: bool, anchor: str = "center") -> Image.Image:
    """Scale the sprite to fit inside w x h and paste onto a transparent canvas."""
    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    if im.width == 0 or im.height == 0:
        return canvas
    scale = min(w / im.width, h / im.height)
    nw, nh = max(1, int(round(im.width * scale))), max(1, int(round(im.height * scale)))
    if pixel:
        # For pixel targets, do not upscale with anything but nearest; prefer integer scales.
        if scale >= 1:
            # already smaller or equal: center as-is if both dims fit, else nearest shrink
            if im.width <= w and im.height <= h:
                nw, nh = im.width, im.height
            else:
                nw, nh = max(1, int(im.width * scale)), max(1, int(im.height * scale))
                im = im.resize((nw, nh), Image.Resampling.NEAREST)
        else:
            im = im.resize((nw, nh), Image.Resampling.NEAREST)
    else:
        resample = Image.Resampling.LANCZOS if scale < 1 else Image.Resampling.BOX
        im = im.resize((nw, nh), resample)
        if im.size != (nw, nh):
            im = im.resize((nw, nh), Image.Resampling.LANCZOS)
    if anchor == "feet":
        x = (w - im.width) // 2
        y = h - im.height
    else:
        x = (w - im.width) // 2
        y = (h - im.height) // 2
    canvas.paste(im, (x, y), im)
    return canvas


def snap_palette(im: Image.Image, palette: list[str], keep_alpha: bool = True) -> Image.Image:
    """Nearest-color remap to a locked palette. No dither. Alpha preserved (binary-ish)."""
    arr = np.asarray(im.convert("RGBA"))
    rgb = arr[:, :, :3].astype(np.int16)
    a = arr[:, :, 3]
    pal = np.array([hex_to_rgb(h) for h in palette], dtype=np.int16)
    # flatten and compute distances
    flat = rgb.reshape(-1, 3)
    # chunk to keep memory modest
    out = np.empty((flat.shape[0],), dtype=np.int32)
    step = 200_000
    pal_f = pal.astype(np.int32)
    for i in range(0, flat.shape[0], step):
        chunk = flat[i : i + step].astype(np.int32)
        # (n, 1, 3) - (p, 3) -> (n, p)
        d = np.sum((chunk[:, None, :] - pal_f[None, :, :]) ** 2, axis=2)
        out[i : i + step] = np.argmin(d, axis=1)
    mapped = pal[out].reshape(rgb.shape).astype(np.uint8)
    # harden alpha for pixel art
    a_hard = np.where(a >= 128, 255, 0).astype(np.uint8)
    rgba = np.dstack([mapped, a_hard])
    rgba[a_hard == 0, 0] = 0
    rgba[a_hard == 0, 1] = 0
    rgba[a_hard == 0, 2] = 0
    return Image.fromarray(rgba, "RGBA")


def downscale_pixel(im: Image.Image, w: int, h: int) -> Image.Image:
    return im.resize((w, h), Image.Resampling.NEAREST)


def extract_palette(im: Image.Image, n: int = 8) -> tuple[list[str], list[str]]:
    """Simple quantized palette + dominant colors. Lightweight (adaptive palette)."""
    rgba = im.convert("RGBA")
    opaque = rgba
    # drop transparent for counting
    arr = np.asarray(rgba)
    mask = arr[:, :, 3] >= 128
    if mask.sum() < 4:
        return [], []
    pixels = arr[mask][:, :3]
    # sample if huge
    if pixels.shape[0] > 40000:
        rng = np.random.default_rng(0)
        pixels = pixels[rng.choice(pixels.shape[0], 40000, replace=False)]
    # use a tiny image + adaptive palette
    sample = Image.fromarray(pixels.reshape(-1, 1, 3).astype(np.uint8), "RGB")
    # reshape to a compact image
    side = int(np.ceil(np.sqrt(pixels.shape[0])))
    canvas = Image.new("RGB", (side, side), (0, 0, 0))
    flat = Image.fromarray(pixels.astype(np.uint8).reshape(1, -1, 3)[:, : pixels.shape[0], :], "RGB")
    # Adaptive palette via Pillow
    pal_im = Image.fromarray(pixels[: min(len(pixels), side * side)].reshape(-1, 3).astype(np.uint8).reshape(-1, 1, 3), "RGB")
    # Better: make a 128x? image of the opaque pixels
    take = min(pixels.shape[0], 128 * 128)
    h = take // 128 or 1
    w = take // h
    take = w * h
    qim = Image.fromarray(pixels[:take].reshape(h, w, 3).astype(np.uint8), "RGB")
    q = qim.quantize(colors=max(2, n), method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    raw_pal = q.getpalette()[: n * 3]
    colors = [f"#{raw_pal[i]:02X}{raw_pal[i+1]:02X}{raw_pal[i+2]:02X}" for i in range(0, len(raw_pal), 3)]
    # dominant: most frequent palette indices
    idx = np.asarray(q)
    counts = np.bincount(idx.flatten(), minlength=n)
    order = list(np.argsort(-counts))
    dominant = [colors[i] for i in order if i < len(colors) and counts[i] > 0]
    # unique preserve order
    seen = set()
    uniq = []
    for c in colors:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq[:n], dominant[:n]


def dhash(im: Image.Image, size: int = 8) -> str:
    """64-bit difference hash as 16-char hex."""
    g = im.convert("RGBA")
    # composite on mid-grey so transparent does not dominate
    bg = Image.new("RGB", g.size, (127, 127, 127))
    bg.paste(g, mask=g.split()[-1])
    small = bg.convert("L").resize((size + 1, size), Image.Resampling.LANCZOS)
    arr = np.asarray(small, dtype=np.int16)
    bits = (arr[:, 1:] > arr[:, :-1]).flatten()
    value = 0
    for b in bits:
        value = (value << 1) | int(b)
    return f"{value:016x}"


def hamming(a: str, b: str) -> int:
    try:
        return int(a, 16) ^ int(b, 16)
    except Exception:
        return 64


def hamming_hex(a: str, b: str) -> int:
    try:
        x = int(a, 16) ^ int(b, 16)
        return x.bit_count()
    except Exception:
        return 64


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def opaque_ratio(im: Image.Image, thr: int = 8) -> float:
    a = np.asarray(im.split()[-1])
    return float((a > thr).mean())


def looks_like_checkerboard(im: Image.Image) -> bool:
    """Cheap QA: regular 2-color alternating blocks often mean a fake-transparent preview."""
    small = im.convert("RGB").resize((32, 32), Image.Resampling.NEAREST)
    arr = np.asarray(small)
    # check 2x2 period energy
    a = arr[0::2, 0::2].reshape(-1, 3).astype(np.int16)
    b = arr[0::2, 1::2].reshape(-1, 3).astype(np.int16)
    c = arr[1::2, 0::2].reshape(-1, 3).astype(np.int16)
    d = arr[1::2, 1::2].reshape(-1, 3).astype(np.int16)
    # classic checker: a≈d, b≈c, a far from b
    ad = np.mean(np.linalg.norm(a - d, axis=1))
    bc = np.mean(np.linalg.norm(b - c, axis=1))
    ab = np.mean(np.linalg.norm(a - b, axis=1))
    return ad < 18 and bc < 18 and ab > 40


def qa_check(im: Image.Image, *, pixel: bool, tileable: bool) -> tuple[str, list[str]]:
    notes = []
    ratio = opaque_ratio(im)
    if ratio < 0.012:
        notes.append("almost_empty")
    if ratio > 0.97 and not tileable:
        notes.append("no_alpha_fill")
    if looks_like_checkerboard(im):
        notes.append("checkerboard")
    arr = np.asarray(im.convert("RGBA"))
    # leftover magenta
    rgb = arr[:, :, :3].astype(np.int32)
    a = arr[:, :, 3]
    mag = np.sqrt(np.sum((rgb - np.array([255, 0, 255], dtype=np.int32)) ** 2, axis=2))
    if float(((mag < 28) & (a > 16)).mean()) > 0.01:
        notes.append("magenta_fringe")
    if im.width < 8 or im.height < 8:
        notes.append("too_small")
    status = "rejected" if any(n in notes for n in ("almost_empty", "checkerboard", "too_small")) else "ok"
    return status, notes


def make_thumb(im: Image.Image, path: Path, size: int = THUMB_SIZE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # preview on mid grey so alpha is visible, plus a true RGBA thumb
    fitted = im.copy()
    fitted.thumbnail((size, size), Image.Resampling.NEAREST if max(im.size) <= 128 else Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(fitted, ((size - fitted.width) // 2, (size - fitted.height) // 2), fitted)
    canvas.save(path, "PNG", optimize=True)


def isolate_main_component(
    im: Image.Image,
    key: tuple[int, int, int] = MAGENTA,
    fuzz: float = 52.0,
) -> Image.Image:
    """Keep the largest central foreground component; drop fragments that only belong to the border."""
    arr = np.asarray(im.convert("RGBA")).copy()
    h, w = arr.shape[:2]
    if h < 4 or w < 4:
        return im
    key, dist = _detect_key_color(arr[:, :, :3], key, fuzz)
    fg = dist >= fuzz
    if int(fg.sum()) < 8:
        return im
    labels, nlab = _label_components(fg)
    if nlab == 0:
        return im
    cy, cx = (h - 1) / 2.0, (w - 1) / 2.0
    inner_y0, inner_y1 = int(h * 0.15), int(np.ceil(h * 0.85))
    inner_x0, inner_x1 = int(w * 0.15), int(np.ceil(w * 0.85))
    best = None
    best_score = -1.0
    for lab in range(1, nlab + 1):
        ys, xs = np.where(labels == lab)
        if len(xs) == 0:
            continue
        area = float(len(xs))
        touches = bool(
            (ys == 0).any() or (ys == h - 1).any() or (xs == 0).any() or (xs == w - 1).any()
        )
        my, mx = float(ys.mean()), float(xs.mean())
        in_center = (inner_x0 <= mx <= inner_x1) and (inner_y0 <= my <= inner_y1)
        distc = ((my - cy) ** 2 + (mx - cx) ** 2) ** 0.5
        # Prefer large, central components. Border-only fragments score very low.
        if touches and not in_center and area < 0.35 * fg.sum():
            continue
        score = area * (1.0 / (1.0 + distc / max(h, w)))
        if touches and not in_center:
            score *= 0.15
        if score > best_score:
            best_score = score
            best = lab
    if best is None:
        # fallback: largest component whose centroid is closest to center
        best = 1
        best_area = -1
        for lab in range(1, nlab + 1):
            area = int((labels == lab).sum())
            if area > best_area:
                best_area, best = area, lab
    keep = labels == best
    # Paint discarded fragments as flat key so later chroma_key sees a clean field.
    arr[~keep, 0] = key[0]
    arr[~keep, 1] = key[1]
    arr[~keep, 2] = key[2]
    arr[~keep, 3] = 255
    return Image.fromarray(arr.astype(np.uint8), "RGBA")


def slice_grid(
    im: Image.Image,
    grid_w: int,
    grid_h: int,
    gutter_guess: bool = True,
    key: tuple[int, int, int] = MAGENTA,
) -> list[Image.Image]:
    """Slice a regular grid, then keep only the largest central component in each cell."""
    W, H = im.size
    cell_w = W / grid_w
    cell_h = H / grid_h
    inset_x = inset_y = 0
    if gutter_guess and grid_w > 1:
        # tighter than a full gutter, just enough to avoid the seam itself
        inset_x = max(1, int(cell_w * 0.03))
        inset_y = max(1, int(cell_h * 0.03))
    cells = []
    for r in range(grid_h):
        for c in range(grid_w):
            left = int(round(c * cell_w)) + inset_x
            top = int(round(r * cell_h)) + inset_y
            right = int(round((c + 1) * cell_w)) - inset_x
            bottom = int(round((r + 1) * cell_h)) - inset_y
            if right <= left or bottom <= top:
                left = int(round(c * cell_w))
                top = int(round(r * cell_h))
                right = int(round((c + 1) * cell_w))
                bottom = int(round((r + 1) * cell_h))
            cell = im.crop((left, top, right, bottom))
            if grid_w * grid_h > 1:
                cell = isolate_main_component(cell, key=key)
            cells.append(cell)
    return cells


def finish_sprite(
    im: Image.Image,
    *,
    target: tuple[int, int],
    palette: list[str],
    pixel: bool,
    tileable: bool,
    chroma: tuple[int, int, int] = MAGENTA,
    pivot_anchor: str = "center",
    key_bg: bool = True,
) -> dict:
    work = im.convert("RGBA")
    if key_bg and not tileable:
        work = chroma_key(work, chroma, fuzz=52.0, erode_px=1)
        work = trim_and_pad(work, pad=2 if not pixel else 1)
    elif key_bg and tileable:
        # tileables should usually be opaque; only key if magenta really is a border
        pass
    if pixel:
        work = downscale_pixel(work, target[0], target[1]) if (work.width != target[0] or work.height != target[1]) else work
        # 1px erode already ran at full resolution inside chroma_key, before this downscale
        # and palette snap. Repeating it at 32px ate thin blades; leak-red is stripped after snap.
        if palette:
            work = snap_palette(work, palette)
            work = strip_key_leak_edges(work, palette, chroma)
        # ensure exact canvas
        if work.size != target:
            work = fit_canvas(work, target[0], target[1], pixel=True, anchor=pivot_anchor)
        elif palette:
            # fit_canvas already happened; leak strip already applied
            pass
    else:
        if tileable:
            work = work.resize(target, Image.Resampling.LANCZOS)
            work = work.convert("RGBA")
            # drop residual magenta if any
            work = chroma_key(work, chroma, fuzz=24.0)
            # if almost all transparent, the tile was not magenta-backed — restore resized RGB as opaque
            if opaque_ratio(work) < 0.5:
                work = im.convert("RGB").resize(target, Image.Resampling.LANCZOS).convert("RGBA")
        else:
            work = fit_canvas(work, target[0], target[1], pixel=False, anchor=pivot_anchor)
    status, notes = qa_check(work, pixel=pixel, tileable=tileable)
    pal, dominant = extract_palette(work)
    ph = dhash(work)
    has_alpha = bool(opaque_ratio(work) < 0.995)
    return {
        "image": work,
        "status": status,
        "qa_notes": notes,
        "palette": pal,
        "dominant_colors": dominant,
        "phash": ph,
        "has_alpha": has_alpha,
        "width": work.width,
        "height": work.height,
    }


def contact_sheet(images: list[Image.Image], path: Path, cols: int = 8, cell: int = 96, bg=(32, 32, 36, 255)) -> Path:
    if not images:
        raise ValueError("no images")
    rows = (len(images) + cols - 1) // cols
    sheet = Image.new("RGBA", (cols * cell, rows * cell), bg)
    for i, im in enumerate(images):
        thumb = im.copy()
        thumb.thumbnail((cell - 4, cell - 4), Image.Resampling.NEAREST if max(im.size) <= 128 else Image.Resampling.LANCZOS)
        x = (i % cols) * cell + (cell - thumb.width) // 2
        y = (i // cols) * cell + (cell - thumb.height) // 2
        if thumb.mode != "RGBA":
            thumb = thumb.convert("RGBA")
        sheet.paste(thumb, (x, y), thumb)
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path, "PNG")
    return path


def save_png(im: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, "PNG", optimize=True)
