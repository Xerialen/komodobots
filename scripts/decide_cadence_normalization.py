#!/usr/bin/env python3
"""Decide whether bot-comparable cadence survives simple normalization."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Iterable

from analyze_human_mvd import format_comparison_value, load_json_if_present
from summarize_reference_aggregate import portable_path


SCHEMA = "komodobots.cadence_normalization_decision.v1"
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REFERENCE_AGGREGATE = (
    REPO_ROOT
    / "experiments"
    / "human_comparison"
    / "evidence"
    / "human-reference-s7c-bot-comparable-cadence-dm3-aggregate.json"
)

DERIVED_AXES = (
    {
        "field": "jump_cadence_per_nonstationary_min",
        "label": "Cadence/non-stationary min",
        "basis": "active time excluding stationary_time_ratio",
        "denominator_ratio_field": "stationary_time_ratio",
        "denominator_mode": "one_minus_ratio",
    },
    {
        "field": "jump_cadence_per_non_low_speed_min",
        "label": "Cadence/non-low-speed min",
        "basis": "active time excluding low_speed_time_ratio",
        "denominator_ratio_field": "low_speed_time_ratio",
        "denominator_mode": "one_minus_ratio",
    },
    {
        "field": "jump_cadence_per_airborne_proxy_min",
        "label": "Cadence/air-proxy min",
        "basis": "airborne_proxy_time_ratio",
        "denominator_ratio_field": "airborne_proxy_time_ratio",
        "denominator_mode": "ratio",
    },
)


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


def denominator(row: dict[str, object], axis: dict[str, str]) -> float | None:
    ratio = optional_float(row.get(axis["denominator_ratio_field"]))
    if ratio is None:
        return None
    if axis["denominator_mode"] == "one_minus_ratio":
        value = 1.0 - ratio
    else:
        value = ratio
    if value <= 0:
        return None
    return value


def derive_axis_value(row: dict[str, object], axis: dict[str, str]) -> float | None:
    cadence = optional_float(row.get("jump_cadence_per_min"))
    denom = denominator(row, axis)
    if cadence is None or denom is None:
        return None
    return round(cadence / denom, 3)


def add_derived_axes(row: dict[str, object]) -> dict[str, object]:
    derived = dict(row)
    for axis in DERIVED_AXES:
        derived[axis["field"]] = derive_axis_value(row, axis)
    return derived


def numeric_values(rows: list[dict[str, object]], field: str) -> list[float]:
    values = []
    for row in rows:
        value = optional_float(row.get(field))
        if value is not None:
            values.append(value)
    return values


def summarize_values(rows: list[dict[str, object]], field: str) -> dict[str, object]:
    values = numeric_values(rows, field)
    if not values:
        return {"count": 0, "min": None, "mean": None, "max": None}
    return {
        "count": len(values),
        "min": round(min(values), 3),
        "mean": round(sum(values) / len(values), 3),
        "max": round(max(values), 3),
    }


def classify_against_reference(value: object, summary: dict[str, object]) -> str:
    if not summary.get("count"):
        return "no_reference_range"
    number = optional_float(value)
    minimum = optional_float(summary.get("min"))
    maximum = optional_float(summary.get("max"))
    if number is None or minimum is None or maximum is None:
        return "unavailable"
    if number < minimum:
        return "below_reference_min"
    if number > maximum:
        return "above_reference_max"
    return "within_reference_range"


def bot_relation(classifications: list[str]) -> str:
    usable = [value for value in classifications if value != "unavailable"]
    if not usable:
        return "no_bot_comparison"
    if all(value == "within_reference_range" for value in usable):
        return "all_bots_within_reference_range"
    if all(value == "above_reference_max" for value in usable):
        return "all_bots_above_reference_range"
    if all(value == "below_reference_min" for value in usable):
        return "all_bots_below_reference_range"
    return "mixed_bot_relation"


def compact_normalized_rows(rows: list[dict[str, object]], *, identity_field: str) -> list[dict[str, object]]:
    compact = []
    for row in rows:
        normalized = add_derived_axes(row)
        compact_row = {
            identity_field: normalized.get(identity_field, ""),
            "run_id": normalized.get("run_id", ""),
            "jump_cadence_per_min": rounded(normalized.get("jump_cadence_per_min")),
            "stationary_time_ratio": rounded(normalized.get("stationary_time_ratio")),
            "low_speed_time_ratio": rounded(normalized.get("low_speed_time_ratio")),
            "airborne_proxy_time_ratio": rounded(normalized.get("airborne_proxy_time_ratio")),
        }
        for axis in DERIVED_AXES:
            compact_row[axis["field"]] = rounded(normalized.get(axis["field"]))
        compact.append(compact_row)
    return compact


def build_normalization_axes(
    reference_rows: list[dict[str, object]],
    bot_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    axes = []
    for axis in DERIVED_AXES:
        field = axis["field"]
        reference_summary = summarize_values(reference_rows, field)
        bot_summary = summarize_values(bot_rows, field)
        bot_rows_for_axis = []
        classifications = []
        for row in bot_rows:
            classification = classify_against_reference(row.get(field), reference_summary)
            classifications.append(classification)
            bot_rows_for_axis.append(
                {
                    "player": row.get("player", ""),
                    "run_id": row.get("run_id", ""),
                    "value": rounded(row.get(field)),
                    "against_reference": classification,
                }
            )
        axes.append(
            {
                "field": field,
                "label": axis["label"],
                "basis": axis["basis"],
                "reference": reference_summary,
                "bot": bot_summary,
                "bot_relation": bot_relation(classifications),
                "bot_rows": bot_rows_for_axis,
            }
        )
    return axes


def make_decision(axes: list[dict[str, object]]) -> dict[str, object]:
    by_field = {str(axis.get("field")): axis for axis in axes}
    moving = by_field.get("jump_cadence_per_non_low_speed_min", {})
    airborne = by_field.get("jump_cadence_per_airborne_proxy_min", {})
    moving_relation = str(moving.get("bot_relation", ""))
    airborne_relation = str(airborne.get("bot_relation", ""))
    if airborne_relation in {"all_bots_above_reference_range", "mixed_bot_relation"}:
        return {
            "verdict": "cadence_stays_diagnostic_not_controller_target",
            "reason": (
                "Movement-time normalization preserves the mixed bot relation, but airborne-proxy "
                "normalization puts bot cadence outside the exact-player range. A cadence controller "
                "would risk optimizing a proxy before the airborne/landing rhythm gap is understood."
            ),
            "next_goal": (
                "S7e should broaden or dissect the cadence evidence before controller work: add more "
                "bot rows and/or inspect airborne-proxy segmentation so cadence can be separated from "
                "the unresolved land-speed and air-rhythm gaps."
            ),
        }
    if moving_relation == "all_bots_within_reference_range" and airborne_relation == "all_bots_within_reference_range":
        return {
            "verdict": "tiny_cadence_probe_may_be_considered",
            "reason": (
                "Both movement-time and airborne-proxy normalization keep bots inside the repeated "
                "exact-player range. A tiny probe could be considered if it keeps land-speed gaps visible."
            ),
            "next_goal": (
                "Design a tiny cadence-only probe with explicit stop conditions and unchanged land-speed reporting."
            ),
        }
    return {
        "verdict": "needs_more_evidence_before_controller",
        "reason": "The normalized relations are inconclusive for a controller decision.",
        "next_goal": "Broaden bot/reference samples before controller work.",
    }


def build_report(aggregate: dict[str, object], *, stage: str, source_aggregate_path: Path | None = None) -> dict[str, object]:
    reference_rows = [
        add_derived_axes(row) for row in aggregate.get("reference_rows", []) if isinstance(row, dict)
    ]
    bot_rows = [add_derived_axes(row) for row in aggregate.get("bot_rows", []) if isinstance(row, dict)]
    axes = build_normalization_axes(reference_rows, bot_rows)
    decision = make_decision(axes)
    return {
        "schema": SCHEMA,
        "stage": stage,
        "source_aggregate_path": portable_path(source_aggregate_path) if source_aggregate_path else "",
        "source_aggregate_stage": aggregate.get("stage", ""),
        "map": aggregate.get("map", ""),
        "reference_count": len(reference_rows),
        "bot_count": len(bot_rows),
        "bot_source_run_ids": aggregate.get("bot_source_run_ids", []),
        "normalization_note": (
            "`jump_cadence_per_min` is already based on active movement-metrics rows "
            "(airborne_proxy_count / active_time_s * 60). S7d re-normalizes it by "
            "non-stationary time, non-low-speed time, and airborne-proxy time to test "
            "whether combat or downtime dilution changes the S7c relation."
        ),
        "reference_rows": compact_normalized_rows(reference_rows, identity_field="target_player"),
        "bot_rows": compact_normalized_rows(bot_rows, identity_field="player"),
        "normalization_axes": axes,
        "decision": decision,
    }


def format_range(field: str, summary: dict[str, object]) -> str:
    if not summary.get("count"):
        return ""
    return (
        f"{format_comparison_value(field, summary.get('min'))}-"
        f"{format_comparison_value(field, summary.get('max'))}"
    )


def write_markdown(report: dict[str, object], output_path: Path) -> None:
    lines = [
        f"# Cadence Normalization Decision {report.get('stage', '')}",
        "",
        "## Scope",
        "",
        f"- Map: `{report.get('map', '')}`",
        f"- Source aggregate: `{report.get('source_aggregate_path', '')}`",
        f"- Reference rows: `{report.get('reference_count', 0)}`",
        f"- S3g bot rows: `{report.get('bot_count', 0)}`",
        f"- Bot source run IDs: `{', '.join(report.get('bot_source_run_ids', []))}`",
        "",
        f"- {report.get('normalization_note', '')}",
        "",
        "## Normalized Cadence Axes",
        "",
        "| Axis | Basis | Reference range | S3g bot range | Bot relation |",
        "|---|---|---:|---:|---|",
    ]
    for axis in report.get("normalization_axes", []):
        field = str(axis.get("field", ""))
        reference = axis.get("reference", {}) if isinstance(axis.get("reference"), dict) else {}
        bot = axis.get("bot", {}) if isinstance(axis.get("bot"), dict) else {}
        lines.append(
            "| "
            f"{axis.get('label', field)} | "
            f"{axis.get('basis', '')} | "
            f"{format_range(field, reference)} | "
            f"{format_range(field, bot)} | "
            f"`{axis.get('bot_relation', '')}` |"
        )

    lines.extend(
        [
            "",
            "## Bot Rows",
            "",
            "| Bot | Cadence/min | Non-stationary | Non-low-speed | Air-proxy |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for row in report.get("bot_rows", []):
        lines.append(
            "| "
            f"`{row.get('player', '')}` | "
            f"{format_comparison_value('jump_cadence_per_min', row.get('jump_cadence_per_min'))} | "
            f"{format_comparison_value('jump_cadence_per_nonstationary_min', row.get('jump_cadence_per_nonstationary_min'))} | "
            f"{format_comparison_value('jump_cadence_per_non_low_speed_min', row.get('jump_cadence_per_non_low_speed_min'))} | "
            f"{format_comparison_value('jump_cadence_per_airborne_proxy_min', row.get('jump_cadence_per_airborne_proxy_min'))} |"
        )

    decision = report.get("decision", {}) if isinstance(report.get("decision"), dict) else {}
    lines.extend(
        [
            "",
            "## Decision",
            "",
            f"- Verdict: `{decision.get('verdict', '')}`",
            f"- Reason: {decision.get('reason', '')}",
            f"- Next goal: {decision.get('next_goal', '')}",
        ]
    )
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Decide whether S7c cadence survives normalization.")
    parser.add_argument("--stage", default="s7d-cadence-normalization-dm3", help="Decision stage label.")
    parser.add_argument(
        "--reference-aggregate",
        type=Path,
        default=DEFAULT_REFERENCE_AGGREGATE,
        help="S7c bot-comparable cadence aggregate JSON.",
    )
    parser.add_argument("--output-json", type=Path, required=True, help="Output decision JSON.")
    parser.add_argument("--output-md", type=Path, required=True, help="Output decision Markdown.")
    return parser.parse_args(list(argv))


def main(argv: Iterable[str] = sys.argv[1:]) -> int:
    args = parse_args(argv)
    aggregate = load_json_if_present(args.reference_aggregate)
    if not aggregate:
        raise FileNotFoundError(args.reference_aggregate)
    report = build_report(aggregate, stage=args.stage, source_aggregate_path=args.reference_aggregate)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_markdown(report, args.output_md)
    print(f"Wrote cadence normalization decision: {args.output_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
