"""Talking to 小瓜 in the bubble over its head, without the chat panel; and the chat's input box."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QInputMethodEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from meihua.companion import app as companion  # noqa: E402
from meihua.companion.agent import Reply  # noqa: E402

qapp = QApplication.instance() or QApplication([])


@pytest.fixture
def pet(tmp_path, monkeypatch):
    monkeypatch.setenv("MEIHUA_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(companion.threading, "Thread",
                        lambda target, args, daemon: type("T", (), {"start": lambda self: None})())
    pet = companion.Pet(companion.OfflineAgent(), "Ctrl+Alt+X")
    pet.show()
    return pet


def ask(pet, text):
    pet.hotkey_pressed()
    pet.bubble.input.setText(text)
    QTest.keyClick(pet.bubble.input, Qt.Key_Return)


def test_the_hotkey_opens_a_box_over_xiaoguas_head_and_closes_it_again(pet):
    pet.hotkey_pressed()
    assert pet.bubble.asking and pet.bubble.input.isVisible() and not pet.chat.isVisible()
    pet.hotkey_pressed()
    assert not pet.bubble.isVisible()
    pet.open_chat()
    pet.hotkey_pressed()                                       # with the chat open: the chat closes
    assert not pet.chat.isVisible() and not pet.bubble.isVisible()


def test_the_first_look_of_the_day_shows_todays_line_above_the_box(pet):
    pet.config.last_greet = ""
    pet.hotkey_pressed()
    assert "宜" in pet.bubble.label.text() and pet.bubble.label.isVisible()
    pet.hotkey_pressed()
    pet.hotkey_pressed()                                       # already greeted today: just the box
    assert not pet.bubble.label.isVisible()


def test_hidden_xiaogua_comes_back_for_the_hotkey(pet):
    pet.hide()
    pet.hotkey_pressed()
    assert pet.isVisible() and pet.bubble.asking


def test_a_question_in_the_bubble_is_worked_on_and_answered_in_the_bubble(pet):
    ask(pet, "今天适合理发吗")
    assert pet.busy and pet.bubble.following_answer and "小瓜在想" in pet.bubble.label.text()
    pet.bridge.step.emit(pet._turn, "almanac_day")
    assert "正在翻黄历" in pet.bubble.label.text()
    pet.bridge.delta.emit(pet._turn, "适合，今天宜理发。")
    QTest.qWait(200)
    assert "宜理发" in pet.bubble.label.text() and pet.bubble.mode == "answer"
    pet.bridge.replied.emit(pet._turn, Reply("适合，今天宜理发。早上去最好。", True))
    assert not pet.busy and pet.bubble.isVisible() and "早上去最好" in pet.bubble.label.text()
    assert pet.bubble.hide_timer.isActive() and "完整对话" in pet.bubble.footer.text()
    kinds = [kind for kind, _ in pet.chat.transcript()]
    assert kinds == ["mine", "xiaogua"]                        # the same conversation as the panel


def test_with_the_chat_open_the_bubble_stays_out_of_it(pet):
    pet.open_chat()
    pet.chat.send("今天适合理发吗")
    pet.bridge.delta.emit(pet._turn, "适合。")
    pet.bridge.replied.emit(pet._turn, Reply("适合。", True))
    assert not pet.bubble.isVisible()


def test_closing_the_chat_half_way_moves_the_answer_to_the_bubble(pet):
    pet.open_chat()
    pet.chat.send("今天适合理发吗")
    pet.chat.hide()
    pet.bridge.delta.emit(pet._turn, "适合。")
    QTest.qWait(200)
    assert pet.bubble.following_answer and "适合" in pet.bubble.label.text()


def test_text_before_a_tool_call_is_taken_back_in_the_bubble_too(pet):
    ask(pet, "今天适合理发吗")
    pet.bridge.delta.emit(pet._turn, "我先看看黄历")
    QTest.qWait(200)
    pet.bridge.discard.emit(pet._turn)
    assert pet.bubble.mode == "thinking" and "看看黄历" not in pet.bubble.label.text()


def test_stopping_takes_the_bubble_down(pet):
    ask(pet, "今天适合理发吗")
    pet.stop_answer()
    assert not pet.bubble.isVisible()


def test_a_new_question_in_the_bubble_stops_the_old_answer(pet):
    ask(pet, "今天适合理发吗")
    first = pet._turn
    ask(pet, "那明天呢")
    assert pet._turn > first and pet.busy
    assert [text for kind, text in pet.chat.transcript() if kind == "mine"] == ["今天适合理发吗", "那明天呢"]


def test_an_error_says_where_to_look(pet):
    ask(pet, "今天适合理发吗")
    pet.bridge.replied.emit(pet._turn, RuntimeError("boom"))
    assert pet.bubble.mode == "note" and "没问成" in pet.bubble.label.text()


def test_long_answers_are_cut_in_the_bubble_but_whole_in_the_chat():
    long = "今天宜理发。" * 80
    shown = companion.bubble_text(long)
    assert len(shown) < len(long) and "点我看完整回答" in shown and shown.split("……")[0].endswith("。")
    assert companion.bubble_text("短的。") == "短的。"
    assert companion.answer_seconds("短") == 12 and companion.answer_seconds(long) == 60


def test_patting_does_not_cover_an_answer_or_the_box(pet):
    ask(pet, "今天适合理发吗")
    pet.bridge.replied.emit(pet._turn, Reply("适合。", True))
    pet._patted()
    assert pet.bubble.label.text() == "适合。"
    pet.hotkey_pressed()                                       # the answer is up: the hotkey asks again
    pet.bubble.input.setText("那明")
    pet._patted()
    assert pet.bubble.asking and pet.bubble.input.text() == "那明"


def test_a_reminder_while_typing_goes_above_the_box(pet):
    pet.hotkey_pressed()
    pet.bubble.input.setText("那明")
    pet.bubble.set_line("该喝水啦")
    assert pet.bubble.asking and pet.bubble.input.text() == "那明" and pet.bubble.label.text() == "该喝水啦"


def test_clicking_xiaogua_takes_half_a_question_into_the_chat(pet):
    pet.hotkey_pressed()
    pet.bubble.input.setText("下周哪天")
    pet.toggle_chat()
    assert pet.chat.isVisible() and not pet.bubble.isVisible()
    assert pet.chat.edit.toPlainText() == "下周哪天"


def test_escape_puts_the_box_away(pet):
    pet.hotkey_pressed()
    QTest.keyClick(pet.bubble.input, Qt.Key_Escape)
    assert not pet.bubble.isVisible()


def test_an_empty_box_goes_after_a_quiet_minute_but_not_once_typed_in(pet):
    pet.hotkey_pressed()
    assert pet.bubble.hide_timer.isActive() and pet.bubble.hide_timer.interval() == companion.ASK_IDLE_S * 1000
    QTest.keyClicks(pet.bubble.input, "a")
    assert not pet.bubble.hide_timer.isActive()


def test_losing_the_focus_does_not_make_the_box_vanish_at_once(pet):
    """Another program grabbing the focus right after the hotkey: the box stays a while."""
    from PySide6.QtCore import QEvent
    pet.hotkey_pressed()
    bubble = pet.bubble
    bubble.isActiveWindow = lambda: False                      # focus went elsewhere
    QApplication.sendEvent(bubble, QEvent(QEvent.ActivationChange))
    QTest.qWait(50)
    assert bubble.asking and bubble.hide_timer.interval() == companion.ASK_AWAY_S * 1000
    bubble.isActiveWindow = lambda: True                       # the user came back to it
    QApplication.sendEvent(bubble, QEvent(QEvent.ActivationChange))
    assert bubble.hide_timer.interval() == companion.ASK_IDLE_S * 1000
    bubble.input.setText("那明天")
    bubble.isActiveWindow = lambda: False                      # left with something typed: it stays
    QApplication.sendEvent(bubble, QEvent(QEvent.ActivationChange))
    assert not bubble.hide_timer.isActive()


def test_pinyin_being_typed_hides_the_grey_hint_in_the_chat(pet):
    """The 'da'da' typed over '问小瓜…' in the user's screenshot."""
    edit = pet.chat.edit
    assert edit.placeholderText() == "问小瓜…"
    QApplication.sendEvent(edit, QInputMethodEvent("da'da", []))
    assert edit.placeholderText() == ""
    commit = QInputMethodEvent("", [])
    commit.setCommitString("哒哒")
    QApplication.sendEvent(edit, commit)
    assert edit.toPlainText() == "哒哒" and edit.placeholderText() == "问小瓜…"
    edit.clear()
    pet.chat.set_listening(True)
    assert "在听" in edit.placeholderText()
