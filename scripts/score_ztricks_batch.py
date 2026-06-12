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

import ztricks_reference_trace as ref


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARTIFACTS_ROOT = REPO_ROOT / "artifacts" / "lab-runs"

BUTTON_JUMP = 2

SPAWN_ORIGIN = {"x": -3516.125, "y": 3712.0, "z": -453.125}
HUMAN_RELEASE = ref.HUMAN_RELEASE
HUMAN_LANDING = ref.HUMAN_LANDING
PHYSICAL_LIP_X = ref.PHYSICAL_LIP_X


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


def interpolate_zjump_state(a: dict[str, object], b: dict[str, object], alpha: float) -> dict[str, object]:
    az = a.get("zjump_state")
    bz = b.get("zjump_state")
    if not isinstance(az, dict) or not isinstance(bz, dict):
        chosen = az if alpha < 0.5 else bz
        return dict(chosen) if isinstance(chosen, dict) else {}
    return {
        "phase": int(az.get("phase", 0)) if alpha < 0.5 else int(bz.get("phase", 0)),
        "d_lip_qu": ref.lerp(float(az.get("d_lip_qu", 999999.0)), float(bz.get("d_lip_qu", 999999.0)), alpha),
        "horizontal_speed": ref.lerp(
            float(az.get("horizontal_speed", 0.0)),
            float(bz.get("horizontal_speed", 0.0)),
            alpha,
        ),
        "velocity_yaw_deg": ref.lerp_angle_deg(
            float(az.get("velocity_yaw_deg", 0.0)),
            float(bz.get("velocity_yaw_deg", 0.0)),
            alpha,
        ),
        "target_yaw_deg": ref.lerp_angle_deg(
            float(az.get("target_yaw_deg", 0.0)),
            float(bz.get("target_yaw_deg", 0.0)),
            alpha,
        ),
        "target_error_deg": ref.lerp_angle_deg(
            float(az.get("target_error_deg", 0.0)),
            float(bz.get("target_error_deg", 0.0)),
            alpha,
        ),
        "yaw_lead_deg": ref.lerp_angle_deg(
            float(az.get("yaw_lead_deg", 0.0)),
            float(bz.get("yaw_lead_deg", 0.0)),
            alpha,
        ),
        "armed": bool(az.get("armed", False)) if alpha < 0.5 else bool(bz.get("armed", False)),
        "release_rule": int(az.get("release_rule", 0)) if alpha < 0.5 else int(bz.get("release_rule", 0)),
    }


def interpolate_attempt_rows(a: dict[str, object], b: dict[str, object], alpha: float) -> dict[str, object]:
    origin_a = a["origin"]
    origin_b = b["origin"]
    row = {
        "time_s": ref.lerp(float(a["time_s"]), float(b["time_s"]), alpha),
        "ed": int(a["ed"]),
        "name": str(a["name"]),
        "mode": int(a.get("mode", 23)),
        "msec": int(a.get("msec", 0)) if alpha < 0.5 else int(b.get("msec", 0)),
        "angles": a.get("angles") if alpha < 0.5 else b.get("angles"),
        "move": a.get("move") if alpha < 0.5 else b.get("move"),
        "buttons": int(a.get("buttons", 0)) if alpha < 0.5 else int(b.get("buttons", 0)),
        "impulse": int(a.get("impulse", 0)) if alpha < 0.5 else int(b.get("impulse", 0)),
        "origin": {
            axis: ref.lerp(float(origin_a[axis]), float(origin_b[axis]), alpha)
            for axis in ("x", "y", "z")
        },
        "zjump_state": interpolate_zjump_state(a, b, alpha),
        "interpolated": True,
        "interpolation_alpha": round(alpha, 6),
        "interpolated_between_time_s": [
            round(float(a["time_s"]), 6),
            round(float(b["time_s"]), 6),
        ],
    }
    return row


def project_point_to_segment(
    a: dict[str, object],
    b: dict[str, object],
    point: dict[str, object],
) -> tuple[float, dict[str, object]]:
    ao = a["origin"]
    bo = b["origin"]
    ax = float(ao["x"])
    ay = float(ao["y"])
    bx = float(bo["x"])
    by = float(bo["y"])
    px = float(point["x"])
    py = float(point["y"])
    dx = bx - ax
    dy = by - ay
    length_sq = dx * dx + dy * dy
    alpha = 0.0 if length_sq <= 1e-9 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
    row = interpolate_attempt_rows(a, b, alpha)
    distance = distance_h(row["origin"], point)
    row["projection_distance_h_qu"] = round(distance, 3)
    return distance, row


