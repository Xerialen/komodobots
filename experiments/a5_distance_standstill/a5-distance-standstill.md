# A5 #118 — the ztricks "Distance" jump from standstill: sim phase

**Plain words first.** The bot must do what the human did in `getspeed.qwd`:
stand still where the map's teleporter drops you, build speed on the ground
by circle-strafing, jump at the platform edge, fly a ~300 qu gap, land the
far platform. This report covers the SIM phase: two data corrections that
change the spec, a full validation of the simulator on the real map (it
replays the human's demo to a tenth of a game unit), and the pre-registered
launch-controller sweep — which came back **0 landings in 4860 attempts**
and fired its pre-registered escalation. The failure is localized to ONE
sub-skill (the release), the data says exactly what is missing, and two
concrete next variants are specced below. No live runs were burned.

---

## 1. Corrections to the spec (both now in the doc's banner + changelog 7)

1. **The map is `ztricks.bsp`, not `trick.bsp`.** The demo's own model list
   says `maps/ztricks.bsp`; the Distance room coordinates are outside
   trick.bsp's world bounds entirely. The spec doc's entity analysis ran
   against the wrong file. Redone on ztricks.bsp: 26 trigger_teleport,
   8 info_teleport_destination, 37 light, 1 info_player_deathmatch — still
   **no push/pad entity**, so "the takeoff is the player's own jump" keeps
   its map-side support. The miss-reset mechanism is a catcher-slab
   teleporter under the gap (x −3392..−3000, y 3552..3872, z −576..−568)
   targeting destination `t5`.

2. **The committed `getspeed.cmds` pairs inputs to the wrong frames.** The
   builder zips the input stream (2145 cmds, complete) with the state
   stream (2104 — the server dropped 41 frames); every drop shifts all
   later rows, so by the winning attempt the inputs printed next to a
   position are ~0.5 s stale. (The dm3 validation demo had zero drops,
   which is why this never showed before.) Fixed by time-matching the two
   streams (`a5_rebuild_cmds.py`; both streams carry demo time; constant
   pipeline lag L=2 found by scanning −1..4 against anchored replay error:
   L=2 gives p95 0.147 qu, every other L ≥ 0.48). Consequence: **the jump
   button is pressed exactly on the last grounded frame of EVERY launch,
   including the winner** — the takeoff is a plain self-jump (+270; the
   spec's "+249 mystery" is that jump sampled 2 frames into gravity across
   the dropped state). The spec's [O0] is closed with data, not just
   player testimony. The per-attempt speed/heading table survives
   unchanged (it was state-stream-derived): lip speeds 455–477, the winner
   uniquely negative at −11.7°. One of the 11 attempts (att 6) was a
   walk-off-the-edge botch with no jump at all.

## 2. The per-attempt start (binding, from the demo + map)

| | |
|---|---|
| teleport deposit (= attempt start) | **(−3516.125, 3712, −453.125)**, all 10 resets within 4 qu |
| facing | **yaw 0** (destination angle; demo arrivals wobble 352°..3°) |
| map entity | `info_teleport_destination` `t5` (−3520, 3712, −480), z+27 at spawn |
| what happens next | the player falls ~35 qu onto the z=−488 platform |

Live spawn-snap: `k_fb_moveprobe_spawn_origin "-3516.125 3712 -453.125"`
(zero velocity = true standstill; the human actually arrives with the
teleporter's 300 qu/s throw, which they immediately scrub — standstill is
the harder, requested case).

## 3. Geometry (BSP-probed, player-origin z; hull-center extents)

| feature | extent |
|---|---|
| run-up platform | x −3540..−3348, y 3600..3820, z −488 |
| launch lip line | x ≈ −3348 (the winner pressed jump at x −3360.8) |
| gap | ~300 qu of open space, floor z −584, catcher slab below |
| far platform | x from −3048 (same y band 3600..3820), z −488 |
| landing detector (locked) | grounded, \|z+488\| < 0.5, **x > −3100**, y in [3600, 3824] |

Flight arithmetic that governs everything: a flat +270 jump returns to
z=−488 after 0.675 s, so carry ≈ vh × 0.675 (+10..25 qu of air-accel
gain). At 455 qu/s that is ~322 qu — the release must fire **within ~35 qu
of the lip**, with a heading that keeps the flight inside the 220-qu-wide
y band. The human: 475 at 13 qu before the edge, heading −11.7°.

## 4. Sim validation on the real map (PASS — `a5_validate_replay.py`)

Free-run replay of the aligned human demo through `pmove_sim` against
ztricks.bsp, re-anchoring only at the 10 teleport resets:

- anchored per-step error: **p95 0.147 qu** (dm3-grade);
- free-run clean rows: mean 0.107 qu (the demo's reference stream has
  lumps near its 41 dropped frames — excluded rows must and do recover);
- **every one of the 11 attempts reproduces**: 10 jump-launches with the
  button on the lip frame, lip speeds 455–477, headings +35..−11.7 with
  the winner uniquely negative — the spec table re-derives exactly;
- **the winning attempt tracks deposit→landing at ≤ 2.6 qu**, lip speed
  476.0 sim vs 475.2 recorded, landing 496.2 vs 495.5, and the arc LANDS
  the far platform in-sim per the locked detector.

The simulator is trusted on this map at these bounds.

## 5. The pre-registered sweep (ledger row written before the block)

**Harness** (`a5_launch_harness.py`): the DEPLOYED mode-23 law byte-for-
byte (`mode23_sim.mode23_step`, audit-law mode) with nav = a fixed point
(the census landing spot), the deployed circle-jump launch block
(`k_fb_moveprobe_s23_launch_vh/_launch_angle` semantics: circle-strafe
grounded below launch_vh, release at speed+aim, 3 s safeguard), over
validated pmove on the real BSP with the map's own teleporters as the
attempt boundary. Plus ONE sim-first variant dimension (off = deployed):
`lip_gate_dmax` — defer the release unless within [0, dmax] qu of the lip.

**Grid:** launch_vh {430,455,475} × launch_angle {45,50,54} × swing
{4,8,15} × circle direction {−1,+1} × lip_gate {off,25,45} = 162 configs ×
seeds 1..30, 25 s budget. **Pre-committed:** best ≥ 5/30 → live phase;
all 0/30 → decomposition + escalate.

**Result: 0/4860 attempts landed.** The off-ramp fires.

## 6. Off-ramp decomposition — WHICH sub-skill fails

(`a5_offramp_decomposition.py`, from the recorded release/lip states)

| sub-skill | verdict | numbers |
|---|---|---|
| BUILD (standstill → speed) | **works** | 48% of attempts reach their launch_vh mid-maneuver; max-vh p50 454.5, p90 469.6 — human-grade speed from a dead stop in ~1.4 s |
| RELEASE (fire at the right moment) | **fails structurally** | **4499/4860 (93%) never release** — the orbit/skate carries the bot off the platform at ~1.8 s before speed+aim ever coincide; 361 release (85 by timeout), and the only repeatable near-lip family is a north-wall slide releasing at y=3824.0, heading 0.0, vh 430–435 (125 cases) |
| ARC (fly and land) | never reached | **4528 NO-JUMP walk-offs** (lip crossings whose last grounded cmd carried no jump bit — falling from platform height can never reach the same-height far floor; no fake arc applied. Classified by the recorded cmd bit at the lip row, Codex P2 rounds 1+2: release timestamps land one tick late and cannot separate an on-lip release from a post-lip mid-air timeout) + 332 actual jumps: 329 SHORT, 3 Y-OUT — the wall-slide family at 430–435 is *simultaneously* ~3–8 qu short on x-reach and ~20 qu north of the band; **0 WOULD-LAND states in 4860 attempts** |

**Plain words:** the bot gets the SPEED skill right and never gets the
RELEASE GEOMETRY right. The deployed launch is a point-condition
(speed ∧ aim [∧ window]) on an orbit it does not steer — on a 190×220 qu
platform those conditions never coincide while still grounded. The wall
slide it discovers on its own is 20 qu of y and ~10° of dip away from the
human's winning line (the human carves off the north wall at −11°; the
slide flies dead along it at 0°), and at the slide's equilibrium speed
(430–435) even a corrected heading would still be ~8 qu short of x-reach.
The human solves speed+aim+position TOGETHER with a planned terminal
carve; the current control cannot express that.

