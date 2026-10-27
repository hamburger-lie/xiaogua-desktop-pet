"""小瓜's control panel.

Every control applies at once and is saved at once: there is no Save button to
forget. The API key is the exception — it is written to Windows Credential
Manager only when "保存密钥" is pressed, and never into config.json.
"""

from __future__ import annotations

import os
import threading

from PySide6.QtCore import QEvent, QObject, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton, QScrollArea, QSlider,
                               QSpinBox, QStackedWidget, QVBoxLayout, QWidget)

import meihua

from . import config as cfg
from . import providers
from .look import (BAD, CARD_LINE, CREAM, DIVIDER, GOOD, INK, LEAF, LEAF_DARK, LINE, MUTED, PAPER, PICKED,
                   SIDEBAR, UI)
from .look import icon as _icon

ZODIAC = "鼠牛虎兔龙蛇马羊猴鸡狗猪"
NO_ZODIAC = "不设置"

# page → section → card → row (label and hint on the left, the control on the right), as in
# dsh-pet-indesktop's settings, in 小瓜's colours.
STYLE = f"""
QWidget {{ color: {INK}; font-family: 'Microsoft YaHei'; font-size: 13px; }}
QWidget#settings, QWidget#pageBody, QScrollArea, QScrollArea > QWidget {{ background: {CREAM}; border: none; }}
QListWidget#nav {{ background: {SIDEBAR}; border: none; border-right: 1px solid {CARD_LINE}; padding: 14px 0;
                   font-size: 14px; outline: 0; }}
QListWidget#nav::item {{ padding: 9px 10px; border-radius: 9px; margin: 2px 10px; }}
QListWidget#nav::item:selected {{ background: {LEAF}; color: white; }}
QListWidget#nav::item:hover:!selected {{ background: {PICKED}; }}
QLabel#title {{ font-size: 22px; font-weight: bold; }}
QLabel#subtitle {{ color: {MUTED}; font-size: 12px; }}
QLabel#section {{ color: #556B4C; font-size: 13px; font-weight: bold; }}
QFrame#card {{ background: {PAPER}; border: 1px solid {CARD_LINE}; border-radius: 12px; }}
QFrame#divider {{ background: {DIVIDER}; border: none; }}
QLabel#hint {{ color: {MUTED}; font-size: 12px; }}
QListWidget#memory {{ background: {PAPER}; border: 1px solid {LINE}; border-radius: 8px; padding: 4px;
                      font-size: 13px; outline: 0; }}
QListWidget#memory::item {{ padding: 6px 10px; margin: 1px 2px; border-radius: 6px; }}
QListWidget#memory::item:selected {{ background: {PICKED}; color: {INK}; }}
QLineEdit, QComboBox, QSpinBox, QPlainTextEdit {{ background: {PAPER}; border: 1px solid {LINE}; border-radius: 8px;
                                                  padding: 4px 8px; min-height: 22px; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QPlainTextEdit:focus {{ border: 1px solid {LEAF}; }}
QComboBox QAbstractItemView {{ background: {PAPER}; selection-background-color: {LEAF}; }}
QPushButton {{ background: {PAPER}; border: 1px solid {LINE}; border-radius: 9px; padding: 5px 14px; }}
QPushButton:hover {{ background: #EEF2E2; }}
QPushButton#primary {{ background: {LEAF}; color: white; border: none; font-weight: bold; }}
QPushButton#primary:hover {{ background: {LEAF_DARK}; }}
QPushButton#recording {{ background: #FFF6D8; border: 1px solid #D8B84A; }}
QWidget#segmented {{ background: #EEF2E2; border-radius: 9px; }}
QPushButton#segment {{ background: transparent; border: 1px solid transparent; border-radius: 7px;
                       padding: 4px 14px; }}
QPushButton#segment:hover:!checked {{ background: {PICKED}; }}
QPushButton#segment:checked {{ background: {PAPER}; border: 1px solid {CARD_LINE}; color: {LEAF_DARK};
                               font-weight: bold; }}
QSlider::groove:horizontal {{ height: 6px; background: #E3EBD2; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {LEAF}; border-radius: 3px; }}
QSlider::handle:horizontal {{ background: white; border: 2px solid {LEAF}; width: 14px; margin: -6px 0;
                              border-radius: 9px; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 38px; height: 22px; border: none; image: url({UI}/switch-off.svg); }}
QCheckBox::indicator:hover {{ image: url({UI}/switch-off-hover.svg); }}
QCheckBox::indicator:checked {{ image: url({UI}/switch-on.svg); }}
QCheckBox::indicator:checked:hover {{ image: url({UI}/switch-on-hover.svg); }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox::down-arrow {{ image: url({UI}/chevron.svg); width: 14px; height: 14px; }}
"""

PAGES = ("连接", "小瓜", "外观", "互动", "记忆", "回收站", "快捷键与启动", "关于")
CONTROL_WIDTH = 230           # combo boxes and sliders on the right of a row
BUBBLE_FONTS = ("小", "标准", "大")
CHATTER_OFTEN = ("偶尔", "常常")


class Card(QFrame):
    """A rounded white card of setting rows, a thin inset line between two rows. A row hidden for
    this choice (接口地址 for Claude, the key for Ollama) takes its line with it."""

    def __init__(self):
        super().__init__(objectName="card")
        self._rows = QVBoxLayout(self)
        self._rows.setContentsMargins(0, 2, 0, 2)
        self._rows.setSpacing(0)
        self._lines: dict[QWidget, QWidget] = {}         # row -> the line above it

    def add(self, row: QWidget) -> QWidget:
        if self._rows.count():
            line = QWidget()
            inset = QHBoxLayout(line)
            inset.setContentsMargins(14, 0, 14, 0)
            rule = QFrame(objectName="divider")
            rule.setFixedHeight(1)
            inset.addWidget(rule)
            self._rows.addWidget(line)
            self._lines[row] = line
            row.installEventFilter(self)
        self._rows.addWidget(row)
        return row

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.ShowToParent, QEvent.HideToParent) and watched in self._lines:
            self._lines[watched].setVisible(not watched.isHidden())
        return False


