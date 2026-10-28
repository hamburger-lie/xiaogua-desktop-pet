#!/usr/bin/env python3
"""奇门遁甲 时家转盘, worked out by code from 《奇门遁甲统宗》卷一 and 《烟波钓叟歌》 (evidence/qimen.md).

School: 时家奇门, 转盘. 定局 by 拆补: the 节气 at the actual moment of its 交节 (solar_terms.json, to
the minute), the 元 by the day's 符头 (统宗 248: 子午卯酉 上元, 寅申巳亥 中元, 辰戌丑未 下元). 中五 寄坤二
(统宗 227; 「阳遁寄坤、阴遁寄艮」 noted as the other reading). 八神 值符 螣蛇 太阴 六合 白虎 玄武 九地 九天,
as current charts use (统宗 233 has 勾陈 朱雀, and notes 白虎 玄武 under them). 置闰 (统宗 72-75) is
not done here. Line numbers refer to the Wikisource texts kept with the admission research.

Two moments get a second chart and confidence B instead of a guess: 23:00-24:00 (the day turns at
子初 here; at midnight in the other reading), and within 3 minutes of a 交节 (the table's margin).
"""

from __future__ import annotations

import argparse
import bisect
import json
import sys
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from cast_bazi import parse_local_datetime
from result_contract import calculation_record

STEMS = "甲乙丙丁戊己庚辛壬癸"
BRANCHES = "子丑寅卯辰巳午未申酉戌亥"
PALACE_NAMES = {1: "坎", 2: "坤", 3: "震", 4: "巽", 5: "中", 6: "乾", 7: "兑", 8: "艮", 9: "离"}
DIRECTIONS = {1: "北", 2: "西南", 3: "东", 4: "东南", 5: "中", 6: "西北", 7: "西", 8: "东北", 9: "南"}
STARS = {1: "天蓬", 2: "天芮", 3: "天冲", 4: "天辅", 5: "天禽", 6: "天心", 7: "天柱", 8: "天任", 9: "天英"}   # 统宗 227
DOORS = {1: "休门", 8: "生门", 3: "伤门", 4: "杜门", 9: "景门", 2: "死门", 7: "惊门", 6: "开门"}             # 统宗 229
RING = (1, 8, 3, 4, 9, 2, 7, 6)              # the eight outer palaces, clockwise: 坎 艮 震 巽 离 坤 兑 乾
GODS = ("值符", "螣蛇", "太阴", "六合", "白虎", "玄武", "九地", "九天")
SEQUENCE = "戊己庚辛壬癸丁丙乙"              # 统宗 235: 顺布六仪、逆布三奇 (阳遁 forwards, 阴遁 backwards)
XUN_YI = "戊己庚辛壬癸"                     # 统宗 231: 甲子戊 甲戌己 甲申庚 甲午辛 甲辰壬 甲寅癸
CENTRE_HOST = 2                             # 中五寄坤二
# 统宗 146: 局 of the 上 中 下 元 for each 节气.
JU = {"冬至": (1, 7, 4), "惊蛰": (1, 7, 4), "小寒": (2, 8, 5), "大寒": (3, 9, 6), "春分": (3, 9, 6), "立春": (8, 5, 2),
      "雨水": (9, 6, 3), "清明": (4, 1, 7), "立夏": (4, 1, 7), "谷雨": (5, 2, 8), "小满": (5, 2, 8), "芒种": (6, 3, 9),
      "夏至": (9, 3, 6), "白露": (9, 3, 6), "小暑": (8, 2, 5), "大暑": (7, 1, 4), "秋分": (7, 1, 4), "立秋": (2, 5, 8),
      "处暑": (1, 4, 7), "霜降": (5, 8, 2), "小雪": (5, 8, 2), "大雪": (4, 7, 1), "立冬": (6, 9, 3), "寒露": (6, 9, 3)}
YANG_TERMS = ("冬至", "小寒", "大寒", "立春", "雨水", "惊蛰", "春分", "清明", "谷雨", "立夏", "小满", "芒种")
MONTH_JIE = ("立春", "惊蛰", "清明", "立夏", "芒种", "小暑", "立秋", "白露", "寒露", "立冬", "大雪", "小寒")
JIAZI_DAY = date(1949, 10, 1)               # a 甲子 day
TERM_MARGIN = timedelta(minutes=3)
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)   # datetime.fromtimestamp fails before 1970 on Windows
SCHOOL = ("时家奇门转盘；拆补法定局（节气按实际交节时刻，元按日干支符头）；中五寄坤二；八神用白虎玄武；"
          "23 点换日（子初换日），零点换日另给候选盘")


