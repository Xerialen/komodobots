# Stage-2 MOVE behavioural-cloning POOL dataset (dm3 4on4 self-POV)

Builds the **pooled** (state, action) BC training set for the learned MOVE
micro-controller of the DM3 4on4 stand-in bot (`docs/12` Stage 2; §5 MOVE
bullet). This is a **pretraining pool**, not a single-player clone — per-player
depth is thin (max 10 demos/player; most have 1–2), so the corpus is pooled
elite-self-POV per the census recommendation.

## What was built (full corpus, not a tranche)

The complete **472 self-POV 4on4 dm3 demos** from the Stage-0 spike-3 census were
run end-to-end. **Zero build failures.**

| Metric | Value |
|---|---|
| Demos processed | 472 / 472 OK (0 fail) |
| dm3 demos (after map filter) | **465** (7 excluded — see below) |
| Raw frames extracted (dm3) | **37,328,301** (full corpus 37,561,151 — matches census) |
| Distinct players (dm3) | **254** |
| Shard format | per-demo NDJSON, one row/frame |
| Shard size | **9.1 GB**, in WSL `~/move_bc_shards/` (gitignored by location) |
| Build wall-clock | **33.6 min** (14 WSL2 workers, AMD 7800X3D) |

State/action per frame (the BC label):
```json
{"demo","map","frame","msec","o":[x,y,z],"v":[x,y,z],"a":[pitch,yaw,roll],
 "m":[fwd,side,up],"buttons","onground","pm_code"}
```
state = (o, v, a, onground, pm_code); action = (m=[fwd,side,up], buttons). This is
the exact shape `scripts/build_training_dataset.py` emits — this build reuses its
core (`build_replay_command_file.build_replay_frames`, exact usercmds from
`tools/qwd_usercmd`, time-aligned `svc_playerinfo` state recovery).

## Label integrity — the headline finding

Each demo's recorded usercmds were re-simulated through the **validated MVDSV
`pmove_sim` port** (the same engine + `C:\nQuake\qw\maps\dm3.bsp` the
`nav_doctrine` validation report passes against), using a **1 s-segmented
(77-frame) free-run with teleport/respawn re-anchoring** — the exact method that
scored the clean human SNG→RL replay at max-err ~0.2 qu. A demo passes if ≥90% of
its 1 s segments stay within 4 qu.

**Whole-demo pass rate: 0.43% (2/465).** This is the expected, honest result and
the key data-quality finding:

