# Phase-2 movement RL — decisions & how to backtrack (post-#427 / #466)

Owner asked for a clear log of the decisions we are taking so any of them can be **reversed** if it
proves wrong. Each entry: **Decision · Why · Status · How to backtrack**. Reviewed by the auditor
(origin/main) + NotebookLM 2026-07-01. Vision anchor: docs/28 — information-honest, **superhuman**,
route-first validation (NOT human-imitation, NOT speed-capped).

Status legend: **LANDED** (on main) · **PROPOSED** (recommended, awaiting owner) · **OPEN** (pending work).

---

## D0 — LANDED baseline (already reversible via git)
- **#427** reframed the reward to information-honest superhuman (option C); **#466** closed the
  `+forward` ground-bulldoze loophole (r_press now bites forward-at-speed on ground too). Both merged.
- **Backtrack:** `git revert` the squash commits (#427 `842b7d0`, #466 `8bac432`); the reward is a pure
  stdlib module behind `--reward-weight`, so weights are also runtime-reversible without a revert.

## D1 — Grade the PPO policy with an OFFLINE route-grade on the pmove-sim rollout — NOT #464's live path
- **Decision:** build the route-completion grade by extending `ml/eval_broad_closedloop.py` to score the
  **PPO checkpoint** in the offline pmove sim (the same sim the reward runs in) against the #420 seed line
  + the #428 route metric — instead of using #464/#428's directed `--score` path.
- **Why:** the auditor verified (origin/main) that `--score` drives the **frozen 6-feat BC mover**
  (`prewar_movecheck.py` → `move_bc_policy.pt`), **not** the PPO policy, and there is no PPO→live bridge
  (`T5.2:276-277`). #464's own scoping calls its metric "degenerate-by-design" until the movement brain
  replaces the BC mover. So #464 would grade the wrong model; the offline sim-grade de-circularizes the
  actual training decisions, reproducibly, with no serving bridge.
- **Status:** PROPOSED (this is the recommended next build; owner go requested).
- **Backtrack:** it is an **additive** new eval mode (no data-contract/model change). If the offline grade
  proves unrepresentative of live behavior → stop using it and fall back to standing up the PPO→live bridge
  (separate ticket) + #464's live path. Reverting = delete the eval mode; nothing else depends on it.
- **Impl note (scoped 2026-07-01) — ⚠ SUPERSEDED; see WIRING SCOPE below (crux was INVERTED; kept for backtrack audit):** ADAPT, don't green-field. `ml/eval_broad_closedloop.py` (1150 ln)
  ALREADY runs the closed-loop rig (seed `pmove_sim.PlayerState` → policy 5 heads → usercmd → step → feed
  back) and has `route_metrics` / `aggregate_route_metrics`. It's built for the FROZEN BC mover (analytic
  `optimal_strafe_yaw`, no view head) graded by the G-MV believability battery + a path-length/anti-stall
  proxy. D1 = (a) drive the **PPO self-yaw policy** (it has its own view) instead of BC+`optimal_strafe_yaw`;
  (b) replace the believability battery + path-length proxy with the **honest route-grade (D2)**: route-shape
  MSE vs the #420 human seed line + faster-than-human (`v_along/v_ref>1`) + press-fraction/air-vs-ground.
  Worktree: `/tmp/wt-d1-routegrade` off origin/main.
- **STATUS (2026-07-01):** the GRADE-MATH CORE is landed + gating-tested — pure-stdlib
  `experiments/route_observatory/route_grade.py` (`grade_trajectory`: the 3-criterion honest gate; reuses
  `route_geom` + `reward_onspeed.route_speedup` so the gate's ratio matches the reward's) + 8 stdlib tests
  in `tests/test_route_grade.py`, incl. `test_r5_hybrid_fails_despite_low_rmse` (proves the paired criteria
  catch the hybrid route-MSE-alone passes). Full floor green (1894 OK). FOLLOW-UP increment: wire it into
  `ml/eval_broad_closedloop.py` to drive the PPO self-yaw ckpt through pmove_sim (torch-side, CI-only).
