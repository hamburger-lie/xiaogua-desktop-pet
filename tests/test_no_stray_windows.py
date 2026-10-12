"""No widget may flash up as a window of its own.

A chat message showed its text label before putting it in the layout: for an instant the
label was a top-level window, and Windows drew a small framed box at the screen's top-left
on every Enter. Every Show event of a window is recorded while the app works; only the
windows 小瓜 means to show may appear.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QObject  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from meihua.companion import app as companion  # noqa: E402
from meihua.companion import chat  # noqa: E402
from meihua.companion.agent import Reply  # noqa: E402

qapp = QApplication.instance() or QApplication([])
MEANT = (companion.Pet, companion.Bubble, chat.ChatPanel)


class WindowsShown(QObject):
    def __init__(self):
        super().__init__()
        self.shown = []

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Show and getattr(watched, "isWindow", lambda: False)():
            self.shown.append(type(watched).__name__)
        return False


@pytest.fixture
def watch():
    spy = WindowsShown()
    qapp.installEventFilter(spy)
    yield spy
    qapp.removeEventFilter(spy)


@pytest.fixture
def pet(tmp_path, monkeypatch):
    monkeypatch.setenv("MEIHUA_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(companion.threading, "Thread",
                        lambda target, args, daemon: type("T", (), {"start": lambda self: None})())
    pet = companion.Pet(companion.OfflineAgent(), "Ctrl+Alt+X")
    pet.show()
    return pet


def stray(spy):
    return [name for name in spy.shown if name not in {cls.__name__ for cls in MEANT}]


@pytest.mark.parametrize("kind", ["mine", "xiaogua", "error", "typing"])
def test_a_new_message_never_shows_as_a_window(watch, kind):
    chat.Message(kind, "今天适合收钱进账。", msg_id="m1", reply_to="q1")
    assert stray(watch) == []


def test_sending_from_the_bubble_flashes_no_window(pet, watch):
    pet.hotkey_pressed()
    pet.bubble.input.setText("今天适合干嘛")
    pet.bubble.send()                                     # your question, then 小瓜在想
    pet.bridge.step.emit(pet._turn, "almanac_day")
    pet.bridge.delta.emit(pet._turn, "今天适合")
    pet.bridge.replied.emit(pet._turn, Reply("今天适合收钱进账。", True))
    assert stray(watch) == []


def test_sending_in_the_chat_and_restoring_it_flash_no_window(pet, watch):
    pet.open_chat()
    pet.chat.send("今天适合干嘛")
    pet.bridge.replied.emit(pet._turn, RuntimeError("网络断了"))
    pet._show_conversation()                              # a restart's restore
    assert stray(watch) == []
