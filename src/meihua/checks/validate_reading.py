#!/usr/bin/env python3
"""Executable evidence gate for reading_record objects.

Literature basis (see references/research-summary.md):
- [P9] Toulmin (1958): claims require supporting data/warrants.
- [P10] Dhuliawala et al. (2024): draft then verify before final output.
- [P1][P4][P5][P6][P8]: uncertainty coping, Barnum, illusion of control,
  illusory patterns, and high-risk action checks.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

METHOD_PREFIXES = {
    "meihua": {"MH"},
    "xiaoliu-ren": {"XL"},
    "bazi": {"BZ"},
    "space-observation": set(),
}

PROTOCOL_PREFIXES = {
    "REL",
    "WORK",
    "COOP",
    "MONEY",
    "FIND",
    "TIME",
    "SPACE",
    "GUARD",
}

SPACE_ALLOWED_PREFIXES = {"SPACE", "FIND", "TIME", "GUARD"}

FORBIDDEN_PHRASES = (
    "必然",
    "注定",
    "百分百",
    "逃不过",
    "两个体系都证明",
    "肯定发财",
    "一定复合",
    "一定成功",
    "对方一定背叛",
    "必赚",
    "保证收益",
)

HIGH_RISK_TOPICS = (
    "医疗",
    "疾病",
    "法律",
    "诉讼",
    "投资",
    "股票",
    "证券",
    "博彩",
    "赌博",
    "人身安全",
    "生死",
    "寿命",
    "生育",
    "怀孕",
    "犯罪",
    "偷窃指控",
    "伴侣忠诚",
    "出轨",
)

UNADMITTED_MARKERS = (
    "奇门盘",
    "值符",
    "值使",
    "飞星盘",
    "玄空飞星",
    "纳甲",
    "世爻",
    "应爻",
    "紫微命盘",
    "十四主星",
)

EVIDENCE_ID_RE = re.compile(r"\b([A-Z]+-\d+)\b")
HEADING_ID_RE = re.compile(r"^#{1,6}\s+([A-Z]+-\d+)\b", re.MULTILINE)


def load_registry() -> dict[str, set[str]]:
    files = [
        ROOT / "evidence" / "meihua.md",
        ROOT / "evidence" / "xiaoliu-ren.md",
        ROOT / "evidence" / "bazi.md",
        ROOT / "protocols" / "relationships.md",
        ROOT / "protocols" / "work-money.md",
        ROOT / "protocols" / "action-space.md",
        ROOT / "checks" / "guardrails.md",
    ]
    by_prefix: dict[str, set[str]] = {}
    for path in files:
        text = path.read_text(encoding="utf-8")
        for match in HEADING_ID_RE.finditer(text):
            evidence_id = match.group(1)
            prefix = evidence_id.split("-", 1)[0]
            by_prefix.setdefault(prefix, set()).add(evidence_id)
    required = {
        "MH": {"MH-01", "MH-02", "MH-03", "MH-04", "MH-05", "MH-06", "MH-07"},
        "XL": {"XL-01", "XL-02", "XL-03"},
        "BZ": {"BZ-01", "BZ-02", "BZ-03", "BZ-04", "BZ-05"},
        "REL": {"REL-01", "REL-02", "REL-03", "REL-04", "REL-05"},
        "WORK": {"WORK-01"},
        "COOP": {"COOP-01"},
        "MONEY": {"MONEY-01"},
        "FIND": {"FIND-01"},
        "TIME": {"TIME-01"},
        "SPACE": {"SPACE-01"},
        "GUARD": {f"GUARD-0{i}" for i in range(1, 7)},
    }
    for prefix, expected in required.items():
        found = by_prefix.get(prefix, set())
        missing = expected - found
        if missing:
            raise RuntimeError(f"missing evidence ids in registry for {prefix}: {sorted(missing)}")
    return by_prefix


def flatten_texts(record: dict[str, Any]) -> list[str]:
    texts: list[str] = []
    for claim in record.get("claims", []):
        texts.append(str(claim.get("text", "")))
        texts.extend(str(item) for item in claim.get("conditions", []) or [])
        texts.extend(str(item) for item in claim.get("reality_checks", []) or [])
    for action in record.get("actions", []):
        texts.append(str(action.get("text", "")))
        texts.append(str(action.get("reality_anchor", "")))
    texts.extend(str(item) for item in record.get("uncertainties", []) or [])
    texts.extend(str(item) for item in record.get("prohibited_topics", []) or [])
    return texts


def normalize_for_risk_scan(text: str) -> str:
    """Remove known false-positive spans before high-risk substring checks."""
    cleaned = text
    for span in ("外出轨迹", "出行轨迹", "运动轨迹"):
        cleaned = cleaned.replace(span, " ")
    return cleaned


def find_high_risk_hits(text: str) -> list[str]:
    scanned = normalize_for_risk_scan(text)
    return [topic for topic in HIGH_RISK_TOPICS if topic in scanned]


def prefix_of(evidence_id: str) -> str:
    return evidence_id.split("-", 1)[0]


def allowed_prefixes_for(method: str) -> set[str]:
    if method == "space-observation":
        return set(SPACE_ALLOWED_PREFIXES)
    board = METHOD_PREFIXES.get(method, set())
    return set(board) | set(PROTOCOL_PREFIXES)


def validate_reading(record: dict[str, Any], registry: dict[str, set[str]] | None = None) -> dict[str, Any]:
    registry = registry or load_registry()
    known_ids = {evidence_id for values in registry.values() for evidence_id in values}

    errors: list[dict[str, str]] = []
    blocking = False

    def revise(code: str, message: str) -> None:
        errors.append({"severity": "REVISE", "code": code, "message": message})

    def block(code: str, message: str) -> None:
        nonlocal blocking
        blocking = True
        errors.append({"severity": "BLOCK", "code": code, "message": message})

    if not isinstance(record, dict):
        block("not_object", "reading_record must be a JSON object")
        return {"status": "BLOCK", "errors": errors}

    method = record.get("method")
    if method not in METHOD_PREFIXES:
        block("bad_method", f"unsupported method: {method!r}")
        return {"status": "BLOCK", "errors": errors}

    confidence = record.get("calculation_confidence")
    if confidence not in {"A", "B", "C"}:
        revise("bad_confidence", "calculation_confidence must be A, B, or C")

    schema_version = record.get("schema_version")
    if schema_version != "daily-yigua-reading-v1":
        revise("bad_schema", "schema_version must be daily-yigua-reading-v1")

    claims = record.get("claims")
    actions = record.get("actions")
    if not isinstance(claims, list):
        revise("claims_type", "claims must be a list")
        claims = []
    if not isinstance(actions, list):
        revise("actions_type", "actions must be a list")
        actions = []

    allowed_prefixes = allowed_prefixes_for(method)
    board_prefixes = METHOD_PREFIXES[method]

    all_ids: list[str] = []

    for index, claim in enumerate(claims):
        if not isinstance(claim, dict):
            revise("claim_type", f"claims[{index}] must be an object")
            continue
        text = str(claim.get("text", "")).strip()
        evidence_ids = claim.get("evidence_ids") or []
        strength = claim.get("strength")
        conditions = claim.get("conditions") or []

        if not text:
            revise("empty_claim", f"claims[{index}].text is empty")
        if not isinstance(evidence_ids, list) or not evidence_ids:
            revise("claim_evidence", f"claims[{index}] needs at least one evidence_id")
            evidence_ids = []
        if strength not in {1, 2, 3}:
            revise("claim_strength", f"claims[{index}].strength must be 1, 2, or 3")

        for evidence_id in evidence_ids:
            if evidence_id not in known_ids:
                revise("unknown_evidence", f"unknown evidence_id: {evidence_id}")
                continue
            prefix = prefix_of(evidence_id)
            if prefix not in allowed_prefixes:
                block("method_mix", f"{method} cannot cite {evidence_id}")
            if prefix in {"MH", "XL", "BZ"} and board_prefixes and prefix not in board_prefixes:
                block("board_mix", f"{method} cannot cite board evidence {evidence_id}")
            all_ids.append(evidence_id)

        if strength == 2:
            unique_ids = {str(item) for item in evidence_ids}
            if len(unique_ids) < 2:
                revise("strength2_evidence", f"claims[{index}] strength 2 needs >=2 independent evidence_ids")
            if not conditions:
                revise("strength2_conditions", f"claims[{index}] strength 2 needs non-empty conditions")
        if strength == 3:
            revise("claim_strength3", f"claims[{index}] strength 3 belongs on actions, not claims")

        if confidence == "C" and strength in {2, 3}:
            block("confidence_c", "calculation_confidence C forbids directional strength 2/3 claims")

    for index, action in enumerate(actions):
        if not isinstance(action, dict):
            revise("action_type", f"actions[{index}] must be an object")
            continue
        text = str(action.get("text", "")).strip()
        evidence_ids = action.get("evidence_ids") or []
        reality_anchor = str(action.get("reality_anchor", "")).strip()
        reversible = action.get("reversible")
        risk_level = action.get("risk_level")

        if not text:
            revise("empty_action", f"actions[{index}].text is empty")
        if not isinstance(evidence_ids, list) or not evidence_ids:
            revise("action_evidence", f"actions[{index}] needs at least one evidence_id")
            evidence_ids = []
        if not reality_anchor:
            revise("missing_anchor", f"actions[{index}] needs reality_anchor")
        if reversible is not True:
            revise("not_reversible", f"actions[{index}].reversible must be true")
        if risk_level != "low":
            revise("risk_not_low", f"actions[{index}].risk_level must be low")

        for evidence_id in evidence_ids:
            if evidence_id not in known_ids:
                revise("unknown_evidence", f"unknown evidence_id: {evidence_id}")
                continue
            prefix = prefix_of(evidence_id)
            if prefix not in allowed_prefixes:
                block("method_mix", f"{method} cannot cite {evidence_id}")
            if prefix in {"MH", "XL", "BZ"} and board_prefixes and prefix not in board_prefixes:
                block("board_mix", f"{method} cannot cite board evidence {evidence_id}")
            all_ids.append(evidence_id)

        if confidence == "C":
            block("confidence_c_action", "calculation_confidence C forbids directional action recommendations")

        # Treat completed action suggestions as strength-3 obligations.
        if not reality_anchor or reversible is not True or risk_level != "low":
            revise("strength3_fields", f"actions[{index}] fails strength-3 field requirements")

    joined = "\n".join(flatten_texts(record))
    for phrase in FORBIDDEN_PHRASES:
        if phrase in joined:
            block("forbidden_phrase", f"forbidden expression detected: {phrase}")

    for marker in UNADMITTED_MARKERS:
        if marker in joined:
            block("unadmitted_system", f"unadmitted system marker detected: {marker}")

    prohibited_topics = record.get("prohibited_topics") or []
    if not isinstance(prohibited_topics, list):
        revise("prohibited_type", "prohibited_topics must be a list")
        prohibited_topics = []

    high_risk_hits = find_high_risk_hits(joined)
    for topic in prohibited_topics:
        topic_text = str(topic)
        if topic_text in HIGH_RISK_TOPICS or find_high_risk_hits(topic_text):
            high_risk_hits.append(topic_text)
    high_risk_hit = bool(high_risk_hits)
    if high_risk_hit:
        decisive = any(
            token in joined
            for token in ("必须", "一定", "马上手术", "立刻起诉", "全仓买入", "不要报警", "可以不管法律")
        )
        if decisive or any(
            token in joined for token in ("必然", "注定", "百分百", "肯定发财", "一定复合")
        ):
            block("high_risk_decisive", "high-risk topic with decisive recommendation")
        elif not prohibited_topics and any(topic in joined for topic in HIGH_RISK_TOPICS):
            revise("high_risk_unmarked", "high-risk language present but prohibited_topics is empty")

    if blocking:
        status = "BLOCK"
    elif errors:
        status = "REVISE"
    else:
        status = "PASS"

    return {
        "status": status,
        "method": method,
        "evidence_ids_seen": sorted(set(all_ids)),
        "errors": errors,
    }


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        try:
            rows.append(json.loads(text))
        except json.JSONDecodeError as error:
            raise ValueError(f"{path}:{line_number}: {error}") from error
    return rows


def run_golden_suite() -> dict[str, Any]:
    registry = load_registry()
    tests_root = ROOT / "tests"
    reading_files = sorted((tests_root / "readings").glob("*.jsonl"))
    safety_files = sorted((tests_root / "safety").glob("*.jsonl"))
    fresh_files = sorted((tests_root / "fresh").glob("*.jsonl")) if (tests_root / "fresh").is_dir() else []
    routing_files = sorted((tests_root / "routing").glob("*.jsonl"))

    results = {
        "registry_prefix_counts": {key: len(values) for key, values in sorted(registry.items())},
        "reading_cases": 0,
        "safety_cases": 0,
        "fresh_cases": 0,
        "routing_cases": 0,
        "failed": [],
    }

    for path in reading_files + safety_files + fresh_files:
        for case in load_jsonl(path):
            case_id = case.get("id") or case.get("input") or path.name
            expected = case["expected_status"]
            actual = validate_reading(case["reading_record"], registry)
            if path.parent.name == "safety":
                bucket = "safety_cases"
            elif path.parent.name == "fresh":
                bucket = "fresh_cases"
            else:
                bucket = "reading_cases"
            results[bucket] += 1
            if actual["status"] != expected:
                results["failed"].append(
                    {
                        "id": case_id,
                        "file": str(path.relative_to(ROOT)),
                        "expected": expected,
                        "actual": actual["status"],
                        "errors": actual["errors"],
                    }
                )
                continue
            required_evidence = set(case.get("required_evidence") or [])
            if required_evidence and expected == "PASS":
                seen = set(actual["evidence_ids_seen"])
                if not required_evidence.issubset(seen):
                    results["failed"].append(
                        {
                            "id": case_id,
                            "file": str(path.relative_to(ROOT)),
                            "expected": "required_evidence",
                            "actual": sorted(seen),
                            "missing": sorted(required_evidence - seen),
                        }
                    )
            forbidden_claims = case.get("forbidden_claims") or []
            joined = "\n".join(flatten_texts(case["reading_record"]))
            for phrase in forbidden_claims:
                if phrase in joined and expected == "PASS":
                    results["failed"].append(
                        {
                            "id": case_id,
                            "file": str(path.relative_to(ROOT)),
                            "expected": "no_forbidden_claim",
                            "actual": phrase,
                        }
                    )

    route_spec = importlib.util.spec_from_file_location("daily_yigua_router", ROOT / "router" / "route.py")
    route_module = importlib.util.module_from_spec(route_spec)
    route_spec.loader.exec_module(route_module)
    for path in routing_files:
        for case in load_jsonl(path):
            results["routing_cases"] += 1
            if "expected_method" not in case or "accept" not in case:
                results["failed"].append({"id": case.get("id"), "file": str(path.relative_to(ROOT)), "error": "missing expected_method or accept"})
                continue
            actual = route_module.route(case["input"])
            expected = {"method": case["expected_method"], "accept": case["accept"]}
            if "expected_status" in case:
                expected["status"] = case["expected_status"]
            if "expected_mode" in case:
                expected["mode"] = case["expected_mode"]
            if any(actual[key] != value for key, value in expected.items()):
                results["failed"].append({"id": case.get("id"), "file": str(path.relative_to(ROOT)),
                                          "expected": expected, "actual": actual})

    results["status"] = "ok" if not results["failed"] else "failed"
    results["total_cases"] = (
        results["reading_cases"]
        + results["safety_cases"]
        + results["fresh_cases"]
        + results["routing_cases"]
    )
    return results


def validate_with_context(record, context_request):
    """Recompute context checks from the source envelope, not a caller's PASS flag."""
    sys.path.insert(0, str(ROOT / 'router'))
    try:
        from route_context import assess
        context = assess(context_request)
    except (ValueError, TypeError, KeyError, OSError) as error:
        return {'status': 'BLOCK', 'errors': [{'severity': 'BLOCK', 'code': 'invalid_context', 'message': str(error)}]}
    finally:
        sys.path.pop(0)
    output = validate_reading(record)
    errors = output['errors']
    route_record = context['route_record']
    if route_record['method'] != record.get('method') or route_record['status'] != 'READY':
        errors.append({'severity': 'BLOCK', 'code': 'context_route_mismatch', 'message': 'Reading needs a READY route of the same method.'})

    ledger = context['information_usage']
    anchor_ids = set(context['place_anchor']['anchor_source_ids'])
    constraint_ids = {row['id'] for row in ledger if row['usage'] == 'constraint'}
    spatial_ids = set(context['spatial_check']['source_ids'])
    # Anchors and constraints are legitimate action sources too, not just the
    # inspected map tiles; an action may cite any of them, but see below for
    # what it *must* cite.
    known = spatial_ids | anchor_ids | constraint_ids
    actions = record.get('actions') if isinstance(record.get('actions'), list) else []
    cited = set()
    for action in actions:
        refs = action.get('context_source_ids') if isinstance(action, dict) else None
        if isinstance(refs, list):
            cited.update(ref for ref in refs if isinstance(ref, str))

    if context_request['context']['spatial_action'] and actions:
        if context['spatial_check']['status'] != 'PASS':
            errors.append({'severity': 'REVISE', 'code': 'spatial_evidence_missing', 'message': 'Do not publish location-based actions before spatial evidence passes.'})
        else:
            for index, action in enumerate(actions):
                refs = action.get('context_source_ids') if isinstance(action, dict) else None
                if not isinstance(refs, list) or not refs or any(not isinstance(ref, str) or ref not in known for ref in refs):
                    errors.append({'severity': 'REVISE', 'code': 'spatial_action_source', 'message': f'actions[{index}] must reference inspected spatial evidence.'})
                elif not spatial_ids.intersection(refs):
                    errors.append({'severity': 'REVISE', 'code': 'spatial_action_unverified', 'message': f'actions[{index}] cites no inspected spatial source.'})

    # The reported place must reach the answer. Accepting a location and then
    # producing direction-free advice is the failure this gate exists for.
    if context['place_anchor']['ready'] and actions and not anchor_ids.intersection(cited):
        errors.append({'severity': 'REVISE', 'code': 'unused_place_anchor',
                       'message': 'A usable place/heading was supplied; at least one action must cite it via context_source_ids.'})
    if constraint_ids and actions and not constraint_ids.intersection(cited):
        errors.append({'severity': 'REVISE', 'code': 'unused_constraint',
                       'message': f'Supplied constraints {sorted(constraint_ids)} never constrain any action.'})

    # Items openly declined still have to be declined *to the user*.
    disclosures = record.get('disclosures')
    disclosed = {str(item) for item in disclosures} if isinstance(disclosures, list) else set()
    for row in context['must_tell_user']:
        if row['id'] not in disclosed:
            errors.append({'severity': 'REVISE', 'code': 'undisclosed_dismissal',
                           'message': f"{row['id']} was dismissed as irrelevant and must be named in disclosures."})

    output['status'] = 'BLOCK' if any(e['severity'] == 'BLOCK' for e in errors) else 'REVISE' if errors else 'PASS'
    output['context_check'] = context
    output['information_coverage'] = {
        'ledger_items': len(ledger),
        'unaccounted': context['unaccounted_information'],
        'anchor_source_ids': sorted(anchor_ids),
        'cited_by_actions': sorted(cited),
    }
    return output


def main(argv: list[str] | None = None) -> int:
    # Windows pipes default to the ANSI code page; downstream tools read UTF-8.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Validate reading_record evidence gates")
    parser.add_argument("--file", help="Path to a reading_record JSON file")
    parser.add_argument("--json", help="Inline reading_record JSON string")
    parser.add_argument("--self-test", action="store_true", help="Run bundled golden cases")
    parser.add_argument("--context-file", help="Original context request for mandatory spatial action checks")
    args = parser.parse_args(argv)

    if args.self_test:
        payload = run_golden_suite()
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload["status"] == "ok" else 1

    if args.file:
        record = json.loads(Path(args.file).read_text(encoding="utf-8"))
    elif args.json:
        record = json.loads(args.json)
    else:
        record = json.load(sys.stdin)

    result = validate_with_context(record, json.loads(Path(args.context_file).read_text(encoding='utf-8-sig'))) if args.context_file else validate_reading(record)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
