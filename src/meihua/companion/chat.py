"""The 每日一瓜 chat panel: one window for the whole conversation.

It sits beside 小瓜 on 小瓜's own screen, keeps the conversation's messages and
shows what 小瓜 is doing while it works. A quick question can also be asked in
the bubble over 小瓜's head (app.Bubble); it lands in the same conversation.
"""

from __future__ import annotations

import re
from datetime import datetime

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QGuiApplication, QIcon, QPainter,
                           QPainterPath, QPixmap)
from PySide6.QtWidgets import (QApplication, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel,
                               QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

import meihua

from . import harness

APP_TITLE = "每日一瓜"
CHAT_SIZE = (400, 580)        # the chat window (shadow margin included) until the user resizes it
CHAT_MIN = (340, 420)
EDGE_OUT, EDGE_IN, EDGE_CORNER = 6, 4, 16   # px around the panel's edge that resize it; corners reach further
QUICK_QUESTIONS = ("我今天适合干嘛", "帮我挑个好日子", "今天几点出门好")
BUBBLE_MAX = 268              # widest text in a bubble (the panel is 400 wide)
# The answer ends with a mood tag (agent.split_mood); while streaming, hide it even half-arrived.
_TRAILING_TAG = re.compile(r"\s*[〔【\[][^〕】\]\n]{0,8}[〕】\]]?\s*$")
UI = meihua.ROOT / "assets" / "ui"

PAPER, CARD, INK, LEAF, LEAF_DARK, LINE, MUTED, MINE = (
    "#FAF8F0", "#FFFFFF", "#2F4737", "#8FAE72", "#6E8F55", "#DCE3CB", "#8C9687", "#E4EDD3")
ERROR_BG, ERROR_LINE = "#FBEFEA", "#E7C2B4"

# What 小瓜 is doing, by tool name (shown while the answer is being worked out).
STEP_LABELS = {
    "cast_now": "正在起卦", "lookup_hexagrams": "正在翻卦书", "validate_reading": "正在核对证据",
    "almanac_day": "正在翻黄历", "almanac_pick_days": "正在挑日子", "remember_zodiac": "记下你的属相",
    "remember_fact": "记下来", "forget_fact": "划掉一条", "close_fact": "记下结果",
    "daily_reading": "正在起卦",
}

STYLE = f"""
QWidget {{ font-family: 'Microsoft YaHei'; color: {INK}; }}
QFrame#panel {{ background: {PAPER}; border: 1px solid {LINE}; border-radius: 18px; }}
QLabel#title {{ font-size: 15px; font-weight: bold; }}
QLabel#status {{ color: {MUTED}; font-size: 11px; }}
QLabel#muted {{ color: {MUTED}; font-size: 11px; }}
QPushButton#icon {{ border: none; border-radius: 8px; padding: 4px; background: transparent; }}
QPushButton#icon:hover {{ background: #EEF1E4; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
QScrollBar:vertical {{ width: 6px; background: transparent; margin: 4px 0; }}
QScrollBar::handle:vertical {{ background: #D5DCC6; border-radius: 3px; min-height: 30px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QFrame#xiaogua {{ background: {CARD}; border: 1px solid {LINE}; border-radius: 14px;
                 border-top-left-radius: 4px; }}
QFrame#mine {{ background: {MINE}; border: none; border-radius: 14px; border-top-right-radius: 4px; }}
QFrame#error {{ background: {ERROR_BG}; border: 1px solid {ERROR_LINE}; border-radius: 14px;
               border-top-left-radius: 4px; }}
QLabel#body {{ font-size: 13px; line-height: 150%; background: transparent; }}
QPushButton#feedback {{ border: none; background: transparent; color: {MUTED}; font-size: 11px; padding: 0 2px; }}
QPushButton#feedback:hover {{ color: {LEAF_DARK}; text-decoration: underline; }}
QPushButton#chip {{ border: 1px solid {LINE}; border-radius: 13px; padding: 4px 12px; background: {CARD};
                   font-size: 12px; }}
QPushButton#chip:hover {{ background: #EEF3E3; border-color: {LEAF}; }}
QFrame#composer {{ background: {CARD}; border: 1px solid {LINE}; border-radius: 16px; }}
QFrame#composer[focused="true"] {{ border: 1px solid {LEAF}; }}
QPlainTextEdit {{ border: none; background: transparent; font-size: 13px; padding: 2px 0; }}
QPushButton#send {{ border: none; border-radius: 16px; background: {LEAF}; }}
QPushButton#send:hover {{ background: {LEAF_DARK}; }}
QPushButton#send:disabled {{ background: #CBD5BC; }}
QLabel#divider {{ color: {MUTED}; font-size: 11px; }}
QFrame#chatlist {{ background: {CARD}; border: 1px solid {LINE}; border-radius: 12px; }}
QFrame#chatrow {{ border-radius: 8px; background: transparent; }}
QFrame#chatrow:hover {{ background: #EEF3E3; }}
QFrame#chatrow[current="true"] {{ background: #E4EDD3; }}
QLabel#chattitle {{ font-size: 13px; background: transparent; }}
QLabel#chattime {{ font-size: 11px; color: {MUTED}; background: transparent; }}
QPushButton#newchat {{ border: 1px dashed {LEAF}; border-radius: 8px; padding: 6px; background: transparent;
                       color: {LEAF_DARK}; font-size: 13px; }}
QPushButton#newchat:hover {{ background: #EEF3E3; }}
QPushButton#rowdelete {{ border: none; border-radius: 6px; padding: 2px 6px; background: transparent;
                         color: {MUTED}; font-size: 11px; }}
QPushButton#rowdelete:hover {{ background: #F4E4DD; color: #B5533C; }}
QLabel#today {{ background: {CARD}; border: 1px solid {LINE}; border-radius: 12px; padding: 10px 14px;
               font-size: 13px; line-height: 150%; }}
QLabel#hello {{ font-size: 13px; color: {INK}; }}
QMenu {{ background: {CARD}; border: 1px solid {LINE}; padding: 4px; }}
QMenu::item {{ padding: 5px 16px; border-radius: 6px; }}
QMenu::item:selected {{ background: #E8EFD9; color: {INK}; }}
"""


def icon(name: str) -> QIcon:
    return QIcon(str(UI / f"{name}.svg"))


def rounded(pixmap: QPixmap, radius: float) -> QPixmap:
    out = QPixmap(pixmap.size())
    out.fill(Qt.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(out.rect()), radius, radius)
    painter.setClipPath(path)
    painter.drawPixmap(0, 0, pixmap)
    painter.end()
    return out


def screen_rect_for(point: QPoint):
    screen = QGuiApplication.screenAt(point) or QGuiApplication.primaryScreen()
    return screen.availableGeometry()


_MOUSE_EVENTS = (QEvent.MouseMove, QEvent.MouseButtonPress, QEvent.MouseButtonRelease)
_NO_EDGE = Qt.Edge(0)


def edge_cursor(edges) -> Qt.CursorShape | None:
    """The resize arrow for a set of edges (None: not on an edge)."""
    left, right = bool(edges & Qt.LeftEdge), bool(edges & Qt.RightEdge)
    top, bottom = bool(edges & Qt.TopEdge), bool(edges & Qt.BottomEdge)
    if (left and top) or (right and bottom):
        return Qt.SizeFDiagCursor
    if (right and top) or (left and bottom):
        return Qt.SizeBDiagCursor
    if left or right:
        return Qt.SizeHorCursor
    if top or bottom:
        return Qt.SizeVerCursor
    return None


def shown_answer(text: str) -> str:
    """Streamed answer text as it may be shown: no mood tag (whole or half-arrived), no dash flashes."""
    return harness.polish(_TRAILING_TAG.sub("", text))[0]


def bring_to_front(window: QWidget):
    """Raise and activate a window so typing goes into it.

    Windows lets 小瓜 take the keyboard right after the user pressed its hotkey (registered
    with the system, hotkeys.py) or clicked its tray icon or itself. No tricks beyond that:
    joining another program's input queue (AttachThreadInput) froze 小瓜 for seconds when
    that program was busy, and Windows put blank 「未响应」 frames in its place.
    """
    window.raise_()
    window.activateWindow()


class Avatar(QLabel):
    def __init__(self, pixmap: QPixmap | None, size: int):
        super().__init__()
        self.setFixedSize(size, size)
        if pixmap is not None:
            self.setPixmap(pixmap.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation))


