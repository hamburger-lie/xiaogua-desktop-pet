"""小瓜's control panel.

Every control applies at once and is saved at once: there is no Save button to
forget. The API key is the exception — it is written to Windows Credential
Manager only when "保存密钥" is pressed, and never into config.json.
"""

from __future__ import annotations

import os
import threading

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QPushButton, QSlider, QSpinBox, QStackedWidget,
                               QVBoxLayout, QWidget)

import meihua

from . import config as cfg
from . import providers

CREAM, PAPER, INK, LEAF, LEAF_DARK, LINE, MUTED = (
    "#FAF8F0", "#FFFFFF", "#2F4737", "#8FAE72", "#6E8F55", "#B7C69B", "#8C9687")
GOOD, BAD = "#5E8C4A", "#B5533C"
UI = (meihua.ROOT / "assets" / "ui").as_posix()      # icons for the stylesheet

ZODIAC = "鼠牛虎兔龙蛇马羊猴鸡狗猪"
NO_ZODIAC = "不设置"

STYLE = f"""
QWidget {{ background: {CREAM}; color: {INK}; font-family: 'Microsoft YaHei'; font-size: 13px; }}
QListWidget {{ background: #F1F4E6; border: none; border-right: 1px solid {LINE}; padding-top: 10px;
               font-size: 14px; outline: 0; }}
QListWidget::item {{ padding: 10px 18px; border-radius: 8px; margin: 2px 8px; }}
QListWidget::item:selected {{ background: {LEAF}; color: white; }}
QListWidget::item:hover:!selected {{ background: #E3EBD2; }}
QLabel#title {{ font-size: 18px; font-weight: bold; }}
QListWidget#memory {{ background: {PAPER}; border: 1px solid {LINE}; border-radius: 8px; padding: 4px;
                      font-size: 13px; }}
QListWidget#memory::item {{ padding: 6px 10px; margin: 1px 2px; }}
QLabel#hint {{ color: {MUTED}; font-size: 12px; }}
QLineEdit, QComboBox, QSpinBox {{ background: {PAPER}; border: 1px solid {LINE}; border-radius: 8px;
                                  padding: 5px 8px; min-height: 20px; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border: 1px solid {LEAF}; }}
QComboBox QAbstractItemView {{ background: {PAPER}; selection-background-color: {LEAF}; }}
QPushButton {{ background: {PAPER}; border: 1px solid {LINE}; border-radius: 10px; padding: 5px 14px; }}
QPushButton:hover {{ background: #EEF2E2; }}
QPushButton#primary {{ background: {LEAF}; color: white; border: none; font-weight: bold; }}
QPushButton#primary:hover {{ background: {LEAF_DARK}; }}
QPushButton#recording {{ background: #FFF6D8; border: 1px solid #D8B84A; }}
QSlider::groove:horizontal {{ height: 6px; background: #E3EBD2; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {LEAF}; border-radius: 3px; }}
QSlider::handle:horizontal {{ background: white; border: 2px solid {LEAF}; width: 14px; margin: -6px 0;
                              border-radius: 9px; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {LINE}; border-radius: 4px;
                        background: {PAPER}; }}
QCheckBox::indicator:hover {{ border: 1px solid {LEAF}; }}
QCheckBox::indicator:checked {{ background: {LEAF}; border: 1px solid {LEAF}; image: url({UI}/check.svg); }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox::down-arrow {{ image: url({UI}/chevron.svg); width: 14px; height: 14px; }}
"""

