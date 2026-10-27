"""紫微 and 奇门 for 小瓜: the engine's chart in brief, what its stars and doors stand for, and the gate.

Until 2026-10-27 小瓜 said it did not do these. Both engines are admitted now (evidence/ziwei.md,
evidence/qimen.md), so 小瓜 draws one when the user names it. As with the 梅花 readings in
fast.py, code does every step it owns (the chart, the meanings, the reading_record and the gate) and
the model only asks for what is missing and talks. What the answer then says of the chart is checked
against the 「盘」 here by harness.py (chart_slips): keep the keys of brief_ziwei and brief_qimen as
they are, harness reads them back.

Meanings come from references/ziwei-stars.md and references/qimen-symbols.md, with the source lines.
"""

from __future__ import annotations

import re
from datetime import datetime
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo

import meihua  # noqa: F401 — engines/checks on sys.path

import cast_qimen  # type: ignore[import-not-found]
import cast_ziwei  # type: ignore[import-not-found]
import lunar  # type: ignore[import-not-found]
from validate_reading import find_high_risk_hits, validate_reading  # type: ignore[import-not-found]

from . import harness

DEFAULT_TIMEZONE = "Asia/Shanghai"
SCHEMA = "daily-yigua-reading-v1"
CHART_TOOLS = ("ziwei_chart", "qimen_chart")
NUMERALS = "一二三四五六七八九"
SEXES = {"男": "男", "女": "女", "男性": "男", "女性": "女", "male": "男", "female": "女"}
_BIRTH = re.compile(r"(\d{4})[-/年.](\d{1,2})[-/月.](\d{1,2})日?[ T]*(\d{1,2})[:：点](\d{1,2})")

ZIWEI_BOUNDS = ("只排本命盘结构（《全书》卷二）：杂曜、神煞、星曜庙旺、流年流月没排，不说。"
                "不谈寿命、疾病、生育、婚姻成败，不据盘评判别人（GUARD-07）。主星为空的宫借对宫主星参看，不说那一宫空白。")
QIMEN_BOUNDS = ("只排时家转盘拆补局的盘面：不判格局吉凶，不用置闰法、飞盘。方位是盘上的方位，"
                "不是他身边的方向，不说「往东南走」这种话。不用于赌博下注、伤人、对抗执法、逃避法律责任（GUARD-07）。")


@lru_cache(maxsize=None)
def meanings(document: str) -> dict[str, str]:
    """references/ziwei-stars.md or qimen-symbols.md: name -> 「白话（原文：要点）」."""
    text = meihua.data_path("references", document).read_text(encoding="utf-8")
    rows = re.findall(r"^\|\s*([^|\s]+)\s*\|\s*([^|]+?)\s*\|\s*[\d—]+\s*\|\s*([^|]+?)\s*\|\s*$", text, re.M)
    return {name: f"{plain}（原文：{source}）" for name, source, plain in rows}


def _record(method: str, confidence: str, claims: list[dict], actions: list[dict], uncertainties: list[str],
            prohibited: list[str]) -> dict:
    return {"schema_version": SCHEMA, "method": method, "calculation_confidence": confidence,
            "claims": claims, "actions": actions, "uncertainties": uncertainties, "prohibited_topics": prohibited}


def _gate(record: dict) -> dict:
    result = validate_reading(record)
    return {"gate": result["status"], **({"gate_errors": result["errors"]} if result["errors"] else {})}


def _step(evidence: list[str]) -> list[dict]:
    return [{"text": "先做一步低成本、能回头的确认，再决定推进还是等等", "evidence_ids": evidence,
             "reality_anchor": "现实里能核对的一步：确认时间、条件或对方的意向", "reversible": True, "risk_level": "low"}]


def _differences(main: dict, other: dict, rows: str, fields: tuple[str, ...], key: str) -> list[str]:
    """What a candidate chart says differently: the top-level fields, then row by row."""
    out = [f"{name}：{_said(main[name])} / {_said(other[name])}" for name in fields if main[name] != other[name]]
    for mine, theirs in zip(main[rows], other[rows]):
        parts = dict.fromkeys([*mine, *theirs])
        changed = [f"{part} {_said(mine.get(part))} / {_said(theirs.get(part))}"
                   for part in parts if part != key and mine.get(part) != theirs.get(part)]
        if changed:
            out.append(f"{mine[key]}：" + "；".join(changed))
    return out


