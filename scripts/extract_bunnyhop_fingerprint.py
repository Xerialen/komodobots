#!/usr/bin/env python3
"""Extract a human (or bot) bunnyhop fingerprint from a replay .cmds file.

A `.cmds` file (schema komodobots.replay.v1) has one whitespace-delimited row
per command frame:

    msec ox oy oz vx vy vz pitch yaw roll fwd side up buttons

This script turns that per-frame trace into the *bunnyhop fingerprint* the
mastery panel needs to compare bot vs human:

  - speed-vs-distance curve (the decisive H1/H2 artifact): horizontal speed as a
    function of cumulative horizontal distance travelled, binned so it is compact;
  - peak / sustained horizontal speed (qu/s);
  - airborne acceleration rate dv/dt (qu/s per second) while gaining speed;
  - turn events: heading reversals and the speed lost through each turn
    (the "turn technique" — how the human preserves speed when changing direction);
  - jump cadence (jumps/min) detected from upmove rising edges;
  - view-yaw-vs-velocity offset distribution (the strafe signature).

It is map- and engine-agnostic: it only reads the recorded kinematics, so the
same script fingerprints a human POV demo's `.cmds` and a bot run's `.cmds`.

Usage:
    python3 scripts/extract_bunnyhop_fingerprint.py \
        --cmds artifacts/replay/trick5.cmds \
        --label human_trick5 \
        --out-json experiments/bunnyhop_mastery/evidence/fingerprint-trick5.json \
        --out-md   experiments/bunnyhop_mastery/evidence/fingerprint-trick5.md
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path

SCHEMA = "komodobots.bunnyhop_fingerprint.v1"

# QW usercmd jump is button bit 1 (value 2); upmove is unused for +jump.
BUTTON_JUMP = 2

# A frame is "moving" (worth measuring strafe/turn behaviour) above this speed.
MOVING_SPEED_QU = 100.0


def _wrap180(deg: float) -> float:
    """Wrap an angle to (-180, 180]."""
    d = (deg + 180.0) % 360.0 - 180.0
    return d if d != -180.0 else 180.0


def parse_cmds(path: Path) -> list[dict]:
    frames: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            p = line.split()
            if len(p) < 14:
                continue
            frames.append(
                {
                    "msec": int(p[0]),
                    "origin": (float(p[1]), float(p[2]), float(p[3])),
                    "vel": (float(p[4]), float(p[5]), float(p[6])),
                    "yaw": float(p[8]),
                    "upmove": int(float(p[12])),
                    "buttons": int(float(p[13])),
                }
            )
    return frames


def compute(frames: list[dict]) -> dict:
    if len(frames) < 2:
        raise ValueError("need at least 2 frames")

    t = 0.0
    dist = 0.0
    samples = []  # per-frame derived series
    prev_origin = frames[0]["origin"]
    for i, f in enumerate(frames):
        vx, vy, _vz = f["vel"]
        hs = math.hypot(vx, vy)
        ox, oy, _oz = f["origin"]
        if i > 0:
            dist += math.hypot(ox - prev_origin[0], oy - prev_origin[1])
            t += frames[i]["msec"] / 1000.0
        prev_origin = f["origin"]
        heading = math.degrees(math.atan2(vy, vx)) if hs > 1e-3 else None
        yaw_off = _wrap180(f["yaw"] - heading) if heading is not None else None
        samples.append(
            {
                "i": i,
                "t": t,
                "dist": dist,
                "hspeed": hs,
                "heading": heading,
                "yaw_off": yaw_off,
                "upmove": f["upmove"],
                "jump_held": 1 if (f["buttons"] & BUTTON_JUMP) else 0,
            }
        )

    total_time = samples[-1]["t"]
    total_dist = samples[-1]["dist"]
    speeds = [s["hspeed"] for s in samples]

    # --- peak / sustained speed ---
    speeds_sorted = sorted(speeds)
    n = len(speeds_sorted)

    def pct(p: float) -> float:
        return speeds_sorted[min(n - 1, int(p * n))]

    peak = max(speeds)
    p50 = pct(0.50)
    p90 = pct(0.90)
    p95 = pct(0.95)

    # --- airborne accel rate dv/dt while gaining speed ---
    # Positive d(hspeed)/dt across consecutive frames, restricted to moving frames.
    accel_rates = []
    for a, b in zip(samples, samples[1:]):
        dt = b["t"] - a["t"]
        if dt <= 0 or b["hspeed"] < MOVING_SPEED_QU:
            continue
        dv = b["hspeed"] - a["hspeed"]
        if dv > 0:
            accel_rates.append(dv / dt)
    accel_p50 = statistics.median(accel_rates) if accel_rates else 0.0
    accel_p90 = (
        sorted(accel_rates)[int(0.90 * len(accel_rates))] if accel_rates else 0.0
    )
    accel_max = max(accel_rates) if accel_rates else 0.0

    # --- jump cadence from +jump button (bit 1) rising edges ---
    jumps = 0
    for a, b in zip(samples, samples[1:]):
        if a["jump_held"] == 0 and b["jump_held"] == 1:
            jumps += 1
    cadence_per_min = (jumps / total_time * 60.0) if total_time > 0 else 0.0

    # --- view-yaw-vs-velocity offset distribution (strafe signature) ---
    offs = [
        abs(s["yaw_off"])
        for s in samples
        if s["yaw_off"] is not None and s["hspeed"] >= MOVING_SPEED_QU
    ]
    yaw_off_p50 = statistics.median(offs) if offs else 0.0
    yaw_off_p90 = sorted(offs)[int(0.90 * len(offs))] if offs else 0.0

    # --- turn technique: speed as a function of instantaneous turn rate ---
    # The crux of bunnyhop mastery. A human carves a continuous bounded-radius
    # arc: high turn rate sustained WITHOUT losing speed. We bucket every moving
    # frame by |heading rate| (deg/s) and report the mean/max speed it holds.
    # The implied carve radius = v / omega tells us the radius the human's
    # technique settles at (which must fit the map's open area).
    turn_buckets: dict[int, list[float]] = {}
    turn_rates_moving: list[float] = []  # deg/s, for the dominant moving regime
    speeds_moving: list[float] = []
    for a, b in zip(samples, samples[1:]):
        if (
            a["heading"] is None
            or b["heading"] is None
            or b["hspeed"] < MOVING_SPEED_QU
        ):
            continue
        dt = b["t"] - a["t"]
        if dt <= 0:
            continue
        rate = abs(_wrap180(b["heading"] - a["heading"])) / dt  # deg/s
        bucket = min(6, int(rate / 60))  # 60-deg/s buckets, top bucket = 360+
        turn_buckets.setdefault(bucket, []).append(b["hspeed"])
        turn_rates_moving.append(rate)
        speeds_moving.append(b["hspeed"])

    speed_vs_turn_rate = [
        {
            "turn_rate_lo_deg_s": k * 60,
            "frames": len(v),
            "frame_frac": round(len(v) / len(turn_rates_moving), 3)
            if turn_rates_moving
            else 0.0,
            "mean_hspeed": round(statistics.mean(v), 1),
            "max_hspeed": round(max(v), 1),
        }
        for k, v in sorted(turn_buckets.items())
    ]
    median_turn_rate = statistics.median(turn_rates_moving) if turn_rates_moving else 0.0
    median_moving_speed = statistics.median(speeds_moving) if speeds_moving else 0.0
    # NOTE: this "radius" divides the MEDIAN INSTANTANEOUS turn rate (dominated by
    # high-frequency strafe OSCILLATION) into speed -- it is NOT the path's radius.
    # Use path_shape (net rotation, straightness, bbox) for the real trajectory shape.
    omega_rad = math.radians(median_turn_rate)
    oscillation_radius_qu = (median_moving_speed / omega_rad) if omega_rad > 1e-6 else None

    # --- path shape: the REAL trajectory geometry (net rotation, straightness, box) ---
    net_rotation_deg = 0.0
    for a, b in zip(samples, samples[1:]):
        if a["heading"] is None or b["heading"] is None or b["hspeed"] < MOVING_SPEED_QU:
            continue
        net_rotation_deg += _wrap180(b["heading"] - a["heading"])
    oxs = [f["origin"][0] for f in frames]
    oys = [f["origin"][1] for f in frames]
    net_disp = math.hypot(oxs[-1] - oxs[0], oys[-1] - oys[0])
    straightness = (net_disp / total_dist) if total_dist > 0 else 0.0
    bbox_x = max(oxs) - min(oxs)
    bbox_y = max(oys) - min(oys)

    # --- speed-vs-distance curve, binned (compact) ---
    n_bins = 40
    bin_w = total_dist / n_bins if total_dist > 0 else 1.0
    bins = [[] for _ in range(n_bins)]
    for s in samples:
        bi = min(n_bins - 1, int(s["dist"] / bin_w)) if bin_w > 0 else 0
        bins[bi].append(s["hspeed"])
    speed_vs_distance = [
        {
            "dist_qu": round(bi * bin_w, 1),
            "mean_hspeed": round(statistics.mean(b), 1) if b else None,
            "max_hspeed": round(max(b), 1) if b else None,
        }
        for bi, b in enumerate(bins)
    ]

    return {
        "schema": SCHEMA,
        "frames": len(frames),
        "total_time_s": round(total_time, 3),
        "total_distance_qu": round(total_dist, 1),
        "hspeed": {
            "peak": round(peak, 1),
            "p95": round(p95, 1),
            "p90": round(p90, 1),
            "p50": round(p50, 1),
        },
        "accel_rate_qu_per_s2": {
            "p50": round(accel_p50, 1),
            "p90": round(accel_p90, 1),
            "max": round(accel_max, 1),
        },
        "jump": {"count": jumps, "cadence_per_min": round(cadence_per_min, 1)},
        "view_yaw_offset_deg": {
            "p50": round(yaw_off_p50, 1),
            "p90": round(yaw_off_p90, 1),
        },
        "turn_technique": {
            "median_turn_rate_deg_s": round(median_turn_rate, 1),
            "median_moving_speed_qu_s": round(median_moving_speed, 1),
            "oscillation_radius_qu": round(oscillation_radius_qu, 1)
            if oscillation_radius_qu is not None
            else None,
            "oscillation_radius_caveat": "median-instantaneous turn rate is strafe "
            "OSCILLATION, not net path curvature; see path_shape for real geometry",
            "speed_vs_turn_rate": speed_vs_turn_rate,
        },
        "path_shape": {
            "net_rotation_deg": round(net_rotation_deg, 1),
            "net_rotations": round(abs(net_rotation_deg) / 360.0, 2),
            "net_displacement_qu": round(net_disp, 1),
            "path_length_qu": round(total_dist, 1),
            "straightness": round(straightness, 3),
            "bbox_qu": [round(bbox_x, 1), round(bbox_y, 1)],
        },
        "speed_vs_distance": speed_vs_distance,
    }


def render_md(fp: dict, label: str, src: str) -> str:
    h = fp["hspeed"]
    a = fp["accel_rate_qu_per_s2"]
    tt = fp["turn_technique"]
    ps = fp["path_shape"]
    lines = [
        f"# Bunnyhop fingerprint: `{label}`",
        "",
        f"- Source: `{src}`",
        f"- Frames: {fp['frames']}  ·  Duration: {fp['total_time_s']} s  ·  "
        f"Distance: {fp['total_distance_qu']} qu",
        "",
        "## Horizontal speed (qu/s)",
        "",
        "| peak | p95 | p90 | p50 |",
        "|---:|---:|---:|---:|",
        f"| {h['peak']} | {h['p95']} | {h['p90']} | {h['p50']} |",
        "",
        "## Airborne accel rate (qu/s²) — positive d(hspeed)/dt while moving",
        "",
        "| p50 | p90 | max |",
        "|---:|---:|---:|",
        f"| {a['p50']} | {a['p90']} | {a['max']} |",
        "",
        f"- Jump cadence: **{fp['jump']['cadence_per_min']}/min** "
        f"({fp['jump']['count']} jumps)",
        f"- View-yaw vs velocity offset: p50 **{fp['view_yaw_offset_deg']['p50']}°**, "
        f"p90 {fp['view_yaw_offset_deg']['p90']}° (strafe signature)",
        "",
        "## Path shape — the REAL trajectory geometry",
        "",
        f"- Net rotation over the run: **{ps['net_rotation_deg']}°** "
        f"({ps['net_rotations']} rotations)",
        f"- Net displacement **{ps['net_displacement_qu']} qu** over path length "
        f"**{ps['path_length_qu']} qu** → straightness **{ps['straightness']}**",
        f"- Bounding box: **{ps['bbox_qu'][0]} × {ps['bbox_qu'][1]} qu**",
        f"- (Strafe-oscillation 'radius' {tt['oscillation_radius_qu']} qu is an "
        f"artifact of instantaneous turn rate, NOT the path radius — see caveat.)",
        "",
        "## Turn technique — speed sustained vs (instantaneous) turn rate",
        "",
        f"- Median instantaneous turn rate while moving: **{tt['median_turn_rate_deg_s']}°/s** "
        f"(strafe oscillation)",
        f"- Median moving speed: **{tt['median_moving_speed_qu_s']} qu/s**",
        "",
        "| turn_rate≥(°/s) | frames | frac | mean_hspeed | max_hspeed |",
        "|---:|---:|---:|---:|---:|",
    ]
    for row in tt["speed_vs_turn_rate"]:
        lines.append(
            f"| {row['turn_rate_lo_deg_s']} | {row['frames']} | "
            f"{row['frame_frac']} | {row['mean_hspeed']} | {row['max_hspeed']} |"
        )
    lines += [
        "",
        "## Speed vs distance (binned)",
        "",
        "| dist_qu | mean_hspeed | max_hspeed |",
        "|---:|---:|---:|",
    ]
    for row in fp["speed_vs_distance"]:
        lines.append(
            f"| {row['dist_qu']} | {row['mean_hspeed']} | {row['max_hspeed']} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cmds", required=True, type=Path)
    ap.add_argument("--label", required=True)
    ap.add_argument("--out-json", type=Path)
    ap.add_argument("--out-md", type=Path)
    ap.add_argument(
        "--expect-peak",
        type=float,
        default=None,
        help="If set, exit non-zero unless peak hspeed is within --expect-tol of this "
        "(validation gate, e.g. the known 880/1088 benchmark).",
    )
    ap.add_argument("--expect-tol", type=float, default=0.10)
    args = ap.parse_args()

    frames = parse_cmds(args.cmds)
    fp = compute(frames)
    fp["label"] = args.label
    fp["source"] = str(args.cmds)

    out = json.dumps(fp, indent=2)
    if args.out_json:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(out, encoding="utf-8")
    if args.out_md:
        args.out_md.parent.mkdir(parents=True, exist_ok=True)
        args.out_md.write_text(render_md(fp, args.label, str(args.cmds)), encoding="utf-8")

    h = fp["hspeed"]
    ps = fp["path_shape"]
    print(
        f"[{args.label}] frames={fp['frames']} dur={fp['total_time_s']}s "
        f"path={fp['total_distance_qu']}qu  peak={h['peak']} p95={h['p95']} "
        f"p50={h['p50']}  cadence={fp['jump']['cadence_per_min']}/min  "
        f"net_rot={ps['net_rotation_deg']}deg ({ps['net_rotations']}turns) "
        f"straightness={ps['straightness']} bbox={ps['bbox_qu'][0]}x{ps['bbox_qu'][1]}"
    )

    if args.expect_peak is not None:
        lo = args.expect_peak * (1 - args.expect_tol)
        hi = args.expect_peak * (1 + args.expect_tol)
        if not (lo <= h["peak"] <= hi):
            print(
                f"VALIDATION FAIL: peak {h['peak']} outside "
                f"[{lo:.0f}, {hi:.0f}] (expected ~{args.expect_peak})"
            )
            return 1
        print(f"VALIDATION OK: peak {h['peak']} within ±{args.expect_tol*100:.0f}% of {args.expect_peak}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
