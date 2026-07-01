# B1 — Wire the honest #428 route-grade into RL checkpoint SELECTION (the #428→#429 bridge)

_Pre-flight reviewed 2026-07-01 by **auditor** (code-truth vs origin/main @ `fe2f250`: SOUND-WITH-FIXES) +
**NotebookLM** (honesty: Goodhart risk, held-out routes required). All must-fixes folded below._

## Why now (code-true)
docs/28 pivot = route-first, information-honest **superhuman** (NOT believable). #428 (merged #471) made the
offline route-grade TRUSTWORTHY — `faster_than_human` judged RELATIVE to the sim-human control (verified on real
dm3 2026-07-01: R5 anchor-off **0.08 / 0-of-12** vs recorded-human control **0.49**). BUT on origin/main RL
training SELECTS its saved checkpoint by the **in-rollout #427 reward RETURN** (`score = mean_reward`,
`rl_onspeed.py:736-738`, sorted+saved `:746-750`) — i.e. it selects by the very reward it trains on = **circular**.
(Believability `--select-legacy-believable` and the eval-press screen `--select-by-eval-press` are OPT-IN legacy,
OFF by default.) The honest route-grade is fed into NONE of them — it exists only in eval's `--grade-route` report.
That circularity is what #429 must optimise against: you cannot tune `w_press` against the honest metric if
selection ignores it. **B1 makes selection able to pick by the honest grade.**

## Scope: B1 is the UNBLOCKED bridge; B2 (full #429) is gated
- **B1 (this plan):** a new selection MODE that ranks the retained snapshots by the honest grade. No new upstream dep.
- **B2 = #429 proper** (Bayesian/Random HP-search over `w_press` etc., graded by B1's metric): additionally needs
  **#426 (T4.2 experiment-tracking, OPEN)**. Named + deferred, not silent.

## Design (surgical, additive, reversible — mirrors the existing ROUND-4/7/8 lever pattern)
1. **New selection mode `--select-by-route-grade`** parallel to `--select-by-eval-press` /
   `--select-legacy-believable`. NOT a rip-out — the reward-return default + legacy paths stay for A/B.
2. **Reuse the screen's existing rollout (crux — auditor CONFIRMED).** `run_eval(grade_route=True)` already computes
   `report["route_grade"] = {summary, recorded_control, per_segment}` INSIDE itself (`eval:823, 911-940, 1060-1064`)
   from the `p_traj`/`r_traj` the rollout already produced — **zero new rollout, zero RNG perturbation** (grading is
   pure stdlib math), and the human-ref route is built from the segment itself (no new input data). The change is
   NOT one line — `_eval_press_screen` (`rl_onspeed.py:895`) today calls `run_eval` WITHOUT `grade_route`
   (`:915-922`) and returns a fixed **4-tuple** `(ep, m1, m6, launch)` (`:950`) that **drops** `rep["route_grade"]`;
   its sole call site unpacks exactly 4 (`:794`). **B1 must:** (a) pass `grade_route=True` in that `run_eval` call;
   (b) extend the screen return to also carry `rep["route_grade"]["summary"]`; (c) update the `:794` unpack; (d) add
   the `--select-by-route-grade` ranking branch.
3. **Ranking comparator** (the one bit of real logic → EXTRACT to a stdlib-pure function so it gates in the floor).
   Among the retained snapshots, pick the highest honest grade. **Primary key `seg_faster_frac`** — the auditor
   confirms this is the ONLY per-candidate *relative* signal (fraction of segments beating their own sim-human
   control). Tie-break: `median_speedup_ratio` (NOTE: this is the median of per-segment **absolute** along-route
   speedup, not control-normalised — label it honestly; a control-normalised tie-break would be
   `median_speedup_ratio / median_human_ref_ratio`, both present but derived), then lowest `median_route_rmse_qu`.
   **Guards:** `relative_ref_invalid`/`relative_ref_degenerate` segments are already excluded from the
   `seg_faster_frac` numerator upstream (`route_grade.py:186-191,281`) → no phantom passes; the comparator must not
   ADD rounding (the raw-compare guard already lives per-segment in `grade_trajectory:189-193`; there is NO
   unrounded AGGREGATE to compare, so "compare unrounded" language is dropped); `superhuman_claim` stays **false** —
   RANKING to de-circularise selection, NOT a superhuman claim (that still needs the live engine + pov_fuse, docs/28).
