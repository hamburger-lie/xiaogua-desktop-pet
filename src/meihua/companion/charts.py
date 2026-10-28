"""紫微, 奇门, 八字 and 小六壬 for 小瓜: the engine's chart in brief, what its parts stand for, and the gate.

Until 2026-10-27 小瓜 said it did not do these. The engines are admitted (evidence/ziwei.md, qimen.md,
bazi.md, xiaoliu-ren.md), so 小瓜 draws one when the user names it (八字 and 小六壬 since 10-28).
As with the 梅花 readings in fast.py, code does every step it owns (the chart, the meanings, the
reading_record and the gate) and the model only asks for what is missing and talks. What the answer
then says of the chart is checked against the 「盘」 here by harness.py (chart_slips): keep the keys
of the brief_* boards as they are, harness reads them back.

Meanings come from references/ziwei-stars.md and qimen-symbols.md (with source lines), and from the
十神 and 六宫 tables in references/bazi.md and xiaoliu-ren.md.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo

import meihua  # noqa: F401 — engines/checks on sys.path

import analyze_bazi  # type: ignore[import-not-found]
import cast_bazi  # type: ignore[import-not-found]
import cast_hexagram  # type: ignore[import-not-found]
import cast_qimen  # type: ignore[import-not-found]
import cast_xiaoliu_ren  # type: ignore[import-not-found]
import cast_ziwei  # type: ignore[import-not-found]
import lunar  # type: ignore[import-not-found]
from validate_reading import find_high_risk_hits, validate_reading  # type: ignore[import-not-found]

from . import harness

DEFAULT_TIMEZONE = "Asia/Shanghai"
SCHEMA = "daily-yigua-reading-v1"
CHART_TOOLS = ("ziwei_chart", "qimen_chart", "qimen_pick", "bazi_chart", "xiaoliu_chart", "space_check")
NUMERALS = "一二三四五六七八九"
SEXES = {"男": "男", "女": "女", "男性": "男", "女性": "女", "male": "男", "female": "女"}
_BIRTH = re.compile(r"(\d{4})[-/年.](\d{1,2})[-/月.](\d{1,2})日?[ T]*(\d{1,2})[:：点](\d{1,2})")

# Said in every chart result, right before the model writes; the harness still sends a runaway back.
LENGTH = "整条四五句、180 字以内：第一句结论，再两处盘面依据各一句，最后一句建议；别的不展开"
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


TIME_ASKED = re.compile(r"大运|大限|流年|今年|明年|这几年|未来|运势|运程|阶段|这十年|最近几年|什么时候")


def _asks_time(question: str) -> bool:
    """A 大运 / 大限 / 流年 line only when he asks about time: otherwise the answer spends itself on it."""
    return bool(TIME_ASKED.search(question or ""))


def _hour_line_note(clock: datetime, what: str) -> str | None:
    """Within 45 minutes of a 时辰 boundary (odd hours) true solar time could move the hour: say so, once."""
    since = (clock.hour * 60 + clock.minute - 60) % 120
    gap = min(since, 120 - since)
    if gap > 45:
        return None
    return (f"出生时刻离时辰交界只有 {gap} 分钟，按钟表时间定的{what}；知道出生城市（经度）按真太阳时能定得更准，"
            "结尾半句提一下就行，他不说也照这个讲")


def _said(value: Any) -> str:
    if value is True:
        return "是"
    if isinstance(value, list):
        return "、".join(value) or "无"
    if isinstance(value, dict):
        return "、".join(f"{k}{v}" for k, v in value.items()) or "无"
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
    leading = [row for row in board["十二宫"] if row["宫"] == "命宫" or row.get("身宫")]
    if not leading[0]["主星"]:                                    # 命宫 empty: read with its 对宫 (ZW-03)
        leading += [row for row in board["十二宫"] if row["宫"] == "迁移"]
    present = {s for row in leading for s in row["主星"]} | set(result["chart"]["mutagen"].values()) \
        | {f"化{k}" for k in result["chart"]["mutagen"]}
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
           "要点": _ziwei_gist(board),
           "置信": confidence if not candidates else "B：有候选盘，两张一样的地方才说死，「不同」里的要两说",
           "盘": board, "象义": {name: text for name, text in meanings("ziwei-stars.md").items() if name in present},
           "边界": ZIWEI_BOUNDS, "篇幅": LENGTH}
    if candidates:
        out["候选盘"] = candidates
    if _asks_time(question):
        out["现在"] = _decade_now(board, timing["lunar"]["year"], now or datetime.now(ZoneInfo(timezone)))
    note = _hour_line_note(clock, "时辰") if longitude in (None, "") else None
    if note:
        out["时辰"] = note
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
           "边界": QIMEN_BOUNDS, "篇幅": LENGTH}
    if candidates:
        out["候选盘"] = candidates
    return out


# ---------------------------------------------------------------- 奇门挑时辰 (QM-08)

MAX_PICK_HOURS = 12
THREE_WONDERS = {"乙": "日奇", "丙": "月奇", "丁": "星奇"}
_CLOCK = re.compile(r"(\d{4})[-/年.](\d{1,2})[-/月.](\d{1,2})日?[ T]*(\d{1,2})[:：点](\d{1,2})")
PICK_BOUNDS = ("按《统宗》凡例六的门奇会合和凡例五的得地排先后：门迫、受制的门不算会合，得地的排前；得时（门跟节令的衰旺）"
               "两部书说法不一，没看，回答里要说这一点。三奇是天盘的乙丙丁，不是星，别说成吉星；会合的宫只是盘上方位，"
               "不说往哪走；不说哪个时辰必成必败（QM-08、QM-04）。")


@lru_cache(maxsize=None)
def pick_matters() -> dict[str, dict[str, Any]]:
    """references/qimen-calculation.md 「选择」: 事 -> its everyday words, its 主门 (执事歌, or None), the doors
    that suit it, the source lines."""
    text = meihua.data_path("references", "qimen-calculation.md").read_text(encoding="utf-8")
    rows = re.findall(r"^\|\s*(\S+)\s*\|\s*([^|]+?)\s*\|\s*([休生伤杜景死惊开]门|—)\s*\|\s*((?:[休生伤杜景死惊开]门、?)+)"
                      r"\s*\|\s*([^|]+?)\s*\|\s*$", text, re.M)
    return {name: {"说法": words, "主门": None if main == "—" else main, "门": doors.split("、"), "出处": source}
            for name, words, main, doors, source in rows}


def _clock(text: str | None, timezone: str) -> datetime | None:
    match = _CLOCK.search(str(text or ""))
    if not match:
        return None
    year, month, day, hour, minute = (int(n) for n in match.groups())
    return datetime(year, month, day, hour, minute, tzinfo=ZoneInfo(timezone))


def _windows(start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    """The 时辰 overlapping [start, end): 子 23-1, 丑 1-3 … 亥 21-23."""
    first = start.replace(minute=0, second=0, microsecond=0)
    if first.hour % 2 == 0:
        first -= timedelta(hours=1)
    out = []
    while first < end and len(out) < MAX_PICK_HOURS:
        out.append((first, first + timedelta(hours=2)))
        first += timedelta(hours=2)
    return out


# 得地: the door's 五行 against its palace's (统宗 凡例五 「临土宫金位…得地」, 迫 lines 129-133; 宝鉴 「门制其宫是迫…
# 门生宫为和，宫生门为义…吉门被迫，则吉事不成」; 元灵经 「上克其下，谓之大凶迫」).
DOOR_ELEMENT = {"休门": "水", "生门": "土", "伤门": "木", "杜门": "木", "景门": "火", "死门": "土", "惊门": "金", "开门": "金"}
PALACE_ELEMENT = {"坎": "水", "坤": "土", "震": "木", "巽": "木", "中": "土", "乾": "金", "兑": "金", "艮": "土", "离": "火"}
_GENERATES = {"木": "火", "火": "土", "土": "金", "金": "水", "水": "木"}
GROUND_WORDS = {"比和": "比和，得地", "义": "宫生门，得地", "和": "门生宫", "迫": "门迫，不算", "制": "宫克门，受制，不算"}


def door_ground(door: str, palace: str) -> str:
    """比和 / 义 (宫生门): 得地; 和 (门生宫); 迫 (门克宫) and 制 (宫克门): a 吉门 there does not count."""
    mine, its = DOOR_ELEMENT[door], PALACE_ELEMENT[palace]
    if mine == its:
        return "比和"
    if _GENERATES[its] == mine:
        return "义"
    if _GENERATES[mine] == its:
        return "和"
    return "迫" if _GENERATES[_GENERATES[mine]] == its else "制"


def _doors_at(board: dict, doors: list[str]) -> list[dict]:
    found = []
    for door in doors:
        row = next(r for r in board["九宫"] if r.get("门") == door)
        wonders = [g for g in (row.get("天盘"), row.get("天盘寄")) if g in THREE_WONDERS]
        ground = door_ground(door, row["宫"])
        found.append({"门": door, "宫": row["宫"], "方位": row["方位"],
                      "奇": "、".join(f"{g}（{THREE_WONDERS[g]}）" for g in wonders) or None,
                      "地": GROUND_WORDS[ground]})
    return found


GRADES = ("主门合奇", "门奇会合", "有门无奇")       # best first: 执事歌's door meets 乙丙丁, another does, none does


def _counts(door: dict) -> bool:
    """A door with a 奇 that is neither 迫 nor 受制: 「吉门被迫，则吉事不成」."""
    return bool(door["奇"]) and not door["地"].endswith("不算")


def _grade(doors: list[dict], main: str | None) -> str:
    if any(_counts(d) and d["门"] == main for d in doors):
        return "主门合奇"
    return "门奇会合" if any(_counts(d) for d in doors) else "有门无奇"


def _grounded(doors: list[dict], main: str | None, grade: str) -> bool:
    """Is the door the grade stands on 得地 (比和 or 宫生门): the 主门 for 主门合奇, any that counts for 门奇会合?
    Within a grade those hours come first (凡例五)."""
    standing = [d for d in doors if _counts(d) and (grade != "主门合奇" or d["门"] == main)]
    return any(d["地"].endswith("得地") for d in standing)


def qimen_pick(question: str, matter: str, start: str | None = None, end: str | None = None,
               timezone: str = DEFAULT_TIMEZONE, now: datetime | None = None) -> dict:
    """选择: one 奇门 chart per 时辰 of the window, ranked by whether a door that suits the matter meets 乙丙丁."""
    off = harness.off_limits("奇门遁甲", question)
    if off:
        return {"status": "NOT_FOR_THIS", "system": "奇门遁甲",
                "note": f"奇门不用于{'、'.join(off)}这类事（GUARD-07），不挑时辰：如实说不排，别的事可以问。"}
    matters = pick_matters()
    named = [name for name, row in matters.items() if any(word in (question or "") for word in row["说法"].split("、"))]
    filed = None
    if len(named) == 1 and named[0] != matter:            # 「见客户」 is 求财 in the table, whatever the model chose
        filed, matter = matter, named[0]
    if matter not in matters:
        return {"status": "UNKNOWN_MATTER", "matters": {k: v["说法"] for k, v in matters.items()},
                "note": "把他要办的事归到最接近的一类再调；都不沾边就如实说奇门择时只管这几类事。"}
    zone = ZoneInfo(timezone)
    now = (now or datetime.now(zone)).astimezone(zone).replace(microsecond=0)
    begin = _clock(start, timezone) if start else now
    finish = _clock(end, timezone) if end else (begin or now) + timedelta(hours=2 * MAX_PICK_HOURS)
    if begin is None or finish is None or finish <= begin:
        return {"status": "INVALID_INPUT", "error": "start、end 要写成 YYYY-MM-DD HH:MM，end 要晚于 start"}
    doors, main = matters[matter]["门"], matters[matter]["主门"]
    rows = []
    for opens, closes in _windows(max(begin, now), finish):
        if closes <= now:
            continue
        moment = max(opens + timedelta(minutes=30), now)
        try:
            result = cast_qimen.run(moment.isoformat(), timezone)
        except ValueError as error:
            return {"status": "INVALID_INPUT", "error": str(error)}
        board = brief_qimen(result["chart"])
        at = _doors_at(board, doors)
        row = {"时辰": f"{result['chart']['hour'][1]}时", "钟点": f"{opens:%m月%d日 %H:%M}—{closes:%H:%M}",
               "局": board["局"], "值符": board["值符"], "值符宫": board["值符宫"],
               "值使": board["值使"], "值使宫": board["值使宫"], "宜用的门": at, "等级": _grade(at, main)}
        others = [(c["why"], _grade(_doors_at(brief_qimen(c["chart"]), doors), main)) for c in result["candidates"]]
        split = [f"{why}那张盘是{grade}" for why, grade in others if grade != row["等级"]]
        if split:
            row["两说"] = "；".join(split)
        rows.append(row)
    if not rows:
        return {"status": "ALL_PAST", "note": "他说的时间段都过去了，问他换哪段时间。"}
    for row in rows:
        row["得地"] = _grounded(row["宜用的门"], main, row["等级"])
    # stable sort: same grade and ground keep time order
    ranked = sorted(rows, key=lambda r: (GRADES.index(r["等级"]), not r["得地"]))
    met = [r for r in ranked if r["等级"] != "有门无奇"]

    def label(row: dict) -> str:
        meet = "、".join(f"{d['门']}合{d['奇'].split('（')[0]}奇（{d['宫']}，盘上{d['方位']}，{d['地']}）"
                         for d in row["宜用的门"] if d["奇"])
        grade = row["等级"] + ("·得地" if row["得地"] else "")
        return f"{row['时辰']} {row['钟点']}：{grade}" + (f"，{meet}" if meet else "") + ("（两说）" if "两说" in row else "")

    best = [r for r in ranked if (r["等级"], r["得地"]) == (ranked[0]["等级"], ranked[0]["得地"])]
    top = ranked[0]["等级"] + ("且得地" if ranked[0]["得地"] else "")
    gist = (f"{top}的时辰：{'、'.join(r['时辰'] for r in best)}" if met
            else "这段时间没有门奇会合的时辰，都是有门无奇（凡例六：犹为可用）")
    split_any = any("两说" in r for r in rows)
    claims = [{"text": f"{matter}宜{'、'.join(doors)}；{gist}", "evidence_ids": ["QM-08", "QM-01"], "strength": 1,
               "conditions": ["限他给的时段", "没看衰旺"], "reality_checks": ["事情实际的安排"]}]
    if split_any:
        claims.append({"text": "有的时辰落在换日或交节的口径分歧处，两说", "evidence_ids": ["QM-05", "GUARD-07"],
                       "strength": 1, "conditions": ["候选盘不同处两说"], "reality_checks": ["事情实际的安排"]})
    record = _record("qimen", "B" if split_any else "A", claims, _step(["QM-07"]),
                     ["没看八门衰旺与门迫，排序只是一半依据", "盘上方位不是身边的现实方向"], find_high_risk_hits(question or ""))
    out = {"status": "OK", "system": "奇门遁甲", "kind": "挑时辰", **_gate(record), "question": question,
           "事": f"{matter}（{matters[matter]['说法']}），宜{'、'.join(doors)}" + (f"，主门{main}" if main else ""),
           "依据": "《统宗》凡例六：奇门选择以会合为上吉，若有门无奇，犹为可用；门宜何事照「八门所主」「论八门执事歌」"
                   f"（第 {matters[matter]['出处']}）",
           "要点": gist, "排序": [label(r) for r in ranked], "时辰": rows,
           "象义": {name: text for name, text in meanings("qimen-symbols.md").items() if name in doors},
           "边界": PICK_BOUNDS, "篇幅": LENGTH}
    notes = ([f"他的话照表归为{matter}，不是{filed}"] if filed else []) + (["已经过去的时辰没排"] if begin < now else [])
    if notes:
        out["说明"] = "；".join(notes)
    return out


# ---------------------------------------------------------------- 八字

STEM_ELEMENT = dict(zip("甲乙丙丁戊己庚辛壬癸", "木木火火土土金金水水"))
BRANCH_ELEMENT = dict(zip("子丑寅卯辰巳午未申酉戌亥", "水土木木土火火土金金土水"))
BAZI_REASONS = {"legal 时间口径": "按钟表时间（不按真太阳时）定时柱", "true-solar 时间口径": "按真太阳时定时柱",
                "midnight 换日口径": "23 点按零点换日（子正）算当天", "zi-initial 换日口径": "23 点按子初换日算次日"}
BAZI_BOUNDS = ("只排四柱和结构（日主、月令、十神、通根、合冲）：不定旺衰、格局、喜忌、用神，不说缺什么补什么。"
               "不谈寿命、疾病、生育、婚姻成败、伴侣忠诚、投资收益，不据盘评判别人（references/bazi.md）。")


@lru_cache(maxsize=None)
def ten_god_meanings() -> dict[str, str]:
    """references/bazi.md 「十神的行动化翻译」 and 「合冲的行动化翻译」: name -> what it is read as."""
    text = meihua.data_path("references", "bazi.md").read_text(encoding="utf-8")
    out = {}
    for group, plain, work, people in re.findall(
            r"^\|\s*([^|\s]+、[^|\s]+)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*$", text, re.M):
        for god in group.split("、"):
            out[god] = f"{plain}；事业上看{work}；关系上看{people}"
    for names, plain in re.findall(r"^- (天干五合、地支六合|地支六冲|地支三合)：(.+)$", text, re.M):
        for name in names.split("、"):
            out[name] = plain
    return out


def brief_bazi(chart: dict, analysis: dict) -> dict:
    """The 四柱 as 小瓜 is given it (and harness.chart_facts reads back)."""
    pillars = chart["pillar_map"]
    master = analysis["day_master"]
    month = analysis["month_command"]
    roots = [f"{r['pillar']}{r['branch']}藏{'、'.join(r['same_element_hidden_stems'])}"
             for r in analysis["day_master_roots"]["locations"]]
    relations = analysis["structural_relations"]
    links = [f"{c['pair']}五合" for c in relations["stem_combinations"]] \
        + [f"{c['pair']}六合" for c in relations["branch_six_combinations"]] \
        + [f"{c['pair']}六冲" for c in relations["branch_six_clashes"]] \
        + [f"{c.get('pair') or ''.join(c.get('branches', []))}三合" for c in relations["branch_three_harmonies"]]
    return {**pillars, "日主": master["stem"] + master["element"],
            "月令": month["branch"] + month["main_element"],
            "天干十神": {f"{s['pillar'][0]}干{s['stem']}": s["role"] for s in analysis["visible_stems"]
                         if s["role"] != "日主"},
            "藏干十神": {f"{b['pillar'][0]}支{b['branch']}": "、".join(h["stem"] + h["ten_god"] for h in b["hidden_stems"])
                         for b in analysis["branches"]},
            "通根": roots or ["地支藏干里没见日主同五行"], "合冲": links or ["没有"]}


def _bazi_gist(board: dict) -> str:
    gods = "、".join(dict.fromkeys(board["天干十神"].values()))
    links = "、".join(board["合冲"]) if board["合冲"] != ["没有"] else "没有明显合冲"
    return (f"四柱 {board['年柱']} {board['月柱']} {board['日柱']} {board['时柱']}；日主{board['日主']}，"
            f"生在{board['月令'][0]}月（月令{board['月令'][1]}）；天干透{gods}；{links}")


def _now_in_luck(chart: dict, birth: datetime, today: datetime) -> tuple[str, str | None]:
    """(「第3步大运戊寅（22—32岁）；2026年流年丙午（正财）」, the 大运 pillar now, if there is one)."""
    flow = chart["flow_year"]
    line = f"{flow['year']}年流年{flow['pillar']}（{flow['visible_ten_god']}）"
    luck = chart.get("luck_cycles")
    if not luck:
        return line + "；大运要知道性别才排", None
    age = (today - birth).days / 365.2425
    for cycle in luck["cycles"]:
        if cycle["start_age"] <= age < cycle["end_age"]:
            return (f"第{cycle['sequence']}步大运{cycle['pillar']}（{cycle['start_age']:.0f}—{cycle['end_age']:.0f}岁）；"
                    + line), cycle["pillar"]
    return f"还没起运（约{luck['start_age_display']}起运）；" + line, None


_PILLARS = re.compile(r"[甲乙丙丁戊己庚辛壬癸][子丑寅卯辰巳午未申酉戌亥]")


def _bazi_from_pillars(question: str, pillars: list[str], today: datetime) -> dict:
    """四柱 he gave himself: their structure and this year's 流年, no 大运 (no birth time), confidence B."""
    try:
        analysis = analyze_bazi.analyze(pillars)
    except ValueError as error:
        return {"status": "INVALID_INPUT", "error": str(error)}
    board = brief_bazi({"pillar_map": dict(zip(("年柱", "月柱", "日柱", "时柱"), pillars))}, analysis)
    flow_at = today.year if today >= cast_bazi.lichun_time(today.year) else today.year - 1
    flow = cast_bazi.flow_year(flow_at, pillars[2][0], [p[1] for p in pillars])
    board["流年"] = flow["pillar"]
    board["流年十神"] = flow["visible_ten_god"]
    claims = [{"text": _bazi_gist(board), "evidence_ids": ["BZ-01", "BZ-02"], "strength": 1,
               "conditions": ["限四柱结构", "四柱是他给的"], "reality_checks": ["对照他自己说的做事方式"]}]
    record = _record("bazi", "B", claims, _step(["BZ-01"]), ["四柱是他自己给的，历法边界没核对（BZ-05）"],
                     find_high_risk_hits(question or ""))
    present = set(board["天干十神"].values()) | _link_names(board)
    out = {"status": "OK", "system": "八字", **_gate(record),
           "依据": "子平四柱结构，照 references/bazi.md，不自动定旺衰用神", "出生": "他直接给的四柱，没有出生时间",
           "要点": _bazi_gist(board),
           "置信": "B：四柱是他给的，立春、节气、时辰这些边界没法核对", "盘": board,
           "象义": {name: text for name, text in ten_god_meanings().items() if name in present}, "边界": BAZI_BOUNDS, "篇幅": LENGTH}
    if _asks_time(question):
        out["现在"] = f"{flow['year']}年流年{flow['pillar']}（{flow['visible_ten_god']}）；只给了四柱，大运要出生时间和性别才排"
    off = harness.off_limits("八字", question)
    if off:
        out["不谈"] = f"他问到的{'、'.join(off)}八字不看：如实说这部分不看，只说别的。"
    return out


