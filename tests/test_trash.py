"""回收站: deleted conversations and facts wait 30 days; 恢复, 彻底删除, 清空; 删除全部记录 empties it."""

from __future__ import annotations

import os
from datetime import datetime, timedelta

import pytest

from meihua.companion.memory import Memory
from meihua.companion.session import Session
from meihua.companion.trash import TRASH_DAYS, Trash

NOW = datetime(2026, 10, 9, 15, 0).astimezone()


def chatted(session: Session, question="这周哪天适合搬家", answer="周日。"):
    session.turn_tag = session.log_message("mine", question, now=NOW)
    session.record_daily_turn(question, answer, now=NOW)
    session.log_message("xiaogua", answer, now=NOW)
    session.save_chat()
    return session.chat.id


# ------------------------------------------------------------ the trash itself

def test_put_list_take(tmp_path):
    trash = Trash(tmp_path / "trash")
    first = trash.put("记忆", "偏好：打绝密", {"id": "m1"}, NOW - timedelta(days=2))
    second = trash.put("对话", "今天适合理发吗", {"id": "c1"}, NOW)
    listed = trash.list(NOW)
    assert [e["id"] for e in listed] == [second, first]                       # newest first
    assert listed[1]["days_left"] == TRASH_DAYS - 2
    assert trash.take(first)["data"] == {"id": "m1"} and trash.take(first) is None
    assert trash.drop(second) and trash.list(NOW) == []


def test_after_thirty_days_it_is_gone(tmp_path):
    trash = Trash(tmp_path / "trash")
    trash.put("记忆", "旧的", {}, NOW - timedelta(days=TRASH_DAYS + 1))
    kept = trash.put("记忆", "新的", {}, NOW - timedelta(days=3))
    assert trash.purge(NOW) == 1 and [e["id"] for e in trash.list(NOW)] == [kept]


def test_ids_cannot_reach_outside_the_trash(tmp_path):
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    trash = Trash(tmp_path / "trash")
    assert not trash.drop("../config") and trash.take("..\\config") is None
    assert (tmp_path / "config.json").exists()


def test_no_folder_keeps_nothing():
    assert Trash(None).put("记忆", "x", {}) is None and Trash(None).list() == []


# ------------------------------------------------------------ conversations

def test_a_deleted_conversation_comes_back_whole(tmp_path):
    session = Session(tmp_path / "history", now=NOW)
    session.trash = Trash(tmp_path / "trash")
    doomed = chatted(session)
    session.delete_chat(doomed, NOW)
    assert session.chats.load(doomed) is None                                  # deleted at once, as before
    assert session.recent_daily_messages() == []                               # and 小瓜 forgot it
    entry = session.trash.list()[0]
    assert entry["kind"] == "对话" and entry["title"] == "这周哪天适合搬家"
    back = session.restore_chat(session.trash.take(entry["id"])["data"])
    assert [m["text"] for m in session.chats.load(back).messages] == ["这周哪天适合搬家", "周日。"]


def test_an_empty_conversation_is_not_kept(tmp_path):
    session = Session(tmp_path / "history", now=NOW)
    session.trash = Trash(tmp_path / "trash")
    session.delete_chat(session.chat.id, NOW)
    assert session.trash.list() == []


# ------------------------------------------------------------ facts

def test_forgotten_facts_wait_in_the_trash_and_come_back(tmp_path):
    memory = Memory()
    memory.trash = Trash(tmp_path / "trash")
    memory.add("偏好", "一般打绝密")
    memory.add("称呼", "老王")
    memory.tool("forget_fact", {"id": "m1"})                                   # the model forgot one
    assert [e["title"] for e in memory.trash.list()] == ["偏好：一般打绝密"]
    memory.clear()                                                             # 全部忘掉
    assert len(memory.trash.list()) == 2 and memory.facts == []
    entry = next(e for e in memory.trash.list() if e["title"] == "偏好：一般打绝密")
    memory.add("偏好", "说话直接点")                                           # m1 is given out again
    out = memory.restore(memory.trash.take(entry["id"])["data"])
    assert out["status"] == "OK" and out["id"] != "m1"
    assert {f.text for f in memory.facts} == {"说话直接点", "一般打绝密"}


# ------------------------------------------------------------ the pet and the settings

@pytest.fixture
def companion(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    monkeypatch.setenv("MEIHUA_HOME", str(tmp_path / "home"))
    from meihua.companion import app as app_module, config
    monkeypatch.setattr(app_module.threading, "Thread",
                        lambda target, args, daemon: type("T", (), {"start": lambda self: None})())
    monkeypatch.setattr(app_module, "start_hotkey", lambda *a, **k: type("L", (), {"stop": lambda self: None})())
    return app_module.Companion(config.Config.load(), agent=app_module.OfflineAgent())


def _ask(pet, question, answer):
    from meihua.companion.agent import Reply
    pet._submit(question)
    pet.bridge.replied.emit(pet._turn, Reply(answer, True, []))


def test_delete_then_restore_from_the_settings(companion):
    pet, settings = companion.pet, companion.settings
    _ask(pet, "今天适合理发吗", "适合。")
    doomed = pet.session.chat.id
    pet._delete_chat(doomed)
    assert "回收站" in pet.chat.status.text() and pet.chat.messages() == []
    assert settings.trash_list.count() == 1 and "今天适合理发吗" in settings.trash_list.item(0).text()
    settings.trash_list.item(0).setSelected(True)
    settings._restore_selected()
    titles = [c["title"] for c in pet.session.list_chats()]
    assert "今天适合理发吗" in titles and settings.trash.list() == []


def test_a_forgotten_fact_restored_from_the_settings(companion):
    pet, settings = companion.pet, companion.settings
    pet.session.memory.add("偏好", "一般打绝密")
    settings.refresh_memory()
    settings.memory_list.item(0).setSelected(True)
    settings._forget_selected()
    assert pet.session.memory.facts == [] and settings.trash_list.count() == 1
    settings.trash_list.item(0).setSelected(True)
    settings._restore_selected()
    assert [f.text for f in pet.session.memory.facts] == ["一般打绝密"]


def test_emptying_takes_two_clicks_and_delete_all_empties_it(companion):
    pet, settings = companion.pet, companion.settings
    pet.session.memory.add("偏好", "一般打绝密")
    pet.session.memory.clear()
    settings.refresh_trash()
    settings._empty_trash()
    assert settings.empty_trash_button.text() == "再点一次确认" and len(settings.trash.list()) == 1
    settings._empty_trash()
    assert settings.trash.list() == []
    pet.session.memory.add("偏好", "说话直接点")
    pet.session.memory.clear()
    settings._delete_history()
    assert settings.trash.list() == []
