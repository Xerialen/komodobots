#!/usr/bin/env python3
"""Design the S7i air-transition horizontal-speed probe."""

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
SCHEMA = "komodobots.air_transition_probe_design.v1"
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_S7G = REPO_ROOT / "experiments" / "human_comparison" / "evidence" / "land-speed-gap-s7g-dm3.json"
DEFAULT_S7H = REPO_ROOT / "experiments" / "human_comparison" / "evidence" / "controller-probe-target-s7h-dm3.json"
DEFAULT_S7E = REPO_ROOT / "experiments" / "human_comparison" / "evidence" / "cadence-evidence-s7e-dm3.json"
DEFAULT_OUTPUT_JSON = REPO_ROOT / "experiments" / "human_comparison" / "evidence" / "air-transition-probe-design-s7i-dm3.json"
DEFAULT_OUTPUT_MD = REPO_ROOT / "experiments" / "human_comparison" / "evidence" / "air-transition-probe-design-s7i-dm3.md"

AIR_BUCKETS = (
    ("pre_air_window_segments", "Pre-air window"),
    ("airborne_proxy_segments", "Airborne-proxy segments"),
    ("post_air_window_segments", "Post-air window"),
)
GUARDRAIL_BUCKETS = (
    ("all_segments", "All accepted segments"),
    ("non_airborne_segments", "Non-airborne segments"),
    ("route_low_dir_speed_segments", "Route low-dir-speed segments"),
    ("route_water_path_segments", "Route WATER_PATH segments"),
)


class ProbeDesignInputError(RuntimeError):
    """Raised when S7i cannot derive a safe probe design."""


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


def summary_value(summary: dict[str, object], key: str) -> float | None:
    return rounded(summary.get(key))


def summary_count(summary: dict[str, object]) -> int:
    try:
        return int(summary.get("count", 0))
    except (TypeError, ValueError):
        return 0


def comparison_bucket(source: dict[str, object], key: str) -> dict[str, object]:
    comparison = source.get("comparison", {}) if isinstance(source.get("comparison"), dict) else {}
    value = comparison.get(key, {}) if isinstance(comparison.get(key), dict) else {}
    return value


def player_summary(bucket: dict[str, object], side: str) -> dict[str, object]:
    field = "reference_player_p50_speed" if side == "reference" else "bot_player_p50_speed"
    value = bucket.get(field, {}) if isinstance(bucket.get(field), dict) else {}
    return value


def bucket_baseline(source: dict[str, object], key: str, label: str) -> dict[str, object]:
    bucket = comparison_bucket(source, key)
    reference = player_summary(bucket, "reference")
    bot = player_summary(bucket, "bot")
    return {
        "bucket": key,
        "label": label,
        "reference_player_count": summary_count(reference),
        "bot_player_count": summary_count(bot),
        "reference_p50_speed_qu_per_s": summary_value(reference, "p50"),
        "bot_p50_speed_qu_per_s": summary_value(bot, "p50"),
        "bot_to_reference_p50_ratio": rounded(bucket.get("bot_to_reference_p50_ratio")),
    }


def cadence_axis(source: dict[str, object], field: str) -> dict[str, object]:
    for axis in source.get("cadence_axes", []):
        if isinstance(axis, dict) and axis.get("field") == field:
            reference = axis.get("reference", {}) if isinstance(axis.get("reference"), dict) else {}
            bot = axis.get("bot", {}) if isinstance(axis.get("bot"), dict) else {}
            return {
                "field": field,
                "label": axis.get("label", field),
                "bot_relation": axis.get("bot_relation", ""),
                "reference_min": summary_value(reference, "min"),
                "reference_max": summary_value(reference, "max"),
                "bot_min": summary_value(bot, "min"),
                "bot_max": summary_value(bot, "max"),
            }
    return {
        "field": field,
        "label": field,
        "bot_relation": "unavailable",
        "reference_min": None,
        "reference_max": None,
        "bot_min": None,
        "bot_max": None,
    }


def s7h_selected_target(source: dict[str, object]) -> str:
    decision = source.get("decision", {}) if isinstance(source.get("decision"), dict) else {}
    return str(decision.get("selected_target", ""))