> A **live 4on4 dm3 match POV is saturated with contamination that the offline
> sim does not (and cannot) model** — player-vs-player collisions, lift/plat
> (submodel) rides, teleporter rides, and respawns. `pmove_sim` traces only the
> worldmodel (submodels + other players are out of scope, by design — see the
> validation report's "Unresolved" §2). So a *whole-demo* divergence number is
> meaningless for match data; the only viable acceptance unit is the **segment**.

The two whole-demo passes are short (550 / 840-frame), near-trick, ~0.99-coverage
clips — i.e. they look like the clean solo route the sim was validated on. Even
demos with ≥0.95 state coverage have a median clean-segment fraction of just
**0.073** — coverage alone does not rescue a match demo, because the
contamination is intrinsic to 4on4 play, not a parsing artefact.

### Segment-level trainable yield (the usable MOVE set)

Per `docs/12` §5 ("accept only on submodel-free / opponent-free trajectory
segments"), the trainable set is the **clean 1 s segments**:

| Metric | Value |
|---|---|
| Total 1 s segments (dm3) | 485,007 |
| **Clean segments (≤4 qu)** | **37,445 (7.72%)** |
| **Trainable clean frames (est.)** | **~2,883,265** |
| **≈ hours @ 72 Hz** | **~11.1 h** |

Segment errors are strongly **bimodal** — clean segments sit at p50 ≈ 0.0 qu (sim
reproduces the trajectory to the demo's quantization floor), contaminated
segments blow past tens-to-hundreds of qu — so the clean set is cleanly
separable, not a soft threshold. ~2.9M physics-faithful frames is a solid
pretraining pool (same order as a few hours of pro CS play; MLMove trained team
movement BC on 123 h across many maps — this is ~11 h on a single map, fully
input-faithful and physics-validated).

**Recommended training filter:** consume only segments whose
`label_integrity.seg_max_err ≤ 4 qu` (the builder records per-demo
`segments_clean` / `segments`; a per-segment mask is a one-pass re-run of
`pmove_sim.replay(reanchor_every=77)` over each shard if a frame-level mask is
needed). Demos are NOT dropped — they are flagged, and the clean frames inside a
mostly-dirty demo are still recoverable.

## Data-quality findings

1. **7 non-dm3 demos** (excluded from the dm3 pool, flagged in
   `manifest.json:summary.non_dm3_demos`): the census filename heuristic matched
   multi-map series whose recorded leg is a different map (cmt4 / dm6 / e2m5 /
   e3m6 / "Painkiller" / "Castle of the Damned"). The recorded `map_level` proves
   them out. The 465 true-dm3 demos all report `"The Abandoned Base"`.
2. **State coverage is the limiting factor, not parsing.** `paired_coverage`
   (matched `svc_playerinfo` state frames / usercmd frames) is broadly
   distributed: 95 demos ≥0.95, but 68 below 0.7 and 29 below 0.5. Low coverage
   means the per-frame state reference is interpolated, which both weakens the
   `o`/`v` labels on those frames and inflates the apparent sim divergence.
   High-coverage demos give the cleanest segments.
3. **Per-player depth is thin** (confirms the census): top players by demo count
   are crit (10), exile (9), wart (9), spice/akke (8), vana/janus (7). By clean
   *frame* yield: fs (102k), spice (71k), sassa (71k), reverend (70k). This is a
   **pool for pretraining**, not enough for a single-elite clone — exactly the
   shape `docs/12` §5 and the census `infeasibility_floor` already call for.

## Clean-segment yield improvement (2026-06-14)

The fixed 77-frame window acceptance above **under-counts** clean frames: one
contaminated frame fails the whole 1 s window. A **frame-level clean mask**
(keep maximal runs of consecutive frames whose `pmove_sim` error <=4 qu, broken
at teleport/respawn boundaries, runs >=24 frames) recovers the clean frames
trapped inside otherwise-failed windows — **2.03x the trainable yield, same 4 qu
tolerance, same validated sim, no quality loss**:

| Acceptance | clean frames | clean % | hours @72 Hz |
|---|---|---|---|
| baseline (fixed-window vote) | 2,883,265 | 7.72% | 11.1 h |
| **improved (frame-level mask)** | **5,847,254** | **15.66%** | **22.6 h** |

Lost frames are dominated by **player-collision (78.6%)**, then free-run drift
(14.1%), submodel/lift rides (7.2%), teleport (0.1%) — contamination is intrinsic
to 4on4 play, not an interpolation artefact (Pearson(coverage, clean%)=0.32;
a cov>=0.9 hard filter would discard 54% of the clean frames). **Recommended MOVE
BC set = the improved frame-level clean mask, all coverage tiers, optionally
weighted by a coverage quality tier (A>=0.9 / B 0.7-0.9 / C<0.7).** Full analysis:
`clean-yield-improvement.md`; per-demo index: `clean-segment-index.json`;
results: `clean-yield-results.json`; script: `analyze_clean_yield.py`.

## Artifacts

| Path | Committed? | What |
|---|---|---|
| `manifest.json` | yes (508 KB) | summary + per-demo movement-quality & label-integrity stats, `is_dm3` flag, provenance (per-demo `source_sha256`) |
| `clean-yield-improvement.md` | yes | clean-segment yield improvement report (2.03x, contamination breakdown, recommended set) |
| `clean-yield-results.json` | yes (254 KB) | per-demo + aggregate baseline-vs-improved clean-frame counts and contamination classes |
| `clean-segment-index.json` | yes (92 KB) | compact per-demo improved clean-frame yield + coverage quality tier (the clean-segment index; no per-frame masks — raw shards stay in WSL) |
| `analyze_clean_yield.py` | yes | shard-based clean-yield analyzer (frame-level mask + boundary-aware runs + contamination classifier) |
| `build_move_bc_pool.py` | yes | the build wrapper (frames → NDJSON shard → segmented pmove_sim label-integrity) |
| `aggregate_manifest.py` | yes | rolls per-demo stats up to the pool headline + dm3 filter |
| `selfpov_4on4_demolist.tsv` | yes | the 472 `player<TAB>filename` self-POV-4on4 rows fed in (from the census TSV) |
| NDJSON frame shards | **no** | 9.1 GB; live in WSL `~/move_bc_shards/` (outside the repo tree — cannot be staged) |

## Reproduce (WSL2, per the machine hosting policy — demos + heavy compute there)

```bash
# demo list: player<TAB>abspath for the 472 self-POV 4on4 dm3 demos
#   (420 in ~/ctv_decomp/, 52 raw .qwd in /mnt/c/.../challenge-tv-archive/stage_dm3/)
cd /mnt/c/Users/benya/projects/quakeworld/komodobots-ml
python3 experiments/stage2/move-bc-dataset/build_move_bc_pool.py \
    --demo-list ~/move_bc_demolist.tsv \
    --shard-dir ~/move_bc_shards \
    --manifest  ~/move_bc_pool_manifest.json \
    --workers 14
python3 experiments/stage2/move-bc-dataset/aggregate_manifest.py \
    --manifest ~/move_bc_pool_manifest.json \
    --out experiments/stage2/move-bc-dataset/manifest.json
```

## Provenance

- Corpus: Stage-0 spike-3 self-POV census
  (`experiments/stage0/data-census/self_pov_per_demo.tsv`, klass=self_pov ∧
  mode=team/4on4 → 472 rows). Decompressed challenge-tv archive.
- Physics / label integrity: `scripts/pmove_sim.py` (validated MVDSV port) +
  `scripts/bsp_geom.py`, dm3 BSP `C:\nQuake\qw\maps\dm3.bsp`
  (md5 `f8a1ae80ed1ff36d01903c1eb98ee2f6`). Per-demo `source_sha256` in the manifest.
- Extraction: `scripts/build_replay_command_file.py` +
  `tools/qwd_usercmd/qwd_usercmd.py`.
- No model training (no torch) — dataset construction + validation only.
