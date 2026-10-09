"""The one-call reading: daily_reading casts, looks the hexagrams up and passes the gate in code."""

from __future__ import annotations

from meihua.companion import fast
from meihua.companion.agent import XiaoguaAgent
from meihua.companion.session import Session

from test_companion_agent import ScriptedClient, text, tool  # noqa: E402


def test_daily_reading_and_risky_questions(tmp_path):
    session = Session(tmp_path)
    out = session.run_daily_tool("daily_reading", {"question": "今天面试能成吗", "topic": "事业"})
    assert out["status"] == "OK" and out["gate"] == "PASS" and out["topic"] == "事业"
    assert out["cast"]["本卦"] and set(out["meanings"]) >= {out["cast"]["本卦"]}
    assert "先给结论" in out["answer_first"]                                 # a 能不能 question
    record = fast.daily_record({"primary": {"name": "乾"}, "mutual": {"name": "乾"}, "moving_line": 1},
                               "钱财", "这只股票要不要全仓投资")
    assert record["prohibited_topics"] and fast.check(record)["status"] == "PASS"


def test_an_open_question_gets_no_verdict_cue(tmp_path):
    out = Session(tmp_path).run_daily_tool("daily_reading", {"question": "说说这次搬家", "topic": "其他"})
    assert out["status"] == "OK" and "answer_first" not in out


def test_the_agent_answers_a_matter_in_two_model_calls(tmp_path):
    session = Session(tmp_path)
    client = ScriptedClient([[tool("daily_reading", question="面试能成吗", topic="事业")], [text("能成，早点到。")]])
    reply = XiaoguaAgent(client=client, session=session).ask("面试能成吗")
    assert reply.validated and len(client.requests) == 2                  # no record-writing round, no nudge
    names = {t["name"] for t in client.requests[0]["tools"]}
    assert "daily_reading" in names and "cast_now" not in names           # the bare cast is not offered
