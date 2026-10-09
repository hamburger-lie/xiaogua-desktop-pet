"""Chat basics: stop an answer, take a question back (撤回), delete a message, ask again, copy."""

from __future__ import annotations

import os
import threading

import pytest

from meihua.companion.agent import Reply, XiaoguaAgent
from meihua.companion.session import Session

from test_companion_agent import ScriptedClient, text, tool  # noqa: E402


# ------------------------------------------------------------ the session's log and the model's context

def test_messages_carry_ids_and_answers_point_at_questions(tmp_path):
    session = Session(tmp_path)
    question = session.log_message("mine", "今天适合理发吗")
    answer = session.log_message("xiaogua", "适合。", reply_to=question)
    assert session.message(answer)["reply_to"] == question and question != answer
    again = Session(tmp_path)
    assert [m["id"] for m in again.chat.messages] == [question, answer]


def test_taking_a_question_back_forgets_the_whole_exchange(tmp_path):
    session = Session(tmp_path)
    session.begin_turn()
    question = session.log_message("mine", "今天适合理发吗")
    session.turn_tag = question
    session.record_daily_turn("今天适合理发吗", "适合。")
    session.log_message("xiaogua", "适合。", reply_to=question)
    assert session.forget_exchange(question) and session.chat.messages == []
    assert session.recent_daily_messages() == [] and Session(tmp_path).chat.daily == []     # saved that way


def test_deleting_only_the_answer_keeps_the_question_but_the_model_forgets(tmp_path):
    session = Session(tmp_path)
    question = session.log_message("mine", "今天宜什么")
    session.turn_tag = question
    session.record_daily_turn("今天宜什么", "宜理发。")
    answer = session.log_message("xiaogua", "宜理发。", reply_to=question)
    assert session.forget_message(answer) == [answer]
    assert [m["id"] for m in session.chat.messages] == [question] and session.chat.daily == []


# ------------------------------------------------------------ the agent stops when told

def test_a_stopped_question_makes_no_more_calls_and_is_not_remembered(tmp_path):
    session = Session(tmp_path)
    cancel = threading.Event()
    client = ScriptedClient([[tool("daily_reading", question="面试能成吗", topic="事业")], [text("能成。")]])
    reply = XiaoguaAgent(client=client, session=session).ask("面试能成吗", on_step=lambda _name: cancel.set(),
                                                            cancel=cancel)
    assert reply.error == "cancelled" and len(client.requests) == 1
    assert session.chat.daily == []


# ------------------------------------------------------------ the pet and its chat (headless Qt)

@pytest.fixture
def pet(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    monkeypatch.setenv("MEIHUA_HOME", str(tmp_path / "home"))
    from meihua.companion import app as companion
    started = []
    monkeypatch.setattr(companion.threading, "Thread",
                        lambda target, args, daemon: type("T", (), {"start": lambda self: started.append(args)})())
    pet = companion.Pet(companion.OfflineAgent(), "Ctrl+Alt+X")
    pet.started = started
    return pet


def _answer(pet, words="适合。"):
    pet.bridge.replied.emit(pet._turn, Reply(words, True, []))


def _kinds(pet):
    return [m.kind for m in pet.chat.messages()]


def _menu(pet, message):
    pet.chat._message_menu(message, pet.chat.mapToGlobal(pet.chat.rect().center()))
    entries = [a.text() for a in pet.chat._menu.actions() if a.text()]
    pet.chat._menu.close()
    return entries


def test_a_reply_is_linked_to_its_question(pet):
    pet._submit("今天适合理发吗")
    _answer(pet)
    mine, answer = pet.chat.messages()
    assert answer.reply_to == mine.msg_id and pet.session.message(answer.msg_id)["reply_to"] == mine.msg_id


def test_stop_button_while_answering(pet):
    stops = []
    pet.chat.stop_requested.connect(lambda: stops.append(1))
    pet._submit("今天适合理发吗")
    assert pet.chat.send_button.toolTip() == "停止回答"
    pet.chat.send_button.click()
    assert stops == [1]


def test_stopping_ignores_whatever_the_old_answer_still_sends(pet):
    pet._submit("今天适合理发吗")
    old_turn = pet._turn
    pet.stop_answer()
    assert not pet.busy and pet._cancel.is_set()
    pet._submit("那今天宜什么")
    pet.bridge.delta.emit(old_turn, "旧的回答")                              # late, from the stopped worker
    pet.bridge.replied.emit(old_turn, Reply("旧的回答", True, []))
    assert pet.chat.draft is None and "旧的回答" not in [m.body.text() for m in pet.chat.messages()]
    _answer(pet, "宜理发。")
    assert pet.chat.messages()[-1].body.text() == "宜理发。"
    assert any(m["text"] == "停下了" for m in pet.session.chat.messages)


def test_recall_takes_back_the_latest_question_and_its_answer(pet):
    pet._submit("今天适合理发吗")
    _answer(pet)
    pet._submit("那明天呢")
    _answer(pet, "坐直升机。")
    first_q, _, last_q, last_a = pet.chat.messages()
    assert "撤回" in _menu(pet, last_q) and "撤回" not in _menu(pet, first_q)
    assert "重新回答" in _menu(pet, last_a) and "复制" in _menu(pet, last_a)
    pet.chat.recall_requested.emit(last_q.msg_id)
    assert _kinds(pet) == ["mine", "xiaogua"] and pet.chat.edit.toPlainText() == "那明天呢"
    assert all(m["text"] != "那明天呢" for m in pet.session.chat.messages)


def test_recall_while_answering_stops_it(pet):
    pet._submit("今天适合理发吗")
    question = pet.chat.messages()[0]
    pet.chat.recall_requested.emit(question.msg_id)
    assert not pet.busy and pet.chat.messages() == [] and not pet.chat.welcome.isHidden()
    assert all(m["text"] != "停下了" for m in pet.session.chat.messages)       # quiet: it was taken back


def test_delete_an_answer_or_a_question(pet):
    pet._submit("今天适合理发吗")
    _answer(pet)
    question, answer = pet.chat.messages()
    pet.chat.delete_requested.emit(answer.msg_id)
    assert _kinds(pet) == ["mine"]
    pet.chat.delete_requested.emit(question.msg_id)
    assert pet.chat.messages() == [] and pet.session.chat.messages == []


def test_ask_again_keeps_the_question_and_replaces_the_answer(pet):
    pet._submit("今天适合理发吗")
    _answer(pet, "适合。")
    question, answer = pet.chat.messages()
    pet.chat.retry_requested.emit(answer.msg_id)
    assert pet.busy and pet.started[-1][0] == "今天适合理发吗" and _kinds(pet) == ["mine"]
    _answer(pet, "明天也行。")
    assert [m.body.text() for m in pet.chat.messages()] == ["今天适合理发吗", "明天也行。"]
    assert pet.chat.messages()[-1].reply_to == question.msg_id


def test_copy_puts_the_text_on_the_clipboard(pet):
    from PySide6.QtWidgets import QApplication
    pet._submit("今天适合理发吗")
    _answer(pet, "适合。")
    answer = pet.chat.messages()[-1]
    pet.chat._message_menu(answer, pet.chat.mapToGlobal(pet.chat.rect().center()))
    next(a for a in pet.chat._menu.actions() if a.text() == "复制").trigger()
    assert QApplication.clipboard().text() == "适合。"