def require_selected_air_target(s7h: dict[str, object]) -> list[str]:
    selected = s7h_selected_target(s7h)
    if selected == "air_transition_horizontal_speed":
        return []
    return [f"S7h selected `{selected}` instead of `air_transition_horizontal_speed`."]


def build_probe_contract() -> dict[str, object]:
    return {
        "probe_id": "s7i-mode8-air-transition-horizontal-speed",
        "intended_followup_stage": "S7j",
        "status": "design_only_no_controller_behavior_changed",
        "implementation_hint": (
            "Start from moveprobe mode 7. Add at most one temporary mode-8 or mode-7-variant branch that changes "
            "horizontal command budget only during takeoff/air-transition windows. Keep combat view yaw, route "
            "projection, no-backpedal folding, command bounding outside the transition window, jump-button policy, "
            "route logging, water logging, and cadence reporting unchanged."
        ),
        "allowed_changes": [
            "A short-lived air-transition horizontal command-budget probe, preferably behind a new cvar or mode.",
            "Additional diagnostic fields only if they are needed to prove the transition window fired.",
        ],
        "forbidden_changes": [
            "No cadence controller or jump timing change.",
            "No route file or WATER_PATH route primitive fix.",
            "No all-segment speed objective.",
            "No combat aiming, firing, item, spawn, parser, or lab-runner behavior change.",
        ],
    }


def stop_conditions(baselines: dict[str, dict[str, object]]) -> list[dict[str, object]]:
    water = baselines["route_water_path_segments"]
    non_air = baselines["non_airborne_segments"]
    return [
        {
            "id": "missing_required_reporting",
            "verdict": "reject_or_inconclusive",
            "rule": (
                "Reject success claims if the post-probe comparison omits pre-air, airborne, post-air, non-air, "
                "cadence, route low-dir-speed, or WATER_PATH reporting."
            ),
        },
        {
            "id": "all_segment_proxy_win",
            "verdict": "reject",
            "rule": (
                "Reject any result where all-segment p50 speed improves but none of pre-air, airborne, or post-air "
                "p50 speed improves over the S7g baseline."
            ),
        },
        {
            "id": "air_transition_regression",
            "verdict": "reject",
            "rule": (
                "Reject if any required air-transition bucket p50 drops by more than 5 percent versus S7g baseline."
            ),
            "baseline_buckets": [key for key, _label in AIR_BUCKETS],
            "tolerance_ratio": 0.95,
        },
        {
            "id": "non_airborne_guardrail",
            "verdict": "reject",
            "rule": "Reject if non-airborne p50 falls more than 5 percent below the S7g baseline.",
            "baseline_p50_speed_qu_per_s": non_air["bot_p50_speed_qu_per_s"],
            "tolerance_ratio": 0.95,
        },
        {
            "id": "water_path_guardrail",
            "verdict": "reject_or_inconclusive",
            "rule": (
                "Reject if WATER_PATH p50 speed falls more than 5 percent below baseline when WATER_PATH evidence "
                "is present. Treat a run with missing route/WATER_PATH diagnostics as inconclusive rather than ready."
            ),
            "baseline_p50_speed_qu_per_s": water["bot_p50_speed_qu_per_s"],
            "baseline_player_count": water["bot_player_count"],
            "tolerance_ratio": 0.95,
        },
        {
            "id": "cadence_still_diagnostic",
            "verdict": "reject_or_inconclusive",
            "rule": (
                "Do not claim success from cadence changes. Cadence must remain reported on the same active, "
                "movement-time, and airborne-proxy bases so S7d/S7e warnings stay visible."
            ),
        },
    ]


