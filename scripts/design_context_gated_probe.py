#!/usr/bin/env python3
"""Design the S7l context-gated air-transition probe."""

from __future__ import annotations

import logging
import argparse
import json
import sys
from pathlib import Path
from typing import Iterable

from analyze_human_mvd import format_comparison_value
from characterize_land_speed_gap import optional_float, summarize_values
from summarize_reference_aggregate import portable_path



LOGGER = logging.getLogger(__name__)
SCHEMA = "komodobots.context_gated_air_transition_probe_design.v1"
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_S7K = REPO_ROOT / "experiments" / "human_comparison" / "evidence" / "failed-bucket-diagnosis-s7k-dm3.json"
DEFAULT_OUTPUT_JSON = (
    REPO_ROOT / "experiments" / "human_comparison" / "evidence" / "context-gated-probe-design-s7l-dm3.json"
)
DEFAULT_OUTPUT_MD = (
    REPO_ROOT / "experiments" / "human_comparison" / "evidence" / "context-gated-probe-design-s7l-dm3.md"
)

FAILED_AIR_BUCKETS = ("pre_air_window_segments", "airborne_proxy_segments")
GUARDRAIL_BUCKETS = ("non_airborne_segments",)
MIN_CLEAN_PLAYER_ROWS = 2
MIN_CLEAN_SEGMENTS = 50
MAX_CLEAN_LOW_DIR_RATIO = 0.25
MAX_CLEAN_WATER_PATH_RATIO = 0.05
MIN_SAMPLED_COMMAND_RATIO = 0.5
MIN_STRONG_COMMAND_RATIO = 0.75


class ContextGatedProbeInputError(RuntimeError):
    """Raised when S7l cannot derive a bounded context-gated probe design."""


def load_json(path: Path) -> dict[str, object]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            loaded = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ContextGatedProbeInputError(f"Could not read {portable_path(path)} as JSON: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ContextGatedProbeInputError(f"{portable_path(path)} did not contain a JSON object.")
    return loaded


def count_value(value: object, *, field_name: str) -> int:
    if value in (None, ""):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ContextGatedProbeInputError(f"{field_name} must be an integer-like value, got {value!r}.") from exc


def rounded(value: object, digits: int = 3) -> float | None:
    number = optional_float(value)
    if number is None:
        return None
    return round(number, digits)


def ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 3)


def speed_p50(row: dict[str, object]) -> float | None:
    speed = row.get("speed", {}) if isinstance(row.get("speed"), dict) else {}
    return optional_float(speed.get("p50"))


def is_route_dirty(row: dict[str, object]) -> bool:
    low_dir = optional_float(row.get("low_dir_speed_ratio")) or 0.0
    water = optional_float(row.get("water_path_ratio")) or 0.0
    # Low-dir exactly at the limit is dirty; WATER_PATH exactly at the tiny tolerance stays clean.
    return low_dir >= MAX_CLEAN_LOW_DIR_RATIO or water > MAX_CLEAN_WATER_PATH_RATIO


def is_measurement_risk(row: dict[str, object]) -> bool:
    sampled = optional_float(row.get("sampled_command_ratio")) or 0.0
    strong = optional_float(row.get("strong_command_ratio")) or 0.0
    return sampled < MIN_SAMPLED_COMMAND_RATIO or strong < MIN_STRONG_COMMAND_RATIO


def context_class(row: dict[str, object]) -> str:
    if is_measurement_risk(row):
        return "measurement_risk"
    if is_route_dirty(row):
        return "route_guardrail_slice"
    return "clean_air_transition_candidate"


def compact_player_row(row: dict[str, object]) -> dict[str, object]:
    return {
        "bucket": row.get("bucket", ""),
        "label": row.get("label", row.get("bucket", "")),
        "player": row.get("player", ""),
        "run_id": row.get("run_id", ""),
        "segment_count": count_value(row.get("segment_count"), field_name="segment_count"),
        "p50_speed_qu_per_s": rounded(speed_p50(row)),
        "sampled_command_ratio": rounded(row.get("sampled_command_ratio")),
        "strong_command_ratio": rounded(row.get("strong_command_ratio")),
        "probe_active_ratio": rounded(row.get("probe_active_ratio")),
        "low_dir_speed_ratio": rounded(row.get("low_dir_speed_ratio")),
        "water_path_ratio": rounded(row.get("water_path_ratio")),
        "context_class": context_class(row),
    }


