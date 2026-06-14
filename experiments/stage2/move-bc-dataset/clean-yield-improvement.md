# MOVE BC clean-segment yield improvement (dm3 4on4 self-POV)

Improves the **clean physics-faithful frame yield** of the Stage-2 MOVE
behavioural-cloning pool (`docs/12` §5 "accept only on submodel-free /
opponent-free trajectory segments") without lowering label quality, and
quantifies the gain over the manifest baseline.

- Corpus: 465 dm3 self-POV 4on4 demos, 37,327,836 frames (the existing
  `manifest.json` pool — same shards in WSL `~/move_bc_shards/`).
- Analysis (no model training, no torch): `analyze_clean_yield.py` consumes the
  already-built NDJSON shards (re-uses the BC labels; skips the ~124 s/demo
  re-extraction) and re-runs the **validated** `pmove_sim` per demo, then scores
  two acceptance methods on the identical per-frame divergence stream.
- Results: `clean-yield-results.json` (per-demo + aggregate).
  Clean-segment index: `clean-segment-index.json` (compact, per-demo only).

## Headline: 2.03x more clean frames from better segmentation

| Acceptance method | clean frames | clean % | hours @72 Hz |
|---|---|---|---|
| **BASELINE** (fixed 77-frame windows, max-err vote) | **2,883,265** | 7.72% | 11.1 h |
| **IMPROVED** (frame-level clean mask, boundary-aware runs >=24f) | **5,847,254** | 15.66% | 22.6 h |
| (reference) raw per-frame clean mask, no min-run filter | 9,685,340 | 25.95% | 37.4 h |

The baseline number reproduces the manifest's `trainable_clean_frames_est`
(2,883,265) **exactly** — the analysis re-derives the same labels and the same
`pmove_sim` divergence, so the +2,963,989 frames (2.03x) are a like-for-like
gain from the acceptance rule alone, not a methodology change.

### Why fixed windows under-count

The baseline cuts the demo into fixed 77-frame (1 s) windows and **fails the
whole window if any single frame exceeds 4 qu**. A 60-frame clean bunny run that
ends in one lift-ride or one opponent bump loses all 60 clean frames. The
divergence stream is strongly bimodal (clean frames sit at the demo's
quantization floor, contaminated frames blow past tens of qu), so a **per-frame
mask** cleanly separates them. Cutting maximal runs of consecutive
clean frames (broken at teleport/respawn discontinuities, min run 24 frames
~1/3 s to stay teachable) recovers the clean frames trapped inside otherwise-failed
windows. This *is* the "segment on actual discontinuity boundaries + onground/air
phase, exclude the contaminated window rather than failing the whole segment"
lever from the task — implemented at the frame level, which is the limit of that idea.

The MIN_RUN=24 filter is conservative: dropping it (raw mask) would give 9.69 M
frames (25.9%), but short runs cannot teach a coherent 1 s movement phase, so
the 5.85 M (>=24-frame runs) is the recommended trainable figure.

## Task 1 — Coverage prioritization and the interpolation-inflation question

Clean yield by `paired_coverage` stratum (improved method):

| coverage | demos | frames | base clean % | improved clean % | imp/base |
|---|---|---|---|---|---|
| [0.00,0.50) | 29 | 1.81 M | 5.0% | 8.1% | 1.62x |
| [0.50,0.70) | 68 | 5.31 M | 5.5% | 10.5% | 1.89x |
| [0.70,0.85) | 135 | 11.35 M | 6.6% | 13.7% | 2.09x |
| [0.85,0.90) | 64 | 5.37 M | 8.6% | 17.1% | 2.00x |
| [0.90,0.95) | 74 | 6.36 M | 8.7% | 20.3% | 2.33x |
| [0.95,1.01) | 95 | 7.14 M | 10.3% | 19.2% | 1.86x |

**Coverage helps, but it is not the limiting lever for clean *count*.**
Pearson(coverage, improved clean fraction) = **0.32** (was 0.24 for the baseline
fraction). Clean% roughly doubles from the lowest to highest coverage tier, so
interpolation *does* inflate divergence on sparse demos — but only modestly. The
contamination that fails 84% of frames is **collision**, not interpolation
(see Task 3). So:

- **Interpolation-inflated vs genuinely contaminated:** the coverage gradient
  bounds the interpolation-inflated share. Going from the ~10% clean rate at high
  coverage to the ~8% pooled rate implies on the order of ~20% relative inflation
  of the *failed* count on low-coverage demos — real but second-order. The bulk of
  the failed 84% is genuine 4on4 contamination (collision/submodel), which is
  intrinsic to match play and does not improve with coverage.
- **Coverage-filtered clean set (cov >= 0.9):** 169 demos, **2,664,030 improved
  clean frames (10.3 h)** = only **45.6%** of all improved-clean frames. Filtering
  hard on coverage throws away more than half the usable physics-faithful data.

Cumulative improved-clean frames by coverage floor:

| floor | demos | improved clean frames | % of total | hours |
|---|---|---|---|---|
| >=0.0 | 465 | 5,847,254 | 100.0% | 22.6 h |
| >=0.7 | 368 | 5,144,430 | 88.0% | 19.8 h |
| >=0.85 | 233 | 3,584,214 | 61.3% | 13.8 h |
| >=0.9 | 169 | 2,664,030 | 45.6% | 10.3 h |
| >=0.95 | 95 | 1,372,627 | 23.5% | 5.3 h |

**Recommendation:** do not hard-filter on coverage. Keep all coverage tiers but
**weight by a coverage-derived quality tier** (the clean *frames* are physics-
validated regardless of coverage; coverage only affects how trustworthy the
interpolated reference is on the *failed* frames, which are excluded anyway).

## Task 3 — Where the lost ~84% goes (contamination class)

Per-frame classification of every contaminated frame (err > 4 qu, excluding
teleport-reanchor rows), 27,610,605 contaminated frames total:

| class | frames | share | what it is |
|---|---|---|---|
| **collision** | 21,689,063 | **78.6%** | large horizontal error: player-vs-player block/contest (sim traces worldmodel only) |
| drift | 3,900,333 | 14.1% | small physics drift that crossed 4 qu late in a free-run window |
| submodel | 1,983,970 | 7.2% | grounded-but-no-world-floor / large vertical error: plat/lift (submodel) ride |
| teleport | 37,239 | 0.1% | teleporter/respawn transition frames |

**Collision dominates by far** — consistent with the README's diagnosis that a
live 4on4 dm3 POV is saturated with player-vs-player contact the offline sim
cannot model. Submodel (lift) contamination is real but small (7%). The 14%
"drift" is partly an artefact of the 77-frame free-run horizon (error accumulates
toward the end of a window even on clean physics); tighter periodic re-anchoring
would reclaim some of it as clean, at the cost of shorter coherent horizons — a
cheap follow-on lever (just lower `reanchor_every`) if more frames are needed.

## Recommended clean training set definition (what feeds MOVE BC)

**Consume the per-frame clean mask, not fixed windows.** A frame is trainable iff
its `pmove_sim` free-run error <= 4 qu under teleport+periodic (77-frame)
re-anchoring; keep maximal consecutive-clean runs of >= 24 frames, broken at
teleport/respawn boundaries.

- **Trainable pool:** 5,847,254 frames (15.66%, ~22.6 h @72 Hz) across 465 demos.
- **Quality tiers** (by demo `paired_coverage`, for optional sample weighting —
  all tiers are physics-faithful, the tier only reflects reference trust on the
  excluded frames):
  - Tier A (cov >= 0.9): 2,664,030 frames
  - Tier B (0.7 <= cov < 0.9): 2,480,400 frames
  - Tier C (cov < 0.7): 702,824 frames
- The clean frames are concentrated: top 100 demos hold 52.5%, top 200 hold
  73.2% — so a curriculum / curation pass can lean on the high-yield demos.

The clean-segment index (`clean-segment-index.json`) records per-demo improved
clean-frame counts, run counts, coverage, and tier. To materialize a frame-level
mask for the trainer, re-run `analyze_clean_yield.py` over a shard and keep the
boundary-aware run intervals (the script already computes them; emitting the
intervals is a one-line change if the trainer wants explicit `[start,end)` spans
rather than recomputing the mask).

## Levers that worked (ranked)

1. **Frame-level acceptance instead of fixed-window vote: +2.96 M frames (2.03x).**
   The single biggest lever. Free, no quality loss — same 4 qu tolerance, same
   validated sim, just stops discarding clean frames adjacent to a contaminated one.
2. **Keep all coverage tiers (do not hard-filter at 0.9):** preserves 54% more
   clean frames than a cov>=0.9 cut, at a documented and weightable quality cost.
3. **(Optional follow-on) tighter re-anchoring** to reclaim part of the 14% "drift"
   class as clean — not applied here; flagged as a cheap next step.

## Reproduce (WSL2)

```bash
cd /mnt/c/Users/benya/projects/quakeworld/komodobots-ml
python3 experiments/stage2/move-bc-dataset/analyze_clean_yield.py \
    --demo-list ~/move_bc_demolist.tsv \
    --shard-dir ~/move_bc_shards \
    --manifest  experiments/stage2/move-bc-dataset/manifest.json \
    --out experiments/stage2/move-bc-dataset/clean-yield-results.json \
    --workers 14 --classify
# ~282 s on the AMD 7800X3D, 14 workers; 0 demo failures.
```

## Provenance / integrity

- Same validated MVDSV `pmove_sim` port + dm3 BSP as the manifest build; same
  4 qu tolerance, same 77-frame segment, same teleport detection. The baseline
  number reproduces `manifest.json:summary.trainable_clean_frames_est` exactly,
  which is the cross-check that the improved number is measured on the same basis.
- No torch, no training. Segmentation/validation analysis only.
- Raw frame shards stay in WSL `~/move_bc_shards/` (9.1 GB, outside the repo).
