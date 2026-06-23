#!/usr/bin/env python3
"""Design the first QWD-derived SNG shortcut server-loop probe.

This is a design gate, not a controller implementation. It consumes the
committed QWD-to-Frogbot mapping evidence and writes a bounded contract for the
next KTX moveprobe mode.
"""

from __future__ import annotations

import logging
import argparse
import json
import math
import sys
from pathlib import Path
from typing import Iterable, Sequence

from summarize_reference_aggregate import portable_path



LOGGER = logging.getLogger(__name__)
SCHEMA = "komodobots.qwd_sng_hybrid_probe_design.v1"
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MAPPING = (
    REPO_ROOT / "experiments" / "qwd_route_probe" / "evidence" / "qwd-frogbot-route-map-dm3-sng-shortcut.json"
)
DEFAULT_OUTPUT_JSON = (
    REPO_ROOT / "experiments" / "qwd_route_probe" / "evidence" / "qwd-sng-hybrid-probe-design-dm3.json"
)
DEFAULT_OUTPUT_MD = (
    REPO_ROOT / "experiments" / "qwd_route_probe" / "evidence" / "qwd-sng-hybrid-probe-design-dm3.md"
)

MAX_CONTROL_POINTS = 16
CONTROL_POINT_RADIUS_QU = 96.0
START_RADIUS_QU = 192.0
MIN_ADVANCED_CONTROL_POINTS = 4
MIN_ACTIVATION_SECONDS = 1.0


class QwdHybridProbeDesignError(RuntimeError):
    """Raised when the QWD mapping cannot support a bounded hybrid probe."""


def load_json(path: Path) -> dict[str, object]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            loaded = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise QwdHybridProbeDesignError(f"Could not read {portable_path(path)} as JSON: {exc}") from exc
    if not isinstance(loaded, dict):
        raise QwdHybridProbeDesignError(f"{portable_path(path)} did not contain a JSON object.")
    return loaded


