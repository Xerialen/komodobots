#!/usr/bin/env python3
"""Build a tiny exact-player movement-signature scaffold."""

from __future__ import annotations

import logging
import argparse
import json
import math
import sys
from pathlib import Path
from typing import Iterable

from analyze_human_mvd import format_comparison_value, load_json_if_present, pct
from summarize_reference_aggregate import portable_path



LOGGER = logging.getLogger(__name__)
SCHEMA = "komodobots.player_movement_signatures.v1"
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REFERENCE_AGGREGATE = (
    REPO_ROOT / "experiments" / "human_comparison" / "evidence" / "human-reference-s5b-aggregate.json"
)

STYLE_FIELDS = (
    {
        "field": "avg_horizontal_speed_qu_per_s",
        "label": "Avg",
        "family": "land_speed",
        "min_abs_spread": 20.0,
        "min_relative_spread": 0.05,
        "bot_comparable": True,
    },
    {
        "field": "p95_horizontal_speed_qu_per_s",
        "label": "P95",
        "family": "land_speed",
        "min_abs_spread": 20.0,
        "min_relative_spread": 0.05,
        "bot_comparable": True,
    },
    {
        "field": "stationary_time_ratio",
        "label": "Stationary",
        "family": "tempo_control",
        "min_abs_spread": 0.02,
        "min_relative_spread": 0.10,
        "bot_comparable": True,
    },
    {
        "field": "low_speed_time_ratio",
        "label": "Low",
        "family": "tempo_control",
        "min_abs_spread": 0.03,
        "min_relative_spread": 0.10,
        "bot_comparable": True,
    },
    {
        "field": "airborne_proxy_time_ratio",
        "label": "Air",
        "family": "air_proxy",
        "min_abs_spread": 0.03,
        "min_relative_spread": 0.10,
        "bot_comparable": True,
    },
    {
        "field": "jump_cadence_per_min",
        "label": "Cadence/min",
        "family": "jump_cadence",
        "min_abs_spread": 2.0,
        "min_relative_spread": 0.05,
        "bot_comparable": True,
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


def numeric_values(rows: list[dict[str, object]], field: str) -> list[float]:
    values = []
    for row in rows:
        number = optional_float(row.get(field))
        if number is not None:
            values.append(number)
    return values


def summarize_values(rows: list[dict[str, object]], field: str) -> dict[str, object]:
    values = numeric_values(rows, field)
    if not values:
        return {"count": 0, "min": None, "mean": None, "max": None, "spread": None, "relative_spread": None}
    minimum = min(values)
    maximum = max(values)
    mean = sum(values) / len(values)
    spread = maximum - minimum
    relative_spread = (spread / abs(mean)) if mean else None
    return {
        "count": len(values),
        "min": round(minimum, 3),
        "mean": round(mean, 3),
        "max": round(maximum, 3),
        "spread": round(spread, 3),
        "relative_spread": round(relative_spread, 3) if relative_spread is not None else None,
    }


def has_meaningful_reference_spread(summary: dict[str, object], field_config: dict[str, object]) -> bool:
    if int(summary.get("count") or 0) < 2:
        return False
    spread = optional_float(summary.get("spread"))
    relative_spread = optional_float(summary.get("relative_spread"))
    if spread is None or relative_spread is None:
        return False
    return spread >= float(field_config["min_abs_spread"]) and relative_spread >= float(
        field_config["min_relative_spread"]
    )


def range_position(value: object, summary: dict[str, object]) -> float | None:
    number = optional_float(value)
    minimum = optional_float(summary.get("min"))
    maximum = optional_float(summary.get("max"))
    if number is None or minimum is None or maximum is None or maximum == minimum:
        return None
    return round((number - minimum) / (maximum - minimum), 3)


def classify_against_reference(value: object, reference_summary: dict[str, object]) -> str:
    if not reference_summary.get("count"):
        return "no_reference_range"
    number = optional_float(value)
    minimum = optional_float(reference_summary.get("min"))
    maximum = optional_float(reference_summary.get("max"))
    if number is None or minimum is None or maximum is None:
        return "unavailable"
    if number < minimum:
        return "below_reference_min"
    if number > maximum:
        return "above_reference_max"
    return "within_reference_range"


def bot_relation(bot_rows: list[dict[str, object]], field: str, reference_summary: dict[str, object]) -> dict[str, object]:
    classifications = [classify_against_reference(row.get(field), reference_summary) for row in bot_rows]
    usable = [value for value in classifications if value != "unavailable"]
    counts = {value: usable.count(value) for value in sorted(set(usable))}
    if not usable:
        relation = "no_bot_comparison"
    elif len(usable) == counts.get("below_reference_min", 0):
        relation = "all_bots_below_reference_range"
    elif len(usable) == counts.get("above_reference_max", 0):
        relation = "all_bots_above_reference_range"
    elif len(usable) == counts.get("within_reference_range", 0):
        relation = "all_bots_within_reference_range"
    else:
        relation = "mixed_bot_relation"
    return {"relation": relation, "classifications": classifications, "counts": counts}


def interpret_axis(
    *,
    field_config: dict[str, object],
    reference_summary: dict[str, object],
    bot_relation_summary: dict[str, object] | None,
    meaningful_reference_spread: bool,
) -> tuple[str, str]:
    field = str(field_config["field"])
    if not field_config.get("bot_comparable", True):
        if meaningful_reference_spread:
            return (
                "reference_only_candidate_style_axis",
                "The exact-player rows differ, but the current committed S3g bot summary lacks this metric.",
            )
        return (
            "not_yet_useful_for_player_style",
            "The current exact-player rows do not show enough spread to treat this as a style axis.",
        )

    relation = str((bot_relation_summary or {}).get("relation", "no_bot_comparison"))
    if relation == "all_bots_below_reference_range" and field_config.get("family") == "land_speed":
        return (
            "generic_human_vs_bot_land_speed_gap",
            "Every S3g bot row is below the exact-player reference range, so this is a broad movement deficit first.",
        )
    if relation in {"all_bots_below_reference_range", "all_bots_above_reference_range"}:
        return (
            "generic_human_bot_mismatch",
            "Every S3g bot row is outside the exact-player range in the same direction.",
        )
    if meaningful_reference_spread:
        return (
            "candidate_player_style_axis_but_thin",
            "The exact-player rows differ and the bots are not uniformly outside the range, but one demo per player is too thin for a style claim.",
        )
    if reference_summary.get("count"):
        return (
            "not_yet_useful_for_player_style",
            "The exact-player reference spread is too small or too under-sampled for a player-specific claim.",
        )
    return ("missing_reference_metric", "No reference rows carried this metric.")


def player_signature_rows(reference_rows: list[dict[str, object]], reference_summaries: dict[str, dict[str, object]]) -> list[dict[str, object]]:
    signatures = []
    for row in reference_rows:
        values = {}
        positions = {}
        for config in STYLE_FIELDS:
            field = str(config["field"])
            values[field] = rounded(row.get(field))
            positions[field] = range_position(row.get(field), reference_summaries[field])
        signatures.append(
            {
                "player": row.get("matched_player") or row.get("target_player") or "",
                "target_player": row.get("target_player", ""),
                "run_id": row.get("run_id", ""),
                "demo": row.get("demo", ""),
                "values": values,
                "within_reference_range_position": positions,
            }
        )
    return signatures


def axis_player_order(
    reference_rows: list[dict[str, object]],
    field: str,
    reference_summary: dict[str, object],
) -> list[dict[str, object]]:
    ordered = []
    for row in reference_rows:
        number = optional_float(row.get(field))
        if number is None:
            continue
        ordered.append(
            {
                "player": row.get("matched_player") or row.get("target_player") or "",
                "value": round(number, 3),
                "range_position": range_position(number, reference_summary),
            }
        )
    return sorted(ordered, key=lambda item: item["value"])


def compact_bot_rows(
    bot_rows: list[dict[str, object]],
    field: str,
    reference_summary: dict[str, object],
) -> list[dict[str, object]]:
    rows = []
    for row in bot_rows:
        value = rounded(row.get(field))
        rows.append(
            {
                "player": row.get("player", ""),
                "run_id": row.get("run_id", ""),
                "value": value,
                "against_reference": classify_against_reference(value, reference_summary),
            }
        )
    return rows


def build_feature_axes(reference_rows: list[dict[str, object]], bot_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    axes = []
    for config in STYLE_FIELDS:
        field = str(config["field"])
        reference_summary = summarize_values(reference_rows, field)
        bot_summary = summarize_values(bot_rows, field) if config.get("bot_comparable", True) else None
        bot_relation_summary = bot_relation(bot_rows, field, reference_summary) if config.get("bot_comparable", True) else None
        meaningful_spread = has_meaningful_reference_spread(reference_summary, config)
        interpretation, reason = interpret_axis(
            field_config=config,
            reference_summary=reference_summary,
            bot_relation_summary=bot_relation_summary,
            meaningful_reference_spread=meaningful_spread,
        )
        axis = {
            "field": field,
            "label": config["label"],
            "family": config["family"],
            "reference": reference_summary,
            "bot": bot_summary,
            "reference_spread_is_meaningful": meaningful_spread,
            "bot_relation": bot_relation_summary,
            "interpretation": interpretation,
            "reason": reason,
            "player_order": axis_player_order(reference_rows, field, reference_summary),
        }
        if config.get("bot_comparable", True):
            axis["bot_rows"] = compact_bot_rows(bot_rows, field, reference_summary)
        axes.append(axis)
    return axes


def group_reference_rows_by_player(reference_rows: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    grouped: dict[str, list[dict[str, object]]] = {}
    for row in reference_rows:
        player = str(row.get("target_player") or row.get("matched_player") or "").strip()
        if not player:
            continue
        grouped.setdefault(player, []).append(row)
    return grouped


def stability_interpretation(
    *,
    field_config: dict[str, object],
    feature_axis: dict[str, object],
    repeated_player_count: int,
    min_player_row_count: int,
    between_mean_spread: float | None,
    max_within_spread: float | None,
    separation_ratio: float | None,
) -> str:
    if repeated_player_count < 2 or min_player_row_count < 2:
        return "needs_repeated_reference_rows"
    if feature_axis.get("interpretation") == "generic_human_vs_bot_land_speed_gap":
        return "stable_but_generic_land_speed_gap"
    if between_mean_spread is None or max_within_spread is None:
        return "not_enough_repeated_metric_data"
    if between_mean_spread < float(field_config["min_abs_spread"]):
        return "not_enough_between_player_spread"
    if separation_ratio is not None and separation_ratio >= 1.5:
        if field_config.get("bot_comparable", True):
            return "repeated_candidate_style_axis"
        return "repeated_reference_only_candidate_axis"
    return "mixed_or_overlap_repeated_axis"


def build_stability_axes(reference_rows: list[dict[str, object]], feature_axes: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped = group_reference_rows_by_player(reference_rows)
    feature_by_field = {str(axis.get("field", "")): axis for axis in feature_axes}
    rows = []
    for config in STYLE_FIELDS:
        field = str(config["field"])
        per_player = []
        means: list[float] = []
        within_spreads: list[float] = []
        for player, player_rows in sorted(grouped.items()):
            summary = summarize_values(player_rows, field)
            count = int(summary.get("count") or 0)
            if count <= 0:
                continue
            mean = optional_float(summary.get("mean"))
            spread = optional_float(summary.get("spread"))
            if mean is not None:
                means.append(mean)
            if spread is not None and count >= 2:
                within_spreads.append(spread)
            per_player.append(
                {
                    "player": player,
                    "count": count,
                    "min": summary.get("min"),
                    "mean": summary.get("mean"),
                    "max": summary.get("max"),
                    "within_player_spread": summary.get("spread"),
                }
            )
        repeated_player_count = sum(1 for row in per_player if int(row.get("count") or 0) >= 2)
        min_player_row_count = min((int(row.get("count") or 0) for row in per_player), default=0)
        between_mean_spread = max(means) - min(means) if len(means) >= 2 else None
        max_within_spread = max(within_spreads) if within_spreads else None
        mean_within_spread = sum(within_spreads) / len(within_spreads) if within_spreads else None
        if between_mean_spread is None or max_within_spread in (None, 0.0):
            separation_ratio = None
        else:
            separation_ratio = between_mean_spread / max_within_spread
        feature_axis = feature_by_field.get(field, {})
        interpretation = stability_interpretation(
            field_config=config,
            feature_axis=feature_axis,
            repeated_player_count=repeated_player_count,
            min_player_row_count=min_player_row_count,
            between_mean_spread=between_mean_spread,
            max_within_spread=max_within_spread,
            separation_ratio=separation_ratio,
        )
        rows.append(
            {
                "field": field,
                "label": config["label"],
                "family": config["family"],
                "bot_comparable": bool(config.get("bot_comparable", True)),
                "repeated_player_count": repeated_player_count,
                "min_player_row_count": min_player_row_count,
                "between_player_mean_spread": round(between_mean_spread, 3)
                if between_mean_spread is not None
                else None,
                "max_within_player_spread": round(max_within_spread, 3) if max_within_spread is not None else None,
                "mean_within_player_spread": round(mean_within_spread, 3) if mean_within_spread is not None else None,
                "separation_ratio": round(separation_ratio, 3) if separation_ratio is not None else None,
                "feature_axis_interpretation": feature_axis.get("interpretation", ""),
                "stability_interpretation": interpretation,
                "per_player": per_player,
            }
        )
    return rows


def build_headline_gaps(axes: list[dict[str, object]]) -> list[dict[str, object]]:
    gaps = []
    for axis in axes:
        if axis.get("interpretation") != "generic_human_vs_bot_land_speed_gap":
            continue
        reference = axis.get("reference", {}) if isinstance(axis.get("reference"), dict) else {}
        bot = axis.get("bot", {}) if isinstance(axis.get("bot"), dict) else {}
        reference_min = optional_float(reference.get("min"))
        bot_max = optional_float(bot.get("max"))
        if reference_min is None or bot_max is None:
            gap_to_reference_min = None
        else:
            gap_to_reference_min = round(reference_min - bot_max, 3)
        gaps.append(
            {
                "field": axis.get("field", ""),
                "label": axis.get("label", ""),
                "reference_min": reference.get("min"),
                "reference_max": reference.get("max"),
                "bot_min": bot.get("min"),
                "bot_max": bot.get("max"),
                "gap_from_best_bot_to_reference_min": gap_to_reference_min,
            }
        )
    return gaps


def build_signature_report(
    aggregate: dict[str, object],
    *,
    stage: str,
    source_aggregate_path: Path | None = None,
) -> dict[str, object]:
    reference_rows = [row for row in aggregate.get("reference_rows", []) if isinstance(row, dict)]
    bot_rows = [row for row in aggregate.get("bot_rows", []) if isinstance(row, dict)]
    reference_summaries = {str(config["field"]): summarize_values(reference_rows, str(config["field"])) for config in STYLE_FIELDS}
    axes = build_feature_axes(reference_rows, bot_rows)
    stability_axes = build_stability_axes(reference_rows, axes)
    headline_gaps = build_headline_gaps(axes)
    interpretations = [str(axis.get("interpretation")) for axis in axes]
    candidate_axes = [
        str(axis.get("field"))
        for axis in axes
        if axis.get("interpretation") == "candidate_player_style_axis_but_thin"
    ]
    reference_only_axes = [
        str(axis.get("field"))
        for axis in axes
        if axis.get("interpretation") == "reference_only_candidate_style_axis"
    ]
    generic_gaps = [
        str(axis.get("field"))
        for axis in axes
        if str(axis.get("interpretation", "")).startswith("generic_human")
    ]
    repeated_candidate_axes = [
        str(axis.get("field"))
        for axis in stability_axes
        if axis.get("stability_interpretation") == "repeated_candidate_style_axis"
    ]
    repeated_reference_only_axes = [
        str(axis.get("field"))
        for axis in stability_axes
        if axis.get("stability_interpretation") == "repeated_reference_only_candidate_axis"
    ]
    one_demo_per_player = bool(reference_rows) and len(
        {str(row.get("target_player") or row.get("matched_player")) for row in reference_rows}
    ) == len(reference_rows)
    stop_condition_triggered = len(reference_rows) < 6 or one_demo_per_player
    stop_reason = (
        "Only three single-demo exact-player rows are available; this can seed axes but cannot support stable player-style claims."
        if stop_condition_triggered
        else "Reference set has enough repeated rows to start checking player-style stability."
    )
    return {
        "schema": SCHEMA,
        "stage": stage,
        "source_aggregate_path": portable_path(source_aggregate_path) if source_aggregate_path else "",
        "source_aggregate_stage": aggregate.get("stage", ""),
        "map": aggregate.get("map", ""),
        "reference_count": len(reference_rows),
        "bot_count": len(bot_rows),
        "bot_source_run_ids": aggregate.get("bot_source_run_ids", []),
        "player_signatures": player_signature_rows(reference_rows, reference_summaries),
        "feature_axes": axes,
        "stability_axes": stability_axes,
        "headline_gaps": headline_gaps,
        "evidence_summary": {
            "generic_human_bot_axes": generic_gaps,
            "candidate_player_style_axes": candidate_axes,
            "reference_only_candidate_axes": reference_only_axes,
            "repeated_candidate_style_axes": repeated_candidate_axes,
            "repeated_reference_only_candidate_axes": repeated_reference_only_axes,
            "axis_interpretations": interpretations,
        },
        "stop_condition_triggered": stop_condition_triggered,
        "stop_condition_reason": stop_reason,
        "notes": [
            "S7a is a measurement scaffold, not a player-specific movement controller.",
            "Features marked as candidate axes are descriptive single-demo signals, not stable style claims.",
            "Land-speed gaps stay visible so player-specific work does not hide the unresolved bunnyhop/high-speed deficit.",
        ],
        "next_goal": (
            (
                "S7b should broaden exact-player movement references before controller work: add repeated dm3 samples "
                "for Milton/carapace/yeti where available, then rerun this signature scaffold to separate stable player "
                "style from one-match noise and the generic S3g land-speed gap."
            )
            if stop_condition_triggered
            else (
                "S7c should make the surviving repeated axes bot-comparable and controller-relevant: add bot-side "
                "cadence/tempo metrics to the S3g summaries, then decide whether low-speed/cadence warrant "
                "player-style targets or whether more exact-player references are needed."
            )
            if repeated_reference_only_axes
            else (
                "S7d should decide what to do with the bot-comparable repeated axes: keep cadence as a diagnostic "
                "target, broaden exact-player/bot samples, or design a tiny controller probe, while keeping the "
                "generic land-speed gap visible."
            )
        ),
    }


def format_range(field: str, summary: dict[str, object]) -> str:
    if not summary or not summary.get("count"):
        return ""
    return (
        f"{format_comparison_value(field, summary.get('min'))}-"
        f"{format_comparison_value(field, summary.get('max'))}"
    )


def write_markdown(report: dict[str, object], output_path: Path) -> None:
    lines = [
        f"# Player Movement Signatures {report.get('stage', '')}",
        "",
        "## Scope",
        "",
        f"- Map: `{report.get('map', '')}`",
        f"- Source aggregate: `{report.get('source_aggregate_path', '')}`",
        f"- Reference rows: `{report.get('reference_count', 0)}`",
        f"- S3g bot rows: `{report.get('bot_count', 0)}`",
        f"- Bot source run IDs: `{', '.join(report.get('bot_source_run_ids', []))}`",
        f"- Stop condition: `{report.get('stop_condition_triggered')}`",
        f"- Stop reason: {report.get('stop_condition_reason', '')}",
        "",
    ]
    for note in report.get("notes", []):
        lines.append(f"- {note}")

    lines.extend(
        [
            "",
            "## Exact-Player Signature Rows",
            "",
            "| Player | Demo | Avg | P95 | Stationary | Low | Air | Cadence/min |",
            "|---|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in report.get("player_signatures", []):
        values = row.get("values", {}) if isinstance(row.get("values"), dict) else {}
        lines.append(
            "| "
            f"`{row.get('player', '')}` | "
            f"`{row.get('demo', '')}` | "
            f"{format_comparison_value('avg_horizontal_speed_qu_per_s', values.get('avg_horizontal_speed_qu_per_s'))} | "
            f"{format_comparison_value('p95_horizontal_speed_qu_per_s', values.get('p95_horizontal_speed_qu_per_s'))} | "
            f"{pct(values.get('stationary_time_ratio'))} | "
            f"{pct(values.get('low_speed_time_ratio'))} | "
            f"{pct(values.get('airborne_proxy_time_ratio'))} | "
            f"{format_comparison_value('jump_cadence_per_min', values.get('jump_cadence_per_min'))} |"
        )

    lines.extend(
        [
            "",
            "## Feature Axes",
            "",
            "| Metric | Reference range | Spread | S3g bot relation | Interpretation |",
            "|---|---:|---:|---|---|",
        ]
    )
    for axis in report.get("feature_axes", []):
        field = str(axis.get("field", ""))
        reference = axis.get("reference", {}) if isinstance(axis.get("reference"), dict) else {}
        relation = axis.get("bot_relation", {}) if isinstance(axis.get("bot_relation"), dict) else {}
        lines.append(
            "| "
            f"{axis.get('label', field)} | "
            f"{format_range(field, reference)} | "
            f"{format_comparison_value(field, reference.get('spread'))} | "
            f"`{relation.get('relation', 'reference_only')}` | "
            f"`{axis.get('interpretation', '')}` |"
        )

    lines.extend(
        [
            "",
            "## Repeated-Player Stability",
            "",
            "| Metric | Repeated players | Between-player mean spread | Max within-player spread | Separation ratio | Stability interpretation |",
            "|---|---:|---:|---:|---:|---|",
        ]
    )
    for axis in report.get("stability_axes", []):
        field = str(axis.get("field", ""))
        separation_ratio = axis.get("separation_ratio")
        ratio_text = f"{float(separation_ratio):.2f}" if separation_ratio is not None else ""
        lines.append(
            "| "
            f"{axis.get('label', field)} | "
            f"{axis.get('repeated_player_count', 0)} | "
            f"{format_comparison_value(field, axis.get('between_player_mean_spread'))} | "
            f"{format_comparison_value(field, axis.get('max_within_player_spread'))} | "
            f"{ratio_text} | "
            f"`{axis.get('stability_interpretation', '')}` |"
        )

    lines.extend(["", "## Headline Land-Speed Gaps", ""])
    gaps = report.get("headline_gaps", []) if isinstance(report.get("headline_gaps", []), list) else []
    if gaps:
        lines.extend(
            [
                "| Metric | Reference range | S3g bot range | Best bot gap to ref min |",
                "|---|---:|---:|---:|",
            ]
        )
        for gap in gaps:
            field = str(gap.get("field", ""))
            lines.append(
                "| "
                f"{gap.get('label', field)} | "
                f"{format_comparison_value(field, gap.get('reference_min'))}-"
                f"{format_comparison_value(field, gap.get('reference_max'))} | "
                f"{format_comparison_value(field, gap.get('bot_min'))}-"
                f"{format_comparison_value(field, gap.get('bot_max'))} | "
                f"{format_comparison_value(field, gap.get('gap_from_best_bot_to_reference_min'))} |"
            )
    else:
        lines.append("- No all-bot land-speed gap was detected in this input.")

    lines.extend(["", "## Next Goal", "", f"- {report.get('next_goal', '')}"])
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a tiny exact-player movement-signature scaffold.")
    parser.add_argument("--stage", default="s7a-player-signatures-dm3", help="Signature stage label.")
    parser.add_argument(
        "--reference-aggregate",
        type=Path,
        default=DEFAULT_REFERENCE_AGGREGATE,
        help="S5b reference aggregate JSON.",
    )
    parser.add_argument("--output-json", type=Path, required=True, help="Output signature JSON.")
    parser.add_argument("--output-md", type=Path, required=True, help="Output signature Markdown.")
    return parser.parse_args(list(argv))


def main(argv: Iterable[str] = sys.argv[1:]) -> int:
    args = parse_args(argv)
    aggregate = load_json_if_present(args.reference_aggregate)
    if not aggregate:
        raise FileNotFoundError(args.reference_aggregate)
    report = build_signature_report(
        aggregate,
        stage=args.stage,
        source_aggregate_path=args.reference_aggregate,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_markdown(report, args.output_md)
    print(f"Wrote player movement signatures: {args.output_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