def build_report(
    s7g: dict[str, object],
    s7h: dict[str, object],
    s7e: dict[str, object],
    *,
    stage: str,
    s7g_path: Path | None = None,
    s7h_path: Path | None = None,
    s7e_path: Path | None = None,
) -> dict[str, object]:
    warnings: list[str] = []
    for name, source in (("S7g", s7g), ("S7h", s7h), ("S7e", s7e)):
        source_warnings = source.get("warnings", [])
        if source_warnings:
            warnings.append(f"{name} source has warnings: {source_warnings}")
    warnings.extend(require_selected_air_target(s7h))

    air_baselines = {
        key: bucket_baseline(s7g, key, label)
        for key, label in AIR_BUCKETS
    }
    guardrail_baselines = {
        key: bucket_baseline(s7g, key, label)
        for key, label in GUARDRAIL_BUCKETS
    }
    baselines = {**air_baselines, **guardrail_baselines}
    cadence_baselines = [
        cadence_axis(s7e, "jump_cadence_per_min"),
        cadence_axis(s7e, "jump_cadence_per_non_low_speed_min"),
        cadence_axis(s7e, "jump_cadence_per_airborne_proxy_min"),
    ]
    decision = {
        "verdict": "ready_to_design_tiny_air_transition_probe" if not warnings else "needs_more_probe_design_input",
        "selected_probe_target": "air_transition_horizontal_speed",
        "reason": (
            "S7h selected a human-comparable air-transition speed gap; S7i turns that into a constrained probe "
            "contract with explicit guardrails before any controller behavior changes."
        ),
        "next_goal": (
            "S7j should implement and run the tiny air-transition probe only if it preserves the S7i contract, "
            "then compare it against the S7g/S7h/S7e baselines."
        ),
    }
    return {
        "schema": SCHEMA,
        "stage": stage,
        "map": s7g.get("map", s7h.get("map", "")),
        "source_land_speed_path": portable_path(s7g_path) if s7g_path else "",
        "source_target_decision_path": portable_path(s7h_path) if s7h_path else "",
        "source_cadence_path": portable_path(s7e_path) if s7e_path else "",
        "source_land_speed_stage": s7g.get("stage", ""),
        "source_target_decision_stage": s7h.get("stage", ""),
        "source_cadence_stage": s7e.get("stage", ""),
        "warnings": warnings,
        "method": (
            "S7i consumes committed S7g/S7h/S7e evidence and writes a constrained probe design. It does not "
            "change KTX, Frogbot behavior, lab runners, parser behavior, or cadence policy."
        ),
        "air_transition_baselines": air_baselines,
        "guardrail_baselines": guardrail_baselines,
        "cadence_baselines": cadence_baselines,
        "probe_contract": build_probe_contract(),
        "required_post_probe_measurements": [
            "pre_air_window_segments",
            "airborne_proxy_segments",
            "post_air_window_segments",
            "non_airborne_segments",
            "route_low_dir_speed_segments",
            "route_water_path_segments",
            "jump_cadence_per_min",
            "jump_cadence_per_non_low_speed_min",
            "jump_cadence_per_airborne_proxy_min",
        ],
        "stop_conditions": stop_conditions(baselines),
        "decision": decision,
    }


def validate_report(report: dict[str, object]) -> None:
    warnings = report.get("warnings", [])
    if warnings:
        raise ProbeDesignInputError("; ".join(str(warning) for warning in warnings))
    if report.get("decision", {}).get("verdict") != "ready_to_design_tiny_air_transition_probe":
        raise ProbeDesignInputError("S7i did not produce a ready probe design.")


def fmt_speed(value: object) -> str:
    return format_comparison_value("avg_horizontal_speed_qu_per_s", value)


def fmt_ratio(value: object) -> str:
    number = optional_float(value)
    if number is None:
        return ""
    return f"{number:.3f}"


