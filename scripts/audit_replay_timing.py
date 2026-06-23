#!/usr/bin/env python3
"""Audit KTX replay timing against the source `.cmds` stream.

This is intentionally diagnostic-only. KTX mode 10/12 currently uses the live
server frame `cmd_msec` for `trap_SetBotCMD`, while the source row `msec`
selects the replay cursor. Before changing that seam, compare the live cadence
and cursor elapsed time to the source cadence and record the divergence.
"""

from __future__ import annotations

import logging
import argparse
import gzip
import json
import sys
from pathlib import Path
from typing import Iterable, Sequence



LOGGER = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import build_replay_command_file as replay_builder
import moveprobe_parse
import pmove_sim


SCHEMA = "komodobots.replay_timing_audit.v1"


def read_text_maybe_gzip(path: Path) -> str:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return fh.read()
    return path.read_text(encoding="utf-8")


def load_json_maybe_gzip(path: Path) -> object:
    return json.loads(read_text_maybe_gzip(path))


def load_live_commands(path: Path) -> list[dict[str, object]]:
    if path.name.endswith(".json") or path.name.endswith(".json.gz"):
        doc = load_json_maybe_gzip(path)
        if isinstance(doc, dict):
            commands = doc.get("commands")
        else:
            commands = doc
        if not isinstance(commands, list):
            raise ValueError(f"{path} does not contain a commands list")
        return [row for row in commands if isinstance(row, dict)]
    return moveprobe_parse.parse_moveprobe_command_logs(read_text_maybe_gzip(path))


def source_start_times_ms(source_frames: Sequence[dict[str, object]]) -> list[float]:
    starts: list[float] = []
    cursor_ms = 0.0
    for frame in source_frames:
        starts.append(cursor_ms)
        cursor_ms += float(frame["msec"])
    return starts


def row_angles(row: dict[str, object]) -> list[float] | None:
    angles = row.get("angles")
    if not isinstance(angles, dict):
        return None
    return [
        float(angles.get("pitch", 0.0)),
        float(angles.get("yaw", 0.0)),
        float(angles.get("roll", 0.0)),
    ]


def angle_delta_summary(source: Sequence[float], live: Sequence[float]) -> dict[str, float]:
    return {
        "pitch": replay_builder.angle_delta_deg(float(source[0]), float(live[0])),
        "yaw": replay_builder.angle_delta_deg(float(source[1]), float(live[1])),
        "roll": replay_builder.angle_delta_deg(float(source[2]), float(live[2])),
    }


