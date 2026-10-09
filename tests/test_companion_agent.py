"""The companion's tool loop, exercised with a scripted client (no API calls)."""

from __future__ import annotations

import itertools
from types import SimpleNamespace as NS


from meihua.companion import tools
from meihua.companion.agent import XiaoguaAgent

_ids = itertools.count()


def tool(name, **arguments):
    return NS(type="tool_use", id=f"tu_{next(_ids)}", name=name, input=arguments)


def text(value):
    return NS(type="text", text=value)


class ScriptedClient:
    """Returns pre-written assistant turns in order and records every request."""

    def __init__(self, turns):
        self.turns, self.requests = list(turns), []
        self.messages = self

    def create(self, **kwargs):
        # Snapshot: the loop keeps appending to the same list after the call,
        # while the real SDK serializes the request at call time.
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        content = self.turns.pop(0)
        stop = "tool_use" if any(b.type == "tool_use" for b in content) else "end_turn"
        return NS(content=content, stop_reason=stop)


PASSING_RECORD = {
    "schema_version": "daily-yigua-reading-v1", "method": "meihua", "calculation_confidence": "A",
    "claims": [{"text": "本卦显示当前格局。", "evidence_ids": ["MH-01"], "strength": 1,
                "conditions": ["限这次面试"], "reality_checks": ["面试官的反馈"]}],
    "actions": [{"text": "先跟 HR 书面确认时间地点。", "evidence_ids": ["MH-02", "WORK-01"],
                 "reality_anchor": "HR 的回复", "reversible": True, "risk_level": "low"}],
    "uncertainties": ["不知道对方的安排"], "prohibited_topics": []}


def test_cast_now_uses_the_live_calendar():
    result = tools.cast_now("今天面试能成吗")
    assert result["status"] == "OK"
    assert result["primary"]["name"] and result["time"]["hour_branch"] in "子丑寅卯辰巳午未申酉戌亥"
    assert tools.cast_now("   ")["status"] == "INVALID_INPUT"


def test_tool_errors_come_back_as_data():
    assert tools.run_tool("no_such_tool", {})["status"] == "UNKNOWN_TOOL"
    bad = tools.run_tool("almanac_day", {"date": "不是日期"})
    assert bad["status"] == "TOOL_ERROR"


def test_every_schema_has_a_function():
    from meihua.companion import fast
    named = {s["name"] for s in tools.TOOL_SCHEMAS + tools.DAILY_TOOL_SCHEMAS + [fast.daily_schema()]}
    assert named == set(tools.TOOL_FUNCTIONS)


def test_answer_after_cast_is_blocked_until_the_gate_passes():
    client = ScriptedClient([
        [tool("cast_now", question="今天面试能成吗")],
        [text("能成。")],                                   # tries to skip the gate
        [tool("validate_reading", reading_record=PASSING_RECORD)],
        [text("小瓜看过了：能成，早点到。")],
    ])
    reply = XiaoguaAgent(client=client).ask("今天面试能成吗")
    assert reply.validated is True
    assert reply.text.startswith("小瓜看过了")
    nudge = client.requests[2]["messages"][-1]["content"][0]["text"]
    assert "validate_reading" in nudge
    assert [c["tool"] for c in reply.tool_calls] == ["cast_now", "validate_reading"]


def test_persistent_gate_skipping_is_reported_not_hidden():
    client = ScriptedClient([[tool("cast_now", question="说说明天的面试")]] + [[text("随便说说")]] * 3)
    reply = XiaoguaAgent(client=client).ask("说说明天的面试")
    assert reply.validated is False and reply.error


def test_system_prompt_is_cached_and_tools_are_declared():
    client = ScriptedClient([[text("在的")]])
    XiaoguaAgent(client=client).ask("你好")
    request = client.requests[0]
    assert request["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert {t["name"] for t in request["tools"]} >= {"cast_now", "validate_reading", "almanac_day", "daily_reading"}


def test_model_rejecting_thinking_falls_back_once():
    class Rejecting(ScriptedClient):
        def create(self, **kwargs):
            if "thinking" in kwargs:
                self.requests.append(kwargs)
                raise type("BadRequest", (Exception,), {"status_code": 400})()
            return super().create(**kwargs)

    client = Rejecting([[text("在的")]])
    agent = XiaoguaAgent(client=client)
    assert agent.ask("你好").text == "在的"
    assert agent.thinking is False and "thinking" not in client.requests[-1]
