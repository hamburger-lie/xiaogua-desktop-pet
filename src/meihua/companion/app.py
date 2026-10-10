#!/usr/bin/env python3
"""每日一瓜 desktop app: 小瓜 floating on the desktop, with a chat panel.

A frameless, always-on-top, transparent window showing 小瓜. Click 小瓜 to open the
chat (chat.py), which keeps the whole conversation. The hotkey (default Ctrl+Alt+X)
or the tray icon opens a small input box in the bubble over 小瓜's head instead;
while the chat is closed, 小瓜's work and answer show in that bubble.

Motions follow voice/xiaogua-motion-design.md. New artwork dropped into
assets/xiaogua/<动作名>/ as PNG frames is picked up on restart; until then each
motion falls back to the existing GIFs or is skipped.
"""

from __future__ import annotations

import argparse
import json
import sys
import math
import os
import threading
import time
from datetime import date, datetime

from PIL import Image, ImageChops, ImageDraw, ImageFilter
from PySide6.QtCore import QObject, QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QImage, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QMenu, QVBoxLayout, QWidget

import meihua

from .config import Config, history_dir, home
from . import life
from .memory import Memory
from .session import Session
from .trash import Trash

ASSETS = meihua.ROOT / "assets"
PET_SIZES = {"小": 150, "中": 220, "大": 300}   # logical window sizes offered in the menu
PET_SIZE = PET_SIZES["中"]   # default; the user's choice is remembered in config.json
PET_MIN, PET_MAX, PET_STEP = 100, 400, 20        # Ctrl + wheel range
ART_PX = 400                 # frames are kept at this size and scaled when painted, so
                             # the largest pet on a 125% screen is still sharp
CREAM, INK = QColor("#FAF8F0"), QColor("#2F4737")


# ---------------------------------------------------------------- artwork

def cut_out(frame: Image.Image, tolerance: int = 24) -> Image.Image:
    """Remove the cream paper background by flood-filling inward from the corners.

    Flooding from the edges (instead of keying one colour everywhere) keeps the
    cream-coloured cushion and highlights inside the figure intact.
    """
    rgb = frame.convert("RGB")
    marker = (255, 0, 255)
    width, height = rgb.size
    for corner in ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)):
        if rgb.getpixel(corner) != marker:
            ImageDraw.floodfill(rgb, corner, marker, thresh=tolerance)
    # A pixel is background exactly when it equals the marker in all three bands.
    difference = ImageChops.difference(rgb, Image.new("RGB", rgb.size, marker))
    alpha = ImageChops.lighter(ImageChops.lighter(*difference.split()[:2]), difference.split()[2])
    alpha = alpha.point(lambda value: 0 if value == 0 else 255)
    alpha = alpha.filter(ImageFilter.GaussianBlur(0.8))     # soften the cut edge
    out = frame.convert("RGBA")
    out.putalpha(alpha)
    return out


def to_pixmap(image: Image.Image, size: int) -> QPixmap:
    image = image.resize((size, size), Image.LANCZOS)
    data = image.tobytes("raw", "RGBA")
    qimage = QImage(data, image.width, image.height, QImage.Format_RGBA8888).copy()
    return QPixmap.fromImage(qimage)


def _gif_frames(path, size):
    gif = Image.open(path)
    frames = []
    for index in range(getattr(gif, "n_frames", 1)):
        gif.seek(index)
        frames.append((to_pixmap(cut_out(gif.copy()), size), max(gif.info.get("duration", 150), 60)))
    return frames


def _png_sequence(folder, size, frame_ms):
    """New artwork: transparent PNG frames, already cut out, played in name order.

    An optional motion.json in the folder sets this motion's own frame_ms
    (sleep breathes slower than a wave); companion/sprites.py writes it.
    """
    meta = folder / "motion.json"
    files = sorted(folder.glob("*.png"))
    # Decoded once per run: a new pet (or a test) reuses the pixmaps unless the folder changed.
    key = (str(folder), size, frame_ms, folder.stat().st_mtime_ns, len(files),
           meta.stat().st_mtime_ns if meta.is_file() else 0)
    if key not in _PNG_CACHE:
        info = json.loads(meta.read_text(encoding="utf-8")) if meta.is_file() else {}
        ms = info.get("frame_ms", frame_ms)
        frames = [(_png_pixmap(f, size), ms) for f in files]
        if info.get("playback") == "pingpong" and len(frames) > 2:
            frames += frames[-2:0:-1]            # 1 2 3 4 3 2 | 1 2 3 4 …: loops without a seam
        _PNG_CACHE[key] = frames
    return list(_PNG_CACHE[key])


_PNG_CACHE: dict[tuple, list] = {}