def optional_float(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def rounded(value: object, digits: int = 3) -> float | None:
    number = optional_float(value)
    if number is None:
        return None
    return round(number, digits)


def count_value(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def finite_point(value: object) -> list[float]:
    if not isinstance(value, list) or len(value) != 3:
        raise QwdHybridProbeDesignError(f"Expected 3D point, got {value!r}.")
    point = [optional_float(component) for component in value]
    if any(component is None for component in point):
        raise QwdHybridProbeDesignError(f"Point contains non-finite values: {value!r}.")
    return [round(float(component), 3) for component in point]


def command_profile(mapping: dict[str, object]) -> dict[str, object]:
    demo_summary = mapping.get("qwd_demo_summary", {}) if isinstance(mapping.get("qwd_demo_summary"), dict) else {}
    commands = demo_summary.get("commands", {}) if isinstance(demo_summary.get("commands"), dict) else {}
    motion = demo_summary.get("motion", {}) if isinstance(demo_summary.get("motion"), dict) else {}
    speed = motion.get("speed_qu_per_s", {}) if isinstance(motion.get("speed_qu_per_s"), dict) else {}
    sidemove = optional_float(commands.get("sidemove_abs_p50"))
    if sidemove is None or sidemove <= 0:
        sidemove = 400.0
    # Keep a small attraction component toward the waypoint even when the human
    # POV command profile is mostly sidemove; pure sidemove cannot advance a
    # waypoint sequence in a generic probe.
    return {
        "nonzero_forward_ratio": rounded(commands.get("nonzero_forward_ratio")),
        "nonzero_side_ratio": rounded(commands.get("nonzero_side_ratio")),
        "jump_button_ratio": rounded(commands.get("jump_button_ratio")),
        "qwd_sidemove_abs_p50": rounded(sidemove),
        "qwd_speed_p50_qu_per_s": rounded(speed.get("p50")),
        "qwd_speed_p95_qu_per_s": rounded(speed.get("p95")),
        "recommended_target_attraction_forwardmove": 320,
        "recommended_qwd_strafe_sidemove": int(round(sidemove)),
        "recommended_jump_policy": "force_jump_only_while_probe_active_and_report_cadence",
    }


def control_points(mapping: dict[str, object], *, max_points: int = MAX_CONTROL_POINTS) -> list[dict[str, object]]:
    sequence = mapping.get("nearest_marker_sequence", [])
    if not isinstance(sequence, list) or not sequence:
        raise QwdHybridProbeDesignError("Mapping evidence has no nearest_marker_sequence.")
    if len(sequence) > max_points:
        raise QwdHybridProbeDesignError(
            f"Control point sequence has {len(sequence)} rows, above max {max_points}; add a thinning rule first."
        )

    points: list[dict[str, object]] = []
    for index, row in enumerate(sequence):
        if not isinstance(row, dict):
            continue
        points.append(
            {
                "index": index,
                "qwd_origin": finite_point(row.get("first_waypoint_origin")),
                "nearest_marker_id": count_value(row.get("marker_id")),
                "nearest_marker_distance_qu": rounded(row.get("nearest_distance_qu")),
                "max_nearest_distance_qu": rounded(row.get("max_nearest_distance_qu")),
                "first_frame": row.get("first_frame"),
                "last_frame": row.get("last_frame"),
                "first_time_s": rounded(row.get("first_time_s")),
                "last_time_s": rounded(row.get("last_time_s")),
                "waypoint_count": count_value(row.get("waypoint_count")),
            }
        )
    if len(points) < MIN_ADVANCED_CONTROL_POINTS:
        raise QwdHybridProbeDesignError(
            f"Only {len(points)} control points found; need at least {MIN_ADVANCED_CONTROL_POINTS} for a useful probe."
        )
    return points


def encode_point_string(points: Sequence[dict[str, object]]) -> str:
    encoded = []
    for row in points:
        point = row.get("qwd_origin")
        if not isinstance(point, list) or len(point) != 3:
            raise QwdHybridProbeDesignError("Control point missing qwd_origin.")
        encoded.append(",".join(f"{float(component):.3f}" for component in point))
    return ";".join(encoded)


def mapping_summary(mapping: dict[str, object]) -> dict[str, object]:
    summary = mapping.get("mapping_summary", {}) if isinstance(mapping.get("mapping_summary"), dict) else {}
    distance = (
        summary.get("nearest_marker_distance_qu", {})
        if isinstance(summary.get("nearest_marker_distance_qu"), dict)
        else {}
    )
    graph = summary.get("bot_graph_alignment", {}) if isinstance(summary.get("bot_graph_alignment"), dict) else {}
    recommendation = mapping.get("recommendation", {}) if isinstance(mapping.get("recommendation"), dict) else {}
    return {
        "qwd_waypoint_count": count_value(summary.get("waypoint_count")),
        "collapsed_marker_count": count_value(summary.get("collapsed_marker_count")),
        "transition_count": count_value(summary.get("transition_count")),
        "nearest_marker_p50_qu": rounded(distance.get("p50")),
        "nearest_marker_p95_qu": rounded(distance.get("p95")),
        "nearest_marker_max_qu": rounded(distance.get("max")),
        "within_128_ratio": rounded(distance.get("within_128_ratio")),
        "direct_edge_ratio": rounded(graph.get("direct_edge_ratio")),
        "graph_reachable_ratio": rounded(graph.get("graph_reachable_ratio")),
        "shortest_path_edges_p50": rounded(graph.get("shortest_path_edges_p50")),
        "source_recommendation": recommendation.get("next_probe", ""),
        "source_recommendation_confidence": recommendation.get("confidence", ""),
    }


def validate_mapping(mapping: dict[str, object], summary: dict[str, object]) -> list[str]:
    warnings: list[str] = []
    if mapping.get("schema") != "komodobots.qwd_frogbot_route_mapping.v1":
        warnings.append(f"Unexpected mapping schema: {mapping.get('schema')!r}.")
    if summary.get("source_recommendation") != "hybrid_waypoint_controller_probe":
        warnings.append("Mapping evidence did not recommend a hybrid waypoint/controller probe.")
    if (optional_float(summary.get("direct_edge_ratio")) or 0.0) >= 0.6:
        warnings.append("Direct edge ratio is high enough that pure route following should be reconsidered.")
    if (optional_float(summary.get("within_128_ratio")) or 0.0) < 0.75:
        warnings.append("Marker fit is too weak for Frogbot spatial context.")
    return warnings


def probe_contract(points: list[dict[str, object]], profile: dict[str, object]) -> dict[str, object]:
    return {
        "probe_id": "qwd-dm3-sng-hybrid-waypoint-controller",
        "intended_followup": "Implement one temporary KTX moveprobe mode, likely mode 9.",
        "status": "design_only_no_controller_behavior_changed",
        "runtime_shape": [
            "Do not edit dm3.bot.",
            "Use cvar_string to read a bounded semicolon-separated QWD waypoint string.",
            "Activate only when the bot is on dm3 and within the start radius of control point 0.",
            "Advance control points only when the bot enters the control-point radius.",
            "Project waypoint-attraction plus QWD-style sidemove into the bot's preserved combat view yaw.",
            "Preserve route, water, command, probe-activation, cadence, and movement-bucket diagnostics.",
        ],
        "suggested_cvars": {
            "k_fb_moveprobe_mode": 9,
            "k_fb_moveprobe_qwd_waypoints": encode_point_string(points),
            "k_fb_moveprobe_qwd_point_radius": CONTROL_POINT_RADIUS_QU,
            "k_fb_moveprobe_qwd_start_radius": START_RADIUS_QU,
            "k_fb_moveprobe_forwardmove": profile.get("recommended_target_attraction_forwardmove"),
            "k_fb_moveprobe_sidemove": profile.get("recommended_qwd_strafe_sidemove"),
            "k_fb_moveprobe_log_commands": 1,
            "k_fb_moveprobe_log_interval": 0.1,
        },
        "allowed_changes": [
            "One temporary moveprobe mode for the SNG shortcut.",
            "One extra `qwd=` command-log suffix with active flag, control-point index, distance, and completion state.",
            "Runner cvars only if needed to pass the waypoint string and radius values.",
            "A comparison helper that scores QWD path distance, control-point advancement, speed, route/water state, and cadence.",
        ],
        "forbidden_changes": [
            "No `dm3.bot` route mutation.",
            "No broad Frogbot route rewrite.",
            "No combat/aim/item/spawn behavior change in the same PR.",
            "No claim that the bot learned SNG from QWD unless a server-loop MVD proves execution.",
            "No expansion to all DM3 QWD moves until the SNG probe produces positive server-loop evidence.",
        ],
    }


def validation_plan() -> list[dict[str, object]]:
    return [
        {
            "step": "patch_compile",
            "command": "Build patched KTX with the temporary mode enabled.",
            "required_result": "Build succeeds and stock mode 0 remains available.",
        },
        {
            "step": "server_loop_run",
            "command": (
                "python scripts/run_bot_lab.py --map dm3 --duration 45 --bot-count 2 "
                "--bot-spacing 6 --moveprobe-mode 9 --moveprobe-sidemove 508 "
                "--moveprobe-log-commands --moveprobe-log-interval 0.1"
            ),
            "required_result": "Run produces MVD, movement metrics, moveprobe command logs, and qwd probe rows.",
        },
        {
            "step": "trajectory_scoring",
            "command": "Compare bot movement against the committed QWD control points and QWD speed profile.",
            "required_result": (
                f"At least {MIN_ADVANCED_CONTROL_POINTS} control points advanced or result is inconclusive; "
                f"probe active for at least {MIN_ACTIVATION_SECONDS:.1f}s or result is inconclusive."
            ),
        },
        {
            "step": "guardrails",
            "command": "Score route, water, cadence, and movement buckets beside the QWD trajectory score.",
            "required_result": "No success claim if route/water/cadence diagnostics are missing or regress badly.",
        },
    ]


def stop_conditions() -> list[dict[str, object]]:
    return [
        {
            "id": "no_server_loop_execution",
            "verdict": "inconclusive",
            "rule": "If the bot never activates or advances fewer than four control points, do not call the move learned.",
        },
        {
            "id": "waypoint_only_success",
            "verdict": "reject",
            "rule": "Reject success if the bot reaches points only by slow/stuck movement that fails movement-bucket checks.",
        },
        {
            "id": "diagnostic_loss",
            "verdict": "inconclusive",
            "rule": "Missing command, route, water, cadence, or qwd probe diagnostics blocks success claims.",
        },
        {
            "id": "route_or_water_regression",
            "verdict": "reject_or_route_handoff",
            "rule": "If WATER_PATH or low-dir route slices dominate failure, pivot to a route primitive instead of widening QWD control.",
        },
        {
            "id": "positive_sng_gate",
            "verdict": "continue_to_more_dm3_qwds",
            "rule": "Only after SNG has positive server-loop evidence should the automation attempt the other DM3 QWD moves.",
        },
    ]


def decision(mapping: dict[str, object], summary: dict[str, object]) -> dict[str, object]:
    warnings = validate_mapping(mapping, summary)
    if warnings:
        return {
            "verdict": "blocked_before_runtime_probe",
            "warnings": warnings,
            "next_goal": "Repair or rerun QWD mapping before a server-loop probe.",
            "frogbots_vs_from_scratch": "no_new_signal",
        }
    return {
        "verdict": "ready_to_implement_qwd_sng_hybrid_server_loop_probe",
        "warnings": [],
        "reason": (
            "The SNG QWD trajectory is close enough to Frogbot marker space for context, but direct route topology "
            "does not match the shortcut and the human command profile is side-move dominant. The next evidence "
            "must therefore execute a temporary hybrid waypoint/controller probe inside KTX."
        ),
        "next_goal": (
            "Implement mode 9 plus a comparison helper, run the SNG shortcut probe on dm3, then ask Claude to review "
            "whether server-loop evidence justifies trying the remaining DM3 QWD moves."
        ),
        "frogbots_vs_from_scratch": "continue_frogbots_for_qwd_sng_runtime_probe",
    }


def build_report(mapping: dict[str, object], *, stage: str, mapping_path: Path | None = None) -> dict[str, object]:
    points = control_points(mapping)
    profile = command_profile(mapping)
    summary = mapping_summary(mapping)
    return {
        "schema": SCHEMA,
        "stage": stage,
        "map": "dm3",
        "source_mapping_path": portable_path(mapping_path) if mapping_path else "",
        "source_demo": mapping.get("source", {}).get("demo", "") if isinstance(mapping.get("source"), dict) else "",
        "source_demo_sha256": (
            mapping.get("source", {}).get("demo_sha256", "") if isinstance(mapping.get("source"), dict) else ""
        ),
        "method": (
            "Consume the committed SNG QWD-to-Frogbot mapping and write a design-only contract for the first "
            "server-loop hybrid waypoint/controller probe. This does not change KTX, Frogbot behavior, route data, "
            "lab runners, or parser behavior."
        ),
        "mapping_summary": summary,
        "qwd_command_profile": profile,
        "control_points": points,
        "probe_contract": probe_contract(points, profile),
        "validation_plan": validation_plan(),
        "stop_conditions": stop_conditions(),
        "decision": decision(mapping, summary),
    }


def validate_report(report: dict[str, object]) -> None:
    decision_row = report.get("decision", {}) if isinstance(report.get("decision"), dict) else {}
    warnings = decision_row.get("warnings", [])
    if warnings:
        raise QwdHybridProbeDesignError("; ".join(str(warning) for warning in warnings))
    if decision_row.get("verdict") != "ready_to_implement_qwd_sng_hybrid_server_loop_probe":
        raise QwdHybridProbeDesignError(str(decision_row.get("reason", "QWD SNG probe design is not ready.")))


def render_markdown(report: dict[str, object]) -> str:
    decision_row = report["decision"]
    summary = report["mapping_summary"]
    profile = report["qwd_command_profile"]
    contract = report["probe_contract"]
    lines = [
        "# QWD SNG Hybrid Probe Design",
        "",
        "## Scope",
        "",
        f"- Map: `{report['map']}`.",
        f"- Source mapping: `{report['source_mapping_path']}`.",
        f"- Source demo: `{report['source_demo']}`.",
        f"- {report['method']}",
        "",
        "## Mapping Inputs",
        "",
        f"- Control points: `{len(report['control_points'])}`.",
        f"- QWD waypoints in source mapping: `{summary['qwd_waypoint_count']}`.",
        f"- Nearest-marker p50/p95/max: `{summary['nearest_marker_p50_qu']}` / `{summary['nearest_marker_p95_qu']}` / `{summary['nearest_marker_max_qu']}` qu.",
        f"- Direct `.bot` edge ratio: `{summary['direct_edge_ratio']}`.",
        f"- Graph reachable ratio: `{summary['graph_reachable_ratio']}`.",
        f"- QWD nonzero forward/side/jump: `{profile['nonzero_forward_ratio']}` / `{profile['nonzero_side_ratio']}` / `{profile['jump_button_ratio']}`.",
        f"- Recommended forward/side commands: `{profile['recommended_target_attraction_forwardmove']}` / `{profile['recommended_qwd_strafe_sidemove']}`.",
        "",
        "## Probe Contract",
        "",
        f"- Probe id: `{contract['probe_id']}`.",
        f"- Status: `{contract['status']}`.",
        f"- Follow-up: {contract['intended_followup']}",
        "",
        "Runtime shape:",
        "",
    ]
    lines.extend(f"- {item}" for item in contract["runtime_shape"])
    lines.extend(
        [
            "",
            "Suggested cvars:",
            "",
            "| cvar | value |",
            "|---|---|",
        ]
    )
    for key, value in contract["suggested_cvars"].items():
        display = str(value)
        if key == "k_fb_moveprobe_qwd_waypoints" and len(display) > 96:
            display = display[:96] + "..."
        lines.append(f"| `{key}` | `{display}` |")

    lines.extend(["", "Control points:", "", "| # | origin | nearest marker | marker distance |", "|---:|---|---:|---:|"])
    for row in report["control_points"]:
        origin = ",".join(str(component) for component in row["qwd_origin"])
        lines.append(
            f"| {row['index']} | `{origin}` | {row['nearest_marker_id']} | {row['nearest_marker_distance_qu']} |"
        )

    lines.extend(["", "## Validation Plan", ""])
    for step in report["validation_plan"]:
        lines.append(f"- `{step['step']}`: {step['required_result']}")
    lines.extend(["", "## Stop Conditions", ""])
    for condition in report["stop_conditions"]:
        lines.append(f"- `{condition['id']}` ({condition['verdict']}): {condition['rule']}")
    lines.extend(
        [
            "",
            "## Decision",
            "",
            f"- Verdict: `{decision_row['verdict']}`.",
            f"- Frogbots-vs-from-scratch: `{decision_row['frogbots_vs_from_scratch']}`.",
            f"- Reason: {decision_row['reason']}",
            f"- Next goal: {decision_row['next_goal']}",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Design the QWD SNG hybrid server-loop probe.")
    parser.add_argument("--stage", default="qwd-dm3-sng-hybrid-probe-design", help="Evidence stage label.")
    parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING, help="QWD-to-Frogbot mapping JSON.")
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON, help="Output evidence JSON.")
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD, help="Output evidence Markdown.")
    return parser.parse_args(list(argv))


def main(argv: Iterable[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    args = parse_args(argv)
    report = build_report(load_json(args.mapping), stage=args.stage, mapping_path=args.mapping)
    validate_report(report)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.output_md.write_text(render_markdown(report) + "\n", encoding="utf-8")
    print(f"Wrote QWD SNG hybrid probe design: {args.output_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
