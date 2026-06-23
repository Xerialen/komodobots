#!/usr/bin/env python3
"""Audit: onground flag vs height_above_floor (haf < 4, the locked
climb_detector grounded convention) on live rows near the rung-1 lip.

NOTE (Codex PR #119 P2): this scans the WHOLE raw trace (no attempt
conditioning) — an upper-bound cross-check. The PRIMARY headline stat
lives in live-lip.json (takeoff_near_*, conditioned attempt segments via
rung1_lib.lip_attempt_metrics); it reads slightly lower (median 439.0,
>=437 in 44/70 vs 440.1 / 50/70 here) because conditioning drops rows
after stray teleports / segment boundaries."""
import logging
import csv
import json
import math
import sys
from pathlib import Path
from statistics import median


LOGGER = logging.getLogger(__name__)
EXP = Path(__file__).resolve().parent
sys.path.insert(0, str(EXP))
from rung1_lib import LIP_Z_MIN, NEAR_R, RUNS, edge_point, load_route, rung1_gap  # noqa: E402

route = load_route()
ex, ey, _ = edge_point(rung1_gap(route))
d = json.loads((EXP / "live-lip.json").read_text())

per_attempt_haf = []
agree = disagree_og = disagree_haf = 0
for r in d["runs"]:
    rows = list(csv.DictReader(open(RUNS / r["run_id"] / "trace.csv")))
    best = None
    for row in rows:
        x, y, z = float(row["x"]), float(row["y"]), float(row["z"])
        if z <= LIP_Z_MIN or math.hypot(x - ex, y - ey) >= NEAR_R:
            continue
        og = int(row["onground"])
        haf = float(row["height_above_floor"]) if row["height_above_floor"] != "" else None
        g_haf = haf is not None and haf < 4.0
        if og == g_haf:
            agree += 1
        elif og:
            disagree_og += 1
        else:
            disagree_haf += 1
        if g_haf:
            vh = float(row["vh"])
            best = vh if best is None else max(best, vh)
    if best is not None:
        per_attempt_haf.append(best)

print(f"near-lip rows: onground==haf<4 agree {agree}, onground-only {disagree_og}, "
      f"haf<4-only {disagree_haf}")
print(f"runs with haf<4 takeoff-capable rows near lip: {len(per_attempt_haf)}/{len(d['runs'])}")
print(f"haf<4 best-vh per run: median {median(per_attempt_haf):.1f}, "
      f"max {max(per_attempt_haf):.1f}, ge437 {sum(1 for v in per_attempt_haf if v >= 437)}")
print("sorted:", sorted(round(v) for v in per_attempt_haf))
