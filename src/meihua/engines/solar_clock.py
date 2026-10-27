#!/usr/bin/env python3
"""Local birth or question time, checked against its time zone, and true solar time.

The two helpers cast_ziwei and cast_qimen need, copied unchanged from the game edition's cast_bazi
(this edition has no 八字 engine): parse_local_datetime refuses a clock time that 夏令时 skipped or
made ambiguous, and an offset that was not the zone's at the time; apparent_solar_clock turns a
clock time into the birthplace's true solar time (longitude and the NOAA/Meeus equation of time).
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

UTC = timezone.utc


def normalize_angle(value: float) -> float:
    return value % 360.0


def julian_day(moment_utc: datetime) -> float:
    if moment_utc.tzinfo is None:
        raise ValueError("Julian day requires a timezone-aware datetime")
    return 2440587.5 + moment_utc.astimezone(UTC).timestamp() / 86400.0


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
