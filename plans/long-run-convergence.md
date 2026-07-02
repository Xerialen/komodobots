# Long-run convergence probe (Phase 2, post-#429) — the first convergence datum under the honest objective

## Decision (owner-approved 2026-07-02)

Question put to both reviewers (auditor = code-truth vs origin/main; NotebookLM = methodology,
grounded on the program docs): *cost/time ignored, which single next step most likely moves the
program toward the docs/28 goal?* Verdict: **train the sweep winner LONG** — no run in this
program's history has exceeded ~360k env steps under ANY objective (rounds 1–3: 149k/360k/45k;
rounds 4–8 unrecorded; everything since = exactly 200k), and the 20260702b sweep exhausted the
hyperparameter plane at fixed 200k (all 42 runs seg_faster_frac ≈ 0.08–0.17). A fixed-tiny-budget
sweep structurally cannot distinguish "reward geometry wrong" from "not converged"; only a long
run can. The historical round-8 "plateau at ~273" is NOT a speed ceiling — it was reached under a
reward that penalised speed above 316, with the believability anchor ON, and is flagged
"indicative" in `docs/notes/rl-onspeed-results.md`.

The one part of a long run that canNOT be repaired afterwards is what the weights trained on:
30 val reset segments × millions of steps is a memorization exposure. Hence the **`--reset-split`
change lands first** (this PR): training resets move to the TRAIN split; the whole val pool (54
qualifying episodes) becomes grading material (ranking + tertiary up to 27 + 27, halving the
1-segment quantization that spanned the sweep's whole dynamic range). Mis-measurement, by
contrast, IS repairable post-hoc: the grade never feeds the training gradient (selection/verdict
only) and its bias is conservative (invalid/degenerate refs can hide progress, never fabricate
it), so instrument refinements can re-grade saved checkpoints later.

Ordering constraints adopted from the reviews: reward iteration (#427 / the parked D7
potential-based shaping — NOT cadence credit) is only meaningfully evaluated AFTER a convergence
datum; NotebookLM's guard is folded in as milestone behavior inspection (reward-hacking check)
rather than instrument-first sequencing, whose premise the code audit refuted.

## Run spec (pinnacle, autonomous per gpu-on-pinnacle-ok; offline pmove sim only)

- Config: the 20260702b verified winner `aa1aaf5477a9` — lr 1.77e-4, clip 0.2373, kl_coef 0.0 +
  kl_anchor_ceiling 1e9 (anchor OFF), ent_coef 1.08e-4, minibatch 768, w_press 2.516, ppo_epochs 4,
  n_envs 12, rollout 256, horizon/ep_horizon 385, init `rl_round6_r4init.pt`, seed 1003.
- New: `--reset-split train` (pool measured BEFORE launch: `build_segments(db, "train", coords,
  385, 99999)` — the sweep-1 lesson), `--n-reset-segments` sized to that measurement,
  `--select-grade-segments` up to 27 on val offset 0.
- **Staged**, not one shot: ~2M steps per stage, each stage `--init-ckpt <previous stage out>`,
  each stage journaled (#426) + route-grade-selected (#472). Milestones give the learning curve;
  a crash loses one stage.
- Per milestone: honest route-grade (ranking chunk) + the never-ranked tertiary chunk
  (`--select-holdout-offset <grade_segments>`) + behavior inspection of the selected checkpoint
  (route plots / eval JSON — does speed come from the air-strafe mechanism or a reward hack?).
- Verdict semantics unchanged: relative to the sim-human control, `superhuman_claim: false`
  hard-coded; an absolute claim still requires the live engine + recording (docs/28).

## What the datum decides

- Grade keeps climbing well past 200k → the sweep's per-trial budget was the binding constraint;
  re-run the tuning loop at the bigger budget.
- Grade plateaus at ~0.15 at millions of steps → evidence-backed unlock for the reward track
  (#427/D7), which then inherits both the instrument and this baseline.