def summarize_slice(rows: list[dict[str, object]], bucket: str, slice_name: str) -> dict[str, object]:
    selected = [row for row in rows if row.get("bucket") == bucket and row.get("context_class") == slice_name]
    segment_count = sum(count_value(row.get("segment_count"), field_name="segment_count") for row in selected)
    p50_values = [value for row in selected if (value := optional_float(row.get("p50_speed_qu_per_s"))) is not None]
    return {
        "bucket": bucket,
        "context_class": slice_name,
        "player_row_count": len(selected),
        "segment_count": segment_count,
        "segment_ratio_in_bucket": None,
        "p50_speed_summary": summarize_values(p50_values),
        "players": selected,
    }


def bucket_context_slices(player_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    slices: list[dict[str, object]] = []
    for bucket in (*FAILED_AIR_BUCKETS, *GUARDRAIL_BUCKETS):
        bucket_total = sum(
            count_value(row.get("segment_count"), field_name="segment_count")
            for row in player_rows
            if row.get("bucket") == bucket
        )
        for slice_name in ("clean_air_transition_candidate", "route_guardrail_slice", "measurement_risk"):
            summary = summarize_slice(player_rows, bucket, slice_name)
            summary["segment_ratio_in_bucket"] = ratio(int(summary["segment_count"]), bucket_total)
            slices.append(summary)
    return slices


def clean_slice_by_bucket(slices: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    return {
        str(row.get("bucket")): row
        for row in slices
        if row.get("context_class") == "clean_air_transition_candidate"
    }


def route_slice_by_bucket(slices: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    return {
        str(row.get("bucket")): row
        for row in slices
        if row.get("context_class") == "route_guardrail_slice"
    }


def clean_bucket_ready(slice_row: dict[str, object]) -> bool:
    return (
        count_value(slice_row.get("player_row_count"), field_name="player_row_count") >= MIN_CLEAN_PLAYER_ROWS
        and count_value(slice_row.get("segment_count"), field_name="segment_count") >= MIN_CLEAN_SEGMENTS
    )


def context_gate_rules() -> list[dict[str, object]]:
    return [
        {
            "id": "eligible_air_transition_context",
            "rule": (
                "Only claim target-bucket success on pre-air or airborne-proxy slices with sampled command ratio "
                f">= {MIN_SAMPLED_COMMAND_RATIO}, strong command ratio >= {MIN_STRONG_COMMAND_RATIO}, "
                f"low-dir-speed ratio < {MAX_CLEAN_LOW_DIR_RATIO}, and WATER_PATH ratio <= "
                f"{MAX_CLEAN_WATER_PATH_RATIO}."
            ),
        },
        {
            "id": "route_context_is_guardrail_not_success",
            "rule": (
                "Low-dir-speed or WATER_PATH slices must be reported separately. They may reject or make the probe "
                "inconclusive, but they cannot be counted as evidence that the air-transition controller improved."
            ),
        },
        {
            "id": "live_gate_must_use_frogbot_state",
            "rule": (
                "A future KTX patch must gate using live Frogbot route/water state available in BotSetCommand. "
                "Offline S7k labels are evidence for the contract, not a runtime oracle."
            ),
        },
    ]


def probe_contract(slices: list[dict[str, object]]) -> dict[str, object]:
    clean = clean_slice_by_bucket(slices)
    route = route_slice_by_bucket(slices)
    return {
        "probe_id": "s7m-context-gated-air-transition-horizontal-speed",
        "intended_followup_stage": "S7m",
        "status": "design_only_no_controller_behavior_changed",
        "runtime_gate": (
            "Start from mode 8's transition-window command-budget idea, but activate it only when the live route "
            "context is clean: no WATER_PATH, no low-dir-speed route primitive, command/probe diagnostics present, "
            "and the bot is inside the intended takeoff/recent-air/recent-landing window."
        ),
        "required_clean_target_buckets": [
            {
                "bucket": bucket,
                "clean_player_rows": count_value(clean.get(bucket, {}).get("player_row_count"), field_name="player_row_count"),
                "clean_segments": count_value(clean.get(bucket, {}).get("segment_count"), field_name="segment_count"),
                "ready_for_probe_claim": clean_bucket_ready(clean.get(bucket, {})),
            }
            for bucket in FAILED_AIR_BUCKETS
        ],
        "route_guardrail_buckets": [
            {
                "bucket": bucket,
                "route_player_rows": count_value(route.get(bucket, {}).get("player_row_count"), field_name="player_row_count"),
                "route_segments": count_value(route.get(bucket, {}).get("segment_count"), field_name="segment_count"),
            }
            for bucket in (*FAILED_AIR_BUCKETS, *GUARDRAIL_BUCKETS)
        ],
        "allowed_changes": [
            "One temporary mode or cvar-gated variant that changes horizontal command budget only in clean air-transition context.",
            "Additional command log fields only if needed to prove runtime gate eligibility, activation, and rejection.",
        ],
        "forbidden_changes": [
            "No route file edit or WATER_PATH primitive fix in the same PR.",
            "No cadence/jump-timing controller change.",
            "No success claim from all-segment speed alone.",
            "No combat, item, spawn, parser, or lab-runner behavior change unless required for missing evidence reporting.",
        ],
    }


def stop_conditions() -> list[dict[str, object]]:
    return [
        {
            "id": "missing_context_split_reporting",
            "verdict": "inconclusive",
            "rule": (
                "The follow-up comparison must split pre-air, airborne-proxy, and non-airborne buckets into clean, "
                "route-guardrail, and measurement-risk slices. Missing split reporting blocks success claims."
            ),
        },
        {
            "id": "insufficient_clean_target_evidence",
            "verdict": "inconclusive",
            "rule": (
                f"Each claimed clean target bucket needs at least {MIN_CLEAN_PLAYER_ROWS} player rows and "
                f"{MIN_CLEAN_SEGMENTS} segments."
            ),
        },
        {
            "id": "clean_air_transition_regression",
            "verdict": "reject",
            "rule": "Reject if any claimed clean pre-air or airborne-proxy p50 drops more than 5 percent versus S7k clean baseline.",
            "tolerance_ratio": 0.95,
        },
        {
            "id": "no_clean_air_transition_gain",
            "verdict": "reject",
            "rule": "Reject if no clean air-transition target bucket improves while all-segment or dirty-route slices improve.",
        },
        {
            "id": "route_guardrail_regression",
            "verdict": "reject_or_route_primitive_handoff",
            "rule": (
                "Reject the controller probe or hand off to a route primitive if route-guardrail slices get worse, "
                "especially WATER_PATH or low-dir-speed contexts."
            ),
        },
        {
            "id": "cadence_and_route_diagnostics_preserved",
            "verdict": "inconclusive",
            "rule": "Missing cadence, route-state, water-state, or probe-activation diagnostics makes the result inconclusive.",
        },
    ]


def decision_gates() -> list[dict[str, object]]:
    return [
        {
            "gate": "continue_ktx_frogbots",
            "rule": (
                "Continue with KTX/Frogbots if the next clean-context probe improves a human-comparable air bucket "
                "while preserving route/cadence diagnostics and dirty-context guardrails."
            ),
        },
        {
            "gate": "switch_to_route_primitive",
            "rule": (
                "If clean air-transition slices are too sparse or route-dirty slices dominate every failure, pivot "
                "to a narrow route primitive instead of increasing controller scope."
            ),
        },
        {
            "gate": "consider_from_scratch",
            "rule": (
                "Consider abandoning Frogbots only after bounded clean-context probes still fail under strong command "
                "coverage and the live route/map state cannot separate controller failures from map-understanding failures."
            ),
        },
    ]


def make_decision(slices: list[dict[str, object]]) -> dict[str, object]:
    clean = clean_slice_by_bucket(slices)
    missing_clean = [bucket for bucket in FAILED_AIR_BUCKETS if not clean_bucket_ready(clean.get(bucket, {}))]
    if missing_clean:
        return {
            "verdict": "repair_or_pivot_before_context_gated_probe",
            "reason": f"S7l lacks enough clean-context evidence for: {', '.join(missing_clean)}.",
            "frogbots_vs_from_scratch": "no_abandon_trigger",
            "next_goal": "Gather or repair clean-context evidence before another controller probe.",
        }
    return {
        "verdict": "ready_to_implement_context_gated_air_transition_probe",
        "reason": (
            "S7k contains enough clean air-transition rows to test a narrower controller primitive, while route-dirty "
            "rows explain why S7j aggregate buckets were misleading. This supports one more bounded Frogbots probe."
        ),
        "frogbots_vs_from_scratch": "continue_frogbots_for_next_bounded_stage",
        "next_goal": (
            "S7m should implement and run the context-gated air-transition probe, then compare clean and route-dirty "
            "slices separately against S7k/S7g baselines."
        ),
    }


def build_report(
    s7k: dict[str, object],
    *,
    stage: str,
    s7k_path: Path | None = None,
) -> dict[str, object]:
    warnings: list[str] = []
    if s7k.get("warnings"):
        warnings.append(f"S7k source has warnings: {s7k.get('warnings')}")
    decision = s7k.get("decision", {}) if isinstance(s7k.get("decision"), dict) else {}
    if decision.get("frogbots_vs_from_scratch") != "continue_frogbots_for_next_bounded_stage":
        warnings.append("S7k did not authorize another bounded Frogbots stage.")
    raw_rows = s7k.get("player_bucket_context", [])
    if not isinstance(raw_rows, list):
        warnings.append("S7k player_bucket_context is not a list.")
        raw_rows = []
    player_rows = [compact_player_row(row) for row in raw_rows if isinstance(row, dict)]
    slices = bucket_context_slices(player_rows)
    return {
        "schema": SCHEMA,
        "stage": stage,
        "map": s7k.get("map", "dm3"),
        "source_s7k_path": portable_path(s7k_path) if s7k_path else "",
        "source_s7k_stage": s7k.get("stage", ""),
        "warnings": warnings,
        "method": (
            "S7l consumes the committed S7k failed-bucket diagnosis and turns it into a design-only context gate "
            "for the next air-transition probe. It does not change KTX, Frogbot behavior, route files, parser "
            "behavior, or lab runners."
        ),
        "context_gate_rules": context_gate_rules(),
        "player_context_rows": player_rows,
        "context_slices": slices,
        "probe_contract": probe_contract(slices),
        "stop_conditions": stop_conditions(),
        "decision_gates": decision_gates(),
        "decision": make_decision(slices),
    }


def validate_report(report: dict[str, object]) -> None:
    warnings = report.get("warnings", [])
    if warnings:
        raise ContextGatedProbeInputError("; ".join(str(warning) for warning in warnings))
    decision = report.get("decision", {}) if isinstance(report.get("decision"), dict) else {}
    if decision.get("verdict") != "ready_to_implement_context_gated_air_transition_probe":
        raise ContextGatedProbeInputError(str(decision.get("reason", "S7l did not produce a ready design.")))


def fmt_speed(value: object) -> str:
    if value is None:
        return ""
    return format_comparison_value("avg_horizontal_speed_qu_per_s", value)


def fmt_ratio(value: object) -> str:
    number = optional_float(value)
    if number is None:
        return ""
    return f"{number:.3f}"


def write_markdown(report: dict[str, object], output_path: Path) -> None:
    contract = report.get("probe_contract", {}) if isinstance(report.get("probe_contract"), dict) else {}
    lines = [
        f"# Context-Gated Probe Design {report.get('stage', '')}",
        "",
        "## Scope",
        "",
        f"- Map: `{report.get('map', '')}`",
        f"- Source S7k diagnosis: `{report.get('source_s7k_path', '')}`",
        f"- {report.get('method', '')}",
        "",
        "## Context Slices",
        "",
        "| Bucket | Slice | Player rows | Segments | Segment ratio | p50 speed |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for row in report.get("context_slices", []):
        if not isinstance(row, dict):
            continue
        p50 = row.get("p50_speed_summary", {}).get("p50") if isinstance(row.get("p50_speed_summary"), dict) else None
        lines.append(
            "| "
            f"`{row.get('bucket', '')}` | "
            f"`{row.get('context_class', '')}` | "
            f"{row.get('player_row_count', 0)} | "
            f"{row.get('segment_count', 0)} | "
            f"{fmt_ratio(row.get('segment_ratio_in_bucket'))} | "
            f"{fmt_speed(p50)} |"
        )

    lines.extend(
        [
            "",
            "## Context Gate Rules",
            "",
        ]
    )
    for rule in report.get("context_gate_rules", []):
        if isinstance(rule, dict):
            lines.append(f"- `{rule.get('id', '')}`: {rule.get('rule', '')}")

    lines.extend(
        [
            "",
            "## Probe Contract",
            "",
            f"- Probe id: `{contract.get('probe_id', '')}`",
            f"- Status: `{contract.get('status', '')}`",
            f"- Follow-up stage: `{contract.get('intended_followup_stage', '')}`",
            f"- Runtime gate: {contract.get('runtime_gate', '')}",
            "",
            "Required clean target buckets:",
            "",
            "| Bucket | Clean rows | Clean segments | Ready for claim |",
            "|---|---:|---:|---|",
        ]
    )
    for row in contract.get("required_clean_target_buckets", []):
        if isinstance(row, dict):
            lines.append(
                "| "
                f"`{row.get('bucket', '')}` | "
                f"{row.get('clean_player_rows', 0)} | "
                f"{row.get('clean_segments', 0)} | "
                f"`{row.get('ready_for_probe_claim', False)}` |"
            )

    lines.extend(["", "Allowed changes:"])
    for item in contract.get("allowed_changes", []):
        lines.append(f"- {item}")
    lines.append("")
    lines.append("Forbidden changes:")
    for item in contract.get("forbidden_changes", []):
        lines.append(f"- {item}")

    lines.extend(["", "## Stop Conditions", ""])
    for condition in report.get("stop_conditions", []):
        if isinstance(condition, dict):
            lines.append(f"- `{condition.get('id', '')}` ({condition.get('verdict', '')}): {condition.get('rule', '')}")

    lines.extend(["", "## Decision Gates", ""])
    for gate in report.get("decision_gates", []):
        if isinstance(gate, dict):
            lines.append(f"- `{gate.get('gate', '')}`: {gate.get('rule', '')}")

    decision = report.get("decision", {}) if isinstance(report.get("decision"), dict) else {}
    lines.extend(
        [
            "",
            "## Decision",
            "",
            f"- Verdict: `{decision.get('verdict', '')}`",
            f"- Frogbots-vs-from-scratch: `{decision.get('frogbots_vs_from_scratch', '')}`",
            f"- Reason: {decision.get('reason', '')}",
            f"- Next goal: {decision.get('next_goal', '')}",
        ]
    )
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Design the S7l context-gated air-transition probe.")
    parser.add_argument("--stage", default="s7l-context-gated-probe-design-dm3", help="Evidence stage label.")
    parser.add_argument("--s7k", type=Path, default=DEFAULT_S7K, help="S7k failed-bucket diagnosis JSON.")
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON, help="Output evidence JSON.")
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD, help="Output evidence Markdown.")
    return parser.parse_args(list(argv))


def main(argv: Iterable[str] = sys.argv[1:]) -> int:
    args = parse_args(argv)
    report = build_report(load_json(args.s7k), stage=args.stage, s7k_path=args.s7k)
    validate_report(report)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_markdown(report, args.output_md)
    print(f"Wrote context-gated probe design: {args.output_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
