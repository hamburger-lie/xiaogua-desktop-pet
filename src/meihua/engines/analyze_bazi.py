#!/usr/bin/env python3
"""Deterministic structural analysis for validated Four Pillars (BaZi)."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter

from result_contract import calculation_record


STEM_ORDER = "甲乙丙丁戊己庚辛壬癸"
BRANCH_ORDER = "子丑寅卯辰巳午未申酉戌亥"
ELEMENTS = ("木", "火", "土", "金", "水")

STEMS = {
    "甲": {"element": "木", "yin_yang": "阳"},
    "乙": {"element": "木", "yin_yang": "阴"},
    "丙": {"element": "火", "yin_yang": "阳"},
    "丁": {"element": "火", "yin_yang": "阴"},
    "戊": {"element": "土", "yin_yang": "阳"},
    "己": {"element": "土", "yin_yang": "阴"},
    "庚": {"element": "金", "yin_yang": "阳"},
    "辛": {"element": "金", "yin_yang": "阴"},
    "壬": {"element": "水", "yin_yang": "阳"},
    "癸": {"element": "水", "yin_yang": "阴"},
}

BRANCHES = {
    "子": {"element": "水", "hidden_stems": ("癸",)},
    "丑": {"element": "土", "hidden_stems": ("己", "癸", "辛")},
    "寅": {"element": "木", "hidden_stems": ("甲", "丙", "戊")},
    "卯": {"element": "木", "hidden_stems": ("乙",)},
    "辰": {"element": "土", "hidden_stems": ("戊", "乙", "癸")},
    "巳": {"element": "火", "hidden_stems": ("丙", "戊", "庚")},
    "午": {"element": "火", "hidden_stems": ("丁", "己")},
    "未": {"element": "土", "hidden_stems": ("己", "丁", "乙")},
    "申": {"element": "金", "hidden_stems": ("庚", "壬", "戊")},
    "酉": {"element": "金", "hidden_stems": ("辛",)},
    "戌": {"element": "土", "hidden_stems": ("戊", "辛", "丁")},
    "亥": {"element": "水", "hidden_stems": ("壬", "甲")},
}

GENERATES = {"木": "火", "火": "土", "土": "金", "金": "水", "水": "木"}
CONTROLS = {"木": "土", "土": "水", "水": "火", "火": "金", "金": "木"}

STEM_COMBINATIONS = (("甲", "己"), ("乙", "庚"), ("丙", "辛"), ("丁", "壬"), ("戊", "癸"))
BRANCH_COMBINATIONS = (("子", "丑"), ("寅", "亥"), ("卯", "戌"), ("辰", "酉"), ("巳", "申"), ("午", "未"))
BRANCH_CLASHES = (("子", "午"), ("丑", "未"), ("寅", "申"), ("卯", "酉"), ("辰", "戌"), ("巳", "亥"))
THREE_HARMONIES = {
    ("申", "子", "辰"): "水",
    ("亥", "卯", "未"): "木",
    ("寅", "午", "戌"): "火",
    ("巳", "酉", "丑"): "金",
}

PILLAR_NAMES = ("年柱", "月柱", "日柱", "时柱")
VALID_JIAZI = {
    STEM_ORDER[index % len(STEM_ORDER)] + BRANCH_ORDER[index % len(BRANCH_ORDER)]
    for index in range(60)
}


def validate_pillar(value: str) -> str:
    pillar = value.strip()
    if len(pillar) != 2 or pillar[0] not in STEMS or pillar[1] not in BRANCHES:
        raise ValueError(f"无效干支柱：{value}；应为两个汉字，例如甲子")
    if pillar not in VALID_JIAZI:
        raise ValueError(f"无效六十甲子组合：{pillar}")
    return pillar


def ten_god(day_stem: str, target_stem: str) -> str:
    day = STEMS[day_stem]
    target = STEMS[target_stem]
    same_polarity = day["yin_yang"] == target["yin_yang"]
    day_element = day["element"]
    target_element = target["element"]

    if day_element == target_element:
        return "比肩" if same_polarity else "劫财"
    if GENERATES[day_element] == target_element:
        return "食神" if same_polarity else "伤官"
    if CONTROLS[day_element] == target_element:
        return "偏财" if same_polarity else "正财"
    if CONTROLS[target_element] == day_element:
        return "七杀" if same_polarity else "正官"
    if GENERATES[target_element] == day_element:
        return "偏印" if same_polarity else "正印"
    raise AssertionError("unreachable element relationship")


def relation_to_day_master(day_element: str, target_element: str) -> str:
    if target_element == day_element:
        return "同类"
    if GENERATES[target_element] == day_element:
        return "生助日主"
    if GENERATES[day_element] == target_element:
        return "日主所生"
    if CONTROLS[target_element] == day_element:
        return "克制日主"
    return "日主所克"


def located_pairs(values: dict[str, str], pairs: tuple[tuple[str, str], ...]) -> list[dict]:
    results = []
    for left, right in pairs:
        left_positions = [position for position, value in values.items() if value == left]
        right_positions = [position for position, value in values.items() if value == right]
        if left_positions and right_positions:
            results.append({
                "pair": left + right,
                "positions": {left: left_positions, right: right_positions},
            })
    return results


def element_counts(values: list[str]) -> dict[str, int]:
    counts = Counter(values)
    return {element: counts[element] for element in ELEMENTS}


def analyze(pillars: list[str]) -> dict:
    if len(pillars) != 4:
        raise ValueError("必须按年、月、日、时提供四柱")
    normalized = [validate_pillar(value) for value in pillars]
    pillar_map = dict(zip(PILLAR_NAMES, normalized, strict=True))
    stems_by_pillar = {name: pillar[0] for name, pillar in pillar_map.items()}
    branches_by_pillar = {name: pillar[1] for name, pillar in pillar_map.items()}

    day_stem = stems_by_pillar["日柱"]
    day_master = {"stem": day_stem, **STEMS[day_stem]}

    visible_stems = []
    for name in PILLAR_NAMES:
        stem = stems_by_pillar[name]
        visible_stems.append({
            "pillar": name,
            "stem": stem,
            **STEMS[stem],
            "role": "日主" if name == "日柱" else ten_god(day_stem, stem),
        })

    branch_details = []
    for name in PILLAR_NAMES:
        branch = branches_by_pillar[name]
        branch_info = BRANCHES[branch]
        hidden = [
            {"stem": stem, **STEMS[stem], "ten_god": ten_god(day_stem, stem)}
            for stem in branch_info["hidden_stems"]
        ]
        branch_details.append({
            "pillar": name,
            "branch": branch,
            "main_element": branch_info["element"],
            "hidden_stems": hidden,
        })

    month_branch = branches_by_pillar["月柱"]
    month_info = BRANCHES[month_branch]
    month_primary_stem = month_info["hidden_stems"][0]

    root_locations = []
    for name, branch in branches_by_pillar.items():
        matching = [
            stem
            for stem in BRANCHES[branch]["hidden_stems"]
            if STEMS[stem]["element"] == day_master["element"]
        ]
        if matching:
            root_locations.append({
                "pillar": name,
                "branch": branch,
                "same_element_hidden_stems": matching,
            })

    surface_elements = [STEMS[stem]["element"] for stem in stems_by_pillar.values()]
    surface_elements.extend(BRANCHES[branch]["element"] for branch in branches_by_pillar.values())
    hidden_elements = [
        STEMS[stem]["element"]
        for branch in branches_by_pillar.values()
        for stem in BRANCHES[branch]["hidden_stems"]
    ]

    stem_combinations = located_pairs(stems_by_pillar, STEM_COMBINATIONS)
    branch_combinations = located_pairs(branches_by_pillar, BRANCH_COMBINATIONS)
    branch_clashes = located_pairs(branches_by_pillar, BRANCH_CLASHES)
    branch_set = set(branches_by_pillar.values())
    three_harmonies = [
        {"branches": "".join(group), "result_element": element}
        for group, element in THREE_HARMONIES.items()
        if set(group).issubset(branch_set)
    ]

    result = {
        "method": "子平四柱结构分析",
        "input": pillar_map,
        "day_master": day_master,
        "month_command": {
            "branch": month_branch,
            "main_element": month_info["element"],
            "hidden_stems": list(month_info["hidden_stems"]),
            "primary_hidden_stem": month_primary_stem,
            "primary_ten_god": ten_god(day_stem, month_primary_stem),
            "relation_to_day_master": relation_to_day_master(
                day_master["element"], month_info["element"]
            ),
        },
        "day_master_roots": {
            "locations": root_locations,
            "note": "只报告日主同五行是否见于地支藏干；不据根数直接判旺衰。",
        },
        "visible_stems": visible_stems,
        "branches": branch_details,
        "element_distribution": {
            "surface_eight_symbols": element_counts(surface_elements),
            "hidden_stems_unweighted": element_counts(hidden_elements),
            "note": "仅作透明结构统计；不据数量直接判旺衰、缺什么补什么或自动取用神。",
        },
        "structural_relations": {
            "stem_combinations": stem_combinations,
            "branch_six_combinations": branch_combinations,
            "branch_six_clashes": branch_clashes,
            "branch_three_harmonies": three_harmonies,
            "note": "只报告结构是否出现；合不等于必化，冲不等于必凶。",
        },
        "boundaries": [
            "本结果假定输入四柱已完成历法校验；若由出生时间排盘，应先运行 engines/cast_bazi.py。",
            "本结果不自动判定日主强弱、格局、喜忌或用神。",
            "大运和流年只可作为另行计算的结构背景，不能据此确定预测具体事件。",
        ],
    }
    relation_count = (
        len(stem_combinations)
        + len(branch_combinations)
        + len(branch_clashes)
        + len(three_harmonies)
    )
    result["calculation_record"] = calculation_record(
        basis=result["method"],
        inputs=pillar_map,
        adopted_school="子平四柱结构分析；不自动定格局、旺衰、喜忌或用神",
        key_structure={
            "pillars": normalized,
            "day_master": day_master,
            "month_command": result["month_command"],
            "structural_relation_count": relation_count,
        },
        time_information={"source": "输入四柱；历法边界须由排盘引擎另行校验"},
        interpretation_signals=[
            {
                "evidence": f"日主{day_stem}，月令{month_branch}",
                "supports": "分析季节背景及日主与月令的结构关系",
                "does_not_support": "不能只凭月令或五行数量自动判旺衰、用神或命运好坏",
            },
            {
                "evidence": f"已识别{relation_count}组明确合冲或三合结构",
                "supports": "提示需要协调、绑定或存在节奏张力的位置",
                "does_not_support": "合不等于必化，冲不等于必凶，也不等于具体事件必然发生",
            },
        ],
        confidence_level="B",
        confidence_reasons=[
            "四柱均已通过六十甲子组合校验",
            "输入未携带出生历法与边界记录，因此结构可复算但排盘来源需另行确认",
        ],
    )
    return result


def main() -> None:
    # Windows pipes default to the ANSI code page; downstream tools read UTF-8.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--pillars",
        nargs=4,
        required=True,
        metavar=("YEAR", "MONTH", "DAY", "HOUR"),
        help="按年柱、月柱、日柱、时柱提供，例如：甲子 丙寅 戊辰 庚申",
    )
    args = parser.parse_args()
    try:
        result = analyze(args.pillars)
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
