"""小瓜's routing (companion/routing.py): every case in src/meihua/tests/companion/routing.jsonl, and the agent obeying it."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

import meihua
from meihua.companion import routing, understand
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


PLAIN = [json.loads(line) for line in
         meihua.data_path("tests", "companion", "plain.jsonl").read_text(encoding="utf-8").splitlines() if line]


def _label(route):
    return {"almanac": "almanac", "declined": "declined"}.get(route.kind) or route.tool or "chat"


def _last(case):
    before = case.get("last")
    if not before:
        return None
    return routing.Route("routed", before["tool"], before["method"], "X", at=NOW - timedelta(minutes=before["minutes_ago"]),
                         question=before["question"])


@pytest.mark.parametrize("case", PLAIN, ids=[case["id"] for case in PLAIN])
def test_plain_words_get_the_reading_the_policy_gives_their_form(case):
    """Code first; what code cannot tell goes through the form a careful reader fills (written in the case)."""
    asked = []

    def read(question, last_question):
        asked.append(last_question)
        return understand.check(case["form"], question, last_question is not None)

    route = routing.pick(case["input"], _last(case), NOW, read=read)
    assert _label(route) in case["ok"], (route.label, route.form)
    assert route.by == ("听懂" if asked else "代码")
    if asked and case.get("last"):
        assert asked == [case["last"]["question"]]       # a follow-up is read beside the last question


def test_the_plain_cases_cover_every_kind_of_form():
    assert {case["form"]["类"] for case in PLAIN} == set(understand.KINDS)


@pytest.mark.parametrize("words", ["你好", "晚安", "嗯嗯好的", "谢谢小瓜", "帮我起个卦", "提醒我明天八点开会",
                                   "用紫微斗数看看我", "摇个六爻看看", "今天宜什么", "我家户型采光不好",
                                   "我2000年1月1号中午出生，男，性格怎么样"])
def test_code_decides_without_the_model_when_it_can(words):
    def read(question, last_question):
        raise AssertionError("the model was asked")

    assert routing.pick(words, None, NOW, read=read).by == "代码"


def test_the_form_is_checked_before_it_is_used():
    check = understand.check
    assert check({"类": "算命"}, "帮我算算", False) == (None, ["类不对：算命"])
    assert check(None, "帮我算算", False)[0] is None
    form, notes = check({"类": "命", "出生": "1995年5月12日"}, "帮我算算命", False)        # not in his words
    assert form["出生"] == "" and "原话里没有" in notes[0]
    form, notes = check({"类": "命", "出生": "去年夏天"}, "我去年夏天生的", False)          # no number in it
    assert form["出生"] == ""
    assert check({"类": "日子"}, "搬家好不好", False)[0]["类"] == "选择"                    # no day, no hour
    assert check({"类": "日子"}, "明天搬家好不好", False)[0]["类"] == "日子"
    assert check({"类": "房间"}, "这事能成吗", False)[0]["类"] == "结果"                    # no room, no thing in it
    assert check({"类": "结果", "接上句": True}, "那周末呢", False)[0]["接上句"] is False     # nothing to follow
    assert check({"类": "结果", "快": "true", "长远": "是"}, "快看看", False)[0] | {} == \
        {"类": "结果", "出生": "", "长远": True, "快": True, "接上句": False, "算法": ""}
    assert check({"类": "结果", "算法": "塔罗"}, "能成吗", False)[0]["算法"] == ""


def test_the_answer_is_found_inside_a_fence_or_a_sentence():
    assert understand.parse('```json\n{"类": "选择"}\n```') == {"类": "选择"}
    assert understand.parse('好的：{"类": "房间", "快": false}') == {"类": "房间", "快": False}
    assert understand.parse("这是选择题") is None
    assert understand.parse("[1, 2]") is None


def test_a_failed_reading_falls_back_to_the_keywords():
    route = routing.pick("换工作好还是留下来好", None, NOW, read=lambda q, last: (None, ["没听成：TimeoutError"]))
    assert route.by == "关键词" and route.label.endswith("·关键词") and route.notes == ["没听成：TimeoutError"]


def test_the_reading_call_is_one_short_call_without_tools():
    client = ScriptedClient([[text('{"类": "房间", "出生": "", "长远": false, "快": false, "接上句": false, "算法": ""}')]])
    form, notes = understand.read(client, "m", "镜子对着床可以吗")
    assert form["类"] == "房间" and notes == []
    request = client.requests[0]
    assert request["system"] == understand.PROMPT and "tools" not in request and request["max_tokens"] <= 300
    assert request["messages"][0]["content"] == "这一句：镜子对着床可以吗"
    assert understand.read(ScriptedClient([[text("我觉得是房间")]]), "m", "镜子对着床可以吗") == (None, ["没填表"])

    class Down:
        messages = None

    assert understand.read(Down(), "m", "能成吗")[1] == ["没听成：AttributeError"]


def test_the_agent_reads_plain_words_and_offers_only_their_reading(tmp_path):
    question = "床放在窗户下面好不好"
    client = ScriptedClient([[text('{"类": "房间"}')],
                             [text("床别贴着窗，窗下漏风又吵，挪到靠墙那侧更好睡。\n〔平静〕")]])
    agent = XiaoguaAgent(client=client, session=Session(tmp_path), understands=True)
    reply = agent.ask(question)
    assert client.requests[0]["system"] == understand.PROMPT                 # the form first…
    offered = {t["name"] for t in client.requests[1]["tools"]}
    assert "space_check" in offered and not offered & {"daily_reading", "bazi_chart", "xiaoliu_chart"}
    assert reply.route == "风水（空间观察）·ROUTE-SPACE·听懂"
    assert "这题用风水（空间观察）：调 space_check" in client.requests[1]["messages"][-1]["content"][-1]["text"]


def test_the_agent_asks_no_form_when_code_can_tell(tmp_path):
    client = ScriptedClient([[text("晚安呀。\n〔平静〕")]])
    reply = XiaoguaAgent(client=client, session=Session(tmp_path), understands=True).ask("晚安")
    assert len(client.requests) == 1 and reply.route == "chat·XG-CHAT"
