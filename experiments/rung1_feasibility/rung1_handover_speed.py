#!/usr/bin/env python3
"""A4 #116 — live speed at the would-be D1 gate evaluation point.

The D1-style gate evaluates in EvalPath at PNLM time. On the rung-1 route
the relevant PNLM is the carrot handover at m210: trigger = horizontal
distance to m210.nav < pass_r (130 deployed). This script measures, per
directed live run, vh at the FIRST trigger-radius entry (and at first
60-qu proximity, the touch-ish bound), plus the maximum vh over ALL rows
inside the trigger radius — bracketing what a live selection-time gate
would sample. Compare with the lip speeds (live-lip.json): the gap between
selection-time speed and lip speed is the gate-design correction the D1
threshold needs for rung 1.

Usage:  python rung1_handover_speed.py [--out handover-speed.json]
"""

from __future__ import annotations

import logging
import argparse
import json
import math
import sys
from pathlib import Path
from statistics import median


LOGGER = logging.getLogger(__name__)
EXP = Path(__file__).resolve().parent
sys.path.insert(0, str(EXP))

from rung1_lib import SCRIPTS, RUNS, load_live_rows, load_route, write_json  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
from mode23_sim import build_world_and_graph  # noqa: E402

PASS_R = 130.0          # deployed k_fb_moveprobe_s23_pass (c5)
TOUCH_R = 60.0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(EXP / "handover-speed.json"))
    args = ap.parse_args()

    _world, graph = build_world_and_graph()
    nav = graph.markers[210].nav
    route = load_route()
    live = json.loads((EXP / "live-lip.json").read_text())

    recs = []
    for r in live["runs"]:
        rows = load_live_rows(r["run_id"], route)
        first_pass = first_touch = None
        in_r = []
        for row in rows:
            hd = math.hypot(row["x"] - nav[0], row["y"] - nav[1])
            dz = abs(row["z"] - nav[2])
            if hd < PASS_R and dz < 100.0:
                in_r.append(row["vh"])
                if first_pass is None:
                    first_pass = row["vh"]
            if hd < TOUCH_R and dz < 100.0 and first_touch is None:
                first_touch = row["vh"]
        recs.append({"run_id": r["run_id"], "block": r["block"],
                     "vh_first_passr": (round(first_pass, 1)
                                        if first_pass is not None else None),
                     "vh_first_touchr": (round(first_touch, 1)
                                         if first_touch is not None else None),
                     "vh_max_in_passr": (round(max(in_r), 1) if in_r else None),
                     "rows_in_passr": len(in_r)})

    fp = sorted(x["vh_first_passr"] for x in recs if x["vh_first_passr"] is not None)
    mx = sorted(x["vh_max_in_passr"] for x in recs if x["vh_max_in_passr"] is not None)
    summary = {
        "runs": len(recs),
        "runs_entering_passr": len(fp),
        "vh_first_passr_sorted": fp,
        "vh_first_passr_median": round(median(fp), 1) if fp else None,
        "first_passr_ge437": sum(1 for v in fp if v >= 437.0),
        "first_passr_ge410": sum(1 for v in fp if v >= 410.0),
        "first_passr_ge350": sum(1 for v in fp if v >= 350.0),
        "vh_max_in_passr_median": round(median(mx), 1) if mx else None,
        "max_in_passr_ge437": sum(1 for v in mx if v >= 437.0),
    }
    write_json(args.out, {"summary": summary, "runs": recs})
    print(f"runs entering pass_r({PASS_R:g}) of m210: {summary['runs_entering_passr']}"
          f"/{summary['runs']}")
    print(f"vh at FIRST pass_r entry: median {summary['vh_first_passr_median']}, "
          f">=437: {summary['first_passr_ge437']}, >=410: {summary['first_passr_ge410']}, "
          f">=350: {summary['first_passr_ge350']}")
    print(f"max vh while inside pass_r: median {summary['vh_max_in_passr_median']}, "
          f">=437: {summary['max_in_passr_ge437']}")


if __name__ == "__main__":
    main()
