"""Make the pictures the README shows (docs/images/), from the app's own artwork and widgets.

    python tools/make_readme_media.py

- motions.gif   小瓜's motions side by side, each looping at its own speed, with its name
- hero.png      小瓜 on a desktop with a speech bubble
- chat-welcome.png / chat-talk.png   the chat window, rendered off screen with sample talk
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MEIHUA_HOME", str(Path(__file__).resolve().parents[1] / "packaging" / "build" / "readme-home"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

import meihua  # noqa: E402

ART = meihua.ROOT / "assets" / "xiaogua"
OUT = Path(__file__).resolve().parents[1] / "docs" / "images"
FONT = "C:/Windows/Fonts/msyh.ttc"
CREAM, INK, LEAF = (250, 248, 240), (47, 71, 55), (143, 174, 114)

SHOWN = [("待机", "发呆"), ("招手", "打招呼"), ("起卦", "起卦"), ("翻书", "翻黄历"), ("灵光一闪", "想到了"),
         ("点头", "点头"), ("被摸头", "被摸头"), ("欢呼", "开心"), ("犯困", "犯困"), ("睡着", "睡着")]


def frames_of(name: str, size: int) -> tuple[list[Image.Image], int, str]:
    folder = ART / name
    meta = json.loads((folder / "motion.json").read_text(encoding="utf-8"))
    frames = [Image.open(p).convert("RGBA").resize((size, size), Image.LANCZOS) for p in sorted(folder.glob("*.png"))]
    if meta.get("playback") == "pingpong" and len(frames) > 2:
        frames = frames + frames[-2:0:-1]
    return frames, int(meta.get("frame_ms", 90)), meta.get("kind", "loop")


def motions_gif(size: int = 120, columns: int = 5, tick: int = 80, seconds: float = 4.0) -> Path:
    font = ImageFont.truetype(FONT, 16)
    cells = [(frames_of(name, size), label) for name, label in SHOWN]
    rows = (len(cells) + columns - 1) // columns
    cell_h = size + 30
    images = []
    for step in range(int(seconds * 1000 / tick)):
        sheet = Image.new("RGB", (columns * size, rows * cell_h), CREAM)
        draw = ImageDraw.Draw(sheet)
        for index, ((frames, ms, _kind), label) in enumerate(cells):
            frame = frames[(step * tick // ms) % len(frames)]
            x, y = (index % columns) * size, (index // columns) * cell_h
            sheet.paste(frame, (x, y), frame)
            width = draw.textlength(label, font=font)
            draw.text((x + (size - width) / 2, y + size + 2), label, font=font, fill=INK)
        images.append(sheet.convert("P", palette=Image.ADAPTIVE, colors=96))
    out = OUT / "motions.gif"
    images[0].save(out, save_all=True, append_images=images[1:], duration=tick, loop=0, optimize=True)
    return out


def hero_png() -> Path:
    """小瓜 waving at the corner of a calm desktop, a bubble with today's line."""
    width, height = 1000, 460
    image = Image.new("RGB", (width, height), (233, 239, 226))
    draw = ImageDraw.Draw(image)
    for y in range(height):                                            # a soft wallpaper gradient
        t = y / height
        draw.line([(0, y), (width, y)], fill=(int(236 - 18 * t), int(242 - 12 * t), int(230 - 20 * t)))
    pet = Image.open(sorted((ART / "招手").glob("*.png"))[4]).convert("RGBA").resize((300, 300), Image.LANCZOS)
    image.paste(pet, (640, 150), pet)
    bubble_font = ImageFont.truetype(FONT, 24)
    lines = ["今天宜理发、出门见朋友，", "跟你属羊三合，往前推。", "傍晚五点到七点是好时辰～"]
    box = (250, 90, 640, 90 + 44 * len(lines) + 30)
    draw.rounded_rectangle(box, radius=26, fill=(255, 255, 255), outline=(220, 227, 203), width=2)
    draw.polygon([(610, box[3] - 30), (660, box[3] + 10), (585, box[3])], fill=(255, 255, 255))
    for i, line in enumerate(lines):
        draw.text((box[0] + 26, box[1] + 18 + 44 * i), line, font=bubble_font, fill=INK)
    title = ImageFont.truetype(FONT, 46)
    sub = ImageFont.truetype(FONT, 24)
    draw.text((50, 300), "每日一瓜", font=title, fill=INK)
    draw.text((52, 365), "住在桌面上的小西瓜 · 看黄历 · 问个事 · 记事提醒", font=sub, fill=(110, 130, 100))
    out = OUT / "hero.png"
    image.save(out, optimize=True)
    return out


def chat_pngs() -> list[Path]:
    from PySide6.QtWidgets import QApplication

    from PySide6.QtGui import QFont, QFontDatabase

    app = QApplication.instance() or QApplication([])
    QFontDatabase.addApplicationFont(FONT)            # off screen there is no system font list
    app.setFont(QFont("Microsoft YaHei", 9))
    from meihua.companion import app as companion
    from meihua.companion.chat import ChatPanel

    avatar = companion.load_avatar(96)[0][0]
    outs = []
    panel = ChatPanel(avatar, "Ctrl+Alt+X")
    panel.set_today("今天宜理发、出行、见朋友，忌开市、动土。跟你属羊三合，适合往前推，"
                    "酉时（傍晚五点到七点）好。")
    panel.set_stats("陪你第 12 天 · 聊过 8 段对话")
    panel.resize(400, 580)
    panel.show()
    app.processEvents()
    outs.append(OUT / "chat-welcome.png")
    panel.grab().save(str(outs[-1]))

    talk = ChatPanel(avatar, "Ctrl+Alt+X")
    talk.resize(400, 640)
    talk.show()
    for question, answer in (
            ("这周哪天适合搬家", "周日（10月11号）最合适，黄历宜入宅、移徙，跟你属羊也合，搬起来顺手。"),
            ("明天下午去面试能成吗", "能成，但得你主动推一把。\n\n对方占主动，待遇和岗位未必一下对上，"
                                  "别当场全盘答应，多问几句具体条件。下午三点到五点是好时辰，尽量压这个点到。"),
            ("十分钟后提醒我喝水", "好，10:47 叫你喝水。")):
        talk.add_mine(question)
        talk.add_reply(answer)
    talk.add_notice("到点啦：喝水（10:47）")
    for _ in range(5):
        app.processEvents()
    outs.append(OUT / "chat-talk.png")
    talk.grab().save(str(outs[-1]))
    return outs


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    print(motions_gif())
    print(hero_png())
    for path in chat_pngs():
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