class Message(QFrame):
    """One chat bubble. kind: xiaogua / mine / error / typing."""

    _metrics: QFontMetrics | None = None

    def set_text(self, text: str):
        """Set the text and size the bubble to it: short lines stay short, long ones wrap at BUBBLE_MAX."""
        self.body.setText(text)
        if Message._metrics is None:
            font = QFont("Microsoft YaHei")
            font.setPixelSize(13)                            # QLabel#body in the style sheet
            Message._metrics = QFontMetrics(font)
        plain = re.sub(r"[*_`#>]", "", text) if self.body.textFormat() == Qt.MarkdownText else text
        natural = max((Message._metrics.horizontalAdvance(line) for line in plain.splitlines()), default=0)
        self.body.setFixedWidth(max(24, min(natural + 8, BUBBLE_MAX)))

    def __init__(self, kind: str, text: str = "", image: QPixmap | None = None,
                 msg_id: str | None = None, reply_to: str | None = None):
        super().__init__()
        self.kind = kind
        self.menu_handler = None                   # set by the panel: the right-click menu
        self.feedback_handler = None               # set by the panel: 「反馈」 under an answer
        self.feedback_button: QPushButton | None = None
        self.setObjectName("error" if kind == "error" else "mine" if kind == "mine" else "xiaogua")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(6)
        if image is not None:
            thumb = QLabel()
            thumb.setPixmap(rounded(image.scaled(220, 124, Qt.KeepAspectRatio, Qt.SmoothTransformation), 8))
            layout.addWidget(thumb)
        self.body = QLabel(objectName="body")
        self.body.setWordWrap(True)
        self.body.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
        self.body.setOpenExternalLinks(True)
        self.body.setTextFormat(Qt.PlainText if kind in ("mine", "typing") else Qt.MarkdownText)
        self.body.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        self.body.setContextMenuPolicy(Qt.NoContextMenu)          # right-click goes to the bubble's menu
        self.set_text(text)
        self.body.setVisible(bool(text) or kind == "typing")
        layout.addWidget(self.body)
        self.set_ids(msg_id, reply_to)
        if kind == "typing":
            self._dots = 0
            self._base = text
            self._timer = QTimer(self, interval=400)
            self._timer.timeout.connect(self._tick)
            self._timer.start()

    def set_ids(self, msg_id: str | None, reply_to: str | None):
        """An answer to a question (not a notice or a reminder) gets a small 「反馈」 under it."""
        self.msg_id, self.reply_to = msg_id, reply_to
        if self.kind == "xiaogua" and msg_id and reply_to and self.feedback_button is None:
            self.feedback_button = QPushButton("反馈", objectName="feedback")
            self.feedback_button.setCursor(Qt.PointingHandCursor)
            self.feedback_button.setToolTip("这条回答不对？反馈给作者")
            self.feedback_button.clicked.connect(lambda: self.feedback_handler and self.feedback_handler(self))
            self.layout().addWidget(self.feedback_button, alignment=Qt.AlignRight)

    def set_step(self, text: str):
        self._base = text
        self._tick()

    def contextMenuEvent(self, event):
        if self.menu_handler is not None and self.kind != "typing":
            self.menu_handler(self, event.globalPos())

    def _tick(self):
        self._dots = (self._dots + 1) % 4
        self.set_text(self._base + "·" * self._dots)


