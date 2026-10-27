"""奇门遁甲 engine (engines/cast_qimen.py) against 《统宗》's rules and two independent charts.

- 76 moments charted by taobi and qimen-skill (evidence/qimen-reference-cases.json), 时家转盘拆补法:
  where the two agree the engine must say the same; the two where taobi breaks 「值符常遣加时干」
  follow qimen-skill; 23:00-24:00 is qimen-skill's reading (子初换日) with taobi's as the candidate.
- The calendar it stands on: the 节气 table against lunar_python, the day's 干支 against lunar_python.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone

import pytest

import meihua
import cast_qimen  # type: ignore[import-not-found]  # noqa: E402 — engines on sys.path via meihua

REFERENCE = json.loads((meihua.ROOT / "evidence" / "qimen-reference-cases.json").read_text(encoding="utf-8"))
CASES = REFERENCE["cases"]
CHINA = timezone(timedelta(hours=8))


def plain(chart: dict) -> dict:
    """The engine's chart in the shape the reference cases use (eight outer palaces)."""
    return {"dun": chart["dun"], "ju": chart["ju"],
            "palaces": {p["name"]: {"earth": p["earth"], "sky": p["sky"], "star": p["star"], "door": p["door"],
                                    "god": p["god"]} for p in chart["palaces"] if p["number"] != 5}}


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_reference_moments(case):
    moment = datetime.fromisoformat(case["at"]).replace(tzinfo=CHINA)
    main, candidates = cast_qimen.charts(moment)
    ours = plain(main)
    if moment.hour == 23:                                   # 子初换日 (qimen-skill), 零点换日 (taobi)
        assert ours == case["skill"]
        assert [c["why"] for c in candidates][:1] == ["23:00-24:00 按零点换日（日柱仍是当天）"]
        assert plain(candidates[0]["chart"]) == case["taobi"]
    elif "taobi_wrong" in case:
        assert ours == case["skill"] != case["taobi"]
    else:
        assert ours == case["skill"] == case["taobi"]
    assert main["term"] == case["skill_reading"]["term"]


def test_the_boundary_moments_are_all_covered():
    kinds = {c["id"].split("-")[0] for c in CASES}
    assert kinds == {"spread", "term", "futou"} and sum(c["id"].startswith("term") for c in CASES) == 20


# ------------------------------------------------------------ the calendar under it

def test_the_day_cycle_agrees_with_lunar_python():
    lunar_python = pytest.importorskip("lunar_python")
    day = date(1950, 1, 1)
    while day < date(2051, 1, 1):
        expected = lunar_python.Solar.fromYmd(day.year, day.month, day.day).getLunar().getDayInGanZhi()
        assert cast_qimen.pillar(cast_qimen.day_index(day)) == expected, day
        day += timedelta(days=97)


def test_the_term_table_agrees_with_lunar_python_to_the_minute():
    lunar_python = pytest.importorskip("lunar_python")
    for year in (1901, 1949, 1986, 2000, 2026, 2049, 2099):
        table = lunar_python.Solar.fromYmd(year, 7, 1).getLunar().getJieQiTable()
        for name in ("立春", "夏至", "秋分", "冬至"):
            s = table[name]
            when = datetime(s.getYear(), s.getMonth(), s.getDay(), s.getHour(), s.getMinute(), s.getSecond(),
                            tzinfo=CHINA)
            got, begun, _ = cast_qimen.term_at(when + timedelta(seconds=1))
            assert got == name and abs((begun - when).total_seconds()) < 1


def test_the_years_and_months_turn_at_their_jie():
    lichun = datetime(2026, 2, 4, 4, 2, tzinfo=CHINA)        # 立春 2026-02-04 04:02
    assert cast_qimen.year_month(lichun - timedelta(minutes=5)) == ("乙巳", "己丑")
    assert cast_qimen.year_month(lichun + timedelta(minutes=5)) == ("丙午", "庚寅")


# ------------------------------------------------------------ boundaries and the record

def test_close_to_a_term_both_sides_are_given():
    _, begun, _ = cast_qimen.term_at(datetime(2024, 12, 21, 18, 0, tzinfo=CHINA))   # 冬至 17:20
    main, candidates = cast_qimen.charts(begun.astimezone(CHINA) + timedelta(minutes=1))
    assert main["term"] == "冬至" and main["dun"] == "阳遁"
    assert candidates and candidates[-1]["chart"]["term"] == "大雪" and candidates[-1]["chart"]["dun"] == "阴遁"
    main, candidates = cast_qimen.charts(begun.astimezone(CHINA) - timedelta(minutes=2))
    assert main["term"] == "大雪" and candidates[-1]["chart"]["term"] == "冬至"


def test_a_plain_moment_is_confidence_a_and_a_boundary_one_b():
    plain_record = cast_qimen.run("2026-10-27T11:30:00", "Asia/Shanghai")
    assert plain_record["calculation_record"]["calculation_confidence"]["level"] == "A"
    assert plain_record["calculation_record"]["key_structure"]["ju"] == 2
    late = cast_qimen.run("2026-10-27T23:30:00", "Asia/Shanghai")
    assert late["calculation_record"]["calculation_confidence"]["level"] == "B"
    assert all(s["does_not_support"] for s in late["calculation_record"]["interpretation_signals"])


def test_the_command_line_prints_a_chart():
    out = subprocess.run([sys.executable, str(meihua.ENGINES / "cast_qimen.py"), "--datetime", "2026-10-27T11:30:00",
                          "--timezone", "Asia/Shanghai"], capture_output=True, text=True, encoding="utf-8", check=True)
    chart = json.loads(out.stdout)["chart"]
    assert (chart["dun"], chart["ju"], chart["zhi_fu"]) == ("阴遁", 2, {"star": "天芮", "palace": "离"})
