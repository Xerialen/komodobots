#!/usr/bin/env python3
"""Broaden S7 cadence evidence with existing mode-7 bot reruns."""

from __future__ import annotations

import logging
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable

from analyze_human_mvd import format_comparison_value, load_json_if_present
from decide_cadence_normalization import (
    add_derived_axes,
    build_normalization_axes,
    classify_against_reference,
    rounded,
    summarize_values,
)
from summarize_reference_aggregate import portable_path



LOGGER = logging.getLogger(__name__)
SCHEMA = "komodobots.cadence_evidence_broadening.v1"
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REFERENCE_AGGREGATE = (
    REPO_ROOT
    / "experiments"
    / "human_comparison"
    / "evidence"
    / "human-reference-s7c-bot-comparable-cadence-dm3-aggregate.json"
)
DEFAULT_ARTIFACTS_ROOT = REPO_ROOT / "artifacts" / "lab-runs"
DEFAULT_BOT_RUN_IDS = (
    "20260606T003718Z",
    "20260606T031102Z",
    "20260606T041805Z",
)
DEFAULT_EXCLUDED_RUNS = {
    "20260606T044000Z": (
        "S6e preserved native water-edge vertical command intent, so it is a mode-7 variant "
        "rather than an unchanged diagnostic rerun."
    )
}
BOT_ROW_FIELDS = (
    "avg_horizontal_speed_qu_per_s",
    "p95_horizontal_speed_qu_per_s",
    "stationary_time_ratio",
    "low_speed_time_ratio",
    "airborne_proxy_time_ratio",
    "airborne_proxy_count",
    "jump_cadence_per_min",
    "avg_airborne_proxy_duration_ms",
    "avg_airborne_proxy_z_delta_qu",
    "avg_landing_pre_speed_qu_per_s",
    "avg_landing_post_speed_qu_per_s",
    "avg_post_landing_speed_delta_qu_per_s",
    "avg_post_landing_speed_loss_ratio",
)


def comparison_axis(
    reference_rows: list[dict[str, object]],
    bot_rows: list[dict[str, object]],
    *,
    field: str,
    label: str,
    basis: str,
) -> dict[str, object]:
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

    usable = [value for value in classifications if value != "unavailable"]
    if not usable:
        relation = "no_bot_comparison"
    elif all(value == "within_reference_range" for value in usable):
        relation = "all_bots_within_reference_range"
    elif all(value == "above_reference_max" for value in usable):
        relation = "all_bots_above_reference_range"
    elif all(value == "below_reference_min" for value in usable):
        relation = "all_bots_below_reference_range"
    else:
        relation = "mixed_bot_relation"

    return {
        "field": field,
        "label": label,
        "basis": basis,
        "reference": reference_summary,
        "bot": bot_summary,
        "bot_relation": relation,
        "bot_rows": bot_rows_for_axis,
    }


def movement_metrics_path(artifacts_root: Path, run_id: str) -> Path:
    return artifacts_root / run_id / "movement-metrics.json"


def compact_bot_row(player: dict[str, object], *, run_id: str, metrics_path: Path, map_command: str) -> dict[str, object]:
    row: dict[str, object] = {
        "player": player.get("name", ""),
        "run_id": run_id,
        "map": map_command,
        "source_metrics_path": portable_path(metrics_path),
        "mode_family": "dm3_mode7_unchanged_diagnostic_rerun",
    }
    for field in BOT_ROW_FIELDS:
        row[field] = rounded(player.get(field))
    return add_derived_axes(row)


def load_bot_rows(run_ids: list[str], artifacts_root: Path) -> tuple[list[dict[str, object]], list[str]]:
    rows: list[dict[str, object]] = []
    warnings: list[str] = []
    for run_id in run_ids:
        metrics_path = movement_metrics_path(artifacts_root, run_id)
        metrics = load_json_if_present(metrics_path)
        if not metrics:
            warnings.append(f"Missing or unreadable movement metrics for run `{run_id}` at `{portable_path(metrics_path)}`.")
            continue
        run = metrics.get("run", {}) if isinstance(metrics.get("run"), dict) else {}
        map_command = str(run.get("map_command", ""))
        if map_command != "dm3":
            warnings.append(f"Run `{run_id}` is `{map_command}`, not `dm3`; row kept but map mismatch should be reviewed.")
        players = metrics.get("players", [])
        if not isinstance(players, list):
            warnings.append(f"Run `{run_id}` has no player list in `{portable_path(metrics_path)}`.")
            continue
        for player in players:
            if isinstance(player, dict) and not player.get("spectator", False):
                rows.append(compact_bot_row(player, run_id=run_id, metrics_path=metrics_path, map_command=map_command))
    return rows, warnings


