# 18 — Bench-iterated human-like DM3 bot program

> **⛔ SUPERSEDED (2026-06-26) by `docs/28_MEGALODON_MILTON_MLOPS_PROGRAM.md`.** The project goal is no
> longer a *believable / human-like* bot judged on a 4on4 bench. It is now the strongest-possible,
> **information-honest** bot (Megalodon Milton), trained by **RL** and validated **route-first**; the 4v4
> bench is demoted to a Phase-4 drift-detection signal. This document is retained as history.

**Status:** SUPERSEDED (was canonical program, greenfield, approved 2026-06-16; superseded 2026-06-26 by
`docs/28`). Supersedes the staged DM3 4on4 stand-in plan, now moved to
`references/12_DM3_4ON4_STANDIN_PROGRAM.md` as background. Register here is deliberately plain ("caveman")
per owner preference; exit criteria and tickets are precise and testable.

## Why we do this
- We want a bot that plays DM3 like a human. Move like human. Aim like human. Think like human.
- All learned from real human demos. Not hand-coded.
- We need a judge. Judge = a match. Team **leap** (our bot) vs team **frog** (stock skill-20 frogbots). 4 vs 4. Count frags. Best of 10–20 games.
- Rule: if a change is real and good, leap wins more. The bench is the boss. The bench says yes or no.
- Win = more **total frags**. To check combat is not broken we use **damage done**, NOT accuracy. You can fake a high LG% by barely shooting. Damage done can't be faked that way. Accuracy = look at it, never gate on it.

## Rules (binding)
1. Fresh start. Old staged docs = reference only, not the plan.
2. Bench judges every change.
3. Lots of machine learning. Little hand-code.
4. Use ALL the data. Map in 3D. Where items are + when they come back. What humans do (QWD = eyes, MVD = god view).
5. DM3 first.
6. Old bunnyhop math helps as input. It does NOT block learning.

## What we already have
- Data: 478 dm3 demos (eyes). Big stats DB ~109k games (god view). Map in 3D (`pmove_sim`). Item spots + timers.
- A bench that runs frog-vs-frog now. We turn it into frog-vs-leap.
- A seam in the server (moveprobe). It can already swap a bot's move, aim, fire.
- One move-brain already trained (MoveMLP). Good seed.

## The brains we build (real ML models)
- Phase 0: NO new model. We use the move-brain we already trained (MoveMLP). Just to prove the pipe. Seed.
- Phase 1: TRAIN a new move-brain. On all demo frames. Richer eyes. Small memory net (GRU/TCN). Real training.
- Phase 2: TRAIN an aim-brain. Turn + shoot. From demos where we now see the enemies.
- Phase 3: TRAIN one brain that does move + aim + shoot together.
- Phase 4: POLISH that brain with RL on the bench. Win more, stay human.
- Where: train on the 4090 (same box as MoveMLP). Imitation learning first (copy humans). Bench picks the best. RL last.
- The bench does NOT replace the model. The model = the brain. The bench = the exam.

