#!/usr/bin/env python3
"""Deterministic routing, not calculation or interpretation.

Policy: method-routing.md. Engineering source: routing-sources.md, ROUTE-L1.
Natural-language extraction is deliberately bounded; JSON is the integration API.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import math
from pathlib import Path
import re
import sys
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ROOT = Path(__file__).resolve().parents[1]
ALIASES = {
    "meihua": ("梅花易数", "梅花"),
    "xiaoliu-ren": ("小六壬",),
    "bazi": ("八字", "四柱"),
    "space-observation": ("空间观察", "环境观察"),
    "qimen": ("奇门遁甲", "奇门"),
    "feixing": ("九宫飞星", "玄空飞星", "飞星"),
    "liuyao": ("六爻纳甲", "六爻"),
    "ziwei": ("紫微斗数", "紫微"),
}
# 紫微 and 奇门 since 2026-10-27, explicit requests only (evidence/method-admission.md).
ADMITTED = {"meihua", "xiaoliu-ren", "bazi", "space-observation", "ziwei", "qimen"}
BRANCHES = "子丑寅卯辰巳午未申酉戌亥"
TRIGRAMS = "乾兑离震巽坎艮坤"
PILLARS = {"甲乙丙丁戊己庚辛壬癸"[i % 10] + BRANCHES[i % 12] for i in range(60)}
SENSITIVE = {"ip", "phone", "phone_number", "account_id", "device_id", "coordinates", "precise_location"}
INPUT_FIELDS = {
    "numbers", "upper", "lower", "moving_line", "year_branch", "lunar_month", "lunar_day",
    "hour_branch", "leap_month", "datetime", "location", "timezone", "pillars",
    "birth_datetime", "birth_timezone", "longitude", "sex", "direction", "target_year", "target_date",
}
REQUEST_FIELDS = {"question", "requested_method", "inputs", "meihua_mode", "calendar_available", "accept_brief"}
MODES = {"numbers", "manual", "traditional-time", "gregorian-time", "personalized-time"}
NEGATION = re.compile(r"(?:不要|不用|别用|不使用|不选|不按|不想用|无需|不是|而非)(?:再|使用|用|按)?\s*$")


def has(text: str, pattern: str) -> bool:
    return bool(re.search(pattern, text))


def mentioned_methods(text: str) -> tuple[list[str], set[str]]:
    selected, excluded = [], set()
    for method, aliases in ALIASES.items():
        pattern = "|".join(map(re.escape, sorted(aliases, key=len, reverse=True)))
        for match in re.finditer(pattern, text):
            before = text[max(0, match.start() - 12):match.start()]
            if NEGATION.search(before):
                excluded.add(method)
                continue
            # Supplied pillars/birth background is not a request to use bazi.
            if method == "bazi":
                following = text[match.end():match.end() + 8]
                directive = has(before, r"(?:用|按|排|算|看|分析|指定|选择|以)(?:完整|我的|一下|出生信息排)?\s*$")
                if not directive and not has(following, r"^(?:分析|排盘|看看|看|来分析)"):
                    continue
            if method not in selected:
                selected.append(method)
    return selected, excluded


def chinese_number(value: str) -> int:
    if value.isdigit():
        return int(value)
    value = value.replace("初", "").replace("正", "一").replace("冬", "十一").replace("腊", "十二")
    value = value.replace("廿", "二十").replace("卅", "三十")
    digits = {c: n for n, c in enumerate("零一二三四五六七八九")}
    if "十" in value:
        left, right = value.split("十", 1)
        return digits.get(left, 1) * 10 + digits.get(right, 0)
    return digits[value]


def extract_inputs(text: str) -> dict:
    """Only explicit numeric casts, trigrams, four pillars, and lunar triples.

    Dates, cities, birth context and user consent are not fabricated by this adapter.
    """
    data = {}
    number_run = re.search(r"(?:^|用|数字[是为：:]?|报数[是为：:]?)\s*(-?\d+(?:[ 、,，]+-?\d+)+)(?=$|[\s,，。;；]|起|看)", text)
    if number_run:
        data["numbers"] = [int(n) for n in re.findall(r"-?\d+", number_run[1])]
    for label, key in (("上卦", "upper"), ("下卦", "lower")):
        match = re.search(label + r"\s*([乾兑离震巽坎艮坤1-8])", text)
        if match:
            data[key] = match[1]
    moving = re.search(r"动爻(?:为|是|第)?\s*([一二三四五六1-6])", text)
    if moving:
        data["moving_line"] = chinese_number(moving[1])
    pillars = re.findall(r"[甲乙丙丁戊己庚辛壬癸][子丑寅卯辰巳午未申酉戌亥]", text)
    if len(pillars) == 4:
        data["pillars"] = pillars
    lunar = re.search(r"农历\s*([\d一二三四五六七八九十正冬腊]+)月\s*([\d初一二三四五六七八九十廿卅]+)(?:日|号)?\s*([子丑寅卯辰巳午未申酉戌亥])时", text)
    if lunar:
        data.update(lunar_month=chinese_number(lunar[1]), lunar_day=chinese_number(lunar[2]), hour_branch=lunar[3])
    return data


def result(method, status, rule, *, mode=None, inputs=None, missing=None, warnings=None, errors=None, engine=None):
    sources = ["router/method-routing.md#决策顺序", "router/routing-sources.md"]
    if status == "BLOCKED":
        sources.append("evidence/method-admission.md" if method not in ADMITTED else "SKILL.md#先确定输入")
    return {
        "schema_version": "daily-yigua-route-v1",
        "method": method, "mode": mode, "status": status,
        "accept": method in ADMITTED and status in {"READY", "NEEDS_INPUT"},
        "rule_id": rule, "policy_sources": sources, "literature_sources": ["ROUTE-L1"],
        "normalized_inputs": inputs or {}, "missing_inputs": missing or [],
        "warnings": warnings or [], "errors": errors or [],
        "engine": engine if status == "READY" else None,
    }


def validate_inputs(data: dict) -> list[str]:
    errors = [f"unknown_input:{key}" for key in sorted(data.keys() - INPUT_FIELDS, key=str)]
    for key in ("lunar_month", "lunar_day", "year_branch", "moving_line"):
        limit = {"lunar_month": 12, "lunar_day": 30, "year_branch": 12, "moving_line": 6}[key]
        if key in data and (type(data[key]) is not int or not 1 <= data[key] <= limit):
            errors.append(f"invalid:{key}")
    if "hour_branch" in data:
        value = data["hour_branch"]
        if not (type(value) is int and 1 <= value <= 12 or isinstance(value, str) and value in list(BRANCHES)):
            errors.append("invalid:hour_branch")
    for key in ("upper", "lower"):
        if key in data and str(data[key]) not in list(TRIGRAMS) + list("12345678"):
            errors.append(f"invalid:{key}")
    if "numbers" in data:
        values = data["numbers"]
        if not isinstance(values, list) or len(values) not in (2, 3) or any(type(v) is not int for v in values):
            errors.append("invalid:numbers")
    if "pillars" in data:
        values = data["pillars"]
        if not isinstance(values, list) or len(values) != 4 or any(not isinstance(v, str) or v not in PILLARS for v in values):
            errors.append("invalid:pillars")
    for key in ("datetime", "birth_datetime"):
        if key not in data:
            continue
        try:
            value = data[key]
            if not isinstance(value, str) or not re.match(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}", value):
                raise ValueError()
            parsed = datetime.fromisoformat(value)
            if key == "datetime" and parsed.utcoffset() is None:
                raise ValueError()
        except (ValueError, TypeError):
            errors.append(f"invalid:{key}")
    for key in ("timezone", "birth_timezone"):
        if key in data:
            try:
                if not isinstance(data[key], str):
                    raise ValueError()
                ZoneInfo(data[key])
            except (ValueError, ZoneInfoNotFoundError):
                errors.append(f"invalid:{key}")
    if "location" in data and (not isinstance(data["location"], str) or not data["location"].strip()):
        errors.append("invalid:location")
    if "longitude" in data and (type(data["longitude"]) not in (int, float) or not -180 <= data["longitude"] <= 180 or not math.isfinite(data["longitude"])):
        errors.append("invalid:longitude")
    for key, allowed in (("sex", ("male", "female")), ("direction", ("forward", "reverse"))):
        if key in data and data[key] not in allowed:
            errors.append(f"invalid:{key}")
    if "leap_month" in data and type(data["leap_month"]) is not bool:
        errors.append("invalid:leap_month")
    if "target_year" in data and (type(data["target_year"]) is not int or not 1 <= data["target_year"] <= 9999):
        errors.append("invalid:target_year")
    if "target_date" in data:
        try:
            datetime.fromisoformat(data["target_date"])
        except (TypeError, ValueError):
            errors.append("invalid:target_date")
    if "target_date" in data and "target_year" in data:
        errors.append("conflict:target_date,target_year")
    return errors


def route(request) -> dict:
    if isinstance(request, str):
        request = {"question": request}
    if not isinstance(request, dict) or not isinstance(request.get("question"), str) or not request["question"].strip():
        return result(None, "INVALID_INPUT", "ROUTE-INPUT", errors=["question_required"])
    unknown = request.keys() - REQUEST_FIELDS
    if unknown:
        return result(None, "INVALID_INPUT", "ROUTE-INPUT", errors=[f"unknown_field:{key}" for key in sorted(unknown, key=str)])
    text = request["question"].strip()
    supplied = request.get("inputs", {})
    if not isinstance(supplied, dict):
        return result(None, "INVALID_INPUT", "ROUTE-INPUT", errors=["inputs_must_be_object"])
    requested = request.get("requested_method")
    if requested is not None and (not isinstance(requested, str) or requested not in ALIASES):
        return result(None, "INVALID_INPUT", "ROUTE-INPUT", errors=["unknown_requested_method"])
    mode_request = request.get("meihua_mode")
    if mode_request is not None and (not isinstance(mode_request, str) or mode_request not in MODES):
        return result(None, "INVALID_INPUT", "ROUTE-INPUT", errors=["unknown_meihua_mode"])
    for flag in ("calendar_available", "accept_brief"):
        if flag in request and type(request[flag]) is not bool:
            return result(None, "INVALID_INPUT", "ROUTE-INPUT", errors=[f"invalid:{flag}"])
    if any(str(key).lower() in SENSITIVE for key in supplied) or has(text, r"(?i)(?:用|根据|按).{0,16}(?:\bIP\b|手机号|账号ID|设备号|设备ID|精确坐标).{0,16}(?:起|专属|算|卦)"):
        return result(requested or "meihua", "BLOCKED", "ROUTE-PRIVACY", warnings=["sensitive_seed_forbidden"])
    extracted = extract_inputs(text)
    conflicts = [key for key in extracted.keys() & supplied.keys() if extracted[key] != supplied[key]]
    if conflicts:
        return result(None, "NEEDS_INPUT", "ROUTE-CONFLICT", missing=[f"confirm:{key}" for key in sorted(conflicts)])
    data = {**extracted, **supplied}
    errors = validate_inputs(data)
    if errors:
        return result(None, "INVALID_INPUT", "ROUTE-INPUT", errors=errors)
    explicit, excluded = mentioned_methods(text)
    if requested and requested not in explicit:
        explicit.append(requested)
    if has(text, r"(?:差异|区别|比较|对比|有什么不同)") and has(text, r"(?:算法|方法|体系|区别)") and not has(text, r"(?:都算|起卦|排盘|起局|复核|验证结果)"):
        return result(None, "COMPARE", "ROUTE-COMPARE", warnings=["comparison_only_no_calculation"])
    if len(explicit) > 1 or any(method in excluded for method in explicit):
        return result(None, "NEEDS_INPUT", "ROUTE-CONFLICT", missing=["single_method_confirmation"], warnings=["no_cross_system_recheck"])
    immediate = has(text, r"找物|找钥匙|找东西|丢失|丢了|眼前|今天|现在|马上|何时|什么时候|这件事")
    long_term = has(text, r"长期|事业结构|事业方式|能力结构|关系模式|资源压力|阶段变化|大运|流年|性格|天赋|"
                          r"适合(?:做|干)?什么(?:工作|行业|职业)|适合(?:做|干)(?:什么|啥)|哪一?行|职业方向|这辈子|一辈子|"
                          r"今年运势|这几年|未来几年|运程|以后|将来|财运|婚姻|姻缘|算命|看命|命(?:运|格|好不好|怎么样)|事业(?:能|运)")
    # 「1995年5月12日出生」「95年5月12号生的」「九七年三月生的」「1993.8.20晚上8点生的」「生日是2001年3月3号」
    birth_present = "birth_datetime" in data or has(text, r"出生.{0,8}\d{4}|\d{4}\s*年.{0,16}(?:出生|生的|生人)|"
                                                          r"(?<!\d)\d{2}\s*年\s*\d{1,2}\s*月.{0,16}(?:出生|生)|"
                                                          r"[〇零一二三四五六七八九]{2,4}\s*年.{0,16}(?:出生|生的|生人)|"
                                                          r"生日.{0,6}\d{4}|\d{4}[-/.]\d{1,2}[-/.]\d{1,2}.{0,10}(?:出生|生)")
    personalized = has(text, r"本人专属|同一时辰|每人不同|问题指纹|结合本人")
    deep = has(text, r"找物|找钥匙|找东西|丢失|丢了|方向|环境特征|过程|变化|原因|阻力|长期|三个月|关系互动|详细|行动方案|怎么推进")
    short = has(text, r"今天|现在|马上|快速|短期")
    lunar_complete = all(key in data for key in ("lunar_month", "lunar_day", "hour_branch"))
    if explicit:
        method, rule = explicit[0], "ROUTE-EXPLICIT"
    elif has(text, r"风水|户型|采光|通风|动线|空间环境"):
        method, rule = "space-observation", "ROUTE-SPACE"
    elif ("pillars" in data or birth_present) and long_term and not immediate:
        method, rule = "bazi", "ROUTE-BIRTH"
    elif any(key in data for key in ("upper", "lower", "moving_line", "numbers")):
        method, rule = "meihua", "ROUTE-STRUCTURED"
    elif lunar_complete and short and not mode_request:
        method, rule = "xiaoliu-ren", "ROUTE-LUNAR"
    elif personalized or deep or mode_request:
        method, rule = "meihua", "ROUTE-DEPTH"
    elif short and (lunar_complete or request.get("accept_brief") or has(text, r"快速|六宫|简断")):
        method, rule = "xiaoliu-ren", "ROUTE-SHORT"
    else:
        method, rule = "meihua", "ROUTE-DEFAULT"
    if method in excluded:
        return result(None, "NEEDS_INPUT", "ROUTE-CONFLICT", missing=["single_method_confirmation"])
    if method not in ADMITTED:
        return result(method, "BLOCKED", "ROUTE-ADMISSION", warnings=["unadmitted_system"])
    if mode_request and method != "meihua":
        return result(None, "NEEDS_INPUT", "ROUTE-CONFLICT", missing=["method_mode_confirmation"])
    missing, warnings = [], []
    if method == "space-observation":
        return result(method, "READY", rule, mode="observation", warnings=["observations_require_user_facts_no_chart"])
    if method == "meihua":
        mode = mode_request or (
            "traditional-time" if has(text, r"传统.*(?:时间|年月日时|起卦)") else
            "manual" if any(key in data for key in ("upper", "lower", "moving_line")) else
            "numbers" if "numbers" in data else "personalized-time")
        required = {"manual": ["upper", "lower"], "numbers": ["numbers"],
                    "traditional-time": ["year_branch", "lunar_month", "lunar_day", "hour_branch"],
                    "gregorian-time": ["datetime"], "personalized-time": ["datetime", "location"]}[mode]
        engine = "engines/cast_hexagram.py"
        if mode == "personalized-time":
            warnings.append("modern_convention_not_classical_formula")
            if "datetime" in data and not re.match(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}", data["datetime"]):
                missing.append("datetime_with_seconds")
        if mode == "gregorian-time":
            warnings.append("modern_gregorian_convention_not_classical_formula")
    elif method == "xiaoliu-ren":
        if lunar_complete or any(key in data for key in ("lunar_month", "lunar_day", "hour_branch")):
            mode, required = "lunar", ["lunar_month", "lunar_day", "hour_branch"]
        elif request.get("calendar_available") is False or "datetime" not in data:
            mode, required = "lunar", ["lunar_month", "lunar_day", "hour_branch"]
        else:
            mode, required = "gregorian", ["datetime", "timezone"]
        if request.get("calendar_available") is False and not lunar_complete:
            warnings.append("calendar_unavailable")
        if mode == "lunar" and not lunar_complete and request.get("calendar_available") is not False:
            warnings.append("alternative_input:datetime+timezone")
        warnings.append("xiaoliu_1936_witness_supported_calendar_boundaries_are_project_conventions")
        engine = "engines/cast_xiaoliu_ren.py"
    elif method == "ziwei":
        mode, required = "natal", ["birth_datetime", "birth_timezone", "sex"]
        engine = "engines/cast_ziwei.py"
        if "longitude" not in data:
            warnings.append("clock_time_used_longitude_gives_true_solar_time")
        warnings.append("candidate_chart_at_late_zi_and_first_half_of_leap_month")
    elif method == "qimen":
        mode, required = "shijia-zhuanpan-chaibu", ["datetime", "timezone"]
        engine = "engines/cast_qimen.py"
        warnings.append("candidate_chart_at_23h_and_within_3_minutes_of_a_term")
    else:
        luck = has(text, r"大运|阶段变化")
        flow = has(text, r"流年")
        mode = "pillars" if "pillars" in data and not luck and not flow else "birth"
        required = ["pillars"] if mode == "pillars" else ["birth_datetime", "birth_timezone", "longitude"]
        engine = "engines/analyze_bazi.py" if mode == "pillars" else "engines/cast_bazi.py"
        if luck and not any(key in data for key in ("direction", "sex")):
            missing.append("direction_or_sex")
        if flow and not any(key in data for key in ("target_year", "target_date")):
            missing.append("target_year_or_date")
        if mode == "birth":
            warnings.append("engine_must_validate_time_boundaries")
    missing.extend(key for key in required if key not in data)
    return result(method, "NEEDS_INPUT" if missing else "READY", rule, mode=mode, inputs={**data, "question": text},
                  missing=missing, warnings=warnings, engine=engine)


def main() -> int:
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8-sig")
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--file", help="UTF-8 JSON request file")
    source.add_argument("--json", help="Inline JSON request")
    source.add_argument("--text", help="Limited natural-language adapter")
    args = parser.parse_args()
    try:
        if args.text is not None:
            payload = args.text
        elif args.file:
            payload = json.loads(Path(args.file).read_text(encoding="utf-8-sig"))
        elif args.json is not None:
            payload = json.loads(args.json)
        else:
            payload = json.load(sys.stdin)
        output = route(payload)
    except (ValueError, OSError, UnicodeError):
        output = result(None, "INVALID_INPUT", "ROUTE-INPUT", errors=["invalid_json_or_unreadable_file"])
    # Windows stdout redirected to pipes must remain UTF-8 JSON.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 2 if output["status"] == "INVALID_INPUT" else 0


if __name__ == "__main__":
    raise SystemExit(main())
