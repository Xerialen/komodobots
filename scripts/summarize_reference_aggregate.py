#!/usr/bin/env python3
"""Build a tiny exact-player movement reference aggregate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable

from analyze_human_mvd import (
    COMPARISON_FIELDS,
    classify_against_range,
    format_comparison_value,
    load_json_if_present,
    pct,
    round_float,
    summarize_numeric_field,
)


SCHEMA = "komodobots.reference_aggregate.v1"
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BOT_SUMMARY = REPO_ROOT / "experiments" / "ktx_moveprobe" / "evidence" / "moveprobe-s3g-summary.json"

REFERENCE_FIELDS = COMPARISON_FIELDS + (("jump_cadence_per_min", "Cadence/min"),)


def parse_target_arg(value: str) -> tuple[str, Path]:
    target, separator, path = value.partition("=")
    if not separator or not target.strip() or not path.strip():
        raise argparse.ArgumentTypeError("--target must be PLAYER=summary.json")
    return target.strip(), Path(path)


def find_player(summary: dict[str, object], target: str) -> dict[str, object]:
    wanted = target.strip().lower()
    for player in summary.get("movement_players", []):
        if not isinstance(player, dict):
            continue
        if str(player.get("name", "")).strip().lower() == wanted:
            return player
    raise ValueError(f"Could not find target player {target!r} in {summary.get('run_id')}")


def compact_reference_row(target: str, summary_path: Path) -> dict[str, object]:
    summary = load_json_if_present(summary_path)
    if not summary:
        raise FileNotFoundError(summary_path)
    player = find_player(summary, target)
    demo = summary.get("demo", {}) if isinstance(summary.get("demo"), dict) else {}
    match = summary.get("match", {}) if isinstance(summary.get("match"), dict) else {}
    row = {
        "target_player": target,
        "matched_player": player.get("name", ""),
        "summary_path": str(summary_path),
        "run_id": summary.get("run_id", ""),
        "demo": demo.get("name", ""),
        "sha256": demo.get("sha256", ""),
        "map": match.get("map", demo.get("map", "")),
        "map_title": match.get("map_title", ""),
        "duration_ms": match.get("duration_ms", ""),
    }
    for field, _label in REFERENCE_FIELDS:
        row[field] = round_float(player.get(field))
    return row


def bot_rows_for_map(bot_summary_path: Path, map_name: str) -> list[dict[str, object]]:
    summary = load_json_if_present(bot_summary_path)
    rows = []
    for run in summary.get("runs", []) if isinstance(summary, dict) else []:
        if not isinstance(run, dict) or str(run.get("map", "")) != map_name:
            continue
        for player in run.get("players", []):
            if not isinstance(player, dict):
                continue
            row = {
                "run_id": run.get("run_id", ""),
                "map": run.get("map", ""),
                "player": player.get("player", ""),
            }
            for field, _label in COMPARISON_FIELDS:
                row[field] = round_float(player.get(field))
            rows.append(row)
    return rows


def build_aggregate(
    *,
    targets: list[tuple[str, Path]],
    bot_summary_path: Path,
    map_name: str,
    stage: str,
) -> dict[str, object]:
    reference_rows = [compact_reference_row(target, path) for target, path in targets]
    map_matched_rows = [row for row in reference_rows if str(row.get("map", "")) == map_name]
    bot_rows = bot_rows_for_map(bot_summary_path, map_name)

    ranges = []
    ranges_by_field = {}
    for field, label in REFERENCE_FIELDS:
        reference_summary = summarize_numeric_field(map_matched_rows, field)
        ranges_by_field[field] = reference_summary
        bot_summary = summarize_numeric_field(bot_rows, field) if field in dict(COMPARISON_FIELDS) else None
        ranges.append(
            {
                "field": field,
                "label": label,
                "reference": reference_summary,
                "bot": bot_summary,
            }
        )

    bot_comparison = []
    for row in bot_rows:
        bot_comparison.append(
            {
                "run_id": row.get("run_id", ""),
                "player": row.get("player", ""),
                "values": {field: row.get(field) for field, _label in COMPARISON_FIELDS},
                "against_reference_range": {
                    field: classify_against_range(row.get(field), ranges_by_field[field])
                    for field, _label in COMPARISON_FIELDS
                },
            }
        )

    return {
        "schema": SCHEMA,
        "stage": stage,
        "map": map_name,
        "reference_count": len(map_matched_rows),
        "targets": [target for target, _path in targets],
        "reference_rows": map_matched_rows,
        "excluded_reference_rows": [row for row in reference_rows if str(row.get("map", "")) != map_name],
        "bot_summary_path": str(bot_summary_path),
        "bot_rows": bot_rows,
        "ranges": ranges,
        "bot_comparison": bot_comparison,
        "notes": [
            "Tiny exact-player reference aggregate; useful for movement-range anchoring, not a player-style model.",
            "Reference rows are selected by metadata before parsing; raw demos and events remain outside Git.",
        ],
    }


def write_markdown(aggregate: dict[str, object], output_path: Path) -> None:
    lines = [
        f"# Reference Aggregate {aggregate.get('stage', '')}",
        "",
        "## Scope",
        "",
        f"- Map: `{aggregate.get('map', '')}`",
        f"- Reference rows: `{aggregate.get('reference_count', 0)}`",
        f"- Targets: `{', '.join(aggregate.get('targets', []))}`",
        f"- Bot summary: `{aggregate.get('bot_summary_path', '')}`",
        "",
    ]
    for note in aggregate.get("notes", []):
        lines.append(f"- {note}")

    lines.extend(
        [
            "",
            "## Reference Rows",
            "",
            "| Target | Demo | Avg | P95 | Stationary | Low | Air | Cadence/min |",
            "|---|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in aggregate.get("reference_rows", []):
        lines.append(
            "| "
            f"`{row.get('matched_player')}` | "
            f"`{row.get('demo')}` | "
            f"{format_comparison_value('avg_horizontal_speed_qu_per_s', row.get('avg_horizontal_speed_qu_per_s'))} | "
            f"{format_comparison_value('p95_horizontal_speed_qu_per_s', row.get('p95_horizontal_speed_qu_per_s'))} | "
            f"{pct(row.get('stationary_time_ratio'))} | "
            f"{pct(row.get('low_speed_time_ratio'))} | "
            f"{pct(row.get('airborne_proxy_time_ratio'))} | "
            f"{format_comparison_value('jump_cadence_per_min', row.get('jump_cadence_per_min'))} |"
        )

    lines.extend(
        [
            "",
            "## Aggregate Range",
            "",
            "| Metric | Ref min | Ref mean | Ref max | Bot min | Bot mean | Bot max |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in aggregate.get("ranges", []):
        field = str(row.get("field", ""))
        reference = row.get("reference", {}) if isinstance(row.get("reference"), dict) else {}
        bot = row.get("bot", {}) if isinstance(row.get("bot"), dict) else {}
        lines.append(
            "| "
            f"{row.get('label', field)} | "
            f"{format_comparison_value(field, reference.get('min'))} | "
            f"{format_comparison_value(field, reference.get('mean'))} | "
            f"{format_comparison_value(field, reference.get('max'))} | "
            f"{format_comparison_value(field, bot.get('min'))} | "
            f"{format_comparison_value(field, bot.get('mean'))} | "
            f"{format_comparison_value(field, bot.get('max'))} |"
        )

    lines.extend(
        [
            "",
            "## S3g Bot Rows",
            "",
            "| Bot | Avg | Avg range | P95 | P95 range | Stationary | Stationary range | Low | Low range | Air | Air range |",
            "|---|---:|---|---:|---|---:|---|---:|---|---:|---|",
        ]
    )
    for row in aggregate.get("bot_comparison", []):
        values = row.get("values", {}) if isinstance(row.get("values"), dict) else {}
        ranges = (
            row.get("against_reference_range", {})
            if isinstance(row.get("against_reference_range"), dict)
            else {}
        )
        lines.append(
            "| "
            f"`{row.get('player', '')}` | "
            f"{format_comparison_value('avg_horizontal_speed_qu_per_s', values.get('avg_horizontal_speed_qu_per_s'))} | "
            f"`{ranges.get('avg_horizontal_speed_qu_per_s', '')}` | "
            f"{format_comparison_value('p95_horizontal_speed_qu_per_s', values.get('p95_horizontal_speed_qu_per_s'))} | "
            f"`{ranges.get('p95_horizontal_speed_qu_per_s', '')}` | "
            f"{format_comparison_value('stationary_time_ratio', values.get('stationary_time_ratio'))} | "
            f"`{ranges.get('stationary_time_ratio', '')}` | "
            f"{format_comparison_value('low_speed_time_ratio', values.get('low_speed_time_ratio'))} | "
            f"`{ranges.get('low_speed_time_ratio', '')}` | "
            f"{format_comparison_value('airborne_proxy_time_ratio', values.get('airborne_proxy_time_ratio'))} | "
            f"`{ranges.get('airborne_proxy_time_ratio', '')}` |"
        )

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize a tiny exact-player movement reference aggregate.")
    parser.add_argument("--stage", default="s5b", help="Aggregate stage label.")
    parser.add_argument("--map", default="dm3", help="Map to aggregate and compare.")
    parser.add_argument("--target", action="append", type=parse_target_arg, required=True, help="PLAYER=summary.json")
    parser.add_argument("--bot-summary", type=Path, default=DEFAULT_BOT_SUMMARY, help="S3g bot summary JSON.")
    parser.add_argument("--output-json", type=Path, required=True, help="Output aggregate JSON.")
    parser.add_argument("--output-md", type=Path, required=True, help="Output aggregate Markdown.")
    return parser.parse_args(list(argv))


def main(argv: Iterable[str] = sys.argv[1:]) -> int:
    args = parse_args(argv)
    aggregate = build_aggregate(
        targets=args.target,
        bot_summary_path=args.bot_summary,
        map_name=args.map,
        stage=args.stage,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(aggregate, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_markdown(aggregate, args.output_md)
    print(f"Wrote aggregate: {args.output_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
