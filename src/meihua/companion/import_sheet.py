"""Turn one sprite sheet (as Codex or a designer delivers it) into a motion folder.

    python -m meihua.companion.import_sheet 摇头.webp 摇头 --grid 2x5 --ms 90 --kind once

Cells are read row by row. Every frame is scaled by the same factor (the first
cell's melon becomes 330 px wide, like 待机) and placed so its feet sit on the
feet line (x 256, y 470): a sheet whose cells drift a few pixels still plays
without the figure sliding. A white or cream background is keyed out; a
transparent one is kept. The sheet is copied to assets/xiaogua/sheets/codex/,
the frames go to assets/xiaogua/<动作名>/, then motion_check runs on them.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from .motion_check import check
from .sprites import key_out

ART = Path(__file__).resolve().parents[1] / "assets" / "xiaogua"
CANVAS, FOOT_X, FOOT_Y, BODY_WIDTH, SOLID = 512, 256, 470, 330, 96
LIFTED = {"提起", "悬空", "落地", "登场", "欢呼"}


def _body_width(alpha: np.ndarray) -> int:
    solid = alpha >= SOLID
    ys = np.nonzero(solid.any(axis=1))[0]
    top, bottom = ys.min(), ys.max()
    band = solid[top + (bottom - top) // 3: top + 2 * (bottom - top) // 3]
    return int(max(np.ptp(np.nonzero(row)[0]) for row in band if row.any()))


def _feet(alpha: np.ndarray) -> tuple[float, int]:
    solid = alpha >= SOLID
    bottom = int(np.nonzero(solid.any(axis=1))[0].max())
    xs = np.nonzero(solid[max(0, bottom - 40): bottom + 1].any(axis=0))[0]
    return (xs.min() + xs.max()) / 2, bottom


def import_sheet(sheet: Path, name: str, rows: int, cols: int, frame_ms: int, kind: str,
                 playback: str = "forward", cells: list[int] | None = None) -> Path:
    image = Image.open(sheet).convert("RGBA")
    if np.asarray(image.getchannel("A"))[:6, :6].max() > 10:      # paper, not transparency
        image = key_out(image)
    width, height = image.size
    grid = [image.crop((round(c * width / cols), round(r * height / rows),
                        round((c + 1) * width / cols), round((r + 1) * height / rows)))
            for r in range(rows) for c in range(cols)]
    picked = [grid[i - 1] for i in (cells or range(1, len(grid) + 1))]
    picked = [p for p in picked if (np.asarray(p.getchannel("A")) >= SOLID).any()]   # empty cells
    scale = BODY_WIDTH / _body_width(np.asarray(picked[0].getchannel("A")))
    first_bottom = None
    out = ART / name
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.png"):
        old.unlink()
    for index, cell in enumerate(picked, 1):
        big = cell.resize((round(cell.width * scale), round(cell.height * scale)), Image.LANCZOS)
        feet_x, bottom = _feet(np.asarray(big.getchannel("A")))
        if first_bottom is None:
            first_bottom = bottom
        # Feet stay on the line; a jump (欢呼, 登场) keeps its height relative to the first cell.
        lift = bottom - first_bottom if name in LIFTED else 0
        canvas = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
        canvas.alpha_composite(big, (round(FOOT_X - feet_x), round(FOOT_Y - bottom + lift)))
        canvas.save(out / f"{index:02d}.png", optimize=True)
    keep = ART / "sheets" / "codex"
    keep.mkdir(parents=True, exist_ok=True)
    if sheet.resolve() != (keep / f"{name}{sheet.suffix}").resolve():
        shutil.copy(sheet, keep / f"{name}{sheet.suffix}")
    meta = {"frame_ms": frame_ms, "playback": playback, "kind": kind,
            "source": f"sheets/codex/{name}{sheet.suffix} ({rows}×{cols})"}
    (out / "motion.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("sheet", type=Path)
    parser.add_argument("name", help="动作名，例如 摇头")
    parser.add_argument("--grid", default="2x4", help="行x列，例如 2x5")
    parser.add_argument("--ms", type=int, default=90)
    parser.add_argument("--kind", choices=["once", "loop", "hold"], default="once")
    parser.add_argument("--playback", choices=["forward", "pingpong"], default="forward")
    parser.add_argument("--cells", help="只取这些格子（从 1 数，逗号分隔），默认全部")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    rows, cols = (int(v) for v in args.grid.lower().split("x"))
    cells = [int(v) for v in args.cells.split(",")] if args.cells else None
    folder = import_sheet(args.sheet, args.name, rows, cols, args.ms, args.kind, args.playback, cells)
    fails, warns = check(folder, args.kind)
    print(f"{folder}：{len(list(folder.glob('*.png')))} 帧，{'不通过' if fails else '通过'}")
    for line in fails:
        print("  FAIL", line)
    for line in warns:
        print("  WARN", line)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
