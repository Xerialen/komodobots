#!/usr/bin/env python3
"""A3 #75 divergence extraction over the 20 screen runs (read-only on traces).

Per run: edge value (a3_surrogate conditioning), crossing time, entry vh at
1000 xy-arc-qu before the crossing (the A2b lucky-condition home), and for
the launch config the circle telemetry: engage (grounded sub-3s spin-up),
peak vh in the first 3 s, time over 400, and the post-release fate (lowest z
in the 2 s after the first vh>=400 moment — the sim never leaves the
walkway: z stays >= -50; a pit dive shows z <= -150).
"""
import logging
import csv
import json
import math
import sys
from pathlib import Path


LOGGER = logging.getLogger(__name__)
SCRIPTS = Path(__file__).resolve().parents[4] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from a3_surrogate import load_rows, graph_nav          # noqa: E402
from mode23_sim import load_route_cfg                  # noqa: E402
from mode23_sweep import RUNG_B, edge_objective        # noqa: E402
from route_metrics import (EDGE_CROSS_EPS, EDGE_CORRIDOR, EDGE_Z_WINDOW,
                           TELEPORT_JUMP, _truncate_at_arrival,
                           legit_segment)              # noqa: E402

SCREENS = {
    "S1_launch": ["20260610T131930Z", "20260610T132007Z", "20260610T132044Z",
                  "20260610T132120Z", "20260610T132157Z"],
    "S2_deleg320": ["20260610T132412Z", "20260610T132449Z", "20260610T132525Z",
                    "20260610T132602Z", "20260610T132639Z"],
    "S3_C4": ["20260610T132742Z", "20260610T132819Z", "20260610T132856Z",
              "20260610T132932Z", "20260610T133009Z"],
    "S4_control": ["20260610T133119Z", "20260610T133156Z", "20260610T133233Z",
                   "20260610T133309Z", "20260610T133346Z"],
}


def crossing_index(rows, gap):
    """Index of the LAST qualifying crossing (route_metrics.edge_speed's own
    constants and rules, returning the row index instead of the speed)."""
    ex, ey, ez = (float(v) for v in gap["edge"][:3])
    ux, uy = float(gap["land"][0]) - ex, float(gap["land"][1]) - ey
    n = math.hypot(ux, uy)
    ux, uy = ux / n, uy / n

    def along(r):
        return (r["x"] - ex) * ux + (r["y"] - ey) * uy

    found = None
    for i in range(len(rows) - 1):
        a, b = rows[i], rows[i + 1]
        if along(a) >= -EDGE_CROSS_EPS or along(b) < -EDGE_CROSS_EPS:
            continue
        step = math.hypot(b["x"] - a["x"], b["y"] - a["y"]) + abs(b["z"] - a["z"])
        if step > TELEPORT_JUMP:
            continue
        cross = abs((b["y"] - ey) * ux - (b["x"] - ex) * uy)
        if cross > EDGE_CORRIDOR or abs(b["z"] - ez) > EDGE_Z_WINDOW:
            continue
        found = i + 1
    return found


def entry_vh(rows, ci, backdist=1000.0):
    """vh at the row `backdist` xy-arc-qu before the crossing row (A2b)."""
    d = 0.0
    for i in range(ci, 0, -1):
        d += math.hypot(rows[i]["x"] - rows[i - 1]["x"],
                        rows[i]["y"] - rows[i - 1]["y"])
        if d >= backdist:
            return rows[i - 1]["vh"]
    return None


def launch_telemetry(rows):
    t0 = rows[0]["t"]
    first3 = [r for r in rows if r["t"] - t0 <= 3.0]
    peak = max(r["vh"] for r in first3)
    t400 = next((r["t"] - t0 for r in first3 if r["vh"] >= 400.0), None)
    low_after = None
    if t400 is not None:
        win = [r for r in rows if t400 <= r["t"] - t0 <= t400 + 2.0]
        low_after = min(r["z"] for r in win)
    grounded_frac = (sum(1 for r in first3 if r["onground"]) / len(first3))
    return dict(peak_vh_3s=round(peak, 1),
                t_first_400=None if t400 is None else round(t400, 2),
                min_z_2s_after_400=low_after,
                grounded_frac_3s=round(grounded_frac, 2))


def main():
    gap = load_route_cfg("sng_to_rl")["gap"]
    goal = graph_nav(RUNG_B["goal_marker"])
    out = {}
    for screen, rids in SCREENS.items():
        out[screen] = []
        for rid in rids:
            rows = load_rows(rid, goal)
            t0 = rows[0]["t"]
            rows = [r for r in rows if r["t"] - t0 <= RUNG_B["budget_s"]]
            seg = _truncate_at_arrival(legit_segment(rows, ()), 60.0)
            ci = crossing_index(seg, gap)
            # the local index finder must agree with the IMPORTED metric
            # exactly (the tail_autopsy convention: index finders exist only
            # because edge_speed returns a speed, never a row)
            v = edge_objective(rows, gap)
            assert (v is None) == (ci is None) and (
                v is None or abs(seg[ci]["vh"] - v) < 0.05), \
                f"{rid}: finder {None if ci is None else seg[ci]['vh']} vs metric {v}"
            rec = {"run": rid}
            if ci is not None:
                rec["edge"] = round(seg[ci]["vh"], 1)
                rec["t_cross"] = round(seg[ci]["t"] - t0, 2)
                ev = entry_vh(seg, ci)
                rec["entry_vh_1000"] = None if ev is None else round(ev, 1)
            else:
                rec["edge"] = None
            if screen == "S1_launch":
                rec.update(launch_telemetry(rows))
            out[screen].append(rec)
            print(screen, json.dumps(rec))
    Path(__file__).with_suffix(".json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
