#!/usr/bin/env python3
"""coldstart_inspect.py — quantify the COLD-START low-speed coverage of a v5 BC shard.

DIAGNOSTIC ONLY (read-only). The v5 policy dead-stops in closed loop because rest
(hspeed ~= 0) is off-manifold for the always-moving corpus. This script measures, on the
REAL train shard, how much low-speed / episode-start signal the human demos actually
contain — the data we can upweight to put rest->launch in-distribution. NO synthetic
labels, NO training; it only reads the shard + the norm artifact and prints honest counts.

Method (every number from the shard the trainer actually consumes):
  * load via the SAME broad_bc.core.read_shard the trainer uses (contract reshaping),
  * for each window take the LAST REAL tick (broad_bc.core._last_real_tick over `mask`) —
    EXACTLY the tick the trainer trains on — and read hspeed_norm (SELF channel index 6)
    from self_history[wi][-SELF_DIM:] (the newest block = the current single-tick SELF),
  * invert the `robust` (median/IQR) hspeed normalization from the norm artifact to RAW
    qu/s, clipped to the artifact's clip range, so the threshold is in real game units,
  * mark a window an EPISODE-START window if its start_tick is the minimum start_tick for
    its episode_id (the post-spawn standing-start window),
  * report low-speed tick counts at several thresholds + how many are episode-starts +
    the existing per-(last-tick) weight stats.

Usage:
  python -m ml.pipeline.coldstart_inspect --shard gold/shards/dm3_4on4_train.parquet \
      --norm gold/norm/normalization_stats.json [--map dm3]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent          # ml/pipeline
ML = HERE.parent                                # ml/
if str(ML) not in sys.path:
    sys.path.insert(0, str(ML))

from broad_bc import core                       # noqa: E402
from broad_bc import shard_contract as SC       # noqa: E402

# SELF channel index of hspeed_norm inside a 21-wide SELF block (agent_observation.
# SELF_FIELDS order: pos(3) vel(3) hspeed(1) ...). hspeed lives at index 6.
HSPEED_IDX = 6

LOW_THRESHOLDS = (25.0, 50.0, 80.0, 120.0)      # qu/s; 80 = the vel-heading floor


def invert_robust(norm_value: float, spec: dict) -> float:
    """RAW value from a `robust` (median + IQR) normalized value: raw = v*iqr + median,
    then clamp to the spec's clip range (the same clip applied at fit time)."""
    median = float(spec["median"])
    iqr = float(spec["iqr"])
    raw = norm_value * iqr + median
    clip = spec.get("clip")
    if clip:
        lo, hi = float(clip[0]), float(clip[1])
        raw = max(lo, min(hi, raw))
    return raw


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--shard", type=Path, required=True)
    ap.add_argument("--norm", type=Path, required=True)
    ap.add_argument("--map", default="dm3")
    args = ap.parse_args(argv)

    stats = json.loads(Path(args.norm).read_text(encoding="utf-8"))
    hspec = stats["per_map"][args.map]["hspeed"]
    if hspec.get("method") != "robust":
        raise SystemExit(f"expected robust hspeed spec, got {hspec.get('method')}")

    shard = core.read_shard(args.shard)
    self_hist = shard[SC.KEY_SELF_HISTORY]          # [n][HD]
    mask = shard[SC.KEY_MASK]                        # [n][K]
    weight = shard.get(SC.KEY_WEIGHT)               # [n][K] or None
    eids = shard.get(SC.KEY_EPISODE_IDS)           # [n] int
    # start_tick is a raw parquet column the reshape does not surface; read it directly.
    import pyarrow.parquet as pq
    start_ticks = pq.read_table(args.shard, columns=["start_tick"]).column(
        "start_tick").to_pylist()

    n = len(self_hist)
    sd = SC.EXPECTS_SELF_DIM
    # episode-start = the window with the MINIMUM start_tick for its episode_id.
    ep_min = {}
    for i in range(n):
        e = eids[i]
        st = int(start_ticks[i])
        if e not in ep_min or st < ep_min[e]:
            ep_min[e] = st

    counts = {t: 0 for t in LOW_THRESHOLDS}
    counts_epstart = {t: 0 for t in LOW_THRESHOLDS}
    n_epstart_windows = 0
    epstart_low50 = 0
    last_tick_w = []                                # the per-last-tick weight the trainer uses
    epstart_hspeeds = []
    all_hspeeds_lt120 = 0
    for i in range(n):
        wmask = mask[i]
        ti = core._last_real_tick(wmask)
        if float(wmask[ti]) < 0.5:
            continue
        # newest SELF block = self_history[-SELF_DIM:]; hspeed_norm at HSPEED_IDX.
        block = self_hist[i][-sd:]
        hspeed = invert_robust(float(block[HSPEED_IDX]), hspec)
        w = float(weight[i][ti]) if weight is not None else 1.0
        last_tick_w.append(w)
        is_epstart = int(start_ticks[i]) == ep_min[eids[i]]
        if is_epstart:
            n_epstart_windows += 1
            epstart_hspeeds.append(hspeed)
            if hspeed < 50.0:
                epstart_low50 += 1
        if hspeed < 120.0:
            all_hspeeds_lt120 += 1
        for t in LOW_THRESHOLDS:
            if hspeed < t:
                counts[t] += 1
                if is_epstart:
                    counts_epstart[t] += 1

    n_real = len(last_tick_w)
    import statistics as st
    print("=== COLD-START COVERAGE (train shard last-real-tick) ===")
    print(f"shard={args.shard}  windows(real last-tick)={n_real}  episodes={len(ep_min)}")
    print(f"hspeed robust spec: median={hspec['median']:.2f} iqr={hspec['iqr']:.2f} "
          f"clip={hspec.get('clip')}")
    print(f"episode-start windows (min start_tick per episode) = {n_epstart_windows}")
    print(f"  of those, hspeed<50 qu/s = {epstart_low50} "
          f"({100.0*epstart_low50/max(n_epstart_windows,1):.1f}%)")
    if epstart_hspeeds:
        print(f"  episode-start hspeed: min={min(epstart_hspeeds):.1f} "
              f"median={st.median(epstart_hspeeds):.1f} max={max(epstart_hspeeds):.1f}")
    print("low-speed last-tick windows by threshold (raw qu/s):")
    for t in LOW_THRESHOLDS:
        print(f"  hspeed < {t:6.1f}: {counts[t]:6d} windows "
              f"({100.0*counts[t]/max(n_real,1):5.2f}%)  "
              f"of which episode-start={counts_epstart[t]}")
    print(f"existing last-tick weight: min={min(last_tick_w):.3f} "
          f"max={max(last_tick_w):.3f} mean={st.mean(last_tick_w):.3f} "
          f"nonzero={sum(1 for w in last_tick_w if w>0)}/{n_real}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
