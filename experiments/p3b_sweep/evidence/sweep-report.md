# P3b A2 — pre-registered offline sweep: corner conversion + launch-edge speed (issue #74)

**VERDICT (sim-only; rankings, not absolutes): the swept constants lift the
bridge-approach launch-plane speed from the live config's 445.3 to a best
distinct median of 470.1 qu/s (+5.6%), and rung-1 reach / Gate-2 conversion
improve up to ~2x — but NO configuration carries >=526 reliably. The 526
objective is reached only as 1-seed-in-30 tail events (48 of 1986 configs,
best single seed 554.5; no candidate's own max reaches 526). The
pre-registered off-ramp ("no config records ANY seed >= 526") therefore does
NOT fire; the 4 transfer candidates are declared in §6, with the
median-vs-tail tension flagged for A3 (#75) in §7.**

Sections 1-3 (geometry resolution + pre-registration) were locked in the
loop ledger BEFORE the first sweep run; sections 4+ are the results.

Date: 2026-06-10. Simulator: `scripts/mode23_sim.py` (A1 calibration gate
FAITHFUL, PR #83); runner `scripts/mode23_sweep.py`. All metrics imported from
`scripts/route_metrics.py` / `scripts/verify_route.py` — no second metric
implementation. Sim trust bounds (binding on every claim below, from the A1
calibration report): sim is +5.8% fast on arrival-tws and −0.20 on reach rate
vs live point estimates; sweep outputs are RANKINGS — winners must be
confirmed live (ticket A3 #75); near-tie marker selections (~4.6% argmax
mismatch band) are not resolvable offline.

---

## 1. STEP 0 — objective geometry resolution (also D1 #77 pre-check (a))

The sprint headline target is >=526 qu/s at the dm3 sng_to_rl LAUNCH EDGE
(census final hard gap: edge (1473.1, 47.5, 3.6) -> land (1614.8, 362.9,
-60.4), required 525.3, human 528.6). Resolved OFFLINE, before
pre-registering, from the live FBMARKER graph + current-c5-only sim probes
(no sweep config was run):

**The directed walkable route to RL (pin marker 1) does NOT traverse the
bridge launch markers 72/110 and does NOT cross the launch-edge plane.**

- Graph: the Dijkstra route (frogbot's own edge times) from the sng_to_rl
  start runs spawn -> teleporter -> PIT FLOOR (z=-168: markers 156/79/82/37/
  80, under the bridge) -> NE stairs (73/70/74/68/69) -> RL. Its only
  along-plane sign change happens at z=-168, outside the A0 metric's z-window
  (±100 of +3.6) and corridor (160 qu).
- Sim (10 pin-RL seeds, c5): 0 qualifying crossings, 0 bridge-marker
  contact, `edge_speed` = None on every seed (3/10 reached RL walkably).
- **D1 #77 pre-check (a): NO** — without a new leap link (D1's one free
  marker slot, live max 299/300), no directed attempt ever crosses the edge.

### The pre-registered surrogate (rung B)

**Bridge-approach launch-plane speed**: `route_metrics.edge_speed` (A0
metric, constants UNCHANGED) over `legit_segment(rows, ())` truncated at the
first arrival within 60 qu (3D, REACH_RL convention) of the pin nav.
Protocol: spawn m75 org (1959, -425, -24) (south-walkway top, the P1
stair-test area), pin marker 148 (one hop PAST tip marker 110: (1354, 218,
24), +48z), budget 20.0 s.

Why this protocol:

- The directed route 75 -> 77 -> 81 -> 83 -> 84 -> 72 -> 110 -> 148 runs the
  full bridge northbound; the 72->110 leg crosses the census plane (the plane
  lies ~7 qu south of 110) at full weave speed on every tip arrival —
  observed crossings at z ≈ -24..19, cross-track 119-138 < 160.
- Pinning 148 instead of 110 keeps the crossing OUTSIDE the 60-qu arrival
  sphere: a 110 pin would truncate before the crossing, and an untruncated
  run pollutes the LAST-crossing semantics with goal-hover re-crossings
  (probe seed 9: 467.7 approach vs 301-326 hover re-crossings).
- c5 explore (20 seeds, run before pre-registration, current config only):
  13/20 crossings, median 445.3, max 472.2.
- A3 can measure the SAME quantity live: the spawn-snap and fixed-goal cvars
  exist, and the conditioning is a pure function of trace + census gap.

Declared caveats: corridor 160 / z-window 100 are A0 constants and are NOT
widened — wide-weave configs can arrive with the crossing just outside the
corridor (probe seed 6: cross-track 166, REJECTED), so arrivals are reported
next to crossings; the surrogate is NOT the leap itself — ANY ">=526" claim
from this sweep is surrogate-based and sim-fast-biased, and only A3 measures
the real thing live.

## 2. Pre-registration (ledger rows written before the first sweep run)

**Stage-1 grid (full factorial, 1944 configs):**

| dim | values | live | transfer |
|---|---|---|---|
| pass_r | 100, 130, 170 | 130 | cvar `k_fb_moveprobe_s23_pass` |
| numerator | 5, 9, 16, 26 | 9 | cvar `k_fb_moveprobe_accel_numerator` |
| swing | 6, 12, 24 | 12 | cvar `k_fb_moveprobe_s21_swing` |
| turn_thresh | 25, 35, 50 | 35 | cvar `k_fb_moveprobe_s21_turn` |
| (corner_thresh, corner_aim) | (58,68), (45,85), (75,50) | (58,68) | cvars `k_fb_moveprobe_s21_corner_thresh` / `_corner_aim` |
| governor | none, vel (c2), pos (c3) | none | CODE change |
| carrot_lead | 0.0, 0.3 s | 0.0 | CODE change |

Governor = the two live-rejected designs re-implemented per the ledger on the
surviving C apply/clear block (`bot_movement.c:3849-3876`): engage at carrot
handover when it re-aims and |leg turn| > 60°; vel compares the new-leg
bearing to the VELOCITY yaw, pos to the positional old-leg bearing and never
engages on climb legs (dz > 18); while engaged (< 2.0 s and marker unchanged):
straight-aim override + no hop. Fixed at calibrated values: bootstrap 25,
look 500, carrot guard = c5 delegation-exact, delegation 18/280/3.0,
sv_maxspeed 320, cadence/think/marker-frame models.

**Per config:** rung A = the exact A1 protocol (sng_shortcut2: spawn
(385.5, 614.25, 56), pin 191, 48.1 s, seeds 1..30, `analyze_attempt`
conditioning) -> reach, arrival-tws median (None-safe), Gate-2 corner stat =
pooled pre-arrival deduped linked-hop exits from 207 (conversion = share ->
191; 206->207 diagnostic). Rung B = the surrogate above, seeds 1..30. SAME
seeds across all configs (paired comparisons). None is never averaged as 0.

**Ranking (applies unchanged to the final stage-1 ∪ stage-2 table):**
eligible iff rung-A reach >= 12/30 (sim-c5 baseline, A1) AND rung-B edge_n >=
8/30 (median stability); sort by (edge_median desc, corner conversion desc
with None last, config id asc). Ineligible configs listed, not ranked.
**Transfer candidates:** ranks 1-3 + mid rank max(4, ceil(N_ranked/2));
N_ranked < 4 -> escalate.

**OFF-RAMP:** fires iff NO config (ranked or unranked) records ANY seed with
edge >= 526.0 -> control-law ceiling finding -> ESCALATION (issue stays
open). If >=526 is reached ONLY by reach-floor-failing configs -> flag loudly.

**Stage 2 (<= 300 configs, same seeds/protocols/ranking):** rank stage-1 dims
by marginal range of mean edge_median over ranked configs; top-3 dims; local
grid around the rank-1 config = {leader, leader±step} per chosen dim (steps:
pass_r 20, numerator 3, swing 4, turn 7, corner ±(8,8), lead 0.15; governor
has no step — its refinement is the top-8 rule: if a governor config ranks
top-8, add governor threshold {45,60,75} × timeout {1,2,3} at the leader's
constants); dedupe vs stage 1, cap 300.

**Anchors (harness validity, not outcome gates):** (i) the live point must
reproduce A1 sim-c5 12/30 + tws 279.4 exactly; (ii) governor-vel at live
constants is expected to crater rung-A reach (live c2 4/10 vs carrot-only
8/10) — directional port sanity.

## 3. Harness verification (before stage 1)

- Params refactor parity: `calibrate --config c5 --seeds 30` post-refactor is
  **byte-identical** to the committed A1 result (summary AND all 30 per-seed
  records; reach 12/30, arrival-tws median 279.4).
- Unit suite: 240 tests OK (53 new/updated: governor engage/apply/clear,
  carrot_lead, params parity, grid, ranking floors + None handling,
  candidates rule, corner helpers, edge-objective conditioning, stage-2 rule).

## 4. Results

Stage 1: all 1944 configs × 60 attempts (30 rung-A + 30 rung-B), wall ~69 min
at 12 workers (one harness-side task restart at config ~1703; the jsonl
resume continued exactly where it stopped — no attempt was re-run or lost).
Stage 2: 42 configs per the pre-registered rule (top-3 marginal dims =
numerator/turn_thresh/pass_r around the leader + pos/vel governor
threshold×timeout grids; plan in `stage2-plan.json`), wall 1.5 min. Total
sweep compute ≈ 71 min — inside the 2.5 h cap.

**Union table: 1986 configs → 726 ranked (663 distinct trajectory
signatures), 1260 unranked** (reach < 12/30 or edge_n < 8/30). Full table:
`ranked.md` / `ranked.json`; per-config aggregates:
`stage{1,2}-aggregates.jsonl`.

### Anchors

- **(i) Live point PASS, exact:** `p130_n9_s12_t35_c58-68_gnone_l0` inside
  the sweep reproduces A1's sim-c5 numbers identically — reach 12/30,
  arrival-tws median 279.4. Its rung-B baseline: edge median 445.3 (edge_n
  21/30, max 484.4) — and 445.3 equals the pre-registration explore median.
- **(ii) Governor crater NOT reproduced** at live constants: governor-vel
  there scores reach 12/30 (= governor-none), conv 0.313. Disclosed, with
  three compatible explanations: live c2 compounded the governor with the
  BROAD carrot guard (this sweep rides the c5 delegation-exact guard
  everywhere); live n=10's binomial CI for 4/10 = [0.12, 0.74] contains the
  sim's 0.40; and closed-loop handover-instant engagement is rarer than the
  live log's "chronically >60° off" suggested (the weave crosses the bearing
  line twice per cycle). The governor rows remain valid as RANKINGS; their
  aggregate marginal effect is near-zero (3.8 qu/s).

### What moves the objective (marginal range of mean edge median, ranked configs)

numerator **140.5** > pass_r **130.5** > turn_thresh **127.5** >> corner
pair 15.1 > swing 9.7 > governor 3.8 > carrot_lead 3.4.

- **numerator 5 dominates** (the turny low-numerator weave carries route
  speed; accel-optimal n26 loses ~140 qu/s of median — the K≈26 straight-line
  optimum does not survive corners).
- **turn_thresh dominates the reach floor**: t25 passes the floor on ~2% of
  configs vs ~86-96% at t35/t50 (corner mode + jump suppression on small
  bearing errors grounds the weave everywhere).
- swing 24 + corner (45,85) (earlier, harder corner response) tops the
  family; pass_r 170 collapses crossing counts (edge_n 0-7/30: the early
  handover cuts the corner outside the metric corridor — censoring visible
  as arrivals >> crossings).

### The 526 objective: tail-only

- 48/1986 configs record ≥1 seed with edge ≥ 526.0 (7 of them ranked); best
  single seed **554.5** (`p130_n5_s12_t35_c45-85_gnone_l0`, ranked #285,
  median 446.5, reach 15/30, conv 0.349). Spikers concentrate at pass_r 130
  with t25/t35 and n5/n9.
- **No config's median (or even per-config max among the top-median
  candidates) reaches 526.** Median ceiling across all 1986 configs: 470.1.
- Off-ramp condition (pre-registered: NO config records ANY seed ≥526) does
  not fire. The ceiling-shaped caveat stands anyway: within this control-law
  family and these 7 dimensions, ≥526 at the plane is a ~1/30-attempt tail
  event, not a steady state — consistent with the calibration report's named
  binding constraint (physics at the precision gates, not nav).

## 5. Top of the final ranked table (distinct trajectory signatures)

| # | config | edge_med | edge_n | edge_max | reachA | conv207 (n) |
|---|---|---|---|---|---|---|
| 1 | `p100_n5_s24_t35_c45-85_gpos60xT_l0.3` (T=1,2,3 per-seed IDENTICAL) | 470.1 | 14/30 | 494.1 | 16/30 | 0.296 (125) |
| 2 | `p130_n5_s24_t50_c75-50_gvel60x2_l0` | 468.8 | 13/30 | 511.0 | 14/30 | 0.323 (96) |
| 3 | `p100_n5_s24_t35_c45-85_gpos75xT_l0.3` (T triple identical) | 468.4 | 16/30 | 494.1 | 17/30 | 0.319 (116) |
| 4 | `p100_n5_s24_t35_c45-85_gnone_l0.3` | 468.4 | 16/30 | 494.1 | 20/30 | 0.312 |
| 5 | `p100_n5_s24_t35_c45-85_gpos45x2_l0.3` (triple identical) | 468.0 | 12/30 | 485.9 | 15/30 | 0.367 |
| … | live baseline `p130_n9_s12_t35_c58-68_gnone_l0` (rank 310) | 445.3 | 21/30 | 484.4 | 12/30 | 0.274 (135) |

Best **cvar-only** configs (governor none, lead 0 — deployable live without
a rebuild): rank 16 `p100_n5_s24_t35_c45-85_gnone_l0` (465.9, reach
**26/30**), rank 19 `p100_n5_s24_t35_c75-50_gnone_l0` (464.4, reach
**28/30**). Best Gate-2 conversion among ranked: 0.441
(`p100_n9_s12_t50_c58-68_gpos60x2_l0`) vs live 0.274.

## 6. The 4 transfer candidates (declared BEFORE any live run; A3 #75 slots)

The literal pre-registered rule (ranks 1-3 + mid 363/726) returned three
PER-SEED-IDENTICAL configs for ranks 1-3 (`gpos60x1/x2/x3`: the governor
escape timeout never binds — every engagement ends by marker-change in
< 1 s, so 1.0/2.0/3.0 s produce the same 60 trajectories; the A1 c4≡c5
phenomenon). Deploying three copies would waste two live slots, so the
DECLARED top-3 are the distinct-signature top-3 with the canonical (closest
to the live-tested governor constants, timeout 2.0) representative; the mid
slot keeps the literal rule's pick verbatim. Both rule outputs are in
`candidates.json`; the literal ids are also in `ranked.json`.

| slot | config | cvars (k_fb_moveprobe_*) | code changes | sim numbers (rung B / rung A) |
|---|---|---|---|---|
| top-1 | `p100_n5_s24_t35_c45-85_gpos60x2_l0.3` | s23_pass **100**, accel_numerator **5**, s21_swing **24**, s21_turn **35**, s21_corner_thresh **45**, s21_corner_aim **85** | pos-governor (engage at carrot handover, positional old-leg vs new-leg bearing > **60°**, escape **2.0 s**, no engage on climb legs dz>18) + carrot_lead **0.3 s** | edge 470.1 med / 14n / 494.1 max; reach 16/30, tws 278.0, conv 0.296 |
| top-2 | `p130_n5_s24_t50_c75-50_gvel60x2_l0` | s23_pass **130**, accel_numerator **5**, s21_swing **24**, s21_turn **50**, s21_corner_thresh **75**, s21_corner_aim **50** | vel-governor (engage at handover, velocity-yaw vs new-leg bearing > **60°**, escape **2.0 s**) | edge 468.8 / 13n / 511.0; reach 14/30, tws 286.2, conv 0.323 |
| top-3 | `p100_n5_s24_t35_c45-85_gpos75x2_l0.3` | as top-1 | as top-1 but engage threshold **75°** | edge 468.4 / 16n / 494.1; reach 17/30, tws 273.3, conv 0.319 |
| mid (lit. rank 363/726) | `p100_n9_s24_t50_c45-85_gnone_l0` | s23_pass **100**, accel_numerator **9**, s21_swing **24**, s21_turn **50**, s21_corner_thresh **45**, s21_corner_aim **85** | **NONE — cvar-only deploy** | edge 440.8 / 24n / 478.1; reach 23/30, tws 269.1, conv 0.411 |

All four pass the reach floor (14-23/30 vs the 12/30 baseline — no
"top-3 regress reach" flag). None of the four ever recorded a seed ≥ 526.

## 7. Trust bounds and flags for A3 (#75)

- **Rankings, not absolutes** (A1 bounds): sim is +5.8% fast on tws and
  −0.20 low on reach rate vs live point estimates. Expect live edge medians
  roughly ~5-6% below sim (≈ 443-445 for the top candidates if the tws bias
  transfers) and live reach plausibly HIGHER than the sim's 14-23/30.
  The edge metric itself has no measured live bias yet — A3 measures it.
- **Surrogate flag:** every number here is the STEP-0 surrogate (pin-148
  bridge approach), not the leap: no leap link exists in the graph (D1 #77
  adds it; pre-check (a) = NO is answered in §1). A 526 in this report is a
  526 across the census plane on the approach, in sim.
- **Median-vs-tail tension (flagged loudly):** the pre-registered ranking
  optimizes the MEDIAN; the sprint's binary goal (one ≥526 attempt) is a
  TAIL event that only mid-median configs exhibit (e.g.
  `p130_n5_s12_t35_c45-85_gnone_l0`, max 554.5 at 1/30 seeds, cvar-only). If
  A3 wants to maximize P(any attempt ≥ 526) rather than learn the sim's
  error structure, the spiker family (pass_r 130, n5/n9, t25/t35, c45-85)
  is the alternative deploy — user's call, outside the pre-registered slots.
- **Corridor censoring:** edge_n < arrivals for wide-weave/early-handover
  configs (crossings just outside the fixed 160-qu corridor are rejected,
  e.g. cross-track 166). The A0 constants were not widened; arrivals are
  reported next to crossings so the censoring is visible.
- **Governor port caveat:** anchor (ii) not confirmed (no reach crater at
  live constants, n=30 vs live n=10 — see §4); governor deltas everywhere
  are small. Candidates 1-3 carry governors with +1.7..+0.4 median over
  their governor-none siblings — within seed noise; the cvar-only siblings
  (§5) are the fallback if A3 wants to avoid the KTX rebuild.
- **Deployment mechanics:** governor + carrot_lead are CODE changes
  (re-add the engage block, ~15 lines at the old bot_movement.c:3640 site,
  plus a lead term in the carrot trigger; suggest cvars
  `k_fb_moveprobe_s23_prec_mode` (0/1=vel/2=pos), `_s23_prec_thresh`,
  `_s23_prec_timeout`, `_s23_lead`). The six constant dims are settable via
  existing cvars (§6 table). Live protocol for the surrogate: matchless +
  `k_fb_moveprobe_spawn_origin "1959 -425 -24"` + `k_fb_moveprobe_fixed_goal
  148`, 20 s window, score with `route_metrics.edge_speed` over
  `legit_segment` truncated at first 60-qu arrival at marker 148's nav —
  identical conditioning to §1.

## 8. Reproduction

```
python scripts/mode23_sweep.py grid                      # 1944, live point included
python scripts/mode23_sweep.py sweep --stage 1 --workers 12
python scripts/mode23_sweep.py sweep --stage 2 --workers 12
python scripts/mode23_sweep.py report
python -m unittest discover -s tests -p "test_*.py"      # full suite
```

Inputs identical to A1 (committed FBMARKER dump fallback, dm3.bsp, census).
Outputs: `artifacts/p3b-sweep/` (gitignored raw) with committed copies here:
`ranked.json`, `ranked.md`, `candidates.json`,
`stage1-aggregates.jsonl`, `stage2-aggregates.jsonl` (per-seed rung-A
records stripped for size; rung-B per-seed edge values retained).
