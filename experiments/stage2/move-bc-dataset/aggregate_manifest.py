#!/usr/bin/env python3
"""Post-aggregate the MOVE-BC pool manifest into the committed summary numbers.

The per-demo build (build_move_bc_pool.py) records movement-quality + label-
integrity stats per demo. This rolls them up to the pool-level headline figures
the dataset manifest needs:

  - raw frame total (all self-POV 4on4 frames extracted)
  - demo-level label-integrity pass rate (strict: whole-demo segment-clean >= 90%)
  - SEGMENT-level clean-frame yield = the actual TRAINABLE MOVE set after
    dropping submodel/player-collision/teleport/respawn-contaminated 1 s segments
    (the docs/12 §5 "accept only on submodel-free / opponent-free segments" rule)
  - per-player and per-coverage breakdowns

Run on the manifest emitted by build_move_bc_pool.py.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from collections import Counter

SEGMENT = 77  # frames per ~1 s segment (matches the builder)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)

    doc = json.loads(args.manifest.read_text())
    demos_all = [d for d in doc["demos"] if d.get("ok")]
    # 7 demos carry a non-dm3 recorded map (census filename heuristic matched a
    # multi-map series where the recorded leg is cmt4/dm6/e2m5/etc) -> exclude
    # from the dm3 MOVE pool. Flag them rather than silently dropping.
    DM3_MAP = "The Abandoned Base"
    non_dm3 = [d["demo"] for d in demos_all if d.get("map") != DM3_MAP]
    demos = [d for d in demos_all if d.get("map") == DM3_MAP]

    total_frames = sum(d["frames"] for d in demos)
    seg_total = seg_clean = 0
    demo_pass = 0
    players = Counter()
    cov_buckets = Counter()
    clean_frac_buckets = Counter()
    per_player_clean_frames = Counter()

    for d in demos:
        li = d.get("label_integrity", {}) or {}
        st = int(li.get("segments", 0) or 0)
        sc = int(li.get("segments_clean", 0) or 0)
        seg_total += st
        seg_clean += sc
        if d.get("label_pass"):
            demo_pass += 1
        pl = d.get("player") or "(unknown)"
        players[pl] += 1
        # segment-level clean-frame estimate for this demo
        clean_frames = sc * SEGMENT
        per_player_clean_frames[pl] += clean_frames
        cov = d.get("paired_coverage") or 0.0
        cov_buckets[_bucket(cov, [0.5, 0.7, 0.85, 0.95])] += 1
        cf = (sc / st) if st else 0.0
        clean_frac_buckets[_bucket(cf, [0.1, 0.25, 0.5, 0.9])] += 1

    seg_clean_frames = seg_clean * SEGMENT  # ~trainable frames after segment filter

    summary = dict(doc["summary"])
    summary["dm3_only_pool"] = True
    summary["non_dm3_demos_excluded"] = len(non_dm3)
    summary["non_dm3_demos"] = non_dm3
    summary["dm3_demos"] = len(demos)
    summary["raw_frames_extracted"] = total_frames
    summary["segments_total"] = seg_total
    summary["segments_clean"] = seg_clean
    summary["segment_clean_frac_pool"] = round(seg_clean / max(seg_total, 1), 4)
    summary["trainable_clean_frames_est"] = seg_clean_frames
    summary["trainable_clean_hours_est_at_72hz"] = round(seg_clean_frames / 72 / 3600, 1)
    summary["demo_level_pass_rate"] = round(demo_pass / max(len(demos), 1), 4)
    summary["paired_coverage_buckets"] = dict(cov_buckets)
    summary["clean_segment_frac_buckets"] = dict(clean_frac_buckets)
    summary["distinct_players"] = len(players)
    summary["top_players_by_demo_count"] = players.most_common(20)
    summary["top_players_by_clean_frames"] = per_player_clean_frames.most_common(20)

    # Re-emit the full manifest with the enriched summary + a per-demo is_dm3 flag,
    # so the committed manifest.json is self-contained.
    for d in doc["demos"]:
        d["is_dm3"] = (d.get("map") == DM3_MAP)
    out = {"summary": summary, "demos": doc["demos"]}
    args.out.write_text(json.dumps(out, indent=1))
    print(json.dumps(summary, indent=1))


def _bucket(v, edges):
    lo = 0.0
    for e in edges:
        if v < e:
            return f"<{e}"
        lo = e
    return f">={lo}"


if __name__ == "__main__":
    main()