def _link_names(board: dict) -> set[str]:
    """「巳亥六冲」 -> 「地支六冲」: the 合冲 notes in references/bazi.md, for what the chart has."""
    return {name for link in board["合冲"] for name in ("天干五合", "地支六合", "地支六冲", "地支三合")
            if link.endswith(name[-2:])}


def bazi_chart(question: str, birth: str = "", sex: str = "", longitude: float | None = None,
               timezone: str = DEFAULT_TIMEZONE, now: datetime | None = None, pillars: str | list | None = None) -> dict:
    """四柱 for a birth on the local clock (「1995-05-12 23:30」), their structure, candidates, meanings, gate.
    Without a birth time, the 四柱 he gave (pillars, or four 干支 in his words) are read as they are."""
    today = (now or datetime.now(ZoneInfo(timezone))).astimezone(ZoneInfo(timezone))
    match = _BIRTH.search(str(birth or ""))
    if not match:
        given = _PILLARS.findall(" ".join(pillars) if isinstance(pillars, list) else str(pillars or question or ""))
        if len(given) == 4:
            return _bazi_from_pillars(question, given, today)
        return {"status": "NEED_INPUT", "missing": "birth",
                "note": "八字要公历出生日期和几点几分（出生地的钟表时间），或者他直接给四柱。只知道日期就问时刻，时柱靠它；"
                        "只记得农历生日就问公历。"}
    sex = SEXES.get(str(sex or "").strip())                       # 大运 only: without it, no 大运
    year, month, day, hour, minute = (int(n) for n in match.groups())
    try:
        clock = datetime(year, month, day, hour, minute, tzinfo=ZoneInfo(timezone))
        lon = None if longitude in (None, "") else float(longitude)
        flow = today.year if today >= cast_bazi.lichun_time(today.year) else today.year - 1
        chart = cast_bazi.cast_birth_chart(clock.isoformat(), timezone, lon, "true-solar" if lon is not None else "legal",
                                           "zi-initial", {"男": "male", "女": "female"}.get(sex), None, flow, None, 0.0)
        analysis = analyze_bazi.analyze(chart["primary_chart"]["pillars"])
        candidates = [{"为什么": BAZI_REASONS.get(c["reason"], c["reason"]),
                       "盘": brief_bazi(c, analyze_bazi.analyze(c["pillars"]))} for c in chart["comparison_charts"]]
    except (ValueError, OverflowError) as error:
        return {"status": "INVALID_INPUT", "error": str(error)}
    board = brief_bazi(chart["primary_chart"], analysis)
    now_line, luck_now = _now_in_luck(chart, clock, today)
    board["流年"] = chart["flow_year"]["pillar"]
    board["流年十神"] = chart["flow_year"]["visible_ten_god"]
    if luck_now:
        board["大运"] = luck_now
        board["大运十神"] = analyze_bazi.ten_god(board["日主"][0], luck_now[0])     # its 干 against the 日主
    for candidate in candidates:
        candidate["盘"]["流年"] = board["流年"]
        candidate["盘"]["流年十神"] = analyze_bazi.ten_god(candidate["盘"]["日主"][0], board["流年"][0])
        candidate["不同"] = _differences_flat(board, candidate["盘"])
    confidence = "B" if candidates else "A"
    present = set(board["天干十神"].values()) | _link_names(board)      # the 十神 that show, not every hidden stem
    claims = [{"text": _bazi_gist(board), "evidence_ids": ["BZ-01", "BZ-02"], "strength": 1,
               "conditions": ["限四柱结构"], "reality_checks": ["对照他自己说的做事方式"]}]
    if board["合冲"] != ["没有"]:
        claims.append({"text": "合冲：" + "、".join(board["合冲"]), "evidence_ids": ["BZ-03"], "strength": 1,
                       "conditions": ["合不等于化，冲不等于凶"], "reality_checks": ["现实里的节奏张力"]})
    if chart.get("luck_cycles"):
        claims.append({"text": "大运流年作阶段背景", "evidence_ids": ["BZ-04"], "strength": 1,
                       "conditions": ["只作背景"], "reality_checks": ["他现在的计划"]})
    if candidates:
        claims.append({"text": "出生时间落在口径分歧处，另有候选盘，只说各盘共同的部分", "evidence_ids": ["BZ-05"],
                       "strength": 1, "conditions": ["候选盘不同处两说"], "reality_checks": ["请他核对出生时间"]})
    record = _record("bazi", confidence, claims, _step(["BZ-01"]),
                     ["八字是传统文化解释框架，不是被证实的预测方法"], find_high_risk_hits(question or ""))
    timing = chart["time_conversion"]
    clock_note = f"{clock:%Y-%m-%d %H:%M}（{timezone}）"
    if lon is not None:
        clock_note += f"，按出生地真太阳时 {timing['apparent_solar_time'][11:16]} 定时柱"
    out = {"status": "OK", "system": "八字", **_gate(record),
           "依据": "子平四柱：立春换年、十二节换月、23 点子初换日；结构照 references/bazi.md，不自动定旺衰用神",
           "出生": clock_note, "要点": _bazi_gist(board),
           "置信": confidence if not candidates else "B：有候选盘，两张一样的地方才说死，「不同」里的要两说",
           "盘": board, "象义": {name: text for name, text in ten_god_meanings().items() if name in present},
           "边界": BAZI_BOUNDS, "篇幅": LENGTH}
    if candidates:
        out["候选盘"] = candidates
    if _asks_time(question):
        out["现在"] = now_line
    note = _hour_line_note(clock, "时柱") if lon is None else None
    if note:
        out["时辰"] = note
    off = harness.off_limits("八字", question)
    if off:
        out["不谈"] = f"他问到的{'、'.join(off)}八字不看：如实说这部分不看，只说别的。"
    return out