def _said(value: Any) -> str:
    if value is True:
        return "是"
    if isinstance(value, list):
        return "、".join(value) or "无"
    return "无" if value in (None, "", False) else str(value)


# ---------------------------------------------------------------- 紫微

def brief_ziwei(chart: dict) -> dict:
    """The chart as 小瓜 is given it (and harness.chart_facts reads back)."""
    where = {s["name"]: p["name"] for p in chart["palaces"] for s in p["major"] + p["minor"]}
    rows = []
    for palace in chart["palaces"]:
        start, end = palace["decade"]
        row = {"宫": palace["name"], "干支": palace["stem"] + palace["branch"],
               "主星": [s["name"] for s in palace["major"]], "辅星": [s["name"] for s in palace["minor"]],
               "大限": f"{start}—{end}岁"}
        if palace["is_body_palace"]:
            row["身宫"] = True
        rows.append(row)
    return {"命宫": chart["soul_palace"], "身宫": chart["body_palace"], "五行局": chart["five_elements"],
            "命主": chart["soul_master"], "身主": chart["body_master"],
            "四化": [f"{star}化{kind}（{where.get(star, '未入盘')}）" for kind, star in chart["mutagen"].items()],
            "十二宫": rows}


def _hall(name: str) -> str:
    return name if name.endswith("宫") else name + "宫"


def _ziwei_gist(board: dict) -> str:
    soul = board["十二宫"][0]
    body = next(row["宫"] for row in board["十二宫"] if row.get("身宫"))
    stars = f"主星{'、'.join(soul['主星'])}" if soul["主星"] else "无主星（借对宫主星参看）"
    where = "与命宫同宫" if body == "命宫" else f"在{_hall(body)}"
    return (f"命宫在{board['命宫']}（{soul['干支']}），{stars}；身宫{where}（{board['身宫']}）；{board['五行局']}；"
            f"四化：{'、'.join(board['四化'])}")


def _decade_now(board: dict, born: int, today: datetime) -> str:
    age = lunar.lunar_date(today.date())["year"] - born + 1                     # 虚岁
    for row in board["十二宫"]:
        start, end = (int(n) for n in row["大限"].removesuffix("岁").split("—"))
        if start <= age <= end:
            return f"虚岁{age}，走{_hall(row['宫'])}这一限（{row['大限']}）"
    return f"虚岁{age}，还没起大限（{min(int(r['大限'].split('—')[0]) for r in board['十二宫'])}岁起）"


