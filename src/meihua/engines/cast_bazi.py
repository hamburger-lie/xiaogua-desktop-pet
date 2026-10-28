#!/usr/bin/env python3
"""Deterministically cast Four Pillars from a birth datetime.

The calendrical layer is intentionally separate from interpretation.  It uses
the apparent solar longitude for Li Chun and the twelve month-opening jie,
supports legal or apparent-solar clock time, and makes disputed day-boundary
choices explicit.
"""

from __future__ import annotations

import argparse
import json
import sys
import math
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from analyze_bazi import BRANCH_ORDER, STEM_ORDER, STEMS, ten_god
from result_contract import calculation_record


UTC = timezone.utc
JIAZI = tuple(
    STEM_ORDER[index % 10] + BRANCH_ORDER[index % 12]
    for index in range(60)
)

# Month-opening jie, starting from Li Chun.  Their apparent solar longitudes
# are spaced by 30 degrees.
JIE_NAMES = (
    "立春", "惊蛰", "清明", "立夏", "芒种", "小暑",
    "立秋", "白露", "寒露", "立冬", "大雪", "小寒",
)
JIE_LONGITUDES = tuple((315 + 30 * index) % 360 for index in range(12))


def normalize_angle(value: float) -> float:
    return value % 360.0


def signed_angle(value: float) -> float:
    """Return an angle in [-180, 180)."""
    return (value + 180.0) % 360.0 - 180.0


def julian_day(moment_utc: datetime) -> float:
    if moment_utc.tzinfo is None:
        raise ValueError("Julian day requires a timezone-aware datetime")
    return 2440587.5 + moment_utc.astimezone(UTC).timestamp() / 86400.0


def solar_apparent_longitude(moment_utc: datetime) -> float:
    """Low-order Meeus/NOAA apparent geocentric solar longitude in degrees.

    The approximation is appropriate for boundary detection in 1901-2099.
    Near a boundary, callers should surface the boundary instead of claiming
    false precision.
    """
    t = (julian_day(moment_utc) - 2451545.0) / 36525.0
    mean_longitude = normalize_angle(
        280.46646 + t * (36000.76983 + t * 0.0003032)
    )
    mean_anomaly = normalize_angle(
        357.52911 + t * (35999.05029 - 0.0001537 * t)
    )
    anomaly_radians = math.radians(mean_anomaly)
    equation_of_center = (
        math.sin(anomaly_radians)
        * (1.914602 - t * (0.004817 + 0.000014 * t))
        + math.sin(2 * anomaly_radians) * (0.019993 - 0.000101 * t)
        + math.sin(3 * anomaly_radians) * 0.000289
    )
    true_longitude = mean_longitude + equation_of_center
    omega = math.radians(125.04 - 1934.136 * t)
    return normalize_angle(true_longitude - 0.00569 - 0.00478 * math.sin(omega))


def equation_of_time_minutes(moment_utc: datetime) -> float:
    """NOAA/Meeus equation of time, in minutes."""
    t = (julian_day(moment_utc) - 2451545.0) / 36525.0
    epsilon = 23.439291 - 0.0130042 * t
    y = math.tan(math.radians(epsilon) / 2.0) ** 2
    mean_longitude = math.radians(normalize_angle(
        280.46646 + t * (36000.76983 + t * 0.0003032)
    ))
    mean_anomaly = math.radians(normalize_angle(
        357.52911 + t * (35999.05029 - 0.0001537 * t)
    ))
    eccentricity = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)
    value = (
        y * math.sin(2 * mean_longitude)
        - 2 * eccentricity * math.sin(mean_anomaly)
        + 4 * eccentricity * y * math.sin(mean_anomaly) * math.cos(2 * mean_longitude)
        - 0.5 * y * y * math.sin(4 * mean_longitude)
        - 1.25 * eccentricity * eccentricity * math.sin(2 * mean_anomaly)
    )
    return math.degrees(value) * 4.0


def solve_solar_longitude(guess_utc: datetime, target_degrees: float) -> datetime:
    """Solve a nearby apparent-solar-longitude crossing by Newton iteration."""
    current = guess_utc.astimezone(UTC)
    for _ in range(12):
        error = signed_angle(solar_apparent_longitude(current) - target_degrees)
        if abs(error) < 1e-8:
            break
        current -= timedelta(days=error / 0.98564736)
    return current


