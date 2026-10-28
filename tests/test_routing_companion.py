"""小瓜's routing (companion/routing.py): every case in src/meihua/tests/companion/routing.jsonl, and the agent obeying it."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

import meihua
from meihua.companion import routing
from meihua.companion.agent import XiaoguaAgent
from meihua.companion.session import Session

from test_companion_agent import ScriptedClient, text, tool  # noqa: E402

CASES = [json.loads(line) for line in
         meihua.data_path("tests", "companion", "routing.jsonl").read_text(encoding="utf-8").splitlines() if line]
NOW = datetime(2026, 10, 28, 15, 0).astimezone()


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_each_golden_case_is_routed_as_written(case):
    last = None
    if case.get("last"):
        before = case["last"]
        last = routing.Route("routed", before["tool"], before["method"], "X",
                             at=NOW - timedelta(minutes=before["minutes_ago"]))
    route = routing.pick(case["input"], last, NOW)
    assert (route.kind, route.tool) == (case["kind"], case["tool"]), route
    if case.get("rule"):
        assert route.rule == case["rule"]


def test_the_cases_cover_every_kind_and_every_reading_tool():
    assert {case["kind"] for case in CASES} == {"named", "follow-up", "space", "almanac", "routed", "chat", "confirm",
                                                "declined"}
    assert {case["tool"] for case in CASES} - {None} == {"daily_reading", "ziwei_chart", "qimen_chart", "qimen_pick",
                                                         "bazi_chart", "xiaoliu_chart", "space_check"}


def test_only_the_routed_reading_is_offered_and_another_is_refused(tmp_path):
    question = "我1995年5月12日上午10点半出生，适合做什么工作"
    client = ScriptedClient([[tool("ziwei_chart", question=question, birth="1995-05-12 10:30", sex="男")],
                             [text("先排个八字看看。\n〔平静〕")]])
    reply = XiaoguaAgent(client=client, session=Session(tmp_path)).ask(question)
    offered = {t["name"] for t in client.requests[0]["tools"]}
    assert "bazi_chart" in offered and not offered & {"ziwei_chart", "daily_reading", "qimen_chart", "space_check"}
    assert reply.tool_calls == [{"tool": "ziwei_chart", "status": "NOT_ROUTED"}] and "拦下:ziwei_chart" in reply.checks
    assert reply.route == "八字·ROUTE-BIRTH"
    told = client.requests[0]["messages"][-1]["content"][-1]["text"]
    assert "这题用八字：调 bazi_chart" in told and "不用跟他解释" in told


def test_a_follow_up_keeps_the_last_reading_in_the_same_conversation(tmp_path):
    session = Session(tmp_path)
    client = ScriptedClient([[text("要出生时间和性别。\n〔平静〕")], [text("财帛宫要先排盘。\n〔平静〕")],
                             [text("在的。\n〔平静〕")]])
    agent = XiaoguaAgent(client=client, session=session)
    agent.ask("用紫微斗数看看我")
    follow = agent.ask("那我的财帛宫呢")
    assert follow.route == "紫微斗数·XG-FOLLOW"
    assert "ziwei_chart" in {t["name"] for t in client.requests[1]["tools"]}
    session.new_chat()                                       # another conversation: nothing to follow
    assert agent.ask("那我的财帛宫呢").route == "chat·XG-CHAT"


def test_a_follow_up_keeps_the_hexagram_its_matter_was_given(tmp_path):
    client = ScriptedClient([[tool("daily_reading", question="今天下午去面试能成吗", topic="事业")],
                             [text("能成，中间会卡一下。\n〔平静〕")],
                             [tool("daily_reading", question="为什么这么说", topic="事业")],    # the model casts again…
                             [text("卦里中间有个卡点。\n〔平静〕")]])
    agent = XiaoguaAgent(client=client, session=Session(tmp_path))
    first = agent.ask("今天下午去面试能成吗")
    again = agent.ask("为什么这么说")
    assert first.tool_calls == [{"tool": "daily_reading", "status": "OK"}]
    assert again.route == "梅花易数·XG-FOLLOW" and again.tool_calls == [{"tool": "daily_reading", "status": "REUSED"}]


def test_a_question_about_a_system_needs_no_verdict_first():
    from meihua.companion import harness
    assert not harness.verdict_late("半准半参考吧，看个大方向。", "八字准不准")
    assert harness.verdict_late("半准半参考吧，看个大方向。", "这单签得成吗")