def _when(stamp: str) -> str:
    """「今天 16:38」「昨天 21:05」「9月24日」 for the conversation list."""
    from datetime import date, timedelta

    try:
        moment = datetime.fromisoformat(stamp)
    except ValueError:
        return ""
    today = date.today()
    if moment.date() == today:
        return f"今天 {moment:%H:%M}"
    if moment.date() == today - timedelta(days=1):
        return f"昨天 {moment:%H:%M}"
    return f"{moment.month}月{moment.day}日"


class ChatList(QFrame):
    """会话列表: a popup with 新对话 and one row per conversation (click to open, 删除 twice to delete)."""

    picked = Signal(str)
    deleted = Signal(str)
    created = Signal()

    def __init__(self, parent, items: list[dict], current_id: str):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setObjectName("chatlist")
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setFixedWidth(260)
        column = QVBoxLayout(self)
        column.setContentsMargins(8, 8, 8, 8)
        column.setSpacing(4)
        new = QPushButton("＋ 新对话", objectName="newchat")
        new.setCursor(Qt.PointingHandCursor)
        new.clicked.connect(lambda: (self.created.emit(), self.close()))
        column.addWidget(new)
        rows = QWidget()
        rows_layout = QVBoxLayout(rows)
        rows_layout.setContentsMargins(0, 0, 0, 0)
        rows_layout.setSpacing(2)
        self.rows = {}
        for item in items:
            row = self._row(item, item["id"] == current_id)
            rows_layout.addWidget(row)
            self.rows[item["id"]] = row
        rows_layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(rows)
        scroll.setFixedHeight(min(320, 48 * max(1, len(items)) + 8))
        column.addWidget(scroll)

    def _row(self, item: dict, current: bool) -> QFrame:
        row = QFrame(objectName="chatrow")
        row.setProperty("current", "true" if current else "false")
        row.setCursor(Qt.PointingHandCursor)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(8, 5, 4, 5)
        text = QVBoxLayout()
        text.setSpacing(0)
        title = QLabel(item.get("title") or "新对话", objectName="chattitle")
        title.setFixedWidth(170)
        title.setText(title.fontMetrics().elidedText(title.text(), Qt.ElideRight, 168))
        text.addWidget(title)
        text.addWidget(QLabel(_when(item.get("updated", "")) or "还没开始", objectName="chattime"))
        layout.addLayout(text, 1)
        delete = QPushButton("删除", objectName="rowdelete")
        delete.setCursor(Qt.PointingHandCursor)
        delete.setToolTip("删除整个对话")

        def confirm():
            if delete.text() == "删除":
                delete.setText("确认删除")                 # one more click: a whole conversation goes
                return
            self.deleted.emit(item["id"])
            self.close()

        delete.clicked.connect(confirm)
        layout.addWidget(delete)
        row.mousePressEvent = lambda _event, i=item["id"]: (self.picked.emit(i), self.close())
        row.delete_button = delete
        return row