def ziwei_chart(question: str, birth: str, sex: str, longitude: float | None = None,
                timezone: str = DEFAULT_TIMEZONE, now: datetime | None = None) -> dict:
    """紫微本命盘 for a birth on the local clock (「1995-05-12 23:30」), its candidates, meanings and gate."""
    match = _BIRTH.search(str(birth or ""))
    if not match:
        return {"status": "NEED_INPUT", "missing": "birth",
                "note": "要公历出生日期和几点几分（出生地的钟表时间）。只记得农历生日就问公历；只知道大概时段就说排不准，问清楚再排。"}
    if SEXES.get(str(sex or "").strip()) is None:
        return {"status": "NEED_INPUT", "missing": "sex", "note": "问他性别（大限顺排逆排要用），别猜。"}
    year, month, day, hour, minute = (int(n) for n in match.groups())
    try:
        clock = datetime(year, month, day, hour, minute, tzinfo=ZoneInfo(timezone))
        result = cast_ziwei.run(clock.isoformat(), timezone, SEXES[str(sex).strip()],
                                None if longitude in (None, "") else float(longitude))
    except (ValueError, OverflowError) as error:
        return {"status": "INVALID_INPUT", "error": str(error)}
    board = brief_ziwei(result["chart"])
    timing = result["calculation_record"]["time_information"]
    candidates = [{"为什么": c["why"], "盘": brief_ziwei(c["chart"])} for c in result["candidates"]]
    for candidate in candidates:
        candidate["不同"] = _differences(board, candidate["盘"], "十二宫", ("命宫", "身宫", "五行局", "命主", "身主", "四化"), "宫")
    confidence = "B" if candidates else "A"
    present = {s for row in board["十二宫"] for s in row["主星"]} | {f"化{k}" for k in result["chart"]["mutagen"]}
    off = harness.off_limits("紫微斗数", question)
    claims = [{"text": _ziwei_gist(board), "evidence_ids": ["ZW-01", "ZW-03", "ZW-04"], "strength": 1,
               "conditions": ["限本命盘结构"], "reality_checks": ["对照他自己说的性格和经历"]}]
    if candidates:
        claims.append({"text": "出生时间落在口径分歧处，另有候选盘，只说各盘共同的部分", "evidence_ids": ["ZW-05", "GUARD-07"],
                       "strength": 1, "conditions": ["候选盘不同处两说"], "reality_checks": ["请他核对出生时间"]})
    record = _record("ziwei", confidence, claims, _step(["ZW-07"]),
                     ["紫微斗数是传统文化解释框架，不是被证实的预测方法"], find_high_risk_hits(question or ""))
    clock_note = f"{clock:%Y-%m-%d %H:%M}（{timezone}）"
    if timing.get("true_solar_time"):
        clock_note += f"，按出生地真太阳时 {timing['clock_used'][11:16]} 定时辰"
    out = {"status": "OK", "system": "紫微斗数", **_gate(record),
           "依据": "《紫微斗数全书》卷二；大限从命宫起（通行起法，卷二原文从命前一宫起）",
           "出生": clock_note + f"，农历{timing['lunar']['year']}年{'闰' if timing['lunar']['is_leap_month'] else ''}"
                   f"{timing['lunar']['month']}月{timing['lunar']['day']}日{result['chart']['hour']}时",
           "要点": _ziwei_gist(board), "现在": _decade_now(board, timing["lunar"]["year"], now or datetime.now(ZoneInfo(timezone))),
           "置信": confidence if not candidates else "B：有候选盘，两张一样的地方才说死，「不同」里的要两说",
           "盘": board, "象义": {name: text for name, text in meanings("ziwei-stars.md").items() if name in present},
           "边界": ZIWEI_BOUNDS}
    if candidates:
        out["候选盘"] = candidates
    if longitude in (None, ""):
        out["时辰"] = "按钟表时间定的时辰；他说了出生城市可带经度重排，按真太阳时更准"
    if off:
        out["不谈"] = f"他问到的{'、'.join(off)}紫微不看：如实说这部分不看，只说别的。"
    return out


# ---------------------------------------------------------------- 奇门

def brief_qimen(chart: dict) -> dict:
    rows = []
    for palace in chart["palaces"]:
        row = {"宫": palace["name"], "方位": palace["direction"]}
        for key, name in (("star", "星"), ("star_hosted", "寄星"), ("door", "门"), ("god", "神"),
                          ("sky", "天盘"), ("sky_hosted", "天盘寄"), ("earth", "地盘"), ("earth_hosted", "地盘寄")):
            if palace.get(key):
                row[name] = palace[key]
        rows.append(row)
    return {"局": f"{chart['dun']}{NUMERALS[chart['ju'] - 1]}局", "节气": chart["term"] + chart["yuan"],
            "值符": chart["zhi_fu"]["star"], "值符宫": chart["zhi_fu"]["palace"],
            "值使": chart["zhi_shi"]["door"], "值使宫": chart["zhi_shi"]["palace"], "九宫": rows}


def _qimen_gist(board: dict) -> str:
    side = {row["宫"]: row["方位"] for row in board["九宫"]}
    return (f"{board['节气']}，{board['局']}；值符{board['值符']}落{board['值符宫']}（盘上{side[board['值符宫']]}），"
            f"值使{board['值使']}落{board['值使宫']}（盘上{side[board['值使宫']]}）")