def write_markdown(report: dict[str, object], output_path: Path) -> None:
    contract = report.get("probe_contract", {}) if isinstance(report.get("probe_contract"), dict) else {}
    lines = [
        f"# Air-Transition Probe Design {report.get('stage', '')}",
        "",
        "## Scope",
        "",
        f"- Map: `{report.get('map', '')}`",
        f"- Source S7g evidence: `{report.get('source_land_speed_path', '')}`",
        f"- Source S7h decision: `{report.get('source_target_decision_path', '')}`",
        f"- Source S7e cadence evidence: `{report.get('source_cadence_path', '')}`",
        f"- {report.get('method', '')}",
        "",
        "## Baseline Buckets",
        "",
        "| Bucket | Reference rows | Bot rows | Reference p50 | Bot p50 | Bot/ref p50 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for group_name in ("air_transition_baselines", "guardrail_baselines"):
        group = report.get(group_name, {}) if isinstance(report.get(group_name), dict) else {}
        for baseline in group.values():
            if not isinstance(baseline, dict):
                continue
            lines.append(
                "| "
                f"{baseline.get('label', '')} | "
                f"{baseline.get('reference_player_count', 0)} | "
                f"{baseline.get('bot_player_count', 0)} | "
                f"{fmt_speed(baseline.get('reference_p50_speed_qu_per_s'))} | "
                f"{fmt_speed(baseline.get('bot_p50_speed_qu_per_s'))} | "
                f"{fmt_ratio(baseline.get('bot_to_reference_p50_ratio'))} |"
            )

    lines.extend(
        [
            "",
            "## Probe Contract",
            "",
            f"- Probe id: `{contract.get('probe_id', '')}`",
            f"- Status: `{contract.get('status', '')}`",
            f"- Follow-up stage: `{contract.get('intended_followup_stage', '')}`",
            f"- Implementation hint: {contract.get('implementation_hint', '')}",
            "",
            "Allowed changes:",
        ]
    )
    for item in contract.get("allowed_changes", []):
        lines.append(f"- {item}")
    lines.append("")
    lines.append("Forbidden changes:")
    for item in contract.get("forbidden_changes", []):
        lines.append(f"- {item}")

    lines.extend(
        [
            "",
            "## Cadence Baseline",
            "",
            "| Axis | Reference range | Bot range | Bot relation |",
            "|---|---:|---:|---|",
        ]
    )
    for axis in report.get("cadence_baselines", []):
        if not isinstance(axis, dict):
            continue
        field = str(axis.get("field", ""))
        lines.append(
            "| "
            f"{axis.get('label', field)} | "
            f"{format_comparison_value(field, axis.get('reference_min'))}-"
            f"{format_comparison_value(field, axis.get('reference_max'))} | "
            f"{format_comparison_value(field, axis.get('bot_min'))}-"
            f"{format_comparison_value(field, axis.get('bot_max'))} | "
            f"`{axis.get('bot_relation', '')}` |"
        )

    lines.extend(["", "## Stop Conditions", ""])
    for condition in report.get("stop_conditions", []):
        if not isinstance(condition, dict):
            continue
        lines.append(f"- `{condition.get('id', '')}` ({condition.get('verdict', '')}): {condition.get('rule', '')}")

    decision = report.get("decision", {}) if isinstance(report.get("decision"), dict) else {}
    lines.extend(
        [
            "",
            "## Decision",
            "",
            f"- Verdict: `{decision.get('verdict', '')}`",
            f"- Selected probe target: `{decision.get('selected_probe_target', '')}`",
            f"- Reason: {decision.get('reason', '')}",
            f"- Next goal: {decision.get('next_goal', '')}",
        ]
    )
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Design the S7i air-transition horizontal-speed probe.")
    parser.add_argument("--stage", default="s7i-air-transition-probe-design-dm3", help="Evidence stage label.")
    parser.add_argument("--s7g", type=Path, default=DEFAULT_S7G, help="S7g land-speed evidence JSON.")
    parser.add_argument("--s7h", type=Path, default=DEFAULT_S7H, help="S7h target-decision evidence JSON.")
    parser.add_argument("--s7e", type=Path, default=DEFAULT_S7E, help="S7e cadence evidence JSON.")
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON, help="Output evidence JSON.")
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD, help="Output evidence Markdown.")
    return parser.parse_args(list(argv))


def load_json(path: Path) -> dict[str, object]:
    with path.open("r", encoding="utf-8") as handle:
        loaded = json.load(handle)
    if not isinstance(loaded, dict):
        raise ProbeDesignInputError(f"{path} did not contain a JSON object.")
    return loaded


def main(argv: Iterable[str] = sys.argv[1:]) -> int:
    args = parse_args(argv)
    report = build_report(
        load_json(args.s7g),
        load_json(args.s7h),
        load_json(args.s7e),
        stage=args.stage,
        s7g_path=args.s7g,
        s7h_path=args.s7h,
        s7e_path=args.s7e,
    )
    validate_report(report)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_markdown(report, args.output_md)
    print(f"Wrote air-transition probe design: {args.output_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
