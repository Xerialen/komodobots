# RL-on-speed results (movement-v5, `ml/rl_onspeed.py`)

Status: 8 RL rounds, all raw-validated, 2026-06-22. Source of record:
`/home/ubuntu/.claude/plans/overnight-rl-summary.md` (narrative) +
`/home/ubuntu/.claude/overnight-rl-state.json` `runs[]` (per-round vectors).

## Headline

The movement problem is SUBSTANTIALLY solved: the central failure (closed-loop over-press /
bulldozing) that defeated the entire supervised family (BC -> reweight -> GRU-sequence ->
DAgger) is CRACKED by RL. Best checkpoint `rl_round6_r4init.pt`: fast (M1 273, in the 252-316
G-MV4 band) by AIR-STRAFING at human-level forward-press (0.243, in the human 0.07-0.50 band —
not bulldozing), launching (ra_jumps PASS), and believable (G-MV1). Round 5 proved the
over-press was a REWARD ARTIFACT (a mechanism-gated speed reward — credit speed only via
perpendicular air-strafe — broke the press<->speed anti-correlation). One residual remains,
rigorously diagnosed: M6 strafe-cadence rhythm co-occurring with launch+speed in a single
snapshot is a REAL tension (the cadence side-flip steals the sustained air-strafe that launch
and the speed-floor need), needing a different mechanism (trajectory/multi-tick cadence credit
or AMP), not more per-tick tuning.

## Eval integrity

- Every number in this doc comes from the SAME goal-conditioned gate harness the judge uses:
  `ml/eval_broad_closedloop.py` (G-MV4 speed, M1/M2) + `ml/eval_broad_dryroute.py` (per-route
  route%/speed% and the launch checks, M4/M5/guard) + the G-MV1/G-MV3 believability/cadence
  checks (M6/guard). Goal-conditioned per the post-#355 goal-injection fix (the policy is fed
  the goal-conditioned obs it was trained on, not free-roam `[0,0,1]`).
- Every metric vector was raw-validated by the orchestrator (read from the per-round
  `metric_*.json`, not from a transcript).
- The reward never reads the gate anchors for its in-band-speed term: that term uses a
  DISJOINT reward-leakage player split (`reward_dryrun` leakage split), so the reward band and
  the eval band are separated. Believability is enforced by a KL-anchor to a frozen copy of
  the BC-pretrained believable-aim policy (the hand-set believability threshold was dropped per
  the STEP-0 audit as unsound — fooled by replayed aim).
- What this does NOT prove: the M6 cadence rhythm is NOT solved in-band together with
  launch+speed; the checkpoints are NOT productionized (no live-server validation, no
  deployment); and the result is the offline goal-conditioned gate harness, not live play.

## Metric vectors (all 8 rounds, raw-validated)

Bands / direction:
- **M1** = closed-loop G-MV4 avg horizontal speed; UP; in-band = 252.279-315.632.
- **M2** = closed-loop G-MV4 p95 horizontal speed; UP; in-band = 461.538-560.008.
- **M3** = air forward-press (lower = less over-press; human band top 0.50). Over-press relief
  = max(0, 0.50 - M3).
- **M4** = hard-route route% mean over mega/sng/ra; UP.
- **M5** = hard-route speed% mean over mega/sng/ra; UP.
- **M6** = G-MV3 cadence flips/min in-band margin; UP/hold; cadence band 8-360 fpm.
- **Guards** = launch (ra_jumps PASS, target launch >= 1/3) + G-MV1 believable (must hold; a
  break is a regression, never a new best).

| Round | M1 avg | M2 p95 | M3 press (air) | M4 route% | M5 speed% | M6 margin | launch | G-MV1 | Note |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 221.073 | 379.439 | 0.5706 | 66.67 | 71.243 | -8.0 | 1/3 | true | basin-escape (over-press 0.906->0.571) |
| 2 | 164.565 | 380.1 | 0.6903 | 29.869 | 20.56 | -8.0 | 0/3 | true | regression + launch-guard break (discarded) |
| 3 | 267.576 | 395.94 | 0.7987 | 57.47 | 74.389 | +5.99 | 1/3 | true | first M1 in-band + cadence fixed |
| 4 | 280.088 | 404.0 | 0.8377 | 65.788 | 80.805 | +9.98 | 1/3 | true | net-best; diagnosed press<->speed reward problem |
| 5 | 257.066 | 409.18 | 0.0 | 62.94 | 56.69 | -8.0 | 0/3 | true | REWARD BREAKTHROUGH (in-band @ press 0); not promoted |
| 6 (r4init) | 273.22 | — | 0.2431 | 65.167 | 80.845 | -8.0 | 1/3 | true | **OVER-PRESS SOLVED in-band = best ckpt** |
| 6 (r5init companion) | 264.356 | — | 0.0260 | — | — | +26.97 | 1/3 | true | M6 in-band but press just-under |
| 7 (it6 guard-safe) | 267.37 | — | 0.268 | 50.2 | 73.2 | -8.0 | 1/3 | true | no new best |
| 7 (it12 candidate) | 251.12 | — | 0.23 | — | — | +78.28 | 0/3 | true | broke press<->cadence but over-flipped (281 fpm); not promoted |
| 8 | 255.826 | — | 0.4853 | 66.614 | 70.214 | -8.0 | 1/3 | true | 4/5; M6 the residual |

(Dashes = the field was not recorded in `runs[]` for that round/sub-checkpoint; M2 is only
in the headline vectors of rounds 1-5.)

