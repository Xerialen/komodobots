#!/usr/bin/env python3
"""Score an open-loop replay run on path fidelity to the human trick trajectory.

Success for a replay run is NOT reaching an item or a wall-clock time -- both are
confounded (a safe walk reaches RL; a spawn can sit on RL; spawn location makes
time meaningless). The confound-proof signal is divergence from the exact human
trick path, which the bot was snapped onto at frame 0 and which is logged every
frame as |bot origin - human origin at the same time index|.

We split it:
- horizontal (XY) divergence -> did it follow the ground path,
- vertical (Z) divergence    -> did it reproduce the jumps/heights (a floor walk
  matches XY on flat stretches but fails Z wherever the human was airborne).

PASS = across the whole active window: max horizontal <= --max-h, max vertical
<= --max-v, max 3D <= --max-3d, AND the full stream was replayed (max cursor
reaches frame_count - 1) with a `complete` event present.

Reads a lab run's `moveprobe-commands.json` (sampled per-frame replay_state) and
`moveprobe-replay-events.json` (exact activate/complete edges).
"""

from __future__ import annotations

import logging
import argparse
import json
import sys
from pathlib import Path
from typing import Iterable



LOGGER = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARTIFACTS_ROOT = REPO_ROOT / "artifacts" / "lab-runs"

# Committed thresholds (qu). 32 ~= a player bounding box width (lockstep).
DEFAULT_MAX_H = 32.0
DEFAULT_MAX_V = 24.0
DEFAULT_MAX_3D = 32.0


def load_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def score_player(replay_state: dict, event_player: dict | None,
                 max_h: float, max_v: float, max_3d: float) -> dict:
    frame_count = int(replay_state.get("frame_count") or 0)
    max_cursor = int(replay_state.get("max_cursor") or 0)
    # Prefer the exact event-edge values where present; fall back to sampled.
    final_cursor = None
    complete_event = False
    if event_player:
        final_cursor = event_player.get("final_cursor")
        complete_event = "complete" in (event_player.get("event_counts") or [])

    # The sampled max_cursor (from throttled command logging) can lag
    # frame_count - 1 even on a true full replay when the final command sample is
    # skipped. The completion event carries the exact final_cursor, so prefer it
    # when present and fall back to the sampled cursor only when no event exists.
    coverage_cursor = max_cursor
    if complete_event and final_cursor is not None:
        coverage_cursor = max(max_cursor, int(final_cursor))
    reached_last = (frame_count > 0) and (coverage_cursor >= frame_count - 1)
    replayed_full = reached_last and complete_event

    max_h_val = replay_state.get("max_divergence_h_qu")
    max_v_val = replay_state.get("max_divergence_v_qu")
    max_3d_val = replay_state.get("max_divergence_qu")

    checks = {
        "horizontal_within": (max_h_val is not None) and (max_h_val <= max_h),
        "vertical_within": (max_v_val is not None) and (max_v_val <= max_v),
        "full_3d_within": (max_3d_val is not None) and (max_3d_val <= max_3d),
        "replayed_full_stream": replayed_full,
    }
    verdict = "PASS" if all(checks.values()) else "FAIL"
    lockstep = (
        verdict == "PASS"
        and max_3d_val is not None
        and max_3d_val <= 32.0
    )
    return {
        "frame_count": frame_count,
        "max_cursor": max_cursor,
        "final_cursor": final_cursor,
        "complete_event": complete_event,
        "max_divergence_h_qu": max_h_val,
        "max_divergence_v_qu": max_v_val,
        "max_divergence_3d_qu": max_3d_val,
        "final_divergence_3d_qu": replay_state.get("final_divergence_qu"),
        "checks": checks,
        "verdict": verdict,
        "lockstep": lockstep,
    }


def score_run(run_dir: Path, max_h: float, max_v: float, max_3d: float) -> dict:
    commands = load_json(run_dir / "moveprobe-commands.json")
    events = load_json(run_dir / "moveprobe-replay-events.json")
    event_by_key = {
        (int(p["ed"]), str(p["name"])): p for p in events.get("players", [])
    }

    players = []
    for player in commands.get("players", []):
        replay_state = player.get("replay_state") or {}
        if not replay_state or int(replay_state.get("sample_count") or 0) == 0:
            continue
        key = (int(player["ed"]), str(player["name"]))
        result = score_player(replay_state, event_by_key.get(key), max_h, max_v, max_3d)
        result["ed"] = key[0]
        result["name"] = key[1]
        players.append(result)

    overall = "PASS" if players and all(p["verdict"] == "PASS" for p in players) else "FAIL"
    return {
        "schema": "komodobots.replay_score.v1",
        "run_dir": run_dir.name,
        "thresholds_qu": {"max_h": max_h, "max_v": max_v, "max_3d": max_3d},
        "overall": overall,
        "players": players,
    }


def render(report: dict) -> str:
    lines = [
        f"# Replay score: {report['run_dir']}  ->  {report['overall']}",
        f"thresholds (qu): H<={report['thresholds_qu']['max_h']} "
        f"V<={report['thresholds_qu']['max_v']} 3D<={report['thresholds_qu']['max_3d']}",
        "",
    ]
    if not report["players"]:
        lines.append("No replay (mode 10) data found in this run.")
        return "\n".join(lines)
    for p in report["players"]:
        lines.append(
            f"{p['verdict']}{'  (lockstep)' if p['lockstep'] else ''}  {p['name']} (ed {p['ed']})"
        )
        lines.append(
            f"  maxH={p['max_divergence_h_qu']} maxV={p['max_divergence_v_qu']} "
            f"max3D={p['max_divergence_3d_qu']} finalDiv={p['final_divergence_3d_qu']} qu"
        )
        lines.append(
            f"  replayed {p['max_cursor']}/{p['frame_count'] - 1 if p['frame_count'] else 0} frames, "
            f"complete_event={p['complete_event']}"
        )
        failed = [k for k, v in p["checks"].items() if not v]
        if failed:
            lines.append(f"  failed checks: {', '.join(failed)}")
    return "\n".join(lines)


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score an open-loop replay run on path fidelity.")
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--run-id", help="Lab run id under artifacts/lab-runs/.")
    g.add_argument("--run-dir", type=Path, help="Explicit run directory.")
    parser.add_argument("--max-h", type=float, default=DEFAULT_MAX_H, help="Max horizontal divergence (qu).")
    parser.add_argument("--max-v", type=float, default=DEFAULT_MAX_V, help="Max vertical divergence (qu).")
    parser.add_argument("--max-3d", type=float, default=DEFAULT_MAX_3D, help="Max 3D divergence (qu).")
    parser.add_argument("--output-json", type=Path, default=None, help="Also write the report JSON here.")
    return parser.parse_args(list(argv))


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    run_dir = args.run_dir or (DEFAULT_ARTIFACTS_ROOT / args.run_id)
    if not run_dir.is_dir():
        print(f"Run directory not found: {run_dir}", file=sys.stderr)
        return 2
    report = score_run(run_dir, args.max_h, args.max_v, args.max_3d)
    out_json = args.output_json or (run_dir / "replay-score.json")
    out_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(render(report))
    return 0 if report["overall"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
