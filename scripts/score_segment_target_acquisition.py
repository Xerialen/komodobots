#!/usr/bin/env python3
"""Score live acquisition of QWD segment targets.

This is for route-controller probes, not open-loop replay scoring.  Given a
target manifest from build_replay_segment_targets.py and a lab run with
moveprobe-commands.json, it reports whether the bot physically entered each
target's horizontal/vertical gate.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARTIFACTS_ROOT = REPO_ROOT / "artifacts" / "lab-runs"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def point_from_origin(origin: dict) -> tuple[float, float, float]:
    return (float(origin["x"]), float(origin["y"]), float(origin["z"]))


def distance_parts(origin: dict, target: tuple[float, float, float]) -> tuple[float, float, float]:
    dx = float(origin["x"]) - target[0]
    dy = float(origin["y"]) - target[1]
    dz = float(origin["z"]) - target[2]
    h = math.hypot(dx, dy)
    v = abs(dz)
    return h, v, math.hypot(h, v)


def best_sample(commands: list[dict], target: tuple[float, float, float], active_only: bool) -> dict | None:
    best: dict | None = None
    for row in commands:
        if active_only and not (row.get("qwd_state") or {}).get("active"):
            continue
        origin = row.get("origin")
        if not isinstance(origin, dict):
            continue
        h, v, d3 = distance_parts(origin, target)
        if best is None or d3 < best["distance_3d_qu"]:
            best = {
                "time_s": row.get("time_s"),
                "origin": origin,
                "distance_h_qu": round(h, 3),
                "distance_v_qu": round(v, 3),
                "distance_3d_qu": round(d3, 3),
                "qwd_active": bool((row.get("qwd_state") or {}).get("active")),
                "qwd_index": (row.get("qwd_state") or {}).get("control_point_index"),
                "speed_qu_s": horizontal_speed(row),
            }
    return best


def horizontal_speed(row: dict) -> float | None:
    water = row.get("water_state") or {}
    vx = water.get("velocity_x")
    vy = water.get("velocity_y")
    if vx is None or vy is None:
        return None
    return round(math.hypot(float(vx), float(vy)), 3)


def event_summary(run_dir: Path) -> dict:
    path = run_dir / "moveprobe-qwd-events.json"
    if not path.is_file():
        return {"events": 0, "complete": False, "max_advanced": 0}
    data = load_json(path)
    events = data.get("events") or []
    complete = any(e.get("event") == "complete" for e in events)
    max_advanced = max(
        (int(e.get("advanced_control_points") or e.get("advanced") or 0) for e in events),
        default=0,
    )
    return {
        "events": len(events),
        "complete": complete,
        "max_advanced": max_advanced,
        "raw": events,
    }


def score_run(targets_path: Path, run_dir: Path) -> dict:
    targets_doc = load_json(targets_path)
    commands_doc = load_json(run_dir / "moveprobe-commands.json")
    commands = commands_doc.get("commands") or []
    events = event_summary(run_dir)

    rows = []
    for target_row in targets_doc.get("targets", []):
        target = point_from_origin(target_row["target"]["origin"])
        gate = target_row.get("acquisition_gate") or target_row.get("gate") or {}
        gate_h = float(gate.get("horizontal_radius_qu", gate.get("horizontal_qu", 64.0)))
        gate_v = float(gate.get("vertical_radius_qu", gate.get("vertical_qu", 64.0)))
        closest = best_sample(commands, target, active_only=False)
        active_closest = best_sample(commands, target, active_only=True)
        acquired = bool(
            active_closest
            and active_closest["distance_h_qu"] <= gate_h
            and active_closest["distance_v_qu"] <= gate_v
        )
        inactive_gate_hit = bool(
            closest
            and closest["distance_h_qu"] <= gate_h
            and closest["distance_v_qu"] <= gate_v
            and not closest["qwd_active"]
        )
        rows.append({
            "order": target_row.get("order"),
            "cursor": target_row.get("cursor"),
            "target_origin": {
                "x": target[0],
                "y": target[1],
                "z": target[2],
            },
            "gate": {"horizontal_qu": gate_h, "vertical_qu": gate_v},
            "closest": closest,
            "active_closest": active_closest,
            "acquired": acquired,
            "inactive_gate_hit": inactive_gate_hit,
        })

    overall = "PASS" if rows and all(row["acquired"] for row in rows) and events["complete"] else "FAIL"
    return {
        "schema": "komodobots.segment_target_acquisition_score.v1",
        "targets": str(targets_path),
        "run_dir": run_dir.name,
        "command_count": len(commands),
        "qwd_events": events,
        "overall": overall,
        "target_results": rows,
    }


def render(report: dict) -> str:
    lines = [
        f"# Segment target acquisition: {report['run_dir']} -> {report['overall']}",
        "",
        f"- Commands: `{report['command_count']}`",
        f"- QWD events: `{report['qwd_events']['events']}`",
        f"- Max advanced: `{report['qwd_events']['max_advanced']}`",
        f"- Complete event: `{report['qwd_events']['complete']}`",
        "",
        "| target | cursor | acquired active | closest H/V/3D | active closest H/V/3D | closest time |",
        "| ---: | ---: | --- | --- | --- | ---: |",
    ]
    for row in report["target_results"]:
        closest = row["closest"] or {}
        active = row["active_closest"] or {}
        closest_cell = dist_cell(closest)
        active_cell = dist_cell(active)
        time_s = closest.get("time_s")
        time_cell = "" if time_s is None else f"{float(time_s):.3f}"
        lines.append(
            f"| {row['order']} | {row['cursor']} | {'yes' if row['acquired'] else 'no'} | "
            f"{closest_cell} | {active_cell} | {time_cell} |"
        )
    return "\n".join(lines) + "\n"


def dist_cell(row: dict) -> str:
    if not row:
        return "-"
    return (
        f"{row['distance_h_qu']:.3f}/"
        f"{row['distance_v_qu']:.3f}/"
        f"{row['distance_3d_qu']:.3f}"
    )


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score live QWD segment target acquisition.")
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--run-id", help="Lab run id under artifacts/lab-runs/.")
    g.add_argument("--run-dir", type=Path, help="Explicit run directory.")
    parser.add_argument("--targets", type=Path, required=True, help="Segment target JSON manifest.")
    parser.add_argument("--output-json", type=Path, default=None)
    parser.add_argument("--output-md", type=Path, default=None)
    return parser.parse_args(list(argv))


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    run_dir = args.run_dir or (DEFAULT_ARTIFACTS_ROOT / args.run_id)
    if not run_dir.is_dir():
        print(f"Run directory not found: {run_dir}", file=sys.stderr)
        return 2
    if not args.targets.is_file():
        print(f"Target manifest not found: {args.targets}", file=sys.stderr)
        return 2

    report = score_run(args.targets, run_dir)
    out_json = args.output_json or (run_dir / "segment-target-score.json")
    out_md = args.output_md or (run_dir / "segment-target-score.md")
    out_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    out_md.write_text(render(report), encoding="utf-8")
    print(render(report), end="")
    return 0 if report["overall"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
