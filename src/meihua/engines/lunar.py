#!/usr/bin/env python3
"""Gregorian -> Chinese lunar date without Node.

Same output as gregorian_to_lunar.mjs (ICU Chinese calendar), read from
lunar_table.json, which build_lunar_table.mjs generated from that same ICU
calendar. Covers 1900-01-01 .. 2100-12-31. The packaged desktop app uses this;
tests check it against the Node script day by day.
"""

from __future__ import annotations

import bisect
import json
import sys
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

TABLE = Path(__file__).with_name("lunar_table.json")
BRANCHES = "子丑寅卯辰巳午未申酉戌亥"
MONTH_NAMES = ["正月", "二月", "三月", "四月", "五月", "六月", "七月", "八月", "九月", "十月", "十一月", "腊月"]


@lru_cache(maxsize=1)
def _table() -> tuple[list[date], list[list]]:
    data = json.loads(TABLE.read_text(encoding="utf-8"))
    rows = data["months"]
    return [date.fromisoformat(r[0]) for r in rows], rows


def lunar_date(day: date) -> dict:
    starts, rows = _table()
    index = bisect.bisect_right(starts, day) - 1
    if index < 0 or day.year > 2100:
        raise ValueError(f"超出农历表范围（1900-01-01 至 2100-12-31）：{day}")
    _, year, year_name, month, leap = rows[index]
    return {"year": year, "year_name": year_name, "month": month,
            "month_name": ("闰" if leap else "") + MONTH_NAMES[month - 1],
            "is_leap_month": leap, "day": (day - starts[index]).days + 1}


def hour_branch_number(hour: int) -> int:
    return 1 if hour in (23, 0) else (hour + 1) // 2 + 1


def convert(datetime_value: str, timezone: str) -> dict:
    """Drop-in for `node gregorian_to_lunar.mjs --datetime ... --timezone ...`."""
    moment = datetime.fromisoformat(datetime_value.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        raise ValueError("datetime 必须带 Z 或时区偏移，例如 2026-09-21T18:35:00+08:00")
    local = moment.astimezone(ZoneInfo(timezone))
    number = hour_branch_number(local.hour)
    return {
        "method": "ICU Chinese calendar conversion (table)",
        "input": {"datetime": datetime_value, "timezone": timezone},
        "lunar": lunar_date(local.date()),
        "local_clock": {"hour": local.hour, "minute": local.minute,
                        "hour_branch": BRANCHES[number - 1], "hour_branch_number": number},
    }


def main(argv: list[str]) -> int:
    args = dict(zip(argv[::2], argv[1::2]))
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(convert(args["--datetime"], args["--timezone"]), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
