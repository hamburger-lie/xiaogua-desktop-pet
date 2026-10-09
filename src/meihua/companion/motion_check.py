"""Check a motion folder before it goes into assets/xiaogua (the rules are in ANIMATION_BRIEF.md).

    python -m meihua.companion.motion_check src/meihua/assets/xiaogua/点头
    python -m meihua.companion.motion_check path/to/新动作 --kind loop

FAIL = the app would show it wrong (wrong size, background not transparent, feet off the
line, the figure a different size). WARN = it would play but look worse (a frozen frame,
a seam in the loop, ghosting, a jump from the idle pose). Exit code 1 on any FAIL.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

CANVAS, FOOT_X, FOOT_Y = 512, 256, 470      # same as sprites.py
BODY_WIDTH = 330
SOLID = 96                                   # alpha at or above this is the figure
KINDS = {"loop": 6, "once": 6, "hold": 4}    # minimum frames
LIFTED = {"提起", "悬空", "落地", "登场", "欢呼"}   # may leave the feet line in the middle frames
HANGING = {"提起", "悬空"}                         # held up by the mouse: off the ground on purpose
IDLE = Path(__file__).resolve().parents[1] / "assets" / "xiaogua" / "待机" / "01.png"


def _alpha(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGBA").getchannel("A"), dtype=np.uint8)


def _feet(alpha: np.ndarray) -> int | None:
    rows = np.nonzero((alpha >= SOLID).any(axis=1))[0]
    return int(rows.max()) if rows.size else None


def _centre(alpha: np.ndarray) -> float | None:
    cols = np.nonzero((alpha >= SOLID).any(axis=0))[0]
    return float(cols.min() + cols.max()) / 2 if cols.size else None


def _body_width(alpha: np.ndarray) -> int:
    """The melon's width: the widest solid run in the band between the leaves and the feet."""
    solid = alpha[180:330] >= SOLID
    widths = [int(np.ptp(np.nonzero(r)[0])) + 1 for r in solid if r.any()]
    return int(np.median(sorted(widths)[-20:])) if widths else 0


def _difference(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.mean(np.abs((a >= SOLID).astype(np.int8) - (b >= SOLID).astype(np.int8))))