def continuous_closest_row(rows: list[dict[str, object]], point: dict[str, object]) -> dict[str, object] | None:
    origin_rows = [row for row in rows if isinstance(row.get("origin"), dict)]
    if not origin_rows:
        return None
    best_distance = float("inf")
    best_row: dict[str, object] | None = None
    for row in origin_rows:
        dist = distance_h(row["origin"], point)
        if dist < best_distance:
            best_distance = dist
            best_row = dict(row)
            best_row["projection_distance_h_qu"] = round(dist, 3)
            best_row["interpolated"] = False
    for a, b in zip(origin_rows, origin_rows[1:]):
        dist, projected = project_point_to_segment(a, b, point)
        if dist < best_distance:
            best_distance = dist
            best_row = projected
    return best_row


def x_crossing_event(rows: list[dict[str, object]], x: float) -> dict[str, object] | None:
    origin_rows = [row for row in rows if isinstance(row.get("origin"), dict)]
    for a, b in zip(origin_rows, origin_rows[1:]):
        ax = float(a["origin"]["x"])
        bx = float(b["origin"]["x"])
        if (ax <= x <= bx) or (bx <= x <= ax):
            alpha = 0.0 if abs(bx - ax) < 1e-9 else (x - ax) / (bx - ax)
            row = interpolate_attempt_rows(a, b, alpha)
            row["event_axis"] = "x"
            row["event_value"] = x
            return row
    closest = continuous_closest_row(origin_rows, {"x": x, "y": HUMAN_RELEASE["origin"]["y"], "z": HUMAN_RELEASE["origin"]["z"]})
    if closest is not None:
        closest["event_axis"] = "x"
        closest["event_value"] = x
        closest["event_fallback"] = "closest_sample_or_segment"
    return closest


def first_matching_row(rows: list[dict[str, object]], predicate) -> dict[str, object] | None:
    for row in rows:
        if predicate(row):
            out = dict(row)
            out["interpolated"] = False
            return out
    return None


def reference_event_summary(reference_trace: dict[str, object] | None) -> dict[str, object] | None:
    if not reference_trace:
        return None
    events = reference_trace.get("events")
    if not isinstance(events, dict):
        return None
    return {
        "schema": reference_trace.get("schema"),
        "source": reference_trace.get("source", {}),
        "events": {
            name: events.get(name)
            for name in ("release_jump", "physical_lip_x_crossing", "landing")
            if name in events
        },
    }


def compare_to_reference_event(row: dict[str, object] | None, reference_event: dict[str, object] | None) -> dict[str, object] | None:
    if row is None or reference_event is None:
        return None
    zjump = row.get("zjump_state") if isinstance(row.get("zjump_state"), dict) else {}
    origin = row.get("origin") if isinstance(row.get("origin"), dict) else None
    ref_origin = reference_event.get("origin") if isinstance(reference_event.get("origin"), dict) else None
    return {
        "time_error_s": round(float(row.get("time_s", 0.0)) - float(reference_event.get("time_s", 0.0)), 6),
        "position_error_h_qu": round(distance_h(origin, ref_origin), 3) if origin and ref_origin else None,
        "position_error_3d_qu": round(distance_3d(origin, ref_origin), 3) if origin and ref_origin else None,
        "speed_error": round(row_speed(row) - float(reference_event.get("horizontal_speed", 0.0)), 3),
        "velocity_yaw_error_deg": round(
            angle_delta_deg(float(zjump.get("velocity_yaw_deg", 0.0)), float(reference_event.get("velocity_yaw_deg", 0.0))),
            3,
        )
        if zjump
        else None,
        "target_error_delta_deg": round(
            angle_delta_deg(float(zjump.get("target_error_deg", 0.0)), float(reference_event.get("target_error_deg", 0.0))),
            3,
        )
        if zjump
        else None,
        "yaw_lead_delta_deg": round(
            angle_delta_deg(float(zjump.get("yaw_lead_deg", 0.0)), float(reference_event.get("yaw_lead_deg", 0.0))),
            3,
        )
        if zjump
        else None,
        "d_lip_error_qu": round(float(zjump.get("d_lip_qu", 0.0)) - float(reference_event.get("d_lip_qu", 0.0)), 3)
        if zjump
        else None,
    }


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
    enriched = {
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
    for key in (
        "interpolated",
        "interpolation_alpha",
        "interpolated_between_time_s",
        "projection_distance_h_qu",
        "event_axis",
        "event_value",
        "event_fallback",
    ):
        if key in row:
            enriched[key] = row[key]
    return enriched


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


def summarize_attempt(
    attempt: dict[str, object],
    *,
    reference_events: dict[str, object] | None = None,
) -> dict[str, object]:
    rows: list[dict[str, object]] = list(attempt["rows"])
    zjump_rows = [row for row in rows if isinstance(row.get("zjump_state"), dict)]
    reference_events = reference_events or {}

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

    continuous_release = continuous_closest_row(rows, HUMAN_RELEASE["origin"])
    continuous_landing = continuous_closest_row(rows, HUMAN_LANDING["origin"])
    physical_lip_crossing = x_crossing_event(rows, PHYSICAL_LIP_X)
    first_jump = first_matching_row(rows, lambda row: bool(int(row.get("buttons", 0)) & BUTTON_JUMP))
    formula_candidates = [row for row in zjump_rows if isinstance(row.get("zjump_state"), dict)]
    for candidate in (continuous_release, physical_lip_crossing, first_jump):
        if candidate is not None and isinstance(candidate.get("zjump_state"), dict):
            formula_candidates.append(candidate)
    best_formula = min(formula_candidates, key=row_formula_score) if formula_candidates else None
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
        "closest_release": enrich_row(continuous_release) if continuous_release else None,
        "physical_lip_x_crossing": enrich_row(physical_lip_crossing) if physical_lip_crossing else None,
        "first_jump": enrich_row(first_jump) if first_jump else None,
        "closest_landing": enrich_row(continuous_landing) if continuous_landing else None,
        "release_vs_reference": compare_to_reference_event(
            continuous_release,
            reference_events.get("release_jump") if isinstance(reference_events, dict) else None,
        ),
        "lip_vs_reference": compare_to_reference_event(
            physical_lip_crossing,
            reference_events.get("physical_lip_x_crossing") if isinstance(reference_events, dict) else None,
        ),
        "landing_vs_reference": compare_to_reference_event(
            continuous_landing,
            reference_events.get("landing") if isinstance(reference_events, dict) else None,
        ),
    }
    summary["classification"] = classify_attempt(summary)
    return summary


