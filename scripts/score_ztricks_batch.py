#!/usr/bin/env python3
"""Score batched ztricks Distance attempts from moveprobe command logs.

The batch scorer treats each attempt as a data row. It reads
`moveprobe-commands.json`, segments repeated bot tries, and compares every
attempt against the successful human `getspeed.qwd` release formula:

- release point near the water-trench lip
- horizontal speed around 475 qu/s
- velocity yaw, target error, and yaw lead synchronized at jump release
- landing near the far platform reference point

This is intentionally an artifact scorer, not a controller.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARTIFACTS_ROOT = REPO_ROOT / "artifacts" / "lab-runs"

BUTTON_JUMP = 2

SPAWN_ORIGIN = {"x": -3516.125, "y": 3712.0, "z": -453.125}
HUMAN_RELEASE = {
    "origin": {"x": -3360.8, "y": 3777.2, "z": -488.0},
    "horizontal_speed": 475.2,
    "velocity_yaw_deg": -11.3,
    "target_error_deg": 8.3,
    "yaw_lead_deg": -7.7,
    "d_lip_qu": 12.8,
}
HUMAN_LANDING = {
    "origin": {"x": -3044.1, "y": 3760.5, "z": -488.0},
    "horizontal_speed": 495.5,
}


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def distance_h(a: dict[str, object], b: dict[str, object]) -> float:
    return math.hypot(float(a["x"]) - float(b["x"]), float(a["y"]) - float(b["y"]))


def distance_3d(a: dict[str, object], b: dict[str, object]) -> float:
    return math.sqrt(
        (float(a["x"]) - float(b["x"])) ** 2
        + (float(a["y"]) - float(b["y"])) ** 2
        + (float(a["z"]) - float(b["z"])) ** 2
    )


def angle_delta_deg(a: float, b: float) -> float:
    return (a - b + 180.0) % 360.0 - 180.0


def row_speed(row: dict[str, object]) -> float:
    zjump = row.get("zjump_state")
    if isinstance(zjump, dict) and "horizontal_speed" in zjump:
        return float(zjump["horizontal_speed"])

    water = row.get("water_state")
    if isinstance(water, dict):
        velocity = water.get("velocity")
        if isinstance(velocity, dict):
            return math.hypot(float(velocity.get("x", 0.0)), float(velocity.get("y", 0.0)))

    return 0.0


def row_formula_score(row: dict[str, object]) -> float:
    """Lower score means closer to the successful human release formula."""
    origin = row.get("origin")
    if not isinstance(origin, dict):
        return float("inf")

    zjump = row.get("zjump_state")
    if not isinstance(zjump, dict):
        return float("inf")

    speed = float(zjump.get("horizontal_speed", 0.0))
    speed_shortfall = max(0.0, HUMAN_RELEASE["horizontal_speed"] - speed)
    speed_excess = max(0.0, speed - HUMAN_RELEASE["horizontal_speed"])
    release_dist = distance_h(origin, HUMAN_RELEASE["origin"])
    d_lip_err = abs(float(zjump.get("d_lip_qu", 999999.0)) - HUMAN_RELEASE["d_lip_qu"])
    vel_yaw_err = abs(
        angle_delta_deg(float(zjump.get("velocity_yaw_deg", 0.0)), HUMAN_RELEASE["velocity_yaw_deg"])
    )
    target_err = abs(float(zjump.get("target_error_deg", 0.0)) - HUMAN_RELEASE["target_error_deg"])
    yaw_lead_err = abs(float(zjump.get("yaw_lead_deg", 0.0)) - HUMAN_RELEASE["yaw_lead_deg"])

    # A speed shortfall blocks the jump harder than a small location miss. The
    # exact weights are only a ranking aid; raw fields remain in the report.
    return (
        speed_shortfall * 2.0
        + speed_excess * 0.25
        + release_dist * 1.0
        + d_lip_err * 0.75
        + vel_yaw_err * 2.0
        + target_err * 1.5
        + yaw_lead_err * 1.5
    )


def has_attempt_signal(row: dict[str, object]) -> bool:
    name = str(row.get("name", "")).strip()
    return bool(name) and isinstance(row.get("origin"), dict) and (
        int(row.get("mode", -1)) == 23 or isinstance(row.get("zjump_state"), dict)
    )


def split_attempts(
    commands: list[dict[str, object]],
    *,
    gap_s: float = 0.75,
    spawn_radius_qu: float = 32.0,
    min_rows_before_spawn_split: int = 4,
) -> list[dict[str, object]]:
    """Split command rows into attempts per bot, then return them in time order."""
    by_bot: dict[tuple[int, str], list[dict[str, object]]] = {}
    for row in commands:
        if not has_attempt_signal(row):
            continue
        key = (int(row["ed"]), str(row["name"]))
        by_bot.setdefault(key, []).append(row)

    attempts: list[dict[str, object]] = []
    for (ed, name), rows in by_bot.items():
        rows = sorted(rows, key=lambda row: float(row["time_s"]))
        current: list[dict[str, object]] = []
        for row in rows:
            origin = row["origin"]
            near_spawn = distance_h(origin, SPAWN_ORIGIN) <= spawn_radius_qu
            start_new = False
            if current:
                prev = current[-1]
                gap = float(row["time_s"]) - float(prev["time_s"])
                prev_origin = prev.get("origin", {})
                prev_near_spawn = (
                    isinstance(prev_origin, dict)
                    and distance_h(prev_origin, SPAWN_ORIGIN) <= spawn_radius_qu
                )
                start_new = gap > gap_s or (
                    near_spawn and not prev_near_spawn and len(current) >= min_rows_before_spawn_split
                )
            if start_new:
                attempts.append({"ed": ed, "name": name, "rows": current})
                current = []
            current.append(row)
        if current:
            attempts.append({"ed": ed, "name": name, "rows": current})

    attempts.sort(key=lambda attempt: float(attempt["rows"][0]["time_s"]))
    for idx, attempt in enumerate(attempts, start=1):
        attempt["attempt_index"] = idx
    return attempts


def enrich_row(row: dict[str, object]) -> dict[str, object]:
    origin = row.get("origin") if isinstance(row.get("origin"), dict) else None
    zjump = row.get("zjump_state") if isinstance(row.get("zjump_state"), dict) else {}
    return {
        "time_s": round(float(row.get("time_s", 0.0)), 3),
        "origin": origin,
        "horizontal_speed": round(row_speed(row), 3),
        "release_distance_h_qu": round(distance_h(origin, HUMAN_RELEASE["origin"]), 3) if origin else None,
        "release_distance_3d_qu": round(distance_3d(origin, HUMAN_RELEASE["origin"]), 3) if origin else None,
        "landing_distance_h_qu": round(distance_h(origin, HUMAN_LANDING["origin"]), 3) if origin else None,
        "landing_distance_3d_qu": round(distance_3d(origin, HUMAN_LANDING["origin"]), 3) if origin else None,
        "formula_score": round(row_formula_score(row), 3),
        "buttons": int(row.get("buttons", 0)),
        "move": row.get("move"),
        "zjump_state": zjump,
    }


def classify_attempt(summary: dict[str, object]) -> str:
    if int(summary["release_rows"]) > 0:
        return "released"
    if int(summary["armed_rows"]) > 0:
        return "armed_without_release"
    if float(summary["max_zjump_speed"]) < 453.0:
        return "approach_speed_below_release_floor"
    if summary["closest_release"]:
        return "release_geometry_miss"
    return "no_zjump_data"


def summarize_attempt(attempt: dict[str, object]) -> dict[str, object]:
    rows: list[dict[str, object]] = list(attempt["rows"])
    zjump_rows = [row for row in rows if isinstance(row.get("zjump_state"), dict)]
    origins = [row for row in rows if isinstance(row.get("origin"), dict)]

    phase_counts: Counter[int] = Counter()
    armed_rows = 0
    release_rows = 0
    for row in zjump_rows:
        zjump = row["zjump_state"]
        phase_counts[int(zjump.get("phase", 0))] += 1
        if bool(zjump.get("armed", False)):
            armed_rows += 1
        if int(zjump.get("release_rule", 0)) > 0:
            release_rows += 1

    best_formula = min(zjump_rows, key=row_formula_score) if zjump_rows else None
    closest_release = (
        min(origins, key=lambda row: distance_h(row["origin"], HUMAN_RELEASE["origin"]))
        if origins
        else None
    )
    closest_landing = (
        min(origins, key=lambda row: distance_h(row["origin"], HUMAN_LANDING["origin"]))
        if origins
        else None
    )
    fastest = max(rows, key=row_speed) if rows else None

    start_time = float(rows[0]["time_s"]) if rows else 0.0
    end_time = float(rows[-1]["time_s"]) if rows else 0.0
    max_speed = row_speed(fastest) if fastest else 0.0
    summary = {
        "attempt_index": int(attempt["attempt_index"]),
        "ed": int(attempt["ed"]),
        "name": str(attempt["name"]),
        "row_count": len(rows),
        "zjump_row_count": len(zjump_rows),
        "start_time_s": round(start_time, 3),
        "end_time_s": round(end_time, 3),
        "duration_s": round(max(0.0, end_time - start_time), 3),
        "phase_counts": {str(k): v for k, v in sorted(phase_counts.items())},
        "armed_rows": armed_rows,
        "release_rows": release_rows,
        "jump_button_rows": sum(1 for row in rows if int(row.get("buttons", 0)) & BUTTON_JUMP),
        "nonzero_move_rows": sum(
            1
            for row in rows
            if isinstance(row.get("move"), dict)
            and (
                int(row["move"].get("forward", 0)) != 0
                or int(row["move"].get("side", 0)) != 0
                or int(row["move"].get("up", 0)) != 0
            )
        ),
        "max_zjump_speed": round(max_speed, 3),
        "max_speed_pct_human_release": round(max_speed / HUMAN_RELEASE["horizontal_speed"], 3)
        if HUMAN_RELEASE["horizontal_speed"]
        else None,
        "best_formula": enrich_row(best_formula) if best_formula else None,
        "closest_release": enrich_row(closest_release) if closest_release else None,
        "closest_landing": enrich_row(closest_landing) if closest_landing else None,
    }
    summary["classification"] = classify_attempt(summary)
    return summary


def score_commands(
    commands: list[dict[str, object]],
    *,
    gap_s: float = 0.75,
    spawn_radius_qu: float = 32.0,
    run_id: str = "",
) -> dict[str, object]:
    attempts = split_attempts(commands, gap_s=gap_s, spawn_radius_qu=spawn_radius_qu)
    summaries = [summarize_attempt(attempt) for attempt in attempts]

    best_formula = min(
        (s for s in summaries if s.get("best_formula")),
        key=lambda s: float(s["best_formula"]["formula_score"]),
        default=None,
    )
    best_landing = min(
        (s for s in summaries if s.get("closest_landing")),
        key=lambda s: float(s["closest_landing"]["landing_distance_h_qu"]),
        default=None,
    )
    fastest = max(summaries, key=lambda s: float(s["max_zjump_speed"]), default=None)

    return {
        "schema": "komodobots.ztricks_batch_score.v1",
        "run_id": run_id,
        "human_reference": {
            "spawn_origin": SPAWN_ORIGIN,
            "release": HUMAN_RELEASE,
            "landing": HUMAN_LANDING,
        },
        "command_count": len(commands),
        "attempt_count": len(summaries),
        "best_formula_attempt": best_formula["attempt_index"] if best_formula else None,
        "best_landing_attempt": best_landing["attempt_index"] if best_landing else None,
        "fastest_attempt": fastest["attempt_index"] if fastest else None,
        "attempts": summaries,
    }


def read_commands(run_dir: Path) -> list[dict[str, object]]:
    document = load_json(run_dir / "moveprobe-commands.json")
    commands = document.get("commands")
    if not isinstance(commands, list):
        raise ValueError(f"{run_dir / 'moveprobe-commands.json'} does not contain a commands list")
    return commands


def score_run_dir(run_dir: Path, *, gap_s: float = 0.75, spawn_radius_qu: float = 32.0) -> dict[str, object]:
    return score_commands(
        read_commands(run_dir),
        gap_s=gap_s,
        spawn_radius_qu=spawn_radius_qu,
        run_id=run_dir.name,
    )


def fmt(value: object, digits: int = 1) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def render_markdown(report: dict[str, object]) -> str:
    lines = [
        f"# ztricks batch score: {report.get('run_id') or 'commands'}",
        "",
        f"- Attempts scored: `{report['attempt_count']}`",
        f"- Best release-formula attempt: `{report['best_formula_attempt']}`",
        f"- Fastest attempt: `{report['fastest_attempt']}`",
        f"- Best landing-distance attempt: `{report['best_landing_attempt']}`",
        "",
        "| # | bot | rows | max vh | closest release | best formula | armed/release | closest landing | class |",
        "|---:|---|---:|---:|---|---|---|---|---|",
    ]
    for attempt in report["attempts"]:
        closest_release = attempt.get("closest_release") or {}
        best_formula = attempt.get("best_formula") or {}
        closest_landing = attempt.get("closest_landing") or {}
        best_zjump = best_formula.get("zjump_state") or {}
        release_text = (
            f"{fmt(closest_release.get('release_distance_h_qu'))}q @ "
            f"{fmt(closest_release.get('horizontal_speed'))}"
        )
        formula_text = (
            f"score {fmt(best_formula.get('formula_score'))}, "
            f"vh {fmt(best_formula.get('horizontal_speed'))}, "
            f"d_lip {fmt(best_zjump.get('d_lip_qu'))}, "
            f"vel {fmt(best_zjump.get('velocity_yaw_deg'))}, "
            f"err {fmt(best_zjump.get('target_error_deg'))}, "
            f"lead {fmt(best_zjump.get('yaw_lead_deg'))}"
        )
        landing_text = (
            f"{fmt(closest_landing.get('landing_distance_h_qu'))}q @ "
            f"{fmt(closest_landing.get('horizontal_speed'))}"
        )
        lines.append(
            f"| {attempt['attempt_index']} | `{attempt['name']}` ed `{attempt['ed']}` | "
            f"{attempt['row_count']} | {fmt(attempt['max_zjump_speed'])} | "
            f"{release_text} | {formula_text} | "
            f"{attempt['armed_rows']}/{attempt['release_rows']} | "
            f"{landing_text} | `{attempt['classification']}` |"
        )

    if not report["attempts"]:
        lines.append("")
        lines.append("No mode-23/zjump command rows with origins were found.")
    return "\n".join(lines) + "\n"


def write_outputs(report: dict[str, object], output_json: Path, output_md: Path) -> None:
    output_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    output_md.write_text(render_markdown(report), encoding="utf-8")


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score batched ztricks Distance attempts.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--run-id", help="Lab run id under artifacts/lab-runs/.")
    group.add_argument("--run-dir", type=Path, help="Explicit run directory.")
    parser.add_argument("--gap-s", type=float, default=0.75, help="Time gap that starts a new attempt.")
    parser.add_argument(
        "--spawn-radius",
        type=float,
        default=32.0,
        help="Spawn-snap radius in qu used to split same-ed repeated attempts.",
    )
    parser.add_argument("--output-json", type=Path, default=None, help="Output JSON path.")
    parser.add_argument("--output-md", type=Path, default=None, help="Output Markdown path.")
    return parser.parse_args(list(argv))


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    run_dir = args.run_dir or DEFAULT_ARTIFACTS_ROOT / args.run_id
    if not run_dir.is_dir():
        print(f"Run directory not found: {run_dir}", file=sys.stderr)
        return 2
    try:
        report = score_run_dir(run_dir, gap_s=args.gap_s, spawn_radius_qu=args.spawn_radius)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Could not score run: {exc}", file=sys.stderr)
        return 2
    output_json = args.output_json or run_dir / "ztricks-batch-score.json"
    output_md = args.output_md or run_dir / "ztricks-batch-score.md"
    write_outputs(report, output_json, output_md)
    print(render_markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