## What one DM3 MVD gives (tested — shapes the DECIDE plan)
Ran a real elite dm3 4on4 (Milton's team, 20 min) through the parsers.

**Alfhan's mvdanalyzer (`qw-analyze-v20`) = the CANONICAL source.** Trust this for decisions/economy/combat: frags per player+weapon (WIN), damage given/taken + who-shot-whom matrix (COMBAT gate; Milton 20065 given / 8143 taken — damage-done, no accuracy needed), 51 item kinds with pickup times, a map-control graph (33 named spots, 116 moves, dwell per player/team armed-vs-unarmed), regionControl over time. One limit: no raw per-tick x/y/z — finest place-signal = named spots.

**demopasha / `mimer` = complementary only, treat tentatively.** Use it for the ONE thing the canonical source lacks: **raw x/y/z positions** (86,864 position snapshots; analysis timeline 8 players @ 2 Hz with [x,y,z,alive,health,armor]). It also computes a strategy layer (item_timing, control, coordination, economy) that DUPLICATES mvdanalyzer — cross-check against the canonical numbers, don't rely on demopasha for them. Why tentative: ~2.6k parse errors on this demo + rough fields (zone='unknown', max_speed ~115k).

**So for the plan:** DECIDE/economy/combat signal = **mvdanalyzer (canonical)**; demopasha supplies **complementary raw positions** when we need finer paths, used with caution and cross-checked. The owner's decision vocabulary maps onto mvdanalyzer's named spots + item/control fields. AIM still gets 77 Hz enemy positions from the QWD decode (Phase 2).

## The 3 walls (must break)
1. **Live brain pipe.** Today the seam only plays back canned moves. We need it to ask a live brain each tick.
2. **One world-view.** Built the SAME way offline (training) and live (playing). Or the brain gets confused (train/serve skew).
3. **See enemies in the demo.** Today we skip that. We need it for aim + awareness.

## Build order
First build the base. Same base for any brain:
- **Bench-as-judge** → spits out "leap frags minus frog frags" over best-of-N.
- **Live brain pipe** → new "live mode" in the server + a python brain helper. Test speed first (1 day).
- **One world-view** → one code file, same offline + live, a test proves they match.
- **See enemies** → read enemy spots from the demo. A safety test must pass or we stop.

Then climb the ladder. Each step ends with a bench game. Keep the step only if leap wins more. Imitation first (copy humans). Bench-pick the best. RL last, only to push the top.

DECISIONS (where to go on the map) stay stock-frogbot at first. That part lives before the seam. We learn it only if the bench says we must.

## Phases + exit rules (testable)
Each phase is DONE only when every check passes. Checks are things you can run and see.

### Phase 0 — Base + first live game (seed brain)
Goal: prove the live pipe + world-view match + bench loop, using the brain we already have.
- Live mode works: a bot asks the python brain each tick. Brain slow or dead → bot falls back, does not freeze. (run 1 bot live 5 min: no freeze; screen.log shows live cmds; pause helper → fallback fires clean)
- Speed proven: brain answers each tick under budget (~0.5 ms/tick) for up to 4 slots. (latency log p99 under budget)
- One world-view file. Offline build and live build match on a replayed demo, tick by tick, inside tolerance. (golden-vector test passes, in CI)
- Bench runs frog-vs-leap 4v4 on dm3. Team check green: enemy damage > 0, same-team damage ≈ 0. (R-T damage.matrix gate)
- Bench prints "leap frags − frog frags" over best-of-10 and writes it to the ledger + dashboard. (number shows; repeatable across two runs)
- PASS bar: loop runs honest end-to-end. The number is the baseline to beat — not a win yet.

### Phase 1 — Better move brain (free + rich)
Goal: a freer move brain, trained on ALL frames, richer view. Aim/fire still stock.
- New brain trained on ALL demo frames (drop the ~85% throwaway mask). (train log shows full frame count; split has no demo leakage)
- World-view widened (speed history, map rays, nearest-item) and golden test still green. (parity test passes)
- Best-of-10–20 bench: best new brain beats the Phase-0 number, with a confidence band. (margin up + CI reported)
- Combat not hurt: leap **damage done** not down more than 1σ vs frog baseline. (damage-done check — accuracy is NOT a gate)

### Phase 2 — See enemies + learned aim
Goal: read enemies from the demo, feed them in, swap aim from frogbot to learned.
- Enemy reader works behind a kill-switch. Safety: read SELF from the same stream, must match the known self-path. (self-track regression passes; track counts reported, not hardcoded)
- Enemy spots fed into world-view, offline + live, golden test green. (parity)
- Aim is learned (turn delta + fire), not frogbot, live in the seam. (leap slot uses learned aim+fire live)
- Best-of-10–20: move+aim brain beats the Phase-1 number. Aim judged by **damage done** (and frags), not accuracy, not angle-copy. (margin up)

### Phase 3 — One brain (move + aim + fire)
Goal: collapse into one brain over the one world-view. IL-trained, optional elite anchor.
- One brain outputs move+aim+fire+weapon together. Drops into the same pipe, no new plumbing. (runs live)
- Best-of-10–20: one-brain beats the Phase-2 split-brain number → adopt it. Else keep split-brain. The bench decides, not elegance. (margin compare; decision recorded)

### Phase 4 — Bench RL (push the ceiling, stay human)
Goal: fine-tune on the bench to win more, without losing the human look.
- RL fine-tune from the IL brain, anchored to it so it stays human. (KL to base bounded; run completes)
- Best-of-20: margin goes up AND the human-look gate (no spin-and-run, G-MV1 believability gate) still passes HARD. (both true → accept; else reject)

## Tickets (small, ordered; mirrored as GitHub issues)
Labels: `bot-program` + `phase-0`..`phase-4`. Each ticket: What / Where / Done-when / Needs-first.

**Phase 0**
- **T0.1 Bench: emit leap−frog frag margin.** Extend `scripts/run_frobodm2_lab.py` + the 4v4 ledger builder to score the leap slot and write the margin over best-of-N. Done when: a frog-vs-leap 4v4 run writes a margin to the ledger and R-T `damage.matrix` gate is green. Needs first: none.
- **T0.2 Live-transport latency spike.** Try cheapest pipes (per-tick action-file re-read / new native socket-or-shmem trap / short action-queue). Measure p99 tick latency for up to 4 slots. Done when: a written report names the chosen pipe and shows p99 < ~0.5 ms/tick. Needs first: none.
- **T0.3 KTX "live mode" patch.** New moveprobe mode: fetch this tick's move+aim(`desired_angle`)+fire+weapon from the chosen pipe; fall through to `trap_SetBotCMD`; safe fallback on timeout. Patch extends `experiments/ktx_moveprobe/frogbot-moveprobe-perslot.patch`. Done when: 1 bot in live mode plays 5 min, no freeze, log shows live cmds, fallback fires clean when helper paused. Needs first: T0.2.
- **T0.4 Shared world-view module v1.** One importable file = MoveMLP's exact 6 features, used by BOTH the offline dataset builder and the live helper. Done when: imported by both; unit test on a sample frame. Needs first: none.
- **T0.5 Golden-vector parity test.** Replay one QWD live in KTX, dump live world-view per tick, diff vs offline-built world-view. Done when: parity passes within tolerance; runs in CI. Needs first: T0.3, T0.4.
- **T0.6 Policy sidecar serving MoveMLP.** Python helper loads MoveMLP, reads world-view, returns move; aim/fire stay stock frogbot. Done when: sidecar answers over the pipe; argmax matches `eval_closedloop` on a sample. Needs first: T0.2, T0.4.
- **T0.7 First live verdict.** Best-of-10 frog-vs-leap (leap = live-MoveMLP move + stock aim + 3 frog mates vs 4 frog). Done when: margin recorded to ledger+dashboard; R-T gate green; repeatable. Needs first: T0.1, T0.3, T0.5, T0.6.

**Phase 1**
- **T1.1 All-frames BC dataset.** Drop the clean-segment mask in `build_dataset.py`; demo-level split; class weights for rare jump/fire. Done when: dataset built from all frames; frame count logged; no demo leakage. Needs first: T0.7.
- **T1.2 Widen world-view.** Add yaw-rate + short history, map rays via `pmove_sim`, nearest-item vector to the shared module; re-run parity. Done when: new channels present; golden parity green. Needs first: T0.5.
- **T1.3 Recurrent move policy.** Small GRU/TCN on the widened view. Done when: trains; open-loop retention ≥ seed on held-out. Needs first: T1.1, T1.2.
- **T1.4 Best-of-N move bake-off.** Candidates differ by data subset / features / weights / air-law-teacher on-off; run best-of-10–20 each. Done when: winner beats Phase-0 margin (with CI) AND leap damage-done not down >1σ vs baseline (accuracy is NOT a gate). Needs first: T1.3, T0.7.

**Phase 2**
- **T2.1 QWD enemy decoder (kill-switch).** Extend the `qwd_usercmd.py` `dem_read` path to decode `svc_packetentities`/`svc_playerinfo` into per-tick enemy tracks; reuse `probe_qwd_route_applicability.py` self-decode. Done when: known-answer self-track regression passes; track counts reported. Needs first: T0.7.
- **T2.2 Enemy channels into world-view.** Offline from decode, live from server entities; re-run parity. Done when: enemy polar channels present; golden parity green. Needs first: T2.1, T1.2.
- **T2.3 Aim-label builder.** On fire-frames, compute target-relative angle from self view + decoded enemy. Done when: aim dataset built; angle spread sane (reported). Needs first: T2.1.
- **T2.4 Learned aim head live.** Turn-delta + fire head served in the seam; stock aim off for the leap slot. Done when: leap uses learned aim+fire live. Needs first: T2.2, T2.3, T0.3.
- **T2.5 Best-of-N aim bake-off.** Done when: move+aim brain beats Phase-1 margin; aim judged on damage done (and frags), not accuracy. Needs first: T2.4, T1.4.

**Phase 3**
- **T3.1 End-to-end policy.** One trunk → move+aim+fire+weapon over the unified view; IL pretrain + optional elite (Milton) anchor. Done when: trains; serves live in the same pipe, no new plumbing. Needs first: T2.5.
- **T3.2 One-brain vs split-brain bake-off.** Done when: adopt one-brain only if it beats the Phase-2 margin; else keep split. Decision recorded. Needs first: T3.1.

**Phase 4**
- **T4.1 On-bench RL fine-tune.** PPO/AWR from IL weights, KL/BC anchor to IL; dense qw-analyze proxy reward + frag-margin terminal. Done when: run completes; KL to base bounded. Needs first: T3.2.
- **T4.2 RL accept gate.** Best-of-20. Done when: accept RL checkpoint only if margin up AND human-look gate (G-MV1) passes hard. Needs first: T4.1.

## Open forks (defaulted; flip on request)
- Live transport: spike decides (don't pre-commit).
- End-to-end vs split brain: bench decides (flag if one-network should win by default).
- Learn DECIDE/goal: defer until a verdict demands it; then prefer a learned waypoint-bias channel over hand-code.
- RL: optional / plateau-triggered — ship best IL if it already wins.
- Believability G-MV1: hard gate from Phase 2.
- Elite anchor: bench picks (Milton/pool/ensemble).

## Key risks
- Live pipe is new + make-or-break → spike first; queue fallback still ships a verdict.
- Train/serve skew → one shared module + golden parity as a hard gate; start at 6 features.
- Enemy decode never done here → self-track kill-switch; MVD-sync fallback; aim deferred to Phase 2.
- Offline sim is worldmodel-only → never gate on trajectory-match; bench frags are binding.
- Stock-aim ceiling in Phase 0–1 → run a plain-frogbot control to isolate the move delta.
- Best-of-N variance → fixed seeds, z-score vs frog baseline, report CIs.
- RL drifts off human → KL anchor + G-MV1 hard gate.

## Reuse (don't rebuild)
Seam: `artifacts/ktx-live/bot_movement.c` (`BotApplyMoveProbe`, `trap_SetBotCMD`, `FBMOVEPROBE_CMD`) + `experiments/ktx_moveprobe/frogbot-moveprobe-perslot.patch`. Bench: `scripts/run_frobodm2_lab.py`, `lab/server/control_bridge.py`, `scripts/moveprobe_parse.py`, `scripts/telemetry_ws.py`, `scripts/freeroam_tws.py`. ML/data: `komodobots-ml/scripts/pmove_sim.py`, `experiments/stage2/move-bc-train/{train,build_dataset,eval_closedloop}.py`, `tools/qwd_usercmd/qwd_usercmd.py`, `scripts/probe_qwd_route_applicability.py`, `komodobots-ml/scripts/economy_state.py`, `lab/dashboard/public/data/map_entities/dm3.json`. Data: `~/ctv_decomp` (478 QWDs), `fantasyquake/backups/qw-stats.db`, `artifacts/human-demos/source/` (real elite dm3 4on4 MVDs). **Canonical MVD parser = Alfhan's mvdanalyzer `~/qw-sim/bin/qw-analyze-v20`** (decisions/economy/combat + bench scoring via ktxstats). **demopasha/`mimer`** (`~/projects/demoparser/target/release/mimer --dump-analysis`; `tools/demopasha/phase0/extract_positions.py`) = complementary/tentative, raw x/y/z positions only, cross-checked against canonical. Docs as reference: `references/12_DM3_4ON4_STANDIN_PROGRAM.md`; the R-T gate (composite) and G-MV1 believability gate are specified on the program branch (not yet on `main`).

## Owner prep track (parallel, no waiting on the live pipe)
The hardest remaining model is DECIDE (navigation, target choice, item/armor timing, rotations, roles).
MVD shows WHAT players did, not WHY — so expert labels raise quality a lot. Owner-contributable, in parallel:
- **Decision vocabulary** — the real DM3 4on4 "moves" (take RA/YA/mega/quad/RL, hold, rotate, support, deny, retreat, force) → the decision label set.
- **Curate + hand-label gold demos** — pick clean-macro 4on4 dm3 demos and mark intent over time → train + test labels.
- **Macro priors + "good looks like"** — armor ownership, rotations, timers, roles, grading bands.
- **Data authorization + sourcing** — which players/teams are usable; get more elite 4on4 MVDs.
These map directly onto mvdanalyzer's named spots + item/control fields and `mimer`'s positions.
