"""Record docs/images/demo.gif: 小瓜 used for real, captured frame by frame.

    python tools/record_demo.py            # needs a model key saved in the settings (豆包 by default)

The app runs off screen with its own throw-away data folder (your history and memory are not
touched). The script does what a person does: click 小瓜, type a question into the box over its
head (a 能不能 question, so 小瓜 casts), press Enter. The answer is the model's own, streamed into the bubble as it arrives. Each
frame is the pet window and the bubble window as Qt draws them, put on a plain desktop colour.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))                      # this repository's meihua, not another one
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["MEIHUA_HOME"] = tempfile.mkdtemp(prefix="xiaogua-demo-")

from PIL import Image  # noqa: E402
from PySide6.QtCore import QBuffer, QIODevice, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

QUESTION = "明天去面试能成吗"
OUT = ROOT / "docs" / "images" / "demo.gif"
FRAME_MS = 100
PET_AT, PET_SIZE = (470, 330), 170              # where 小瓜 sits on the 800×600 off-screen desktop
CROP = (150, 40, 800, 530)                      # the part of the desktop the GIF shows
SCALE = 0.78


def backdrop(size):
    """A quiet desktop: a soft vertical gradient."""
    w, h = size
    top, bottom = (236, 244, 238), (248, 245, 236)
    img = Image.new("RGB", (w, h))
    for y in range(h):
        t = y / max(h - 1, 1)
        img.paste(tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)), (0, y, w, y + 1))
    return img


def grab(widget) -> Image.Image | None:
    if not widget.isVisible():
        return None
    pixmap = widget.grab()
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    pixmap.save(buffer, "PNG")
    from io import BytesIO
    image = Image.open(BytesIO(bytes(buffer.data()))).convert("RGBA")
    if image.size != (widget.width(), widget.height()):          # high-DPI grab: back to window size
        image = image.resize((widget.width(), widget.height()), Image.LANCZOS)
    return image


def main() -> int:
    from meihua.companion import app as companion, config

    cfg = config.Config.load()
    cfg.zodiac, cfg.pet_size, cfg.greet_on_start = "羊", PET_SIZE, False
    cfg.save()
    qt = QApplication.instance() or QApplication([])
    # Off screen, Qt does not see the system fonts: load the Chinese UI font by hand.
    from PySide6.QtGui import QFont, QFontDatabase
    for name in ("msyh.ttc", "msyhbd.ttc", "seguiemj.ttf"):
        QFontDatabase.addApplicationFont(str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name))
    qt.setFont(QFont("Microsoft YaHei", 9))
    pet_app = companion.Companion(cfg)
    if pet_app.notice:
        print("没有可用的模型密钥：", pet_app.notice)
        return 1
    pet = pet_app.pet
    pet.show()
    pet.set_size(PET_SIZE)
    pet.move(*PET_AT)

    desk = backdrop((800, 600))
    frames: list[Image.Image] = []

    def capture():
        frame = desk.copy()
        for widget in (pet, pet.bubble):
            image = grab(widget)
            if image is not None:
                frame.paste(image, (widget.x(), widget.y()), image)
        frame = frame.crop(CROP)
        frames.append(frame.resize((round(frame.width * SCALE), round(frame.height * SCALE)), Image.LANCZOS))

    ticker = QTimer(interval=FRAME_MS)
    ticker.timeout.connect(capture)
    ticker.start()

    state = {"sent": False, "done_at": None}

    def type_question(i=0):
        if i < len(QUESTION):
            pet.bubble.input.insert(QUESTION[i])
            QTimer.singleShot(260, lambda: type_question(i + 1))
        else:
            QTimer.singleShot(600, send)

    def send():
        pet.bubble.send()
        state["sent"] = True

    def watch():
        if state["sent"] and not pet.busy and state["done_at"] is None:
            state["done_at"] = len(frames)
            QTimer.singleShot(5000, qt.quit)                   # let the answer be read
        if len(frames) * FRAME_MS > 60_000:                    # the model never answered: give up
            qt.quit()

    watcher = QTimer(interval=200)
    watcher.timeout.connect(watch)
    watcher.start()
    QTimer.singleShot(1200, pet.ask_in_bubble)                 # a click on 小瓜: the box over its head
    QTimer.singleShot(2400, type_question)
    qt.exec()
    ticker.stop()

    # Same frame in a row: one frame shown longer (a much smaller file).
    kept, durations = [], []
    for frame in frames:
        if kept and frame.tobytes() == kept[-1].tobytes():
            durations[-1] += FRAME_MS
        else:
            kept.append(frame)
            durations.append(FRAME_MS)
    palette = [f.convert("P", palette=Image.ADAPTIVE, colors=128) for f in kept]
    palette[0].save(OUT, save_all=True, append_images=palette[1:], duration=durations, loop=0, optimize=True)
    print(f"{OUT}  {len(kept)} 帧，{sum(durations) / 1000:.1f} 秒，{OUT.stat().st_size / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
