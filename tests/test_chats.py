"""Conversations (会话): new, switch, delete a whole one; each keeps its own Q&A."""

from __future__ import annotations

import os
from datetime import datetime, timedelta

import pytest

from meihua.companion.session import Session

from test_session import chatted  # noqa: E402

NOW = datetime(2026, 10, 7, 15, 0).astimezone()


def test_new_switch_and_list(tmp_path):
    session = Session(tmp_path, now=NOW)
    first = session.chat.id
    session.log_message("mine", "这周哪天适合搬家", now=NOW)
    session.new_chat(NOW)
    assert session.chat.id != first and session.chat.empty
    session.new_chat(NOW)                                                    # an empty one is not doubled
    listed = session.list_chats()
    assert [c["id"] for c in listed] == [session.chat.id, first]
    assert listed[1]["title"] == "这周哪天适合搬家" and listed[0]["title"] == "新对话"
    assert session.switch_chat(first).messages[0]["text"] == "这周哪天适合搬家"
    assert len(list((tmp_path / "chats").glob("*.json"))) == 1             # empty conversations are not written


def test_each_conversation_has_its_own_qa(tmp_path):
    session = Session(tmp_path, now=NOW)
    chatted(session, "今天适合理发吗", "适合。", now=NOW)
    session.new_chat(NOW)
    assert session.recent_daily_messages() == []                              # a new one starts clean


def test_deleting_a_conversation_forgets_it(tmp_path):
    session = Session(tmp_path, now=NOW)
    chatted(session, now=NOW)
    doomed = session.chat.id
    session.delete_chat(doomed, NOW)
    assert session.chats.load(doomed) is None and session.chat.id != doomed
    assert session.recent_daily_messages() == []


def test_a_restart_resumes_todays_conversation_and_tomorrow_starts_fresh(tmp_path):
    session = Session(tmp_path, now=NOW)
    session.log_message("mine", "在吗", now=NOW)
    again = Session(tmp_path, now=NOW + timedelta(hours=2))
    assert again.chat.id == session.chat.id and again.chat.messages[0]["text"] == "在吗"
    tomorrow = Session(tmp_path, now=NOW + timedelta(days=1))
    assert tomorrow.chat.empty and tomorrow.list_chats()[1]["id"] == session.chat.id


def test_deleting_the_last_message_deletes_the_conversation_file(tmp_path):
    session = Session(tmp_path, now=NOW)
    question = session.log_message("mine", "在吗", now=NOW)
    session.forget_exchange(question)
    assert not list((tmp_path / "chats").glob("*.json"))


# ------------------------------------------------------------ the chat window

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
    return companion.Pet(companion.OfflineAgent(), "Ctrl+Alt+X")


def _ask(pet, question, answer):
    from meihua.companion.agent import Reply
    pet._submit(question)
    pet.bridge.replied.emit(pet._turn, Reply(answer, True, []))


def _texts(pet):
    return [m.body.text() for m in pet.chat.messages()]


def test_the_list_opens_switches_and_starts_new_ones(pet):
    _ask(pet, "今天适合理发吗", "适合。")
    first = pet.session.chat.id
    pet.chat.chats_requested.emit()
    popup = pet.chat._chat_list
    assert list(popup.rows) == [first] and popup.isVisible()
    popup.created.emit()
    assert pet.chat.messages() == [] and not pet.chat.welcome.isHidden()
    _ask(pet, "今天宜什么", "宜理发。")
    pet.chat.chats_requested.emit()
    assert len(pet.chat._chat_list.rows) == 2
    pet.chat.chat_picked.emit(first)
    assert _texts(pet) == ["今天适合理发吗", "适合。"]


def test_deleting_a_whole_conversation_takes_two_clicks(pet):
    _ask(pet, "今天适合理发吗", "适合。")
    doomed = pet.session.chat.id
    pet.chat.chats_requested.emit()
    button = pet.chat._chat_list.rows[doomed].delete_button
    button.click()
    assert button.text() == "确认删除" and _texts(pet) == ["今天适合理发吗", "适合。"]
    button.click()
    assert pet.chat.messages() == [] and pet.session.chat.id != doomed
    assert pet.session.chats.load(doomed) is None


def test_switching_while_answering_stops_the_answer(pet):
    _ask(pet, "今天适合理发吗", "适合。")
    first = pet.session.chat.id
    pet._new_chat()
    pet._submit("今天宜什么")
    pet.chat.chat_picked.emit(first)
    assert not pet.busy and _texts(pet) == ["今天适合理发吗", "适合。"]


def test_settings_delete_all_clears_the_screen(pet):
    _ask(pet, "今天适合理发吗", "适合。")
    pet._forget()
    assert pet.chat.messages() == [] and pet.session.chat.empty
