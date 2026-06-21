#!/usr/bin/env python3
"""coldstart_reweight.py — upweight rest->launch frames in a v5 BC shard (a DATA op).

THE COLD-START FIX, BC-only, no synthetic labels. The v5 policy dead-stops in closed
loop because rest (hspeed ~= 0) is off-manifold: the corpus is mostly fast frames, and
the few low-speed frames are dominated by "human at rest, NOT pressing forward" (it
ground-accelerates then hops). So at rest the policy correctly learns "none" -> zero
thrust -> absorbing state. This boosts the per-sample loss WEIGHT of the REAL human
frames that demonstrate launch-from-low-speed, so rest->accelerate becomes in-
distribution WITHOUT inventing any action.

What it boosts (REAL frames only; the trainer reads weight[wi][last_real_tick]):
  a window's last-real-tick weight is multiplied by `--boost` iff that tick's
    raw hspeed < `--hspeed-max` qu/s            (low-speed / cold band), AND
    (unless --all-low) the human is producing THRUST there:
        forwardmove > 0  OR  jump pressed  OR  sidemove != 0
  i.e. the genuine "slow and accelerating/strafing/hopping" launch demonstrations. A
  separate, larger `--epstart-boost` (default = boost) is applied to true episode-start
  windows (min start_tick per episode_id) that are also low-speed, the cleanest post-
  spawn standing-starts. Only the LAST-REAL-TICK weight cell is changed (the only cell
  the trainer reads); every other array/byte is copied through unchanged, and the table
  metadata (shape/contract keys) is preserved verbatim so the loader reshapes identically.

hspeed is recovered from self_history[wi][-SELF_DIM:][6] (hspeed_norm, the newest SELF
block) inverted through the norm artifact's robust median/IQR spec (clipped) -> raw qu/s,
so the threshold is in real game units. Zero-weight ticks (pad/interp/missing label) are
left at 0 (boost*0 == 0) -- we never resurrect an unlabeled frame.

Usage (pinnacle, ml venv):
  python -m ml.pipeline.coldstart_reweight \
      --in  gold/shards/dm3_4on4_train.parquet \
      --out gold/shards/dm3_4on4_train_cs.parquet \
      --norm gold/norm/normalization_stats.json \
      --hspeed-max 80 --boost 10 [--all-low] [--epstart-boost 16]
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

LOGGER = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent
ML = HERE.parent
if str(ML) not in sys.path:
    sys.path.insert(0, str(ML))

from broad_bc import core                       # noqa: E402
from broad_bc import shard_contract as SC       # noqa: E402

HSPEED_IDX = 6                                  # hspeed_norm channel in a 21-wide SELF block


def invert_robust(v: float, spec: dict) -> float:
    raw = v * float(spec["iqr"]) + float(spec["median"])
    clip = spec.get("clip")
    if clip:
        raw = max(float(clip[0]), min(float(clip[1]), raw))
    return raw


def is_launch(act_row) -> bool:
    """Human is producing thrust this tick: forwardmove>0 OR jump pressed OR sidemove!=0.
    act cols: forwardmove(0) sidemove(1) upmove(2) jump_button(3) attack(4)."""
    return (float(act_row[0]) > 1e-3) or (float(act_row[3]) >= 0.5) \
        or (abs(float(act_row[1])) > 1e-3)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="inp", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--norm", type=Path, required=True)
    ap.add_argument("--map", default="dm3")
    ap.add_argument("--hspeed-max", type=float, default=80.0,
                    help="boost last-tick frames whose raw hspeed is below this (qu/s)")
    ap.add_argument("--boost", type=float, default=10.0,
                    help="multiply the matching last-tick weight by this factor")
    ap.add_argument("--epstart-boost", type=float, default=None,
                    help="separate (usually larger) boost for low-speed episode-start "
                         "windows; defaults to --boost")
    ap.add_argument("--all-low", action="store_true",
                    help="boost ALL low-speed frames, not just thrust/launch ones "
                         "(diagnostic; the default targets launch frames only)")
    args = ap.parse_args(argv)
    epstart_boost = args.boost if args.epstart_boost is None else args.epstart_boost

    import numpy as np
    import pyarrow as pa
    import pyarrow.parquet as pq

    stats = json.loads(Path(args.norm).read_text(encoding="utf-8"))
    hspec = stats["per_map"][args.map]["hspeed"]
    if hspec.get("method") != "robust":
        raise SystemExit(f"expected robust hspeed spec, got {hspec.get('method')}")

    # Read the table RAW (preserve every column + the schema metadata verbatim), and ALSO
    # via the contract loader so we get the reshaped self_history/mask/act/episode ids.
    t = pq.read_table(args.inp)
    meta_kv = t.schema.metadata or {}
    K = int((meta_kv.get(b"komodobots.shard.K") or b"1").decode())
    sd = SC.EXPECTS_SELF_DIM

    sh = core.read_shard(args.inp)
    hist = sh[SC.KEY_SELF_HISTORY]              # [n][HD]
    mask = sh[SC.KEY_MASK]                      # [n][K]
    act = sh[SC.KEY_ACT]                        # [n][K][A]
    eids = sh.get(SC.KEY_EPISODE_IDS)
    start_ticks = pq.read_table(args.inp, columns=["start_tick"]).column(
        "start_tick").to_pylist()
    n = len(hist)
    assert t.num_rows == n, f"row count mismatch {t.num_rows} != {n}"

    ep_min = {}
    for i in range(n):
        e = eids[i]
        st = int(start_ticks[i])
        if e not in ep_min or st < ep_min[e]:
            ep_min[e] = st

    # Pull the FLAT weight column out of the raw table, reshape to [n, K], edit the
    # last-real-tick cell per matching window, flatten back. Editing the raw flat column
    # (not rebuilding from the loader's float view) keeps every other byte identical.
    wcol = t.column("weight")
    if wcol.null_count:
        raise SystemExit("weight column has nulls; contract is dense")
    wflat = np.concatenate(
        [ch.flatten().to_numpy(zero_copy_only=False) for ch in wcol.chunks]
    ).astype(np.float32)
    wmat = wflat.reshape(n, K)

    n_boost = n_epstart = n_zero_skipped = 0
    boosted_share_before = 0.0
    # the trainer only ever uses the LAST-REAL-TICK weight (one cell per window), so the
    # honest denominator for "share of the training signal" is the SUM over those cells,
    # NOT the full K*n flat column. Accumulate it here so the printout reports the share
    # the trainer actually sees.
    last_tick_total_before = 0.0
    for i in range(n):
        wm = mask[i]
        ti = core._last_real_tick(wm)
        if float(wm[ti]) < 0.5:
            continue
        last_tick_total_before += float(wmat[i, ti])
        hs = invert_robust(float(hist[i][-sd:][HSPEED_IDX]), hspec)
        if hs >= args.hspeed_max:
            continue
        match = True if args.all_low else is_launch(act[i][ti])
        if not match:
            continue
        w0 = float(wmat[i, ti])
        if w0 <= 0.0:
            n_zero_skipped += 1
            continue                            # never resurrect an unlabeled frame
        is_epstart = int(start_ticks[i]) == ep_min[eids[i]]
        factor = epstart_boost if is_epstart else args.boost
        wmat[i, ti] = w0 * factor
        boosted_share_before += w0
        n_boost += 1
        if is_epstart:
            n_epstart += 1

    new_wflat = wmat.reshape(-1)
    # Rebuild the weight column as list<float32> of length K per row (same logical type).
    offsets = np.arange(0, (n + 1) * K, K, dtype=np.int32)
    new_wcol = pa.ListArray.from_arrays(
        pa.array(offsets, type=pa.int32()),
        pa.array(new_wflat, type=pa.float32()))
    idx = t.schema.get_field_index("weight")
    t2 = t.set_column(idx, t.schema.field(idx), new_wcol)
    # preserve the schema-level metadata (shape/contract keys) verbatim.
    t2 = t2.replace_schema_metadata(meta_kv)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(t2, out)

    # post-boost the boosted set carries boosted_share_before scaled by the (mixed) factor;
    # the new last-tick total grows by the same delta (only last-tick cells were edited).
    delta = (post_boost_sum(wmat, mask, hist, act, eids, ep_min, hspec, args, sd)
             - boosted_share_before)
    last_tick_total_after = last_tick_total_before + delta
    boosted_after = boosted_share_before + delta
    print("=== COLD-START REWEIGHT ===")
    print(f"in={args.inp} -> out={out}")
    print(f"rule: hspeed < {args.hspeed_max} qu/s AND "
          f"{'ALL low-speed' if args.all_low else 'launch (fwd>0|jump|side!=0)'}; "
          f"boost={args.boost} epstart_boost={epstart_boost}")
    print(f"boosted windows: {n_boost} (episode-start of those: {n_epstart}); "
          f"zero-weight skipped: {n_zero_skipped}")
    print("share is of the LAST-REAL-TICK effective weight (what the trainer trains on):")
    print(f"  boosted set: {boosted_share_before:.1f} pre "
          f"({100.0*boosted_share_before/max(last_tick_total_before,1):.2f}% of "
          f"{last_tick_total_before:.1f}) -> {boosted_after:.1f} post "
          f"({100.0*boosted_after/max(last_tick_total_after,1):.2f}% of "
          f"{last_tick_total_after:.1f})")
    return 0


def post_boost_sum(wmat, mask, hist, act, eids, ep_min, hspec, args, sd):
    """Sum of the (now-edited) last-real-tick weights of the boosted set — the exact
    post-boost effective weight the boosted frames carry."""
    s = 0.0
    for i in range(len(hist)):
        ti = core._last_real_tick(mask[i])
        if float(mask[i][ti]) < 0.5:
            continue
        if invert_robust(float(hist[i][-sd:][HSPEED_IDX]), hspec) >= args.hspeed_max:
            continue
        if not (True if args.all_low else is_launch(act[i][ti])):
            continue
        if float(wmat[i, ti]) > 0.0:
            s += float(wmat[i, ti])
    return s


if __name__ == "__main__":
    raise SystemExit(main())