@lru_cache(maxsize=1)
def _terms() -> tuple[list[int], list[str]]:
    data = json.loads(Path(__file__).with_name("solar_terms.json").read_text(encoding="utf-8"))
    moments, names = [], []
    for year in range(data["first_year"], data["last_year"] + 1):
        for name, seconds in zip(data["terms"], data["years"][str(year)]):
            moments.append(seconds)
            names.append(name)
    return moments, names


def term_at(moment: datetime) -> tuple[str, datetime, datetime]:
    """The 节气 in force at `moment`, when it began, and when the next one begins."""
    moments, names = _terms()
    at = moment.timestamp()
    index = bisect.bisect_right(moments, at) - 1
    if index < 0 or index + 1 >= len(moments):
        raise ValueError("只支持 1900—2100 年")
    begin = EPOCH + timedelta(seconds=moments[index])
    return names[index], begin, EPOCH + timedelta(seconds=moments[index + 1])


def day_index(day: date) -> int:
    """The day's place in the sixty (甲子 0)."""
    return (day - JIAZI_DAY).days % 60


def hour_number(hour: int) -> int:
    return 0 if hour == 23 else (hour + 1) // 2


def pillar(index: int) -> str:
    return STEMS[index % 10] + BRANCHES[index % 12]


def build(moment: datetime, day: date, term: str) -> dict:
    """The chart for a local `moment`, counting `day` as its day (the 换日 reading) and `term` as its 节气."""
    d = day_index(day)
    h = hour_number(moment.hour)
    hour_stem = (d % 10 % 5 * 2 + h) % 10                   # 五鼠遁: 甲己日起甲子时 …
    hour_index = next(i for i in range(60) if i % 10 == hour_stem and i % 12 == h)
    yang = term in YANG_TERMS
    yuan = d // 5 % 3                                       # 符头: 甲子 / 己卯 … 上元; 统宗 248
    ju = JU[term][yuan]

    earth = {}                                              # 地盘: 统宗 235, 237
    for k, stem in enumerate(SEQUENCE):
        earth[(ju - 1 + (k if yang else -k)) % 9 + 1] = stem
    where = {stem: palace for palace, stem in earth.items()}
    xun = hour_index - hour_index % 10                      # 旬首: 统宗 250
    yi = XUN_YI[xun // 10]
    head = where[yi]                                        # 旬首所临之宫: 其星为值符，其门为值使
    star_home = CENTRE_HOST if head == 5 else head
    time_stem = STEMS[hour_stem]
    target = where[yi if time_stem == "甲" else time_stem]  # 值符常遣加时干 (甲遁于旬首之仪)
    target = CENTRE_HOST if target == 5 else target

    def turn(home: int, to: int) -> dict[int, int]:
        """Each outer palace -> the palace whose contents land there when `home` turns to `to`."""
        shift = RING.index(to) - RING.index(home)
        return {RING[i]: RING[(i - shift) % 8] for i in range(8)}

    sky_from = turn(star_home, target)
    steps = hour_index % 10                                 # 值使顺逆遁宫去: one palace a 时辰 from the 旬首
    door_at = (head - 1 + (steps if yang else -steps)) % 9 + 1
    door_at = CENTRE_HOST if door_at == 5 else door_at
    door_from = turn(star_home, door_at)
    gods = {RING[(RING.index(target) + (i if yang else -i)) % 8]: GODS[i] for i in range(8)}

    palaces = []
    for number in range(1, 10):
        cell = {"number": number, "name": PALACE_NAMES[number], "direction": DIRECTIONS[number],
                "earth": earth[number]}
        if number == CENTRE_HOST:
            cell["earth_hosted"] = earth[5]
        if number != 5:
            source = sky_from[number]
            cell.update({"sky": earth[source], "star": STARS[source], "door": DOORS[door_from[number]],
                         "god": gods[number]})
            if source == CENTRE_HOST:
                cell.update({"sky_hosted": earth[5], "star_hosted": STARS[5]})
        palaces.append(cell)
    return {"dun": "阳遁" if yang else "阴遁", "ju": ju, "term": term, "yuan": "上中下"[yuan] + "元",
            "fu_tou": pillar(d - d % 5), "day": pillar(d), "hour": pillar(hour_index), "xun_shou": pillar(xun) + yi,
            "zhi_fu": {"star": STARS[head], "palace": PALACE_NAMES[target]},
            "zhi_shi": {"door": DOORS[star_home], "palace": PALACE_NAMES[door_at]},
            "palaces": palaces}


def year_month(moment: datetime) -> tuple[str, str]:
    """年柱 by 立春, 月柱 by the month's 节 (shown with the chart; the chart does not use them)."""
    moments, names = _terms()
    at = moment.timestamp()
    index = bisect.bisect_right(moments, at) - 1
    while names[index] not in MONTH_JIE:
        index -= 1
    month_branch = (MONTH_JIE.index(names[index]) + 2) % 12
    begun = (EPOCH + timedelta(seconds=moments[index])).astimezone(moment.tzinfo)
    year = begun.year if names[index] != "小寒" else begun.year - 1
    year_index = (year - 4) % 60
    first = (year_index % 10 % 5 * 2 + 2) % 10            # 五虎遁: 甲己之年丙作首 …
    month_stem = (first + (month_branch - 2) % 12) % 10
    month_index = next(i for i in range(60) if i % 10 == month_stem and i % 12 == month_branch)
    return pillar(year_index), pillar(month_index)


def charts(moment: datetime) -> tuple[dict, list[dict]]:
    """The chart for a local, zone-aware moment and the candidate charts at the two boundaries."""
    term, begun, upcoming = term_at(moment)
    day = moment.date() + timedelta(days=1 if moment.hour == 23 else 0)      # 子初换日
    main = build(moment, day, term)
    candidates = []
    if moment.hour == 23:
        candidates.append({"why": "23:00-24:00 按零点换日（日柱仍是当天）", "chart": build(moment, moment.date(), term)})
    if moment - begun < TERM_MARGIN:
        before, _, _ = term_at(begun - timedelta(minutes=1))
        candidates.append({"why": f"距{term}交节不足 3 分钟，按交节前的{before}", "chart": build(moment, day, before)})
    elif upcoming - moment < TERM_MARGIN:
        after, _, _ = term_at(upcoming + timedelta(minutes=1))
        candidates.append({"why": f"距{after}交节不足 3 分钟，按已交{after}", "chart": build(moment, day, after)})
    return main, candidates


def run(datetime_value: str, timezone_name: str) -> dict:
    local, _zone = parse_local_datetime(datetime_value, timezone_name)
    main, candidates = charts(local)
    year, month = year_month(local)
    term, begun, upcoming = term_at(local)
    result = {
        "method": "奇门遁甲时家转盘（拆补法）",
        "input": {"datetime": datetime_value, "timezone": timezone_name},
        "pillars": {"year": year, "month": month, "day": main["day"], "hour": main["hour"]},
        "chart": main,
        "candidates": candidates,
        "boundary_note": "只排盘面结构；不判格局吉凶，不做置闰法、飞盘或日家月家奇门。",
    }
    result["calculation_record"] = calculation_record(
        basis=result["method"],
        inputs=result["input"],
        adopted_school=SCHOOL,
        key_structure={k: main[k] for k in ("dun", "ju", "term", "yuan", "fu_tou", "xun_shou", "zhi_fu", "zhi_shi")},
        time_information={"local_clock": local.isoformat(timespec="minutes"),
                          "term_began": begun.astimezone(local.tzinfo).isoformat(timespec="minutes"),
                          "next_term": upcoming.astimezone(local.tzinfo).isoformat(timespec="minutes"),
                          "day_counted": main["day"], "candidate_reasons": [c["why"] for c in candidates]},
        interpretation_signals=[{
            "evidence": (f"{main['term']}{main['yuan']}，{main['dun']}{main['ju']}局；值符{main['zhi_fu']['star']}"
                         f"落{main['zhi_fu']['palace']}，值使{main['zhi_shi']['door']}落{main['zhi_shi']['palace']}"),
            "supports": "作为时机、方位与人事配合的传统象征参考",
            "does_not_support": "不能推出成败定局、具体结果、他人隐私，也不能替代现实安全判断",
        }],
        confidence_level="B" if candidates else "A",
        confidence_reasons=(["起局时间落在口径分歧处，另附候选盘：" + "；".join(c["why"] for c in candidates)]
                            if candidates else ["定局与布盘规则出自《统宗》《钓叟歌》，节气按交节时刻，可复算"]),
    )
    return result


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="奇门遁甲时家转盘（拆补法）")
    parser.add_argument("--datetime", required=True, help="起局的当地钟表时间，ISO 格式，例如 2026-10-27T11:30:00")
    parser.add_argument("--timezone", required=True, help="IANA 时区，例如 Asia/Shanghai")
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.datetime, args.timezone), ensure_ascii=False, indent=2))
    except ValueError as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
