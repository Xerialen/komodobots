# dm3 trick-route difficulty ladder (Phase 0.5 census)

Built from the 11 parsed human trajectories in `artifacts/replay/dm3_*.cmds`
(per-frame origin + velocity + angles + buttons at ~77 fps) probed against the
`dm3.bsp` worldmodel via `scripts/bsp_geom.py`. Machine-readable metrics:
`census.json` (this dir). Generator: `census.py` + `score.py` (this dir).

## Sanity anchor — PASSED

The sng_to_rl analysis reproduces the validated `dm3_jump_geom.json` result:

| metric | anchor | this census |
|---|---|---|
| route arc-length | ~4085 qu | 4085 qu |
| active-mean speed | ~425 | 424.9 |
| hardest gap required speed | ~526 | 525.3 |
| human speed at launch edge | ~528 | 528.6 |
| margin | ~2 | 3.3 |

(Edge frame fires 1 frame earlier than the reference — 510 vs 511 — because
the census uses a relative >100 qu floor-drop criterion vs the reference's
absolute z < -200; required/human speeds agree to <1 qu/s.)

## Composite score (0–10, higher = harder)

`score = 10 × (0.38·speed + 0.27·precision + 0.18·technique + 0.09·turns + 0.08·volume)`

- **speed (heaviest, per spec)** = 0.7·margin-tightness + 0.3·speed-demand.
  Margin-tightness = `clamp01((35 − tightest ballistic margin)/35)`: a route
  whose binding gap leaves <5 qu/s of slack saturates this term; ≥35 qu/s of
  slack zeroes it. Speed-demand = `clamp01((max required speed − 320)/330)`:
  320 is flat run speed (no bunny needed), 650 saturates. Margins from
  `t_obs`-sourced required speeds are excluded (tautological, see caveats).
- **precision** = `clamp01((12000 − smallest hard-gap landing platform qu²)/12000)`.
  Platform measured by flood-filling an 8 qu grid (±80 qu, floor within
  ±20 qu of the landing floor) around the human landing point.
- **technique** = `clamp01(N/5)`, N = teleporters + water segments + ledge
  climbs + rocket boosts + lift/bmodel rides. (All detected boosts were
  verified against the attack button bit in the command stream — they are
  genuine rocket jumps, not parser noise.)
- **turns** = 0.6·`clamp01(sharpest/360°)` + 0.4·`clamp01(count>45°/12)`.
- **volume** (minor tiebreak) = `clamp01(hard gaps/8)`: nine consecutive
  cruxes are harder than one, even when each is individually moderate.

A "hard" gap = undershoot drops >100 qu below the landing ledge (death/route
reset); "soft" gaps (you just land lower) still bind the route but cost less.

## The ladder (easiest → hardest)

80/80 baselines = the two numbers `verify_route`-style scoring needs:
human **active-mean speed** (qu/s, frame 0 → arrival) and **route arc-length**
(qu, full xy cumulative, verify_route convention — includes teleporter
displacement).

| # | route | score | active-mean | arc (qu) | tightest margin | max req speed | min landing (qu²) |
|---|---|---|---|---|---|---|---|
| 1 | sng_shortcut2 | 3.61 | **374** | **981** | +21.9 | 437 | 3840 |
| 2 | hilljump | 4.00 | **404** | **3525** | +10.6 | 511 | 10816 |
| 3 | rl_to_ya | 4.38 | **474** | **2071** | +9.8 | 728 (boosted) | 14784 |
| 4 | ring_to_mega | 4.78 | **483** | **2414** | +0.3 | 537 | 10048 |
| 5 | ra_jumps | 5.58 | **233** | **2592** | +11.1 | 419 | 6144 |
| 6 | mega_to_rl | 5.58 | **485** | **3466** | +10.0 | 626 | 6912 |
| 7 | rl_to_bridge | 5.63 | **300** | **3589** | +4.2 | 511 (boosted) | 14400 |
| 8 | sng_shortcut | 5.71 | **448** | **2104** | +8.8 | 509 | 3840 |
| 9 | sng_to_rl | 5.97 | **425** | **4085** | +3.3 | 525 | 5376 |
| 10 | mega_to_window | 6.12 | **460** | **1264** | n/a (RJ-only) | 601 eff. | 4608 |
| 11 | sng_jumps | 8.45 | **298** | **6222** | −1.4 (noise ≈0) | 445 | 3712 |

## Per-route summaries

**1. sng_shortcut2** (3.65 s, peak 459) — One clean 238 qu flat hop in the SNG
yard onto an 88×96 ledge, +21.9 margin at a modest 437 required. No
teleporter, no turns of note. The crux is only the small landing pad; this is
the natural first rung for the bot.

**2. hilljump** (9.43 s, peak 529) — Five consecutive 203–251 qu leaps over
the 256-deep hill pit, each with +10–27 margin at 372–511 required and
generous ~10800 qu² landings. No technique elements; pure repeatable
run-up + jump. Crux: consistency across five attempts, not any single jump.