## Per-round honest read

- **R1 — basin-escape.** The first working end-to-end PPO-on-speed loop + first vector. RL
  moved over-press off the basin (0.906 -> 0.571) while G-MV1 held — the supervised family
  never moved it off ~0.83-1.0. M5 hard-route speed% 22 -> 71 (3.2x); launch 0 -> 1/3
  (ra_jumps PASS). Not yet in-band (M1 221 < 252) and M6 cadence regressed to 0.
- **R2 — discarded regression + launch-guard break.** A tuning misstep: every targeted lever
  missed or backfired (4/6 metrics down, launch 1/3 -> 0/3). Key insight that carries forward:
  the eval is deterministic-ARGMAX, so a behavior reward (cadence) must move the argmax, not
  just sampling; and loosening KL/entropy RAISES over-press. Not promoted; best stayed R1.
- **R3 — first M1 in-band + cadence.** M1 crossed into the speed band for the first time
  (267.576 >= 252) and M6 cadence was fixed (argmax-targeted), guards held. Trade: over-press
  regressed to 0.799 via an eval-vs-rollout press selection bug.
- **R4 — net-best + diagnosed the press<->speed reward problem.** Net-best on aggregate (M1
  280.088, M4/M5/M6 up, guards held), but the decisive diagnostic: over-press and speed are
  ANTI-CORRELATED under the "speed-however-achieved" reward — every in-band-speed snapshot
  bulldozes (press >= 0.80) and the only low-press snapshot is too slow (M1 163.5). So press <
  0.50 is unreachable by selection/tuning — it is a reward-geometry problem.
- **R5 — reward breakthrough.** Changed the reward to credit speed ONLY via the air-strafe
  mechanism (`perp_frac = 1 - (v_hat . wishdir)^2`) + a hard air press-barrier. The
  anti-correlation BROKE: M1 257.066 in-band at forward-press 0.0 (relief maxed 0.5), G-MV1
  held = fast by AIR-STRAFING, not bulldozing. The over-press was a reward artifact. But it
  overshot (press 0, past the human floor) + cadence/launch broke -> not promoted.
- **R6 — OVER-PRESS SOLVED in-band = the best ckpt.** A soft press-barrier (hinge above
  press-frac 0.40, not flat) + cadence-coexistence + band-targeted selection landed
  `rl_round6_r4init.pt`: forward-press 0.243 (in the human 0.07-0.50 band), M1 273.22 in-band,
  launch 1/3 RECOVERED, G-MV1. The central failure is solved. Companion `rl_round6.pt` (r5init)
  reaches M6 in-band (+26.97) but at press just-under (0.026) — so in-band press and in-band
  cadence each recover, just not co-occurring in one snapshot.
- **R7 — broke press<->cadence but over-flipped.** Forcing L<->R flips produced the first
  fully-qualified press + M6 + G-MV1 candidate (@it12) — but its full eval came in at M1 251.12
  (1.16 under the floor) and launch broke (0/3): the closed-loop-only selection screen was blind
  to launch. The barrier evolved to (M1 + launch) vs cadence. No new guard-safe best.
- **R8 — 4/5 with cadence the residual.** Moderate cadence + a LAUNCH-AWARE selection screen
  (runs the dryroutes, requires launch >= 1) gave 4/5 guard-safe (M1 255.826 in-band, press
  0.485 in-band, launch 1/3 ra_jumps PASS, G-MV1) with M6 cadence -8 the miss. An 8-candidate
  screen + a seed sweep reproduced the tension: M6-in-band ALWAYS co-occurs with launch-break +
  M1-collapse (the argmax side-flip that makes cadence steals the sustained-perpendicular
  air-strafe that launch and M1 depend on). The launch-aware selection provably rejected every
  launch-breaker but cannot manufacture a snapshot that does not exist.

## Stopping rationale

Stopped per the owner's 5-run rule: the saved-ckpt frontier plateaued (rounds 7-8 did not
advance the best; the cadence-unification is a diagnosed MECHANISM gap, not a tuning gap). The
core goal (over-press) is solved. Guard-breaks 0 (clean stop, no backstop trip).

## Checkpoints

Checkpoints live on pinnacle `/home/xerial/rl-onspeed/ckpts/rl_round{1..8}*.pt` — NOT in git
(too large; offline GPU artifacts). Best = `rl_round6_r4init.pt`. Companions of note:
`rl_round6.pt` (r5init: M6 in-band but press just-under) and `rl_round4.pt` (M6 + cadence but
over-presses 0.838 = the failure not solved).

## The cadence residual + next mechanism

M6 (the L<->R strafe-flip rhythm) co-occurring with launch + speed in one snapshot is the one
unsolved axis. It is a REAL tension (diagnosed across rounds 7-8 + a seed sweep), not
under-tuning: the argmax side-flip that creates cadence steals the sustained-perpendicular
air-strafe that the hard-route launch and the speed floor depend on — they compete for the same
yaw control, and a per-tick cadence reward + BC-warmstart PPO cannot decouple them. The next
attempt needs a DIFFERENT mechanism, not more per-tick tuning:

- a **trajectory/multi-tick cadence credit** — reward the rhythm without shortening the
  strafe-hold that feeds launch; OR
- **AMP** — an adversarial believability discriminator trained on the real human yaw-rhythm
  distribution (the STEP-0 audit's recommendation).

Either is a fresh RL sub-track and is owner-gated.
