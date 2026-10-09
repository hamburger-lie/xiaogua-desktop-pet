"""The 黄历 engine, the 属相 relations, the session's 黄历 context, and the pet answering offline."""

from __future__ import annotations

import os
from datetime import date, datetime

import pytest

import meihua  # noqa: F401 — engines on sys.path
import almanac  # type: ignore[import-not-found]  # noqa: E402

from meihua.companion import tools  # noqa: E402
from meihua.companion.agent import SYSTEM_PROMPT, XiaoguaAgent  # noqa: E402
from meihua.companion.session import Session, daily_context_text  # noqa: E402

from test_companion_agent import ScriptedClient, text, tool  # noqa: E402

DAY = date(2026, 10, 7)
MORNING = datetime(2026, 10, 7, 10, 0).astimezone()


# ------------------------------------------------------------ the 黄历 page

def test_a_known_day():
    page = almanac.day_almanac(DAY)
    assert page["ganzhi"]["day"] == "甲寅" and page["lunar"] == "丙午年 八月廿七"
    assert page["clash"]["zodiac"] == "猴" and page["clash"]["sha_direction"] == "北"
    assert page["day_god"] == {"name": "青龙", "kind": "黄道", "luck": "吉"}
    assert "沐浴" in [i["term"] for i in page["yi"]] and "嫁娶" in [i["term"] for i in page["ji"]]
    assert {"term": "嫁娶", "plain": "结婚办喜事"} in page["ji"]
    assert len(page["hours"]) == 12 and page["hours"][0]["range"] == "00:00-00:59"


def test_funeral_terms_fold_into_one_plain_word():
    page = almanac.day_almanac(DAY)
    assert almanac.plain_text(page["yi"]) == "洗澡放松、灭虫除害、丧葬事"


@pytest.mark.parametrize("mine, other, expected", [
    ("寅", "申", ["冲", "刑"]), ("子", "午", ["冲"]), ("子", "丑", ["六合"]), ("寅", "午", ["三合"]), ("子", "卯", ["刑"]),
    ("子", "未", ["害"]), ("午", "午", ["本命", "刑"]), ("寅", "寅", ["本命"]), ("寅", "巳", ["刑", "害"]),
    ("巳", "申", ["六合", "刑"]), ("子", "辰", ["三合"]), ("子", "寅", []),
])
def test_branch_relations(mine, other, expected):
    assert almanac.relations(mine, other) == expected


def test_tone_of_a_day():
    assert almanac.tone(["冲", "刑"]) == "冲"
    assert almanac.tone(["六合", "刑"]) == "合中带刑"
    assert almanac.tone(["三合"]) == "顺" and almanac.tone(["害"]) == "不顺" and almanac.tone([]) == "平"


def test_the_day_for_a_zodiac():
    monkey = almanac.day_almanac(DAY, "猴")["for_you"]
    assert monkey["clashed_today"] and monkey["day_tone"] == "冲"
    horse = almanac.day_almanac(DAY, "属马")["for_you"]
    assert horse["day_tone"] == "顺" and horse["tai_sui"] == ["值太岁（本命年）", "刑太岁"]   # 丙午年
    assert "子时 00:00-00:59" not in horse["good_hours"]                     # 子时 clashes 马
    with pytest.raises(ValueError):
        almanac.day_almanac(DAY, "猫")


def test_picking_days_for_moving():
    found = almanac.pick_days("搬家", DAY, 30, "虎")
    assert found["status"] == "OK" and found["terms"] == ["入宅", "移徙"] and found["matches"]
    for entry in found["matches"]:
        day = date.fromisoformat(entry["date"])
        page = almanac.day_almanac(day, "虎")
        yi, ji = {i["term"] for i in page["yi"]}, {i["term"] for i in page["ji"]}
        assert yi & {"入宅", "移徙"} and not ji & {"入宅", "移徙"}
        assert not page["for_you"]["clashed_today"]
    assert found["matches"][0]["for_you"] == "顺"                            # good days first


def test_picking_days_reports_clashes_unknown_words_and_approximations():
    clash = almanac.pick_days("理发", DAY, 60, "猴")
    for skipped in clash.get("skipped_clash_days", []):
        assert almanac.day_almanac(date.fromisoformat(skipped))["clash"]["zodiac"] == "猴"
    assert almanac.pick_days("蹦迪", DAY)["status"] == "UNKNOWN_ACTIVITY"
    assert "见贵" in almanac.pick_days("面试", DAY, 10)["approximate"]
    assert almanac.pick_days("理发", DAY, 9999)["days"] == almanac.MAX_SPAN_DAYS


def test_almanac_tools_default_to_today():
    assert tools.run_tool("almanac_day", {})["date"] == tools.today().isoformat()
    assert tools.run_tool("almanac_day", {"date": "2026-13-01"})["status"] == "TOOL_ERROR"


# ------------------------------------------------------------ the session

def test_daily_context_has_today_in_plain_words():
    unknown = daily_context_text(None, MORNING)
    assert "【今天】2026-10-07 星期三" in unknown and "宜：洗澡放松" in unknown and "冲猴" in unknown
    assert "remember_zodiac" in unknown                                      # ask when it matters
    known = daily_context_text("猴", MORNING)
    assert "【用户】属猴" in known and "day_tone=冲" in known
    assert "子时" not in known and "丑时" not in known                       # hours already past


