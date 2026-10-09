"""Long-term memory: facts the user told 小瓜, and the morning line."""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta

import pytest

from meihua.companion.agent import XiaoguaAgent
from meihua.companion.memory import Memory
from meihua.companion.session import Session

from test_companion_agent import ScriptedClient, text, tool  # noqa: E402

TODAY = date(2026, 10, 7)
NINE = datetime(2026, 10, 7, 9, 0).astimezone()


# ------------------------------------------------------------ facts

def test_facts_are_added_listed_and_kept(tmp_path):
    memory = Memory(tmp_path / "memory.json")
    assert memory.add("称呼", "叫他老王", today=TODAY)["status"] == "OK"
    plan = memory.add("计划", "搬家", "2026-10-11", today=TODAY)
    assert plan["id"] == "m2" and plan["fact"] == "计划 10月11日（周日，4天后）：搬家"
    assert memory.add("计划", "搬家", "2026-10-11", today=TODAY)["status"] == "ALREADY_KNOWN"
    assert memory.add("称呼", "叫他瓜哥", today=TODAY)["status"] == "OK"       # one name: newest wins
    again = Memory(tmp_path / "memory.json")
    assert [f.text for f in again.facts] == ["搬家", "叫他瓜哥"]
    assert "[m2] 计划 10月11日（周日，4天后）：搬家" in again.context_text(TODAY)


@pytest.mark.parametrize("kind, text, when", [
    ("心情", "开心", None), ("偏好", "", None), ("偏好", "长" * 61, None),
    ("计划", "面试", None), ("计划", "面试", "下周五"),
])
def test_bad_facts_are_refused(kind, text, when):
    assert Memory().add(kind, text, when, today=TODAY)["status"] == "INVALID_INPUT"


def test_forget_and_close(tmp_path):
    memory = Memory(tmp_path / "memory.json")
    memory.add("偏好", "一般打绝密", today=TODAY)
    memory.add("计划", "面试", "2026-10-09", today=TODAY)
    assert memory.close("m1", "过了")["status"] == "NOT_FOUND"              # only plans have outcomes
    assert memory.close("[m2]", "过了，下周入职")["status"] == "OK"
    assert memory.forget("m1")["status"] == "OK" and memory.forget("m1")["status"] == "NOT_FOUND"
    assert "（结果：过了，下周入职）" in Memory(tmp_path / "memory.json").facts[0].label(TODAY)


def test_plans_near_today_are_shown_and_followed_up():
    memory = Memory()
    memory.add("计划", "搬家", "2026-10-11", today=TODAY)
    memory.add("计划", "面试", "2026-10-06", today=TODAY)
    memory.add("计划", "体检", "2026-10-07", today=TODAY)
    memory.add("计划", "旧事", "2026-09-01", today=TODAY)                    # too long ago
    memory.add("计划", "年底旅行", "2027-02-01", today=TODAY)                # too far ahead
    assert [f.text for f in memory.due(TODAY)] == ["体检"]
    follow = memory.to_follow_up(TODAY)
    assert [f.text for f in follow] == ["面试"]
    assert "（已过，还不知道结果）" in follow[0].label(TODAY)
    memory.mark_asked(follow)
    assert memory.to_follow_up(TODAY) == [] and "（问过结果，等他回答）" in follow[0].label(TODAY)
    assert {f.text for f in memory.shown(TODAY)} == {"搬家", "面试", "体检"}


def test_a_full_memory_drops_finished_plans_first():
    memory = Memory()
    memory.add("计划", "早就办完的事", "2026-10-01", today=TODAY)
    memory.close("m1", "办完了")
    for i in range(80):
        memory.add("其他", f"第{i}件小事", today=TODAY)
    assert len(memory.facts) == 80 and memory.find("m1") is None


# ------------------------------------------------------------ the session and the agent

def test_memory_tools(tmp_path):
    session = Session(tmp_path / "history")
    session.memory = Memory(tmp_path / "memory.json")
    changed = []
    session.on_memory = lambda: changed.append(1)
    assert session.run_tool("remember_fact", {"kind": "偏好", "text": "说话直接点"})["status"] == "OK"
    assert session.run_daily_tool("remember_fact", {"kind": "计划", "text": "搬家",
                                                    "date": "2026-10-11"})["status"] == "OK"
    assert session.run_tool("remember_zodiac", {"zodiac": "龙"})["status"] == "OK" and session.zodiac == "龙"
    assert len(changed) == 2
    assert "【小瓜记得的你】" in session.daily_context_text() and "说话直接点" in session.daily_context_text()
    assert "搬家" in session.daily_context_text()
    session.memory = None
    assert session.run_tool("forget_fact", {"id": "m1"})["status"] == "UNAVAILABLE"


