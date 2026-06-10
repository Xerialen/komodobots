#!/usr/bin/env python3
"""A4 #116 work item 2 — lip speed TODAY from every directed rung-A run on disk.

Inventory: every artifacts/lab-runs/<id>/lab.cfg with the rung-A cvar triple
  k_fb_moveprobe_mode 23 + k_fb_moveprobe_fixed_goal 191 +
  k_fb_moveprobe_spawn_origin "385.5 614.25 56"
is a directed rung-1 run and is INCLUDED (no selection; runs whose trace.csv
is missing are built offline with build_trace.py first). Blocks are labeled
by run-id timestamp against the ledger timeline (P2 baseline / P3 c1..c5
deploys); the lip measurement itself is config-agnostic.

Per attempt (rung1_lib conventions; conditioning of record):
  * edge          — route_metrics.edge_speed at the RUNG-1 census gap (A0
                    constants unchanged) + audit crossing details
  * lip_approach  — closest upper-level (z > 96) approach to the census edge
                    point: distance, vh, grounded flag, heading
  * reached_lip   — approach < 80 qu (share reported; cf. P2's Gate-1 stat:
                    66 lip-marker entries across the baseline 10, 41 fell
                    back = 25 conversions)
  * grounded_near_vh_max — best grounded vh within 150 qu of the edge on the
                    upper level (the classify() near-edge convention)

Usage:  python rung1_lip_live.py [--out live-lip.json]
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from statistics import median

EXP = Path(__file__).resolve().parent
sys.path.insert(0, str(EXP))

from rung1_lib import (  # noqa: E402
    REPO, REQUIRED, RUNS, SCRIPTS, attempt_segments, lip_attempt_metrics,
    load_live_rows, load_route, rung1_gap, verify_route_mod, write_json,
)

CVARS = {
    "k_fb_moveprobe_mode": "23",
    "k_fb_moveprobe_fixed_goal": "191",
    "k_fb_moveprobe_spawn_origin": "385.5 614.25 56",
}

# Block labels from the ACTUAL run-id clusters on disk (10-run blocks, ~1 min
# spacing) cross-referenced with the ledger timeline. The P3 c1/c2/c3 gate
# runs are NOT on disk (run dirs since cleaned; cf. B5 backfill "ssd-only
# 41"). The four 00:48-01:36 blocks fall between the ledger's "c5 adopted"
# row and the A1 c5 comparator block; the ledger does not pin their exact
# sub-config (c4/c5 guard A/B + confirm era), so they are labeled
# carrot-family. Labels are interpretive only — every matching run is
# measured identically.
BLOCKS = [
    ("pre-baseline-18s", "00000000T000000Z", "20260609T225416Z"),  # invalidated 18 s block (duration truncation)
    ("p2-baseline-v8",   "20260609T225417Z", "20260609T230323Z"),  # v8, no carrot (the P2 decomposition 10)
    ("carrot-family-1",  "20260610T004839Z", "20260610T005744Z"),
    ("carrot-family-2",  "20260610T010219Z", "20260610T011123Z"),
    ("carrot-family-3",  "20260610T011345Z", "20260610T012249Z"),
    ("carrot-family-4",  "20260610T012657Z", "20260610T013602Z"),
    ("p3-c5-comparator", "20260610T013959Z", "20260610T014904Z"),  # the A1 comparator block (deployed config)
]


def block_of(run_id):
    for name, lo, hi in BLOCKS:
        if lo <= run_id <= hi:
            return name
    return "unknown"


def cfg_matches(cfg_path):
    try:
        text = cfg_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    for k, v in CVARS.items():
        m = re.search(rf'^set {re.escape(k)} "?([^"\r\n]*)"?\s*$', text, re.M)
        if not m or m.group(1).strip() != v:
            return False
    return True


def inventory():
    out = []
    for d in sorted(RUNS.iterdir()):
        if d.is_dir() and cfg_matches(d / "lab.cfg"):
            out.append(d.name)
    return out


def ensure_trace(run_id):
    if (RUNS / run_id / "trace.csv").exists():
        return True
    if not (RUNS / run_id / "moveprobe-commands.json").exists():
        return False
    print(f"  building trace for {run_id} ...")
    subprocess.run([sys.executable, str(SCRIPTS / "build_trace.py"), run_id],
                   check=True, cwd=REPO)
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(EXP / "live-lip.json"))
    args = ap.parse_args()

    route = load_route()
    gap = rung1_gap(route)
    vr = verify_route_mod()
    run_ids = inventory()
    print(f"{len(run_ids)} directed rung-A runs match the cvar triple")

    runs, skipped = [], []
    for rid in run_ids:
        if not ensure_trace(rid):
            skipped.append(rid)
            continue
        rows = load_live_rows(rid, route)
        rec = {"run_id": rid, "block": block_of(rid),
               "duration_s": round(rows[-1]["t"] - rows[0]["t"], 1) if rows else 0.0,
               "attempts": []}
        for seg in attempt_segments(rows, route):
            cls, closest, _, _ = vr.classify(seg, route["geom"])
            m = lip_attempt_metrics(seg, gap)
            m.update(cls=cls, closest_goal=round(closest, 1),
                     t0=seg[0]["t"], dur=round(seg[-1]["t"] - seg[0]["t"], 1))
            rec["attempts"].append(m)
        runs.append(rec)

    atts = [a for r in runs for a in r["attempts"]]
    lip = [a for a in atts if a["reached_lip"]]
    edges = [a["edge"] for a in atts if a["edge"] is not None]
    lip_vh = [a["lip_approach"]["vh"] for a in lip]
    near = [a["grounded_near_vh_max"] for a in atts
            if a["grounded_near_vh_max"] is not None]
    summary = {
        "runs": len(runs), "skipped_no_cmdlog": skipped,
        "attempts": len(atts),
        "reached_lip_attempts": len(lip),
        "reached_lip_share": round(len(lip) / len(atts), 3) if atts else None,
        "edge_crossings": len(edges),
        "edge_values_sorted": sorted(edges),
        "edge_median": round(median(edges), 1) if edges else None,
        "edge_max": max(edges) if edges else None,
        "edge_ge_437": sum(1 for v in edges if v >= REQUIRED),
        "lip_approach_vh_sorted": sorted(lip_vh),
        "lip_approach_vh_median": round(median(lip_vh), 1) if lip_vh else None,
        "lip_vh_ge_437": sum(1 for v in lip_vh if v >= REQUIRED),
        "grounded_near_vh_max_median": round(median(near), 1) if near else None,
        "grounded_near_vh_max_max": max(near) if near else None,
        "grounded_near_ge_437": sum(1 for v in near if v >= REQUIRED),
    }
    by_block = {}
    for r in runs:
        b = by_block.setdefault(r["block"], {"runs": 0, "attempts": 0,
                                             "reached_lip": 0, "edges": []})
        b["runs"] += 1
        for a in r["attempts"]:
            b["attempts"] += 1
            b["reached_lip"] += int(a["reached_lip"])
            if a["edge"] is not None:
                b["edges"].append(a["edge"])
    for b in by_block.values():
        b["edge_median"] = round(median(b["edges"]), 1) if b["edges"] else None
        b["edge_ge_437"] = sum(1 for v in b["edges"] if v >= REQUIRED)
        b["edges"] = sorted(b["edges"])

    write_json(args.out, {"summary": summary, "by_block": by_block, "runs": runs})
    print(f"\nattempts {summary['attempts']}, reached lip {summary['reached_lip_attempts']} "
          f"({summary['reached_lip_share']}), edge crossings {summary['edge_crossings']} "
          f"(median {summary['edge_median']}, max {summary['edge_max']}, "
          f">=437: {summary['edge_ge_437']})")
    for name, b in by_block.items():
        print(f"  {name:12s} runs={b['runs']:2d} attempts={b['attempts']:3d} "
              f"lip={b['reached_lip']:3d} edge_n={len(b['edges'])} "
              f"edge_med={b['edge_median']} ge437={b['edge_ge_437']}")


if __name__ == "__main__":
    main()
