"""Cut 小瓜 sprite sheets into the per-motion PNG folders the pet plays.

Sheets live in assets/xiaogua/sheets/ as grids of equal cells. Each motion takes
some cells of one sheet, in order, and is written to assets/xiaogua/<motion>/ as
512x512 transparent frames (voice/xiaogua-motion-design.md):

- one scale for every frame of a motion, so the figure never breathes in size;
- feet anchored at (256, 470): the bottom of the figure sits on y=470 and the
  middle of its lowest quarter (feet, cushion, table legs) sits on x=256, so a
  waving arm does not drag the body sideways.

Frame sequences (a folder of numbered PNGs, e.g. the redrawn 思考 / 拖拽 keys) are
imported by CLIPS below instead: one transform for a whole group of clips, so a
lift really goes up and the hover continues from where the lift ended.

Re-run after replacing a sheet:  python -m meihua.companion.sprites
"""

from __future__ import annotations

import json
import shutil
import sys
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw

import meihua

from .app import cut_out

SHEETS = meihua.ROOT / "assets" / "xiaogua" / "sheets"
OUT = meihua.ROOT / "assets" / "xiaogua"
CANVAS, FOOT_X, FOOT_Y = 512, 256, 470
ALPHA_SOLID = 96          # below this a pixel is shadow / soft edge, not figure
ALPHA_NOISE = 8           # below this a pixel is compression residue


@dataclass(frozen=True)
class Motion:
    name: str
    sheet: str
    grid: tuple[int, int]          # rows, cols
    cells: tuple[int, ...]         # 1-based, row-major, in play order
    height: int                    # figure height on the canvas for the tallest frame
    frame_ms: int = 90
    take: tuple[int, ...] | None = None   # write only these (1-based) of the built frames;
                                          # the scale still comes from all cells, so two
                                          # motions cut from one sheet stay the same size


# Heights are chosen so the melon body is about the same size in every motion;
# props (table, cushion) add to the figure's height, not the melon's.
# 歪头, 摇头, 落地 (and 点头, 说话, 被摸头, 犯困, 欢呼, 登场) are made elsewhere now:
# tools/make_procedural_motions.py and companion/import_sheet.py. Do not cut them here again.
MOTIONS = [
    Motion("招手", "招手.webp", (4, 4), tuple(range(1, 17)), 400),
    Motion("翻书", "翻书.webp", (4, 4), tuple(range(1, 17)), 400, 110),
    Motion("睡着", "睡着.webp", (4, 4), tuple(range(1, 17)), 390, 160),
    Motion("加油", "举手.webp", (4, 4), tuple(range(1, 13)), 400),
    Motion("待机", "举手.webp", (4, 4), (13, 14, 15, 16, 15, 14), 400, 220),
    Motion("看图", "放大镜.webp", (3, 4), tuple(range(1, 13)), 400, 110),
    Motion("起卦", "起卦卷轴.webp", (3, 4), tuple(range(1, 13)), 430, 110, take=tuple(range(1, 9))),
    Motion("灵光一闪", "起卦卷轴.webp", (3, 4), tuple(range(1, 13)), 430, 120, take=(9, 10, 11, 12)),
    Motion("摸鱼", "托腮_摸鱼_吃饭.webp", (3, 4), (5, 6, 7, 8), 390, 200),
    Motion("吃饭", "托腮_摸鱼_吃饭.webp", (3, 4), (9, 10, 11, 12), 400, 180),
]


def cells(sheet: Image.Image, grid: tuple[int, int]) -> list[Image.Image]:
    rows, cols = grid
    width, height = sheet.width / cols, sheet.height / rows
    out = []
    for r in range(rows):
        for c in range(cols):
            box = (round(c * width), round(r * height), round((c + 1) * width), round((r + 1) * height))
            cell = sheet.crop(box)
            # Opaque sheets (paper background) are cut out the same way the GIFs are.
            if cell.getchannel("A").getextrema()[0] == 255:
                cell = cut_out(cell)
            # WebP leaves near-invisible alpha specks across the whole sheet; drop them.
            cell.putalpha(cell.getchannel("A").point(lambda a: 0 if a < ALPHA_NOISE else a))
            out.append(cell)
    return out