def _differences_flat(main: dict, other: dict) -> list[str]:
    return [f"{key}：{_said(main[key])} / {_said(other.get(key))}" for key in main if main[key] != other.get(key)]


# ---------------------------------------------------------------- 小六壬

PALACES = ("大安", "留连", "速喜", "赤口", "小吉", "空亡")
XIAOLIU_BOUNDS = ("只看短期节奏、沟通和行动条件：不给精确日期、收益金额、对方隐私，不说必然成败；找东西不凭课指认别人"
                  "（XL-01、XL-02）。")


@lru_cache(maxsize=None)
def palace_meanings() -> dict[str, dict[str, str]]:
    """references/xiaoliu-ren.md: each 课宫's 条件化解释 and its reading by kind of question."""
    text = meihua.data_path("references", "xiaoliu-ren.md").read_text(encoding="utf-8")
    out = {name: {"象义": plain} for name, plain in re.findall(rf"^- ({'|'.join(PALACES)})：(.+)$", text, re.M)}
    header = re.search(r"^\|\s*课宫\s*\|(.+)\|\s*$", text, re.M).group(1)
    kinds = [k.strip() for k in header.split("|")]
    for row in re.findall(rf"^\|\s*({'|'.join(PALACES)})\s*\|(.+)\|\s*$", text, re.M):
        out[row[0]].update(zip(kinds, (cell.strip() for cell in row[1].split("|"))))
    return out


