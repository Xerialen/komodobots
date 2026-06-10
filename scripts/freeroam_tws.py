#!/usr/bin/env python3
"""FREE-ROAM time-weighted speed: the one scoring convention for un-pinned runs.

The metric itself is route_metrics.time_weighted_speed (imported, never
reimplemented). What this module adds is the free-roam PARAMETERIZATION:

  In free-roam there is no route, so there is no such thing as a *stray*
  teleporter -- every dm3 teleporter is legitimate navigation. We therefore
  sanction every teleport the run actually took: tele_entrances = the (x, y)
  source point of each teleport-sized step in the trace, listed once per use.
  legit_segment() then keeps the whole run, and time_weighted_speed()'s own
  convention excludes each teleport throw's instantaneous displacement from
  the distance sum (the throw is not player movement).

  Equivalently: whole-trace xy distance (teleport steps excluded) / duration.

  NOTE this derivation is free-roam ONLY. For route gates the sanctioned
  entrance list MUST stay the route census's fixed list -- deriving it from
  the trace would neutralize the stray-teleport guard (see MEMORY: "Preserve
  validator guards on rewrite").

Convention provenance (C1, issue #65): validated by exactly reproducing both
pre-existing ledger blocks from their stored traces before the C1 block ran:
  v4 n=6  -> mean 209.3 sd 33.5 range 172.8-254.7  (ledger: "209+-34, 173-255")
  v8 n=5  -> mean 194.2 sd 34.9                    (ledger: "194+-35")

Usage:
  python scripts/freeroam_tws.py <run_id> [<run_id> ...]

prints one JSON line per run (tws, teleports, records, duration_s, max_vh,
pct_onground) from artifacts/lab-runs/<run_id>/{trace.csv,trace_summary.json}.
"""

from __future__ import annotations

import csv
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from route_metrics import TELEPORT_JUMP, time_weighted_speed  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
RUNS = REPO / "artifacts" / "lab-runs"


def observed_teleport_entrances(rows, teleport_jump=TELEPORT_JUMP):
    """The (x, y) source of every teleport-sized step, once per use.

    Free-roam sanctioning: every teleporter the run took is legitimate (there
    is no route to stray from). Do NOT use this for route gates -- routes
    sanction a fixed census list, and deriving entrances from the trace there
    would disable the stray-teleport truncation guard.
    """
    ents = []
    for a, b in zip(rows, rows[1:]):
        jump = math.hypot(b["x"] - a["x"], b["y"] - a["y"]) + abs(b["z"] - a["z"])
        if jump > teleport_jump:
            ents.append((a["x"], a["y"]))
    return tuple(ents)


def freeroam_tws(rows, teleport_jump=TELEPORT_JUMP):
    """time_weighted_speed under the free-roam sanctioning convention."""
    return time_weighted_speed(
        rows, observed_teleport_entrances(rows, teleport_jump),
        teleport_jump=teleport_jump)


def load_trace(run_id):
    rows = []
    with open(RUNS / run_id / "trace.csv") as f:
        for r in csv.DictReader(f):
            rows.append({"t": float(r["t"]), "x": float(r["x"]), "y": float(r["y"]),
                         "z": float(r["z"]), "vh": float(r["vh"])})
    return rows


def main(argv):
    if not argv:
        print(__doc__)
        return 1
    for rid in argv:
        rows = load_trace(rid)
        ents = observed_teleport_entrances(rows)
        out = {"run_id": rid, "tws": round(freeroam_tws(rows), 1),
               "teleports": len(ents)}
        summary = RUNS / rid / "trace_summary.json"
        if summary.exists():
            s = json.loads(summary.read_text())
            out.update(records=s["records"], duration_s=s["duration_s"],
                       max_vh=s["max_vh"], pct_onground=s["pct_onground"])
        print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