def anchor(cell: Image.Image) -> tuple[tuple[int, int, int, int], float, int]:
    """(solid bbox, foot centre x, bottom y) in cell pixels."""
    solid = cell.getchannel("A").point(lambda a: 255 if a >= ALPHA_SOLID else 0)
    left, top, right, bottom = solid.getbbox()
    foot_band = solid.crop((0, bottom - (bottom - top) // 4, cell.width, bottom)).getbbox()
    return (left, top, right, bottom), (foot_band[0] + foot_band[2]) / 2, bottom


def build(motion: Motion) -> list[Image.Image]:
    sheet = Image.open(SHEETS / motion.sheet).convert("RGBA")
    grid_cells = cells(sheet, motion.grid)
    picked = [grid_cells[i - 1] for i in motion.cells]
    anchors = [anchor(c) for c in picked]
    scale = motion.height / max(b[3] - b[1] for b, _, _ in anchors)
    frames = []
    for cell, (_, foot_x, bottom) in zip(picked, anchors):
        size = (round(cell.width * scale), round(cell.height * scale))
        scaled = cell.resize(size, Image.LANCZOS)
        canvas = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
        canvas.alpha_composite(scaled, (round(FOOT_X - foot_x * scale), round(FOOT_Y - bottom * scale)))
        frames.append(canvas)
    return frames


def write(motion: Motion) -> dict:
    folder = OUT / motion.name
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    frames = build(motion)
    if motion.take:
        frames = [frames[i - 1] for i in motion.take]
    for index, frame in enumerate(frames, 1):
        frame.save(folder / f"{index:02d}.png")
    (folder / "motion.json").write_text(
        json.dumps({"frame_ms": motion.frame_ms, "sheet": motion.sheet, "cells": list(motion.cells)},
                   ensure_ascii=False), encoding="utf-8")
    clipped = sum(1 for f in frames if _touches_edge(f))
    return {"motion": motion.name, "frames": len(frames), "frame_ms": motion.frame_ms, "clipped": clipped}


# ------------------------------------------------------------ frame sequences

BODY_WIDTH = 330          # the melon's width on the canvas, measured on 待机 (arms down)


@dataclass(frozen=True)
class Clip:
    name: str
    source: str                     # folder under sheets/, numbered PNGs on cream paper
    indices: tuple[int, ...]        # 0-based positions in that folder, in play order
    frame_ms: int
    playback: str = "forward"       # or "pingpong": loops back and forth, so it has no seam
    reference: int = 0              # the grounded frame whose width and feet set the transform


# Clean redrawn keys, not the 60 fps interpolated clips: those blend neighbouring
# keys into ghosted double images wherever the pose changes a lot.
CLIPS = [
    Clip("思考入", "redrawn/思考", tuple(range(0, 7)), 90),
    Clip("思考", "redrawn/思考", tuple(range(6, 12)), 150, "pingpong"),
    Clip("思考出", "redrawn/思考", tuple(range(12, 18)), 90),
    # 提起 / 悬空 / 落地 are made from 待机 now (tools/make_procedural_motions.py): same size and colour.
]


def key_out(image: Image.Image, flood_tolerance: int = 60, soft_low: int = 10, soft_high: int = 60) -> Image.Image:
    """Cream paper -> transparent, keeping the soft shadow.

    Only paper reachable from the corners (the flood) can turn transparent, so the
    melon's own light patches stay solid; inside that region alpha follows the
    colour distance from the paper, and the colour is un-mixed from the paper, so
    the ground shadow becomes a clean semi-transparent grey.
    """
    rgb = image.convert("RGB")
    marker = (255, 0, 255)
    flooded = rgb.copy()
    w, h = rgb.size
    for corner in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        ImageDraw.floodfill(flooded, corner, marker, thresh=flood_tolerance)
    pixels = np.asarray(rgb).astype(np.float32)
    region = np.all(np.asarray(flooded) == marker, axis=-1)
    paper = np.median(np.concatenate([pixels[:4, :4].reshape(-1, 3), pixels[-4:, -4:].reshape(-1, 3)]), axis=0)
    distance = np.abs(pixels - paper).max(axis=-1)
    soft = np.clip((distance - soft_low) / (soft_high - soft_low), 0.0, 1.0)
    alpha = np.where(region, soft, 1.0)
    safe = np.maximum(alpha, 1e-3)[..., None]
    colour = np.where(region[..., None], (pixels - (1.0 - alpha[..., None]) * paper) / safe, pixels)
    out = np.dstack([np.clip(colour, 0, 255), alpha * 255]).astype(np.uint8)
    return Image.fromarray(out, "RGBA")


def _body_width(alpha: np.ndarray) -> int:
    solid = alpha >= ALPHA_SOLID
    ys = np.nonzero(solid.any(axis=1))[0]
    top, bottom = ys.min(), ys.max()
    band = solid[top + (bottom - top) // 3: top + 2 * (bottom - top) // 3]
    return int(max((np.nonzero(row)[0].max() - np.nonzero(row)[0].min()) for row in band if row.any()))


def build_clip(clip: Clip) -> list[Image.Image]:
    files = sorted((SHEETS / clip.source).glob("*.png"))
    keyed = {i: key_out(Image.open(files[i])) for i in set(clip.indices) | {clip.reference}}
    reference = keyed[clip.reference]
    alpha = np.asarray(reference.getchannel("A"))
    scale = BODY_WIDTH / _body_width(alpha)
    _, foot_x, bottom = anchor(reference)
    offset = (round(FOOT_X - foot_x * scale), round(FOOT_Y - bottom * scale))
    frames = []
    for i in clip.indices:
        frame = keyed[i]
        scaled = frame.resize((round(frame.width * scale), round(frame.height * scale)), Image.LANCZOS)
        canvas = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
        canvas.alpha_composite(scaled, offset)     # the same offset for every frame: motion is kept
        frames.append(canvas)
    return frames


def write_clip(clip: Clip) -> dict:
    folder = OUT / clip.name
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    frames = build_clip(clip)
    for index, frame in enumerate(frames, 1):
        frame.save(folder / f"{index:02d}.png")
    (folder / "motion.json").write_text(json.dumps(
        {"frame_ms": clip.frame_ms, "playback": clip.playback, "source": clip.source,
         "indices": list(clip.indices)}, ensure_ascii=False), encoding="utf-8")
    return {"motion": clip.name, "frames": len(frames), "frame_ms": clip.frame_ms,
            "playback": clip.playback, "clipped": sum(1 for f in frames if _touches_edge(f))}


def _touches_edge(frame: Image.Image) -> bool:
    left, top, right, bottom = frame.getchannel("A").getbbox()
    return left == 0 or top == 0 or right == CANVAS or bottom == CANVAS


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    wanted = set(sys.argv[1:])
    for motion in MOTIONS:
        if not wanted or motion.name in wanted:
            print(json.dumps(write(motion), ensure_ascii=False))
    for clip in CLIPS:
        if (not wanted or clip.name in wanted) and (SHEETS / clip.source).is_dir():
            print(json.dumps(write_clip(clip), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