def xiaoliu_chart(question: str, timezone: str = DEFAULT_TIMEZONE, now: datetime | None = None) -> dict:
    """小六壬 for this moment (lunar month, day, 时支), its candidate at 23:00, meanings and gate."""
    moment = (now or datetime.now(ZoneInfo(timezone))).replace(microsecond=0)
    moment = moment.replace(tzinfo=ZoneInfo(timezone)) if moment.tzinfo is None else moment.astimezone(ZoneInfo(timezone))
    try:
        conversion = lunar.convert(moment.isoformat(), timezone)
    except ValueError as error:
        return {"status": "INVALID_INPUT", "error": str(error)}
    day = conversion["lunar"]
    hour = conversion["local_clock"]["hour_branch_number"]
    result = cast_xiaoliu_ren.cast(day["month"], day["day"], hour, day["is_leap_month"], conversion)
    palace = result["trace"]["final_palace"]["name"]
    candidates = []
    if moment.hour == 23:                             # 子初换日: the 子 hour may already count as the next day
        nxt = lunar.lunar_date(moment.date() + timedelta(days=1))
        other = cast_xiaoliu_ren.cast(nxt["month"], nxt["day"], 1, nxt["is_leap_month"])["trace"]["final_palace"]["name"]
        candidates.append({"为什么": "23 点按子初换日算次日", "盘": {"课宫": other},
                           "不同": [] if other == palace else [f"课宫：{palace} / {other}"]})
    reasons = ([c["为什么"] for c in candidates] + (["闰月按本月数"] if day["is_leap_month"] else []))
    confidence = "B" if reasons else "A"
    claims = [{"text": f"落{palace}", "evidence_ids": ["XL-01", "XL-02"], "strength": 1,
               "conditions": ["限这一件事的短期节奏"], "reality_checks": ["事情实际的进展"]}]
    if reasons:
        claims.append({"text": "口径分歧：" + "、".join(reasons), "evidence_ids": ["XL-03"], "strength": 1,
                       "conditions": ["两说"], "reality_checks": ["事情实际的进展"]})
    record = _record("xiaoliu-ren", confidence, claims, _step(["XL-01"]),
                     ["小六壬是传统文化解释框架，不是被证实的预测方法"], find_high_risk_hits(question or ""))
    month_name = ("闰" if day["is_leap_month"] else "") + f"{day['month']}月{day['day']}日"
    out = {"status": "OK", "system": "小六壬", **_gate(record), "question": question,
           "依据": "《萬寶玉匣記》卷下「李淳風六壬時課」：大安起正月，月上起日，日上起时，起点计一",
           "起课": f"{moment:%Y-%m-%d %H:%M}，农历{month_name} {result['input']['hour_branch']}时",
           "要点": f"落{palace}",
           "置信": confidence if not reasons else "B：" + "、".join(reasons) + "，不同处两说",
           "盘": {"课宫": palace},
           "象义": {name: meaning for name, meaning in palace_meanings().items()
                    if name == palace or any(c["盘"]["课宫"] == name for c in candidates)},
           "边界": XIAOLIU_BOUNDS, "篇幅": LENGTH}
    if candidates:
        out["候选盘"] = candidates
    return out