This is the same lesson as A3's live divergence ("release line/timing is
the leak"), now measured exhaustively at 0/4860 on a tighter stage.

## 7. Next variants (specced, NOT run — pre-register before any scored block)

1. **Terminal carve release** (the human's actual move). While the launch
   is armed: when d_lip ≤ carve_d AND vh ≥ carve_vh: stop circling, hold
   the wishdir a carve angle toward the target side of the velocity
   (continues building speed — a carve IS a swept wishdir), jump when
   herr ≤ tol or d_lip ≤ 8. Live shape: `k_fb_moveprobe_s23_launch_target
   "x y z"` (already needed: ztricks has no .bot, the target point IS the
   nav) + `_s23_launch_carve` (window). Quantified target from the data:
   bend the existing 430–435 wall-slide release by −8..−12° and raise its
   release speed toward the open-field p90 (~470) — at 455+/−10° the
   flight lands mid-band with margin.
2. **Short-timeout circle → hop-chain** (smallest possible change: the
   deployed 3 s LAUNCH_TIMEOUT as a cvar, set ~1.0–1.2 s). Releases the
   circle at speed mid-platform and lets the hop chain quantize toward the
   lip; geometry says ~10–15% of chains touch last inside the launch
   window. Cheap, no new control concept, but luck-based — a screening
   config, not the solution.

Estimated next round: one registered sim sweep over the carve variant's
3–4 knobs (carve_d, carve angle, carve_vh, tol) × 30 seeds, then the live
phase per the ticket (KTX additive cvars + .bot generation for ztricks +
spawn-snap protocol).

## 8. Files

| file | what |
|---|---|
| `a5_start_point.py` → `start-point.json` | per-attempt start extraction (demo + map cross-check) |
| `a5_rebuild_cmds.py` → `getspeed-aligned.cmds`, `alignment-meta.json` | time-aligned input/state pairing (the 41-drop fix) |
| `a5_validate_replay.py` → `human-replay.json` | the PASS validation: anchored + free-run + per-attempt table + winning arc |
| `a5_launch_harness.py` → `sweep-results.json` | point-goal harness (deployed law verbatim) + the 162-config sweep |
| `a5_offramp_decomposition.py` → `offramp-decomposition.json` | the sub-skill failure analysis |

Caveats: (i) sim-vs-live lip-local bias from A4 (live measured +8–14%
FASTER than sim at dm3 lips) — favorable direction, carried; (ii) the
harness pins the circle direction per protocol (the deposit-fall weave
otherwise randomizes it — measured and disclosed); (iii) `sweep-results.json`
holds all 4860 per-attempt records for re-analysis.

## 9. Round 2 pre-registration — terminal carve release (written BEFORE the scored run)

**Variant** (§7.1, the human's actual move): launch armed → orbit as
deployed; **ARM** (latched, never disarms) when grounded AND d_lip ≤
carve_d AND vh ≥ carve_vh — no lower d_lip bound, so a grounded lip-edge
tick arms and releases via the backstop, converting a round-1 walk-off
into a last-instant jump; while armed hold the wishdir **carve_deg toward
the target side of the velocity** (side recomputed per tick; jump
suppressed — a carve IS a swept wishdir, it keeps ground-building);
**RELEASE** (jump, aimed at the target — the harness emits the jump bit
itself, because the deployed herr>35° gate would turn a poor-aim backstop
release into the round-1 silent walk-off) when |herr_to_target| ≤ tol OR
d_lip ≤ 8. The carve REPLACES the deployed speed+aim release (deferred
exactly like round 1's lip gate); the deployed 3 s LAUNCH_TIMEOUT
safeguard is kept verbatim (carve stands aside past it; such releases are
recorded rule=timeout). Implemented at the harness seam (`_carve_step`,
guard-first, zero RNG/compute when off); `mode23_sim.py` untouched.
Mutually exclusive with lip_gate_dmax.

**Fixed from round 1's data:** launch_vh 430 (arms the circle earliest;
the wall-slide family's cell), launch_angle 50 (its dominant sub-cell),
**sign +1** (the 430–435 wall-slide release family — the bend target — is
sign +1 in **122/122** recorded cases, re-mined from the committed
`sweep-results.json.gz`), swing 8 (now scopes only the pre-arm defer
check), lip_gate off. **New evidence used for the grid:** round-1
lip-strip crossing vh is **p50 394.9 / p90 424.8** (same artifact), so
carve_vh reaches down to 410 — a 455 floor would arm almost never and
re-create the 93% never-release failure.

**Grid:** carve_d {35, 55, 80} × carve_deg {45, 52, 60} × carve_vh
{410, 430, 450} × tol {3, 6, 10} = **81 configs × seeds 1..30 = 2430
attempts**, 25 s budget, ~20–25 min at the measured ~7500 attempts/h.
Grounding: carve_d — releases >~35 qu early land in the gap, and bending
a tangential entry takes ~45–90 qu of lead at ~5–7°/tick; carve_deg —
ground-accel equilibrium v ≤ 320/cosθ = 452/520/640, tests the
speed-ceiling vs turn-rate trade; tol — the to-target heading from the
strip spans ~−3° (mid-band) to ~−12° (north wall; aim-at-point from the
wall IS the spec's −8..−12° bend, so the herr rule and the bend agree).
Release rule is herr-only (the ledger's primary rule) — no
absolute-heading-band dimension. Mechanism smoke probes (≤5 seeds,
non-scored) allowed; the single scored block is the sweep above.

**Pre-committed:** best config ≥ 5/30 LANDED → live phase (KTX additive
default-off cvars + ztricks.bot + spawn-snap per ticket S1/S2). Best
1–4/30 → ONE pre-registered extension: top-3 configs × seeds 1..100;
≥ 10/100 → live, else off-ramp. All 0/2430 → decomposition + escalate
(§7 variant 2 or a human-trace-guided release). Secondary funnel,
reported regardless of landings: armed share, release-rule histogram,
release d_lip/vh/heading/y vs the round-1 wall-slide family — did the
carve bend the release −8..−12° and lift vh toward ~470?

**Known risks, accepted into the round** (measured, not silently
patched): early-align SHORT (herr ≤ tol can fire at d_lip 40–80 with
insufficient carry — the spec has no lip window on the herr rule; a lip
window composed into the herr rule is the named round-3 candidate);
under-arming if even 410 rarely coincides with the window (armed-share
makes it one-number diagnosable); tangential/west entries bending up to
~180° (recorded via armed_herr); d_lip backstop overshoot at 10–21 ms
tick granularity.

**Refactor safety, run before this block (2026-06-10):**
`carve-selfcheck` **PASS (10 checks)**; `baseline-check` **PASS — 3
round-1 cells × 30 seeds byte-identical** to the committed
`sweep-results.json.gz` with carve off; unit suite **274 tests OK**;
mechanism smoke (cd55/cg52/cv430/ct6, seeds 1..3): arms at d_lip 22–50,
carves 1–2 ticks, releases rule=herr with the jump bit ON the lip row
(lip vh 437.6–441.1, heading −6.9..−7.3) — the walk-off failure mode is
mechanically gone; all three short of the far floor, as the funnel
predicts for a 440-speed wall release.

## 10. Round 2 result — FIRST LANDINGS EVER; off-ramp fires at 9/100 (bar was 10)

**Scored sweep (81 × 30 = 2430):** 9 configs landed **exactly 1/30** —
every one of them `carve_deg 52 × carve_vh 450` (all three carve_d, all
three tol: the arm, not the carve length, decides). **The first landings
in the project's history** — round 1 was 0/4860.

**Pre-committed ladder:** best 1–4/30 → the registered extension, top-3
× seeds 1..100: **ct3 8/100, ct6 9/100, ct10 6/100** (armed 34/100 in
all three). Bar: ≥ 10/100 → live. **Best 9/100 < 10 → the off-ramp
fires.** No goalpost moves: the wall is recorded, one seed short of the
bar.

**What the funnel proves** (`carve-offramp-decomposition.json`):

| sub-skill | round 1 | round 2 (carve) |
|---|---|---|
| BUILD | works (48% reach target) | works (100% reach 430; max_vh p50 482.9) |
| RELEASE | fails structurally — 93% never release, 85 by timeout | **fixed**: 1917/2430 release (79%), 0 by timeout, 82% within 45 qu of the lip, heading bent to p50 −7.1° (wall-slide was 0.0°), jump bit ON the lip row |
| ARM→SPEED | — | **the new bottleneck**: release vh p50 433.5; every one of the 23 landings released at **453.0–459.7** — the trick needs ≥ ~453 at release, and the orbit passes the arm window at ≥ 450 only ~34% of attempts |
| ARC | never reached | SHORT 1718 / NO-JUMP 513 (the un-armed walk-offs) / Y-OUT 81 / WOULD-LAND 118 (ballistic estimate; 9 estimated vs 1 real landing per cv450 cell — the flat-carry +15 qu estimate is ~8× optimistic at the band edge, real flights clip the y-band sanity check or fall at the far lip) |

**Plain words:** the carve fixed the release — the bot now bends the
wall-slide by −7..−12° exactly as designed and jumps on the lip. What it
did NOT do is lift release speed: the herr rule fires after ~2 carve
ticks (the wall entry is already nearly aimed), long before the carve's
ground-build raises 433 toward 453+. Landing is now a pure speed-at-arm
lottery: arm ≥ 450 (34% of attempts) → ~26% land; arm below → SHORT,
always. The human's answer is visible in the same numbers: their lip
speed was 475.

**Escalation candidate for round 3 (NOT run, pre-register first):** a
release speed floor — while armed, keep carving (the carve IS the
build) until `vh >= release_vh` AND the aim rule; grid release_vh
{450, 455, 460} × carve_d {55, 80} (cd mattered nothing at arm but sets
the build runway once the floor holds the carve open), tol fixed 6,
d_lip backstop verbatim. Risk to measure: held carves bending past the
target heading and re-orbiting (the per-tick side flip bounds it) and
running out of platform (the d_lip ≤ 8 backstop converts those to
low-speed jumps, recorded honestly as SHORT).

| file | what |
|---|---|
| `a5_launch_harness.py` (carve-* modes) | the carve variant + selfcheck + baseline-check |
| `carve-sweep-results.json.gz` | all 2430 per-attempt records |
| `carve-extension-results.json` | the registered top-3 × 100 extension |
| `carve-offramp-decomposition.json` | funnel + arc classes above |

Caveats carried: sim-vs-live lip bias (A4, favorable), pinned circle
direction (+1, the family's), ballistic WOULD-LAND is an estimate (now
measured ~8× optimistic at the band edge — trust LANDED only).
