"""「反馈这条回答」: the user sends one of 小瓜's answers to the author, by their own hand.

小瓜 itself sends nothing. The dialog shows exactly what would go out and lets the user
choose what to include; then the text goes to the clipboard and the project's feedback
page on GitHub opens (the issue form in .github/ISSUE_TEMPLATE/answer-feedback.yml),
where the user pastes it and submits it. Nothing the user wrote is put in the web
address, and the API key, the vendor's address and what 小瓜 remembers never go in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QDialog, QHBoxLayout, QLabel, QLayout, QPlainTextEdit,
                               QPushButton, QRadioButton, QVBoxLayout)

import meihua

FEEDBACK_URL = "https://github.com/hamburger-lie/xiaogua-desktop-pet/issues/new?template=answer-feedback.yml"
PROBLEMS = ("说得不对", "答非所问", "太长或太绕", "时辰或日子不对", "其他")

STYLE = """
QDialog { background: #FAF8F0; }
QWidget { font-family: 'Microsoft YaHei'; font-size: 13px; color: #2F4737; }
QLabel#note { color: #8C9687; font-size: 12px; }
QLabel#head { font-weight: bold; }
QPlainTextEdit { background: #FFFFFF; border: 1px solid #DCE3CB; border-radius: 8px; padding: 4px; }
QPlainTextEdit[readOnly="true"] { background: #F3F5EC; color: #4A5E4F; }
QPushButton { border: 1px solid #DCE3CB; border-radius: 8px; padding: 6px 14px; background: #FFFFFF; }
QPushButton:hover { background: #EEF3E3; }
QPushButton#primary { background: #8FAE72; border-color: #8FAE72; color: #FFFFFF; }
QPushButton#primary:hover { background: #6E8F55; }
"""


@dataclass
class Exchange:
    """One question and 小瓜's answer to it, as kept in the conversation."""
    question: str
    answer: str
    asked_at: str = ""                    # ISO time the question was asked (黄历 and 时辰 depend on it)
    model: str = ""                       # 「豆包（火山方舟） · doubao-…」, 「离线模式」, or "" for older answers
    checks: list[str] = field(default_factory=list)   # what the answer checks found (harness.py)
    zodiac: str | None = None


def feedback_text(exchange: Exchange, problem: str, note: str = "", *, question: bool = True,
                  answer: bool = True, zodiac: bool = False) -> str:
    """The text the user is about to send: only what they ticked, plus the version, model and time."""
    lines = [f"问题类型：{problem}"]
    if note.strip():
        lines.append(f"补充说明：{note.strip()}")
    if question:
        lines += ["", "【我的问题】", exchange.question.strip()]
    if answer:
        lines += ["", "【小瓜的回答】", exchange.answer.strip()]
    lines += ["", "【环境】", f"每日一瓜 {meihua.__version__}"]
    if exchange.model:
        lines.append(f"模型：{exchange.model}")
    try:
        lines.append(f"提问时间：{datetime.fromisoformat(exchange.asked_at):%Y-%m-%d %H:%M}")
    except ValueError:
        pass
    if exchange.checks:
        lines.append("程序检查：" + "；".join(exchange.checks))
    if zodiac and exchange.zodiac:
        lines.append(f"属相：{exchange.zodiac}")
    return "\n".join(lines)


class FeedbackDialog(QDialog):
    """Shows what would be sent, lets the user choose, then copies it and (maybe) opens GitHub."""
    sent = Signal(bool)          # copied; True when the feedback page was opened too

    def __init__(self, exchange: Exchange, parent=None):
        super().__init__(parent)
        self.exchange = exchange
        self.setWindowTitle("反馈这条回答")
        self.setStyleSheet(STYLE)
        self.setMinimumWidth(440)
        column = QVBoxLayout(self)
        column.setSpacing(8)
        intro = QLabel("觉得这条回答哪里不对？反馈会发在小瓜的 GitHub 项目页上，帮作者把小瓜调得更靠谱。\n"
                       "小瓜自己不会发出任何东西：点下面的按钮后，内容会复制下来并打开反馈页，"
                       "你粘贴（Ctrl+V）后自己点提交。", objectName="note")
        intro.setWordWrap(True)
        column.addWidget(intro)

        column.addWidget(QLabel("哪里不对？", objectName="head"))
        row = QHBoxLayout()
        self.problems = QButtonGroup(self)
        for index, problem in enumerate(PROBLEMS):
            button = QRadioButton(problem)
            button.setChecked(index == 0)
            self.problems.addButton(button, index)
            row.addWidget(button)
        row.addStretch()
        column.addLayout(row)

        column.addWidget(QLabel("想补充点什么（可以不填）", objectName="head"))
        self.note = QPlainTextEdit()
        self.note.setPlaceholderText("比如：今天明明宜搬家，它说不宜")
        self.note.setFixedHeight(56)
        column.addWidget(self.note)

        column.addWidget(QLabel("一起发出去的内容", objectName="head"))
        self.with_question = QCheckBox("我的问题")
        self.with_answer = QCheckBox("小瓜的回答")
        self.with_zodiac = QCheckBox(f"我的属相（{exchange.zodiac}）" if exchange.zodiac else "我的属相（没设置）")
        self.with_question.setChecked(True)
        self.with_answer.setChecked(True)
        self.with_zodiac.setEnabled(bool(exchange.zodiac))
        boxes = QHBoxLayout()
        for box in (self.with_question, self.with_answer, self.with_zodiac):
            boxes.addWidget(box)
        boxes.addStretch()
        column.addLayout(boxes)
        public = QLabel("注意：反馈是公开的，任何人都能看到；提交需要一个 GitHub 账号。"
                        "问题里有真名、电话、地址这类信息的话，先在下面改掉，或者别勾「我的问题」。", objectName="note")
        public.setWordWrap(True)
        column.addWidget(public)

        column.addWidget(QLabel("预览：发出去的就是这些（可以直接改）", objectName="head"))
        self.preview = QPlainTextEdit()
        self.preview.setMinimumHeight(180)
        column.addWidget(self.preview)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        only_copy = QPushButton("只复制")
        only_copy.setToolTip("复制下来，自己贴到想发的地方")
        only_copy.clicked.connect(lambda: self._send(open_page=False))
        self.open_button = QPushButton("复制并打开 GitHub", objectName="primary")
        self.open_button.clicked.connect(lambda: self._send(open_page=True))
        for button in (cancel, only_copy, self.open_button):
            buttons.addWidget(button)
        column.addLayout(buttons)

        self.problems.idClicked.connect(lambda _id: self._refresh())
        self.note.textChanged.connect(self._refresh)
        for box in (self.with_question, self.with_answer, self.with_zodiac):
            box.toggled.connect(lambda _on: self._refresh())
        self._refresh()
        column.setSizeConstraint(QLayout.SetMinimumSize)      # never smaller than its content: no overlap
        self.resize(self.sizeHint())

    def text(self) -> str:
        """What would go out now: the preview, including any edits the user made in it."""
        return self.preview.toPlainText().strip()

    def _composed(self) -> str:
        return feedback_text(self.exchange, PROBLEMS[self.problems.checkedId()], self.note.toPlainText(),
                             question=self.with_question.isChecked(), answer=self.with_answer.isChecked(),
                             zodiac=self.with_zodiac.isChecked())

    def _refresh(self):
        """The choices changed: rebuild the preview (edits made in it give way to the new choice)."""
        self.preview.setPlainText(self._composed())

    def _send(self, open_page: bool):
        QGuiApplication.clipboard().setText(self.text())
        if open_page:
            QDesktopServices.openUrl(QUrl(FEEDBACK_URL))
        self.sent.emit(open_page)
        self.accept()