4. **HELD-OUT selection routes (nblm MF-N1, KEY anti-Goodhart).** The grade MUST run on routes DISJOINT from the RL
   reset segments, else selection rewards route-memorisation. Risk is REAL: the screen's `run_eval(split=args.split)`
   (`:915-922`) uses the SAME `split` `build_segments` draws the RL reset segments from (`:696-697,712-713`). Fix:
   grade selection on a held-out set — a disjoint split or an explicit held-out route list — mirroring how
   `reward_band_disjoint` already reserves disjoint players for the reward band. The comparator ranks on the
   HELD-OUT grade. (New flag, e.g. `--select-grade-split`/held-out route list; default to the disjoint reserve.)
5. **Full segment count + valid-ref floor (auditor SF-4).** For `--select-by-route-grade`, grade over the full
   `--eval-segments=12` (NOT the 8-seg screen default `:1270`) so `seg_faster_frac` isn't 1/8-coarse; and require a
   minimum count of VALID-ref segments (`n_segments − n_ref_invalid − n_ref_degenerate`) or fall back, since
   invalid/degenerate sim-human controls structurally cap the achievable fraction.
6. **Control PURITY (nblm MF-N2).** The relative baseline must be pure base movement: check whether a trick-jump /
   trick-route anomaly signal already exists for the control episodes; if so, gate on it (refuse a trick-contaminated
   control beyond the off-route/degenerate cases already guarded); if not, NAME it as a follow-up, don't silently
   trust a possibly-trick control.
7. **Candidate pool is explicit (auditor SF-5).** `--select-by-route-grade` re-ranks the reward+KL-eligible top-K
   (`:737-747`); it cannot recover an honest-best snapshot that never entered top-K. Expose/​widen `K`
   (`--topk-snapshots`) so the honest optimum isn't pre-excluded by the reward pre-filter.
8. **Provenance:** the chosen candidate records its honest grade summary + `n_segments`/`n_ref_invalid`/
   `n_ref_degenerate` in the run meta (evidence chain for #426/#429 later).

## Scope guard (named, not silent)
- NOT B2/#429: no HP-search script (gated on #426).
- NOT a training-reward change: grade-only SELECTION. Auditor CONFIRMED selection runs POST-training (save-only:
  `rl.base.load_state_dict(sel["sd"])` → `save_rl_ckpt` → `train()` returns; NO rollout/ppo_update after) → **zero
  training-parity risk**. Enabling `grade_route` is an additive offline eval-only consumer.
- NOT removing the reward-return default or the legacy paths: kept behind their flags for A/B.

## Verification
- **stdlib floor green:** the extracted ranking comparator + a gating test (a worse honest grade never beats a
  better one; a `relative_ref_invalid`-heavy candidate cannot win on phantom passes; `superhuman_claim` stays false;
  the comparator adds no rounding). torch-side wiring validated via `py_compile` + reading (no torch on aws-dev).
- **Data-contract:** no extraction/feature/training-data change → no contract move. It changes SELECTION semantics →
  ML-reviewer evidence-chain lens applies; pre-empt failure-classes (1)-(5).
- **Pinnacle smoke (autonomous OK):** short training with `--select-by-route-grade` on a held-out split; confirm it
  selects by the honest metric + writes it + the ref-counts to the meta; sanity that a faster-on-route candidate
  ranks above a slow one.

## Implementation discipline
/tmp worktree off fresh origin/main; stdlib-gated comparator test; `LOGGER=`; use EXACT origin/main line refs
(`_eval_press_screen:895`, run_eval call `:915`, selection region `:723-857`); coder role (open PR, never
merge/label/resolve); Codex auto-reviews; commit trailers + session line; PR body says **"does not finish #429"**.

## As-built note (divergence from auditor MF-A1)
The auditor confirmed the grade could ride `_eval_press_screen`'s existing `run_eval` call with ZERO new
rollout. But nblm MF-N1 (held-out routes) forces the selection grade onto a segment set DISJOINT from the
training resets — which the press screen (training-overlapping HEAD) cannot supply. So B1 adds a DEDICATED
`_route_grade_screen` that grades the held-out SUFFIX (`select_start_segments(skip=n_reset_segments)`), one
rollout per candidate. Held-out correctness (KEY guard) outranks the zero-rollout efficiency the shared call
would have bought; `_eval_press_screen` is left untouched (its 4-tuple + call site unchanged), which is lower
risk than the shared-call threading MF-A1 anticipated. Landed via `--select-by-route-grade`.

Review fix: `_route_grade_screen` selects the held-out suffix with the same segment-load horizon
as the reset pool (`--horizon`), not the rollout episode horizon (`--ep-horizon`), so
`skip=--n-reset-segments` skips the exact qualifying prefix training can reset from even when those
CLI knobs differ.