def grouped_player_summary(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    fields = (
        "jump_cadence_per_min",
        "jump_cadence_per_airborne_proxy_min",
        "airborne_proxy_time_ratio",
        "avg_airborne_proxy_duration_ms",
        "avg_horizontal_speed_qu_per_s",
        "p95_horizontal_speed_qu_per_s",
    )
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("player", ""))].append(row)
    summaries = []
    for player, player_rows in sorted(grouped.items()):
        summary = {"player": player, "count": len(player_rows), "run_ids": [row.get("run_id", "") for row in player_rows]}
        for field in fields:
            summary[field] = summarize_values(player_rows, field)
        summaries.append(summary)
    return summaries


def make_decision(axes: list[dict[str, object]], bot_rows: list[dict[str, object]]) -> dict[str, object]:
    by_field = {str(axis.get("field")): axis for axis in axes}
    raw_relation = str(by_field.get("jump_cadence_per_min", {}).get("bot_relation", ""))
    moving_relation = str(by_field.get("jump_cadence_per_non_low_speed_min", {}).get("bot_relation", ""))
    air_relation = str(by_field.get("jump_cadence_per_airborne_proxy_min", {}).get("bot_relation", ""))
    bot_count = len(bot_rows)
    if air_relation == "all_bots_above_reference_range" and bot_count >= 6:
        return {
            "verdict": "cadence_stays_diagnostic_after_broadened_mode7_rows",
            "reason": (
                "The broadened unchanged mode-7 dm3 bot set keeps every bot row above the exact-player "
                "airborne-proxy-normalized cadence range, while raw and movement-time cadence remain mixed. "
                "This strengthens S7d's warning that cadence is entangled with air-rhythm/proxy segmentation "
                "and should not become a controller target yet."
            ),
            "next_goal": (
                "S7f should inspect raw airborne-proxy segment distributions, or pivot to the larger land-speed "
                "gap, before any cadence controller probe."
            ),
            "raw_cadence_relation": raw_relation,
            "movement_time_relation": moving_relation,
            "airborne_proxy_relation": air_relation,
        }
    return {
        "verdict": "needs_more_s7e_evidence",
        "reason": "The broadened bot rows do not yet produce a stable enough relation for a controller decision.",
        "next_goal": "Add more bot rows or inspect raw airborne-proxy segments before controller work.",
        "raw_cadence_relation": raw_relation,
        "movement_time_relation": moving_relation,
        "airborne_proxy_relation": air_relation,
    }


