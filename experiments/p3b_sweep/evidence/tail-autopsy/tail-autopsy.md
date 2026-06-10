# A2b — tail autopsy: why the >=526 tries work, and how to cause them (issue #111)

**VERDICT: PATTERNIZED (sim).** The lucky tries succeed because they enter
the final runway already fast instead of starting it from a standstill — and
the speed comes from an accidental **circle-jump** (a grounded circle-strafe,
the same trick human players use before a bunnyhop chain). Doing that
circle-jump on purpose, once, at the start of the attempt turns the >=526
crossing from a 1-in-30 fluke into a 7-of-30 regular event on fresh seeds,
with the typical (median) crossing speed rising from 459.8 to 496.7 — above
the ceiling of every one of the 1986 configs in the A2 sweep (470.1).

In plain words: the bot used to sprint the bridge from a standing start, and
the track is simply too short to reach 526 that way. The lucky runs had
wandered first and hit the track already at speed. The fix teaches the bot
what every QuakeWorld player does on spawn: run a tight little circle on the
ground to build speed (ground acceleration is ~10x stronger than air
acceleration when you hold the wish-direction at an angle), then jump out of
the circle straight onto the track.

Everything here is sim-only (A1-calibrated port, +5.8% fast on tws vs live;
edge bias unmeasured live). The measurement, seeds, and pass criteria were
pre-registered in `artifacts/loop-state.md` BEFORE any fresh-seed run. The
526 target and the `route_metrics.edge_speed` metric were never touched.

Date: 2026-06-10. Sim: `scripts/mode23_sim.py` (additive, default-off knobs;
A1 calibration parity re-verified byte-identical after the changes — summary
AND all 30 per-seed records). Autopsy tooling: `scripts/tail_autopsy.py`.

---

## 1. Inventory — the lucky tail

From the raw sweep jsonl (`artifacts/p3b-sweep/stage{1,2}.jsonl`):
**50 (config, seed) pairs with rung-B edge >= 526**, in 48 configs, from only
**12 distinct seeds** (heavy hitters: seed 18 x12 configs, 25 x8, 15 x7,
5 x6). Many pairs are per-seed identical trajectories (governor-inert twins);
24 distinct (seed, edge) trajectory groups. Best single try 554.5
(`p130_n5_s12_t35_c45-85_gnone_l0`, seed 20).

All 1440 tries (48 configs x 30 seeds) were re-run with rich traces
(`run_attempt(rich_trace=True)`, additive observation keys) — **every
recorded edge value reproduced exactly** (hard assert per try), and the
crossing-index finder was asserted against `route_metrics.edge_speed` on
every try. Bands (within-config, sweep-recorded values): lucky >= 526 (n=50),
near 490-526 (n=78), mid 450-490 (n=229), deep < 450 (n=339), none = no
crossing (n=744).

## 2. The condition (falsifiable) and where it lives

Working backwards from the measured crossing by path arc length (the plane's
along-axis aliases the spawn area; arc length is monotone), median vh per
band:

| backdist (qu before crossing) | lucky | near | mid | deep |
|---|---|---|---|---|
| 0 (the crossing) | **529.0** | 504.9 | 460.1 | 436.5 |
| 300 | 491.5 | 466.1 | 409.1 | 390.9 |
| 600 | 448.0 | 419.4 | 340.4 | 333.4 |
| **1000 (runway entry)** | **386.1** [p10 358, p90 402] | 328.7 | 180.8 | 194.5 |

The separation GROWS going backwards: ~+70 at the plane, ~+200 at the runway
entry. The condition's home is the **runway entry**, 1000 path-qu before the
crossing (mid south-walkway), not the corner and not the final hops.

**Condition (stated falsifiably):** every >=526 try enters the last 1000
path-qu of its approach carrying >= 323 qu/s (median 386); sub-450 tries
enter at ~180-195. Threshold table over all 696 crossing tries:

| entry vh >= | tries | of them >=526 | P(>=526) | recall |
|---|---|---|---|---|
| 300 | 200 | 50 | 25.0% | 50/50 |
| 350 | 118 | 47 | 39.8% | 47/50 |
| 400 | 18 | 6 | 33.3% | 6/50 |

Necessary (50/50 above 300; 0 lucky below 323) but not sufficient (~40%
convert at >=350) — the rest is runway execution: lucky tries touch the
ground ~3 frames over the last 1000 qu vs ~16 for deep tries (each ground
frame at speed costs friction).

Supporting facts: lucky tries cross LATE (t_cross median 5.3 s vs 3.7 s
mid/deep — the flying start takes a detour); 47/50 lucky entries sit in the
spawn-walkway-east / SE-stair area; their paths all show a backward leg
(nav noise linking markers 75/76 before the westbound run).

## 3. The mechanism — an accidental circle-jump

Tick-level replay of the strongest natural try (seed 20, 554.5) over its
loop turn (`t = 2.42..2.88`):

