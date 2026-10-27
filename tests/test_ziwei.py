"""紫微斗数 engine (engines/cast_ziwei.py) against 《紫微斗数全书》卷二 and two independent charts.

- The five 起紫微 tables printed in 卷二: every cell, but for the two copying slips on record.
- 64 births charted by iztro and fortel-ziweidoushu (evidence/ziwei-reference-cases.json): where the
  two agree, the engine must say the same; where they part, 《全书》 decides (命主 by 命宫, 化科 for
  戊庚壬); the 晚子时 and the first half of a 闰月 get a second chart that matches the other reading.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime

import pytest

import meihua
import cast_ziwei  # type: ignore[import-not-found]  # noqa: E402 — engines on sys.path via meihua

EVIDENCE = meihua.ROOT / "evidence"
TABLES = json.loads((EVIDENCE / "ziwei-quanshu-tables.json").read_text(encoding="utf-8"))
REFERENCE = json.loads((EVIDENCE / "ziwei-reference-cases.json").read_text(encoding="utf-8"))
CASES = REFERENCE["cases"]
QUANSHU_KE = {"戊": "右弼", "庚": "太阴", "壬": "天府"}     # 卷二 76-84, where the two libraries part


def plain(chart: dict) -> dict:
    """The engine's chart in the shape the reference cases use."""
    return {"soul": chart["soul_palace"], "body": chart["body_palace"], "five": chart["five_elements"],
            "soulMaster": chart["soul_master"], "bodyMaster": chart["body_master"], "mutagen": chart["mutagen"],
            "palaces": {p["branch"]: {"stem": p["stem"], "name": p["name"].removesuffix("宫"),   # 命宫 → 命
                                      "major": sorted(s["name"] for s in p["major"]),
                                      "minor": sorted(s["name"] for s in p["minor"]),
                                      "decade": f"{p['decade'][0]}-{p['decade'][1]}"} for p in chart["palaces"]}}


def same(ours: dict, theirs: dict, year_stem: str, soul_master: bool = False) -> list[str]:
    """Fields where the engine differs from a library's chart, 《全书》's 化科 taken as given. 命主 is
    compared only with iztro (`soul_master`): fortel takes it from the year, not from 命宫."""
    fields = ("soul", "body", "five", "bodyMaster") + (("soulMaster",) if soul_master else ())
    diffs = [f for f in fields if ours[f] != theirs[f]]
    for kind in "禄权忌":
        if ours["mutagen"][kind] != theirs["mutagen"][kind]:
            diffs.append("化" + kind)
    for branch, palace in theirs["palaces"].items():
        for field in ("stem", "name", "major", "minor", "decade"):
            if ours["palaces"][branch][field] != palace[field]:
                diffs.append(f"{field}{branch}")
    if ours["mutagen"]["科"] != QUANSHU_KE.get(year_stem, theirs["mutagen"]["科"]):
        diffs.append("化科")
    return diffs


# ------------------------------------------------------------ 《全书》卷二's own tables

def test_every_cell_of_the_quanshu_tables_but_the_two_slips():
    errata = {(e["table"], e["branch"], e["reads"]) for e in TABLES["errata"]}
    checked, slips = 0, set()
    for name, table in TABLES["cells_as_printed"].items():
        for day, branch in table["cells"]:
            got = cast_ziwei.BRANCHES[cast_ziwei.ziwei_branch(table["bureau"], day)]
            if (name, branch, day) in errata:
                slips.add((name, branch, day))
                continue
            assert got == branch, f"{name}{day}日：表在{branch}，引擎在{got}"
            checked += 1
    assert checked == 148 and slips == {("木三局", "寅", 9)}      # 149 printed cells, one slip
    # The slips, read as they should: 木三局 初五 in 寅, 金四局 三十 in 亥.
    assert cast_ziwei.BRANCHES[cast_ziwei.ziwei_branch(3, 5)] == "寅"
    assert cast_ziwei.BRANCHES[cast_ziwei.ziwei_branch(4, 30)] == "亥"


