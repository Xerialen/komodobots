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
| ARC (fly and land) | never reached | every lip crossing classed SHORT (4593: dribble-offs falling at vh p50 395, no jump) or Y-OUT (267: the wall-line flights at y 3824, ~4–20 qu north of the far platform edge); **0 WOULD-LAND states in 4860 attempts** |

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