class ChatPanel(QWidget):
    """Signals `submitted(text)`, `clear_requested()`, `settings_requested()`; the pet does the
    work and calls back add_reply/add_error."""
    submitted = Signal(str)
    user_typing = Signal()                     # the user is typing (小瓜 listens)
    clear_requested = Signal()
    settings_requested = Signal()
    delete_requested = Signal(str)             # message id: 删除
    recall_requested = Signal(str)             # message id of my latest question: 撤回
    retry_requested = Signal(str)              # message id of 小瓜's latest answer or error: 重新回答
    feedback_requested = Signal(str)           # message id of one of 小瓜's answers: 反馈这条回答
    stop_requested = Signal()                  # the stop button while 小瓜 is answering
    chats_requested = Signal()                 # the 对话 button: the pet answers with show_chat_list
    chat_picked = Signal(str)                  # conversation id
    chat_deleted = Signal(str)                 # conversation id: 删除整个对话
    new_chat_requested = Signal()
    resized = Signal(int, int)                 # the user dragged an edge: the size to open at next time

    def __init__(self, avatar: QPixmap | None = None, hotkey_label: str = "Ctrl+Alt+X"):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet(STYLE)
        self.avatar = avatar
        self.hotkey_label = hotkey_label
        self.busy = False
        self.typing: Message | None = None
        self.draft: Message | None = None          # the answer while it is being streamed
        self._draft_text = ""
        self._flush_timer = QTimer(self, singleShot=True, interval=66)
        self._flush_timer.timeout.connect(self._flush_draft)
        self._drag: QPoint | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 14)               # room for the shadow
        self.panel = QFrame(objectName="panel")
        shadow = QGraphicsDropShadowEffect(blurRadius=28, xOffset=0, yOffset=6)
        shadow.setColor(QColor(47, 71, 55, 60))
        self.panel.setGraphicsEffect(shadow)
        outer.addWidget(self.panel)
        body = QVBoxLayout(self.panel)
        body.setContentsMargins(0, 0, 0, 12)
        body.setSpacing(0)
        body.addWidget(self._header())
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background: {LINE};")
        body.addWidget(line)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.feed = QWidget()
        self.feed_layout = QVBoxLayout(self.feed)
        self.feed_layout.setContentsMargins(14, 14, 14, 8)
        self.feed_layout.setSpacing(10)
        self.feed_layout.addStretch()
        self.scroll.setWidget(self.feed)
        # Follow new messages to the bottom once their layout has settled (a message's
        # height is only known after it is laid out, so scrolling right away falls short).
        self.scroll.verticalScrollBar().rangeChanged.connect(self._follow)
        body.addWidget(self.scroll, 1)
        self.welcome = self._welcome()
        self.feed_layout.addWidget(self.welcome)

        body.addWidget(self._composer())
        self.resize(*CHAT_SIZE)

        # Resizing by the edges: a frameless window has none of its own (see _edge_event).
        self.preferred_size: tuple[int, int] | None = None     # set by the pet from the settings
        self.setMinimumSize(*CHAT_MIN)
        self._resizing = None                  # (edges, pointer, geometry) while resized by hand
        self._placing = False                  # open_beside sizing it: not the user
        self._size_timer = QTimer(self, singleShot=True, interval=400)
        self._size_timer.timeout.connect(lambda: self.resized.emit(self.width(), self.height()))
        QApplication.instance().installEventFilter(self)

    # building -------------------------------------------------------------
    def _icon_button(self, name: str, tip: str, handler) -> QPushButton:
        button = QPushButton(objectName="icon")
        button.setIcon(icon(name))
        button.setIconSize(QSize(18, 18))
        button.setToolTip(tip)
        button.setCursor(Qt.PointingHandCursor)
        button.clicked.connect(handler)
        return button

    def _header(self) -> QWidget:
        header = QWidget()
        header.setFixedHeight(58)
        row = QHBoxLayout(header)
        row.setContentsMargins(16, 10, 10, 10)
        row.setSpacing(8)
        row.addWidget(Avatar(self.avatar, 34), alignment=Qt.AlignVCenter)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        titles.addWidget(QLabel(APP_TITLE, objectName="title"))
        self.status = QLabel("", objectName="status")          # shown only while 小瓜 is working
        self.status.hide()
        titles.addWidget(self.status)
        titles.setAlignment(Qt.AlignVCenter)
        row.addLayout(titles, 1)
        row.addWidget(self._icon_button("list", "对话列表：新对话、切换、删除", self.chats_requested.emit))
        row.addWidget(self._icon_button("gear", "设置（清空对话在右键小瓜的菜单里）", self.settings_requested.emit))
        row.addWidget(self._icon_button("close", "收起（Esc）", self.hide))
        self.header = header
        return header

    def _welcome(self) -> QWidget:
        box = QWidget()
        column = QVBoxLayout(box)
        column.setContentsMargins(4, 20, 4, 4)
        column.setSpacing(8)
        column.addWidget(Avatar(self.avatar, 60), alignment=Qt.AlignHCenter)
        self._today_text = ""
        self.today_line = QLabel(objectName="today")       # the morning line: 黄历, a plan, a follow-up
        self.today_line.setWordWrap(True)
        self.today_line.hide()
        column.addWidget(self.today_line)
        self.stats_line = QLabel(objectName="muted")      # 陪你第 N 天 · 聊过 N 段对话
        self.stats_line.setAlignment(Qt.AlignHCenter)
        self.stats_line.hide()
        self.welcome_hint = QLabel(objectName="hello")
        self.welcome_hint.setAlignment(Qt.AlignHCenter)
        column.addWidget(self.welcome_hint)
        column.addWidget(self.stats_line)
        column.addSpacing(4)
        self.chips = self._chip_row(QUICK_QUESTIONS)
        column.addWidget(self.chips)
        self._update_welcome_hint()
        return box

    def _chip_row(self, questions) -> QWidget:
        row_widget = QWidget()
        chips = QHBoxLayout(row_widget)
        chips.setContentsMargins(0, 0, 0, 0)
        chips.setSpacing(6)
        chips.addStretch()
        for question in questions:
            chip = QPushButton(question, objectName="chip")
            chip.setCursor(Qt.PointingHandCursor)
            chip.clicked.connect(lambda _=False, q=question: self.send(q))
            chips.addWidget(chip)
        chips.addStretch()
        return row_widget

    @property
    def today_text(self) -> str:
        """The morning line on the welcome card (the bubble's input box shows it too)."""
        return self._today_text

    def set_today(self, text: str | None):
        self._today_text = text or ""
        self.today_line.setText(self._today_text)
        self._update_welcome_hint()

    def set_stats(self, text: str | None):
        self.stats_line.setText(text or "")
        self.stats_line.setVisible(bool(text))

    def _update_welcome_hint(self):
        today = getattr(self, "_today_text", "")
        self.welcome_hint.setText("今天有什么拿不准的？")
        self.welcome_hint.setVisible(not today)
        if hasattr(self, "today_line"):
            self.today_line.setVisible(bool(today))

    def _composer(self) -> QWidget:
        wrap = QWidget()
        column = QVBoxLayout(wrap)
        column.setContentsMargins(12, 8, 12, 0)
        column.setSpacing(6)

        self.composer = QFrame(objectName="composer")
        row = QHBoxLayout(self.composer)
        row.setContentsMargins(4, 4, 4, 4)
        row.setSpacing(4)
        self.edit = QPlainTextEdit()
        self._hint = ""
        self.set_hint("问小瓜…")
        self.edit.setTabChangesFocus(True)
        self.edit.setFixedHeight(32)
        self.edit.textChanged.connect(self._fit_input)
        self.edit.installEventFilter(self)
        row.addWidget(self.edit, 1)
        self.send_button = QPushButton(objectName="send")
        self.send_button.setIcon(icon("send"))
        self.send_button.setIconSize(QSize(18, 18))
        self.send_button.setFixedSize(32, 32)
        self.send_button.setCursor(Qt.PointingHandCursor)
        self.send_button.setToolTip("发送（Enter）；换行用 Shift+Enter")
        self.send_button.clicked.connect(lambda: self.stop_requested.emit() if self.busy else self.send())
        row.addWidget(self.send_button, alignment=Qt.AlignBottom)
        column.addWidget(self.composer)
        return wrap

    # input ----------------------------------------------------------------
    def eventFilter(self, watched, event):
        if event.type() in _MOUSE_EVENTS and isinstance(watched, QWidget) and watched.window() is self:
            if self._edge_event(event):
                return True
        if watched is self.edit:
            if event.type() == event.Type.KeyPress:
                if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not event.modifiers() & Qt.ShiftModifier:
                    self.send()
                    return True
                if event.key() == Qt.Key_Escape:
                    self.hide()
                    return True
            elif event.type() in (event.Type.FocusIn, event.Type.FocusOut):
                self.composer.setProperty("focused", event.type() == event.Type.FocusIn)
                self.composer.setStyle(self.composer.style())
            elif event.type() == event.Type.InputMethod:
                # Pinyin still being typed is not in the document yet, and QPlainTextEdit would
                # draw the grey hint right under it: put the hint away while there is any.
                self.edit.setPlaceholderText("" if event.preeditString() else self._hint)
        return super().eventFilter(watched, event)

    def set_hint(self, text: str):
        """The grey hint in the empty input box."""
        self._hint = text
        self.edit.setPlaceholderText(text)

    def _fit_input(self):
        if self.edit.toPlainText().strip():
            self.user_typing.emit()
        lines = max(1, min(5, int(self.edit.document().size().height())))
        self.edit.setFixedHeight(18 * lines + 14)

    def send(self, text: str | None = None):
        if self.busy:
            return
        text = (self.edit.toPlainText() if text is None else text).strip()
        if not text:
            self.set_hint("先写一句想问的～")
            return
        self.edit.clear()
        self.set_hint("问小瓜…")
        self.submitted.emit(text)

    # conversation ----------------------------------------------------------
    def _add(self, widget: Message, mine: bool = False):
        self.welcome.hide()
        row = QHBoxLayout()
        row.setSpacing(8)
        if mine:
            row.addStretch()
            row.addWidget(widget)
        else:
            row.addWidget(Avatar(self.avatar, 28), alignment=Qt.AlignTop)
            row.addWidget(widget)
            row.addStretch()
        holder = QWidget()
        holder.setLayout(row)
        row.setContentsMargins(0, 0, 0, 0)
        self.feed_layout.addWidget(holder)
        widget.holder = holder
        widget.menu_handler = self._message_menu
        widget.feedback_handler = lambda message: self.feedback_requested.emit(message.msg_id)
        self._stick_to_end = True
        self._scroll_to_end()
        return widget

    def _scroll_to_end(self):
        bar = self.scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _follow(self, _minimum, maximum):
        if getattr(self, "_stick_to_end", False):
            self.scroll.verticalScrollBar().setValue(maximum)
            QTimer.singleShot(200, lambda: setattr(self, "_stick_to_end", False))

    def add_mine(self, text: str, msg_id: str | None = None) -> Message:
        return self._add(Message("mine", text, msg_id=msg_id), mine=True)

    # the bubbles' right-click menu ---------------------------------------------
    def messages(self) -> list[Message]:
        out = []
        for index in range(self.feed_layout.count()):
            holder = self.feed_layout.itemAt(index).widget()
            message = holder.findChild(Message) if holder is not None and holder is not self.welcome else None
            if message is not None and message.kind != "typing":
                out.append(message)
        return out

    def _message_menu(self, message: Message, position):
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)
        menu.addAction("复制", lambda: QApplication.clipboard().setText(message.body.text()))
        shown = self.messages()
        last_mine = next((m for m in reversed(shown) if m.kind == "mine"), None)
        last_answer = next((m for m in reversed(shown) if m.kind in ("xiaogua", "error")), None)
        if message.msg_id:
            if message.kind == "mine" and message is last_mine:
                menu.addAction("撤回", lambda: self.recall_requested.emit(message.msg_id))
            if (message.kind in ("xiaogua", "error") and message is last_answer and message.reply_to
                    and not self.busy):
                menu.addAction("重新回答" if message.kind == "xiaogua" else "重试",
                               lambda: self.retry_requested.emit(message.msg_id))
            if message.feedback_button is not None:
                menu.addAction("反馈这条回答…", lambda: self.feedback_requested.emit(message.msg_id))
            menu.addSeparator()
            menu.addAction("删除", lambda: self.delete_requested.emit(message.msg_id))
        self._menu = menu                                    # keep it alive while shown
        menu.popup(position)

    # conversations ------------------------------------------------------------
    def show_chat_list(self, items: list[dict], current_id: str):
        """The 对话 list under the header: 新对话 on top, then every conversation, newest first."""
        self._chat_list = ChatList(self, items, current_id)
        self._chat_list.picked.connect(self.chat_picked.emit)
        self._chat_list.deleted.connect(self.chat_deleted.emit)
        self._chat_list.created.connect(self.new_chat_requested.emit)
        corner = self.header.mapToGlobal(self.header.rect().bottomRight())
        self._chat_list.adjustSize()
        self._chat_list.move(corner.x() - self._chat_list.width() - 6, corner.y() + 2)
        self._chat_list.show()

    def remove_messages(self, ids):
        """Take bubbles off the screen by message id; the welcome comes back when none are left."""
        ids = set(ids)
        for message in self.messages():
            if message.msg_id in ids:
                self._remove_holder(message.holder)
        if not self.messages() and self.typing is None and self.draft is None:
            self.welcome.show()

    def start_thinking(self, first_step: str = "小瓜在想"):
        self.busy = True
        self.send_button.setIcon(icon("stop"))           # the send button becomes stop
        self.send_button.setToolTip("停止回答")
        self._step_label = first_step
        self.typing = self._add(Message("typing", first_step))
        self._set_status(first_step + "…")

    def set_listening(self, on: bool):
        """按键说话: say so in the box while Windows voice typing listens."""
        self.set_hint("在听……说完再按一次快捷键就发出去" if on else "问小瓜…")
        self._set_status("在听…" if on else "")

    def _set_status(self, text: str):
        self.status.setText(text)
        self.status.setVisible(bool(text))

    def notify(self, text: str, seconds: int = 8):
        """A passing note under the title (not a message: the conversation and its welcome stay as they are)."""
        self._set_status(text)
        QTimer.singleShot(seconds * 1000, lambda: self.status.text() == text and self._set_status(""))

    def step(self, tool_name: str):
        label = STEP_LABELS.get(tool_name, "正在琢磨")
        self._step_label = label
        if self.draft is not None:                   # the model moved on to a tool: not the answer
            self.discard_draft()
        if self.typing is not None:
            self.typing.set_step(label)
        self._set_status(label + "…")

    # streaming ------------------------------------------------------------
    def stream_text(self, delta: str):
        """The answer as it arrives: the typing bubble turns into a growing reply bubble."""
        if self.draft is None:
            self._remove_typing()
            self.draft = self._add(Message("xiaogua", ""))
            self._draft_text = ""
            self._set_status("小瓜在说…")
        self._draft_text += delta
        if not self._flush_timer.isActive():         # re-render markdown at most ~15 times a second
            self._flush_timer.start()

    def _flush_draft(self):
        if self.draft is not None:
            shown = shown_answer(self._draft_text)
            self.draft.set_text(shown)
            self.draft.body.setVisible(bool(shown))
            self._stick_to_end = True
            self._scroll_to_end()

    def discard_draft(self):
        """Take back streamed text that turned out not to be the answer."""
        if self.draft is None:
            return
        self._flush_timer.stop()
        self._remove_holder(self.draft.holder)
        self.draft, self._draft_text = None, ""
        if self.busy and self.typing is None:
            self.typing = self._add(Message("typing", getattr(self, "_step_label", "小瓜在想")))

    # ending a turn ----------------------------------------------------------
    def _remove_holder(self, holder):
        self.feed_layout.removeWidget(holder)            # now, not at the next event loop turn
        holder.hide()
        holder.deleteLater()

    def _remove_typing(self):
        if self.typing is not None:
            self.typing._timer.stop()
            self._remove_holder(self.typing.holder)
            self.typing = None

    def stop_thinking(self):
        self._stop_thinking()

    def _stop_thinking(self):
        self.busy = False
        self.send_button.setIcon(icon("send"))
        self.send_button.setToolTip("发送（Enter）；换行用 Shift+Enter")
        self.send_button.setEnabled(True)
        self._set_status("")
        self._remove_typing()

    def add_reply(self, text: str, note: str | None = None, msg_id: str | None = None,
                  reply_to: str | None = None) -> Message:
        """The final answer. If it was streamed, the streamed bubble becomes the answer."""
        self._stop_thinking()
        if note:
            text += f"\n\n*{note}*"
        if self.draft is not None:
            self._flush_timer.stop()
            message, self.draft, self._draft_text = self.draft, None, ""
            message.set_text(text)
            message.body.setVisible(True)
            message.set_ids(msg_id, reply_to)
            self._stick_to_end = True
            self._scroll_to_end()
            return message
        return self._add(Message("xiaogua", text, msg_id=msg_id, reply_to=reply_to))

    def add_error(self, text: str, msg_id: str | None = None, reply_to: str | None = None) -> Message:
        self._stop_thinking()
        self.discard_draft()
        return self._add(Message("error", text, msg_id=msg_id, reply_to=reply_to))

    def add_notice(self, text: str, msg_id: str | None = None) -> Message:
        return self._add(Message("xiaogua", text, msg_id=msg_id))

    def add_divider(self, text: str) -> QLabel:
        """A quiet centred line between parts of the conversation: 新的一天…"""
        self.welcome.hide()
        label = QLabel(f"—— {text} ——", objectName="divider")
        label.setAlignment(Qt.AlignHCenter)
        label.setWordWrap(True)
        self.feed_layout.addWidget(label)
        self._stick_to_end = True
        self._scroll_to_end()
        return label

    def restore(self, messages: list[dict]):
        """Show the stored conversation after a restart."""
        for message in messages:
            role, text = message.get("role"), message.get("text", "")
            ids = {"msg_id": message.get("id"), "reply_to": message.get("reply_to")}
            if role == "mine":
                self._add(Message("mine", text, msg_id=ids["msg_id"]), mine=True)
            elif role in ("xiaogua", "error"):
                self._add(Message(role, text, **ids))
            elif role == "divider":
                self.add_divider(text)

    def clear(self):
        self._flush_timer.stop()
        self.draft, self._draft_text = None, ""       # its widget goes with the rest below
        self._stop_thinking()
        while self.feed_layout.count() > 2:           # keep the stretch and the welcome block
            item = self.feed_layout.takeAt(2)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        self.welcome.show()

    def transcript(self) -> list[tuple[str, str]]:
        """(kind, text) of every message shown, for tests and debugging."""
        out = []
        for index in range(self.feed_layout.count()):
            holder = self.feed_layout.itemAt(index).widget()
            if holder is None or holder is self.welcome:
                continue
            message = holder.findChild(Message)
            if message is not None:
                out.append((message.kind, message.body.text()))
        return out

    def set_hotkey_label(self, label: str):
        self.hotkey_label = label
        self._update_welcome_hint()

    # window ---------------------------------------------------------------
    # resizing by the edges -----------------------------------------------------
    def _edges_at(self, point: QPoint):
        """The panel edges a screen point is on: a band from EDGE_OUT outside the panel (its
        shadow) to EDGE_IN inside it; near a corner the band reaches EDGE_CORNER along both sides."""
        if not self.isVisible():
            return _NO_EDGE
        rect = QRect(self.panel.mapToGlobal(QPoint(0, 0)), self.panel.size())
        if not rect.adjusted(-EDGE_OUT, -EDGE_OUT, EDGE_OUT, EDGE_OUT).contains(point):
            return _NO_EDGE
        inside = {Qt.LeftEdge: point.x() - rect.left(), Qt.RightEdge: rect.right() - point.x(),
                  Qt.TopEdge: point.y() - rect.top(), Qt.BottomEdge: rect.bottom() - point.y()}
        edges = _NO_EDGE
        for edge, distance in inside.items():
            if distance <= EDGE_IN:
                edges |= edge
        if edges:                                        # on an edge: near its ends is a corner
            for edge, distance in inside.items():
                if distance <= EDGE_CORNER:
                    edges |= edge
        return edges

    def _edge_event(self, event) -> bool:
        """Mouse events anywhere in the window: the resize arrow on the edges, and the resize
        itself. True when the event was the resize's (the widget under the mouse must not get it)."""
        point = event.globalPosition().toPoint()
        if self._resizing is not None:
            if event.type() == QEvent.MouseMove:
                self._resize_to(point)
            elif event.type() == QEvent.MouseButtonRelease:
                self._resizing = None
            return True
        edges = self._edges_at(point)
        if event.type() == QEvent.MouseMove and not event.buttons():
            shape = edge_cursor(edges)
            if shape is None:
                self.unsetCursor()
            else:
                self.setCursor(shape)
            return False
        if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton and edges:
            handle = self.windowHandle()
            if handle is None or not handle.startSystemResize(edges):     # Windows does it smoothly
                self._resizing = (edges, point, QRect(self.geometry()))
            return True
        return False

    def _resize_to(self, point: QPoint):
        """By hand, where the system cannot: move the dragged edges, keep the others put."""
        edges, start, geometry = self._resizing
        dx, dy = point.x() - start.x(), point.y() - start.y()
        rect = QRect(geometry)
        min_w, min_h = self.minimumWidth(), self.minimumHeight()
        if edges & Qt.LeftEdge:
            rect.setLeft(min(rect.left() + dx, rect.right() - min_w + 1))
        if edges & Qt.RightEdge:
            rect.setRight(max(rect.right() + dx, rect.left() + min_w - 1))
        if edges & Qt.TopEdge:
            rect.setTop(min(rect.top() + dy, rect.bottom() - min_h + 1))
        if edges & Qt.BottomEdge:
            rect.setBottom(max(rect.bottom() + dy, rect.top() + min_h - 1))
        self.setGeometry(rect)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.isVisible() and not self._placing:
            self._size_timer.start()                 # remember it once the dragging stops

    def open_beside(self, pet_geometry):
        """Show next to 小瓜 on 小瓜's own screen: left of it if there is room, else right.
        At the size the user last dragged it to (within the screen)."""
        area = screen_rect_for(pet_geometry.center())
        width, height = self.preferred_size or CHAT_SIZE
        self._placing = True
        self.resize(max(CHAT_MIN[0], min(width, area.width() - 20)),
                    max(CHAT_MIN[1], min(height, area.height() - 20)))
        self._placing = False
        x = pet_geometry.left() - self.width() + 10
        if x < area.left():
            x = pet_geometry.right() - 10
        y = pet_geometry.bottom() - self.height() + 14
        x = max(area.left(), min(x, area.right() - self.width()))
        y = max(area.top(), min(y, area.bottom() - self.height()))
        self.move(x, y)
        self.show()
        bring_to_front(self)
        self.edit.setFocus()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.header.geometry().contains(
                self.panel.mapFrom(self, event.position().toPoint())):
            self._drag = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self._drag is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, _event):
        self._drag = None