def test_the_worked_examples_in_the_text():
    # 卷二 11: 「正月初一生者是火局，酉宫起初一日」.
    assert cast_ziwei.BRANCHES[cast_ziwei.ziwei_branch(6, 1)] == "酉"
    # 卷二 12: a 甲 year with 命宫 in 寅: 丙寅 炉中火.
    assert cast_ziwei.nayin("丙", "寅") == "炉中火"


# ------------------------------------------------------------ two independent charts, 64 births

def _ours(case: dict) -> tuple[dict, list[dict]]:
    main, candidates, _ = cast_ziwei.charts(datetime.fromisoformat(case["clock"]), case["sex"])
    return plain(main), [dict(c, chart=plain(c["chart"])) for c in candidates]


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_reference_births(case):
    clock = datetime.fromisoformat(case["clock"])
    main, candidates, day_of = cast_ziwei.charts(clock, case["sex"])
    ours, stem = plain(main), main["year"][0]
    iztro, fortel = case["iztro"], case["fortel"]
    assert ours["soulMaster"] == cast_ziwei.SOUL_MASTER[ours["soul"]]        # 卷二 185: by 命宫
    reasons = [c["why"] for c in candidates]
    if clock.hour == 23:                                          # 晚子时: this day (fortel) or the next (iztro)
        assert reasons == ["晚子时（23:00-24:00）按次日起日数"]
        assert same(ours, fortel, stem) == []
        assert same(plain(candidates[0]["chart"]), iztro, stem, soul_master=True) == []
    elif day_of["is_leap_month"] and day_of["day"] <= 15:         # both libraries: the first half is this month
        assert reasons == ["闰月前半月按本月（现代通行另一说）"]
        other = plain(candidates[0]["chart"])
        assert same(other, iztro, stem, soul_master=True) == [] and same(other, fortel, stem) == []
        assert ours["soul"] != other["soul"]                      # 《全书》: the whole 闰月 is the next month
    else:
        assert reasons == []
        assert same(ours, iztro, stem, soul_master=True) == [] and same(ours, fortel, stem) == []


# ------------------------------------------------------------ the record and the command line

def test_a_plain_birth_is_confidence_a_and_a_boundary_one_b():
    record = cast_ziwei.run("1990-05-12T08:30:00", "Asia/Shanghai", "男")["calculation_record"]
    assert record["calculation_confidence"]["level"] == "A"
    assert record["key_structure"]["soul_palace"] == "丑" and record["key_structure"]["soul_stars"] == ["太阳", "太阴"]
    late = cast_ziwei.run("2001-11-20T23:30:00", "Asia/Shanghai", "女")
    assert late["calculation_record"]["calculation_confidence"]["level"] == "B" and len(late["candidates"]) == 1
    assert all(s["does_not_support"] for s in late["calculation_record"]["interpretation_signals"])


def test_a_leap_twelfth_month_counts_as_the_first():
    assert cast_ziwei.counted_month(12, True) == 1 and cast_ziwei.counted_month(4, True) == 5
    assert cast_ziwei.counted_month(4, False) == 4


def test_true_solar_time_moves_the_hour_when_given():
    # 08:00 Beijing time in Urumqi (87.6°E) is about 05:54 by the sun: 卯时, not 辰时. (Not 1986-1991:
    # China kept summer time then, and the same clock reading is an hour earlier still.)
    clock = cast_ziwei.run("2000-05-12T08:00:00", "Asia/Shanghai", "男", 87.6)
    assert clock["chart"]["hour"] == "卯" and clock["calculation_record"]["time_information"]["true_solar_time"]
    summer = cast_ziwei.run("1990-05-12T08:00:00", "Asia/Shanghai", "男", 87.6)
    assert summer["chart"]["hour"] == "寅"


def test_the_command_line_prints_a_chart():
    out = subprocess.run([sys.executable, str(meihua.ENGINES / "cast_ziwei.py"), "--datetime", "1990-05-12T08:30:00",
                          "--timezone", "Asia/Shanghai", "--sex", "男"], capture_output=True, text=True,
                         encoding="utf-8", check=True)
    assert json.loads(out.stdout)["chart"]["five_elements"] == "火六局"
