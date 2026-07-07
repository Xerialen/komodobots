#!/usr/bin/env python3
"""probe_qualifying_pool.py — measure the honest route-grade's QUALIFYING pool in a catalog.

The instrument-pool-growth round (plans/instrument-pool-growth.md §3.3): before a carved slice
ships anywhere, this probe answers — per split — how many episodes actually QUALIFY as grade/
reset segments at the given horizon, replicating `ml/eval_broad_closedloop.select_start_segments`
EXACTLY (episode >= horizon+1 ticks; stride-`horizon` scan; FIRST window with >=
`mv1_min_ticks` ticks that are airborne (onground falsey) AND moving (hspeed >=
`mv1_min_hspeed_qu_per_s`); ONE segment per episode). The eval module itself is torch-loaded and
cannot run on a bare box; the thresholds are imported from their single stdlib source
(`scripts/gmv_believability.DEFAULT_THRESHOLDS`) so the rule cannot silently fork, and a gating
test locks the window semantics against adversarial fixtures.

Pre-registered guards run HERE, by exit code (a guard that exists only as prose is not a guard):
`--require-val N` fails the probe when the val pool lands under target.

Stdlib only (sqlite3) — runs on servexeri's bare python3. Streams one ordered pass over
player_ticks (no duckdb, no full-split materialization).
"""

import argparse
import json
import logging
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gmv_believability import DEFAULT_THRESHOLDS  # noqa: E402  (stdlib; the rule's one source)

LOGGER = logging.getLogger(__name__)


def episode_qualifies(flags, horizon, min_airborne_moving):
    """flags = per-tick booleans (airborne AND moving), tick-ascending. Mirrors
    select_start_segments: len >= horizon+1; stride-`horizon` scan; first window
    [start, start+horizon+1) with enough qualifying ticks."""
    n = len(flags)
    if n < horizon + 1:
        return False
    start = 0
    while start + horizon + 1 <= n:
        if sum(flags[start:start + horizon + 1]) >= min_airborne_moving:
            return True
        start += horizon
    return False


def probe(db, horizon):
    thr_speed = DEFAULT_THRESHOLDS["mv1_min_hspeed_qu_per_s"]
    min_ticks = DEFAULT_THRESHOLDS["mv1_min_ticks"]
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        splits = {s: {"episodes": 0, "qualifying": 0}
                  for (s,) in con.execute("SELECT DISTINCT split FROM episodes")}
        cur = con.execute(
            """SELECT e.episode_id, e.split, p.onground, p.hspeed
                 FROM player_ticks p JOIN episodes e USING(episode_id)
                ORDER BY p.episode_id, p.tick""")
        cur_eid, cur_split, flags = None, None, []

        def close_episode():
            if cur_eid is None:
                return
            splits[cur_split]["episodes"] += 1
            if episode_qualifies(flags, horizon, min_ticks):
                splits[cur_split]["qualifying"] += 1

        for eid, split, onground, hspeed in cur:
            if eid != cur_eid:
                close_episode()
                cur_eid, cur_split, flags = eid, split, []
            flags.append((not onground) and (hspeed or 0.0) >= thr_speed)
        close_episode()
    finally:
        con.close()
    for s, row in sorted(splits.items()):
        row["qualify_rate"] = round(row["qualifying"] / row["episodes"], 4) if row["episodes"] else 0.0
        LOGGER.info("split=%-6s episodes=%7d qualifying@%d=%6d (%.2f%%)",
                    s, row["episodes"], horizon, row["qualifying"], 100 * row["qualify_rate"])
    return splits


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", required=True)
    ap.add_argument("--horizon", type=int, default=385)
    ap.add_argument("--require-val", type=int, default=0,
                    help="exit nonzero unless qualifying val >= this (the pre-registered guard)")
    ap.add_argument("--out", default=None, help="also write the JSON report here")
    a = ap.parse_args(argv)
    splits = probe(a.db, a.horizon)
    report = {"db": str(a.db), "horizon": a.horizon,
              "thresholds": {k: DEFAULT_THRESHOLDS[k]
                             for k in ("mv1_min_hspeed_qu_per_s", "mv1_min_ticks")},
              "splits": splits}
    print(json.dumps(report, indent=1))
    if a.out:
        Path(a.out).write_text(json.dumps(report, indent=1), encoding="utf-8")
    val_q = splits.get("val", {}).get("qualifying", 0)
    if a.require_val and val_q < a.require_val:
        LOGGER.error("GUARD FAILED: qualifying val %d < required %d", val_q, a.require_val)
        return 1
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    sys.exit(main())