def qimen_chart(question: str, timezone: str = DEFAULT_TIMEZONE, now: datetime | None = None) -> dict:
    """时家转盘拆补局 for this moment, its candidates, meanings and gate. Not drawn for what GUARD-07 rules out."""
    off = harness.off_limits("奇门遁甲", question)
    if off:
        return {"status": "NOT_FOR_THIS", "system": "奇门遁甲",
                "note": f"奇门不用于{'、'.join(off)}这类事（GUARD-07），这局不起：如实说不排，别的事可以问。"}
    moment = (now or datetime.now(ZoneInfo(timezone))).replace(microsecond=0)
    moment = moment.replace(tzinfo=ZoneInfo(timezone)) if moment.tzinfo is None else moment.astimezone(ZoneInfo(timezone))
    try:
        result = cast_qimen.run(moment.isoformat(), timezone)
    except ValueError as error:
        return {"status": "INVALID_INPUT", "error": str(error)}
    board = brief_qimen(result["chart"])
    candidates = [{"为什么": c["why"], "盘": brief_qimen(c["chart"])} for c in result["candidates"]]
    for candidate in candidates:
        candidate["不同"] = _differences(board, candidate["盘"], "九宫", ("局", "节气", "值符", "值符宫", "值使", "值使宫"), "宫")
    confidence = "B" if candidates else "A"
    present = {row.get(part) for row in board["九宫"] for part in ("星", "寄星", "门", "神")} - {None}
    claims = [{"text": _qimen_gist(board), "evidence_ids": ["QM-01", "QM-02"], "strength": 1,
               "conditions": ["限此刻起局"], "reality_checks": ["事情实际的进展"]}]
    if candidates:
        claims.append({"text": "起局时刻落在口径分歧处，另有候选盘，只说各盘共同的部分", "evidence_ids": ["QM-05", "GUARD-07"],
                       "strength": 1, "conditions": ["候选盘不同处两说"], "reality_checks": ["事情实际的进展"]})
    record = _record("qimen", confidence, claims, _step(["QM-07"]),
                     ["奇门遁甲是传统文化解释框架，不是被证实的预测方法", "盘上方位不是身边的现实方向"],
                     find_high_risk_hits(question or ""))
    out = {"status": "OK", "system": "奇门遁甲", **_gate(record), "question": question,
           "依据": "时家转盘，拆补法定局，中五寄坤二，八神用白虎玄武",
           "起局": f"{moment:%Y-%m-%d %H:%M} {result['chart']['hour']}时",
           "要点": _qimen_gist(board),
           "置信": confidence if not candidates else "B：有候选盘，两张一样的地方才说死，「不同」里的要两说",
           "盘": board, "象义": {name: text for name, text in meanings("qimen-symbols.md").items() if name in present},
           "边界": QIMEN_BOUNDS}
    if candidates:
        out["候选盘"] = candidates
    return out


# ---------------------------------------------------------------- schemas

def schemas() -> list[dict[str, Any]]:
    return [
        {"name": "ziwei_chart",
         "description": "他点名要紫微斗数（看命盘、性格、做事方式、人生阶段）时调用，一次做完：按《紫微斗数全书》卷二排本命盘、"
                        "查星性、核对依据。要公历出生日期和几点几分（出生地钟表时间）和性别，缺哪样先问，不猜。"
                        "知道出生城市就传 longitude（东经度数），按真太阳时定时辰。返回 NEED_INPUT 就照 note 问他。",
         "input_schema": {"type": "object", "properties": {
             "question": {"type": "string", "description": "用户原话"},
             "birth": {"type": "string", "description": "公历出生时间 YYYY-MM-DD HH:MM，出生地钟表时间"},
             "sex": {"type": "string", "enum": ["男", "女"]},
             "longitude": {"type": "number", "description": "出生城市东经度数，如广州 113.3；不知道就不传"}},
             "required": ["question", "birth", "sex"]}},
        {"name": "qimen_chart",
         "description": "他点名要奇门遁甲看一件近期的事（时机、人事配合）时调用，一次做完：按此刻起时家转盘拆补局、"
                        "查门星神象义、核对依据。一件事只起一局：追问上一局的同一件事传 follow_up=true，沿用那一局。"
                        "赌博下注、伤人、对抗执法的事不起局（返回 NOT_FOR_THIS）。",
         "input_schema": {"type": "object", "properties": {
             "question": {"type": "string", "description": "用户原话"},
             "follow_up": {"type": "boolean", "description": "追问上一局的同一件事时传 true"}},
             "required": ["question"]}},
    ]