* lands on the stair terrace at 208 qu/s; the **grounded** turn dips to ~109
  and ground-acceleration instantly rebuilds 113 -> 273 in 0.25 s
  (delegation walks the U-turn — below maxspeed, ground accel is free);
* then, still grounded, with the weave's wish-direction held 35-60 deg off
  the velocity, speed climbs **325 -> 384 in ~0.1 s** — far beyond air
  acceleration. This is QW **ground accelerate**: it adds up to
  `accel * wishspeed * frametime` (~32 qu per tick, ~10x the air cap) as
  long as the velocity's projection onto the wish-direction stays under
  maxspeed. Holding the wishdir at an angle keeps that condition true ABOVE
  320 — the classic human circle-jump. Equilibrium of a held grounded
  circle-strafe ~460-480 qu/s;
* the jump stays suppressed through the turn because the law's corner rule
  (herr > turn_thresh) holds it — by luck;
* at 384, aligned, it jumps; one further touch on the walkway (instant
  re-jump, no loss) and the hop chain carries 384 -> 554.5 at the plane.

So the lucky shape end-to-end: wander -> grounded circle-ish turn
(accidental circle-jump to ~330-420) -> clean 1000-1300 qu hop chain. The
unlucky shape: beeline from a standing start — and from ~0, the available
~1300 qu of track tops out at ~470-510 (confirmed: the all-sweep median
ceiling is 470.1, and every "clean direct run" design variant capped at
~498-514 median / ~514-525 max).

## 4. Patternization — design rounds (training seeds 1..30 only)

Seven design rounds, all on the SAME seeds the sweep used (1..30); fresh
seeds were never touched during design. Raw grids:
`design-grid-r{1..7}.json`. Dead ends, kept for the record:

| round | idea | result | lesson |
|---|---|---|---|
| r1 | spin-up loop (temporary nav goal 76/71/126/124/127, then release) | n526 <= 1-2/30 | release before the plaza adds no path; plaza overshoot U-turns at 430+ dump to ~120 |
| r2 | + delegation speed gate (`deleg_vh_max` 320) | median 512.3 (!) but max ~522, n526 0 | the stair-climb delegation was scrubbing returns; gating it lifts the median but the loop turn still costs ~30-50 |
| r3 | + launch assist (`jump_min_vh`: run grounded to speed before hopping) | clean-start median 498 (no spinup), max ~514 | fixes the 0-2.5 s low-speed orbit chaos; single-pass ceiling confirmed |
| r4 | numerator 9/16/26 (accel-optimal wishdir on straights) | medians DROP (466/324) | turn responsiveness >> the last few degrees of accel angle; n5 stays |
| r5 | runway-constant cross (pass_r/swing/turn) on the spinup stack | best 512/527, n526 1 | the wall persists; entry ~345 is ~30-40 short |
| r6 | **circle-jump launch** (`launch_vh`/`launch_angle`) | **cj400a40: n526 10/30, median 505.9, max 556.5** | the root mechanism, induced deliberately, replaces the whole loop |
| r7 | refinement | **p100s12t35 + cj400a42: n526 13/30, median 528.0, edge_n 26/30, max 558.3** | the candidate |

The winner (`PATTERNIZED` in `scripts/tail_autopsy.py`):

* cvars (existing): `k_fb_moveprobe_s23_pass 100`, `_accel_numerator 5`,
  `_s21_swing 12`, `_s21_turn 35`, `_s21_corner_thresh 45`,
  `_s21_corner_aim 85` — the sweep's top-median family;
* NEW (additive, default off): **circle-jump launch** `_s23_launch_vh 400`,
  `_s23_launch_angle 42` — one-shot at attempt start: while grounded below
  400 qu/s, hold the jump and keep the wish-direction 42 deg off the
  velocity (the grounded circle); release into the hop chain the moment the
  bot is fast (>= 400) AND aimed (|heading err| <= swing); 3 s safeguard
  timeout; an engage ray (>= 0.9 open toward the goal direction) filters
  direct-wall starts.

NOT a grounding governor: it acts once, at spawn, below route speed, and
never re-engages mid-route (the two live-rejected governors grounded the bot
at corners mid-route; this does the opposite — it un-grounds the start).

## 5. Pre-registered fresh-seed test (seeds 31..60)

