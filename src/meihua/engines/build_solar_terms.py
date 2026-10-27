#!/usr/bin/env python3
"""Build solar_terms.json: the moment of each of the 24 节气, 1900-2100, for the engines that need
them to the minute (cast_qimen: a 交节 changes the 局 within the hour).

Generated once with lunar_python (6tail's 寿星万年历, MIT), the same way lunar_table.json was
generated from ICU, so the engines themselves need no third-party package. The table is
second-level; it was checked against an independent JPL DE440s table (1950-2049: within 0.72 min).

    python build_solar_terms.py            # rewrites solar_terms.json next to this file
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from lunar_python import Solar

OUT = Path(__file__).with_name("solar_terms.json")
CHINA = timezone(timedelta(hours=8))          # lunar_python gives Beijing time
FIRST, LAST = 1900, 2100
# Calendar order within one Gregorian year: 小寒 is first, 冬至 last.
TERMS = ("小寒", "大寒", "立春", "雨水", "惊蛰", "春分", "清明", "谷雨", "立夏", "小满", "芒种", "夏至",
         "小暑", "大暑", "立秋", "处暑", "白露", "秋分", "寒露", "霜降", "立冬", "小雪", "大雪", "冬至")
PINYIN = {"DONG_ZHI": "冬至", "XIAO_HAN": "小寒", "DA_HAN": "大寒", "LI_CHUN": "立春", "YU_SHUI": "雨水",
          "JING_ZHE": "惊蛰", "DA_XUE": "大雪"}


def moments_in(year: int) -> dict[str, int]:
    """name -> UTC epoch seconds, for the terms falling in Gregorian `year` (Beijing date)."""
    found: dict[str, int] = {}
    for table_year in (year - 1, year, year + 1):
        for key, solar in Solar.fromYmd(table_year, 7, 1).getLunar().getJieQiTable().items():
            name = PINYIN.get(key, key)
            local = datetime(solar.getYear(), solar.getMonth(), solar.getDay(), solar.getHour(),
                             solar.getMinute(), solar.getSecond(), tzinfo=CHINA)
            if local.year == year:
                found[name] = int(local.timestamp())
    missing = [name for name in TERMS if name not in found]
    if missing:
        raise RuntimeError(f"{year} 缺节气：{missing}")
    return found


def main() -> None:
    years = {}
    for year in range(FIRST, LAST + 1):
        found = moments_in(year)
        years[str(year)] = [found[name] for name in TERMS]
    data = {"source": "lunar_python 1.4.8（寿星万年历）", "unit": "UTC epoch seconds", "first_year": FIRST,
            "last_year": LAST, "terms": list(TERMS), "years": years}
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {OUT.name}: {LAST - FIRST + 1} years")


if __name__ == "__main__":
    main()