class Segmented(QWidget):
    """Two or three choices side by side, the chosen one raised. Reads like a QComboBox to callers."""
    currentTextChanged = Signal(str)

    def __init__(self, choices, current: str):
        super().__init__(objectName="segmented")
        self.setAttribute(Qt.WA_StyledBackground)
        row = QHBoxLayout(self)
        row.setContentsMargins(3, 3, 3, 3)
        row.setSpacing(2)
        self._group = QButtonGroup(self)
        self._buttons = {}
        for choice in choices:
            button = QPushButton(choice, objectName="segment", checkable=True, checked=choice == current)
            button.setCursor(Qt.PointingHandCursor)
            self._group.addButton(button)
            self._buttons[choice] = button
            row.addWidget(button)
        self._group.buttonToggled.connect(lambda button, on: on and self.currentTextChanged.emit(button.text()))

    def currentText(self) -> str:
        checked = self._group.checkedButton()
        return checked.text() if checked else ""

    def setCurrentText(self, text: str):
        if text in self._buttons:
            self._buttons[text].setChecked(True)


class _Signals(QObject):
    checked = Signal(bool, str, list)


# ------------------------------------------------------------ hotkeys

_SPECIAL = {Qt.Key_Space: "space", Qt.Key_Tab: "tab", Qt.Key_Return: "enter", Qt.Key_Enter: "enter",
            Qt.Key_Insert: "insert", Qt.Key_Home: "home", Qt.Key_End: "end", Qt.Key_PageUp: "page_up",
            Qt.Key_PageDown: "page_down", Qt.Key_Up: "up", Qt.Key_Down: "down", Qt.Key_Left: "left",
            Qt.Key_Right: "right", Qt.Key_Pause: "pause", Qt.Key_Print: "print_screen"}


def to_pynput(modifiers, key: int) -> str | None:
    """A Qt key press as pynput's hotkey string, or None if it is not a usable hotkey.

    A hotkey needs at least one of Ctrl/Alt/Win, unless it is a function key; a
    bare letter or Shift+letter would fire while typing in chat.
    """
    parts = []
    if modifiers & Qt.ControlModifier:
        parts.append("<ctrl>")
    if modifiers & Qt.AltModifier:
        parts.append("<alt>")
    if modifiers & Qt.ShiftModifier:
        parts.append("<shift>")
    if modifiers & Qt.MetaModifier:
        parts.append("<cmd>")
    if Qt.Key_F1 <= key <= Qt.Key_F24:
        name = f"<f{key - Qt.Key_F1 + 1}>"
    elif key in _SPECIAL:
        name = f"<{_SPECIAL[key]}>"
    elif Qt.Key_0 <= key <= Qt.Key_9 or Qt.Key_A <= key <= Qt.Key_Z:
        name = chr(key).lower()
    else:
        return None
    if not (set(parts) & {"<ctrl>", "<alt>", "<cmd>"}) and not name.startswith("<f"):
        return None
    return "+".join(parts + [name])


def plain_http_elsewhere(url: str) -> bool:
    """An http:// address on another machine: a key sent there travels unencrypted."""
    link = QUrl(url.strip())
    local = link.host().lower() in ("localhost", "127.0.0.1", "::1") or link.host().lower().endswith(".localhost")
    return link.scheme().lower() == "http" and not local


def hotkey_label(combo: str) -> str:
    """'<ctrl>+<alt>+g' -> 'Ctrl+Alt+G'."""
    names = {"cmd": "Win", "page_up": "PgUp", "page_down": "PgDn", "print_screen": "PrtSc"}
    out = []
    for part in combo.split("+"):
        bare = part.strip("<>")
        is_key = len(bare) == 1 or (bare[0] == "f" and bare[1:].isdigit())    # g, 5, f8
        out.append(names.get(bare, bare.upper() if is_key else bare.title()))
    return "+".join(out)


class HotkeyButton(QPushButton):
    """Click, then press the new combination. Esc cancels."""
    recorded = Signal(str)

    def __init__(self, combo: str):
        super().__init__(hotkey_label(combo))
        self.combo = combo
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumWidth(160)
        self.clicked.connect(self._start)

    def _start(self):
        self.setText("请按下新的组合键…（Esc 取消）")
        self.setObjectName("recording")
        self.setStyle(self.style())
        self.grabKeyboard()

    def _stop(self):
        self.releaseKeyboard()
        self.setObjectName("")
        self.setStyle(self.style())
        self.setText(hotkey_label(self.combo))

    def keyPressEvent(self, event):
        if self.keyboardGrabber() is not self:
            return super().keyPressEvent(event)
        if event.key() == Qt.Key_Escape:
            self._stop()
            return
        if event.key() in (Qt.Key_Control, Qt.Key_Alt, Qt.Key_Shift, Qt.Key_Meta):
            return                                      # wait for the real key
        combo = to_pynput(event.modifiers(), event.key())
        if combo is None:
            self.setText("要带 Ctrl / Alt / Win，或用 F1–F12")
            return
        self.combo = combo
        self._stop()
        self.recorded.emit(combo)


