"""Tools the 小瓜 companion exposes to the model.

Each tool wraps a deterministic function that already exists in this package (the
梅花 cast, the 黄历, the evidence gate), so the model never computes a hexagram or a
calendar fact itself — it calls these and interprets the results. Schemas follow the
Messages API tool format.
"""

from __future__ import annotations

import re
from datetime import date as Date, datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo

import meihua  # noqa: F401 — puts engines/router/checks on sys.path

import almanac  # type: ignore[import-not-found]
import cast_hexagram  # type: ignore[import-not-found]
import lunar  # type: ignore[import-not-found]
from validate_reading import validate_reading  # type: ignore[import-not-found]

BRANCHES = "子丑寅卯辰巳午未申酉戌亥"
DEFAULT_TIMEZONE = "Asia/Shanghai"


def lunar_now(timezone: str = DEFAULT_TIMEZONE, now: datetime | None = None) -> dict:
    """Current local time converted to the lunar calendar (ICU-generated table, no Node)."""
    moment = (now or datetime.now(ZoneInfo(timezone))).replace(microsecond=0)
    data = lunar.convert(moment.isoformat(), timezone)
    return {
        "datetime": moment.isoformat(),
        "timezone": timezone,
        "year_name": data["lunar"]["year_name"],
        "year_branch": BRANCHES.index(data["lunar"]["year_name"][-1]) + 1,
        "lunar_month": data["lunar"]["month"],
        "lunar_day": data["lunar"]["day"],
        "is_leap_month": data["lunar"]["is_leap_month"],
        "hour_branch": data["local_clock"]["hour_branch"],
        "hour_branch_number": data["local_clock"]["hour_branch_number"],
    }


def _trigram(t: dict) -> dict:
    return {"name": t["name"], "element": t["element"], "direction": t["direction"]}


def cast_now(question: str, timezone: str = DEFAULT_TIMEZONE, now: datetime | None = None) -> dict:
    """Traditional year/month/day/hour Meihua cast at the current moment."""
    if not question.strip():
        return {"status": "INVALID_INPUT", "error": "question 不能为空，须保留用户原话"}
    lunar = lunar_now(timezone, now)
    upper = lunar["year_branch"] + lunar["lunar_month"] + lunar["lunar_day"]
    total = upper + lunar["hour_branch_number"]
    result = cast_hexagram.cast(upper, total, total, "传统农历年月日时法", {
        "year_branch": lunar["year_branch"], "lunar_month": lunar["lunar_month"],
        "lunar_day": lunar["lunar_day"], "hour_branch": lunar["hour_branch_number"]})
    out = {
        "status": "OK",
        "question": question,
        "time": lunar,
        "method": result["method"],
        "primary": {"number": result["primary"]["number"], "name": result["primary"]["name"],
                    "upper": _trigram(result["primary"]["upper"]), "lower": _trigram(result["primary"]["lower"])},
        "mutual": {"number": result["mutual"]["number"], "name": result["mutual"]["name"]},
        "moving_line": result["moving_line"],
    }
    if result.get("changed"):
        out.update(
            changed={"number": result["changed"]["number"], "name": result["changed"]["name"]},
            body=_trigram(result["body"]),
            use=_trigram(result["use"]),
            body_use_relation=result["body_use_relation"],
            locator=_trigram(result["lost_item_locator"]),
        )
    return out


def lookup_hexagrams(names: list[str]) -> dict:
    """Core pattern and action hint for each hexagram, from references/hexagrams.md."""
    text = meihua.data_path("references", "hexagrams.md").read_text(encoding="utf-8")
    rows = {m.group(2): {"number": int(m.group(1)), "pattern": m.group(3).strip(), "hint": m.group(4).strip()}
            for m in re.finditer(r"^\|\s*(\d+)\s*\|\s*([^|]+?)\s*\|\s*([^|]+)\|\s*([^|]+)\|", text, re.M)}
    found = {n: rows[n] for n in names if n in rows}
    return {"status": "OK", "hexagrams": found, "missing": [n for n in names if n not in rows]}


def today(timezone: str = DEFAULT_TIMEZONE) -> Date:
    return datetime.now(ZoneInfo(timezone)).date()


def _day(value: str | None) -> Date:
    return Date.fromisoformat(value) if value else today()


def almanac_day(date: str | None = None, zodiac: str | None = None) -> dict:
    """The 黄历 page for a day (default today); with a 属相, how the day sits with it."""
    return almanac.day_almanac(_day(date), zodiac or None)


