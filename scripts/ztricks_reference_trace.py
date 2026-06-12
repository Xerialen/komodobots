"""Interpolated ztricks Distance human-reference trace helpers."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
A5_DIR = REPO_ROOT / "experiments" / "a5_distance_standstill"
DEFAULT_CMDS = A5_DIR / "getspeed-aligned.cmds"
DEFAULT_HUMAN_REPLAY = A5_DIR / "human-replay.json"
DEFAULT_TRACE_JSON = A5_DIR / "ztricks-reference-trace.json"
DEFAULT_TRACE_MD = A5_DIR / "ztricks-reference-trace.md"

SCHEMA = "komodobots.ztricks_reference_trace.v1"
BUTTON_JUMP = 2
SUCCESS_ATTEMPT = 11
PHYSICAL_LIP_X = -3348.0
CONTROLLER_SAMPLE_STEP_S = 0.01

TERMINAL_EVENT_ROWS = {
    "attempt_start": 1807,
    "first_grounded": 1830,
    "terminal_sweep_start": 1904,
    "speed_floor_crossed": 1908,
    "aligned_near_target_line": 1916,
}


def wrap_angle_deg(angle: float) -> float:
    return (angle + 180.0) % 360.0 - 180.0


def angle_delta_deg(a: float, b: float) -> float:
    return wrap_angle_deg(a - b)


def unwrap_angles(values: Iterable[float]) -> list[float]:
    result: list[float] = []
    previous: float | None = None
    for value in values:
        current = float(value)
        if previous is None:
            result.append(current)
            previous = current
            continue
        current = previous + angle_delta_deg(current, previous)
        result.append(current)
        previous = current
    return result


def lerp(a: float, b: float, alpha: float) -> float:
    return a + (b - a) * alpha


def lerp_angle_deg(a: float, b: float, alpha: float) -> float:
    return wrap_angle_deg(a + angle_delta_deg(b, a) * alpha)


def quadratic_lagrange(x: float, points: list[tuple[float, float]]) -> float:
    """Evaluate a local quadratic through three points.

    This is intentionally local and per-attempt. It is a spline-style smoother
    for controller guidance, not an event-crossing proof. If a duplicate x
    sneaks in, fall back to the safer linear interpolation over the end points.
    """
    if len(points) != 3:
        raise ValueError("quadratic_lagrange needs exactly three points")
    if len({round(px, 9) for px, _ in points}) < 3:
        points = sorted(points)
        x0, y0 = points[0]
        x1, y1 = points[-1]
        alpha = 0.0 if abs(x1 - x0) < 1e-9 else (x - x0) / (x1 - x0)
        return lerp(y0, y1, alpha)

    total = 0.0
    for i, (xi, yi) in enumerate(points):
        basis = 1.0
        for j, (xj, _yj) in enumerate(points):
            if i == j:
                continue
            basis *= (x - xj) / (xi - xj)
        total += yi * basis
    return total


def distance_h(a: dict[str, object], b: dict[str, object]) -> float:
    return math.hypot(float(a["x"]) - float(b["x"]), float(a["y"]) - float(b["y"]))


def distance_3d(a: dict[str, object], b: dict[str, object]) -> float:
    return math.sqrt(
        (float(a["x"]) - float(b["x"])) ** 2
        + (float(a["y"]) - float(b["y"])) ** 2
        + (float(a["z"]) - float(b["z"])) ** 2
    )


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def parse_cmds(path: Path = DEFAULT_CMDS) -> tuple[dict[str, str], list[dict[str, object]]]:
    header: dict[str, str] = {}
    rows: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        if line.startswith("#"):
            parts = line[1:].strip().split()
            if parts:
                header["schema"] = parts[0]
            for token in parts[1:]:
                if "=" in token:
                    key, value = token.split("=", 1)
                    header[key] = value
            continue
        parts = line.split()
        if len(parts) != 14:
            raise ValueError(f"Expected 14 fields in {path}, got {len(parts)}: {line}")
        index = len(rows)
        rows.append(
            {
                "source_row": index,
                "msec": int(parts[0]),
                "origin": {"x": float(parts[1]), "y": float(parts[2]), "z": float(parts[3])},
                "velocity": {"x": float(parts[4]), "y": float(parts[5]), "z": float(parts[6])},
                "angles": {"pitch": float(parts[7]), "yaw": float(parts[8]), "roll": float(parts[9])},
                "move": {"forward": int(parts[10]), "side": int(parts[11]), "up": int(parts[12])},
                "buttons": int(parts[13]),
            }
        )
    return header, rows


def success_bounds(human_replay_path: Path = DEFAULT_HUMAN_REPLAY) -> dict[str, int]:
    human = load_json(human_replay_path)
    attempt = next(
        row for row in human["attempt_table"] if int(row["attempt"]) == SUCCESS_ATTEMPT
    )
    checkpoints = human["verdict"]["checkpoints"]
    return {
        "attempt_start_row": int(attempt["rows"][0]),
        "attempt_end_row": int(attempt["rows"][1]),
        "release_row": int(checkpoints["lip"]["row"]),
        "landing_row": int(checkpoints["landing"]["row"]),
    }


def normalize_row(row: dict[str, object], *, start_row: int, time_s: float, arc_h: float, arc_3d: float) -> dict[str, object]:
    origin = row["origin"]
    velocity = row["velocity"]
    angles = row["angles"]
    vx = float(velocity["x"])
    vy = float(velocity["y"])
    speed = math.hypot(vx, vy)
    velocity_yaw = math.degrees(math.atan2(vy, vx)) if speed > 0.001 else 0.0
    target_yaw = math.degrees(
        math.atan2(HUMAN_LANDING["origin"]["y"] - float(origin["y"]), HUMAN_LANDING["origin"]["x"] - float(origin["x"]))
    )
    view_yaw = float(angles["yaw"])
    return {
        "source_row": int(row["source_row"]),
        "attempt_row": int(row["source_row"]) - start_row,
        "time_s": round(time_s, 6),
        "arc_h_qu": round(arc_h, 3),
        "arc_3d_qu": round(arc_3d, 3),
        "origin": origin,
        "velocity": velocity,
        "horizontal_speed": round(speed, 3),
        "velocity_yaw_deg": round(wrap_angle_deg(velocity_yaw), 3),
        "view_yaw_deg": round(wrap_angle_deg(view_yaw), 3),
        "target_yaw_deg": round(wrap_angle_deg(target_yaw), 3),
        "target_error_deg": round(angle_delta_deg(target_yaw, velocity_yaw), 3),
        "yaw_lead_deg": round(angle_delta_deg(view_yaw, velocity_yaw), 3),
        "d_lip_qu": round(PHYSICAL_LIP_X - float(origin["x"]), 3),
        "move": row["move"],
        "buttons": int(row["buttons"]),
        "jump_button": bool(int(row["buttons"]) & BUTTON_JUMP),
    }


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


def build_trace(
    *,
    cmds_path: Path = DEFAULT_CMDS,
    human_replay_path: Path = DEFAULT_HUMAN_REPLAY,
) -> dict[str, object]:
    header, all_rows = parse_cmds(cmds_path)
    bounds = success_bounds(human_replay_path)
    start = bounds["attempt_start_row"]
    end = bounds["landing_row"]
    dropped = set(load_json(A5_DIR / "alignment-meta.json").get("dropped_cmd_indices", []))

    rows: list[dict[str, object]] = []
    time_s = 0.0
    arc_h = 0.0
    arc_3d = 0.0
    previous: dict[str, object] | None = None
    for source_row in range(start, end + 1):
        source = all_rows[source_row]
        if previous is not None:
            arc_h += distance_h(previous["origin"], source["origin"])
            arc_3d += distance_3d(previous["origin"], source["origin"])
            time_s += float(previous["msec"]) / 1000.0
        out = normalize_row(source, start_row=start, time_s=time_s, arc_h=arc_h, arc_3d=arc_3d)
        out["reference_state_interpolated"] = source_row in dropped
        rows.append(out)
        previous = source

    view_unwrapped = unwrap_angles(row["view_yaw_deg"] for row in rows)
    velocity_unwrapped = unwrap_angles(row["velocity_yaw_deg"] for row in rows)
    target_unwrapped = unwrap_angles(row["target_yaw_deg"] for row in rows)
    target_error_unwrapped = unwrap_angles(row["target_error_deg"] for row in rows)
    yaw_lead_unwrapped = unwrap_angles(row["yaw_lead_deg"] for row in rows)
    for row, view, velocity, target, target_error, yaw_lead in zip(
        rows,
        view_unwrapped,
        velocity_unwrapped,
        target_unwrapped,
        target_error_unwrapped,
        yaw_lead_unwrapped,
    ):
        row["view_yaw_unwrapped_deg"] = round(view, 3)
        row["velocity_yaw_unwrapped_deg"] = round(velocity, 3)
        row["target_yaw_unwrapped_deg"] = round(target, 3)
        row["target_error_unwrapped_deg"] = round(target_error, 3)
        row["yaw_lead_unwrapped_deg"] = round(yaw_lead, 3)

    events = build_events(rows, bounds)
    controller_curve = build_controller_curve(rows, events)
    return {
        "schema": SCHEMA,
        "source": {
            "cmds": str(cmds_path),
            "human_replay": str(human_replay_path),
            "demo": header.get("demo"),
            "sha256": header.get("sha256"),
            "fps": float(header.get("fps", "76.999")),
            "attempt": SUCCESS_ATTEMPT,
            **bounds,
        },
        "constants": {
            "physical_lip_x": PHYSICAL_LIP_X,
            "human_release": HUMAN_RELEASE,
            "human_landing": HUMAN_LANDING,
        },
        "interpolation": {
            "event_crossings": "piecewise_linear_between_adjacent_rows",
            "closest_points": "xy_projection_onto_adjacent_row_segments",
            "controller_curve": "local_quadratic_lagrange_by_time_on_successful_attempt",
            "angle_policy": "unwrap_before_interpolation_wrap_for_display",
            "discontinuity_policy": "do_not_cross_attempt_or_teleport_boundaries",
        },
        "events": events,
        "controller_curve": controller_curve,
        "rows": rows,
    }


def interpolate_rows(a: dict[str, object], b: dict[str, object], alpha: float) -> dict[str, object]:
    origin = {
        axis: round(lerp(float(a["origin"][axis]), float(b["origin"][axis]), alpha), 3)
        for axis in ("x", "y", "z")
    }
    velocity = {
        axis: round(lerp(float(a["velocity"][axis]), float(b["velocity"][axis]), alpha), 3)
        for axis in ("x", "y", "z")
    }
    row: dict[str, object] = {
        "source_row": f"{a['source_row']}..{b['source_row']}",
        "attempt_row": round(lerp(float(a["attempt_row"]), float(b["attempt_row"]), alpha), 3),
        "time_s": round(lerp(float(a["time_s"]), float(b["time_s"]), alpha), 6),
        "arc_h_qu": round(lerp(float(a["arc_h_qu"]), float(b["arc_h_qu"]), alpha), 3),
        "arc_3d_qu": round(lerp(float(a["arc_3d_qu"]), float(b["arc_3d_qu"]), alpha), 3),
        "origin": origin,
        "velocity": velocity,
        "horizontal_speed": round(lerp(float(a["horizontal_speed"]), float(b["horizontal_speed"]), alpha), 3),
        "velocity_yaw_deg": round(lerp_angle_deg(float(a["velocity_yaw_deg"]), float(b["velocity_yaw_deg"]), alpha), 3),
        "view_yaw_deg": round(lerp_angle_deg(float(a["view_yaw_deg"]), float(b["view_yaw_deg"]), alpha), 3),
        "target_yaw_deg": round(lerp_angle_deg(float(a["target_yaw_deg"]), float(b["target_yaw_deg"]), alpha), 3),
        "target_error_deg": round(lerp_angle_deg(float(a["target_error_deg"]), float(b["target_error_deg"]), alpha), 3),
        "yaw_lead_deg": round(lerp_angle_deg(float(a["yaw_lead_deg"]), float(b["yaw_lead_deg"]), alpha), 3),
        "d_lip_qu": round(lerp(float(a["d_lip_qu"]), float(b["d_lip_qu"]), alpha), 3),
        "move": a["move"] if alpha < 0.5 else b["move"],
        "buttons": int(a["buttons"]) if alpha < 0.5 else int(b["buttons"]),
        "jump_button": bool((int(a["buttons"]) if alpha < 0.5 else int(b["buttons"])) & BUTTON_JUMP),
        "interpolation_alpha": round(alpha, 6),
    }
    return row


def interpolate_by_source_row(rows: list[dict[str, object]], source_row: int) -> dict[str, object]:
    exact = next((row for row in rows if int(row["source_row"]) == source_row), None)
    if exact is not None:
        return exact
    lower = [row for row in rows if int(row["source_row"]) < source_row]
    upper = [row for row in rows if int(row["source_row"]) > source_row]
    if not lower or not upper:
        raise ValueError(f"source row {source_row} is outside the trace")
    a = lower[-1]
    b = upper[0]
    alpha = (source_row - int(a["source_row"])) / (int(b["source_row"]) - int(a["source_row"]))
    return interpolate_rows(a, b, alpha)


def interpolate_x_crossing(rows: list[dict[str, object]], x: float) -> dict[str, object]:
    for a, b in zip(rows, rows[1:]):
        ax = float(a["origin"]["x"])
        bx = float(b["origin"]["x"])
        if (ax <= x <= bx) or (bx <= x <= ax):
            if abs(bx - ax) < 1e-9:
                alpha = 0.0
            else:
                alpha = (x - ax) / (bx - ax)
            row = interpolate_rows(a, b, alpha)
            row["event_axis"] = "x"
            row["event_value"] = x
            return row
    closest = min(rows, key=lambda row: abs(float(row["origin"]["x"]) - x))
    out = dict(closest)
    out["event_axis"] = "x"
    out["event_value"] = x
    out["event_fallback"] = "closest_sample"
    return out


def build_events(rows: list[dict[str, object]], bounds: dict[str, int]) -> dict[str, object]:
    events: dict[str, object] = {}
    for name, source_row in TERMINAL_EVENT_ROWS.items():
        events[name] = interpolate_by_source_row(rows, source_row)
    events["release_jump"] = interpolate_by_source_row(rows, bounds["release_row"])
    events["physical_lip_x_crossing"] = interpolate_x_crossing(rows, PHYSICAL_LIP_X)
    events["landing"] = interpolate_by_source_row(rows, bounds["landing_row"])
    return events


def bracketing_index(rows: list[dict[str, object]], time_s: float) -> int:
    if time_s <= float(rows[0]["time_s"]):
        return 0
    for index, row in enumerate(rows[:-1]):
        if float(row["time_s"]) <= time_s <= float(rows[index + 1]["time_s"]):
            return index
    return max(0, len(rows) - 2)


def quadratic_triplet(rows: list[dict[str, object]], near_index: int) -> list[dict[str, object]]:
    if len(rows) < 3:
        return rows
    start = max(0, min(near_index - 1, len(rows) - 3))
    return rows[start : start + 3]


def qfield(triplet: list[dict[str, object]], time_s: float, key: str) -> float:
    if len(triplet) < 3:
        return float(triplet[0][key])
    return quadratic_lagrange(time_s, [(float(row["time_s"]), float(row[key])) for row in triplet])


def qnested(triplet: list[dict[str, object]], time_s: float, parent: str, key: str) -> float:
    if len(triplet) < 3:
        return float(triplet[0][parent][key])
    return quadratic_lagrange(time_s, [(float(row["time_s"]), float(row[parent][key])) for row in triplet])


def nearest_row(rows: list[dict[str, object]], time_s: float) -> dict[str, object]:
    return min(rows, key=lambda row: abs(float(row["time_s"]) - time_s))


def quadratic_sample(rows: list[dict[str, object]], time_s: float) -> dict[str, object]:
    index = bracketing_index(rows, time_s)
    triplet = quadratic_triplet(rows, index)
    nearest = nearest_row(rows, time_s)
    origin = {
        axis: round(qnested(triplet, time_s, "origin", axis), 3)
        for axis in ("x", "y", "z")
    }
    velocity = {
        axis: round(qnested(triplet, time_s, "velocity", axis), 3)
        for axis in ("x", "y", "z")
    }
    velocity_yaw = qfield(triplet, time_s, "velocity_yaw_unwrapped_deg")
    view_yaw = qfield(triplet, time_s, "view_yaw_unwrapped_deg")
    target_yaw = qfield(triplet, time_s, "target_yaw_unwrapped_deg")
    target_error = qfield(triplet, time_s, "target_error_unwrapped_deg")
    yaw_lead = qfield(triplet, time_s, "yaw_lead_unwrapped_deg")
    return {
        "time_s": round(time_s, 6),
        "origin": origin,
        "velocity": velocity,
        "horizontal_speed": round(qfield(triplet, time_s, "horizontal_speed"), 3),
        "velocity_yaw_deg": round(wrap_angle_deg(velocity_yaw), 3),
        "view_yaw_deg": round(wrap_angle_deg(view_yaw), 3),
        "target_yaw_deg": round(wrap_angle_deg(target_yaw), 3),
        "target_error_deg": round(wrap_angle_deg(target_error), 3),
        "yaw_lead_deg": round(wrap_angle_deg(yaw_lead), 3),
        "d_lip_qu": round(qfield(triplet, time_s, "d_lip_qu"), 3),
        "move": nearest["move"],
        "buttons": int(nearest["buttons"]),
        "jump_button": bool(int(nearest["buttons"]) & BUTTON_JUMP),
        "nearest_source_row": int(nearest["source_row"]),
        "support_rows": [int(row["source_row"]) for row in triplet],
    }


def build_controller_curve(rows: list[dict[str, object]], events: dict[str, object]) -> dict[str, object]:
    start = float(events["terminal_sweep_start"]["time_s"])
    end = float(events["physical_lip_x_crossing"]["time_s"])
    samples: list[dict[str, object]] = []
    t = start
    while t <= end + 1e-9:
        samples.append(quadratic_sample(rows, t))
        t += CONTROLLER_SAMPLE_STEP_S
    if samples[-1]["time_s"] < end:
        samples.append(quadratic_sample(rows, end))
    return {
        "method": "local_quadratic_lagrange_by_time",
        "sample_step_s": CONTROLLER_SAMPLE_STEP_S,
        "window": {
            "start_event": "terminal_sweep_start",
            "end_event": "physical_lip_x_crossing",
            "start_time_s": round(start, 6),
            "end_time_s": round(end, 6),
        },
        "samples": samples,
    }


def render_markdown(report: dict[str, object]) -> str:
    source = report["source"]
    events = report["events"]
    lines = [
        "# ztricks Distance Reference Trace",
        "",
        f"- Schema: `{report['schema']}`",
        f"- Demo: `{source.get('demo')}`",
        f"- SHA-256: `{source.get('sha256')}`",
        f"- Attempt: `{source.get('attempt')}`",
        f"- Rows: `{source.get('attempt_start_row')}` to `{source.get('landing_row')}`",
        f"- Samples: `{len(report['rows'])}`",
        f"- Controller curve: `{report['controller_curve']['method']}` "
        f"step `{report['controller_curve']['sample_step_s']}`s",
        "",
        "| event | row | t | x | y | z | vh | vel yaw | view yaw | target err | yaw lead | d_lip | buttons |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name in (
        "attempt_start",
        "first_grounded",
        "terminal_sweep_start",
        "speed_floor_crossed",
        "aligned_near_target_line",
        "release_jump",
        "physical_lip_x_crossing",
        "landing",
    ):
        row = events[name]
        origin = row["origin"]
        lines.append(
            f"| `{name}` | `{row['source_row']}` | {float(row['time_s']):.3f} | "
            f"{float(origin['x']):.1f} | {float(origin['y']):.1f} | {float(origin['z']):.1f} | "
            f"{float(row['horizontal_speed']):.1f} | {float(row['velocity_yaw_deg']):.1f} | "
            f"{float(row['view_yaw_deg']):.1f} | {float(row['target_error_deg']):.1f} | "
            f"{float(row['yaw_lead_deg']):.1f} | {float(row['d_lip_qu']):.1f} | "
            f"{int(row['buttons'])} |"
        )
    lines.extend(
        [
            "",
            "Interpolation notes:",
            "",
            "- View yaw, velocity yaw, target yaw, yaw lead, and target error are unwrapped before interpolation.",
            "- `physical_lip_x_crossing` is estimated between adjacent rows at `x=-3348.0`.",
            "- Controller guidance samples use local quadratic interpolation over the successful attempt only.",
            "- Event proof stays piecewise-linear/projection based to avoid spline overshoot in evidence.",
            "- Rows flagged as A5 dropped-state interpolations remain marked in JSON as `reference_state_interpolated`.",
        ]
    )
    return "\n".join(lines) + "\n"
