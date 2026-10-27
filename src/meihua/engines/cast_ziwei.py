#!/usr/bin/env python3
"""紫微斗数 命盘, worked out by code from 《紫微斗数全书》卷二 (evidence/ziwei.md).

School: every placement follows 卷二 (line numbers below refer to the Wikisource text kept with the
admission research). Where 卷二 and practice part:
  - 大限 start at 命宫, as every current chart does; 卷二 173-175 reads 「从命前一宫起」 (noted).
  - 魁钺 for 丙丁 are 亥 酉; the Wikisource 卷二 50 reads 「猪狗」, a copying slip (same line writes
    免 for 兔; other editions and 《御定星历考原》 read 「猪鸡」).
The year runs from 正月初一. A 闰月 counts as the next month (卷二 10). Two births get a second chart
and confidence B instead of a guess: 23:00-24:00 (晚子时: this day or the next; 卷二 is silent) and
the first half of a 闰月 (初一-十五: many current charts count it as this month).
Charted: 命宫 身宫, 十二宫 干支, 五行局, 十四主星, 十四辅曜, 四化, 命主 身主, 大限.
Not charted: 杂曜, 神煞, 星曜庙旺 (the schools' tables differ; not admitted yet).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta

import lunar
from solar_clock import apparent_solar_clock, parse_local_datetime
from result_contract import calculation_record

STEMS = "甲乙丙丁戊己庚辛壬癸"
BRANCHES = "子丑寅卯辰巳午未申酉戌亥"
YIN = 2                                                    # 寅: months and many stars count from it
# 卷二 14: 「一命宫、二兄弟、三妻妾…十二父母」, counted backwards (逆转). Current names.
PALACES = ("命宫", "兄弟", "夫妻", "子女", "财帛", "疾厄", "迁移", "仆役", "官禄", "田宅", "福德", "父母")
# 卷二 18: 起五行寅例 — the stem of 寅 for the year's stem.
TIGER = {"甲": "丙", "己": "丙", "乙": "戊", "庚": "戊", "丙": "庚", "辛": "庚", "丁": "壬", "壬": "壬",
         "戊": "甲", "癸": "甲"}
# 卷二 22-29: 六十花甲子纳音 (the Wikisource text has 甲戊 for 甲戌 and 已亥 for 己亥: copying slips).
NAYIN = ("海中金 炉中火 大林木 路旁土 剑锋金 山头火 涧下水 城头土 白蜡金 杨柳木 泉中水 屋上土 霹雳火 松柏木 长流水 "
         "沙中金 山下火 平地木 壁上土 金箔金 覆灯火 天河水 大驿土 钗钏金 桑柘木 大溪水 沙中土 天上火 石榴木 大海水").split()
BUREAU = {"水": 2, "木": 3, "金": 4, "土": 5, "火": 6}      # 五行局
# 卷二 31-34: 安南北斗诸星诀 — offsets from 紫微 (backwards) and from 天府 (forwards).
ZIWEI_GROUP = (("紫微", 0), ("天机", -1), ("太阳", -3), ("武曲", -4), ("天同", -5), ("廉贞", -8))
TIANFU_GROUP = (("天府", 0), ("太阴", 1), ("贪狼", 2), ("巨门", 3), ("天相", 4), ("天梁", 5), ("七杀", 6),
                ("破军", 10))
MAJOR = tuple(name for name, _ in ZIWEI_GROUP + TIANFU_GROUP)
MINOR = ("左辅", "右弼", "文昌", "文曲", "天魁", "天钺", "禄存", "擎羊", "陀罗", "火星", "铃星", "地空", "地劫", "天马")
# 卷二 50: 安天魁天钺诀 (魁, 钺) by the year's stem.
KUI_YUE = {"甲": "丑未", "戊": "丑未", "庚": "丑未", "乙": "子申", "己": "子申", "丙": "亥酉", "丁": "亥酉",
           "辛": "午寅", "壬": "卯巳", "癸": "卯巳"}
# 卷二 62: 安禄存星诀.
LUCUN = {"甲": "寅", "乙": "卯", "丙": "巳", "戊": "巳", "丁": "午", "己": "午", "庚": "申", "辛": "酉", "壬": "亥",
         "癸": "子"}
# 卷二 56: 安天马星诀, by the year's branch.
HORSE = {**dict.fromkeys("寅午戌", "申"), **dict.fromkeys("申子辰", "寅"), **dict.fromkeys("巳酉丑", "亥"),
         **dict.fromkeys("亥卯未", "巳")}
# 卷二 72: 安火铃二星诀 — where 火星 and 铃星 stand at 子时, by the year's branch; both go on by the hour.
FIRE_BELL = {**dict.fromkeys("寅午戌", "丑卯"), **dict.fromkeys("申子辰", "寅戌"), **dict.fromkeys("巳酉丑", "卯戌"),
             **dict.fromkeys("亥卯未", "酉戌")}
# 卷二 76-84: 安禄权科忌四星变化诀 (戊 右弼科, 庚 太阴科, 壬 天府科 — where current charts differ).
MUTAGEN = {"甲": "廉贞 破军 武曲 太阳", "乙": "天机 天梁 紫微 太阴", "丙": "天同 天机 文昌 廉贞", "丁": "太阴 天同 天机 巨门",
           "戊": "贪狼 太阴 右弼 天机", "己": "武曲 贪狼 天梁 文曲", "庚": "太阳 武曲 太阴 天同", "辛": "巨门 太阳 文曲 文昌",
           "壬": "天梁 紫微 天府 武曲", "癸": "破军 巨门 太阴 贪狼"}
# 卷二 185-193: 安命主 (by 命宫's branch), 安身主 (by the year's branch).
SOUL_MASTER = {"子": "贪狼", "丑": "巨门", "亥": "巨门", "寅": "禄存", "戌": "禄存", "卯": "文曲", "酉": "文曲",
               "辰": "廉贞", "申": "廉贞", "巳": "武曲", "未": "武曲", "午": "破军"}
BODY_MASTER = {**dict.fromkeys("子午", "火星"), **dict.fromkeys("丑未", "天相"), **dict.fromkeys("寅申", "天梁"),
               **dict.fromkeys("卯酉", "天同"), **dict.fromkeys("辰戌", "文昌"), **dict.fromkeys("巳亥", "天机")}
SCHOOL = ("《紫微斗数全书》卷二安星诀；农历正月初一换年；闰月按下月（卷二）；大限从命宫起（通行，卷二作命前一宫）；"
          "丙丁魁钺亥酉；只排十四主星、十四辅曜、四化、命主身主、大限")


def hour_index(hour: int) -> int:
    """子 0 … 亥 11; 23:00 is already 子时."""
    return 0 if hour == 23 else (hour + 1) // 2


def nayin(stem: str, branch: str) -> str:
    cycle = next(i for i in range(60) if STEMS[i % 10] == stem and BRANCHES[i % 12] == branch)
    return NAYIN[cycle // 2]


def ziwei_branch(bureau: int, day: int) -> int:
    """卷二 297-450 (五局起紫微表): add the least k making the day a multiple of the 局; the quotient
    counts from 寅; then step back k when k is odd, forward k when it is even."""
    k = (-day) % bureau
    position = YIN + (day + k) // bureau - 1
    return (position - k if k % 2 else position + k) % 12


def build(lunar_year: int, month: int, day: int, hour: int, sex: str) -> dict:
    """One chart from a lunar year number, the month counted (1-12, a 闰月 already settled), the day,
    the hour (子 0 … 亥 11) and 男 / 女."""
    stem, branch = STEMS[(lunar_year - 4) % 10], BRANCHES[(lunar_year - 4) % 12]
    month_palace = (YIN + month - 1) % 12
    soul = (month_palace - hour) % 12                       # 卷二 5-9: 逆至生时安命
    body = (month_palace + hour) % 12                       # 顺至生时安身
    first = STEMS.index(TIGER[stem])
    stems = {b: STEMS[(first + (b - YIN) % 12) % 10] for b in range(12)}
    element = nayin(stems[soul], BRANCHES[soul])
    bureau = BUREAU[element[-1]]

    places: dict[str, int] = {}
    zw = ziwei_branch(bureau, day)
    tf = (4 - zw) % 12                                      # 天府 mirrors 紫微 across 寅申
    places.update({name: (zw + step) % 12 for name, step in ZIWEI_GROUP})
    places.update({name: (tf + step) % 12 for name, step in TIANFU_GROUP})
    places["文昌"], places["文曲"] = (10 - hour) % 12, (4 + hour) % 12           # 卷二 36
    places["左辅"], places["右弼"] = (4 + month - 1) % 12, (10 - month + 1) % 12  # 卷二 44
    kui, yue = KUI_YUE[stem]
    places["天魁"], places["天钺"] = BRANCHES.index(kui), BRANCHES.index(yue)
    lucun = BRANCHES.index(LUCUN[stem])
    places["禄存"], places["擎羊"], places["陀罗"] = lucun, (lucun + 1) % 12, (lucun - 1) % 12   # 卷二 66
    fire, bell = FIRE_BELL[branch]
    places["火星"], places["铃星"] = (BRANCHES.index(fire) + hour) % 12, (BRANCHES.index(bell) + hour) % 12
    places["地劫"], places["地空"] = (11 + hour) % 12, (11 - hour) % 12          # 卷二 86
    places["天马"] = BRANCHES.index(HORSE[branch])
    mutagen = dict(zip("禄权科忌", MUTAGEN[stem].split()))
    star_mutagen = {star: kind for kind, star in mutagen.items()}

    forward = (STEMS.index(stem) % 2 == 0) == (sex == "男")    # 阳男阴女顺行，阴男阳女逆行
    palaces = []
    for offset in range(12):
        b = (soul - offset) % 12                            # 十二宫逆布
        steps = (b - soul) % 12 if forward else (soul - b) % 12
        start = bureau + 10 * steps
        palaces.append({
            "branch": BRANCHES[b], "stem": stems[b], "name": PALACES[offset], "is_body_palace": b == body,
            "major": [{"name": s, **({"mutagen": star_mutagen[s]} if s in star_mutagen else {})}
                      for s in MAJOR if places[s] == b],
            "minor": [{"name": s, **({"mutagen": star_mutagen[s]} if s in star_mutagen else {})}
                      for s in MINOR if places[s] == b],
            "decade": [start, start + 9],
        })
    return {"year": stem + branch, "month": month, "day": day, "hour": BRANCHES[hour], "sex": sex,
            "soul_palace": BRANCHES[soul], "body_palace": BRANCHES[body], "nayin": element,
            "five_elements": f"{element[-1]}{'二三四五六'[bureau - 2]}局", "bureau": bureau, "soul_master": SOUL_MASTER[BRANCHES[soul]], "body_master": BODY_MASTER[branch],
            "mutagen": mutagen, "decade_direction": "顺行" if forward else "逆行", "palaces": palaces}


def counted_month(month: int, leap: bool) -> int:
    """卷二 10: a 闰月 counts as the next month (闰腊月 as 正月)."""
    return month % 12 + 1 if leap else month


def charts(clock: datetime, sex: str) -> tuple[dict, list[dict], dict]:
    """The chart for a birth on this (local or solar) clock, its candidate charts, and the calendar facts."""
    if sex not in ("男", "女"):
        raise ValueError("性别只能是 男 或 女（大限顺逆要用）")
    hour = hour_index(clock.hour)
    day_of = lunar.lunar_date(clock.date())
    main = build(day_of["year"], counted_month(day_of["month"], day_of["is_leap_month"]), day_of["day"], hour, sex)
    candidates = []
    if clock.hour == 23:                                    # 晚子时: the next day's date may be the one
        nxt = lunar.lunar_date(clock.date() + timedelta(days=1))
        candidates.append({"why": "晚子时（23:00-24:00）按次日起日数",
                           "chart": build(nxt["year"], counted_month(nxt["month"], nxt["is_leap_month"]),
                                          nxt["day"], hour, sex)})
    if day_of["is_leap_month"] and day_of["day"] <= 15:     # many current charts: first half = this month
        candidates.append({"why": "闰月前半月按本月（现代通行另一说）",
                           "chart": build(day_of["year"], day_of["month"], day_of["day"], hour, sex)})
    return main, candidates, day_of


def run(datetime_value: str, timezone_name: str, sex: str, longitude: float | None = None) -> dict:
    local, _zone = parse_local_datetime(datetime_value, timezone_name)
    solar = None
    clock = local
    if longitude is not None:
        clock, solar = apparent_solar_clock(local, longitude)
    main, candidates, day_of = charts(clock.replace(tzinfo=None), sex)
    soul = next(p for p in main["palaces"] if p["name"] == "命宫")
    stars = "、".join(s["name"] for s in soul["major"]) or "无主星（借对宫）"
    result = {
        "method": "紫微斗数命盘（《紫微斗数全书》卷二安星诀）",
        "input": {"datetime": datetime_value, "timezone": timezone_name, "sex": sex, "longitude": longitude},
        "chart": main,
        "candidates": candidates,
        "boundary_note": "只排命盘结构；不含杂曜、神煞、星曜庙旺，也不生成流年流月流日。",
    }
    result["calculation_record"] = calculation_record(
        basis=result["method"],
        inputs=result["input"],
        adopted_school=SCHOOL,
        key_structure={"soul_palace": main["soul_palace"], "body_palace": main["body_palace"],
                       "five_elements": main["five_elements"], "soul_stars": [s["name"] for s in soul["major"]],
                       "mutagen": main["mutagen"], "soul_master": main["soul_master"], "body_master": main["body_master"]},
        time_information={"clock_used": clock.replace(tzinfo=None).isoformat(timespec="minutes"),
                          "true_solar_time": solar, "lunar": day_of, "hour_branch": main["hour"],
                          "counted_month": main["month"], "candidate_reasons": [c["why"] for c in candidates]},
        interpretation_signals=[{
            "evidence": f"命宫在{main['soul_palace']}，主星{stars}；{main['five_elements']}",
            "supports": "作为性格倾向、做事方式与人生阶段结构的传统象征参考",
            "does_not_support": "不能推出寿命、疾病、婚姻成败、具体事件或必然吉凶",
        }],
        confidence_level="B" if candidates else "A",
        confidence_reasons=(["出生时间落在口径分歧处，另附候选盘：" + "；".join(c["why"] for c in candidates)]
                            if candidates else ["安星规则逐条出自《全书》卷二，输入完整，可复算"]),
    )
    return result


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="紫微斗数命盘（《紫微斗数全书》卷二）")
    parser.add_argument("--datetime", required=True, help="出生地钟表时间，ISO 格式，例如 1990-05-12T08:30:00")
    parser.add_argument("--timezone", required=True, help="IANA 时区，例如 Asia/Shanghai")
    parser.add_argument("--sex", required=True, choices=("男", "女"))
    parser.add_argument("--longitude", type=float, help="出生地经度（东经为正）；给了就按真太阳时定时辰")
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.datetime, args.timezone, args.sex, args.longitude), ensure_ascii=False, indent=2))
    except ValueError as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