- **WIRING SCOPE — auditor + nblm reviewed 2026-07-01 (crux INVERTED; the build is SMALLER than an "increment", not bigger).**
  The impl-note's "built only for the frozen BC mover / PPO forward-pass not reachable" fear is FALSE:
  `ml/eval_broad_closedloop.py` ALREADY loads + steps an `rl_onspeed` PPO **self-yaw** ckpt — `run_eval` →
  `_build_policy_from_checkpoint` (`eval_broad_believability.py:488-525`, reads `yaw_head`, strict-loads `state_dict`)
  + `closed_loop_rollout(aim_mode="policy")` (`:729-737`, `forward_with_yaw` → integrates `policy_yaw`), and that exact
  path runs in PRODUCTION today from the RL loop (`rl_onspeed.py:978-985`). `optimal_strafe_yaw` (`:160`) is a SEPARATE
  analytic overlay (`aim_mode="optimal"`), NOT the BC mover; the frozen 6-feat mover is the serving-path
  `move_bc_policy.pt`, never loaded here. So NO new policy-runner, NO obs re-featurization, ONE obs-space/norm-artifact.
  **The true increment = 3 additive pieces:** (1) per-tick collect `{ox,oy,oz,vx,vy,onground,fwd_am}` — all already in the
  loop; only `oz` + `fwd_am` (= the press **CLASS** `pred_cls[0]`, NOT the magnitude) need storing; return as a 7th element
  from `closed_loop_rollout` (`:625`; only unpack site = `run_eval:883-884`, and `rl_onspeed` calls `run_eval` not
  `closed_loop_rollout`, so it is insulated). (2) build the `route` (`polyline`/`speeds`/`total_len`, 3D) from `seg["self"]`
  — code already exists at `rl_onspeed._reset_state:267-272`, the SAME route `route_speedup` consumes → grade's ratio ==
  reward's by construction. (3) call `grade_trajectory` as a NEW `--grade route` report section.
  **⚠ THE ONE LANDMINE — ADD alongside, do NOT remove/replace the G-MV battery inside `run_eval`.** Its gates are read LIVE
  by the RL loop's checkpoint selection (`eval_metric_vector:986-997`, `_eval_press_screen:923-927`); removing them = a
  SILENT cross-module break with NO local test catch (no torch on aws-dev). This is the ONLY reason D1's "delete the mode"
  backtrack rule holds — it holds iff we ADD, never SWAP. (Corrects the impl-note's wrong "(b) replace the believability battery".)
  **5 misgrade traps to code right (else false PASS/FAIL):** (i) `fwd_am` as CLASS not magnitude — else `clean_mechanism`
  always-passes (the #466 analog); (ii) grade PER-SEGMENT then aggregate — pooling injects a teleport at each seg join;
  (iii) terminate the graded window at arc-coverage ≈1.0 — else a genuinely superhuman run overruns the human route-end,
  RMSE inflates, and the gate FALSE-FAILs the behavior docs/28 WANTS; (iv) guard the ratio near `v_ref≈0` (ratio=0 ticks
  drag the median → false FAIL; tiny-nonzero → blowup → false PASS); (v) monotonic/windowed arc projection on
  self-intersecting dm3 routes (nearest-segment snap can pick the wrong arc). Build in a fresh `/tmp` worktree off
  origin/main (working tree is behind at `f6d571c`; the `route_grade`/`reward_onspeed`/`route_geom` files exist only on origin/main).
- **SEQUENCING (both reviewers converge): D1-wire (aws-dev, now) ∥ D3 anchor-off training (pinnacle, autonomous) — D1
  GATES the conclusion.** They don't block each other (training-compute is autonomous on pinnacle; D1 is CI-only on
  aws-dev); the D3 anchor-off ckpt doubles as D1's end-to-end smoke-test fixture. The only hard ordering is
  INTERPRETATION: do NOT claim anchor-off "better" until D1's honest grade confirms it (R5's 0.315 is the circular
  reward-return, Codex-BLOCKed non-reproducible). Supersedes the auto-memory `phase2-reward-reframe.md` "proof-run first" line.