def check(folder: Path, kind: str | None = None) -> tuple[list[str], list[str]]:
    fails, warns = [], []
    name = folder.name
    frames = sorted(folder.glob("*.png"))
    if not frames:
        return [f"{folder} 里没有 PNG"], []
    expected = [f"{i:02d}.png" for i in range(1, len(frames) + 1)]
    if [f.name for f in frames] != expected:
        fails.append(f"帧要按 01.png、02.png……连续命名，现在是 {[f.name for f in frames][:6]}…")
    meta = folder / "motion.json"
    info = {}
    if not meta.is_file():
        fails.append("缺 motion.json（至少写 frame_ms）")
    else:
        try:
            info = json.loads(meta.read_text(encoding="utf-8"))
        except ValueError as error:
            fails.append(f"motion.json 不是合法 JSON：{error}")
        frame_ms = info.get("frame_ms")
        if not isinstance(frame_ms, int) or not 60 <= frame_ms <= 250:
            fails.append(f"frame_ms 要是 60～250 的整数，现在是 {frame_ms!r}")
        if info.get("playback", "forward") not in ("forward", "pingpong"):
            fails.append("playback 只能是 forward 或 pingpong")
    kind = kind or info.get("kind")
    if kind in KINDS and len(frames) < KINDS[kind]:
        warns.append(f"{kind} 动作建议至少 {KINDS[kind]} 帧，现在 {len(frames)} 帧")

    alphas = []
    for frame in frames:
        image = Image.open(frame)
        if image.size != (CANVAS, CANVAS) or image.mode != "RGBA":
            fails.append(f"{frame.name}：要 512×512 RGBA，现在是 {image.size} {image.mode}")
            continue
        if frame.stat().st_size > 400_000:
            warns.append(f"{frame.name}：{frame.stat().st_size // 1024} KB，太大（建议 300 KB 以内）")
        alpha = _alpha(frame)
        alphas.append((frame.name, alpha))
        border = np.concatenate([alpha[:6].ravel(), alpha[-6:].ravel(), alpha[:, :6].ravel(), alpha[:, -6:].ravel()])
        if border.max() > 10:
            fails.append(f"{frame.name}：画布边缘不透明，背景没抠干净（要真透明，不要白底、米黄底或棋盘格）")
        inside = alpha[(alpha > 0)]
        if inside.size and np.mean((inside > 20) & (inside < 200)) > 0.18:
            warns.append(f"{frame.name}：半透明像素偏多，可能有重影 / 运动模糊 / 两帧叠在一起")
    if not alphas:
        return fails, warns

    first, last = alphas[0][1], alphas[-1][1]
    if name in HANGING:                       # 提起 ends in the air, 悬空 is all in the air
        ends = (("第一帧", first),) if name == "提起" else ()
    else:
        ends = (("最后一帧", last),) if name in LIFTED else (("第一帧", first), ("最后一帧", last))
    for label, alpha in ends:                  # a lifted motion may start in the air, never end there
        feet = _feet(alpha)
        if feet is None or abs(feet - FOOT_Y) > 6:
            fails.append(f"{label}：脚底要落在 y={FOOT_Y}（±6），现在在 {feet}")
        centre = _centre(alpha)
        if centre is None or abs(centre - FOOT_X) > 24:
            fails.append(f"{label}：身体要水平居中在 x={FOOT_X} 附近，现在中心在 {centre}")
    sized, label = (last, "最后一帧") if name in LIFTED else (first, "第一帧")   # 登场 grows from small
    width = _body_width(sized)
    if abs(width - BODY_WIDTH) > 25:
        fails.append(f"{label}：瓜身宽约 {BODY_WIDTH}px（跟待机一样大），现在约 {width}px")
    if name not in LIFTED:
        for frame_name, alpha in alphas[1:-1]:
            feet = _feet(alpha)
            if feet is not None and abs(feet - FOOT_Y) > 10:
                warns.append(f"{frame_name}：脚底离开了 y={FOOT_Y}（现在 {feet}），整个身子在跳？")

    steps = [_difference(alphas[i][1], alphas[i + 1][1]) for i in range(len(alphas) - 1)]
    pixels = [np.asarray(Image.open(folder / n).convert("RGBA"), dtype=np.int16) for n, _ in alphas]
    for i in range(len(pixels) - 1):                  # the whole picture: a new face is a new frame
        if np.mean(np.abs(pixels[i] - pixels[i + 1])) < 0.15:
            warns.append(f"{alphas[i][0]} 和 {alphas[i + 1][0]} 几乎一样：卡帧，删掉重复帧")
    moving = [s for s in steps if s >= 0.0005]
    if moving and max(moving) > 4 * (sum(moving) / len(moving)) and max(moving) > 0.01:
        warns.append("有一处跳变特别大（关键帧间距不均匀），中间补一帧或调匀")
    if kind == "loop" and info.get("playback", "forward") == "forward" and moving:
        seam = _difference(last, first)
        if seam > 2.5 * (sum(moving) / len(moving)) and seam > 0.006:
            warns.append("循环接缝明显：最后一帧接不回第一帧（改成 pingpong，或让首尾相接）")
    if kind == "once" and IDLE.is_file() and name not in LIFTED:
        idle = _alpha(IDLE)
        for label, alpha in (("第一帧", first), ("最后一帧", last)):
            if _difference(alpha, idle) > 0.035:
                warns.append(f"{label}跟待机姿势差得多：切换时会跳一下（一次性动作要从待机姿势开始、回到待机姿势）")
    return fails, warns


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folders", nargs="+", type=Path)
    parser.add_argument("--kind", choices=list(KINDS), help="loop / once / hold（不写就看 motion.json 的 kind）")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    failed = False
    for folder in args.folders:
        fails, warns = check(folder, args.kind)
        print(f"== {folder.name}：{'不通过' if fails else '通过'}" + (f"（{len(warns)} 条提醒）" if warns else ""))
        for line in fails:
            print("  FAIL", line)
        for line in warns:
            print("  WARN", line)
        failed |= bool(fails)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