# ------------------------------------------------------------ window

class SettingsWindow(QWidget):
    """Emits `changed(config)` after any setting changes; `key_changed()` after the key does."""
    changed = Signal(object)
    key_changed = Signal()
    history_deleted = Signal()
    mini_requested = Signal(bool)             # the pet docks itself; it saves the setting
    memory_edited = Signal()                  # a fact was deleted here
    trash_restore = Signal(str)               # 恢复 this trash entry (the pet puts it back)

    def __init__(self, config: cfg.Config, icon: QIcon | None = None):
        super().__init__()
        self.config = config
        self.setObjectName("settings")
        self.setWindowTitle("每日一瓜 · 设置")
        if icon:
            self.setWindowIcon(icon)
        self.setStyleSheet(STYLE)
        self.setMinimumSize(720, 520)
        self.resize(820, 640)

        self.nav = QListWidget(objectName="nav")
        self.nav.setIconSize(QSize(18, 18))
        for name in PAGES:
            self.nav.addItem(QListWidgetItem(_icon(name, MUTED, "#FFFFFF"), f" {name}"))
        self.nav.setFixedWidth(176)
        self.pages = QStackedWidget()
        self.memory = None
        self._memory_stats = None
        self.trash = None
        for build in (self._connection_page, self._pet_page, self._look_page, self._play_page,
                      self._memory_page, self._trash_page, self._start_page, self._about_page):
            self.pages.addWidget(build())
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.nav.setCurrentRow(0)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.nav)
        layout.addWidget(self.pages, 1)

        self._signals = _Signals()
        self._signals.checked.connect(self._checked)
        self._untested_key = None          # (provider, key) typed in the box and being tested

    # helpers --------------------------------------------------------------
    def _page(self, title: str, subtitle: str) -> tuple[QWidget, QVBoxLayout]:
        """A scrolling page: a big title, a line under it, then sections (`_section`)."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget(objectName="pageBody")
        column = QVBoxLayout(body)
        column.setContentsMargins(30, 24, 28, 24)
        column.setSpacing(0)
        column.addWidget(QLabel(title, objectName="title"))
        column.addSpacing(4)
        note = QLabel(subtitle, objectName="subtitle")
        note.setWordWrap(True)
        column.addWidget(note)
        column.addSpacing(6)
        scroll.setWidget(body)
        return scroll, column

    def _section(self, column: QVBoxLayout, title: str = "") -> Card:
        """A titled card on the page; rows go in with `card.add(self._row(...))`."""
        column.addSpacing(18)
        if title:
            column.addWidget(QLabel(title, objectName="section"))
            column.addSpacing(7)
        card = Card()
        column.addWidget(card)
        return card

    def _row(self, label: str, control: QWidget | None = None, hint: str = "", below: bool = False,
             note: QWidget | None = None) -> QWidget:
        """One setting: its name and a grey line on the left, the control on the right (or `below`
        the words, for lists and wide editors). `note` is a widget under the words (links, a status)."""
        row = QWidget()
        outer = QVBoxLayout(row)
        outer.setContentsMargins(16, 11, 16, 11)
        outer.setSpacing(8)
        line = QHBoxLayout()
        line.setSpacing(18)
        words = QVBoxLayout()
        words.setSpacing(2)
        if label:
            words.addWidget(QLabel(label, objectName="rowLabel"))
        if hint:
            words.addWidget(self._hint(hint))
        if note is not None:
            words.addWidget(note)
        line.addLayout(words, 1)
        if control is not None and not below:
            line.addWidget(control, 0, Qt.AlignRight | Qt.AlignVCenter)
        outer.addLayout(line)
        if control is not None and below:
            outer.addWidget(control)
        return row

    def _hint(self, text: str) -> QLabel:
        label = QLabel(text, objectName="hint")
        label.setWordWrap(True)
        return label

    @staticmethod
    def _switch(on: bool, toggled) -> QCheckBox:
        switch = QCheckBox()
        switch.setCursor(Qt.PointingHandCursor)
        switch.setChecked(on)
        switch.toggled.connect(toggled)
        return switch

    @staticmethod
    def _wrap(*widgets, stretch_first: bool = True) -> QWidget:
        """Several controls side by side, as one control of a row."""
        box = QWidget()
        line = QHBoxLayout(box)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(8)
        for index, widget in enumerate(widgets):
            line.addWidget(widget, 1 if stretch_first and index == 0 else 0)
        return box

    def _set(self, name: str, value):
        if getattr(self.config, name) == value:
            return
        setattr(self.config, name, value)
        self.config.save()
        self.changed.emit(self.config)

    # 连接 -----------------------------------------------------------------
    def _connection_page(self) -> QWidget:
        page, column = self._page("连接模型", "小瓜细讲黄历、卦象要用大模型。选一家厂商、填上密钥就行（旁边有申请链接）；"
                                           "没有密钥时也能看今天的黄历、离线起卦给盘面。")
        self.provider_box = QComboBox()
        self.provider_box.setMaxVisibleItems(24)
        self.provider_box.setFixedWidth(CONTROL_WIDTH)
        model = QStandardItemModel(self.provider_box)
        for group in providers.GROUPS:
            header = QStandardItem(f"—— {group} ——")
            header.setFlags(Qt.NoItemFlags)                       # a heading, not a choice
            header.setForeground(QColor(MUTED))
            model.appendRow(header)
            for preset in providers.PROVIDERS:
                if preset.group == group:
                    item = QStandardItem(("    " + preset.name))
                    item.setData(preset.id, Qt.UserRole)
                    model.appendRow(item)
        self.provider_box.setModel(model)
        self._select_provider(self.config.provider)
        self.provider_box.currentIndexChanged.connect(self._provider_changed)
        self.provider_info = QLabel(objectName="hint")
        self.provider_info.setWordWrap(True)
        self.provider_info.setOpenExternalLinks(True)
        self.provider_info.setTextFormat(Qt.RichText)
        card = self._section(column, "厂商")
        card.add(self._row("厂商", self.provider_box, note=self.provider_info))

        self.base_url_edit = QLineEdit(placeholderText="https://…/v1")
        self.base_url_edit.editingFinished.connect(self._base_url_changed)
        reset = QPushButton("恢复默认")
        reset.clicked.connect(self._reset_base_url)
        self.base_url_row = self._wrap(self.base_url_edit, reset)
        self.base_url_label = card.add(self._row("接口地址", self.base_url_row, below=True))

        card = self._section(column, "密钥")
        self.key_source = QLabel()
        card.add(self._row("当前密钥", self.key_source))
        self.key_edit = QLineEdit(placeholderText="粘贴这家厂商的 API key")
        self.key_edit.setEchoMode(QLineEdit.Password)
        peek = QPushButton("显示")
        peek.setCheckable(True)
        peek.toggled.connect(lambda on: (self.key_edit.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password),
                                         peek.setText("隐藏" if on else "显示")))
        self.key_row = self._wrap(self.key_edit, peek)
        save = QPushButton("保存密钥", objectName="primary")
        save.clicked.connect(self._save_key)
        clear = QPushButton("清除已存密钥")
        clear.clicked.connect(self._clear_key)
        self.key_buttons = self._wrap(save, clear, stretch_first=False)
        self.key_buttons.layout().addStretch()
        entry = QWidget()
        stack = QVBoxLayout(entry)
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(8)
        stack.addWidget(self.key_row)
        stack.addWidget(self.key_buttons)
        self.key_entry = card.add(self._row("API key", entry, "每家的密钥分开存进本机的 Windows 凭据管理器，"
                                                              "不写进任何配置文件。", below=True))

        card = self._section(column, "模型")
        self.model_box = QComboBox()
        self.model_box.setEditable(True)
        self.model_box.setMaxVisibleItems(20)
        self.model_box.currentTextChanged.connect(self._model_changed)
        test = QPushButton("测试并获取模型列表")
        test.clicked.connect(self._test)
        self.check_result = QLabel()
        self.check_result.setWordWrap(True)
        tested = QWidget()
        stack = QVBoxLayout(tested)
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(6)
        stack.addWidget(self._wrap(self.model_box, test))
        stack.addWidget(self.check_result)
        card.add(self._row("模型", tested, below=True))

        card = self._section(column, "其他")
        card.add(self._row("离线模式", self._switch(self.config.offline, lambda on: self._set("offline", on)),
                           "不连模型，只看黄历和本地起卦，什么都不发出去。"))
        card.add(self._row("深度思考", self._switch(self.config.deep_thinking,
                                                    lambda on: self._set("deep_thinking", on)),
                           "模型先想再答，豆包每次要多等十来秒。"))
        column.addStretch()
        self._fetched: dict[str, list[str]] = {}
        self._refresh_provider()
        return page

    def _select_provider(self, provider_id: str):
        box = self.provider_box
        for index in range(box.count()):
            if box.itemData(index, Qt.UserRole) == provider_id:
                box.setCurrentIndex(index)
                return

    def _provider_changed(self, index: int):
        provider_id = self.provider_box.itemData(index, Qt.UserRole)
        if not provider_id:
            return
        self.key_edit.clear()
        self.check_result.clear()
        self._set("provider", provider_id)
        self._refresh_provider()

    def _refresh_provider(self):
        preset = self.config.preset
        parts = []
        if preset.key_url:
            label = "去下载" if not preset.needs_key else "去申请密钥"
            parts.append(f"<a href='{preset.key_url}' style='color:{LEAF_DARK}'>{label} ↗</a>")
        if preset.note:
            parts.append(preset.note)
        self.provider_info.setText("　".join(parts))

        openai_like = preset.kind == "openai"
        self.base_url_row.setVisible(openai_like)
        if self.base_url_label:
            self.base_url_label.setVisible(openai_like)
        self.base_url_edit.setText(self.config.base_url)
        for widget in (self.key_row, self.key_buttons, self.key_entry):
            widget.setVisible(preset.needs_key)

        self.model_box.blockSignals(True)
        self.model_box.clear()
        choices = list(dict.fromkeys(list(preset.models) + self._fetched.get(preset.id, [])))
        self.model_box.addItems(choices)
        self.model_box.setCurrentText(self.config.model)
        self.model_box.lineEdit().setPlaceholderText("填模型名，或点右边获取列表")
        self.model_box.blockSignals(False)
        self._refresh_key()

    def _model_changed(self, text: str):
        self._set("model", text.strip())

    def _base_url_changed(self):
        value = self.base_url_edit.text().strip().rstrip("/")
        preset = self.config.preset
        urls = dict(self.config.base_urls)
        if value and value != preset.base_url:
            urls[preset.id] = value
        else:
            urls.pop(preset.id, None)
        self._set("base_urls", urls)
        if value and plain_http_elsewhere(value) and preset.needs_key:
            self._show_check(False, "注意：这个地址是 http，不加密，API key 会明文发出去。"
                                    "除非是你自己电脑上的模型服务，请用 https 开头的地址。", [])

    def _reset_base_url(self):
        self.base_url_edit.setText(self.config.preset.base_url)
        self._base_url_changed()

    def _refresh_key(self):
        preset = self.config.preset
        key, source = cfg.api_key(preset.id)
        if not preset.needs_key:
            self.key_source.setText(source)
            self.key_source.setStyleSheet(f"color: {GOOD};")
            return
        self.key_source.setText(f"{source}（{cfg.mask(key)}）" if key else "未设置")
        self.key_source.setStyleSheet(f"color: {GOOD if key else BAD};")

    def _save_key(self):
        key = self.key_edit.text().strip()
        preset = self.config.preset
        if not key:
            self._show_check(False, "先把密钥粘贴进来", [])
            return
        try:
            cfg.store_api_key(key, preset.id)
        except OSError as error:
            self._show_check(False, f"没存上：{error}", [])
            return
        self.key_edit.clear()
        self._refresh_key()
        self._show_check(True, f"{preset.name} 的密钥已保存", [])
        self.key_changed.emit()
        if preset.env and os.environ.get(preset.env):
            self._show_check(True, f"已保存；但环境变量 {preset.env} 也设了，目前用的是环境变量里的那个", [])

    def _clear_key(self):
        cfg.delete_api_key(self.config.provider)
        self._refresh_key()
        self._show_check(True, "已清除保存的密钥", [])
        self.key_changed.emit()

    def _test(self):
        preset = self.config.preset
        typed = self.key_edit.text().strip()
        key = typed or cfg.api_key(preset.id)[0]
        self._untested_key = (preset.id, typed) if typed else None
        if preset.needs_key and not key:
            self._show_check(False, "还没有密钥可测", [])
            return
        self.check_result.setStyleSheet(f"color: {MUTED};")
        self.check_result.setText("正在连接…")
        model, base_url, provider_id = self.model_box.currentText().strip(), self.config.base_url, preset.id

        def work():
            from .agent import check_connection
            ok, message, available = check_connection(key, model, provider_id, base_url)
            self._signals.checked.emit(ok, message, [provider_id] + available)
        threading.Thread(target=work, daemon=True).start()

    def _checked(self, ok: bool, message: str, available: list):
        """The test is back. A key that was only typed in the box (not saved) and works is saved now:
        「连上了」 and still offline, because 保存密钥 was never pressed, was a trap."""
        pending, self._untested_key = self._untested_key, None
        if ok and pending and pending[0] == self.config.provider and self.key_edit.text().strip() == pending[1]:
            try:
                cfg.store_api_key(pending[1], pending[0])
            except OSError as error:
                message += f"；但密钥没存上：{error}"
            else:
                self.key_edit.clear()
                self._refresh_key()
                message += "；密钥也已保存，小瓜现在就能用"
                self.key_changed.emit()
        elif not ok and pending:
            message += "（这个密钥还没保存）"
        self._show_check(ok, message, available)

    def _show_check(self, ok: bool, message: str, available: list):
        self.check_result.setStyleSheet(f"color: {GOOD if ok else BAD};")
        self.check_result.setText(message)
        if len(available) > 1:
            provider_id, models = available[0], sorted(set(available[1:]))
            self._fetched[provider_id] = models
            if provider_id == self.config.provider:
                self._refresh_provider()
                self.check_result.setText(message)
                self.check_result.setStyleSheet(f"color: {GOOD if ok else BAD};")

    # 小瓜 -----------------------------------------------------------------
    def _slider(self, low, high, value, suffix, name, step=1) -> tuple[QSlider, QWidget]:
        slider = QSlider(Qt.Horizontal)
        slider.setRange(low, high)
        slider.setSingleStep(step)
        slider.setValue(value)
        label = QLabel(f"{value}{suffix}")
        label.setMinimumWidth(50)
        label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        slider.valueChanged.connect(lambda v: (label.setText(f"{v}{suffix}"), self._set(name, v)))
        box = self._wrap(slider, label)
        box.setFixedWidth(CONTROL_WIDTH + 40)
        return slider, box

    def _choice(self, choices, current: str, name: str) -> Segmented:
        box = Segmented(choices, current)
        box.currentTextChanged.connect(lambda text: self._set(name, text))
        return box

    def _pet_page(self) -> QWidget:
        page, column = self._page("小瓜", "它怎么跟你说话、什么时候开口。改动立刻生效。")
        card = self._section(column, "说话")
        self.style_box = self._choice(["直白", "平衡", "玄一点"], self.config.voice_style, "voice_style")
        card.add(self._row("说话风格", self.style_box, "直白：一句结论加一句为什么。平衡：先给结论，再用大白话说为什么。"
                                                      "玄一点：多一分老黄历的味道。下一个问题起生效。"))
        self.proactive_box = self._choice(["正常", "少", "关"], self.config.proactive, "proactive")
        card.add(self._row("主动说话", self.proactive_box, "正常：每天第一句、计划到期、深夜被叫醒时会冒个泡，"
                                                          "闲着时偶尔随口说两句。少：只提醒你的计划。"
                                                          "关：只在你问的时候说话（你让它定的闹钟照样会响）。"))
        self.greet_box = self._switch(self.config.greet_on_start, lambda on: self._set("greet_on_start", on))
        card.add(self._row("启动时打个招呼", self.greet_box))

        card = self._section(column, "关于你")
        self.zodiac_box = QComboBox()
        self.zodiac_box.addItems([NO_ZODIAC] + list(ZODIAC))
        self.zodiac_box.setCurrentText(self.config.zodiac or NO_ZODIAC)
        self.zodiac_box.setFixedWidth(120)
        self.zodiac_box.currentTextChanged.connect(
            lambda text: self._set("zodiac", "" if text == NO_ZODIAC else text))
        card.add(self._row("你的属相", self.zodiac_box, "看黄历时用：今天冲不冲你、哪个时辰对你好。只存在本机；"
                                                        "在对话里说「我属虎」也会记住。"))
        column.addStretch()
        return page

    def _look_page(self) -> QWidget:
        page, column = self._page("外观", "小瓜和它头顶的气泡长什么样。大小也可以在小瓜身上按住 Ctrl 滚滚轮。")
        card = self._section(column, "小瓜")
        self.size_slider, box = self._slider(100, 400, self.config.pet_size, " px", "pet_size", 10)
        card.add(self._row("大小", box))
        self.opacity_slider, box = self._slider(30, 100, self.config.opacity, " %", "opacity", 5)
        card.add(self._row("不透明度", box, "调低一点，小瓜就不那么抢眼。"))
        self.on_top_box = self._switch(self.config.always_on_top, lambda on: self._set("always_on_top", on))
        card.add(self._row("总在最前面", self.on_top_box, "关掉后，别的窗口可以盖住小瓜。"))
        self.mini_box = self._switch(self.config.mini, lambda on: self.mini_requested.emit(on))
        card.add(self._row("缩成贴边小球", self.mini_box, "不挡屏幕；有回答时小球会闪一下。"))

        card = self._section(column, "气泡")
        self.bubble_font_box = self._choice(BUBBLE_FONTS, self.config.bubble_font, "bubble_font")
        card.add(self._row("气泡字号", self.bubble_font_box, "小瓜头顶气泡里的字，看着费劲就调大。"))
        column.addStretch()
        return page

    def _play_page(self) -> QWidget:
        page, column = self._page("互动", "拖它、点它、它闲着的时候。改动立刻生效。")
        card = self._section(column, "拖动与点击")
        self.lock_box = self._switch(self.config.lock_position, lambda on: self._set("lock_position", on))
        card.add(self._row("锁定位置", self.lock_box, "拖不动小瓜，免得不小心挪走；点它照样能问。"
                                                      "右键小瓜也能开关。"))
        self.click_through = self._switch(self.config.click_through, lambda on: self._set("click_through", on))
        card.add(self._row("鼠标穿透", self.click_through, "点击直接穿过小瓜，看视频、打字时不挡操作。"
                                                           "开启后点不到小瓜了：叫它用快捷键，关掉穿透用右下角托盘图标。"))

        card = self._section(column, "随口说两句")
        self.chatter_box = self._switch(self.config.chatter, lambda on: self._set("chatter", on))
        card.add(self._row("闲着时说两句", self.chatter_box, "小瓜待着没事时偶尔冒一句：今天宜什么、哪个时辰好、"
                                                            "快到的节日，或者叫你喝口水。主动说话选「正常」才说，夜里不说。"))
        self.chatter_often_box = self._choice(CHATTER_OFTEN, self.config.chatter_often, "chatter_often")
        card.add(self._row("多久一次", self.chatter_often_box, "偶尔：半小时上下一句。常常：十来分钟一句。"))
        self.chatter_edit = QPlainTextEdit("\n".join(self.config.chatter_lines))
        self.chatter_edit.setPlaceholderText("一行一句，比如：\n记得站起来走走\n今天也辛苦啦\n留空就用小瓜自己的话")
        self.chatter_edit.setFixedHeight(110)
        self._chatter_timer = QTimer(self, singleShot=True, interval=600)
        self._chatter_timer.timeout.connect(self._save_chatter_lines)
        self.chatter_edit.textChanged.connect(self._chatter_timer.start)
        card.add(self._row("自己写的话", self.chatter_edit, "写了就只说你写的；一行一句。", below=True))

        card = self._section(column, "作息")
        sleep = QSpinBox(suffix=" 分钟", minimum=1, maximum=240, value=self.config.sleep_minutes)
        sleep.valueChanged.connect(lambda v: self._set("sleep_minutes", v))
        sleep.setFixedWidth(120)
        card.add(self._row("没动静多久睡觉", sleep, "夜里 11 点以后两分钟就睡。"))
        bubble = QSpinBox(suffix=" 秒", minimum=3, maximum=600, value=self.config.bubble_seconds)
        bubble.valueChanged.connect(lambda v: self._set("bubble_seconds", v))
        bubble.setFixedWidth(120)
        card.add(self._row("回答后多久回到待机", bubble))
        column.addStretch()
        return page

    def _save_chatter_lines(self):
        lines = [line.strip() for line in self.chatter_edit.toPlainText().splitlines() if line.strip()]
        self._set("chatter_lines", lines[:50])

    def sync_from(self, config: cfg.Config):
        """Reflect changes made elsewhere (Ctrl+wheel, tray, 小瓜's menu) without re-emitting them."""
        for widget, value in ((self.size_slider, config.pet_size), (self.opacity_slider, config.opacity)):
            widget.blockSignals(True)
            widget.setValue(value)
            widget.blockSignals(False)
            widget.valueChanged.emit(value)                 # updates the label; _set is a no-op
        for box, value in ((self.click_through, config.click_through), (self.mini_box, config.mini),
                           (self.lock_box, config.lock_position), (self.on_top_box, config.always_on_top)):
            box.blockSignals(True)
            box.setChecked(value)
            box.blockSignals(False)
        self.zodiac_box.blockSignals(True)
        self.zodiac_box.setCurrentText(config.zodiac or NO_ZODIAC)
        self.zodiac_box.blockSignals(False)

    # 记忆 -----------------------------------------------------------------
    def _memory_page(self) -> QWidget:
        page, column = self._page("小瓜记得的你", "你在对话里让小瓜记下的事：称呼、偏好、带日期的计划。"
                                  "只存在本机；属相在「小瓜」页改。")
        self.memory_stats = self._hint("")
        column.addSpacing(6)
        column.addWidget(self.memory_stats)
        card = self._section(column)
        self.memory_list = QListWidget(objectName="memory")
        self.memory_list.setMinimumHeight(260)
        self.memory_list.setSelectionMode(QListWidget.ExtendedSelection)
        forget = QPushButton("删掉选中的")
        forget.clicked.connect(self._forget_selected)
        self.forget_all_button = QPushButton("全部忘掉")
        self.forget_all_button.clicked.connect(self._forget_all)
        buttons = self._wrap(forget, self.forget_all_button, stretch_first=False)
        buttons.layout().addStretch()
        stack = QWidget()
        lines = QVBoxLayout(stack)
        lines.setContentsMargins(0, 0, 0, 0)
        lines.setSpacing(8)
        lines.addWidget(self.memory_list)
        lines.addWidget(buttons)
        self.memory_status = self._hint("在对话里说「叫我老王」「我周五面试」，小瓜就会记下；"
                                        "到了那天早上提醒你，过了会问一句结果。")
        lines.addWidget(self.memory_status)
        card.add(self._row("", stack, below=True))
        column.addStretch()
        return page

    def set_memory(self, memory, stats=None):
        self.memory, self._memory_stats = memory, stats
        self.refresh_memory()

    def refresh_memory(self):
        from datetime import date

        from PySide6.QtWidgets import QListWidgetItem

        self.memory_list.clear()
        facts = self.memory.facts if self.memory is not None else []
        for fact in facts:
            item = QListWidgetItem(fact.label(date.today()))
            item.setData(Qt.UserRole, fact.id)
            self.memory_list.addItem(item)
        if not facts:
            empty = QListWidgetItem("还没记下什么。")
            empty.setFlags(Qt.NoItemFlags)
            self.memory_list.addItem(empty)
        stats = self._memory_stats() if self._memory_stats else None
        self.memory_stats.setText(stats or "")
        self.forget_all_button.setText("全部忘掉")

    def _forget_selected(self):
        if self.memory is None:
            return
        ids = [item.data(Qt.UserRole) for item in self.memory_list.selectedItems() if item.data(Qt.UserRole)]
        for fact_id in ids:
            self.memory.forget(fact_id)
        self.refresh_memory()
        self.refresh_trash()
        if ids:
            self.memory_status.setText(f"删掉了 {len(ids)} 条。")
            self.memory_edited.emit()

    def _forget_all(self):
        if self.memory is None:
            return
        if self.forget_all_button.text() == "全部忘掉":
            self.forget_all_button.setText("再点一次确认")          # no modal dialog: one more click
            return
        count = self.memory.clear()
        self.refresh_memory()
        self.refresh_trash()
        self.memory_status.setText(f"已忘掉 {count} 条。")
        self.memory_edited.emit()

    # 回收站 ----------------------------------------------------------------
    def _trash_page(self) -> QWidget:
        page, column = self._page("回收站", "删掉的对话和「小瓜记得的你」里删掉的条目，在这里放 30 天，"
                                  "到期自动彻底删除。小瓜删的时候就已经忘掉了；对话里你说过的原话也存在这里，"
                                  "想马上清掉就点「彻底删除」。")
        card = self._section(column)
        self.trash_list = QListWidget(objectName="memory")
        self.trash_list.setMinimumHeight(260)
        self.trash_list.setSelectionMode(QListWidget.ExtendedSelection)
        restore = QPushButton("恢复选中的")
        restore.clicked.connect(self._restore_selected)
        drop = QPushButton("彻底删除选中的")
        drop.clicked.connect(self._drop_selected)
        self.empty_trash_button = QPushButton("清空回收站")
        self.empty_trash_button.clicked.connect(self._empty_trash)
        buttons = self._wrap(restore, drop, self.empty_trash_button, stretch_first=False)
        buttons.layout().addStretch()
        stack = QWidget()
        lines = QVBoxLayout(stack)
        lines.setContentsMargins(0, 0, 0, 0)
        lines.setSpacing(8)
        lines.addWidget(self.trash_list)
        lines.addWidget(buttons)
        self.trash_status = self._hint("对话恢复后回到对话列表；单条消息删了不进回收站。")
        lines.addWidget(self.trash_status)
        card.add(self._row("", stack, below=True))
        column.addStretch()
        return page

    def set_trash(self, trash):
        self.trash = trash
        self.refresh_trash()

    def refresh_trash(self):
        from PySide6.QtWidgets import QListWidgetItem

        self.trash_list.clear()
        entries = self.trash.list() if self.trash is not None else []
        for entry in entries:
            when = entry["deleted"]
            item = QListWidgetItem(f"{entry['kind']}｜{entry['title']}　"
                                   f"{when.month}月{when.day}日删，{entry['days_left']} 天后彻底删除")
            item.setData(Qt.UserRole, entry["id"])
            self.trash_list.addItem(item)
        if not entries:
            empty = QListWidgetItem("回收站是空的。")
            empty.setFlags(Qt.NoItemFlags)
            self.trash_list.addItem(empty)
        self.empty_trash_button.setText("清空回收站")

    def _selected_trash(self) -> list[str]:
        return [item.data(Qt.UserRole) for item in self.trash_list.selectedItems() if item.data(Qt.UserRole)]

    def _restore_selected(self):
        ids = self._selected_trash()
        for entry_id in ids:
            self.trash_restore.emit(entry_id)
        self.refresh_trash()
        if ids:
            self.trash_status.setText(f"恢复了 {len(ids)} 条。")

    def _drop_selected(self):
        ids = self._selected_trash()
        for entry_id in ids:
            self.trash.drop(entry_id)
        self.refresh_trash()
        if ids:
            self.trash_status.setText(f"彻底删除了 {len(ids)} 条。")

    def _empty_trash(self):
        if self.trash is None:
            return
        if self.empty_trash_button.text() == "清空回收站":
            self.empty_trash_button.setText("再点一次确认")          # no modal dialog: one more click
            return
        count = self.trash.clear()
        self.refresh_trash()
        self.trash_status.setText(f"彻底删除了 {count} 条。")

    # 快捷键与启动 ----------------------------------------------------------
    def _start_page(self) -> QWidget:
        page, column = self._page("快捷键与启动", "快捷键全局有效，在别的窗口里也能按。")
        card = self._section(column, "快捷键")
        self.hotkey_button = HotkeyButton(self.config.hotkey)
        self.hotkey_button.recorded.connect(lambda combo: self._set("hotkey", combo))
        card.add(self._row("叫出小瓜", self.hotkey_button, "按一下，小瓜头顶冒出输入框，打字回车就问，回答也冒在气泡里；"
                                                           "再按一下收起；单击小瓜也一样。完整对话：右键小瓜 →「打开对话」。"))
        self.voice_button = HotkeyButton(self.config.voice_hotkey)
        self.voice_button.recorded.connect(lambda combo: self._set("voice_hotkey", combo))
        card.add(self._row("按键说话", self.voice_button, "按一下开始说（用 Windows 自带的语音输入，第一次要在系统里"
                                                          "允许麦克风），说完再按一下就发给小瓜。小瓜回答时按它会先打断。"))
        self.hotkey_status = self._hint("点一下按钮，再按新的组合键。")
        column.addSpacing(6)
        column.addWidget(self.hotkey_status)

        card = self._section(column, "启动")
        self.autostart = self._switch(cfg.autostart_enabled(), self._toggle_autostart)
        self.autostart_status = self._hint("")
        card.add(self._row("开机自动启动", self.autostart, "启动后安静待在桌面上。", note=self.autostart_status))
        column.addStretch()
        return page

    def hotkey_failed(self, message: str):
        self.hotkey_status.setText(message)
        self.hotkey_status.setStyleSheet(f"color: {BAD}; font-size: 12px;")

    def hotkey_ok(self):
        self.hotkey_status.setText("点一下按钮，再按新的组合键。")
        self.hotkey_status.setStyleSheet("")

    def _toggle_autostart(self, on: bool):
        try:
            cfg.set_autostart(on)
            self.autostart_status.setText("已加入开机启动" if on else "已取消开机启动")
            self.autostart_status.setStyleSheet(f"color: {GOOD}; font-size: 12px;")
        except OSError as error:
            # Say so plainly: a silently failed autostart is worse than none.
            self.autostart.blockSignals(True)
            self.autostart.setChecked(cfg.autostart_enabled())
            self.autostart.blockSignals(False)
            self.autostart_status.setText(f"没设置成功：{error}")
            self.autostart_status.setStyleSheet(f"color: {BAD}; font-size: 12px;")

    # 关于 -----------------------------------------------------------------
    def _about_page(self) -> QWidget:
        page, column = self._page("关于每日一瓜", "看黄历、问个事的桌面小参谋，陪你的是小瓜。黄历和卦只当参考，"
                                  "拿主意还是你自己。")
        card = self._section(column, "这台电脑上的小瓜")
        card.add(self._row("版本", QLabel(meihua.__version__)))
        for label, folder in (("配置文件夹", cfg.home()), ("日志文件夹", cfg.log_dir())):
            button = QPushButton("打开")
            button.clicked.connect(lambda _=False, f=folder: QDesktopServices.openUrl(QUrl.fromLocalFile(str(f))))
            path = self._hint(str(folder))
            path.setTextInteractionFlags(Qt.TextSelectableByMouse)
            card.add(self._row(label, button, note=path))

        card = self._section(column, "对话记录")
        keep = self._switch(self.config.keep_history, lambda on: self._set("keep_history", on))
        self.history_status = self._hint("小瓜记下聊过的对话，重启后接着聊；关掉就只在内存里记。")
        card.add(self._row("保存对话记录", keep, "只存文字。", note=self.history_status))
        folder_button = QPushButton("打开记录文件夹")
        folder_button.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(cfg.history_dir().resolve()))))
        delete_button = QPushButton("删除全部记录")
        delete_button.clicked.connect(self._delete_history)
        card.add(self._row("记录文件", self._wrap(folder_button, delete_button, stretch_first=False)))

        card = self._section(column, "隐私")
        terms = QPushButton("查看使用协议与隐私说明")
        terms.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(meihua.ROOT / "PRIVACY.txt"))))
        card.add(self._row("你的话去了哪", terms, "你问的话只发给你选的模型厂商；记录、记忆和密钥都只存在这台电脑上。"))
        column.addStretch()
        return page

    def _delete_history(self):
        from .session import forget_everything

        self.history_deleted.emit()                   # the app clears the live chat first
        count = forget_everything(cfg.history_dir())
        if self.trash is not None:
            self.trash.clear()                        # the deleted conversations kept there go too
            self.refresh_trash()
        self.history_status.setText(f"已删除 {count} 个记录文件，回收站也清空了。")
        self.history_status.setStyleSheet(f"color: {GOOD}; font-size: 12px;")

    def closeEvent(self, event):
        event.ignore()          # closing the panel only hides it; the pet keeps running
        self.hide()

