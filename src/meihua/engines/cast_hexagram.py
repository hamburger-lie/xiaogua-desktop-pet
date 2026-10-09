#!/usr/bin/env python3
"""Deterministic Meihua Yishu casting helper; outputs calculation facts as JSON."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import unicodedata
from datetime import datetime

from result_contract import calculation_record


TRIGRAMS = {
    1: {"name": "乾", "lines": (1, 1, 1), "element": "金", "direction": "西北"},
    2: {"name": "兑", "lines": (1, 1, 0), "element": "金", "direction": "西"},
    3: {"name": "离", "lines": (1, 0, 1), "element": "火", "direction": "南"},
    4: {"name": "震", "lines": (1, 0, 0), "element": "木", "direction": "东"},
    5: {"name": "巽", "lines": (0, 1, 1), "element": "木", "direction": "东南"},
    6: {"name": "坎", "lines": (0, 1, 0), "element": "水", "direction": "北"},
    7: {"name": "艮", "lines": (0, 0, 1), "element": "土", "direction": "东北"},
    8: {"name": "坤", "lines": (0, 0, 0), "element": "土", "direction": "西南"},
}
ALIASES = {v["name"]: k for k, v in TRIGRAMS.items()} | {"兌": 2, "離": 3}
LINE_TO_NUM = {v["lines"]: k for k, v in TRIGRAMS.items()}

HEXAGRAMS = {
    (1, 1): (1, "乾"), (8, 8): (2, "坤"), (6, 4): (3, "屯"), (7, 6): (4, "蒙"),
    (6, 1): (5, "需"), (1, 6): (6, "讼"), (8, 6): (7, "师"), (6, 8): (8, "比"),
    (5, 1): (9, "小畜"), (1, 2): (10, "履"), (8, 1): (11, "泰"), (1, 8): (12, "否"),
    (1, 3): (13, "同人"), (3, 1): (14, "大有"), (8, 7): (15, "谦"), (4, 8): (16, "豫"),
    (2, 4): (17, "随"), (7, 5): (18, "蛊"), (8, 2): (19, "临"), (5, 8): (20, "观"),
    (3, 4): (21, "噬嗑"), (7, 3): (22, "贲"), (7, 8): (23, "剥"), (8, 4): (24, "复"),
    (1, 4): (25, "无妄"), (7, 1): (26, "大畜"), (7, 4): (27, "颐"), (2, 5): (28, "大过"),
    (6, 6): (29, "坎"), (3, 3): (30, "离"), (2, 7): (31, "咸"), (4, 5): (32, "恒"),
    (1, 7): (33, "遁"), (4, 1): (34, "大壮"), (3, 8): (35, "晋"), (8, 3): (36, "明夷"),
    (5, 3): (37, "家人"), (3, 2): (38, "睽"), (6, 7): (39, "蹇"), (4, 6): (40, "解"),
    (7, 2): (41, "损"), (5, 4): (42, "益"), (2, 1): (43, "夬"), (1, 5): (44, "姤"),
    (2, 8): (45, "萃"), (8, 5): (46, "升"), (2, 6): (47, "困"), (6, 5): (48, "井"),
    (2, 3): (49, "革"), (3, 5): (50, "鼎"), (4, 4): (51, "震"), (7, 7): (52, "艮"),
    (5, 7): (53, "渐"), (4, 2): (54, "归妹"), (4, 3): (55, "丰"), (3, 7): (56, "旅"),
    (5, 5): (57, "巽"), (2, 2): (58, "兑"), (5, 6): (59, "涣"), (6, 2): (60, "节"),
    (5, 2): (61, "中孚"), (4, 7): (62, "小过"), (6, 3): (63, "既济"), (3, 6): (64, "未济"),
}
GENERATES = {"木": "火", "火": "土", "土": "金", "金": "水", "水": "木"}
CONTROLS = {"木": "土", "土": "水", "水": "火", "火": "金", "金": "木"}


def mod_index(value: int, base: int) -> int:
    remainder = abs(value) % base
    return base if remainder == 0 else remainder


def trigram_number(value: str | int) -> int:
    if str(value).lstrip("-").isdigit() and 1 <= int(value) <= 8:
        return int(value)
    if str(value) in ALIASES:
        return ALIASES[str(value)]
    raise ValueError(f"未知八卦：{value}")


def hour_branch(hour: int) -> int:
    if hour == 23 or hour == 0:
        return 1
    return (hour + 1) // 2 + 1


def relation(body: str, use: str) -> str:
    if body == use:
        return "体用比和"
    if GENERATES[use] == body:
        return "用生体"
    if GENERATES[body] == use:
        return "体生用"
    if CONTROLS[body] == use:
        return "体克用"
    return "用克体"


def trigram_payload(number: int) -> dict:
    return {"number": number, **TRIGRAMS[number]}


def normalize_personalization_text(value: str) -> str:
    """Normalize user-provided text without collecting hidden identifiers."""
    return " ".join(unicodedata.normalize("NFKC", value).strip().split())


# Only user-confirmed, coarse place facts may season the modern fingerprint.
# Precise coordinates, addresses and device identifiers stay out by design.
PLACE_FINGERPRINT_FIELDS = ("domain", "label", "map_id", "area", "position", "heading")


def place_fingerprint(place: dict) -> dict:
    """Reduce a reported place to the stable subset that may enter the digest.

    This is an explicitly modern convention. The classical year/month/day/hour
    formula never takes a place term, so traditional-time casting must not call
    this; see contracts/context-record.md.
    """
    if not isinstance(place, dict):
        raise ValueError("place 必须是对象")
    if place.get("domain") not in ("game", "real_world"):
        raise ValueError("place.domain 必须是 game 或 real_world")
    reduced = {}
    for key in PLACE_FINGERPRINT_FIELDS:
        value = place.get(key)
        if value is None:
            continue
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            reduced[key] = value
            continue
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"place.{key} 必须是非空字符串或数值")
        reduced[key] = normalize_personalization_text(value)
    if not reduced.get("label"):
        raise ValueError("place.label 必须提供用户已确认的地点名称")
    return reduced


def personalized_values(
    question: str,
    datetime_value: str,
    location: str,
    personal_seed: str | None = None,
    place: dict | None = None,
) -> tuple[int, int, int, dict]:
    """Derive reproducible casting values from explicit, non-sensitive context."""
    dt = datetime.fromisoformat(datetime_value)
    if dt.tzinfo is None:
        raise ValueError("个性化时间必须包含时区偏移，例如 +08:00")
    normalized_question = normalize_personalization_text(question)
    normalized_location = normalize_personalization_text(location)
    if not normalized_question:
        raise ValueError("具体问题不能为空")
    if not normalized_location:
        raise ValueError("城市或时区名称不能为空")
    payload = {
        "scheme": "daily-yigua-personalized-v1",
        "question": normalized_question,
        "datetime": dt.isoformat(),
        "location": normalized_location,
    }
    if place is not None:
        # A place term changes the digest, so the scheme label changes with it:
        # v1 and v2 casts stay independently reproducible and auditable.
        payload["scheme"] = "daily-yigua-personalized-v2"
        payload["place"] = place_fingerprint(place)
    if personal_seed is not None:
        normalized_seed = normalize_personalization_text(personal_seed)
        if normalized_seed:
            payload["personal_seed"] = normalized_seed
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).digest()
    upper_value = int.from_bytes(digest[0:8], "big")
    lower_value = int.from_bytes(digest[8:16], "big")
    moving_value = int.from_bytes(digest[16:24], "big")
    trace = {**payload, "fingerprint": digest.hex()[:16]}
    return upper_value, lower_value, moving_value, trace


def hex_payload(upper: int, lower: int) -> dict:
    number, name = HEXAGRAMS[(upper, lower)]
    return {"number": number, "name": name, "upper": trigram_payload(upper), "lower": trigram_payload(lower)}


def attach_calculation_record(result: dict) -> dict:
    key_structure = {
        "primary": result["primary"],
        "mutual": result["mutual"],
        "moving_line": result["moving_line"],
    }
    signals = [{
        "evidence": f"本卦{result['primary']['name']}、互卦{result['mutual']['name']}",
        "supports": "描述当前格局与中间过程的条件性假设",
        "does_not_support": "不能单独证明现实事件已经发生或必然发生",
    }]
    if result.get("changed"):
        key_structure.update({
            "changed": result["changed"],
            "body": result["body"],
            "use": result["use"],
            "body_use_relation": result["body_use_relation"],
        })
        signals.append({
            "evidence": (
                f"动爻第{result['moving_line']}爻；体用关系为"
                f"{result['body_use_relation']}；变卦{result['changed']['name']}"
            ),
            "supports": "判断主体与所问事项的相对支持、投入或阻力，以及趋势变化",
            "does_not_support": "不能直接推出成功、失败、分手、发财或精确应期",
        })
    trace = result.get("trace", {})
    modern = result["method"].startswith("现代")
    result["calculation_record"] = calculation_record(
        basis=result["method"],
        inputs=trace,
        adopted_school="每日一瓜梅花易数统一口径",
        key_structure=key_structure,
        time_information={
            "datetime": trace.get("datetime"),
            "location": trace.get("location"),
            # Present only when the user supplied a confirmed place that entered
            # the modern digest; absent for every classical mode.
            "place": trace.get("place"),
        },
        interpretation_signals=signals,
        confidence_level="B" if modern else "A",
        confidence_reasons=[
            "输出可由相同输入和同一取模规则复算",
            (
                "采用已明确标注的现代约定，不冒充原典公式"
                if modern else "采用已声明的传统或手动输入口径"
            ),
        ],
    )
    return result


def cast(upper_value: int, lower_value: int, moving_value: int | None, method: str, trace: dict) -> dict:
    upper = mod_index(upper_value, 8)
    lower = mod_index(lower_value, 8)
    moving = mod_index(moving_value, 6) if moving_value is not None else None
    lines = list(TRIGRAMS[lower]["lines"] + TRIGRAMS[upper]["lines"])
    mutual_lower = LINE_TO_NUM[tuple(lines[1:4])]
    mutual_upper = LINE_TO_NUM[tuple(lines[2:5])]
    if moving is None:
        return attach_calculation_record({
            "method": method, "trace": trace,
            "primary": hex_payload(upper, lower),
            "mutual": hex_payload(mutual_upper, mutual_lower),
            "moving_line": None,
            "line_order_note": "六爻均自下而上编号；静卦不生成变卦、体用或定位卦",
        })
    changed_lines = lines.copy()
    changed_lines[moving - 1] = 1 - changed_lines[moving - 1]
    changed_lower = LINE_TO_NUM[tuple(changed_lines[:3])]
    changed_upper = LINE_TO_NUM[tuple(changed_lines[3:])]

    if moving <= 3:
        body_num, use_num, locator_num = upper, lower, changed_lower
    else:
        body_num, use_num, locator_num = lower, upper, changed_upper
    body, use = TRIGRAMS[body_num], TRIGRAMS[use_num]
    return attach_calculation_record({
        "method": method,
        "trace": trace,
        "remainders": {"upper_mod_8": upper, "lower_mod_8": lower, "moving_mod_6": moving},
        "primary": hex_payload(upper, lower),
        "mutual": hex_payload(mutual_upper, mutual_lower),
        "changed": hex_payload(changed_upper, changed_lower),
        "moving_line": moving,
        "body": trigram_payload(body_num),
        "use": trigram_payload(use_num),
        "body_use_relation": relation(body["element"], use["element"]),
        "lost_item_locator": trigram_payload(locator_num),
        "line_order_note": "六爻均自下而上编号",
    })


def main() -> None:
    # Windows pipes default to the ANSI code page; downstream tools read UTF-8.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)
    p = sub.add_parser("numbers")
    p.add_argument("--numbers", nargs="+", type=int, required=True)
    p = sub.add_parser("traditional-time")
    p.add_argument("--year-branch", type=int, choices=range(1, 13), required=True)
    p.add_argument("--lunar-month", type=int, choices=range(1, 13), required=True)
    p.add_argument("--lunar-day", type=int, choices=range(1, 31), required=True)
    p.add_argument("--hour-branch", type=int, choices=range(1, 13), required=True)
    p = sub.add_parser("gregorian-time")
    p.add_argument("--datetime", required=True)
    p = sub.add_parser("personalized-time")
    p.add_argument("--question", required=True)
    p.add_argument("--datetime", required=True)
    p.add_argument("--location", required=True)
    p.add_argument("--personal-seed")
    p.add_argument("--place-file", help="用户已确认地点 JSON；提供后地点参与取数（现代约定，非原典）")
    p = sub.add_parser("manual")
    p.add_argument("--upper", required=True)
    p.add_argument("--lower", required=True)
    p.add_argument("--moving-line", type=int, choices=range(1, 7))

    args = parser.parse_args()
    if args.mode == "numbers":
        if len(args.numbers) not in (2, 3):
            parser.error("numbers 模式必须提供两个或三个数字")
        upper_value, lower_value = args.numbers[:2]
        moving_value = sum(abs(n) for n in args.numbers) if len(args.numbers) == 2 else abs(args.numbers[2])
        result = cast(upper_value, lower_value, moving_value, f"{len(args.numbers)}数法", {"numbers": args.numbers})
    elif args.mode == "traditional-time":
        upper_value = args.year_branch + args.lunar_month + args.lunar_day
        total = upper_value + args.hour_branch
        result = cast(upper_value, total, total, "传统农历年月日时法", vars(args))
    elif args.mode == "gregorian-time":
        dt = datetime.fromisoformat(args.datetime)
        if dt.tzinfo is None:
            parser.error("公历时间必须包含时区偏移，例如 +08:00")
        branch = hour_branch(dt.hour)
        upper_value = dt.year + dt.month + dt.day
        total = upper_value + branch
        result = cast(upper_value, total, total, "现代公历时间约定（非原典农历法）", {"datetime": dt.isoformat(), "hour_branch": branch, "minute_recorded_not_used": dt.minute})
    elif args.mode == "personalized-time":
        try:
            place = None
            if args.place_file:
                with open(args.place_file, encoding="utf-8-sig") as handle:
                    place = json.load(handle)
            upper_value, lower_value, moving_value, trace = personalized_values(
                args.question, args.datetime, args.location, args.personal_seed, place
            )
        except (ValueError, OSError) as exc:
            parser.error(str(exc))
        result = cast(
            upper_value,
            lower_value,
            moving_value,
            "现代问题指纹起卦（含地点项，非原典法）" if place else "现代问题指纹起卦（非原典法）",
            trace,
        )
    else:
        upper = trigram_number(args.upper)
        lower = trigram_number(args.lower)
        result = cast(upper, lower, args.moving_line, "手动卦象", vars(args))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
