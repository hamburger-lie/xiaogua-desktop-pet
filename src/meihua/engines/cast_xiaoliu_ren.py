#!/usr/bin/env python3
"""Deterministic Xiao Liu Ren month-day-hour casting helper."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import lunar
from result_contract import calculation_record


PALACES = ("大安", "留连", "速喜", "赤口", "小吉", "空亡")
BRANCHES = ("子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥")
BRANCH_ALIASES = {name: index for index, name in enumerate(BRANCHES, start=1)}


def palace(index_zero_based: int) -> dict:
    normalized = index_zero_based % len(PALACES)
    return {"index": normalized + 1, "name": PALACES[normalized]}


def branch_number(value: str) -> int:
    if value.isdigit() and 1 <= int(value) <= 12:
        return int(value)
    if value in BRANCH_ALIASES:
        return BRANCH_ALIASES[value]
    raise ValueError(f"未知时支：{value}")


def convert_gregorian(datetime_value: str, timezone: str) -> dict:
    # Table lookup generated from ICU (lunar.py); no Node runtime needed.
    return lunar.convert(datetime_value, timezone)


def cast(lunar_month: int, lunar_day: int, hour_branch: int, is_leap_month: bool = False,
         conversion: dict | None = None) -> dict:
    """The 课 for a lunar month, day and hour branch (1-12); conversion: lunar.convert's record, if any."""
    month_index = lunar_month - 1
    day_index = month_index + lunar_day - 1
    final_index = day_index + hour_branch - 1
    result = {
        "method": "小六壬月日时法（起点计一）",
        "input": {
            "lunar_month": lunar_month,
            "lunar_day": lunar_day,
            "is_leap_month": is_leap_month,
            "hour_branch": BRANCHES[hour_branch - 1],
            "hour_branch_number": hour_branch,
        },
        "palace_order": list(PALACES),
        "trace": {
            "month_palace": palace(month_index),
            "day_palace": palace(day_index),
            "final_palace": palace(final_index),
            "formula": "(农历月-1 + 农历日-1 + 时支序数-1) mod 6",
        },
        "calendar_conversion": conversion,
        "boundary_note": "这是小六壬六宫起课，不生成六十四卦、动爻、体用或六爻纳甲信息。",
    }
    result["calculation_record"] = calculation_record(
        basis=result["method"],
        inputs=result["input"],
        adopted_school="小六壬月日时六宫顺数；起点计一",
        key_structure={"final_palace": result["trace"]["final_palace"]},
        time_information={
            "source": "公历自动换算" if conversion else "用户提供农历月日时支",
            "local_clock": conversion.get("local_clock") if conversion else None,
        },
        interpretation_signals=[{
            "evidence": f"最终课宫为{result['trace']['final_palace']['name']}",
            "supports": "提供短期节奏、沟通或行动条件的传统象义提示",
            "does_not_support": "不能推出精确日期、他人隐私、必然成败或六十四卦信息",
        }],
        confidence_level="A" if conversion else "B",
        confidence_reasons=[
            "六宫顺序与起点计一规则固定且可复算",
            "公历输入已自动换算并保留历法记录" if conversion else "农历输入依赖用户自行确认",
        ],
    )
    return result


def main() -> None:
    # Windows pipes default to the ANSI code page; downstream tools read UTF-8.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--lunar-month", type=int, choices=range(1, 13))
    parser.add_argument("--lunar-day", type=int, choices=range(1, 31))
    parser.add_argument("--hour-branch", help="子至亥，或 1 至 12")
    parser.add_argument("--leap-month", action="store_true")
    parser.add_argument("--datetime", help="带时区偏移的 ISO 时间")
    parser.add_argument("--timezone", help="IANA 时区，例如 Asia/Shanghai")
    args = parser.parse_args()

    conversion = None
    if args.datetime:
        if not args.timezone:
            parser.error("datetime 模式必须提供 --timezone")
        if args.lunar_month or args.lunar_day or args.hour_branch:
            parser.error("datetime 模式不能同时提供农历月日或时支")
        try:
            conversion = convert_gregorian(args.datetime, args.timezone)
        except ValueError as error:
            parser.error(str(error))
        lunar_month = conversion["lunar"]["month"]
        lunar_day = conversion["lunar"]["day"]
        is_leap_month = conversion["lunar"]["is_leap_month"]
        hour_branch = conversion["local_clock"]["hour_branch_number"]
    else:
        if args.lunar_month is None or args.lunar_day is None or args.hour_branch is None:
            parser.error("请提供 --datetime 与 --timezone，或完整的农历月、日和时支")
        lunar_month = args.lunar_month
        lunar_day = args.lunar_day
        is_leap_month = args.leap_month
        try:
            hour_branch = branch_number(args.hour_branch)
        except ValueError as error:
            parser.error(str(error))

    result = cast(lunar_month, lunar_day, hour_branch, is_leap_month, conversion)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