**3. rl_to_ya** (5.2 s, peak 812!) — A descending 304 qu leap that needs 678
at the edge (the highest ballistic speed demand in the census; human carried
688), then a rocket boost up to YA. Landing zones are huge (≥14700 qu²).
Crux: building ~690 edge speed; everything else is forgiving.

**4. ring_to_mega** (6.0 s, peak 551) — The 597 qu descending mega-leap with
the **tightest speed margin of the whole census: +0.3 at 536 required**.
Big landing (10048 qu²), one warm-up hop, few turns. Crux: pure edge-speed —
arrive even 1 qu/s slow and the leap dies in the 180-deep pit.

**5. ra_jumps** (13.8 s, peak 440, active-mean only 233) — Slow technical
climb to RA: a lift ride (invisible to the BSP oracle — see caveats), two
short shaft-crossing hops from near-standstill, sharpest cumulative turn of
the set (496°). Crux: navigation and precision from low speed, not speed.

**6. mega_to_rl** (8.05 s, peak 659) — Speed route: opens with a 412 qu leap
requiring 626 (margin +10, soft), then a rocket jump (vz 790) up 269 z, then
a 366 qu chasm leap (+52). Crux: sustaining 630+ into the first leap and the
RJ that follows; landings are mid-size.

**7. rl_to_bridge** (13.2 s, peak 547) — The reverse bridge route: **two**
rocket-boosted leaps from the RL ledge up (+45–57 z) across the 368-deep
chasm — at launch the human was ~162 qu/s short of the unboosted requirement;
the rocket makes the difference. 4 ledge climbs, 8 big turns. Crux: RJ
execution + timing over the chasm, twice.

**8. sng_shortcut** (5.72 s, peak 530) — One jump, but a nasty one: 209 qu at
509 required (+8.8 margin) onto the same small 88×96 (3840 qu²) ledge as
sng_shortcut2. Crux: speed AND precision in a single leap — sng_shortcut2's
landing at sng_to_rl-level speed pressure.

**9. sng_to_rl** (8.99 s, peak 535) — The validated wall: 4085 qu through the
SNG teleporter, a 199 qu void-rim leap (+11), then the 346 qu chasm leap
requiring 525 with **+3.3 margin** onto a 112×48 sliver under the bridge
(5376 qu², smallest hard landing outside the sng routes). Crux: carrying
~528 to the launch edge after 4000 qu of clean navigation.

**10. mega_to_window** (3.8 s, peak 714) — A **double rocket jump**: ground
RJ at mega (vz 646), then a second mid-air rocket boost at the apex, +269 z
across 732 qu into the 96×48 window slot (4608 qu²). Human edge speed was 53
below the effective need — the mid-air boost closes it. Crux: two-rocket
execution + tiny landing; speed-margin analysis doesn't even apply.

**11. sng_jumps** (22.25 s, peak 477) — A 6222 qu compilation of **9 hard
void-rim hops** with the smallest landing pads of the census (3712 qu²,
multiple 88×88–96 ledges), 6 ledge climbs, 20 >45° turns, sharpest 456°.
No single gap is extreme (margins +6.5 to +89), but the bot must chain ~10
precision landings without one reset. Crux: sustained precision over volume.

## Data-quality caveats

1. **The .cmds files are fully sufficient** — per-frame origin, velocity,
   view angles, move commands and buttons at ~77 fps. Nothing had to be
   approximated from commands alone.
2. **bmodel blindness**: `bsp_geom.py` parses only the worldmodel hull, so
   lifts/plats/doors are invisible — a player riding a lift reads as
   "airborne over void". Detected and excluded via kinematics
   (near-zero vz "flights" >0.8 s → `bmodel_rides`); **ra_jumps** is the
   route most affected and its gap inventory is the least trustworthy.
3. **t_obs-sourced required speeds are tautological**: when the ballistic
   model can't apply (boost mid-flight, model/observed flight-time mismatch
   >35%), required = span / observed flight time ≈ the human's own speed, so
   margin ≈ 0 by construction. These are reported but excluded from scoring
   (e.g. mega_to_rl's −2.6 rim-skim).
4. **Small negative margins are measurement noise**, not impossibility:
   speed is sampled at the first over-void frame, and QW air-control gains
   speed mid-flight (sng_jumps −1.4, mega_to_rl −2.6).
5. **Landing-area probe is capped** at the ±80 qu grid (max 25600 qu²);
   "large" landings saturate. Tolerance ±20 qu of floor variation; sloped or
   stepped landings under-measure slightly.
6. **Arc length follows the verify_route convention** (sum of consecutive xy
   distances over all frames), so sng_to_rl's 4085 includes the 780 qu
   teleporter displacement; movement-only arc is 3305. census.json carries
   both (`arc_xy_total_qu` / `arc_xy_moved_qu`). The 80/80 baseline numbers
   in the table use the verify_route convention.
7. **Rocket-jump health cost is not modeled** (no health/armor stream in the
   .cmds); RJ routes are scored on execution difficulty only.