def score_commands(
    commands: list[dict[str, object]],
    *,
    gap_s: float = 0.75,
    spawn_radius_qu: float = 32.0,
    run_id: str = "",
    reference_trace: dict[str, object] | None = None,
) -> dict[str, object]:
    attempts = split_attempts(commands, gap_s=gap_s, spawn_radius_qu=spawn_radius_qu)
    reference_events = {}
    if reference_trace and isinstance(reference_trace.get("events"), dict):
        reference_events = reference_trace["events"]
    summaries = [
        summarize_attempt(attempt, reference_events=reference_events)
        for attempt in attempts
    ]

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
        "interpolation": {
            "attempt_events": "xy_projection_onto_adjacent_bot_samples",
            "lip_crossing": "piecewise_linear_x_crossing",
            "reference": reference_event_summary(reference_trace),
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


def load_reference_trace(path: Path | None = None) -> dict[str, object]:
    trace_path = path or ref.DEFAULT_TRACE_JSON
    if trace_path.is_file():
        return load_json(trace_path)
    return ref.build_trace()


def score_run_dir(
    run_dir: Path,
    *,
    gap_s: float = 0.75,
    spawn_radius_qu: float = 32.0,
    reference_trace: dict[str, object] | None = None,
) -> dict[str, object]:
    return score_commands(
        read_commands(run_dir),
        gap_s=gap_s,
        spawn_radius_qu=spawn_radius_qu,
        run_id=run_dir.name,
        reference_trace=reference_trace or load_reference_trace(),
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
        f"- Attempt-event interpolation: `{report.get('interpolation', {}).get('attempt_events', 'n/a')}`",
        f"- Lip-crossing interpolation: `{report.get('interpolation', {}).get('lip_crossing', 'n/a')}`",
        "",
        "| # | bot | rows | max vh | release projection | lip x=-3348 | best formula | armed/release | landing projection | class |",
        "|---:|---|---:|---:|---|---|---|---|---|---|",
    ]
    for attempt in report["attempts"]:
        closest_release = attempt.get("closest_release") or {}
        physical_lip = attempt.get("physical_lip_x_crossing") or {}
        best_formula = attempt.get("best_formula") or {}
        closest_landing = attempt.get("closest_landing") or {}
        best_zjump = best_formula.get("zjump_state") or {}
        release_text = (
            f"{fmt(closest_release.get('release_distance_h_qu'))}q @ "
            f"{fmt(closest_release.get('horizontal_speed'))}"
        )
        lip_text = (
            f"{fmt(physical_lip.get('time_s'), 3)}s @ "
            f"{fmt(physical_lip.get('horizontal_speed'))}"
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
            f"{release_text} | {lip_text} | {formula_text} | "
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
    parser.add_argument(
        "--reference-trace",
        type=Path,
        default=None,
        help="Interpolated ztricks reference trace JSON. Defaults to A5 generated trace.",
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
        report = score_run_dir(
            run_dir,
            gap_s=args.gap_s,
            spawn_radius_qu=args.spawn_radius,
            reference_trace=load_reference_trace(args.reference_trace),
        )
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