def nearby_jie(moment_utc: datetime) -> dict:
    longitude = solar_apparent_longitude(moment_utc)
    relative = normalize_angle(longitude - 315.0)
    index = int(relative // 30.0)
    progress = relative - index * 30.0
    previous_target = JIE_LONGITUDES[index]
    next_index = (index + 1) % 12
    next_target = JIE_LONGITUDES[next_index]
    previous_guess = moment_utc - timedelta(days=progress / 0.98564736)
    next_guess = moment_utc + timedelta(days=(30.0 - progress) / 0.98564736)
    previous_time = solve_solar_longitude(previous_guess, previous_target)
    next_time = solve_solar_longitude(next_guess, next_target)
    result = {
        "previous": {
            "name": JIE_NAMES[index],
            "longitude": previous_target,
            "utc": previous_time,
            "distance_minutes": (moment_utc - previous_time).total_seconds() / 60.0,
        },
        "next": {
            "name": JIE_NAMES[next_index],
            "longitude": next_target,
            "utc": next_time,
            "distance_minutes": (next_time - moment_utc).total_seconds() / 60.0,
        },
    }
    return result


def lichun_time(year: int) -> datetime:
    return solve_solar_longitude(datetime(year, 2, 4, 8, tzinfo=UTC), 315.0)


def parse_local_datetime(value: str, timezone_name: str) -> tuple[datetime, ZoneInfo]:
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as error:
        raise ValueError(f"未知 IANA 时区：{timezone_name}") from error
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError("出生时间应为 ISO 格式，例如 1990-05-12T08:30:00") from error
    wall_time = parsed.replace(tzinfo=None)
    valid_candidates = {}
    for fold in (0, 1):
        candidate = wall_time.replace(tzinfo=zone, fold=fold)
        round_trip = candidate.astimezone(UTC).astimezone(zone)
        if round_trip.replace(tzinfo=None) == wall_time:
            valid_candidates[candidate.utcoffset()] = candidate

    if not valid_candidates:
        raise ValueError(
            f"当地时间 {wall_time.isoformat()} 在 {timezone_name} 因夏令时跳转而不存在；"
            "请核对出生记录中的实际钟表时间"
        )

    if parsed.tzinfo is None:
        if len(valid_candidates) > 1:
            offsets = "、".join(
                sorted(candidate.strftime("UTC%z") for candidate in valid_candidates.values())
            )
            raise ValueError(
                f"当地时间 {wall_time.isoformat()} 在 {timezone_name} 因夏令时回拨而重复；"
                f"请在 ISO 时间中明确 UTC 偏移（候选：{offsets}）"
            )
        local = next(iter(valid_candidates.values()))
    else:
        local = parsed.astimezone(zone)
        if local.replace(tzinfo=None) != wall_time:
            raise ValueError(
                f"输入偏移与 {timezone_name} 当时的法定时间不一致；"
                "请使用出生地当地钟表时间和正确 UTC 偏移"
            )
        if local.utcoffset() not in valid_candidates:
            raise ValueError(
                f"输入 UTC 偏移不适用于 {timezone_name} 的该当地时间"
            )
    if not 1901 <= local.year <= 2099:
        raise ValueError("自动排盘当前只支持 1901—2099 年")
    return local, zone


def apparent_solar_clock(local: datetime, longitude: float) -> tuple[datetime, dict]:
    if not -180.0 <= longitude <= 180.0:
        raise ValueError("经度必须在 -180 到 180 度之间，东经为正、西经为负")
    utc_moment = local.astimezone(UTC)
    daylight_minutes = (local.dst() or timedelta()).total_seconds() / 60.0
    standard_offset = local.utcoffset() - (local.dst() or timedelta())
    standard_offset_hours = standard_offset.total_seconds() / 3600.0
    longitude_correction = 4.0 * (longitude - 15.0 * standard_offset_hours)
    eot = equation_of_time_minutes(utc_moment)
    correction = longitude_correction + eot - daylight_minutes
    return local + timedelta(minutes=correction), {
        "longitude_degrees": longitude,
        "standard_meridian_degrees": 15.0 * standard_offset_hours,
        "longitude_correction_minutes": longitude_correction,
        "equation_of_time_minutes": eot,
        "daylight_saving_correction_minutes": -daylight_minutes,
        "total_correction_minutes": correction,
    }


def gregorian_jdn(value: date) -> int:
    year, month, day = value.year, value.month, value.day
    a = (14 - month) // 12
    adjusted_year = year + 4800 - a
    adjusted_month = month + 12 * a - 3
    return (
        day
        + (153 * adjusted_month + 2) // 5
        + 365 * adjusted_year
        + adjusted_year // 4
        - adjusted_year // 100
        + adjusted_year // 400
        - 32045
    )


def pillar_from_index(index: int) -> str:
    return JIAZI[index % 60]


def year_pillar(moment_utc: datetime) -> tuple[str, int, datetime]:
    civil_year = moment_utc.year
    boundary = lichun_time(civil_year)
    pillar_year = civil_year if moment_utc >= boundary else civil_year - 1
    index = (pillar_year - 1984) % 60
    return pillar_from_index(index), pillar_year, boundary


def month_pillar(moment_utc: datetime, year_stem: str) -> tuple[str, int, float]:
    longitude = solar_apparent_longitude(moment_utc)
    month_index = int(normalize_angle(longitude - 315.0) // 30.0)
    branch_index = (2 + month_index) % 12  # 寅 starts the solar-term year.
    stem_index = ((STEM_ORDER.index(year_stem) % 5) * 2 + 2 + month_index) % 10
    return STEM_ORDER[stem_index] + BRANCH_ORDER[branch_index], month_index, longitude


def day_pillar(clock: datetime, boundary: str) -> tuple[str, date]:
    effective_date = clock.date()
    if boundary == "zi-initial" and clock.hour == 23:
        effective_date += timedelta(days=1)
    index = (gregorian_jdn(effective_date) + 49) % 60
    return pillar_from_index(index), effective_date


def hour_pillar(clock: datetime, day_stem: str) -> tuple[str, int]:
    branch_index = ((clock.hour + 1) // 2) % 12
    stem_index = (STEM_ORDER.index(day_stem) * 2 + branch_index) % 10
    return STEM_ORDER[stem_index] + BRANCH_ORDER[branch_index], branch_index


def cast_at_clock(moment_utc: datetime, clock: datetime, day_boundary: str) -> dict:
    year_value, pillar_year, lichun = year_pillar(moment_utc)
    month_value, month_index, longitude = month_pillar(moment_utc, year_value[0])
    day_value, effective_day = day_pillar(clock, day_boundary)
    hour_value, hour_index = hour_pillar(clock, day_value[0])
    return {
        "pillars": [year_value, month_value, day_value, hour_value],
        "pillar_map": {
            "年柱": year_value,
            "月柱": month_value,
            "日柱": day_value,
            "时柱": hour_value,
        },
        "clock": clock.isoformat(),
        "day_boundary": day_boundary,
        "effective_day_date": effective_day.isoformat(),
        "solar_longitude_degrees": longitude,
        "solar_month_index_from_yin": month_index,
        "pillar_year": pillar_year,
        "lichun_utc": lichun.isoformat(),
        "hour_branch_index": hour_index,
    }


def luck_direction(year_stem: str, sex: str | None, explicit: str | None) -> tuple[str | None, str]:
    if explicit:
        return explicit, "用户直接指定顺排或逆排"
    if not sex:
        return None, "未提供性别或顺逆方向，不自动排大运"
    yang_year = STEMS[year_stem]["yin_yang"] == "阳"
    forward = (sex == "male" and yang_year) or (sex == "female" and not yang_year)
    return ("forward" if forward else "reverse"), "按年干阴阳与传统性别规则定顺逆"


def luck_cycles(
    birth_utc: datetime,
    month_value: str,
    direction: str,
    jie: dict,
    count: int = 8,
) -> dict:
    target = jie["next"] if direction == "forward" else jie["previous"]
    interval_days = abs((target["utc"] - birth_utc).total_seconds()) / 86400.0
    start_age = interval_days / 3.0
    month_index = JIAZI.index(month_value)
    step = 1 if direction == "forward" else -1
    cycles = []
    for index in range(1, count + 1):
        start = start_age + (index - 1) * 10.0
        cycles.append({
            "sequence": index,
            "pillar": pillar_from_index(month_index + step * index),
            "start_age": round(start, 3),
            "end_age": round(start + 10.0, 3),
        })
    whole_years = int(start_age)
    months = int(round((start_age - whole_years) * 12))
    if months == 12:
        whole_years += 1
        months = 0
    return {
        "direction": direction,
        "reference_jie": {
            "name": target["name"],
            "utc": target["utc"].isoformat(),
        },
        "conversion_rule": "出生至顺排下一节或逆排上一节的时距；三日折一年",
        "start_age_years": round(start_age, 6),
        "start_age_display": f"约{whole_years}年{months}个月",
        "cycles": cycles,
    }


def flow_year(target_year: int, day_stem: str, natal_branches: list[str]) -> dict:
    value = pillar_from_index((target_year - 1984) % 60)
    stem, branch = value
    combinations = {
        "子": "丑", "丑": "子", "寅": "亥", "亥": "寅",
        "卯": "戌", "戌": "卯", "辰": "酉", "酉": "辰",
        "巳": "申", "申": "巳", "午": "未", "未": "午",
    }
    clashes = {
        "子": "午", "午": "子", "丑": "未", "未": "丑",
        "寅": "申", "申": "寅", "卯": "酉", "酉": "卯",
        "辰": "戌", "戌": "辰", "巳": "亥", "亥": "巳",
    }
    return {
        "year": target_year,
        "cycle": f"{target_year}年立春起的流年周期",
        "boundary": "从该公历年的立春起，至下一年立春前止",
        "pillar": value,
        "visible_ten_god": ten_god(day_stem, stem),
        "branch_links": {
            "six_combination_with": [b for b in natal_branches if combinations[branch] == b],
            "six_clash_with": [b for b in natal_branches if clashes[branch] == b],
        },
        "note": "只提供结构关系，不据此保证具体事件发生。",
    }


def flow_date(
    target_value: str,
    timezone_name: str,
    day_stem: str,
    natal_branches: list[str],
) -> dict:
    value = target_value if "T" in target_value else f"{target_value}T12:00:00"
    target_local, _ = parse_local_datetime(value, timezone_name)
    target_utc = target_local.astimezone(UTC)
    pillar, pillar_year, boundary = year_pillar(target_utc)
    result = flow_year(pillar_year, day_stem, natal_branches)
    result.update({
        "target_date": target_local.date().isoformat(),
        "target_local_time": target_local.isoformat(),
        "pillar": pillar,
        "pillar_year": pillar_year,
        "relevant_lichun_local": boundary.astimezone(target_local.tzinfo).isoformat(),
        "boundary": "按目标日期与当地立春实际时刻判断流年归属",
    })
    return result


def cast_birth_chart(
    datetime_value: str,
    timezone_name: str,
    longitude: float | None,
    clock_mode: str,
    day_boundary: str,
    sex: str | None = None,
    direction: str | None = None,
    target_year: int | None = None,
    target_date: str | None = None,
    uncertainty_minutes: float = 0.0,
) -> dict:
    local, zone = parse_local_datetime(datetime_value, timezone_name)
    birth_utc = local.astimezone(UTC)
    if clock_mode == "true-solar" and longitude is None:
        raise ValueError("真太阳时模式必须提供出生地经度；东经为正、西经为负")
    if uncertainty_minutes < 0 or uncertainty_minutes > 1440:
        raise ValueError("出生时间误差范围必须在 0—1440 分钟之间")
    if target_year is not None and target_date is not None:
        raise ValueError("--target-year 与 --target-date 只能选择一个")

    solar_clock = None
    correction = None
    if longitude is not None:
        solar_clock, correction = apparent_solar_clock(local, longitude)
    primary_clock = solar_clock if clock_mode == "true-solar" else local
    primary = cast_at_clock(birth_utc, primary_clock, day_boundary)
    jie = nearby_jie(birth_utc)

    warnings = []
    nearest_key = min(
        ("previous", "next"),
        key=lambda key: jie[key]["distance_minutes"],
    )
    nearest_boundary = jie[nearest_key]
    nearest_distance = nearest_boundary["distance_minutes"]
    if uncertainty_minutes > 0 and nearest_distance <= uncertainty_minutes:
        warnings.append("出生时间误差范围跨越月令交界，候选盘可能具有不同年柱或月柱。")
    elif nearest_distance <= 15:
        warnings.append("出生时刻距月令交界不超过15分钟，建议确认出生记录的时间精度。")
    if primary_clock.hour == 23:
        warnings.append("出生落在23时段，子初换日与子正换日会产生不同日柱，已提供对照盘。")
    if solar_clock is not None and (
        local.date() != solar_clock.date()
        or ((local.hour + 1) // 2) % 12 != ((solar_clock.hour + 1) // 2) % 12
    ):
        warnings.append("真太阳时校正跨越日期或时辰边界，已提供法定时间对照盘。")

    comparisons = []
    uncertainty_charts = []
    if uncertainty_minutes > 0:
        for label, sign in (("出生时间误差下限", -1), ("出生时间误差上限", 1)):
            candidate_utc = birth_utc + timedelta(minutes=sign * uncertainty_minutes)
            candidate_local = candidate_utc.astimezone(zone)
            if clock_mode == "true-solar":
                candidate_clock, _ = apparent_solar_clock(candidate_local, longitude)
            else:
                candidate_clock = candidate_local
            candidate = cast_at_clock(candidate_utc, candidate_clock, day_boundary)
            uncertainty_charts.append((label, candidate))
            if candidate["pillars"] != primary["pillars"]:
                comparisons.append({"reason": label, **candidate})
        if len({tuple(chart["pillars"]) for _, chart in uncertainty_charts}) > 1:
            warnings.append("出生时间误差上下限得到不同四柱，解读必须保留共同结论与差异点。")
    if solar_clock is not None:
        alternate_mode = "legal" if clock_mode == "true-solar" else "true-solar"
        alternate_clock = local if alternate_mode == "legal" else solar_clock
        alternate = cast_at_clock(birth_utc, alternate_clock, day_boundary)
        if alternate["pillars"] != primary["pillars"]:
            comparisons.append({"reason": f"{alternate_mode} 时间口径", **alternate})
    if primary_clock.hour == 23:
        alternate_boundary = "midnight" if day_boundary == "zi-initial" else "zi-initial"
        alternate = cast_at_clock(birth_utc, primary_clock, alternate_boundary)
        if alternate["pillars"] != primary["pillars"]:
            comparisons.append({"reason": f"{alternate_boundary} 换日口径", **alternate})

    selected_direction, direction_basis = luck_direction(primary["pillars"][0][0], sex, direction)
    luck = None
    if selected_direction:
        luck = luck_cycles(
            birth_utc,
            primary["pillars"][1],
            selected_direction,
            jie,
        )
        luck["direction_basis"] = direction_basis

    annual = None
    if target_date is not None:
        annual = flow_date(
            target_date,
            timezone_name,
            primary["pillars"][2][0],
            [pillar[1] for pillar in primary["pillars"]],
        )
    elif target_year is not None:
        if not 1901 <= target_year <= 2099:
            raise ValueError("流年年份当前只支持 1901—2099 年")
        annual = flow_year(
            target_year,
            primary["pillars"][2][0],
            [pillar[1] for pillar in primary["pillars"]],
        )

    result = {
        "method": "子平四柱排盘",
        "input": {
            "birth_datetime": datetime_value,
            "timezone": timezone_name,
            "longitude": longitude,
            "clock_mode": clock_mode,
            "day_boundary": day_boundary,
            "sex": sex,
            "explicit_direction": direction,
            "uncertainty_minutes": uncertainty_minutes,
            "target_year": target_year,
            "target_date": target_date,
        },
        "time_conversion": {
            "legal_local_time": local.isoformat(),
            "birth_utc": birth_utc.isoformat(),
            "apparent_solar_time": solar_clock.isoformat() if solar_clock else None,
            "correction": correction,
        },
        "primary_chart": primary,
        "comparison_charts": comparisons,
        "jie_boundaries": {
            key: {
                **{k: v for k, v in value.items() if k != "utc"},
                "utc": value["utc"].isoformat(),
                "local": value["utc"].astimezone(local.tzinfo).isoformat(),
            }
            for key, value in jie.items()
        },
        "boundary_warnings": warnings,
        "luck_cycles": luck,
        "flow_year": annual,
        "rules": [
            "年柱以立春为界，月柱以十二个节为界。",
            "默认真太阳时时，以经度差和均时差校正法定时间。",
            "日界口径显式记录；边界对照盘不是第二次测算。",
            "只有出生时间误差范围实际跨越边界时，才把误差上下限列为候选盘。",
            "大运默认按年干阴阳与传统性别规则定顺逆，三日折一年；也可由用户直接指定顺逆。",
        ],
        "limits": [
            "太阳位置采用适用于1901—2099年的近似算法；交界附近必须核对权威历书或专业排盘。",
            "排盘规则的一致性不等于预测得到实证验证。",
        ],
    }
    confidence_level = "A"
    confidence_reasons = [
        "出生时间、时区与所选日界口径已显式记录",
        "年柱与月柱按太阳视黄经边界计算",
    ]
    if comparison_charts := result["comparison_charts"]:
        confidence_level = "B"
        confidence_reasons.append(
            f"存在{len(comparison_charts)}个会改变四柱的边界或口径候选"
        )
    if uncertainty_minutes > 0:
        confidence_reasons.append(f"已检查出生时间正负{uncertainty_minutes:g}分钟区间")
    result["calculation_record"] = calculation_record(
        basis=result["method"],
        inputs=result["input"],
        adopted_school=(
            "立春换年、十二节换月、"
            + ("真太阳时" if clock_mode == "true-solar" else "法定时间")
            + ("、23时子初换日" if day_boundary == "zi-initial" else "、零时换日")
        ),
        key_structure={
            "pillars": primary["pillars"],
            "pillar_year": primary["pillar_year"],
            "comparison_chart_count": len(result["comparison_charts"]),
            "luck_direction": selected_direction,
            "flow_year": annual,
        },
        time_information={
            "legal_local_time": local.isoformat(),
            "birth_utc": birth_utc.isoformat(),
            "apparent_solar_time": solar_clock.isoformat() if solar_clock else None,
            "nearest_jie": {
                "name": nearest_boundary["name"],
                "distance_minutes": nearest_distance,
            },
        },
        interpretation_signals=[
            {
                "evidence": f"四柱为{'、'.join(primary['pillars'])}",
                "supports": "供日主、月令、十神与明确合冲结构分析",
                "does_not_support": "不能仅凭四柱保证具体事件或自动确定喜用神",
            },
            {
                "evidence": "边界候选与时间误差已按输入检查",
                "supports": "决定解读是否需要保留共同结论与差异点",
                "does_not_support": "不能把出生记录本身的不确定性包装成分钟级精确结论",
            },
        ],
        confidence_level=confidence_level,
        confidence_reasons=confidence_reasons,
    )
    return result


def main() -> None:
    # Windows pipes default to the ANSI code page; downstream tools read UTF-8.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--datetime", required=True, help="出生地当地 ISO 日期时间")
    parser.add_argument("--timezone", required=True, help="IANA 时区，例如 Asia/Shanghai")
    parser.add_argument("--longitude", type=float, help="出生地经度；东经为正、西经为负")
    parser.add_argument(
        "--clock-mode",
        choices=("true-solar", "legal"),
        default="true-solar",
    )
    parser.add_argument(
        "--day-boundary",
        choices=("zi-initial", "midnight"),
        default="zi-initial",
    )
    parser.add_argument("--sex", choices=("male", "female"))
    parser.add_argument("--direction", choices=("forward", "reverse"))
    parser.add_argument("--target-year", type=int)
    parser.add_argument("--target-date", help="需要分析的具体当地日期或ISO时间")
    parser.add_argument(
        "--uncertainty-minutes",
        type=float,
        default=0.0,
        help="出生时间可能误差的正负分钟数",
    )
    args = parser.parse_args()
    try:
        result = cast_birth_chart(
            args.datetime,
            args.timezone,
            args.longitude,
            args.clock_mode,
            args.day_boundary,
            args.sex,
            args.direction,
            args.target_year,
            args.target_date,
            args.uncertainty_minutes,
        )
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