Registration (ledger row, written before any seed-31..60 run): runner
`python scripts/tail_autopsy.py fresh`; rung B + rung A, patternized AND
base, all 120 runs reported, no re-runs, no selection. Criteria: C1
patternized rung-B n526 >= 4/30 AND > base; C2 patternized edge median
>= 490; C3 edge_n >= 8/30; C4 BASE (deploy-default, launch off) rung-A reach
>= 12/30, with the launch-ON rung-A number disclosed (deviation from the
ticket's example floor recorded in the registration with rationale).

**Results (`fresh-seed-results.json`, all 30 seeds each):**

| | patternized | base (same cvars, launch off) |
|---|---|---|
| n526 | **7/30** | 0/30 |
| edge median (present) | **496.7** | 459.8 |
| edge_n | 25/30 | 27/30 |
| edge max | 548.5 | 483.1 |
| rung-A reach | 6/30 (launch ON — disclosed) | **24/30** |
| rung-A tws median | 265.6 | 269.6 |

**C1 PASS** (7 >= 4, base 0). **C2 PASS** (496.7 >= 490). **C3 PASS**
(25 >= 8). **C4 PASS** (24 >= 12). The borderline rule (confirmation block
61..90 if n526 = 3) did not trigger; no extra seeds were run.

Training -> fresh regression is visible and expected (13/30 -> 7/30, median
528 -> 497: the design picked the training argmax); the pre-registered
thresholds were set for exactly this, and all hold.

## 6. Honest flags

* **Sim-only.** A1 trust bounds apply: sim +5.8% fast on tws vs live; the
  edge metric's live bias is unmeasured (A3 measures it). A 526 here is a
  526 in the sim's physics. The circle-jump itself is bog-standard QW
  movement (ground accelerate + friction), the port of which was validated
  against live pmove frame-for-frame in A1 — but live cmd cadence /
  onground-flag jitter could shave the grounded gain. A3's first job is one
  live block of the patternized config.
* **Surrogate flag** (inherited from A2): "the crossing" is the pin-148
  bridge-approach plane crossing, not the leap; no leap link exists in the
  graph (D1 #77).
* **Per-protocol knob.** With the launch cvar forced on, rung A (a tight
  spawn room) regresses 21->10/30 on training seeds and 24->6/30 on fresh
  seeds: the circle wall-locks (the engage ray filters direct walls but
  cannot size the ARC room — measured, documented in the code). The launch
  cvars therefore ship **default 0** (= byte-identical law everywhere) and
  are set per-run by the measurement protocol, exactly like
  `k_fb_moveprobe_spawn_origin` and `_fixed_goal` already are. The deploy
  default's rung-A floor is C4 (24/30, PASS).
* **Crossing-rate dip**: patternized edge_n 25/30 vs base 27/30 — 5 fresh
  seeds never crossed (launch-released runs can fall off the walkway at
  speed). Reported, inside the C3 floor.
* The spin-up loop + delegation gate + jump_min_vh knobs from the dead-end
  rounds remain in the sim as documented, default-off, unit-tested params —
  they are part of the record (and `deleg_vh_max` is independently
  interesting for A3: it produced the 512-median family without any launch).

## 7. What A3 (#75) deploys if it wants this live

Additive KTX changes at the mode-23 block (no metric, no nav, no KTX source
touched in this ticket — this is the would-be change list):

1. Cvars `k_fb_moveprobe_s23_launch_vh` (default 0 = off) and
   `k_fb_moveprobe_s23_launch_angle` (default 45). ~25 lines in
   `BotApplyMoveProbe` mode-23: two per-slot statics (launch_done,
   launch_since), the engage ray (existing traceline helper, LOOK=500,
   fraction >= 0.9), the grounded circle branch (wishdir = velocity yaw +
   angle * sign, jump suppressed), release on (vh >= launch_vh AND
   |signed_to_goal| <= swing) or 3 s timeout, one-shot latch.
2. Optionally `k_fb_moveprobe_s23_deleg_vh_max` (default huge = off): gate
   the delegation early-return AND the c5 carrot guard on horizontal speed.
3. Surrogate protocol per run: matchless + `spawn_origin "1959 -425 -24"` +
   `fixed_goal 148` + the six constants + `launch_vh 400 launch_angle 42`,
   20 s window, score with `route_metrics.edge_speed` over `legit_segment`
   truncated at first 60-qu arrival (unchanged conditioning).

Expected live numbers per the trust bounds: median ~470-497 (sim-fast bias),
P(>=526) somewhere between the base ~0/30 and the sim's 7/30 — the
pre-registered live block decides.

## 8. Reproduction

```
python scripts/tail_autopsy.py inventory          # lucky pairs from the sweep jsonl
python scripts/tail_autopsy.py trace --workers 12 # 1440 rich re-runs + assert vs recorded
python scripts/tail_autopsy.py analyze            # band tables (band-summary.json)
python scripts/tail_autopsy.py design --workers 12   # the (final-round) design grid
python scripts/tail_autopsy.py rung-a --workers 12   # rung-A floor, training seeds
python scripts/tail_autopsy.py fresh --workers 12    # THE pre-registered 31..60 block
python scripts/mode23_sim.py calibrate --config c5 --seeds 30 --out artifacts/tail-autopsy/parity-check
python -m unittest discover -s tests -p "test_*.py"  # 267 tests
```

Raw (gitignored): `artifacts/tail-autopsy/` (features.jsonl 1.9 MB, parity
check, design grids). Committed copies here: `inventory.json`,
`band-summary.json`, `design-grid-r{1..7}.json`, `fresh-seed-results.json`.