# ---------------------------------------------------------------- 风水: space observation (SPACE-01)

DIRECTIONS = ("北", "东北", "东", "东南", "南", "西南", "西", "西北")
NATURE = {"乾": "天", "坤": "地", "震": "雷", "巽": "风", "坎": "水", "离": "火", "艮": "山", "兑": "泽"}   # 《说卦传》
SPACE_BOUNDS = ("两栏分开说：先说现实环境（工具「现实环境」里的几项，按「先看」「能做」说），传统说法放最后单列一句，只作参考。"
                "不排飞星宅盘；不把方位说成病灾、破财、犯煞；不劝拆承重墙、改燃气电路、挡消防；不推荐开光化煞转运的摆件"
                "（SPACE-01）。")


@lru_cache(maxsize=None)
def space_items() -> dict[str, dict[str, str]]:
    """references/space-checks.md: each 现实环境 item -> what he may say, what to look at, what to do, what not."""
    text = meihua.data_path("references", "space-checks.md").read_text(encoding="utf-8")
    rows = re.findall(r"^\|\s*([^|\s]+)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*$", text, re.M)
    return {name: {"说法": said, "先看": look, "能做": do, "别做": dont}
            for name, said, look, do, dont in rows if name not in ("项", "---")}


def space_check(question: str, space: str = "", facing: str = "", problems: list | None = None,
                limits: str = "") -> dict:
    """风水 as SPACE-01 has it: the practical items his words touch, then (with a 朝向) the direction's 卦 and 五行."""
    problems = [str(p) for p in (problems or []) if str(p).strip()]
    said = " ".join([question or "", space or "", limits or "", *problems])
    items = space_items()
    touched = [name for name, row in items.items() if any(word in said for word in row["说法"].split("、"))]
    picked = touched or list(items)
    facing = (facing or "").strip().removesuffix("方").removesuffix("边")
    missing = [name for name, given in (("用途（哪个房间）", space), ("朝向（窗或门朝哪）", facing in DIRECTIONS),
                                        ("主要问题", touched)) if not given]
    traditional = None
    if facing in DIRECTIONS:
        trigram = next(t for t in cast_hexagram.TRIGRAMS.values() if t["direction"] == facing)
        traditional = {"方位": facing, "卦": trigram["name"], "五行": trigram["element"],
                       "说卦": f"{trigram['name']}为{NATURE[trigram['name']]}",
                       "说明": "只作传统象征参考，不是吉凶判断；飞星宅盘没排（要精确坐向和建造年份，且未准入）"}
    gist = "先看：" + "、".join(picked[:3])
    claims = [{"text": "现实环境：" + "、".join(picked), "evidence_ids": ["SPACE-01"], "strength": 1,
               "conditions": ["以他实际看到的房间为准"], "reality_checks": ["照「先看」逐项看一遍"]}]
    if traditional:
        claims.append({"text": f"传统象征：{facing}方属{traditional['卦']}{traditional['五行']}", "evidence_ids": ["SPACE-01"],
                       "strength": 1, "conditions": ["只作参考"], "reality_checks": ["不作吉凶判断"]})
    actions = [{"text": "先做一件低成本、能回头的改动：" + items[picked[0]]["能做"], "evidence_ids": ["SPACE-01"],
                "reality_anchor": "他自己的房间：" + items[picked[0]]["先看"], "reversible": True, "risk_level": "low"}]
    record = {"schema_version": SCHEMA, "method": "space-observation", "calculation_confidence": "A" if not missing else "B",
              "claims": claims, "actions": actions,
              "uncertainties": ["没看到实物，只按他的描述", "飞星宅盘未准入，不排"],
              "prohibited_topics": find_high_risk_hits(question or "")}
    out = {"status": "OK", "system": "风水", **_gate(record),
           "依据": "SPACE-01（protocols/action-space.md）：先现实环境，后传统象征；清单见 references/space-checks.md",
           "要点": gist, "盘": {"空间": space or "没说", "朝向": facing or "没说"},
           "现实环境": [{"项": name, **{k: items[name][k] for k in ("先看", "能做", "别做")}} for name in picked],
           "边界": SPACE_BOUNDS, "篇幅": LENGTH}
    if traditional:
        out["传统象征"] = traditional
    if missing:
        out["还缺"] = "、".join(missing) + "：缺的先问一句，能先说的照说。"
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
        {"name": "qimen_pick",
         "description": "他点名用奇门挑时辰（「用奇门看看明天下午几点去见客户好」「哪个时辰搬家好」）时调用：在他说的时间段里"
                        "每个时辰各起一局，按《统宗》门奇会合排先后（主门合奇最先）。matter 选最接近的一类，返回 UNKNOWN_MATTER "
                        "就照列表换；start、end 按【今天】换算成 YYYY-MM-DD HH:MM，没说就从现在起看 12 个时辰。只问此刻这件事怎么样用 "
                        "qimen_chart。没看衰旺，回答里要说明。",
         "input_schema": {"type": "object", "properties": {
             "question": {"type": "string", "description": "用户原话"},
             "matter": {"type": "string", "enum": list(pick_matters()),
                        "description": "照这张表归类：" + "；".join(f"{name}＝{row['说法']}" for name, row in pick_matters().items())},
             "start": {"type": "string", "description": "时间段开始 YYYY-MM-DD HH:MM，不传就是现在"},
             "end": {"type": "string", "description": "时间段结束 YYYY-MM-DD HH:MM，不传就看 12 个时辰"}},
             "required": ["question", "matter"]}},
        {"name": "space_check",
         "description": "他问家里、房间、办公室的风水，或采光、通风、潮湿、户型这些时调用：按 SPACE-01 列出现实环境要看的几项"
                        "（先看什么、能做什么、别做什么），给了朝向再附该方位的卦和五行作传统参考。不排飞星宅盘。",
         "input_schema": {"type": "object", "properties": {
             "question": {"type": "string", "description": "用户原话"},
             "space": {"type": "string", "description": "哪个房间：卧室、客厅、书房、厨房、办公室、整套房…；没说就不传"},
             "facing": {"type": "string", "enum": list(DIRECTIONS) + ["不知道"], "description": "窗或门朝哪，没说就传 不知道"},
             "problems": {"type": "array", "items": {"type": "string"}, "description": "他说的问题：潮、暗、吵、闷…"},
             "limits": {"type": "string", "description": "限制：租房、不能动墙…"}},
             "required": ["question"]}},
        {"name": "bazi_chart",
         "description": "他点名要八字（排八字、看命局、做事方式、长期倾向、大运流年）时调用，一次做完：排四柱（立春换年、"
                        "十二节换月）、看日主月令十神合冲、查十神象义、核对依据。要公历出生日期和几点几分，缺就先问，不猜；"
                        "问大运才要性别；知道出生城市就传 longitude，按真太阳时定时柱。不定旺衰用神，不说缺什么补什么。",
         "input_schema": {"type": "object", "properties": {
             "question": {"type": "string", "description": "用户原话"},
             "birth": {"type": "string", "description": "公历出生时间 YYYY-MM-DD HH:MM，出生地钟表时间"},
             "sex": {"type": "string", "enum": ["男", "女"], "description": "问大运才需要；不知道就不传"},
             "longitude": {"type": "number", "description": "出生城市东经度数，如广州 113.3；不知道就不传"},
             "pillars": {"type": "string", "description": "他直接给的四柱，如 甲子 乙丑 丙寅 丁卯；有出生时间就不用"}},
             "required": ["question"]}},
        {"name": "xiaoliu_chart",
         "description": "他点名要小六壬看一件眼前的事（快速起一课、短期节奏）时调用，一次做完：按此刻农历月日时起课、"
                        "查六宫象义、核对依据。一件事只起一课：追问同一件事传 follow_up=true，沿用那一课。",
         "input_schema": {"type": "object", "properties": {
             "question": {"type": "string", "description": "用户原话"},
             "follow_up": {"type": "boolean", "description": "追问上一课的同一件事时传 true"}},
             "required": ["question"]}},
    ]
