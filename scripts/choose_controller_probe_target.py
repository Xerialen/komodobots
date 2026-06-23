#!/usr/bin/env python3
"""Choose the first S7 controller probe target from S7g context."""

from __future__ import annotations

import logging
import argparse
import json
import math
import sys
from pathlib import Path
from typing import Iterable

from analyze_human_mvd import format_comparison_value
from summarize_reference_aggregate import portable_path



LOGGER = logging.getLogger(__name__)
SCHEMA = "komodobots.controller_probe_target.v1"
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = REPO_ROOT / "experiments" / "human_comparison" / "evidence" / "land-speed-gap-s7g-dm3.json"
DEFAULT_OUTPUT_JSON = REPO_ROOT / "experiments" / "human_comparison" / "evidence" / "controller-probe-target-s7h-dm3.json"
DEFAULT_OUTPUT_MD = REPO_ROOT / "experiments" / "human_comparison" / "evidence" / "controller-probe-target-s7h-dm3.md"


class DecisionInputError(RuntimeError):
    """Raised when S7h cannot derive a safe target decision."""


def optional_float(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def rounded(value: object, digits: int = 3) -> float | None:
    number = optional_float(value)
    if number is None:
        return None
    return round(number, digits)


def summary_count(summary: dict[str, object]) -> int:
    try:
        return int(summary.get("count", 0))
    except (TypeError, ValueError):
        return 0


def bucket(report: dict[str, object], key: str) -> dict[str, object]:
    comparison = report.get("comparison", {}) if isinstance(report.get("comparison"), dict) else {}
    value = comparison.get(key, {}) if isinstance(comparison.get(key), dict) else {}
    return value


def bucket_summary(report: dict[str, object], key: str, side: str) -> dict[str, object]:
    row = bucket(report, key)
    field = "reference_player_p50_speed" if side == "reference" else "bot_player_p50_speed"
    value = row.get(field, {}) if isinstance(row.get(field), dict) else {}
    return value


def bucket_ratio(report: dict[str, object], key: str) -> float | None:
    return rounded(bucket(report, key).get("bot_to_reference_p50_ratio"))


def bucket_p50(report: dict[str, object], key: str, side: str) -> float | None:
    return rounded(bucket_summary(report, key, side).get("p50"))


def bot_route_state_segment_count(report: dict[str, object]) -> int:
    total = 0
    for row in report.get("bot_players", []):
        if not isinstance(row, dict):
            continue
        try:
            total += int(row.get("route_state_segment_count", 0))
        except (TypeError, ValueError):
            continue
    return total


def route_rows_with_bucket(report: dict[str, object], key: str) -> int:
    total = 0
    for row in report.get("bot_players", []):
        if not isinstance(row, dict):
            continue
        buckets = row.get("speed_buckets", {}) if isinstance(row.get("speed_buckets"), dict) else {}
        summary = buckets.get(key, {}) if isinstance(buckets.get(key), dict) else {}
        if summary_count(summary) > 0:
            total += 1
    return total


def relation_label(ratio: float | None) -> str:
    if ratio is None:
        return "unavailable"
    if ratio < 0.45:
        return "severe_gap"
    if ratio < 0.6:
        return "large_gap"
    if ratio < 0.85:
        return "moderate_gap"
    return "near_reference"


def air_transition_candidate(report: dict[str, object]) -> dict[str, object]:
    keys = ["pre_air_window_segments", "airborne_proxy_segments", "post_air_window_segments"]
    ratios = {key: bucket_ratio(report, key) for key in keys}
    counts = {
        key: {
            "reference": summary_count(bucket_summary(report, key, "reference")),
            "bot": summary_count(bucket_summary(report, key, "bot")),
        }
        for key in keys
    }
    non_air_ratio = bucket_ratio(report, "non_airborne_segments")
    usable_ratios = [value for value in ratios.values() if value is not None]
    evidence_complete = len(usable_ratios) == len(keys) and all(
        counts[key]["reference"] >= 3 and counts[key]["bot"] >= 3 for key in keys
    )
    severity = round(sum(1.0 - value for value in usable_ratios) / len(usable_ratios), 3) if usable_ratios else None
    selected_ready = (
        evidence_complete
        and non_air_ratio is not None
        and non_air_ratio >= 0.85
        and all(value is not None and value < 0.6 for value in ratios.values())
    )
    return {
        "target": "air_transition_horizontal_speed",
        "label": "Air-transition horizontal speed production",
        "priority": "preferred_first_probe_target" if selected_ready else "candidate_needs_more_evidence",
        "human_comparable": evidence_complete,
        "score": rounded(severity),
        "evidence": {
            "pre_air_p50_ratio": ratios["pre_air_window_segments"],
            "airborne_p50_ratio": ratios["airborne_proxy_segments"],
            "post_air_p50_ratio": ratios["post_air_window_segments"],
            "non_airborne_p50_ratio": non_air_ratio,
            "pre_air_counts": counts["pre_air_window_segments"],
            "airborne_counts": counts["airborne_proxy_segments"],
            "post_air_counts": counts["post_air_window_segments"],
        },
        "reason": (
            "The gap is human-comparable and context-specific: pre-air, airborne, and post-air p50 ratios are all "
            "below 0.6 while generic non-airborne p50 speed is near reference."
            if selected_ready
            else "Air-transition evidence is incomplete or not clearly separated from generic non-air speed."
        ),
        "risk": (
            "A probe must preserve combat/route context and keep route WATER_PATH as a guardrail, because S7g also "
            "found very slow route-specific samples."
        ),
    }


def water_path_candidate(report: dict[str, object]) -> dict[str, object]:
    water_summary = bucket_summary(report, "route_water_path_segments", "bot")
    low_dir_summary = bucket_summary(report, "route_low_dir_speed_segments", "bot")
    water_speed = rounded(water_summary.get("p50"))
    low_dir_speed = rounded(low_dir_summary.get("p50"))
    route_segment_count = bot_route_state_segment_count(report)
    water_rows = route_rows_with_bucket(report, "route_water_path_segments")
    low_dir_rows = route_rows_with_bucket(report, "route_low_dir_speed_segments")
    has_route_evidence = route_segment_count > 0 and water_rows > 0 and water_speed is not None
    score = None
    if water_speed is not None:
        score = round(max(0.0, min(1.0, (220.0 - water_speed) / 220.0)), 3)
    return {
        "target": "water_path_low_dir_speed_recovery",
        "label": "Route WATER_PATH low-dir-speed recovery",
        "priority": "secondary_guardrail_target" if has_route_evidence else "candidate_needs_route_evidence",
        "human_comparable": False,
        "score": score,
        "evidence": {
            "bot_route_state_matched_segments": route_segment_count,
            "water_path_rows": water_rows,
            "low_dir_speed_rows": low_dir_rows,
            "water_path_bot_p50_speed": water_speed,
            "low_dir_bot_p50_speed": low_dir_speed,
            "water_path_player_p50_count": summary_count(water_summary),
            "low_dir_player_p50_count": summary_count(low_dir_summary),
        },
        "reason": (
            "WATER_PATH is extremely slow, but the evidence is bot-only route diagnostics with no exact-player "
            "reference bucket and only a narrow route context."
            if has_route_evidence
            else "The S7g artifact does not expose enough route-state evidence to choose a WATER_PATH probe."
        ),
        "risk": (
            "A route-only probe may overfit a narrow `dm3.bot` primitive before the broader human-comparable "
            "air-transition speed gap is addressed."
        ),
    }


def make_decision(candidates: list[dict[str, object]]) -> dict[str, object]:
    by_target = {str(candidate["target"]): candidate for candidate in candidates}
    air = by_target.get("air_transition_horizontal_speed", {})
    water = by_target.get("water_path_low_dir_speed_recovery", {})
    if air.get("priority") == "preferred_first_probe_target":
        return {
            "verdict": "choose_air_transition_horizontal_speed_probe",
            "selected_target": "air_transition_horizontal_speed",
            "deferred_target": "water_path_low_dir_speed_recovery",
            "reason": (
                "Air-transition speed is the first controller probe target because it is human-comparable across "
                "the exact-player and bot row set, affects pre-air/airborne/post-air contexts, and is clearly "
                "separated from generic non-airborne speed. WATER_PATH remains a guardrail and later narrow "
                "route target rather than the first probe."
            ),
            "next_goal": (
                "S7i should design a tiny air-transition horizontal-speed probe with unchanged cadence reporting, "
                "unchanged route diagnostics, and stop conditions that reject all-segment speed gains if air "
                "transition buckets or WATER_PATH context get worse."
            ),
        }
    if water.get("priority") == "secondary_guardrail_target":
        return {
            "verdict": "choose_water_path_route_probe",
            "selected_target": "water_path_low_dir_speed_recovery",
            "deferred_target": "air_transition_horizontal_speed",
            "reason": "Only the route target has enough evidence for a probe in this input.",
            "next_goal": "S7i should design a narrow WATER_PATH recovery probe with explicit anti-overfit guards.",
        }
    return {
        "verdict": "needs_more_probe_target_evidence",
        "selected_target": None,
        "deferred_target": None,
        "reason": "Neither candidate has enough evidence for a controller probe decision.",
        "next_goal": "Broaden or regenerate S7g context before controller work.",
    }


def build_report(report: dict[str, object], *, stage: str, source_path: Path | None = None) -> dict[str, object]:
    warnings = []
    if report.get("warnings"):
        warnings.append(f"S7g source has warnings: {report.get('warnings')}")
    candidates = [air_transition_candidate(report), water_path_candidate(report)]
    decision = make_decision(candidates)
    return {
        "schema": SCHEMA,
        "stage": stage,
        "source_land_speed_path": portable_path(source_path) if source_path else "",
        "source_land_speed_stage": report.get("stage", ""),
        "map": report.get("map", ""),
        "method": (
            "S7h consumes S7g land-speed context and chooses the first controller-probe target. It prefers a "
            "human-comparable context gap over a narrow bot-only route diagnostic unless the comparable evidence "
            "is missing."
        ),
        "warnings": warnings,
        "candidates": candidates,
        "decision": decision,
        "probe_guardrails": [
            "Do not treat all-segment speed as success by itself.",
            "Keep cadence diagnostic and report airborne-proxy cadence after any probe.",
            "Report pre-air, airborne, post-air, non-airborne, route low-dir-speed, and WATER_PATH buckets after any probe.",
            "Reject a probe if it improves one bucket while making combat/route context or WATER_PATH behavior worse.",
        ],
    }


def validate_report(report: dict[str, object]) -> None:
    warnings = report.get("warnings", [])
    if warnings:
        raise DecisionInputError("; ".join(str(warning) for warning in warnings))
    if report.get("decision", {}).get("verdict") == "needs_more_probe_target_evidence":
        raise DecisionInputError("S7h could not choose a controller probe target from the source evidence.")


def fmt_speed(value: object) -> str:
    return format_comparison_value("avg_horizontal_speed_qu_per_s", value)


def fmt_ratio(value: object) -> str:
    number = optional_float(value)
    if number is None:
        return ""
    return f"{number:.3f}"


def write_markdown(report: dict[str, object], output_path: Path) -> None:
    decision = report.get("decision", {}) if isinstance(report.get("decision"), dict) else {}
    lines = [
        f"# Controller Probe Target Decision {report.get('stage', '')}",
        "",
        "## Scope",
        "",
        f"- Map: `{report.get('map', '')}`",
        f"- Source S7g evidence: `{report.get('source_land_speed_path', '')}`",
        f"- {report.get('method', '')}",
        "",
        "## Candidate Comparison",
        "",
        "| Candidate | Priority | Human comparable | Score | Key evidence |",
        "|---|---|---:|---:|---|",
    ]
    for candidate in report.get("candidates", []):
        if not isinstance(candidate, dict):
            continue
        evidence = candidate.get("evidence", {}) if isinstance(candidate.get("evidence"), dict) else {}
        if candidate.get("target") == "air_transition_horizontal_speed":
            key_evidence = (
                f"pre `{fmt_ratio(evidence.get('pre_air_p50_ratio'))}`, "
                f"air `{fmt_ratio(evidence.get('airborne_p50_ratio'))}`, "
                f"post `{fmt_ratio(evidence.get('post_air_p50_ratio'))}`, "
                f"non-air `{fmt_ratio(evidence.get('non_airborne_p50_ratio'))}`"
            )
        else:
            key_evidence = (
                f"WATER_PATH `{fmt_speed(evidence.get('water_path_bot_p50_speed'))}`, "
                f"low-dir `{fmt_speed(evidence.get('low_dir_bot_p50_speed'))}`, "
                f"route-matched segments `{evidence.get('bot_route_state_matched_segments', '')}`"
            )
        lines.append(
            "| "
            f"{candidate.get('label', '')} | "
            f"`{candidate.get('priority', '')}` | "
            f"`{candidate.get('human_comparable', False)}` | "
            f"`{candidate.get('score', '')}` | "
            f"{key_evidence} |"
        )

    lines.extend(
        [
            "",
            "## Decision",
            "",
            f"- Verdict: `{decision.get('verdict', '')}`",
            f"- Selected target: `{decision.get('selected_target', '')}`",
            f"- Deferred target: `{decision.get('deferred_target', '')}`",
            f"- Reason: {decision.get('reason', '')}",
            f"- Next goal: {decision.get('next_goal', '')}",
            "",
            "## Probe Guardrails",
            "",
        ]
    )
    for guardrail in report.get("probe_guardrails", []):
        lines.append(f"- {guardrail}")
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Choose the S7h controller probe target from S7g evidence.")
    parser.add_argument("--stage", default="s7h-controller-probe-target-dm3", help="Evidence stage label.")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="S7g land-speed evidence JSON.")
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON, help="Output evidence JSON.")
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD, help="Output evidence Markdown.")
    return parser.parse_args(list(argv))


def main(argv: Iterable[str] = sys.argv[1:]) -> int:
    args = parse_args(argv)
    with args.source.open("r", encoding="utf-8") as handle:
        source = json.load(handle)
    if not isinstance(source, dict):
        raise DecisionInputError(f"{args.source} did not contain a JSON object.")
    report = build_report(source, stage=args.stage, source_path=args.source)
    validate_report(report)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_markdown(report, args.output_md)
    print(f"Wrote controller probe target decision: {args.output_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