def build_report(
    reference_aggregate: dict[str, object],
    *,
    stage: str,
    bot_run_ids: list[str],
    artifacts_root: Path,
    reference_aggregate_path: Path | None = None,
) -> dict[str, object]:
    reference_rows = [
        add_derived_axes(row) for row in reference_aggregate.get("reference_rows", []) if isinstance(row, dict)
    ]
    bot_rows, warnings = load_bot_rows(bot_run_ids, artifacts_root)
    raw_axis = comparison_axis(
        reference_rows,
        bot_rows,
        field="jump_cadence_per_min",
        label="Cadence/active min",
        basis="active movement-metrics rows",
    )
    normalized_axes = build_normalization_axes(reference_rows, bot_rows)
    axes = [raw_axis, *normalized_axes]
    decision = make_decision(axes, bot_rows)
    return {
        "schema": SCHEMA,
        "stage": stage,
        "source_reference_aggregate_path": portable_path(reference_aggregate_path) if reference_aggregate_path else "",
        "source_reference_aggregate_stage": reference_aggregate.get("stage", ""),
        "map": reference_aggregate.get("map", ""),
        "reference_count": len(reference_rows),
        "bot_count": len(bot_rows),
        "bot_run_ids": bot_run_ids,
        "excluded_run_ids": DEFAULT_EXCLUDED_RUNS,
        "warnings": warnings,
        "scope_note": (
            "S7e broadens bot cadence evidence from existing dm3 mode-7 artifacts only. "
            "The default included runs are S3g plus S6b/S6d diagnostic reruns that did not intentionally "
            "change movement commands. S6e is excluded because it changed water-edge vertical command behavior."
        ),
        "reference_rows": reference_rows,
        "bot_rows": bot_rows,
        "bot_player_summary": grouped_player_summary(bot_rows),
        "cadence_axes": axes,
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
        f"# Cadence Evidence Broadening {report.get('stage', '')}",
        "",
        "## Scope",
        "",
        f"- Map: `{report.get('map', '')}`",
        f"- Source reference aggregate: `{report.get('source_reference_aggregate_path', '')}`",
        f"- Reference rows: `{report.get('reference_count', 0)}`",
        f"- Bot rows: `{report.get('bot_count', 0)}`",
        f"- Included bot run IDs: `{', '.join(report.get('bot_run_ids', []))}`",
        f"- {report.get('scope_note', '')}",
        "",
    ]
    excluded = report.get("excluded_run_ids", {})
    if isinstance(excluded, dict) and excluded:
        lines.extend(["## Excluded Runs", ""])
        for run_id, reason in excluded.items():
            lines.append(f"- `{run_id}`: {reason}")
        lines.append("")

    warnings = report.get("warnings", [])
    if isinstance(warnings, list) and warnings:
        lines.extend(["## Warnings", ""])
        for warning in warnings:
            lines.append(f"- {warning}")
        lines.append("")

    lines.extend(
        [
            "## Cadence Axes",
            "",
            "| Axis | Basis | Reference range | Bot range | Bot relation |",
            "|---|---|---:|---:|---|",
        ]
    )
    for axis in report.get("cadence_axes", []):
        if not isinstance(axis, dict):
            continue
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
            "| Run | Bot | Avg | P95 | Cadence | Air cadence | Air ratio | Avg air ms | Avg air z | Landing delta |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in report.get("bot_rows", []):
        if not isinstance(row, dict):
            continue
        lines.append(
            "| "
            f"`{row.get('run_id', '')}` | "
            f"`{row.get('player', '')}` | "
            f"{format_comparison_value('avg_horizontal_speed_qu_per_s', row.get('avg_horizontal_speed_qu_per_s'))} | "
            f"{format_comparison_value('p95_horizontal_speed_qu_per_s', row.get('p95_horizontal_speed_qu_per_s'))} | "
            f"{format_comparison_value('jump_cadence_per_min', row.get('jump_cadence_per_min'))} | "
            f"{format_comparison_value('jump_cadence_per_airborne_proxy_min', row.get('jump_cadence_per_airborne_proxy_min'))} | "
            f"{format_comparison_value('airborne_proxy_time_ratio', row.get('airborne_proxy_time_ratio'))} | "
            f"{format_comparison_value('avg_airborne_proxy_duration_ms', row.get('avg_airborne_proxy_duration_ms'))} | "
            f"{format_comparison_value('avg_airborne_proxy_z_delta_qu', row.get('avg_airborne_proxy_z_delta_qu'))} | "
            f"{format_comparison_value('avg_post_landing_speed_delta_qu_per_s', row.get('avg_post_landing_speed_delta_qu_per_s'))} |"
        )

    decision = report.get("decision", {}) if isinstance(report.get("decision"), dict) else {}
    lines.extend(
        [
            "",
            "## Decision",
            "",
            f"- Verdict: `{decision.get('verdict', '')}`",
            f"- Raw cadence relation: `{decision.get('raw_cadence_relation', '')}`",
            f"- Movement-time relation: `{decision.get('movement_time_relation', '')}`",
            f"- Airborne-proxy relation: `{decision.get('airborne_proxy_relation', '')}`",
            f"- Reason: {decision.get('reason', '')}",
            f"- Next goal: {decision.get('next_goal', '')}",
        ]
    )
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Broaden S7 cadence evidence with existing bot movement artifacts.")
    parser.add_argument("--stage", default="s7e-cadence-evidence-dm3", help="Evidence stage label.")
    parser.add_argument(
        "--reference-aggregate",
        type=Path,
        default=DEFAULT_REFERENCE_AGGREGATE,
        help="S7c bot-comparable cadence aggregate JSON.",
    )
    parser.add_argument(
        "--artifacts-root",
        type=Path,
        default=DEFAULT_ARTIFACTS_ROOT,
        help="Root directory containing lab run artifacts.",
    )
    parser.add_argument(
        "--bot-run-id",
        action="append",
        dest="bot_run_ids",
        default=None,
        help="Bot run id to include. May be repeated. Defaults to the S7e unchanged mode-7 set.",
    )
    parser.add_argument("--output-json", type=Path, required=True, help="Output evidence JSON.")
    parser.add_argument("--output-md", type=Path, required=True, help="Output evidence Markdown.")
    return parser.parse_args(list(argv))


def main(argv: Iterable[str] = sys.argv[1:]) -> int:
    args = parse_args(argv)
    reference_aggregate = load_json_if_present(args.reference_aggregate)
    if not reference_aggregate:
        raise FileNotFoundError(args.reference_aggregate)
    bot_run_ids = args.bot_run_ids if args.bot_run_ids else list(DEFAULT_BOT_RUN_IDS)
    report = build_report(
        reference_aggregate,
        stage=args.stage,
        bot_run_ids=bot_run_ids,
        artifacts_root=args.artifacts_root,
        reference_aggregate_path=args.reference_aggregate,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_markdown(report, args.output_md)
    print(f"Wrote cadence evidence broadening: {args.output_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
