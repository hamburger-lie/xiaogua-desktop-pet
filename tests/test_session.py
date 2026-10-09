"""Conversation state: the open conversation, its Q&A, days, restarts, history on and off."""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta

import pytest

from meihua.companion.session import Session, forget_everything

T0 = datetime(2026, 9, 24, 20, 0).astimezone()


def chatted(session: Session, question="今天适合理发吗", answer="适合，下午去。", now=T0) -> str:
    """One question and its answer, as the pet logs them."""
    question_id = session.log_message("mine", question, now=now)
    session.turn_tag = question_id
    session.record_daily_turn(question, answer, now=now)
    session.log_message("xiaogua", answer, now=now, reply_to=question_id)
    return question_id


def test_history_off_writes_nothing(tmp_path):
    session = Session(None, now=T0)
    chatted(session)
    assert list(tmp_path.iterdir()) == []


def test_forget_everything_deletes_the_conversations(tmp_path):
    session = Session(tmp_path, now=T0)
    chatted(session)
    assert forget_everything(tmp_path) == 1 and not list((tmp_path / "chats").glob("*.json"))


def test_a_restart_carries_on_with_todays_conversation(tmp_path):
    session = Session(tmp_path, now=T0)
    chatted(session)
    again = Session(tmp_path, now=T0 + timedelta(hours=1))
    assert again.chat.id == session.chat.id and again.recent_daily_messages()[0]["content"] == "今天适合理发吗"


def test_the_next_day_starts_a_new_conversation(tmp_path):
    session = Session(tmp_path, now=T0)
    chatted(session)
    first = session.chat.id
    session.begin_turn(now=T0 + timedelta(days=1))
    assert session.chat.id != first and session.recent_daily_messages() == []
    assert any(c["id"] == first for c in session.list_chats())                    # the old one stays


def test_earlier_talk_is_kept_within_a_budget(tmp_path):
    session = Session(tmp_path, now=T0)
    for i in range(30):
        session.record_daily_turn(f"问题{i}" + "啊" * 200, f"回答{i}" + "嗯" * 200, now=T0)
    messages = session.recent_daily_messages()
    assert messages[-1]["content"].startswith("回答29") and len(messages) < 30


def test_together_counts_days_and_conversations(tmp_path):
    session = Session(tmp_path, now=T0)
    session.first_day = date(2026, 9, 10)
    assert session.together_text(T0) == "陪你第 15 天"
    chatted(session)
    assert session.together_text(T0) == "陪你第 15 天 · 聊过 1 段对话"


# ------------------------------------------------------------ the chat window (headless Qt)

@pytest.fixture
def pet(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    monkeypatch.setenv("MEIHUA_HOME", str(tmp_path / "home"))
    from meihua.companion import app as companion
    return companion.Pet(companion.OfflineAgent(), "Ctrl+Alt+X")


def test_todays_chat_comes_back_after_a_restart(pet):
    from meihua.companion import app as companion
    pet.session.log_message("mine", "今天适合理发吗")
    pet.session.log_message("xiaogua", "适合。")
    again = companion.Pet(companion.OfflineAgent(), "Ctrl+Alt+X")
    assert again.chat.transcript() == [("mine", "今天适合理发吗"), ("xiaogua", "适合。")]


def test_the_first_day_is_remembered(pet):
    assert pet.config.first_day == date.today().isoformat() and pet.session.first_day == date.today()