def _png_pixmap(path, size: int) -> QPixmap:
    """Qt decodes and smooth-scales the PNG itself: several times faster than going through PIL."""
    image = QImage(str(path))
    if image.isNull():                           # an odd PNG Qt cannot read: the slow way
        return to_pixmap(Image.open(path).convert("RGBA"), size)
    if image.width() != size or image.height() != size:
        image = image.scaled(size, size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    return QPixmap.fromImage(image)


def load_animation(name: str, size: int = ART_PX) -> list[tuple[QPixmap, int]]:
    return _gif_frames(ASSETS / "xiaogua" / name, size)


def load_avatar(size: int = ART_PX) -> list[tuple[QPixmap, int]]:
    return [(to_pixmap(_avatar_image(str(ASSETS)), size), 1000)]


_AVATARS: dict[str, Image.Image] = {}


def _avatar_image(assets: str) -> Image.Image:
    """The icon cut out once per run: cut_out's flood fill is slow (seconds), and it was paid on every start."""
    if assets not in _AVATARS:
        icon = os.path.join(assets, "xiaogua-icon.png")
        done = os.path.join(assets, "xiaogua-icon.cut.png")      # kept next to the icon after the first run
        if os.path.isfile(done) and os.path.getmtime(done) >= os.path.getmtime(icon):
            _AVATARS[assets] = Image.open(done).convert("RGBA")
        else:
            _AVATARS[assets] = cut_out(Image.open(icon))
            try:
                _AVATARS[assets].save(done)
            except OSError:
                pass                                              # read-only install: cut it each run
    return _AVATARS[assets]


# Motion states (voice/xiaogua-motion-design.md). Each state tries its sources in
# order: a PNG-sequence folder of new artwork, then an existing GIF standing in
# for it, then the static avatar. A state with no source at all is skipped.
# kind: loop repeats; once plays through then hands over; hold stops on the last frame.
MOTIONS = {
    "待机": ("loop", ["待机", "小瓜_摸鱼.gif"]),
    "睡着": ("loop", ["睡着", "小瓜_摸鱼.gif"]),
    "提起": ("once", ["提起"]),
    "悬空": ("loop", ["悬空"]),
    "落地": ("once", ["落地"]),
    "思考入": ("once", ["思考入"]),
    "思考": ("loop", ["思考", "翻书", "小瓜_思考.gif"]),
    "思考出": ("once", ["思考出"]),
    "翻书": ("loop", ["翻书", "小瓜_思考.gif"]),
    "起卦": ("once", ["起卦"]),
    "招手": ("once", ["招手"]),
    "灵光一闪": ("once", ["灵光一闪"]),
    "摇头": ("once", ["摇头"]),
    "点头": ("once", ["点头"]),
    "加油": ("once", ["加油"]),
    "歪头": ("hold", ["歪头"]),
    # Waiting for artwork (ANIMATION_BRIEF.md). Missing ones are skipped or fall back.
    "说话": ("loop", ["说话"]),               # while the answer arrives (else a code-made bounce)
    "被摸头": ("once", ["被摸头"]),           # patted on the head (else 歪头 then 点头)
    "入睡": ("once", ["入睡"]),               # 待机 -> 睡着
    "起床": ("once", ["起床"]),               # 睡着 -> 待机
    "犯困": ("loop", ["犯困"]),               # late at night, idle
    "登场": ("once", ["登场"]),               # on start (else 招手)
    "欢呼": ("once", ["欢呼", "加油"]),       # good news
    "头像": ("hold", ["@avatar"]),
}
FRAME_MS = 90                 # about 11 fps for PNG sequences

# Drawn keys are few; a gentle procedural motion on top, redrawn at ~30 fps, keeps
# 小瓜 alive between them: (period in s, squash-and-stretch amount, float amount).
AMBIENT = {
    "待机": (3.2, 0.018, 0.0),
    "睡着": (4.8, 0.024, 0.0),
    "思考": (2.6, 0.010, 0.0),
    "翻书": (3.0, 0.010, 0.0),
    "悬空": (1.5, 0.008, 0.0),
}
SWING_STATES = ("提起", "悬空", "落地")   # drawn turned by the live swing while it is not zero
SWING_MAX = 22.0                          # degrees
FOOT_RATIO = 470 / 512        # feet line in every frame (sprites.py anchors them there)
AMBIENT_MS = 33

# What 小瓜 does while the answer is being worked out, by the tool being run.
STEP_MOTIONS = {
    "cast_now": "起卦", "lookup_hexagrams": "翻书", "validate_reading": "思考",
    "almanac_day": "翻书", "almanac_pick_days": "翻书", "daily_reading": "起卦",
}
BUSY_LOOP = "思考"            # between steps, and after a one-shot step motion
HOLD_MS = 1600                # a held pose (歪头) lasts this long when something is queued after it
REMIND_MS = 20_000            # how often 小瓜 looks for a reminder whose minute has come
REMIND_FIRST_MS = 5_000       # … and the first look after starting (one missed while closed)
REMIND_BUBBLE_S = 30          # a reminder stays up this long
VOICE_KEYS_UP_MS = 2000       # 按键说话 waits at most this long for Ctrl/Alt to be let go

# The answer's mood tag (agent.MOODS) -> what 小瓜 does once the answer is in.
MOOD_MOTIONS = {"开心": "点头", "加油": "加油", "担心": "摇头", "犹豫": "歪头", "平静": None}


def load_motions(size: int = ART_PX, skin: str | None = None) -> dict:
    """state -> (kind, frames or None, which source was used)."""
    motions = {}
    folders = ([ASSETS / skin] if skin else []) + [ASSETS / "xiaogua"]
    for state, (kind, sources) in MOTIONS.items():
        frames, used = None, None
        for folder, source in ((f, src) for src in sources for f in folders):
            path = folder / source
            if source == "@avatar":
                frames, used = load_avatar(size), source
            elif path.is_dir() and any(path.glob("*.png")):
                frames, used = _png_sequence(path, size, FRAME_MS), (
                    source if folder.name == "xiaogua" else f"{folder.name}/{source}")
            elif source.endswith(".gif") and path.is_file():
                frames, used = _gif_frames(path, size), source
            if frames:
                break
        motions[state] = (kind, frames, used)
    return motions


# ---------------------------------------------------------------- agents

class OfflineAgent:
    """No model connected yet: today's 黄历, and the local cast for a 能不能 question."""

    session = None          # set by the pet

    def ask(self, text, on_step=None, **_):
        from .agent import Reply
        from .harness import YES_NO
        from .session import daily_context_text
        from .tools import cast_now

        if YES_NO.search(text or ""):
            cast = cast_now(text)
            line = f"本卦{cast['primary']['name']}，互卦{cast['mutual']['name']}"
            if cast.get("changed"):
                line += (f"，变卦{cast['changed']['name']}。你是{cast['body']['name']}{cast['body']['element']}，"
                         f"所问的事是{cast['use']['name']}{cast['use']['element']}，{cast['body_use_relation']}。")
            answer = (f"离线起卦：{line}\n\n还没接上模型，只能先给你盘面。右键小瓜 → 设置… → 连接，"
                      "选好厂商、填上密钥，小瓜就能按你的事细讲。")
            calls = [{"tool": "cast_now", "status": cast["status"]}]
        else:
            zodiac = self.session.zodiac if self.session is not None else None
            facts = daily_context_text(zodiac).replace("【今天】", "").replace("【用户】", "")
            lines = [line for line in facts.splitlines() if "remember_zodiac" not in line]
            if not zodiac:
                lines.append("属相还没设：右键小瓜 → 设置… → 小瓜本体，选上属相，就能看今天跟你合不合。")
            answer = "离线黄历：" + "\n".join(lines) + "\n\n接上模型后，小瓜能按你的事细讲、帮你挑日子。"
            calls = [{"tool": "almanac_day", "status": "OK"}]
        if self.session is not None:
            self.session.record_daily_turn(text, "（离线）")
        return Reply(answer, True, calls)


def explain_error(error: Exception) -> str:
    """A failed question in plain Chinese first; the vendor's own words below, small."""
    from .openai_compat import explain

    status = getattr(error, "status_code", None)
    detail = getattr(error, "message", None) or str(error)
    if status is not None:
        advice = explain(status, detail)
    elif "connect" in type(error).__name__.lower() or "timeout" in type(error).__name__.lower():
        advice = "连不上模型厂商，检查一下网络或代理。"
    else:
        advice = "出了点意外。"
    return f"小瓜这次没问成：**{advice}**\n\n*厂商原话：{detail[:300]}*"


MINI_SIZE = 64                # 贴边小球: the pet shrunk to a round head at the screen edge


class Bridge(QObject):
    """Carries results from worker / hotkey threads back to the Qt thread.

    Worker signals carry the turn number: after 停止 or 撤回 a new question may start
    while the old worker is still finishing, and its late output must not leak in.
    """
    replied = Signal(int, object)
    step = Signal(int, str)     # the agent is about to run this tool
    zodiac = Signal(str)        # the user told 小瓜 their 属相 in the chat
    memory = Signal()           # a fact was remembered, dropped or closed
    delta = Signal(int, str)    # streamed answer text
    discard = Signal(int)       # the streamed text was not the answer after all
    hotkey = Signal()
    voice = Signal()            # the 按键说话 hotkey


# ---------------------------------------------------------------- bubble

BUBBLE_WIDTH = 300            # an answer's bubble; short notices keep to NOTE_WIDTH
NOTE_WIDTH = 260
BUBBLE_CHARS = 260            # longer answers are cut in the bubble; the chat panel has them whole
BUBBLE_STREAM_MS = 120        # the streamed answer is redrawn at most this often
ASK_IDLE_S = 60               # an input box left empty this long goes away
ASK_AWAY_S = 10               # … or this long once the user is in another window


def bubble_text(text: str, limit: int = BUBBLE_CHARS) -> str:
    """An answer short enough for the bubble: cut at the last sentence end before `limit`."""
    text = text.strip()
    if len(text) <= limit:
        return text
    head = text[:limit]
    cut = max(head.rfind(mark) for mark in "。！？；\n")
    head = head[:cut + 1] if cut > limit // 2 else head
    return head.rstrip() + "……\n\n*（点我看完整回答）*"


def answer_seconds(text: str) -> int:
    """How long an answer stays over 小瓜's head: time to read it, 12 s to a minute."""
    return max(12, min(60, len(text) // 5))


class Bubble(QWidget):
    """The speech bubble above 小瓜.

    Short notices (greeting, a reminder, 'I'm here'), and talking without the chat panel:
    `ask` turns it into a little input box, `thinking` shows what 小瓜 is doing, `stream`
    and `answer` show the reply. Clicking a notice or an answer opens the chat panel,
    which has the whole conversation.
    """
    asked = Signal(str)          # the user typed a question into the bubble

    def __init__(self, on_click=None):
        from PySide6.QtWidgets import QLineEdit

        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.on_click = on_click
        self.mode = "note"                               # note / ask / thinking / answer
        self.setAttribute(Qt.WA_TranslucentBackground)
        font = "font-family: 'Microsoft YaHei';"
        self.label = QLabel(self)
        self.label.setWordWrap(True)
        self.label.setTextFormat(Qt.MarkdownText)
        self.label.setStyleSheet(f"color: {INK.name()}; {font} font-size: 13px; background: transparent;")
        self.label.setMaximumWidth(NOTE_WIDTH)
        self.input = QLineEdit(self)
        self.input.setPlaceholderText("问小瓜…")
        self.input.setMinimumWidth(240)
        self.input.setStyleSheet(f"QLineEdit {{ {font} font-size: 13px; color: {INK.name()}; background: #FFFFFF;"
                                 " border: 1px solid #C9D3B5; border-radius: 12px; padding: 5px 10px; }"
                                 " QLineEdit:focus { border-color: #8FAE72; }")
        self.input.returnPressed.connect(self.send)
        self.input.installEventFilter(self)
        self.input.hide()
        self.footer = QLabel(self)
        self.footer.setStyleSheet(f"color: #8C9687; {font} font-size: 11px; background: transparent;")
        self.footer.hide()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 18)        # bottom: room for the tail
        layout.setSpacing(6)
        layout.addWidget(self.label)
        layout.addWidget(self.input)
        layout.addWidget(self.footer)
        self.hide_timer = QTimer(self, singleShot=True)
        self.hide_timer.timeout.connect(self.hide)
        self._paused = False                             # the mouse is on it: the hide timer waits
        self.hearing = False                             # 按键说话 is writing into the input box
        self.input.textEdited.connect(self._typed)
        self._stream = ""
        self._stream_timer = QTimer(self, singleShot=True, interval=BUBBLE_STREAM_MS)
        self._stream_timer.timeout.connect(self._show_stream)
        self._pet_geometry = None

    @property
    def asking(self) -> bool:
        return self.isVisible() and self.mode == "ask"

    @property
    def following_answer(self) -> bool:
        """Showing 小瓜 at work or its reply (not a notice, not the input box)."""
        return self.isVisible() and self.mode in ("thinking", "answer")

    # kept for callers and tests that read the bubble's text
    @property
    def view(self):
        return self

    def toPlainText(self) -> str:
        return self.label.text()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        body = QRectF(self.rect()).adjusted(1, 1, -1, -9)
        path = QPainterPath()
        path.addRoundedRect(body, 14, 14)
        tail = QPainterPath()
        x = body.right() - 36
        tail.moveTo(x, body.bottom() - 1)
        tail.lineTo(x + 14, body.bottom() - 1)
        tail.lineTo(x + 18, body.bottom() + 8)
        tail.closeSubpath()
        path = path.united(tail)
        painter.fillPath(path, CREAM)
        painter.setPen(QColor("#C9D3B5"))
        painter.drawPath(path)

    def follow(self, pet_geometry):
        """Stay above 小瓜 while it is dragged: same text, same time left."""
        from .chat import screen_rect_for

        area = screen_rect_for(pet_geometry.center())
        x = pet_geometry.center().x() - self.width() + 40
        y = pet_geometry.top() - self.height() + 6
        self.move(max(area.left() + 4, min(x, area.right() - self.width() - 4)), max(area.top() + 4, y))

    def _show(self, mode: str, text: str, pet_geometry, seconds: int | None, footer: str = "",
              width: int = NOTE_WIDTH):
        """Lay the bubble out for `mode` above 小瓜. `seconds` None: stays until told otherwise."""
        self.mode = mode
        self._stream_timer.stop()
        self._pet_geometry = pet_geometry
        self.label.setMaximumWidth(width)
        self._set_label(text)
        self.input.setVisible(mode == "ask")
        self.footer.setText(footer)
        self.footer.setVisible(bool(footer))
        self.adjustSize()
        self.follow(pet_geometry)
        self.show()
        self.raise_()
        if seconds is None:
            self.hide_timer.stop()
        else:
            self.hide_timer.start(seconds * 1000)

    def say(self, text: str, pet_geometry, seconds: int = 8):
        """A short notice; it goes away by itself."""
        self._show("note", text, pet_geometry, seconds)

    def ask(self, pet_geometry, text: str = ""):
        """Turn into a small input box (with an optional line above it, like today's 黄历)."""
        from .chat import bring_to_front

        self.input.clear()
        self.listening(False)
        self._show("ask", text, pet_geometry, ASK_IDLE_S, "Enter 发送 · Esc 收起 · 单击小瓜看完整对话",
                   width=BUBBLE_WIDTH)
        bring_to_front(self)
        self.input.setFocus()

    def _typed(self, text: str):
        """Something typed: the box stays; emptied again: it goes after a quiet minute."""
        if self.mode == "ask":
            if text.strip() or self.hearing:
                self.hide_timer.stop()
            else:
                self.hide_timer.start(ASK_IDLE_S * 1000)

    def _set_label(self, text: str):
        # A wrapped QLabel guesses a narrow width: give it the room it needs, up to its maximum.
        longest = max((self.label.fontMetrics().horizontalAdvance(line) for line in text.splitlines()), default=0)
        self.label.setMinimumWidth(min(self.label.maximumWidth(), longest + 4))
        self.label.setText(text)
        self.label.setVisible(bool(text))

    def set_line(self, text: str):
        """Change the text above the input box (or the notice) without touching what is typed."""
        self._set_label(text)
        self.adjustSize()
        if self._pet_geometry is not None:
            self.follow(self._pet_geometry)

    def listening(self, on: bool):
        """按键说话 into the bubble: Windows voice typing writes into the input box."""
        self.hearing = on
        self.input.setPlaceholderText("在听……说完再按一次快捷键就发出去" if on else "问小瓜…")
        if on:
            self.hide_timer.stop()

    def thinking(self, text: str, pet_geometry):
        self._show("thinking", text, pet_geometry, None, width=BUBBLE_WIDTH)

    def stream(self, text: str, pet_geometry):
        """The answer as it arrives (redrawn a few times a second, not on every token)."""
        self._stream, self._pet_geometry = text, pet_geometry
        if not self._stream_timer.isActive():
            self._stream_timer.start()

    def _show_stream(self):
        from .chat import shown_answer

        shown = shown_answer(self._stream)
        if shown and self.mode in ("thinking", "answer") and self.isVisible():
            self._show("answer", bubble_text(shown), self._pet_geometry, None, width=BUBBLE_WIDTH)

    def answer(self, text: str, pet_geometry):
        self._show("answer", bubble_text(text), pet_geometry, answer_seconds(text), "点我看完整对话",
                   width=BUBBLE_WIDTH)

    def send(self):
        text = self.input.text().strip()
        if not text:
            self.input.setPlaceholderText("先写一句想问的～")
            return
        self.input.clear()
        self.input.setPlaceholderText("问小瓜…")
        self.asked.emit(text)

    def eventFilter(self, watched, event):
        if watched is self.input and event.type() == event.Type.KeyPress and event.key() == Qt.Key_Escape:
            self.hide()
            return True
        return super().eventFilter(watched, event)

    def changeEvent(self, event):
        """Gone to another window with the input box still empty: it goes after ASK_AWAY_S, not at
        once. Another program grabbing the focus right after the hotkey must not make the box
        vanish (it would look as if the key did nothing). Coming back to it keeps it."""
        super().changeEvent(event)
        if event.type() != event.Type.ActivationChange or self.mode != "ask" or not self.isVisible():
            return
        if self.isActiveWindow() or self.hearing or self.input.text().strip():
            self._typed(self.input.text())
        else:
            self.hide_timer.start(ASK_AWAY_S * 1000)

    def enterEvent(self, _event):
        """A notice or an answer being read: it stays."""
        if self.mode in ("note", "answer") and self.hide_timer.isActive():
            self.hide_timer.stop()
            self._paused = True

    def leaveEvent(self, _event):
        if self._paused:
            self._paused = False
            if self.mode in ("note", "answer"):
                self.hide_timer.start(5000)

    def hideEvent(self, event):
        super().hideEvent(event)
        self._stream_timer.stop()
        self.hide_timer.stop()
        self._paused = False

    # old name, same behaviour
    def show_text(self, text: str, anchor=None, seconds: int = 8):
        pet = anchor if hasattr(anchor, "center") else None
        if pet is None:
            from PySide6.QtCore import QRect
            point = anchor if isinstance(anchor, QPoint) else QPoint(0, 0)
            pet = QRect(point, point)
        self.say(text, pet, seconds)

    def mousePressEvent(self, _event):
        if self.mode == "ask":                           # a click beside the input box: keep typing
            self.input.setFocus()
            return
        self.hide()
        if self.on_click:
            self.on_click()


# ------------------------------------------------------------------- pet

class Pet(QWidget):
    zodiac_changed = Signal(str)          # learnt in the chat; the settings window follows
    memory_changed = Signal()             # 设置 → 记忆 follows
    mini_changed = Signal(bool)           # 贴边小球 switched; the tray and the settings follow
    reminded = Signal(str)                # a reminder was given: the tray tells it when 小瓜 cannot be seen
    trash_changed = Signal()              # something went into the trash or came back; 设置 → 回收站 follows

    def __init__(self, agent, hotkey_label: str, config: Config | None = None):
        from .chat import ChatPanel

        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.agent, self.hotkey_label = agent, hotkey_label
        self.config = config or Config.load()
        self.open_settings = None           # set by the app: the right-click "设置…" entry
        self.motions = load_motions()
        # The frame is painted scaled to the window's *current* size. A fixed-size
        # pixmap in a QLabel got cropped when the window moved to a monitor with a
        # different scale factor (window 120px, pixmap 150px on a 125%/100% pair).
        self.pixmap: QPixmap | None = None
        size = max(PET_MIN, min(PET_MAX, self.config.pet_size))
        self.resize(size, size)
        self.bubble = Bubble(on_click=self.open_chat)
        self.bubble.asked.connect(self._ask_from_bubble)
        self.bubble.input.textEdited.connect(lambda text: text.strip() and self._on_typing())
        self._bubble_draft, self._bubble_step = "", "小瓜在想"     # the answer as the bubble shows it
        self.chat = ChatPanel(load_avatar(96)[0][0], hotkey_label)
        self.chat.submitted.connect(self._submit)
        self.chat.clear_requested.connect(self._forget)
        self.chat.settings_requested.connect(lambda: self.open_settings and self.open_settings())
        # The conversation's state: the open conversation, today's 黄历, what 小瓜 remembers.
        self.session = Session(history_dir() if self.config.keep_history else None)
        self.session.zodiac = self.config.zodiac or None
        if not self.config.first_day:                              # 陪你第 N 天 counts from here
            self.config.first_day = date.today().isoformat()
            self.config.save()
        self.session.first_day = date.fromisoformat(self.config.first_day)
        self.session.memory = Memory(home() / "memory.json")      # 小瓜记得的你, across days
        self.trash = Trash(home() / "trash")                       # 回收站: deleted conversations and facts
        self.session.trash = self.session.memory.trash = self.trash
        self.chat.restore(self.session.chat.messages)
        self.bridge = Bridge()
        self.session.on_zodiac = self.bridge.zodiac.emit             # called from the worker thread
        self.bridge.zodiac.connect(self._on_zodiac)
        self.session.on_memory = self.bridge.memory.emit
        self.bridge.memory.connect(self._on_memory)
        self._refresh_welcome()
        self._turn, self._cancel, self._question_id = 0, None, None
        self.bridge.replied.connect(lambda turn, reply: turn == self._turn and self._on_reply(reply))
        self.bridge.step.connect(lambda turn, name: turn == self._turn and self._on_worker_step(name))
        self.bridge.delta.connect(lambda turn, text: turn == self._turn and self._on_worker_delta(text))
        self.bridge.discard.connect(lambda turn: turn == self._turn and self._on_worker_discard())
        self.chat.user_typing.connect(self._on_typing)
        self.chat.stop_requested.connect(self.stop_answer)
        self.chat.recall_requested.connect(self._recall)
        self.chat.delete_requested.connect(self._delete)
        self.chat.retry_requested.connect(self._retry)
        self.chat.feedback_requested.connect(self._feedback)
        self.chat.preferred_size = tuple(self.config.chat_size) if self.config.chat_size else None
        self.chat.resized.connect(self._chat_resized)
        self.chat.chats_requested.connect(
            lambda: self.chat.show_chat_list(self.session.list_chats(), self.session.chat.id))
        self.chat.chat_picked.connect(self._switch_chat)
        self.chat.chat_deleted.connect(self._delete_chat)
        self.chat.new_chat_requested.connect(self._new_chat)
        self.bridge.hotkey.connect(self.hotkey_pressed)
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)      # coarse timers jitter by ~16 ms on Windows
        self.timer.timeout.connect(self._next_frame)
        self.ambient = QTimer(self, interval=AMBIENT_MS)
        self.ambient.setTimerType(Qt.PreciseTimer)
        self.ambient.timeout.connect(self._tick)
        self._swing, self._swing_speed, self._swing_target = 0.0, 0.0, 0.0
        self._last_drag = None                                      # (time, global x) of the last drag move
        self.listen_timer = QTimer(self, singleShot=True, interval=3500)
        self.listen_timer.timeout.connect(self._stop_listening)
        self._dragging = False
        self._answer_started = False
        self.idle_timer = QTimer(self, singleShot=True)
        self.idle_timer.timeout.connect(self._settle)
        self.sleep_timer = QTimer(self, singleShot=True)
        self.sleep_timer.timeout.connect(self._fall_asleep)
        self.fidget_timer = QTimer(self, singleShot=True)          # idle fidgets (VPet / DyberPet)
        self.fidget_timer.timeout.connect(self._fidget)
        self.remind_timer = QTimer(self, interval=REMIND_MS)        # 到点提醒 (memory.py: a plan with a time)
        self.remind_timer.timeout.connect(self.check_reminders)
        self.remind_timer.start()
        self.pats = life.PatDetector()
        self.setMouseTracking(True)                                 # patting needs moves without a button
        self._talking_until = 0.0                                   # the answer is arriving: talk bounce
        self._night_greeted = ""
        self._listening = False                                     # 按键说话 in progress
        self._voice_in_bubble = False                               # … into the bubble, not the panel
        self._attention_until = 0.0                                 # mini ball: a reply is waiting
        self.bridge.voice.connect(self.voice_toggle)
        self.busy = False
        self._drag = None
        self._press = None
        self.state, self.frame, self.queue = "待机", 0, []
        self.apply_config(self.config)
        if self.config.mini:
            self.set_mini(True, save=False)
        self.play("登场" if self.has("登场") else "招手", "待机")

    def apply_config(self, config: Config):
        """Apply look-and-behaviour settings live (the settings window calls this)."""
        self.config = config
        if config.pet_size != self.width():
            self.set_size(config.pet_size)
        self.setWindowOpacity(max(20, min(100, config.opacity)) / 100)
        flags = Qt.FramelessWindowHint | Qt.Tool
        if config.always_on_top:
            flags |= Qt.WindowStaysOnTopHint
        if config.click_through:
            flags |= Qt.WindowTransparentForInput
        if self.windowFlags() != flags:
            visible = self.isVisible()
            self.setWindowFlags(flags)          # hides the window; show it again
            if visible:
                self.show()
        if hasattr(self, "session"):                  # history switched on/off takes effect now
            self.session.set_folder(history_dir() if config.keep_history else None)
            if (config.zodiac or None) != self.session.zodiac:
                self.session.zodiac = config.zodiac or None
                self._refresh_welcome()
        self.sleep_ms = max(1, config.sleep_minutes) * 60_000
        self.idle_ms = max(3, config.bubble_seconds) * 1000
        self.chat.set_hotkey_label(self.hotkey_label)
        self.setToolTip(f"小瓜 · 单击聊天，{self.hotkey_label} 随时叫我，右键更多")

    # animation ------------------------------------------------------------
    def play(self, state: str, *then: str):
        """Show `state`; a one-shot state hands over to `then` (default 待机) when done."""
        _, frames, _ = self.motions[state]
        if not frames:                      # no artwork for this state yet: skip it
            if then:
                self.play(*then)
            return
        self.state, self.frame, self.queue = state, 0, list(then)
        if state == "待机":
            night = life.is_night()
            self.sleep_timer.start(min(self.sleep_ms, life.NIGHT_SLEEP_MS) if night else self.sleep_ms)
            if not night or self.has("犯困"):
                self.fidget_timer.start(life.fidget_delay())
            else:
                self.fidget_timer.stop()
        else:
            self.sleep_timer.stop()
            self.fidget_timer.stop()
        if state in AMBIENT or state in SWING_STATES:
            if not self.ambient.isActive():
                self.ambient.start()
        else:
            self.ambient.stop()
            self._swing = self._swing_speed = self._swing_target = 0.0
        self._next_frame()

    def _sway(self) -> float:
        """The small idle swing while hanging still."""
        return 2.2 * math.sin(2 * math.pi * time.monotonic() / 1.7) if self.state == "悬空" else 0.0

    def _tick(self):
        """~30 times a second: the hanging swing (a damped spring) and a repaint."""
        if self.state in SWING_STATES or self._swing:
            dt = AMBIENT_MS / 1000
            target = 0.0 if self.state == "落地" else self._swing_target
            stiffness, damping = (90.0, 16.0) if self.state == "落地" else (55.0, 6.5)
            acceleration = stiffness * (target - self._swing) - damping * self._swing_speed
            self._swing_speed += acceleration * dt
            self._swing = max(-SWING_MAX, min(SWING_MAX, self._swing + self._swing_speed * dt))
            self._swing_target *= 0.86                # the push fades once the mouse stops
            if self.state not in SWING_STATES and abs(self._swing) < 0.05 and abs(self._swing_speed) < 0.5:
                self._swing = self._swing_speed = 0.0
        self.update()

    def _next_frame(self):
        kind, frames, _ = self.motions[self.state]
        if self.frame >= len(frames):
            if kind == "loop":
                self.frame = 0
            elif kind == "once":
                self.play(*(self.queue or ["待机"]))
                return
            else:                            # hold: stay on the last frame
                self.timer.stop()
                if self.queue:                   # …for a moment, when something is queued after it
                    state, then = self.state, list(self.queue)
                    QTimer.singleShot(HOLD_MS, lambda: self.state == state and self.queue == then
                                      and not self._dragging and self.play(*then))
                return
        self.pixmap, duration = frames[self.frame]
        self.update()
        self.frame += 1
        if len(frames) > 1 or kind == "once":
            self.timer.start(duration)
        else:
            self.timer.stop()

    def _settle(self):
        """「回答后多久回到待机」: only from a reaction, never mid-drag, mid-answer, asleep or listening."""
        if self._dragging or self.busy or self.state in ("待机", "睡着", "犯困") or self.listen_timer.isActive():
            return
        self.play("待机")

    def has(self, state: str) -> bool:
        """Is there artwork for this motion (its own, or a fallback)?"""
        return bool(self.motions.get(state, (None, None, None))[1])

    def _fall_asleep(self):
        if self.state == "待机" and not self.busy:
            self.play("入睡", "睡着")

    def _fidget(self):
        """Now and then, while idle: a nod, a tilt of the head, a little wave."""
        if self.state != "待机" or self.busy or self._dragging:
            return
        available = {name for name, (_, frames, _) in self.motions.items() if frames}
        action = life.pick_fidget(available)
        if life.is_night() and self.has("犯困"):
            self.play("犯困")                      # a yawn or two, then back to idle
            QTimer.singleShot(4000, lambda: self.state == "犯困" and not self.busy and self.play("待机"))
            return
        if action == "歪头":
            self.play("歪头")
            QTimer.singleShot(1800, lambda: self.state == "歪头" and not self.busy and not self._dragging
                              and not self.listen_timer.isActive() and self.play("待机"))
        elif action:
            self.play(action, "待机")

    def _wake(self):
        if self.state == "睡着":
            self.play("起床", "待机")
            today = datetime.now().date().isoformat()
            if (life.is_night() and self._night_greeted != today and not self.chat.isVisible()
                    and life.allows(self.config.proactive, "night")):
                self._night_greeted = today
                self._say("这么晚还不睡呀……我陪你一会儿。", 6)
                return
        if not self.chat.isVisible():
            self.greet_today(bubble=self.config.greet_on_start)       # back after midnight

    # the morning line -------------------------------------------------------
    def greet_today(self, bubble: bool = True) -> bool:
        """Once a day: today's 黄历 for the user's 属相, a plan for today, or how a past one went.

        Made by code (no model, no wait); shown in a bubble and on the chat's welcome.
        """
        today = datetime.now().date().isoformat()
        if self.config.last_greet == today:
            return False
        self.config.last_greet = today
        self.config.save()
        text = self.session.greeting()
        self.chat.set_today(text)
        kind = getattr(self.session, "greeting_kind", "morning")
        if bubble and self.isVisible() and life.allows(self.config.proactive, kind):
            self._say(text, 15)
        return True

    def _refresh_welcome(self):
        self.chat.set_today(self.session.greeting(mark=False))
        self._refresh_stats()

    def _refresh_stats(self):
        """陪你第 N 天 · 聊过 N 段对话."""
        self.chat.set_stats(self.session.together_text())

    def _on_memory(self):
        self._refresh_welcome()
        self.memory_changed.emit()

    def paintEvent(self, _event):
        if self.config.mini:
            self._paint_mini()
            return
        if self.pixmap is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        width, height = self.width(), self.height()
        talking = time.monotonic() < self._talking_until
        swinging = self.state in SWING_STATES or abs(self._swing) > 0.05
        if swinging:
            # Hanging from where it is held: turn around that point (never below the middle,
            # or it would swing like a stick standing on its end). A small idle sway on top.
            held = self._drag or getattr(self, "_swing_pivot", None) or QPoint(width // 2, height // 4)
            pivot_x, pivot_y = held.x(), min(held.y(), height * 0.45)
            sway = self._sway()
            painter.translate(pivot_x, pivot_y)
            painter.rotate(self._swing + sway)
            painter.translate(-pivot_x, -pivot_y)
        if self.state not in AMBIENT and not talking:
            painter.drawPixmap(self.rect(), self.pixmap)
            return
        # Breathe around the feet: taller-and-narrower, then back; hover floats as well.
        # While the answer is arriving, a quick small bounce stands in for a 说话 animation.
        period, stretch, float_amount = AMBIENT.get(self.state, (3.0, 0.0, 0.0))
        if talking:
            period, stretch = 0.34, max(stretch, 0.03)
        phase = math.sin(2 * math.pi * time.monotonic() / period)
        scale_y, scale_x = 1 + stretch * phase, 1 - stretch * 0.45 * phase
        w, h = width * scale_x, height * scale_y
        x = (width - w) / 2
        y = height * FOOT_RATIO - h * FOOT_RATIO - float_amount * height * phase
        painter.drawPixmap(QRectF(x, y, w, h), self.pixmap, QRectF(self.pixmap.rect()))

    # 贴边小球 (逗逗's floating ball, VPet's side hide) ------------------------------
    def set_mini(self, on: bool, save: bool = True):
        """Shrink to a round head docked at the nearest screen edge, or come back full size."""
        from .chat import screen_rect_for

        if save:
            self.config.mini = on
            self.config.save()
            self.mini_changed.emit(on)
        area = screen_rect_for(self.frameGeometry().center())
        centre = self.frameGeometry().center()
        if on:
            self.resize(MINI_SIZE, MINI_SIZE)
            self._dock(area, centre.y() - MINI_SIZE // 2)
        else:
            size = max(PET_MIN, min(PET_MAX, self.config.pet_size))
            self.resize(size, size)
            left = area.left() + 8 if centre.x() < area.center().x() else area.right() - size - 8
            self.move(left, max(area.top(), min(centre.y() - size // 2, area.bottom() - size)))
            self.config.position = [self.x(), self.y()]
            if save:
                self.config.save()
        self.update()

    def _dock(self, area, top: int):
        """Stick to the left or right edge, whichever is nearer, half a head out of the way."""
        x = area.left() - MINI_SIZE // 4 if self.frameGeometry().center().x() < area.center().x() \
            else area.right() - MINI_SIZE * 3 // 4
        self.move(x, max(area.top(), min(top, area.bottom() - MINI_SIZE)))

    def _paint_mini(self):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        rect = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        waiting = time.monotonic() < self._attention_until
        ring = QColor("#8FAE72")
        if waiting:                                   # a reply is waiting: the ring pulses
            ring.setAlpha(int(140 + 115 * abs(math.sin(time.monotonic() * 4))))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#FAF8F0"))
        painter.drawEllipse(rect)
        avatar = getattr(self, "_mini_avatar", None)
        if avatar is None:
            avatar = self._mini_avatar = load_avatar(128)[0][0]
        clip = QPainterPath()
        clip.addEllipse(rect.adjusted(3, 3, -3, -3))
        painter.setClipPath(clip)
        painter.drawPixmap(rect.adjusted(3, 3, -3, -3), avatar, QRectF(avatar.rect()))
        painter.setClipping(False)
        from PySide6.QtGui import QPen
        painter.setPen(QPen(ring, 3 if waiting else 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(rect)

    # 按键说话 (逗逗's walkie-talkie key) ------------------------------------------
    def voice_toggle(self):
        """First press: start Windows voice typing (Win+H) into the bubble's input box, or into the
        chat panel's when that is open. Second press: stop it and send what was said; the answer
        comes where the question went. Pressing while 小瓜 answers interrupts it."""
        from .chat import bring_to_front
        from .settings_window import hotkey_label

        if not self._listening:
            if self.busy:
                self.stop_answer(quiet=True)                         # speaking up interrupts
            self._voice_in_bubble = not self.chat.isVisible()
            if self._voice_in_bubble:
                if not self.isVisible():
                    self.show()
                self.ask_in_bubble()
                self.bubble.listening(True)
                self.bubble.set_line(f"我在听，说吧～说完再按一次 **{hotkey_label(self.config.voice_hotkey)}**。"
                                     "\n\n没弹出 Windows 的语音输入条的话，直接打字也行。")
            else:
                bring_to_front(self.chat)
                self.chat.edit.setFocus()
                self.chat.set_listening(True)
            if not self._dragging:
                self.play("歪头")                                    # listening, until the second press
            self._listening = True
            self._when_keys_up(self._press_voice_typing)
            return
        self._listening = False
        if self.state == "歪头" and not self.busy:
            self.play("点头", "待机")
        if self._voice_in_bubble:
            self.bubble.listening(False)
            send = lambda: self.bubble.asking and self.bubble.input.text().strip() and self.bubble.send()  # noqa: E731
        else:
            self.chat.set_listening(False)
            send = lambda: self.chat.edit.toPlainText().strip() and self.chat.send()  # noqa: E731
        # Close the voice typing bar, then send what it wrote once it has let go of the box.
        self._when_keys_up(lambda: (self._press_voice_typing(), QTimer.singleShot(500, send)))

    def _when_keys_up(self, action, waited_ms: int = 0):
        """Win+H must go in on its own: while the user still holds Ctrl+Alt from the hotkey,
        Windows would read it as Ctrl+Alt+Win+H and no voice typing comes up."""
        from .hotkeys import modifiers_held

        if modifiers_held() and waited_ms < VOICE_KEYS_UP_MS:
            QTimer.singleShot(40, lambda: self._when_keys_up(action, waited_ms + 40))
            return
        QTimer.singleShot(80, action)

    @staticmethod
    def _press_voice_typing():
        try:
            from pynput.keyboard import Controller, Key
        except ImportError:
            return
        keyboard = Controller()
        with keyboard.pressed(Key.cmd):
            keyboard.press("h")
            keyboard.release("h")

    # chat -----------------------------------------------------------------
    def open_chat(self):
        typed = self.bubble.input.text().strip() if self.bubble.asking else ""
        self.bubble.hide()
        self.greet_today(bubble=False)
        if not self.chat.isVisible() and not self.busy and self.state in ("待机", "睡着"):
            self.play("招手", "待机")
        self.chat.open_beside(self.frameGeometry())
        if typed and not self.chat.edit.toPlainText().strip():
            self.chat.edit.setPlainText(typed)                       # half a question in the bubble comes along

    def toggle_chat(self):
        if self.chat.isVisible():
            self.chat.hide()
        else:
            self.open_chat()

    # talking in the bubble (no chat panel) ---------------------------------------
    def hotkey_pressed(self):
        """叫出小瓜 (Ctrl+Alt+X): a box to type in, right over 小瓜's head. Pressed again it goes
        away; with the chat panel open, the panel closes instead."""
        if self.chat.isVisible():
            self.chat.hide()
        elif self.bubble.asking:
            self.bubble.hide()
        else:
            self.summon()

    def summon(self):
        """Come out and listen (the hotkey, the tray icon): 小瓜 shows up if it was hidden, then the
        chat panel comes to the front if it is open, otherwise the bubble's input box opens."""
        from .chat import bring_to_front

        if not self.isVisible():
            self.show()
        if self.chat.isVisible():
            bring_to_front(self.chat)
            self.chat.edit.setFocus()
        else:
            self.ask_in_bubble()

    def ask_in_bubble(self):
        first = self.greet_today(bubble=False)            # the first look today: today's line above the box
        if not self.busy and not self._dragging and self.state in ("待机", "睡着"):
            self.play("招手", "待机")
        self.bubble.ask(self.frameGeometry(), self.chat.today_text if first else "")

    def _ask_from_bubble(self, text: str):
        if self.busy:
            self.stop_answer(quiet=True)                  # a new question: the old answer stops
        self._submit(text)

    def _bubble_follows(self) -> bool:
        """With the chat panel closed, 小瓜 works and answers in its bubble."""
        return self.isVisible() and not self.chat.isVisible()

    def _bubble_thinking(self):
        if self._bubble_follows():
            self.bubble.thinking(self._bubble_step + "…", self.frameGeometry())

    def _submit(self, text):
        if self.busy:
            return
        self.busy = True
        self.idle_timer.stop()
        chat_before = self.session.chat.id
        self.session.begin_turn()                      # a new day: a new conversation
        if self.session.chat.id != chat_before:
            self._show_conversation()
        question_id = self.session.log_message("mine", text)
        self.chat.add_mine(text, question_id)
        self._start_answer(question_id, text)

    def _start_answer(self, question_id, text):
        """Ask the agent about one logged question (a new one, or the same one again)."""
        self.busy = True
        self._question_id = question_id
        self.session.turn_tag = question_id
        self._turn += 1
        self._cancel = threading.Event()
        self.chat.start_thinking("小瓜在想")
        self._bubble_draft, self._bubble_step = "", "小瓜在想"
        self._bubble_thinking()
        self._answer_started = False
        self.listen_timer.stop()
        self.play("思考入", BUSY_LOOP)
        threading.Thread(target=self._work, args=(text.strip(), self._turn, self._cancel), daemon=True).start()

    def _work(self, text, turn=0, cancel=None):
        if hasattr(self.agent, "session"):
            self.agent.session = self.session
        try:
            if isinstance(self.agent, OfflineAgent) or not hasattr(self.agent, "client"):
                reply = self.agent.ask(text)
            else:
                reply = self.agent.ask(text,
                                       on_step=lambda name: self.bridge.step.emit(turn, name),
                                       on_text=lambda delta: self.bridge.delta.emit(turn, delta),
                                       on_discard=lambda: self.bridge.discard.emit(turn),
                                       cancel=cancel)
        except Exception as error:  # noqa: BLE001 — surface any SDK/network error in the chat
            reply = error
        self.bridge.replied.emit(turn, reply)

    def _act_mood(self, mood: str):
        """The answer's own mood tag: hold up the result if it just arrived, then react."""
        motion = MOOD_MOTIONS[mood]
        after = [motion, "待机"] if motion else ["待机"]
        if self._answer_started and self.state == "灵光一闪":
            self.queue = after                     # right after the result is held up
        elif self.state == "说话":
            self.play(*after)                      # done talking
        elif self._answer_started:
            self.play(*after)
        else:
            self.play("灵光一闪", *after)

    def _on_worker_discard(self):
        self.chat.discard_draft()
        self._bubble_draft = ""
        if self.bubble.following_answer:
            self._bubble_thinking()
        self._answer_started = False               # the real answer will hold up its result again
        self._talking_until = 0.0
        if self.busy and not self._dragging and self.state in ("说话", "灵光一闪"):
            self.play(BUSY_LOOP)

    def _on_worker_step(self, tool_name: str):
        from .chat import STEP_LABELS

        self.chat.step(tool_name)
        self._bubble_draft = ""                    # text before a tool was not the answer
        self._bubble_step = STEP_LABELS.get(tool_name, "正在琢磨")
        if not self.bubble.asking:
            self._bubble_thinking()
        self.on_step(tool_name)

    def _on_worker_delta(self, delta: str):
        self.chat.stream_text(delta)
        self._bubble_draft += delta
        if self._bubble_follows() and not self.bubble.asking:
            if not self.bubble.following_answer:   # the panel was closed half way through
                self._bubble_thinking()
            self.bubble.stream(self._bubble_draft, self.frameGeometry())
        self._on_first_text(delta)
        if not self.has("说话"):                     # the code-made bounce stands in for the artwork
            self._talking_until = time.monotonic() + 0.6
            if not self.ambient.isActive():
                self.ambient.start()

    # stop, take back, delete, ask again ----------------------------------------
    def stop_answer(self, quiet: bool = False):
        """停止: the worker is told to stop, and whatever it still sends is ignored."""
        if not self.busy:
            return
        if self._cancel is not None:
            self._cancel.set()
        self._turn += 1
        self.busy = False
        self.chat.stop_thinking()
        self.chat.discard_draft()
        if self.bubble.following_answer:
            self.bubble.hide()
        if not quiet:
            self.chat.add_divider("停下了")
            self.session.log_message("divider", "停下了")
        if not self._dragging:
            self.play("待机")

    def _recall(self, question_id: str):
        """撤回 my latest question: its answer goes too, the model forgets it, the text comes back to edit."""
        question = self.session.message(question_id)
        if question is None:
            return
        if self.busy and question_id == self._question_id:
            self.stop_answer(quiet=True)
        self.chat.remove_messages(self.session.forget_exchange(question_id) or [question_id])
        self.chat.edit.setPlainText(question.get("text", ""))
        self.chat.edit.setFocus()

    def _delete(self, message_id: str):
        if self.busy and message_id == self._question_id:
            self.stop_answer(quiet=True)
        self.chat.remove_messages(self.session.forget_message(message_id) or [message_id])

    def _retry(self, answer_id: str):
        """重新回答: the same question again."""
        if self.busy:
            return
        answer = self.session.message(answer_id) or {}
        question = self.session.message(answer.get("reply_to") or "")
        if question is None:
            return
        self.chat.remove_messages(self.session.forget_message(answer_id))
        self.idle_timer.stop()
        self._answer_started = False
        self._start_answer(question["id"], question.get("text", ""))

    # linking motion to the conversation ------------------------------------------
    def on_step(self, tool_name: str):
        """The agent is about to run a tool: act it out (scroll, book…)."""
        motion = STEP_MOTIONS.get(tool_name)
        if not self.busy or self._dragging or motion is None or motion == self.state:
            return
        if motion in self.queue[:1] and self.state in ("起卦", "思考入"):
            return                                 # already on its way there
        kind = MOTIONS[motion][0]
        if kind == "once":
            self.play(motion, BUSY_LOOP)
        else:
            self.play(motion)

    def _on_first_text(self, _delta: str):
        """The answer has started to arrive: 小瓜 holds up the result."""
        if self._answer_started or not self.busy:
            return
        self._answer_started = True
        if not self._dragging:
            self.play("灵光一闪", "说话" if self.has("说话") else "待机")

    def _on_typing(self):
        """The user is typing in the chat: 小瓜 tilts its head and listens."""
        if self.busy or self._dragging:
            return
        if self.state in ("待机", "睡着"):
            self.play("歪头")
        if self.state == "歪头":
            self.listen_timer.start()

    def _stop_listening(self):
        if self.state == "歪头" and not self.busy and not self._listening:    # 按键说话 keeps the head tilted
            self.play("待机")

    def _after_drag(self) -> str:
        return BUSY_LOOP if self.busy else "待机"

    def _on_reply(self, reply):
        self.busy = False
        if isinstance(reply, Exception):
            self.play("摇头", "待机")
            message = explain_error(reply)
            error_id = self.session.log_message("error", message, reply_to=self._question_id)
            self.chat.add_error(message, error_id, self._question_id)
            self._notify_if_hidden("小瓜这次没问成，点我看看原因。")
            return
        text = reply.text
        note = None
        if not reply.validated:
            note = "（这次解读没通过证据校验，只当参考。）"
        if self._dragging:
            pass                                   # the landing motion takes over on release
        elif not reply.validated:
            self.play("摇头", "待机")
        elif getattr(reply, "mood", None) in MOOD_MOTIONS:
            self._act_mood(reply.mood)
        elif not self._answer_started:
            self.play("灵光一闪", "待机")
        elif self.state == "灵光一闪":
            self.queue = ["待机"]                  # the answer is all in: no talking after the result
        else:
            self.play("待机")
        self._talking_until = 0.0
        answer_id = self.session.log_message("xiaogua", text + (f"\n\n*{note}*" if note else ""),
                                             reply_to=self._question_id, model=self._model_label(),
                                             checks=list(getattr(reply, "checks", None) or []))
        self.chat.add_reply(text, note, answer_id, self._question_id)
        self.chat.set_stats(self.session.together_text())
        self._bubble_draft = ""
        self._notify_if_hidden(answer=text + (f"\n\n*{note}*" if note else ""))
        self.idle_timer.start(self.idle_ms)

    def _chat_resized(self, width: int, height: int):
        """The user dragged the chat's edges: it opens at that size from now on."""
        self.chat.preferred_size = (width, height)
        self.config.chat_size = [width, height]
        self.config.save()

    def _model_label(self) -> str:
        """Which model answered, for 反馈这条回答: the vendor's name and the model, never its address or key."""
        if isinstance(self.agent, OfflineAgent):
            return "离线模式"
        model = str(getattr(self.agent, "model", "") or "")
        return " · ".join(part for part in (self.config.preset.name, model) if part)

    def _feedback(self, answer_id: str):
        """反馈这条回答: show what would go out; the user copies it and submits it on GitHub themselves."""
        from .feedback import Exchange, FeedbackDialog

        answer = self.session.message(answer_id)
        question = self.session.message((answer or {}).get("reply_to") or "")
        if answer is None or question is None:
            return
        exchange = Exchange(question=question.get("text", ""), answer=answer.get("text", ""),
                            asked_at=question.get("at", ""), model=answer.get("model", ""),
                            checks=list(answer.get("checks", [])), zodiac=self.session.zodiac)
        dialog = self._feedback_dialog = FeedbackDialog(exchange, self.chat)
        dialog.sent.connect(lambda opened: self.chat.notify(
            "反馈内容已复制。在打开的网页里按 Ctrl+V 粘贴，再点提交就好。" if opened
            else "反馈内容已复制，贴到你想发的地方就好。", 15))
        dialog.open()

    def _on_zodiac(self, zodiac: str):
        """The user said their 属相 in the chat: keep it, like the settings field."""
        self.config.zodiac = zodiac
        self.config.save()
        self._refresh_welcome()
        self.zodiac_changed.emit(zodiac)

    def check_reminders(self, now: datetime | None = None) -> list[str]:
        """到点提醒: plans the user asked to be reminded of, at their minute. Given whatever 主动说话 is
        set to and at night too (the user asked for them); held back while 小瓜 is answering or dragged.
        Said in a bubble with a wave, kept in the conversation, and on the tray when 小瓜 is out of sight."""
        memory = self.session.memory
        if memory is None or self.busy or self._dragging:
            return []
        now = now or datetime.now()
        due = memory.due_reminders(now)
        if not due:
            return []
        memory.mark_reminded(due)
        lines = [life.reminder_text(f.text, f.time, now) for f in due]
        text = "\n".join(lines)
        self.chat.add_notice(text, self.session.log_message("xiaogua", text))
        self.memory_changed.emit()
        if self.state == "睡着":
            self.play("起床", "招手", "待机")
        else:
            self.play("招手", "待机")
        if self.bubble.asking:
            self.bubble.set_line(text)                    # over the box being typed in, which stays
        elif self.isVisible():
            self.bubble.say(text, self.frameGeometry(), REMIND_BUBBLE_S)
        if self.config.mini:
            self._attention_until = time.monotonic() + 60
            if not self.ambient.isActive():
                self.ambient.start()
        self.reminded.emit(text)
        return lines

    def _notify_if_hidden(self, text: str = "", answer: str = ""):
        """The chat panel is closed: the answer itself goes in the bubble (a notice for anything else)."""
        if self.config.mini and not self.chat.isVisible():
            self._attention_until = time.monotonic() + 30
            if not self.ambient.isActive():
                self.ambient.start()
        if not self._bubble_follows() or self.bubble.asking:     # the next question is being typed
            return
        if answer:
            self.bubble.answer(answer, self.frameGeometry())
        else:
            self.bubble.say(text, self.frameGeometry())

    def _say(self, text: str, seconds: int = 8) -> bool:
        """A passing word over 小瓜's head, unless the bubble is in the middle of a conversation."""
        if self.bubble.asking or self.bubble.following_answer:
            return False
        self.bubble.say(text, self.frameGeometry(), seconds)
        return True

    # mouse ----------------------------------------------------------------
    def mousePressEvent(self, event):
        self._wake()
        if event.button() == Qt.LeftButton:
            self._press = event.globalPosition().toPoint()
            self._drag = self._press - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self._dragging and not event.buttons() & Qt.LeftButton:
            self._end_drag()                       # the release went elsewhere: land now
            return
        if not event.buttons() and not self.config.mini:
            point = event.position()
            if self.pats.feed(point.x(), point.y(), self.width(), self.height()):
                self._patted()
            return
        if self._drag is not None and event.buttons() & Qt.LeftButton:
            if (event.globalPosition().toPoint() - self._press).manhattanLength() < 5:
                return                           # a click, not a drag yet
            if not self._dragging:
                self._dragging = True
                self.listen_timer.stop()
                self._last_drag = None
                self._swing_pivot = QPoint(self._drag)  # kept after release, so the swing eases out in place
                self.play("提起", "悬空")          # picked up, then dangling while dragged
            now, x = time.monotonic(), event.globalPosition().x()
            if self._last_drag is not None and now > self._last_drag[0]:
                speed = (x - self._last_drag[1]) / (now - self._last_drag[0])      # px per second
                # Pulled right, the body lags to the left (and the other way), like a held melon.
                push = max(-SWING_MAX, min(SWING_MAX, -speed * 0.018))
                self._swing_target = 0.6 * self._swing_target + 0.4 * push
            self._last_drag = (now, x)
            self.move(event.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, event):
        clicked = (self._press is not None and
                   (event.globalPosition().toPoint() - self._press).manhattanLength() < 5)
        if self._drag is not None and not clicked:
            self.config.position = [self.x(), self.y()]
            self.config.save()
        self._drag = self._press = None
        if self._dragging:
            self._end_drag()
        if clicked and event.button() == Qt.LeftButton:
            self.toggle_chat()

    def _end_drag(self):
        self._dragging = False
        self._drag = self._press = None
        self._swing += self._sway()                # the idle sway carries on into the landing, no jump
        self.play("落地", self._after_drag())
        if self.config.mini:
            from .chat import screen_rect_for
            self._dock(screen_rect_for(self.frameGeometry().center()), self.y())
        self.config.position = [self.x(), self.y()]
        self.config.save()

    def moveEvent(self, event):
        """A bubble over 小瓜's head goes where 小瓜 goes."""
        super().moveEvent(event)
        if hasattr(self, "bubble") and self.bubble.isVisible():
            self.bubble.follow(self.frameGeometry())

    def enterEvent(self, _event):
        self._wake()
        if self.config.mini:
            self._attention_until = 0.0
            self.update()

    def _patted(self):
        """摸头 (VPet / DyberPet): a tilt and a word; never while answering or being dragged."""
        if self.busy or self._dragging:
            return
        import random
        if self.has("被摸头"):
            self.play("被摸头", "待机")
        else:
            self.play("歪头")
            QTimer.singleShot(1500, lambda: self.state == "歪头" and not self.busy and self.play("点头", "待机"))
        self._say(random.choice(life.PAT_LINES), 2)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier and not self.config.mini:
            step = PET_STEP if event.angleDelta().y() > 0 else -PET_STEP
            self.set_size(self.width() + step)

    def set_size(self, size: int):
        """Resize around the feet: the bottom centre stays where the user put 小瓜."""
        size = max(PET_MIN, min(PET_MAX, size))
        feet = self.geometry().center().x(), self.geometry().bottom()
        self.resize(size, size)
        self.move(feet[0] - size // 2, feet[1] - size + 1)
        self.config.pet_size = size
        self.config.save()

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        for label, handler in ((f"问小瓜（{self.hotkey_label}）", self.ask_in_bubble), ("打开对话", self.open_chat)):
            action = QAction(label, menu)
            action.triggered.connect(handler)
            menu.addAction(action)
        sizes = menu.addMenu("大小（也可 Ctrl+滚轮）")
        for name, size in PET_SIZES.items():
            action = QAction(name, sizes, checkable=True, checked=self.width() == size)
            action.triggered.connect(lambda _=False, s=size: self.set_size(s))
            sizes.addAction(action)
        menu.addSeparator()
        entries = [("变回小瓜" if self.config.mini else "缩成小球（不挡屏幕）",
                    lambda: self.set_mini(not self.config.mini)),
                   ("新对话", self._new_chat), ("删除这个对话…", self._confirm_delete_chat)]
        if self.open_settings:
            entries.append(("设置…", self.open_settings))
        entries.append(("退出每日一瓜", QApplication.quit))
        for label, handler in entries:
            action = QAction(label, menu)
            action.triggered.connect(handler)
            menu.addAction(action)
        menu.exec(event.globalPos())

    # conversations -----------------------------------------------------------
    def _show_conversation(self):
        """Put the session's open conversation on screen."""
        if hasattr(self.agent, "history"):
            self.agent.history.clear()
        self.chat.clear()
        self.chat.restore(self.session.chat.messages)
        self._refresh_welcome()

    def _new_chat(self):
        if self.busy:
            self.stop_answer(quiet=True)
        self.session.new_chat()
        self._show_conversation()
        self.play("点头", "待机")

    def _switch_chat(self, chat_id: str):
        if chat_id == self.session.chat.id:
            return
        if self.busy:
            self.stop_answer(quiet=True)
        if self.session.switch_chat(chat_id) is not None:
            self._show_conversation()

    def _delete_chat(self, chat_id: str):
        current = chat_id == self.session.chat.id
        if current and self.busy:
            self.stop_answer(quiet=True)
        self.session.delete_chat(chat_id)
        if current:
            self._show_conversation()
        self.chat.notify("对话移到回收站了，30 天内能在 设置 → 回收站 找回来。")
        self.trash_changed.emit()

    def restore_from_trash(self, entry_id: str) -> str | None:
        """设置 → 回收站 → 恢复: a conversation goes back in the list, a fact back in 小瓜记得的你."""
        entry = self.trash.take(entry_id)
        if entry is None:
            return None
        if entry["kind"] == "对话":
            restored = self.session.restore_chat(entry["data"])
        else:
            restored = self.session.memory.restore(entry["data"]).get("id")
            self.memory_changed.emit()
            self._refresh_welcome()
        if restored is None:                       # nowhere to put it (records are off): keep it in the trash
            self.trash.put(entry["kind"], entry["title"], entry["data"])
        self.trash_changed.emit()
        return restored

    def _confirm_delete_chat(self):
        """From the pet's menu there is no second click to catch a slip: ask first."""
        from PySide6.QtWidgets import QMessageBox

        title = self.session.chat.title or "这个对话"
        answer = QMessageBox.question(None, "删除对话", f"删除「{title}」？小瓜马上就会忘掉它；"
                                      "对话先放进回收站，30 天内能在 设置 → 回收站 找回来。",
                                      QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer == QMessageBox.Yes:
            self._delete_chat(self.session.chat.id)

    def _forget(self):
        """删除全部记录 in the settings: the files are gone, so is everything held in memory."""
        if self.busy:
            self.stop_answer(quiet=True)
        self.session.reset()
        self._show_conversation()
        self.play("点头", "待机")


# ------------------------------------------------------------------ main

SERVER_NAME = "xiaogua-desktop-pet"      # local socket a second launch uses to wake the first


def start_hotkey(combo: str, bridge: Bridge, voice: str | None = None):
    """叫出小瓜 and 按键说话, registered with Windows (hotkeys.py). The result's `failed` lists the
    combinations another program already has."""
    from . import hotkeys

    keys = {combo: bridge.hotkey.emit}
    if voice and voice != combo:
        keys[voice] = bridge.voice.emit
    return hotkeys.start(keys)


def build_agent(config: Config):
    """(agent, notice or None). Offline when asked to be, or when there is no key."""
    from .config import api_key

    if config.offline:
        return OfflineAgent(), None
    preset = config.preset
    key, _ = api_key(config.provider)
    if preset.needs_key and not key:
        return OfflineAgent(), (f"还没设置 **{preset.name}** 的 API key，小瓜先用离线模式陪你：能看今天的黄历、"
                                "给你起个盘面，但细讲要接上模型。\n\n"
                                "右键小瓜 → **设置…** → 连接，选好厂商、填上密钥就好（怎么拿密钥，设置里有链接）。")
    from .agent import make_agent
    agent = make_agent(config.model, key, config.provider, config.base_url, config.deep_thinking)
    agent.voice_style = config.voice_style
    return agent, None


def setup_logging() -> None:
    import logging
    from logging.handlers import RotatingFileHandler

    from .config import log_dir

    handler = RotatingFileHandler(log_dir() / "xiaogua.log", maxBytes=1_000_000, backupCount=3,
                                  encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler],
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    def log_uncaught(kind, value, trace):
        logging.getLogger("xiaogua").critical("未捕获的异常", exc_info=(kind, value, trace))
    sys.excepthook = log_uncaught


class Companion(QObject):
    """Owns the pet, the tray icon, the settings window and the hotkey listener."""

    def __init__(self, config: Config, agent=None):
        super().__init__()
        from PySide6.QtWidgets import QSystemTrayIcon

        from .settings_window import SettingsWindow, hotkey_label

        self.config = config
        self.hotkey_label = hotkey_label
        built, self.notice = (agent, None) if agent is not None else build_agent(config)
        self.pet = Pet(built, hotkey_label(config.hotkey), config)
        self.pet.open_settings = self.show_settings
        self.icon = QIcon(load_avatar(128)[0][0])
        self.settings = SettingsWindow(config, self.icon)
        self.settings.changed.connect(self.apply)
        self.settings.key_changed.connect(self.rebuild_agent)
        self.settings.history_deleted.connect(self.pet._forget)
        self.pet.zodiac_changed.connect(lambda _z: self.settings.sync_from(self.config))
        self.settings.set_memory(self.pet.session.memory, self.pet.session.together_text)
        self.pet.memory_changed.connect(self.settings.refresh_memory)
        self.pet.reminded.connect(self._remind_on_tray)
        self.settings.set_trash(self.pet.trash)
        self.settings.trash_restore.connect(self.pet.restore_from_trash)
        self.pet.trash_changed.connect(self.settings.refresh_trash)
        self.pet.memory_changed.connect(self.settings.refresh_trash)     # the model's forget_fact goes there too
        self.settings.memory_edited.connect(self.pet._refresh_welcome)
        self.settings.mini_requested.connect(self.set_mini)
        self.pet.mini_changed.connect(self._mini_changed)
        self.listener = None
        self._hotkey = None
        self.hotkey_problem = None                 # a hotkey that could not be had, said at start
        self._model_state = self._connection(config)

        self.tray = QSystemTrayIcon(self.icon)
        self.tray.setToolTip("每日一瓜")
        menu = QMenu()
        self.tray_actions = {}
        for key, label, handler in (
                ("ask", "问小瓜", self.pet.summon),
                ("chat", "打开对话", self.pet.open_chat),
                ("toggle", "隐藏小瓜", self.toggle_pet),
                ("mini", "缩成小球", lambda: self.set_mini(not self.config.mini)),
                ("through", "鼠标穿透", self.toggle_click_through),
                ("settings", "设置…", self.show_settings),
                ("quit", "退出每日一瓜", QApplication.quit)):
            action = QAction(label, menu)
            action.triggered.connect(handler)
            menu.addAction(action)
            self.tray_actions[key] = action
        self.tray_actions["through"].setCheckable(True)
        self.tray_actions["mini"].setText("变回小瓜" if config.mini else "缩成小球")
        self.tray_menu = menu                    # keep a reference: the tray does not own it
        menu.aboutToShow.connect(self._refresh_toggle)           # 小瓜 may have come back by the hotkey
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_clicked)
        self.apply(config)

    # settings -------------------------------------------------------------
    def apply(self, config: Config):
        self.config = config
        self.pet.hotkey_label = self.hotkey_label(config.hotkey)
        self.pet.apply_config(config)
        if hasattr(self.pet.agent, "voice_style"):
            self.pet.agent.voice_style = config.voice_style      # takes effect on the next question
        self.tray_actions["through"].setChecked(config.click_through)
        self.tray_actions["ask"].setText(f"问小瓜（{self.pet.hotkey_label}）")
        self.settings.sync_from(config)
        if (config.hotkey, config.voice_hotkey) != self._hotkey:
            self.restart_hotkey()
        if self._connection(config) != self._model_state:
            self._model_state = self._connection(config)
            self.rebuild_agent()

    def _remind_on_tray(self, text: str):
        """A reminder 小瓜 cannot show: hidden, 鼠标穿透 (a full-screen window on top), or shrunk to the ball."""
        if not self.pet.isVisible() or self.config.click_through or self.config.mini:
            self.tray.showMessage("每日一瓜 · 提醒", text, self.icon, 15000)

    @staticmethod
    def _connection(config: Config) -> tuple:
        return config.provider, config.model, config.base_url, config.offline, config.deep_thinking

    def restart_hotkey(self):
        if self.listener is not None:
            self.listener.stop()
            self.listener = None
        self.hotkey_problem = None
        try:
            self.listener = start_hotkey(self.config.hotkey, self.pet.bridge, self.config.voice_hotkey)
            self._hotkey = (self.config.hotkey, self.config.voice_hotkey)
        except Exception as error:  # noqa: BLE001 — a bad combo, or the system refused the listener
            self._hotkey = None
            self.hotkey_problem = f"这个组合键用不了：{error}"
            self.settings.hotkey_failed(self.hotkey_problem)
            return
        taken = [self.hotkey_label(combo) for combo in getattr(self.listener, "failed", [])]
        if not taken:
            self.settings.hotkey_ok()
        else:
            self.hotkey_problem = (f"**{'、'.join(taken)}** 被别的程序占用了，按了也叫不到小瓜。"
                                   "右键小瓜 → 设置… → 快捷键与启动，换一个组合吧。")
            self.settings.hotkey_failed(self.hotkey_problem.replace("**", ""))

    def rebuild_agent(self):
        agent, notice = build_agent(self.config)
        history = getattr(self.pet.agent, "history", None)
        if history and hasattr(agent, "history"):
            agent.history = history                 # switching model keeps the conversation
        was_offline = isinstance(self.pet.agent, OfflineAgent)
        self.pet.agent = agent
        self.notice = notice
        if was_offline and not isinstance(agent, OfflineAgent):
            # The chat may still show 「还没设置 API key」 from before: say plainly that it is connected now.
            text = f"接上 **{self.config.preset.name}** 了，现在可以细问了 🍉"
            self.pet.chat.add_notice(text, self.pet.session.log_message("xiaogua", text))
            self.pet._say(text, 8)

    def set_mini(self, on: bool):
        """贴边小球 from the tray or the settings (the pet's own menu goes straight to the pet)."""
        if on != self.config.mini:
            self.pet.set_mini(on)

    def _mini_changed(self, on: bool):
        self.tray_actions["mini"].setText("变回小瓜" if on else "缩成小球")
        self.settings.sync_from(self.config)

    # tray -----------------------------------------------------------------
    def _tray_clicked(self, reason):
        """A click on the tray icon calls 小瓜 out (never hides it: that is in the right-click menu)."""
        from PySide6.QtWidgets import QSystemTrayIcon
        if reason == QSystemTrayIcon.Trigger:
            self.pet.summon()
            self._refresh_toggle()
        elif reason == QSystemTrayIcon.DoubleClick:
            self.show_settings()

    def toggle_pet(self):
        if self.pet.isVisible():
            self.pet.hide()
            self.pet.bubble.hide()
            self.pet.chat.hide()
        else:
            self.pet.show()
        self._refresh_toggle()

    def _refresh_toggle(self):
        self.tray_actions["toggle"].setText("隐藏小瓜" if self.pet.isVisible() else "显示小瓜")

    def toggle_click_through(self):
        self.config.click_through = not self.config.click_through
        self.config.save()
        self.apply(self.config)
        self.tray.showMessage("每日一瓜", "鼠标穿透已开启：点击会穿过小瓜" if self.config.click_through
                              else "鼠标穿透已关闭：可以拖动、单击小瓜聊天了", self.icon, 2500)

    def show_settings(self):
        self.settings.show()
        self.settings.raise_()
        self.settings.activateWindow()

    def wake(self):
        """A second launch asked us to show up."""
        if not self.pet.isVisible():
            self.toggle_pet()
        self.pet.play("招手", "待机")
        self.pet.bubble.say("小瓜已经在这儿啦，点我聊天。", self.pet.frameGeometry())

    # start ----------------------------------------------------------------
    def place_pet(self):
        screens = [s.availableGeometry() for s in QApplication.screens()]
        position = self.config.position
        centre = position and QPoint(position[0] + self.pet.width() // 2, position[1] + self.pet.height() // 2)
        if centre and any(g.contains(centre) for g in screens):
            self.pet.move(*position)
        else:                                   # first run, or that monitor is gone
            screen = QApplication.primaryScreen().availableGeometry()
            self.pet.move(screen.right() - self.pet.width() - 24, screen.bottom() - self.pet.height() - 24)

    def start(self, quiet: bool = False):
        self.place_pet()
        self.pet.show()
        self.tray.show()
        if self.notice:
            self.pet.chat.add_notice(self.notice)
        if self.hotkey_problem:
            self.pet.bubble.say(self.hotkey_problem, self.pet.frameGeometry(), 20)
        elif self.notice:
            self.pet.bubble.say("还没连上模型，点我看看怎么设置。", self.pet.frameGeometry(), 12)
        elif self.config.greet_on_start and not quiet and not self.pet.greet_today():
            self.pet.bubble.say(f"小瓜在～点我聊天，或者按 **{self.pet.hotkey_label}** 随时叫我。",
                                self.pet.frameGeometry())
        QTimer.singleShot(REMIND_FIRST_MS, self.pet.check_reminders)   # one missed while 小瓜 was closed
        self.pet.trash.purge()                                          # 30 days are up: gone for good


def claim_single_instance(on_wake):
    """The server that keeps us the only 小瓜, or None if one is already running.

    A second launch (autostart plus a manual start, say) pokes the first one and exits.
    """
    from PySide6.QtNetwork import QLocalServer, QLocalSocket

    probe = QLocalSocket()
    probe.connectToServer(SERVER_NAME)
    if probe.waitForConnected(300):
        probe.write(b"wake")
        probe.waitForBytesWritten(300)
        probe.disconnectFromServer()
        return None
    QLocalServer.removeServer(SERVER_NAME)        # a stale name left by a crash
    server = QLocalServer()
    server.listen(SERVER_NAME)
    server.newConnection.connect(lambda: (server.nextPendingConnection(), on_wake()))
    return server


def selftest(out_path: str) -> int:
    """Exercise the paths a packaged build can break (hidden imports, data files,
    time zones) and write the result as JSON: a windowed exe has no console."""
    from pathlib import Path

    report: dict = {}
    try:
        from . import chat, feedback, hotkeys, openai_compat, providers, settings_window  # noqa: F401 — import check
        from .tools import cast_now, lookup_hexagrams, run_tool

        cast = cast_now("自检：今天面试能成吗")
        report["cast"] = {"primary": cast["primary"]["name"], "hour_branch": cast["time"]["hour_branch"]}
        report["hexagram_lookup"] = not lookup_hexagrams([cast["primary"]["name"]])["missing"]
        report["almanac"] = run_tool("almanac_day", {}).get("status")
        report["providers"] = len(providers.PROVIDERS)
        QApplication.instance() or QApplication(sys.argv[:1])
        motions = load_motions(64)
        report["motions_with_art"] = sorted(s for s, (_, frames, _) in motions.items() if frames)
        report["status"] = "ok"
    except Exception as error:  # noqa: BLE001 — the whole point is to report it
        import traceback
        report.update(status="error", error=f"{type(error).__name__}: {error}", trace=traceback.format_exc())
    Path(out_path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["status"] == "ok" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="xiaogua", description=__doc__)
    parser.add_argument("--offline", action="store_true", help="不连模型，只看黄历和本地起卦")
    parser.add_argument("--provider", help="本次使用的厂商 ID，如 deepseek、qwen（不改设置）")
    parser.add_argument("--model", help="本次使用的模型 ID（不改设置）")
    parser.add_argument("--autostart", action="store_true", help="开机自启时使用：安静启动，不打招呼")
    parser.add_argument("--selftest", metavar="OUT", help="打包自检：起一卦、查农历、载入动作，结果写入 OUT 后退出")
    args = parser.parse_args(argv)
    if args.selftest:
        return selftest(args.selftest)

    setup_logging()
    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("每日一瓜")

    holder = {}
    server = claim_single_instance(lambda: holder["companion"].wake())
    if server is None:
        return 0
    config = Config.load()
    if args.offline:
        config.offline = True
    if args.provider:
        config.provider = args.provider
    if args.model:
        config.model = args.model
    companion = holder["companion"] = Companion(config)
    companion.start(quiet=args.autostart)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