def audit_timing(
    cmds_path: Path,
    live_path: Path,
    *,
    bot_name: str | None = None,
) -> dict[str, object]:
    source_frames = pmove_sim.load_cmds_file(cmds_path)
    live_commands = load_live_commands(live_path)
    if bot_name is not None:
        live_commands = [row for row in live_commands if row.get("name") == bot_name]

    starts_ms = source_start_times_ms(source_frames)
    rows_with_replay = [
        row
        for row in live_commands
        if isinstance(row.get("replay_state"), dict)
    ]
    active_rows = [
        row
        for row in rows_with_replay
        if bool(row["replay_state"].get("active"))
    ]

    first_active_time = None
    for row in active_rows:
        if row.get("time_s") is not None:
            first_active_time = float(row["time_s"])
            break

    valid_rows: list[dict[str, object]] = []
    live_msec: list[float] = []
    source_msec: list[float] = []
    msec_delta: list[float] = []
    cursor_time_delta: list[float] = []
    cursor_values: list[int] = []
    invalid_cursor_rows = 0

    for row in active_rows:
        state = row["replay_state"]
        cursor = int(state.get("cursor", -1))
        if cursor < 0 or cursor >= len(source_frames):
            invalid_cursor_rows += 1
            continue
        live_msec_value = float(row.get("msec", 0))
        source_msec_value = float(source_frames[cursor]["msec"])
        live_msec.append(live_msec_value)
        source_msec.append(source_msec_value)
        msec_delta.append(live_msec_value - source_msec_value)
        cursor_values.append(cursor)
        row_summary: dict[str, object] = {
            "time_s": row.get("time_s"),
            "cursor": cursor,
            "live_msec": live_msec_value,
            "source_msec": source_msec_value,
            "msec_delta_ms": live_msec_value - source_msec_value,
        }
        if first_active_time is not None and row.get("time_s") is not None:
            live_elapsed_ms = (float(row["time_s"]) - first_active_time) * 1000.0
            source_elapsed_ms = starts_ms[cursor]
            delta_ms = live_elapsed_ms - source_elapsed_ms
            cursor_time_delta.append(delta_ms)
            row_summary["live_elapsed_ms"] = round(live_elapsed_ms, 3)
            row_summary["source_elapsed_ms"] = round(source_elapsed_ms, 3)
            row_summary["cursor_time_delta_ms"] = round(delta_ms, 3)
        valid_rows.append(row_summary)

    duplicate_cursor_rows = len(cursor_values) - len(set(cursor_values))
    cursor_regressions = sum(
        1
        for previous, current in zip(cursor_values, cursor_values[1:])
        if current < previous
    )

    first_angle_delta = None
    if active_rows and source_frames:
        first = active_rows[0]
        cursor = int(first["replay_state"].get("cursor", 0))
        if 0 <= cursor < len(source_frames):
            live_angles = row_angles(first)
            if live_angles is not None:
                first_angle_delta = angle_delta_summary(source_frames[cursor]["angles"], live_angles)

    return {
        "schema": SCHEMA,
        "cmds_path": str(cmds_path),
        "live_path": str(live_path),
        "bot_name": bot_name,
        "source_frames": len(source_frames),
        "live_command_rows": len(live_commands),
        "rows_with_replay_state": len(rows_with_replay),
        "active_replay_rows": len(active_rows),
        "valid_cursor_rows": len(valid_rows),
        "invalid_cursor_rows": invalid_cursor_rows,
        "cursor_min": min(cursor_values) if cursor_values else None,
        "cursor_max": max(cursor_values) if cursor_values else None,
        "duplicate_cursor_rows": duplicate_cursor_rows,
        "cursor_regressions": cursor_regressions,
        "source_msec": replay_builder.summarize_values(source_msec, digits=3),
        "live_msec": replay_builder.summarize_values(live_msec, digits=3),
        "msec_delta_ms": replay_builder.summarize_values(msec_delta, digits=3),
        "cursor_time_delta_ms": replay_builder.summarize_values(cursor_time_delta, digits=3),
        "first_active_angle_delta_deg": first_angle_delta,
        "sample_rows": valid_rows[:10],
    }


def render_markdown(report: dict[str, object]) -> str:
    first_angle = report.get("first_active_angle_delta_deg") or {}
    lines = [
        "# Replay timing audit",
        "",
        "| source frames | live rows | active rows | valid cursors | cursor range | msec delta p95 | cursor time delta p95 | first yaw delta |",
        "| ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: |",
        "| {source_frames} | {live_rows} | {active_rows} | {valid_rows} | {cursor_min}-{cursor_max} | {msec_p95} | {time_p95} | {yaw_delta} |".format(
            source_frames=report["source_frames"],
            live_rows=report["live_command_rows"],
            active_rows=report["active_replay_rows"],
            valid_rows=report["valid_cursor_rows"],
            cursor_min=report["cursor_min"],
            cursor_max=report["cursor_max"],
            msec_p95=report["msec_delta_ms"]["p95"],
            time_p95=report["cursor_time_delta_ms"]["p95"],
            yaw_delta=first_angle.get("yaw"),
        ),
        "",
        "Use this as evidence before changing live replay to source-row `msec`.",
        "",
    ]
    return "\n".join(lines)


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare source replay cadence with live KTX command rows.")
    parser.add_argument("--cmds", type=Path, required=True, help="Source komodobots.replay.v1 .cmds file.")
    parser.add_argument(
        "--commands-json",
        "--live",
        dest="live_path",
        type=Path,
        required=True,
        help="moveprobe-commands.json(.gz) or raw screen.log containing FBMOVEPROBE_CMD rows.",
    )
    parser.add_argument("--bot-name", help="Optional exact bot name filter, e.g. '/ bro'.")
    parser.add_argument("--output-json", type=Path, help="Write machine-readable audit JSON.")
    parser.add_argument("--output-md", type=Path, help="Write Markdown summary.")
    return parser.parse_args(list(argv))


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    report = audit_timing(args.cmds, args.live_path, bot_name=args.bot_name)
    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    rendered = render_markdown(report)
    if args.output_md:
        args.output_md.parent.mkdir(parents=True, exist_ok=True)
        args.output_md.write_text(rendered + "\n", encoding="utf-8")
    if not args.output_json and not args.output_md:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
