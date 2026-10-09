"""小瓜's small life: speaking up (逗逗), fidgets and night (VPet / DyberPet), patting, the ball, the voice key."""

from __future__ import annotations

import os
import random
from datetime import datetime

import pytest

from meihua.companion import life


# ------------------------------------------------------------ the rules

@pytest.mark.parametrize("level, kind, expected", [
    ("正常", "morning", True), ("正常", "night", True), ("少", "morning", False), ("少", "plan", True),
    ("关", "plan", False), ("关", "night", False),
])
def test_proactive_levels(level, kind, expected):
    assert life.allows(level, kind) is expected


def test_night_hours():
    assert life.is_night(datetime(2026, 10, 7, 23, 30)) and life.is_night(datetime(2026, 10, 8, 5, 59))
    assert not life.is_night(datetime(2026, 10, 7, 6, 0)) and not life.is_night(datetime(2026, 10, 7, 22, 59))


def test_fidgets_only_use_motions_that_have_art():
    rng = random.Random(1)
    assert {life.pick_fidget({"点头"}, rng) for _ in range(20)} == {"点头"}
    assert life.pick_fidget(set(), rng) is None
    assert life.FIDGET_MS[0] <= life.fidget_delay(rng) <= life.FIDGET_MS[1]


def test_patting_is_rubbing_the_head():
    pats = life.PatDetector()
    xs = [100, 110, 100, 110, 100, 110]
    assert not any(pats.feed(x, 20, 220, 220, now=i * 0.1) for i, x in enumerate(xs[:3]))
    assert any(pats.feed(x, 20, 220, 220, now=0.3 + i * 0.1) for i, x in enumerate(xs[3:]))
    assert not pats.feed(100, 20, 220, 220, now=1.0)                       # cooling down
    body = life.PatDetector()
    assert not any(body.feed(x, 180, 220, 220, now=i * 0.1) for i, x in enumerate(xs * 2))   # not the head


# ------------------------------------------------------------ the pet

@pytest.fixture
def pet(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    monkeypatch.setenv("MEIHUA_HOME", str(tmp_path / "home"))
    from meihua.companion import app as companion
    monkeypatch.setattr(companion.threading, "Thread",
                        lambda target, args, daemon: type("T", (), {"start": lambda self: None})())
    pet = companion.Pet(companion.OfflineAgent(), "Ctrl+Alt+X")
    pet.show()
    return pet


def test_idle_fidgets_by_day_and_sleeps_sooner_at_night(pet, monkeypatch):
    monkeypatch.setattr(life, "is_night", lambda now=None: False)
    pet.play("待机")
    assert pet.fidget_timer.isActive() and pet.sleep_timer.interval() == pet.sleep_ms
    pet._fidget()
    assert pet.state in ("点头", "歪头", "招手")
    monkeypatch.setattr(life, "is_night", lambda now=None: True)
    pet.play("待机")
    assert pet.sleep_timer.interval() == min(pet.sleep_ms, life.NIGHT_SLEEP_MS)
    assert pet.fidget_timer.isActive()                                      # at night the fidget is a doze
    pet._fidget()
    assert pet.state == "犯困"


def test_no_fidget_while_answering(pet):
    pet._submit("今天宜什么")
    state = pet.state
    pet._fidget()
    assert pet.state == state


@pytest.mark.parametrize("level, bubble", [("正常", True), ("少", False), ("关", False)])
def test_the_morning_line_obeys_proactive(pet, level, bubble):
    pet.config.proactive, pet.config.last_greet = level, ""
    pet.greet_today()
    assert pet.bubble.isVisible() is bubble
    assert not pet.chat.today_line.text() == ""                             # the welcome card always has it


def test_patting_the_head(pet):
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication
    pet.play("待机")
    pet.pats = life.PatDetector(window=10)
    for x in (100, 112, 100, 112, 100, 112, 100):
        point = QPointF(x, 20)
        QApplication.sendEvent(pet, QMouseEvent(QMouseEvent.Type.MouseMove, point, QPointF(pet.mapToGlobal(point.toPoint())),
                                                Qt.NoButton, Qt.NoButton, Qt.NoModifier))
    assert pet.state == "被摸头" and pet.bubble.toPlainText() in life.PAT_LINES


def test_the_answer_arriving_makes_him_talk(pet, monkeypatch):
    import time
    pet._submit("今天宜什么")
    pet.bridge.delta.emit(pet._turn, "宜理发")
    assert pet.state == "灵光一闪" and pet.queue == ["说话"] and pet._talking_until == 0.0   # the drawn 说话
    monkeypatch.setattr(pet, "has", lambda state: state != "说话")         # no artwork: the code bounce
    pet.bridge.delta.emit(pet._turn, "，")
    assert pet._talking_until > time.monotonic() and pet.ambient.isActive()
    assert pet.grab().width() == pet.width()                                # paints the bounce


def test_the_ball_docks_at_the_edge_and_comes_back(pet):
    from meihua.companion import app as companion
    from meihua.companion.chat import screen_rect_for
    from meihua.companion.config import Config
    pet.set_mini(True)
    area = screen_rect_for(pet.frameGeometry().center())
    assert pet.width() == companion.MINI_SIZE and Config.load().mini
    assert pet.x() < area.left() + 10 or pet.x() + pet.width() > area.right() - 10
    assert pet.grab().width() == companion.MINI_SIZE
    pet.chat.hide()
    pet._notify_if_hidden("小瓜看好了")
    assert pet._attention_until > 0
    pet.set_mini(False)
    assert pet.width() == pet.config.pet_size and not Config.load().mini


def test_the_voice_key_listens_then_sends(pet, monkeypatch):
    from PySide6.QtTest import QTest
    presses, sent = [], []
    monkeypatch.setattr(type(pet), "_press_voice_typing", staticmethod(lambda: presses.append(1)))
    pet.chat.submitted.connect(lambda *args: sent.append(args[0]))
    pet.voice_toggle()
    QTest.qWait(350)
    assert pet._listening and pet.chat.isVisible() and presses == [1] and "在听" in pet.chat.edit.placeholderText()
    pet.chat.edit.setPlainText("今天宜什么")                                # what Windows voice typing wrote
    pet.voice_toggle()
    QTest.qWait(650)
    assert not pet._listening and presses == [1, 1] and sent == ["今天宜什么"]


def test_the_voice_key_interrupts_an_answer(pet, monkeypatch):
    monkeypatch.setattr(type(pet), "_press_voice_typing", staticmethod(lambda: None))
    pet._submit("今天宜什么")
    pet.voice_toggle()
    assert not pet.busy and pet._listening


