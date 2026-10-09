"""到点提醒: a plan with a time is said at its minute, with a wave, whatever 主动说话 is set to."""

from __future__ import annotations

import os
from datetime import date, datetime

import pytest

from meihua.companion import harness, life
from meihua.companion.agent import XiaoguaAgent
from meihua.companion.memory import Fact, Memory, clock
from meihua.companion.session import Session

from test_companion_agent import ScriptedClient, text, tool  # noqa: E402

TODAY = date(2026, 10, 9)
NOON = datetime(2026, 10, 9, 12, 0)


def test_a_plan_with_a_time_is_a_reminder():
    memory = Memory()
    out = memory.add("计划", "交报告", "2026-10-09", TODAY, at="15:00", now=NOON)
    assert out["status"] == "OK" and out["remind_at"] == "今天 15:00"
    assert "15:00 到点提醒：交报告" in memory.facts[0].label(TODAY)


def test_a_time_alone_means_today_and_odd_times_are_refused():
    memory = Memory()
    assert memory.add("计划", "喝水", None, TODAY, at="9:5", now=datetime(2026, 10, 9, 8, 0))["status"] == "OK"
    assert memory.facts[0].date == "2026-10-09" and memory.facts[0].time == "09:05"
    assert memory.add("计划", "开会", None, TODAY, at="25:00", now=NOON)["status"] == "INVALID_INPUT"
    assert memory.add("偏好", "打绝密", None, TODAY, at="15:00", now=NOON)["status"] == "INVALID_INPUT"


def test_a_time_already_gone_is_sent_back_to_be_worked_out_again():
    out = Memory().add("计划", "拉闸点开了", None, TODAY, at="11:40", now=NOON)
    assert out["status"] == "INVALID_INPUT" and "已经过了" in out["error"]


@pytest.mark.parametrize("raw, expected", [("15:00", "15:00"), ("9:5", "09:05"), ("15：30", "15:30"),
                                           ("24:00", ""), ("三点", ""), ("", "")])
def test_clock(raw, expected):
    assert clock(raw) == expected


def test_due_reminders_come_once():
    memory = Memory()
    memory.add("计划", "交报告", None, TODAY, at="15:00", now=NOON)
    memory.add("计划", "搬家", "2026-10-11", TODAY)                         # a plan without a time: no reminder
    assert memory.due_reminders(datetime(2026, 10, 9, 14, 59)) == []
    due = memory.due_reminders(datetime(2026, 10, 9, 15, 0))
    assert [f.text for f in due] == ["交报告"]
    memory.mark_reminded(due)
    assert memory.due_reminders(datetime(2026, 10, 9, 15, 1)) == [] and "已提醒" in memory.facts[0].label(TODAY)


def test_old_memory_files_still_load(tmp_path):
    path = tmp_path / "memory.json"
    path.write_text('{"facts": [{"id": "m1", "kind": "计划", "text": "搬家", "created": "2026-10-01", '
                    '"date": "2026-10-11"}]}', encoding="utf-8")
    assert Memory(path).facts[0] == Fact("m1", "计划", "搬家", "2026-10-01", "2026-10-11")


def test_what_xiaogua_says_on_time_and_when_late():
    assert life.reminder_text("交报告", "15:00", datetime(2026, 10, 9, 15, 0)) == "到点啦：交报告（15:00）"
    assert "没开着" in life.reminder_text("交报告", "15:00", datetime(2026, 10, 9, 15, 30))


@pytest.mark.parametrize("answer", ["好，15:00 叫你。", "行，下午三点叫你交报告。", "到 3点 我喊你。", "十五点叫你"])
def test_an_answer_that_says_the_time_is_left_alone(answer):
    assert harness.say_reminders(answer, ["今天 15:00"]) == (answer, [])


def test_an_answer_that_does_not_gets_it_from_code():
    out, checks = harness.say_reminders("好，记下了。", ["今天 15:00"])
    assert out == "好，记下了。\n今天 15:00 到点提醒你。" and checks == ["补提醒时间"]
    assert harness.say_reminders("十三点叫你", ["今天 15:00"])[1] == ["补提醒时间"]   # 三点 inside 十三点 is not 15:00


def test_the_agent_sets_a_reminder_and_says_when(tmp_path):
    session = Session(tmp_path)
    session.memory = Memory()
    client = ScriptedClient([[tool("remember_fact", kind="计划", text="喝水", time="23:59")],
                             [text("好，记下了。\n〔平静〕")]])
    reply = XiaoguaAgent(client=client, session=session).ask("23点59提醒我喝水")
    assert session.memory.facts[0].time == "23:59"
    assert reply.text.endswith("今天 23:59 到点提醒你。") and "补提醒时间" in reply.checks


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
    pet.session.memory = Memory()
    pet.show()
    return pet


def test_the_pet_waves_and_says_it_at_the_minute(pet):
    pet.config.proactive = "关"                                   # asked for: given anyway
    pet.session.memory.add("计划", "交报告", None, TODAY, at="15:00", now=NOON)
    heard = []
    pet.reminded.connect(heard.append)
    assert pet.check_reminders(datetime(2026, 10, 9, 14, 59)) == []
    assert pet.check_reminders(datetime(2026, 10, 9, 15, 0)) == ["到点啦：交报告（15:00）"]
    assert pet.state == "招手" and heard == ["到点啦：交报告（15:00）"]
    assert any(m["text"] == "到点啦：交报告（15:00）" for m in pet.session.chat.messages)    # kept in the chat
    assert pet.check_reminders(datetime(2026, 10, 9, 15, 1)) == []                     # once


def test_the_pet_waits_while_it_is_answering(pet):
    pet.session.memory.add("计划", "交报告", None, TODAY, at="15:00", now=NOON)
    pet.busy = True
    assert pet.check_reminders(datetime(2026, 10, 9, 15, 0)) == []
    pet.busy = False
    assert pet.check_reminders(datetime(2026, 10, 9, 15, 0))