## D2 — Honest gate = route-shape MSE **+** faster-than-human **+** press-fraction/air-vs-ground (+ visual)
- **Decision:** the pass criterion is NOT route-MSE alone. It is: (a) route-shape adherence (MSE) as a
  floor; (b) a **faster-than-human** criterion — lift the reward's `v_along/v_ref>1` ratio INTO the gate,
  replacing G-MV4's two-sided band with a **≥human floor that keeps crediting above**; (c) a
  **press-fraction / air-vs-ground** mechanism check so a bulldoze-hybrid is separable from clean bhop at
  equal speed; (d) a `pov_fuse` visual-integrity eyeball.
- **Why:** both reviewers — adherence-MSE is **speed-blind** (`route_eval.py:6`), so R5's non-bhop
  forward+strafe hybrid (fwd_press 1.0, hspeed 151) hugs the line and scores GOOD MSE. Velocity is only a
  reported scalar with no faster-than-human comparison; the eval gate has exactly the hole #466 just closed
  in the reward.
- **Status:** PROPOSED (part of D1's build).
- **Backtrack:** each sub-gate is an additive, config-flagged term. If the faster-than-human floor passes
  nothing → relax to ≥human−ε. If the press-fraction check misfires → disable that term. Fully tunable.

## D3 — DECISION B: remove / loosen the believability KL-anchor
- **Decision:** drop (or loosen) the KL-anchor to the believability-era warmstart in PPO training.
- **Why:** its stated purpose is "so believability holds" — a **superseded** docs/18 goal; PPO stability
  already comes from the per-step `target_kl` trust region; R5 (anchor OFF) scored best. Keeping a
  superseded-goal anchor in an info-honest-superhuman program is itself drift; removing it is
  drift-correction. Auditor: the *removal* is a legitimately independent fix, NOT a shortcut past the
  ticket order.
- **Status:** PROPOSED, **OWNER-GATED** (architecture decision). Recommendation: remove.
- **Backtrack:** it is a **CLI flag** (`--kl-anchor-ceiling` / anchor on-off), per-run. Re-enable by
  restoring the flag and re-anchoring to `rl_round6_r4init.pt`. Fully reversible run-to-run.
- **GUARDRAIL:** do NOT market anchor-off as "better" until **D1**'s honest grade confirms faster-honest
  route completion — R5's 0.315 is the *circular* reward-return (and was Codex-BLOCKed as non-reproducible).

## D4 — Reframe #464 as Brain-1 measurement hygiene, not the PPO unlock
- **Decision:** #464 proceeds independently and non-blocking as measurement-spine hygiene for the *eventual*
  route-first validation of the frozen Brain-1; it is NOT what unlocks the current PPO training decisions.
- **Why:** see D1 — #464 grades the BC mover, and its own tickets already record it as degenerate-by-design.
- **Status:** OPEN (independent).
- **Backtrack:** pure labeling/sequencing; re-prioritize #464 if D1's offline grade turns out to need the
  live path after all.

## D5 — Reconcile docs/28's validation sentence to "route-shape AND faster-than-human"
- **Decision:** edit docs/28:65 — "grade its trajectory objectively by MSE/RMSE vs elite-human ground
  truth" — which reads as pure **imitation** and contradicts the superhuman goal; reconcile to
  "route-shape adherence AND faster-than-human speed".
- **Why:** auditor drift finding — the north-star's own validation sentence contradicts the north-star's
  superhuman goal, and the code silently worked around it (which is why eval lacks a faster-than-human
  criterion). Root cause of the D2 honesty gap.
- **Status:** PROPOSED, **OWNER-GATED** (program-of-record).
- **Backtrack:** a doc edit; `git revert` the doc PR.

## D6 — First-jump `+forward` reward shaping (DESIGNED + adversarially repaired — workflow `first-jump-forward-reward`)
- **Question (owner):** what reward/penalty credits `+forward` at the START (initial ground accel + first
  jump) but NOT once bhopping — **without** the bot just standing still?
- **Grounding (workflow, all verified):**
  - **Physics:** `onground` is the accel-law gate — the exact engine branch (`pmove.c:512`) where the
    wishspeed cap flips **320 (ground) → 30 (air)**. A velocity-aligned `+forward` accelerates only below
    **30 qu/s** and adds **exactly 0** above it; airborne speed must come from perpendicular strafe + view
    turn. The first jump launches at ≥320 ≫ 30, so forward is worthless from airborne-frame-1.
  - **QWD action oracle (5 pros, 478 local `ctv_decomp/` demos, ground-truth forwardmove):** humans hold
    `+forward` from standstill through the ground circle-jump AND the first jump, then **release it at
    median 453 qu/s** (the ground→air boundary): fwd-held fraction 55–59% at 320–450 qu/s → 24% at 450–500
    → ~2% at 500+. docs/27 §4.1 confirms forward→0 in the bhop regime (≥400 qu/s) costs only ~1.5–5% speed.
    **Mechanism grounding, NOT an imitation target** (docs/28 = superhuman).
- **Decision (post-adversarial):** the honest "early vs late" gate is **whether forward is PRODUCING SPEED
  GAIN (`ds>0` / `r_phi_raw`), NOT instantaneous speed and NOT a free-ground-pass.**
  - **CREDIT side — no change:** the existing **`r_phi`** already credits *realized* ground speed-gain
    (only `PM_Accelerate` produces it); un-gameable (standing → `ds=0` → 0), self-limiting near 320. It
    already credits the pre-jump build + the launch. So "+forward at the start is credited via its
    OUTCOME," not the button.
  - **PENALTY side — re-gate, do NOT free the ground:** penalize the forward *button* when it is **not**
    producing speed gain (steady push, `ds≈0` = bulldoze) at **any** speed/state; genuine acceleration
    (`ds>0`, the launch build) stays free. Set **`launch_grace=0`** (forward is worthless from
    airborne-frame-1; a grace ramp has no physics basis, subsidises the hybrid, and is a latent
    imitation-anchor).
  - **Anti-freeze (sound):** the penalty is gated to the forward *button*, so the escape hatch is "release
    forward + strafe" (penalty-free + full speed credit), **never** "stop." Pure-strafe dominates freeze at
    every state. (The design's "+0.9, 90×" margin was inflated; true steady-state margin ~38×, carried by
    `r_vel` not `r_phi` — still safely positive.)
- **⚠ Adversarial catch (why the naïve design was rejected — MUST heed):**
  1. Setting `g_fwd=0` on the ground **reopens #466**: the policy's whole observed band is 100–156 qu/s
     (R1 156 / R4 ~100 / R5 151), which sits INSIDE the freed 126–320 zone → flips a deterred ground
     bulldoze (−0.21/tick) into an attractive one (+0.39/tick). Hence the `ds>0` re-gate above.
  2. "Shaping alone kills the R5 hybrid" is **false** — the strict-domination proof omitted the along-route
     term (`perp_frac` ⊥ *velocity* ≠ `v_along` ∥ *route*); pure strafe curves off-route, lowering `r_vel`,
     so the local gradient can still favour the hybrid (= R5's exact result). The single-tick equal-speed
     unit test CANNOT detect this (it's a multi-tick trajectory property). **So the penalty must stay ≥ #466
     strength everywhere the policy operates (100–320 qu/s); the STRENGTH that actually kills the hybrid is
     #429 (`w_press`) graded by the route-MSE (D1/#428).** This shaping SUPPORTS #429 (makes the penalty
     phase-correct so `w_press` can rise without a freeze/scrape) — it does **not** replace it.
- **Status:** PROPOSED (design repaired; owner sign-off needed — it would deliberately INVERT the #466
  `test_ground_forward_at_speed_now_penalized`, moving anti-bulldoze onto the `ds>0` condition). Needs an
  origin/main sync before editing (`reward_onspeed.py` not on the local checkout).
- **Backtrack:** additive `--reward-weight`-gated term + 2 `carry` keys (`prev_onground`, `air_ticks` if any
  grace kept) → revert = weight 0 / restore the #466 `hspeed>band_lo*0.5` gate. No data-contract change.

## D7 — [BOOKMARK / PARKED] Does the air-strafe sustain-gap need denser *outcome* credit? (the yaw / m_yaw question)
- **Bookmark (owner, 2026-07-01):** we may need to return here and introduce an explicit **yaw /
  air-strafe-coordination** reward. Parked deliberately — this entry is the marker to come back to.
- **Current state (verified, origin/main):** the policy OWNS its yaw — a **self-yaw head** emits a per-tick
  yaw-delta (deg), integrated onto the executed view-yaw, which drives the pmove wishdir
  (`ml/rl_onspeed.py:6,308–333`). **`m_yaw` (the human mouse→deg sensitivity) does NOT exist in the RL loop**
  — QW usercmds carry absolute view angles, not mouse deltas; there is nothing to reward there. The
  air-strafe mechanism is rewarded ONLY via its geometric **outcome**: `r_phi = perp_frac·r_phi_raw`,
  `r_strafe = perp_frac`, with `perp_frac = 1−(v̂·wishdir)²` crediting only speed earned by wishdir ⊥
  velocity (bulldoze → ~0). **⚠ CORRECTION (auditor, verified `c8b11ed`): yaw is NOT positively unshaped** —
  beyond the `p_hack` spin-penalty, the PPO LOSS carries an ACTIVE believability KL-anchor on the yaw
  (`kl_yaw = (yaw_mean − a_yawmean)²/180²`, `kl_coef=0.05`, `rl_onspeed.py:590-591,1204`) pulling the yaw mean
  toward the believable-aim warmstart. So the yaw is ALREADY shaped — toward *human aim*. Hence **decision B
  (drop the anchor) MUST precede D7** (two opposing yaw shapers otherwise), and this is MORE evidence for B.
- **BOTH reviewers (auditor + nblm): KEEP PARKED — mostly a PHANTOM.** The coordination's *outcome* is
  ALREADY doubly rewarded (a productive yaw raises perp_frac → pays both `r_phi` and `r_strafe`; its sustained
  result pays `r_vel`); a separate yaw term is redundant UNLESS it credits the temporal *sustain* — which is
  exactly the cadence-style prescription that got `r_cad` dropped. The sustain failure is better explained by
  verified levers: `w_press` strength (#429) + the `kl_yaw` anchor (decision B) — and it's UNMEASURABLE until
  D1. **Reframe (auditor):** not "reward the mechanism more directly" (that inverts docs/28's "reward what we
  want, let the agent DISCOVER the mechanics") but *does the gap survive B + #429 + D6, and if so is denser
  OUTCOME credit needed* — only ever as **potential-based** invariant shaping `F = γΦ(s′)−Φ(s)`, Φ(perp_frac),
  never keyed to yaw-rate / hold-length / cadence. **Provenance (auditor):** the R4/R5 decay magnitudes are
  off-repo (only R1 committed, hspeed 156) → treat as indicative, attach the pinnacle log before citing as fact.
- **Why we PARKED it (the caveat):** rewarding a prescribed motion is exactly what `r_cad` did — and we
  DROPPED r_cad (w_cad=0) because it was a believability/imitation anchor that capped performance.
  Outcome-shaping (perp_frac) is the info-honest default; a yaw-coordination term risks re-introducing the
  same over-specification / imitation trap.
- **Status:** PARKED. Return to it ONLY if the honest route-grade (D1) shows the sustain-speed problem
  persists after D6 (phase-correct forward penalty) + #429 (`w_press`) + decision B (anchor off). Evaluate
  against D1, never blind. (Under review by auditor + nblm 2026-07-01.)
- **Backtrack:** additive `--reward-weight`-gated term → revert = weight 0. No data-contract change.

---

### Sequence
D1 (build the offline honest grade) → re-run PPO with anchor-off (D3) **graded by D1** → tune weights (#429)
against D1's metric, incorporating D6's first-jump shaping. D4 (#464) and D5 (docs) run independently.

### Owner decisions currently needed
1. Go on **D1** as the next build (offline, no live-MVD).
2. **D3** — remove the KL-anchor? (rec: yes; removal only, no "better" claim yet.)
3. **D5** — may I make the docs/28 validation-sentence edit?