def test_the_model_remembers_a_plan_and_sees_it_next_time(tmp_path):
    session = Session(tmp_path / "history")
    session.memory = Memory(tmp_path / "memory.json")
    client = ScriptedClient([
        [tool("remember_fact", kind="计划", text="周日搬家", date=(date.today() + timedelta(days=4)).isoformat())],
        [text("好，周日搬，到时候提醒你。")],
        [text("记着呢，周日搬家。")],
    ])
    agent = XiaoguaAgent(client=client, session=session)
    agent.ask("那就周日搬吧")
    names = {t["name"] for t in client.requests[0]["tools"]}
    assert {"remember_fact", "forget_fact", "close_fact", "remember_zodiac"} <= names
    agent.ask("我哪天搬家来着")
    assert "4天后）：搬家" in client.requests[-1]["system"][1]["text"]           # the day is not repeated


# ------------------------------------------------------------ the morning line

def test_morning_line_without_a_zodiac_asks_for_it():
    line = Session(None).greeting(NINE)
    assert line.startswith("今天宜洗澡放松、灭虫除害，忌祭拜祖先") and "告诉我你属什么" in line
    assert line.endswith("明天寒露。")


def test_morning_line_for_a_zodiac_and_on_a_solar_term():
    session = Session(None)
    session.zodiac = "猴"
    assert "跟你属猴相冲，大事缓缓" in session.greeting(NINE) and "好。" in session.greeting(NINE)
    term_day = datetime(2026, 10, 8, 9, 0).astimezone()
    assert session.greeting(term_day).startswith("今天寒露。")


def test_morning_line_puts_plans_first_and_asks_once():
    session = Session(None)
    session.zodiac = "龙"
    session.memory = Memory()
    session.memory.add("计划", "体检", "2026-10-07", today=TODAY)
    assert session.greeting(NINE).startswith("别忘了今天的事：体检。日子跟你属龙不冲不合")
    session.memory.close("m1", "做完了")
    session.memory.add("计划", "面试", "2026-10-06", today=TODAY)
    assert session.greeting(NINE, mark=False) == "10月6日的「面试」怎么样了？跟我说说。明天寒露。"
    assert session.greeting(NINE) == "10月6日的「面试」怎么样了？跟我说说。明天寒露。"
    assert session.greeting(NINE).startswith("今天宜")                     # asked once only


# ------------------------------------------------------------ the pet and the settings page

@pytest.fixture
def qt(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    monkeypatch.setenv("MEIHUA_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from meihua.companion import app as companion, config
    monkeypatch.setattr(config, "CREDENTIAL_PREFIX", "meihua-xiaogua-pytest-" + tmp_path.name)
    monkeypatch.setattr(companion, "start_hotkey", lambda combo, bridge, voice=None: type("L", (), {"stop": lambda s: None})())
    return companion


def test_the_pet_greets_once_a_day(qt):
    from meihua.companion.config import Config
    pet = qt.Pet(qt.OfflineAgent(), "Ctrl+Alt+X")
    pet.show()
    assert not pet.chat.today_line.isHidden()                               # preview on the welcome
    assert pet.greet_today() is True and pet.bubble.isVisible()
    assert "宜" in pet.bubble.toPlainText() and Config.load().last_greet == date.today().isoformat()
    assert pet.greet_today() is False
    pet.bubble.hide()
    pet.open_chat()
    assert not pet.bubble.isVisible()


def test_memory_learnt_in_the_chat_reaches_the_settings_page(qt):
    app = qt.Companion(qt.Config.load())
    session = app.pet.session
    assert app.settings.memory is session.memory
    session.run_daily_tool("remember_fact", {"kind": "称呼", "text": "叫他老王"})   # as the worker would
    items = [app.settings.memory_list.item(i).text() for i in range(app.settings.memory_list.count())]
    assert items == ["称呼：叫他老王"]
    app.settings.memory_list.item(0).setSelected(True)
    app.settings._forget_selected()
    assert session.memory.facts == [] and "还没记下什么" in app.settings.memory_list.item(0).text()


def test_forgetting_everything_takes_two_clicks(qt):
    app = qt.Companion(qt.Config.load())
    app.pet.session.memory.add("偏好", "说话直接点")
    app.settings.refresh_memory()
    app.settings.forget_all_button.click()
    assert len(app.pet.session.memory.facts) == 1 and app.settings.forget_all_button.text() == "再点一次确认"
    app.settings.forget_all_button.click()
    assert app.pet.session.memory.facts == [] and "已忘掉 1 条" in app.settings.memory_status.text()


def test_welcome_shows_how_long_we_have_been_together(qt):
    from meihua.companion.config import Config
    config = Config.load()
    config.first_day = "2026-09-24"
    config.save()
    pet = qt.Pet(qt.OfflineAgent(), "Ctrl+Alt+X")
    assert pet.chat.stats_line.text().startswith("陪你第 ") and not pet.chat.stats_line.isHidden()