PAGES = ("连接", "小瓜", "记忆", "回收站", "快捷键与启动", "关于")


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
        self.setWindowTitle("每日一瓜 · 设置")
        if icon:
            self.setWindowIcon(icon)
        self.setStyleSheet(STYLE)
        self.resize(720, 600)

        self.nav = QListWidget()
        self.nav.addItems(PAGES)
        self.nav.setFixedWidth(150)
        self.pages = QStackedWidget()
        self.memory = None
        self._memory_stats = None
        self.trash = None
        for build in (self._connection_page, self._pet_page, self._memory_page, self._trash_page,
                      self._start_page, self._about_page):
            self.pages.addWidget(build())
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.nav.setCurrentRow(0)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.nav)
        layout.addWidget(self.pages, 1)

        self._signals = _Signals()
        self._signals.checked.connect(self._show_check)

    # helpers --------------------------------------------------------------
    def _page(self, title: str, subtitle: str) -> tuple[QWidget, QFormLayout]:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(26, 22, 26, 20)
        heading = QLabel(title, objectName="title")
        note = QLabel(subtitle, objectName="hint")
        note.setWordWrap(True)
        outer.addWidget(heading)
        outer.addWidget(note)
        outer.addSpacing(10)
        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(12)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        outer.addLayout(form)
        outer.addStretch()
        return page, form

    def _hint(self, text: str) -> QLabel:
        label = QLabel(text, objectName="hint")
        label.setWordWrap(True)
        return label

    def _set(self, name: str, value):
        if getattr(self.config, name) == value:
            return
        setattr(self.config, name, value)
        self.config.save()
        self.changed.emit(self.config)

    # 连接 -----------------------------------------------------------------
    def _connection_page(self) -> QWidget:
        page, form = self._page("连接模型", "小瓜细讲黄历、卦象要用大模型。选一家厂商、填上密钥就行（旁边有申请链接）；"
                                         "没有密钥时也能看今天的黄历、离线起卦给盘面。")
        self.provider_box = QComboBox()
        self.provider_box.setMaxVisibleItems(24)
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
        form.addRow("厂商", self.provider_box)
        self.provider_info = QLabel(objectName="hint")
        self.provider_info.setWordWrap(True)
        self.provider_info.setOpenExternalLinks(True)
        self.provider_info.setTextFormat(Qt.RichText)
        form.addRow("", self.provider_info)

        self.base_url_edit = QLineEdit(placeholderText="https://…/v1")
        self.base_url_edit.editingFinished.connect(self._base_url_changed)
        reset = QPushButton("恢复默认")
        reset.clicked.connect(self._reset_base_url)
        self.base_url_row = QWidget()
        row = QHBoxLayout(self.base_url_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.base_url_edit, 1)
        row.addWidget(reset)
        form.addRow("接口地址", self.base_url_row)
        self.base_url_label = form.labelForField(self.base_url_row)

        self.key_source = QLabel()
        form.addRow("当前密钥", self.key_source)
        self.key_edit = QLineEdit(placeholderText="粘贴这家厂商的 API key")
        self.key_edit.setEchoMode(QLineEdit.Password)
        peek = QPushButton("显示")
        peek.setCheckable(True)
        peek.toggled.connect(lambda on: (self.key_edit.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password),
                                         peek.setText("隐藏" if on else "显示")))
        self.key_row = QWidget()
        row = QHBoxLayout(self.key_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.key_edit, 1)
        row.addWidget(peek)
        form.addRow("API key", self.key_row)
        save = QPushButton("保存密钥", objectName="primary")
        save.clicked.connect(self._save_key)
        clear = QPushButton("清除已存密钥")
        clear.clicked.connect(self._clear_key)
        self.key_buttons = QWidget()
        buttons = QHBoxLayout(self.key_buttons)
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.addWidget(save)
        buttons.addWidget(clear)
        buttons.addStretch()
        form.addRow("", self.key_buttons)
        form.addRow("", self._hint("每家的密钥分开存进本机的 Windows 凭据管理器，不写进任何配置文件。"))

        self.model_box = QComboBox()
        self.model_box.setEditable(True)
        self.model_box.setMaxVisibleItems(20)
        self.model_box.currentTextChanged.connect(self._model_changed)
        test = QPushButton("测试并获取模型列表")
        test.clicked.connect(self._test)
        row = QHBoxLayout()
        row.addWidget(self.model_box, 1)
        row.addWidget(test)
        form.addRow("模型", row)
        self.check_result = QLabel()
        self.check_result.setWordWrap(True)
        form.addRow("", self.check_result)

        offline = QCheckBox("离线模式：不连模型，只看黄历和本地起卦，什么都不发出去")
        offline.setChecked(self.config.offline)
        offline.toggled.connect(lambda on: self._set("offline", on))
        form.addRow("", offline)
        deep = QCheckBox("深度思考：模型先想再答（豆包每次要多等十来秒）")
        deep.setChecked(self.config.deep_thinking)
        deep.toggled.connect(lambda on: self._set("deep_thinking", on))
        form.addRow("", deep)
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
        for widget in (self.key_row, self.key_buttons):
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
        key = self.key_edit.text().strip() or cfg.api_key(preset.id)[0]
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
    def _slider(self, low, high, value, suffix, name, step=1):
        slider = QSlider(Qt.Horizontal)
        slider.setRange(low, high)
        slider.setSingleStep(step)
        slider.setValue(value)
        label = QLabel(f"{value}{suffix}")
        label.setMinimumWidth(52)
        slider.valueChanged.connect(lambda v: (label.setText(f"{v}{suffix}"), self._set(name, v)))
        row = QHBoxLayout()
        row.addWidget(slider, 1)
        row.addWidget(label)
        return slider, row

    def _pet_page(self) -> QWidget:
        page, form = self._page("小瓜本体", "改动立刻生效。大小也可以在小瓜身上按住 Ctrl 滚滚轮。")
        self.style_box = QComboBox()
        self.style_box.addItems(["直白", "平衡", "玄一点"])
        self.style_box.setCurrentText(self.config.voice_style)
        self.style_box.currentTextChanged.connect(lambda text: self._set("voice_style", text))
        form.addRow("说话风格", self.style_box)
        form.addRow("", self._hint("直白：一句结论加一句为什么，不绕弯。平衡：先给结论，再用大白话说为什么。"
                                   "玄一点：多一分老黄历的味道和比喻。下一个问题起生效。"))
        self.proactive_box = QComboBox()
        self.proactive_box.addItems(["正常", "少", "关"])
        self.proactive_box.setCurrentText(self.config.proactive)
        self.proactive_box.currentTextChanged.connect(lambda text: self._set("proactive", text))
        form.addRow("主动说话", self.proactive_box)
        form.addRow("", self._hint("正常：每天第一句、计划到期、深夜被叫醒时会冒个泡。"
                                   "少：只提醒你的计划。关：只在你问的时候说话（你让它定的闹钟照样会响）。"))
        self.mini_box = QCheckBox("缩成贴边小球（不挡屏幕，有回答时会闪一下）")
        self.mini_box.setChecked(self.config.mini)
        self.mini_box.toggled.connect(lambda on: self.mini_requested.emit(on))
        form.addRow("", self.mini_box)
        self.zodiac_box = QComboBox()
        self.zodiac_box.addItems([NO_ZODIAC] + list(ZODIAC))
        self.zodiac_box.setCurrentText(self.config.zodiac or NO_ZODIAC)
        self.zodiac_box.currentTextChanged.connect(
            lambda text: self._set("zodiac", "" if text == NO_ZODIAC else text))
        form.addRow("你的属相", self.zodiac_box)
        form.addRow("", self._hint("看黄历时用：今天冲不冲你、哪个时辰对你好。只存在本机；在对话里说「我属虎」也会记住。"))
        self.size_slider, row = self._slider(100, 400, self.config.pet_size, " px", "pet_size", 10)
        form.addRow("大小", row)
        self.opacity_slider, row = self._slider(30, 100, self.config.opacity, " %", "opacity", 5)
        form.addRow("不透明度", row)

        self.click_through = QCheckBox("鼠标穿透：点击直接穿过小瓜（看视频、打字时不挡操作）")
        self.click_through.setChecked(self.config.click_through)
        self.click_through.toggled.connect(lambda on: self._set("click_through", on))
        form.addRow("", self.click_through)
        form.addRow("", self._hint("开启后点不到小瓜了：叫小瓜用快捷键，关闭穿透请用右下角托盘图标。"))
        on_top = QCheckBox("总在最前面")
        on_top.setChecked(self.config.always_on_top)
        on_top.toggled.connect(lambda on: self._set("always_on_top", on))
        form.addRow("", on_top)

        sleep = QSpinBox(suffix=" 分钟", minimum=1, maximum=240, value=self.config.sleep_minutes)
        sleep.valueChanged.connect(lambda v: self._set("sleep_minutes", v))
        form.addRow("没动静多久睡觉", sleep)
        bubble = QSpinBox(suffix=" 秒", minimum=3, maximum=600, value=self.config.bubble_seconds)
        bubble.valueChanged.connect(lambda v: self._set("bubble_seconds", v))
        form.addRow("回答后多久回到待机", bubble)
        greet = QCheckBox("启动时打个招呼")
        greet.setChecked(self.config.greet_on_start)
        greet.toggled.connect(lambda on: self._set("greet_on_start", on))
        form.addRow("", greet)
        return page

    def sync_from(self, config: cfg.Config):
        """Reflect changes made elsewhere (Ctrl+wheel, tray) without re-emitting them."""
        for widget, value in ((self.size_slider, config.pet_size), (self.opacity_slider, config.opacity)):
            widget.blockSignals(True)
            widget.setValue(value)
            widget.blockSignals(False)
            widget.valueChanged.emit(value)                 # updates the label; _set is a no-op
        self.click_through.blockSignals(True)
        self.click_through.setChecked(config.click_through)
        self.click_through.blockSignals(False)
        self.zodiac_box.blockSignals(True)
        self.zodiac_box.setCurrentText(config.zodiac or NO_ZODIAC)
        self.zodiac_box.blockSignals(False)
        self.mini_box.blockSignals(True)
        self.mini_box.setChecked(config.mini)
        self.mini_box.blockSignals(False)

    # 记忆 -----------------------------------------------------------------
    def _memory_page(self) -> QWidget:
        page, form = self._page("小瓜记得的你", "你在对话里让小瓜记下的事：称呼、偏好、带日期的计划。"
                                "只存在本机；属相在「小瓜」页改。")
        self.memory_stats = self._hint("")
        form.addRow(self.memory_stats)
        self.memory_list = QListWidget(objectName="memory")
        self.memory_list.setMinimumHeight(230)
        self.memory_list.setSelectionMode(QListWidget.ExtendedSelection)
        form.addRow(self.memory_list)
        forget = QPushButton("删掉选中的")
        forget.clicked.connect(self._forget_selected)
        self.forget_all_button = QPushButton("全部忘掉")
        self.forget_all_button.clicked.connect(self._forget_all)
        row = QHBoxLayout()
        row.addWidget(forget)
        row.addWidget(self.forget_all_button)
        row.addStretch()
        form.addRow(row)
        self.memory_status = self._hint("在对话里说「叫我老王」「我周五面试」，小瓜就会记下；"
                                        "到了那天早上提醒你，过了会问一句结果。")
        form.addRow(self.memory_status)
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
        page, form = self._page("回收站", "删掉的对话和「小瓜记得的你」里删掉的条目，在这里放 30 天，"
                                "到期自动彻底删除。小瓜删的时候就已经忘掉了；对话里你说过的原话也存在这里，"
                                "想马上清掉就点「彻底删除」。")
        self.trash_list = QListWidget(objectName="memory")
        self.trash_list.setMinimumHeight(260)
        self.trash_list.setSelectionMode(QListWidget.ExtendedSelection)
        form.addRow(self.trash_list)
        restore = QPushButton("恢复选中的")
        restore.clicked.connect(self._restore_selected)
        drop = QPushButton("彻底删除选中的")
        drop.clicked.connect(self._drop_selected)
        self.empty_trash_button = QPushButton("清空回收站")
        self.empty_trash_button.clicked.connect(self._empty_trash)
        row = QHBoxLayout()
        for button in (restore, drop, self.empty_trash_button):
            row.addWidget(button)
        row.addStretch()
        form.addRow(row)
        self.trash_status = self._hint("对话恢复后回到对话列表；单条消息删了不进回收站。")
        form.addRow(self.trash_status)
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
        page, form = self._page("快捷键与启动", "快捷键全局有效，在别的窗口里也能按。")
        self.hotkey_button = HotkeyButton(self.config.hotkey)
        self.hotkey_button.recorded.connect(lambda combo: self._set("hotkey", combo))
        form.addRow("叫出小瓜", self.hotkey_button)
        form.addRow("", self._hint("按一下，小瓜头顶冒出输入框，打字回车就问，回答也冒在气泡里；"
                                   "再按一下收起。想看完整对话就单击小瓜。"))
        self.voice_button = HotkeyButton(self.config.voice_hotkey)
        self.voice_button.recorded.connect(lambda combo: self._set("voice_hotkey", combo))
        form.addRow("按键说话", self.voice_button)
        form.addRow("", self._hint("按一下开始说（用 Windows 自带的语音输入，第一次要在系统里允许麦克风），"
                                   "说完再按一下就发给小瓜，回答冒在气泡里；对话框开着时就在对话框里。"
                                   "小瓜回答时按它会先打断。"))
        self.hotkey_status = self._hint("点一下按钮，再按新的组合键。")
        form.addRow("", self.hotkey_status)

        self.autostart = QCheckBox("开机自动启动每日一瓜（启动后安静待在桌面上）")
        self.autostart.setChecked(cfg.autostart_enabled())
        self.autostart.toggled.connect(self._toggle_autostart)
        form.addRow("", self.autostart)
        self.autostart_status = self._hint("")
        form.addRow("", self.autostart_status)
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
        page, form = self._page("关于每日一瓜", "看黄历、问个事的桌面小参谋，陪你的是小瓜。黄历和卦只当参考，拿主意还是你自己。")
        form.addRow("版本", QLabel(meihua.__version__))
        for label, folder in (("配置文件夹", cfg.home()), ("日志文件夹", cfg.log_dir())):
            button = QPushButton("打开")
            button.clicked.connect(lambda _=False, f=folder: QDesktopServices.openUrl(QUrl.fromLocalFile(str(f))))
            row = QHBoxLayout()
            path = QLabel(str(folder), objectName="hint")
            path.setTextInteractionFlags(Qt.TextSelectableByMouse)
            row.addWidget(path, 1)
            row.addWidget(button)
            form.addRow(label, row)
        keep = QCheckBox("保存对话记录（只存文字）")
        keep.setChecked(self.config.keep_history)
        keep.toggled.connect(lambda on: self._set("keep_history", on))
        form.addRow("记录", keep)
        folder_button = QPushButton("打开记录文件夹")
        folder_button.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(cfg.history_dir().resolve()))))
        delete_button = QPushButton("删除全部记录")
        delete_button.clicked.connect(self._delete_history)
        row = QHBoxLayout()
        row.addWidget(folder_button)
        row.addWidget(delete_button)
        row.addStretch()
        form.addRow("", row)
        self.history_status = self._hint("小瓜记下聊过的对话，重启后接着聊；关掉就只在内存里记。")
        form.addRow("", self.history_status)
        form.addRow("隐私", self._hint("你问的话只发给你选的模型厂商；记录、记忆和密钥都只存在这台电脑上。"))
        terms = QPushButton("查看使用协议与隐私说明")
        terms.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(meihua.ROOT / "PRIVACY.txt"))))
        row = QHBoxLayout()
        row.addWidget(terms)
        row.addStretch()
        form.addRow("", row)
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