def almanac_pick_days(activity: str, start: str | None = None, days: int = 30,
                      zodiac: str | None = None) -> dict:
    """Days from `start` whose 宜 covers the activity (and do not clash the 属相)."""
    return almanac.pick_days(activity, _day(start), days, zodiac or None)


def _validate(reading_record: dict) -> dict:
    result = validate_reading(reading_record)
    return {"status": result["status"], "errors": result["errors"]}


TOOL_FUNCTIONS: dict[str, Callable[..., dict]] = {
    "cast_now": cast_now,
    "lookup_hexagrams": lookup_hexagrams,
    "validate_reading": _validate,
    "almanac_day": almanac_day,
    "almanac_pick_days": almanac_pick_days,
    # the one-call reading needs a session: a throwaway one here
    "daily_reading": lambda **kw: _session_tool("daily_reading", kw),
}


def _session_tool(name: str, arguments: dict) -> dict:
    from .session import Session

    session = Session(None)
    return session.run_daily_tool(name, arguments)

_STR = {"type": "string"}
TOOL_SCHEMAS: list[dict[str, Any]] = [
    {"name": "cast_now",
     "description": "用当前时刻按传统农历年月日时法起梅花卦。返回本卦、互卦、变卦、动爻、体用五行与生克、各卦方位。每个求测问题只调用一次，不得为挑结果重复起卦。",
     "input_schema": {"type": "object", "properties": {
         "question": {"type": "string", "description": "用户问题原话"}}, "required": ["question"]}},
    {"name": "lookup_hexagrams",
     "description": "查卦名对应的核心格局与行动提示（references/hexagrams.md）。解释卦义前先查，不凭记忆。",
     "input_schema": {"type": "object", "properties": {
         "names": {"type": "array", "items": _STR, "description": "卦名，如 [\"归妹\",\"既济\",\"临\"]"}},
         "required": ["names"]}},
    {"name": "validate_reading",
     "description": "输出前的证据闸门。按 contracts/reading-record.md 组装 reading_record（claims/actions 都带 evidence_ids，actions 带 reality_anchor、reversible=true、risk_level=low）。PASS 才能回答；REVISE 按 errors 改后重交。",
     "input_schema": {"type": "object", "properties": {"reading_record": {"type": "object"}},
                      "required": ["reading_record"]}},
]


# The 黄历, plus a cast for one concrete decision (with the same gate).
ALMANAC_SCHEMAS: list[dict[str, Any]] = [
    {"name": "almanac_day",
     "description": "查某一天的黄历：宜忌（老词带 plain 白话）、冲哪个属相、煞方、黄道黑道、建除、财神喜神方位、各时辰吉凶。"
                    "传了属相（或用户已记下属相）会多给 for_you：这天跟属相是冲/合/刑/害、day_tone、太岁、对他好的时辰。"
                    "今天的已在【今天】里，问别的日子才调。",
     "input_schema": {"type": "object", "properties": {
         "date": {"type": "string", "description": "公历日期 YYYY-MM-DD，按【今天】换算；不传就是今天"},
         "zodiac": {"type": "string", "description": "属相一个字，如 虎；不传就用已记下的"}}}},
    {"name": "almanac_pick_days",
     "description": "挑日子：从 start 起 days 天内，黄历宜做这件事、又不忌、也不冲用户属相的日子，好的排前面。"
                    "activity 用常见说法（搬家、结婚、订婚、开业、签约、买房、买车、装修、出行、理发、入职、面试、聚会、看病、求财、学习…）。",
     "input_schema": {"type": "object", "properties": {
         "activity": _STR,
         "start": {"type": "string", "description": "起始公历日期 YYYY-MM-DD，默认今天"},
         "days": {"type": "integer", "description": "往后看几天，默认 30，最多 120"},
         "zodiac": _STR}, "required": ["activity"]}},
]
DAILY_TOOL_SCHEMAS: list[dict[str, Any]] = ALMANAC_SCHEMAS + [
    s for s in TOOL_SCHEMAS if s["name"] in ("cast_now", "lookup_hexagrams", "validate_reading")]


def run_tool(name: str, arguments: dict) -> dict:
    """Execute one tool; errors come back as data so the model can correct itself."""
    function = TOOL_FUNCTIONS.get(name)
    if function is None:
        return {"status": "UNKNOWN_TOOL", "tool": name}
    try:
        return function(**arguments)
    except (TypeError, ValueError, KeyError, OSError) as error:
        return {"status": "TOOL_ERROR", "tool": name, "error": f"{type(error).__name__}: {error}"}
