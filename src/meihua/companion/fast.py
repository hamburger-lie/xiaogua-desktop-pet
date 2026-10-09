"""One-call reading: the deterministic steps of a reading done in one tool, the evidence record built by code.

A reading used to take the model several rounds (起卦, 查卦义, then writing a reading_record by
hand for the gate). Here code does every step it already owns and assembles the reading_record
from the computed facts: every claim and action cites the evidence ids of the step that produced
it, then validate_reading checks it with the same rules as a hand-written one. The model only
picks the tool and talks.

Builders only; the tool that uses them (daily_reading) lives in session.py.
"""

from __future__ import annotations

from typing import Any

import meihua  # noqa: F401 — engines/checks on sys.path

from validate_reading import find_high_risk_hits, validate_reading  # type: ignore[import-not-found]

SCHEMA = "daily-yigua-reading-v1"
TOPIC_EVIDENCE = {"事业": "WORK-01", "合作": "COOP-01", "钱财": "MONEY-01", "感情": "REL-01", "其他": None}
FAST_TOOLS = ("daily_reading",)


# ---------------------------------------------------------------- the cast, briefly

def cast_brief(cast: dict) -> dict:
    out = {"本卦": cast["primary"]["name"], "互卦": cast["mutual"]["name"], "动爻": cast["moving_line"],
           "起卦时间": f"{cast['time']['datetime'][11:16]} {cast['time']['hour_branch']}时"}
    if cast.get("changed"):
        out.update({"变卦": cast["changed"]["name"],
                    "体": f"{cast['body']['name']}{cast['body']['element']}",
                    "用": f"{cast['use']['name']}{cast['use']['element']}",
                    "体用": cast["body_use_relation"]})
    return out


def hexagram_names(cast: dict) -> list[str]:
    names = [cast["primary"]["name"], cast["mutual"]["name"]]
    if cast.get("changed"):
        names.append(cast["changed"]["name"])
    return names


def _claims(cast: dict, scope: str) -> list[dict[str, Any]]:
    claims = [{"text": f"本卦{cast['primary']['name']}、互卦{cast['mutual']['name']}"
                       + (f"、变卦{cast['changed']['name']}" if cast.get("changed") else "")
                       + f"，动爻第{cast['moving_line']}爻：格局、过程与走向",
               "evidence_ids": ["MH-01"], "strength": 1, "conditions": [scope],
               "reality_checks": ["以实际看到的情况为准"]}]
    if cast.get("changed"):
        claims.append({"text": f"体卦{cast['body']['name']}属{cast['body']['element']}，"
                               f"用卦{cast['use']['name']}属{cast['use']['element']}，体用{cast['body_use_relation']}",
                       "evidence_ids": ["MH-02"], "strength": 1, "conditions": [scope],
                       "reality_checks": ["事情实际的难易"]})
    return claims


def _record(claims, actions, uncertainties, prohibited=()) -> dict:
    return {"schema_version": SCHEMA, "method": "meihua", "calculation_confidence": "A",
            "claims": claims, "actions": actions, "uncertainties": list(uncertainties),
            "prohibited_topics": list(prohibited)}


def check(record: dict) -> dict:
    result = validate_reading(record)
    return {"status": result["status"], "errors": result["errors"]}


def daily_record(cast: dict, topic: str, question: str) -> dict:
    """One concrete matter: the hexagram, a reversible next step, the topic's protocol."""
    protocol = TOPIC_EVIDENCE.get(topic) if topic in TOPIC_EVIDENCE else None
    evidence = ["MH-02"] + ([protocol] if protocol else [])
    actions = [{"text": "先做一步低成本、能回头的确认，再决定推进还是等等",
                "evidence_ids": evidence, "reality_anchor": "现实里能核对的一步：确认时间、条件或对方的意向",
                "reversible": True, "risk_level": "low"}]
    risky = find_high_risk_hits(question or "")
    uncertainties = ["卦只看这件事此刻的格局和走向，替代不了现实里的判断"]
    if risky:
        uncertainties.append("涉及" + "、".join(risky) + "：以专业意见为准")
    return _record(_claims(cast, "限这次所问"), actions, uncertainties, risky)


def daily_schema() -> dict[str, Any]:
    return {"name": "daily_reading",
            "description": "他问一件具体的事「能不能 / 成不成 / 要不要」时调用，一次做完：起卦、查卦义、核对依据。"
                           "纯黄历和闲聊不用。",
            "input_schema": {"type": "object", "properties": {
                "question": {"type": "string", "description": "用户原话"},
                "topic": {"type": "string", "enum": list(TOPIC_EVIDENCE)}},
                "required": ["question", "topic"]}}