def test_daily_tools_remember_the_zodiac_and_use_it(tmp_path):
    session = Session(tmp_path)
    told = []
    session.on_zodiac = told.append
    assert session.run_daily_tool("remember_zodiac", {"zodiac": "猫"})["status"] == "INVALID_INPUT"
    assert session.run_daily_tool("remember_zodiac", {"zodiac": "属虎"})["status"] == "OK"
    assert session.zodiac == "虎" and told == ["虎"]
    assert session.run_daily_tool("almanac_day", {"date": "2026-10-07"})["for_you"]["zodiac"] == "虎"
    assert session.run_daily_tool("almanac_day", {"date": "2026-10-07", "zodiac": "猴"})["for_you"]["zodiac"] == "猴"
    assert session.run_daily_tool("cast_now", {"question": "今天面试能成吗"})["status"] == "OK"


# ------------------------------------------------------------ the agent in 日常模式

def test_daily_question_gets_the_daily_prompt_tools_and_context(tmp_path):
    session = Session(tmp_path)
    session.zodiac = "猴"
    client = ScriptedClient([[text("今天冲你，大事往后放。")]])
    reply = XiaoguaAgent(client=client, session=session).ask("我今天适合干嘛")
    assert reply.validated and reply.text.startswith("今天冲你")
    system = client.requests[0]["system"]
    assert system[0]["text"] == SYSTEM_PROMPT and "【今天】" in system[1]["text"] and "属猴" in system[1]["text"]
    names = {t["name"] for t in client.requests[0]["tools"]}
    assert {"almanac_day", "almanac_pick_days", "remember_zodiac", "daily_reading", "validate_reading"} <= names
    assert not names & {"cast_now", "lookup_hexagrams"}
    assert session.chat.daily[-1]["q"] == "我今天适合干嘛"


def test_the_model_learns_the_zodiac_mid_conversation(tmp_path):
    session = Session(tmp_path)
    client = ScriptedClient([[tool("remember_zodiac", zodiac="虎")], [text("记住了，你属虎。")]])
    XiaoguaAgent(client=client, session=session).ask("我属虎")
    assert session.zodiac == "虎" and "属虎" in client.requests[1]["system"][1]["text"]


DAILY_RECORD = {
    "schema_version": "daily-yigua-reading-v1", "method": "meihua", "calculation_confidence": "A",
    "claims": [{"text": "本卦显示事情在推进。", "evidence_ids": ["MH-01"], "strength": 1,
                "conditions": ["限这次面试"], "reality_checks": ["面试官反馈"]}],
    "actions": [{"text": "提前到场，把作品带上。", "evidence_ids": ["MH-02", "WORK-01"],
                 "reality_anchor": "先跟 HR 书面确认时间地点", "reversible": True, "risk_level": "low"}],
    "uncertainties": ["不知道竞争者情况"], "prohibited_topics": []}


def test_a_cast_needs_the_gate(tmp_path):
    session = Session(tmp_path)
    client = ScriptedClient([
        [tool("cast_now", question="今天面试能成吗")],
        [text("能成。")],                                                    # skips the gate
        [tool("validate_reading", reading_record=DAILY_RECORD)],
        [text("能成，早点到。")],
    ])
    agent = XiaoguaAgent(client=client, session=session)
    reply = agent.ask("今天面试能成吗")
    assert reply.validated and reply.text == "能成，早点到。"
    statuses = {c["tool"]: c["status"] for c in reply.tool_calls}
    assert statuses["cast_now"] == "OK" and statuses["validate_reading"] == "PASS"


def test_a_talk_without_a_cast_needs_no_gate(tmp_path):
    session = Session(tmp_path)
    client = ScriptedClient([[text("想求财往东北走走，财神在那边。")]])
    reply = XiaoguaAgent(client=client, session=session).ask("今天财神在哪")
    assert reply.validated and len(client.requests) == 1


# ------------------------------------------------------------ the pet (headless Qt)

@pytest.fixture
def qt(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    monkeypatch.setenv("MEIHUA_HOME", str(tmp_path / "home"))
    from meihua.companion import app as companion
    return companion


@pytest.fixture
def pet(qt, monkeypatch):
    started = []
    monkeypatch.setattr(qt.threading, "Thread",
                        lambda target, args, daemon: type("T", (), {"start": lambda self: started.append(args)})())
    pet = qt.Pet(qt.OfflineAgent(), "Ctrl+Alt+X")
    pet.started = started
    return pet


def test_offline_daily_answer_is_the_almanac(pet):
    pet.agent.session = pet.session
    pet.session.zodiac = "猴"
    reply = pet.agent.ask("今天宜什么")
    assert "宜：" in reply.text and "忌：" in reply.text and "属猴" in reply.text and reply.validated
    assert pet.session.chat.daily[-1]["a"] == "（离线）"


def test_offline_a_yes_no_question_gets_the_local_cast(pet):
    pet.agent.session = pet.session
    reply = pet.agent.ask("明天面试能成吗")
    assert reply.text.startswith("离线起卦：本卦") and reply.tool_calls[0]["tool"] == "cast_now"


def test_a_zodiac_learnt_in_the_chat_is_saved_like_the_setting(pet):
    from meihua.companion.config import Config
    seen = []
    pet.zodiac_changed.connect(seen.append)
    pet.session.run_daily_tool("remember_zodiac", {"zodiac": "虎"})        # as the worker would
    assert Config.load().zodiac == "虎" and seen == ["虎"] and "属虎" in pet.chat.today_line.text()


def test_settings_window_sets_the_zodiac(qt):
    from meihua.companion import config
    from meihua.companion.settings_window import SettingsWindow
    cfg = config.Config.load()
    window = SettingsWindow(cfg)
    window.zodiac_box.setCurrentText("龙")
    assert cfg.zodiac == "龙" and config.Config.load().zodiac == "龙"
    window.zodiac_box.setCurrentText("不设置")
    assert cfg.zodiac == ""
    cfg.zodiac = "鸡"
    window.sync_from(cfg)
    assert window.zodiac_box.currentText() == "鸡"


