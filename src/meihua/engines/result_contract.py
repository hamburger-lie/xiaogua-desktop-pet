#!/usr/bin/env python3
"""Shared output contract for Daily Yigua calculation engines."""

from __future__ import annotations


REQUIRED_FIELDS = (
    "basis",
    "inputs",
    "adopted_school",
    "key_structure",
    "time_information",
    "interpretation_signals",
    "calculation_confidence",
)
CONFIDENCE_LEVELS = {"A", "B", "C"}


def calculation_record(
    *,
    basis: str,
    inputs: dict,
    adopted_school: str,
    key_structure: dict,
    time_information: dict,
    interpretation_signals: list[dict],
    confidence_level: str,
    confidence_reasons: list[str],
) -> dict:
    """Build a validated facts-only record; it must not contain a final reading."""
    if confidence_level not in CONFIDENCE_LEVELS:
        raise ValueError(f"未知计算置信级别：{confidence_level}")
    record = {
        "contract_version": "daily-yigua-calculation-v1",
        "basis": basis,
        "inputs": inputs,
        "adopted_school": adopted_school,
        "key_structure": key_structure,
        "time_information": time_information,
        "interpretation_signals": interpretation_signals,
        "calculation_confidence": {
            "level": confidence_level,
            "scope": "仅表示输入完整度与既定算法的可复算性，不表示预测准确率",
            "reasons": confidence_reasons,
        },
        "predictive_validity": "传统文化解释框架；不视为已证实的客观预测方法",
    }
    validate_calculation_record(record)
    return record


def validate_calculation_record(record: dict) -> None:
    missing = [field for field in REQUIRED_FIELDS if field not in record]
    if missing:
        raise ValueError(f"统一计算记录缺少字段：{', '.join(missing)}")
    confidence = record["calculation_confidence"]
    if confidence.get("level") not in CONFIDENCE_LEVELS:
        raise ValueError("统一计算记录的置信级别必须为 A、B 或 C")
    for signal in record["interpretation_signals"]:
        required = {"evidence", "supports", "does_not_support"}
        if not required.issubset(signal):
            raise ValueError("每个解读信号必须声明证据、可支持结论和不可推出结论")
