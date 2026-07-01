# Execution plan — D1 + D3 + D5 (owner-approved 2026-07-01; auditor + nblm PRE-FLIGHT applied)

Vision: the strongest **information-honest** superhuman movement bot, validated **route-first** (docs/28 —
NOT human-imitation, NOT speed-capped). Owner said YES to all three; this is the corrected HOW after the
pre-flight review. Backtrack-ready per-decision detail in `plans/phase2-next-step-decisions.md` (D1/D3/D5).

**Review sign-off (2026-07-01):** auditor (code-truth vs origin/main `da344d5`) + nblm (principle). Both
converge that the plan is right in shape; the auditor found concrete errors (now folded in below) and the
plan was **NOT execution-ready as first written**. nblm's load-bearing addition: the offline sim-grade is the
fast internal instrument — a "superhuman" CLAIM still needs a **live recorded run + `pov_fuse` visual check**
(docs/28's "no success claim without a recording"), never the offline grade alone (sim-to-real / reward-hack risk).

---

## D1 — wire the honest route-grade onto the PPO rollout (the "honest judge")

Add a `--grade-route` mode to `ml/eval_broad_closedloop.py` that runs the PPO self-yaw checkpoint through the
pmove sim and grades each route with `grade_trajectory` (on-route + faster-than-human + clean-mechanism +
completed-route). **Strictly additive.** Fresh `/tmp` worktree off `origin/main` (working tree behind at
`f6d571c`). Torch-side → **CI-only** on aws-dev (validate via `py_compile` + reading + stdlib tests).

Edit set (corrected by audit — trust the code, the `closed_loop_rollout` docstring `:632-634` is stale):
1. **Return tuple 6 → 7** (currently `:780`: `gmv_ticks, origins, speeds, msecs, attack_classes,
   fwd_press_frac`). Add the per-tick trajectory list as the 7th element.
2. **Per-tick collect** at the append site `:765-768`: `vx,vy,onground` are ALREADY in the tick
   (`gmv_tick_from_state:204-207`); only **`oz`** (`st.origin[2]`, `:763`) and **`fwd_am`** are new.
   `fwd_am = pred_cls[0]` (the press CLASS) is defined only inside the policy branch `:740` — thread it out to
   the append site; the `recorded` controller has no `pred_cls` → store `None` (its traj is unused).
3. **BOTH unpack statements 6 → 7** — `:883` (policy) AND `:884` (recorded). Missing `:884` raises ValueError.
4. **Route per segment** — build inside the `for (eid,start,seg)` loop `:875`, mirroring `rl_onspeed.py:267-272`
   (`polyline=[(ox,oy,oz)]`, `speeds=[hypot(vx,vy)]`, `total_len` 3-D). Grade ONLY the policy traj (not the
   `recorded` positive control).
5. **New `--grade-route` report section** — additive to the `run_eval` dict `:942-1008`; does NOT touch the
   `bot_policy`/`gmv`/`fwd_press_frac` keys the RL loop reads (`rl_onspeed.py:924-927,:986-988`). No `docs/25` change.

⚠ LANDMINE: never remove/replace the G-MV battery `run_eval` returns — the RL loop reads its gates live
(`eval_metric_vector:986-997`, `_eval_press_screen:923-927`); removing = silent cross-module break, no local
test catches it (no torch here). ADD alongside.

The 3 caller-side guards + 2 that live in already-merged code (audit split — they are NOT uniform wiring):
- **(iii) TOP RISK — truncate the graded window at arc-coverage ≈ 1.0 (caller-side).** The rollout runs a
  FIXED `len(segment)-1` ticks (`:670`); a genuinely faster bot reaches the human route-end early and overruns
  → horizontal RMSE inflates → `on_route` FALSE-FAILs *exactly the superhuman behavior docs/28 certifies*.
  Silent misgrade = the #466 analog (a judge that penalizes the target). Track arc per tick, cut at ≈1.0.
- **(iv) drop low-`v_ref` ticks BEFORE grading (caller-side).** `route_speedup` returns `ratio=0` when
  `v_ref≤1e-6` (`reward_onspeed.py:133`); merged `route_grade`'s median (`:146`) INCLUDES those 0-ratio ticks
  and does not winsorize → depresses the median → FALSE-FAIL `faster_than_human`. Pre-filter in the caller.
- **(i) fwd_am as CLASS / (ii) grade PER SEGMENT then aggregate** — caller-side, as before.
- **(v) self-intersecting routes** — `project_onto_polyline` picks the GLOBAL-nearest segment
  (`route_geom.py:64-71`), no monotonic constraint, and the REWARD uses the same projection. A grade-only fix
  breaks "ratio == reward by construction". **Resolution: declare the Route-Canon Highways non-self-intersecting**
  (guard moot) — VERIFY against the actual Highway data; if any Highway self-intersects, fall back to a windowed
  projection in SHARED `route_speedup` + re-validate reward parity (bigger change, avoid unless forced).

Testability: `grade_trajectory`/`route_geom`/`reward_onspeed` are pure stdlib and already gate on aws-dev
(`tests/test_route_grade.py`, `tests/test_reward_onspeed.py`). Extract the per-segment aggregation as a pure
stdlib helper → new gating test in `tests/`. **The torch CI smoke MUST drive `run_eval` end-to-end with
`--grade-route`** (exercises both `:883`/`:884`) — a smoke that only calls `grade_trajectory` on synthetic data
would miss the `:884` ValueError. PR as coder (NO merge, NO gate label; Codex auto-reviews).

**Honesty framing (nblm):** this offline grade is the fast internal instrument that de-circularizes training
decisions. It is NOT the superhuman CLAIM — that needs a live recorded run + `pov_fuse` visual check
(owner-gated), per docs/28's recording mandate. State this in the report output so a green offline grade is
never mis-read as "done".

---

## D3 — anchor-off training run on pinnacle (remove the "act human" leash)

Runtime flags, no code change. Remove the leash =
- **`--kl-coef 0.0`** — drops the whole believable-aim anchor term from the PPO loss (`:593`; the term is
  `kl_anchor = kl_disc + kl_yaw`, `:591` — both drop, NaN-safe; the yaw leash is `kl_yaw:590`).
- **`--kl-anchor-ceiling 1e9`** (effectively +∞) — the ceiling does NOT only early-stop (`:755`); it also gates
  best-ckpt **eligibility** (`on_manifold = kl_anchor ≤ kl_ceiling`, `:732`, used in the default select path
  `:736`). With `kl_coef=0` the policy drifts and `kl_anchor` grows unbounded → a merely "raised" ceiling makes
  the late reward-best iters INELIGIBLE and the run saves an early, low-reward ckpt. Set it so no iter is filtered.
- **Do NOT pass the opt-in believability/press/launch selectors** — `--select-legacy-believable` (`:1218`),
  `--select-by-eval-press` (`:1225`), `--select-launch` (`:1274`); all re-introduce a pull that fights anchor-off.
  Default selection is reward-return (`:736-737`, `saved_params="best_phase2_reward":882-884`) — CONFIRMED correct.

Run on pinnacle (`ssh pinnacle-gpu`; env `/home/xerial/rl-onspeed`; warmstart the round-6 ckpt — **confirm the
exact `--init-ckpt` filename on pinnacle before launch**, it's a pinnacle artifact not in the repo), autonomous,
save everything. The resulting checkpoint is D1's end-to-end smoke-test fixture. Guardrail: no "better" claim
until D1 grades it (R5's 0.315 is the circular reward-return). Live-MVD publish stays owner-gated.

---

## D5 — reconcile the imitation-framing across the program docs (fix the self-contradiction)

`docs/28:64-65` (*"grade its trajectory objectively and instantly by MSE / RMSE against the elite-human ground
truth"*) reads as pure imitation. Fix to grade on **route-shape adherence (staying on the Highway) AND
faster-than-human speed**, mirroring the honest 4-criterion grade + the phrasing that ALREADY exists at
`docs/02_SOURCE_MAP.md:1143` and `docs/08_DECISION_LOG.md:4032/4045/4085`.

**Minimal COMPLETE in-doc set (audit correction — my "leave `:93/:96/:127`" was wrong):** also reconcile the
MSE token at `docs/28:67` ("MSE is the objective gate"), `:93` ("route-isolated MSE/RMSE"), `:96` ("graded by
MSE/RMSE"), `:127` ("route-isolated MSE) — KEEP each line's separate *no-4v4 / route-isolated* semantics, only
retire the "MSE-vs-human is the gate" claim.

**⚠ OWNER SCOPE CALL (surfaced by audit invariant #1 — goal anchoring):** the same "MSE vs elite-human is the
gate" claim ALSO stands in the **North Star `docs/00:66`, the data contract `docs/25:33`, and `AGENTS.md:41`**.
Fixing only `docs/28` relocates the contradiction. Recommend the WIDE fix (one sentence each, all four docs) so
the drift is killed everywhere. Narrow (docs/28 only) + a recorded parity follow-up is the alternative. Owner decides.
Own small docs PR; backtrack = `git revert`.

---

## Sequence
D1 build (aws-dev) ∥ D3 training run (pinnacle) — independent, both start on the owner's nod. D5 docs PR
alongside (pending the scope call). D1's grade then reads the D3 checkpoint → the honest OFFLINE verdict on
anchor-off; the superhuman CLAIM waits for the owner-gated live recording.

## Done-criteria
- **D1:** stdlib floor green incl. the new aggregation test; `py_compile` clean; guard (iii) truncation +
  guard (iv) pre-filter present; torch CI smoke drives `run_eval --grade-route` end-to-end; PR opened.
- **D3:** run launched on pinnacle with `--kl-coef 0.0 --kl-anchor-ceiling 1e9`, no opt-in selectors; logging
  `r_vel`; checkpoint retrievable for D1.
- **D5:** all "MSE-vs-human is the gate" claims in the chosen doc set read honest (route + faster-than-human),
  no dangling contradiction.
