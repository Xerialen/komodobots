# P3b A1 — mode-23 config-5 control-law port over pmove_sim: calibration gate (issue #69)

**VERDICT: FAITHFUL** — sim-c5 reproduces live-c5 behavior within both pre-registered
tolerances, with the seam audit below. The A2 offline sweep (#74) may proceed on this
substrate, subject to the trust bounds in "What bounds sweep trust".

Date: 2026-06-10. Simulator: `scripts/mode23_sim.py` (control law + frogbot nav stub
over the validated `scripts/pmove_sim.py`). All metrics via `scripts/route_metrics.py`
and `scripts/verify_route.py` imports — no second metric implementation.

---

## 1. Comparator recomputation (step one, pre-registered before any sim ran)

The ticket's comparator ("arrival tws median 270") was computed BEFORE the E1 Codex
fix to `time_weighted_speed` (teleport-sized per-tick deltas now excluded). Recomputed
from the raw local c5 block `20260610T013959Z..014904Z` with current main:

| run | verify_route attempts | arriving attempt tws |
|---|---|---|
| 013959Z | ATTEMPTED_JUMP_FELL_SHORT | — |
| 014100Z | AJFS, **REACHED_RL** | 247 |
| 014200Z | **REACHED_RL** | 284 |
| 014301Z | LEDGE_NO_JUMP, AJFS | — |
| 014401Z | LEDGE_NO_JUMP, AJFS | — |
| 014502Z | **REACHED_RL** | 253 |
| 014603Z | AJFS, **REACHED_RL** | 260 |
| 014703Z | LEDGE_NO_JUMP | — |
| 014804Z | **REACHED_RL** | 285 |
| 014904Z | **REACHED_RL** | 268 |

- **Reach 6/10** (unchanged — arrival detection is metric-independent).
- **Arrival-tws median 264.0** qu/s (values [247, 253, 260, 268, 284, 285]); the
  stale 270 was −2.2% off for this block.
- Sensitivity: run-level conditioning (whole run start → first arrival, multi-attempt
  runs as one) gives median 266.1 (+0.8%) — immaterial.

## 2. Pre-registered targets (ledger row written before the calibration block)

- Seed set: seeds **1..30** per config; same seeds for c1/c4/c5. Budget 48.1 s per
  attempt (the live cmd-log window; live runs span t 7.32→55.40).
- **Reach**: sim-c5 reach-rate within the exact binomial (Clopper-Pearson) 95% CI of
  6/10 = **[0.2624, 0.8784]** → n=30 reach count in **8..26**.
- **Speed**: sim-c5 arrival-tws median within ±10% of 264.0 → **[237.6, 290.4]**.
- Conditioning identical to live: `verify_route.segment_attempts` + `classify`
  (REACHED_RL, radius 60), `time_weighted_speed(seg, reach=60)` of arriving attempts.

## 3. Results

| config | reach | reach rate | arrival-tws median | live reference |
|---|---|---|---|---|
| **c5** (deployed: carrot + delegation-exact guard) | **12/30** | **0.40** | **279.4** | 6/10 = 0.60; 264.0 |
| c1 (carrot, no guard) | 14/30 | 0.467 | 274.5 | 8/10 = 0.80 |
| c4 (carrot, broad guard) | 12/30 | 0.40 | 279.4 | 5/10 = 0.50 |

**c5 gate: PASS on both pre-registered criteria.**
- Reach 12/30 = 0.40 ∈ [0.2624, 0.8784] (count 12 ∈ 8..26). ✓
- Arrival-tws median 279.4 ∈ [237.6, 290.4] (+5.8% vs live 264.0). ✓
- No tolerance was widened.

*Re-run disclosure:* the block ran twice. The first pass (c5 15/30 / 279.9, c1
21/30, c4 15/30 — also a PASS on both criteria) preceded five port-fidelity fixes
found in self-review against the C source (ExistsPath path_state overwrite-not-OR;
CanDamage ray direction/endpoints/corner-jitter per combat.c:78; player absmin −1;
goal-hover dir_move keep; jump-toggle static not reset on early-return frames) plus
the Codex P2 zero-arrival fix. The post-fix numbers above are the reported result —
the code was corrected to match the C source, not the outcome; both runs passed and
no tolerance moved.

Sim-c5 arrival times: 6.8–47.7 s (live attempt-level: 5.0–28.4 s). Sim-c5 arrival-tws
values: [241.6, 243.5, 248.8, 253.0, 259.9, 275.7, 283.2, 284.6, 298.3, 302.8, 318.4,
334.5].

**Error structure across configs (the transfer doctrine check):**
- Ordering preserved: sim c1 (0.467) > c4 = c5 (0.40); live c1 (0.80) > c5 (0.60) ≈
  c4 (0.50). The c1 gap is compressed vs live — but neither side resolves it:
  live 8/10 vs 6/10 and sim 14/30 vs 12/30 are both statistically indistinguishable
  at their n. Directionally consistent; magnitude not calibrated.
- c4 ≡ c5 per-seed identical (30/30 same trajectories): inside the 130 qu carrot zone
  the `dist<280` clause is vacuous, so c4/c5 differ only on jump-flagged paths while
  grounded near a climb marker — which never occurred in 30 seeds. Mechanistically
  explains why the live c4-vs-c5 A/B was indistinguishable at n=10.
- Failure-mode mix matches live: sim-c5 failures = 12 ATTEMPTED_JUMP_FELL_SHORT +
  6 REACHED_LEDGE_NO_JUMP; live c5 failures were the same two classes (3 AJFS-ending
  runs + 3 LEDGE_NO_JUMP attempts) — the Gate-1/Gate-2 physics-precision story from
  the P2 decomposition, not nav wandering.

## 4. Port validation (three layers, all against live data)

1. **Law step, tick-for-tick** (carrot disabled, live nav state injected): over the
   38,160 live mode-23 cmds of the 10-run c5 block, the ported law reproduces the
   live view yaw within the log's 0.1° rounding on **97.72%** of ticks and the jump
   button on **99.98%**. Residuals: 0.1°-rounding boundary cases, brief strafe-sign
   desyncs seeded by rounded log inputs (re-converge), and wall-net traces near
   plats (engine traceline sees plat brushes; the sim's hull-0 world trace does not).
2. **Nav selection**: replaying all 2,342 live (touch → linked) selection events
   through the ported PathScoringLogic: **95.4%** deterministic argmax agreement;
   **98.9%** within the g_random ±1 score band (`audit-selection` CLI).
3. **Closed loop**: section 3.

## 5. Seam audit — constants diffed vs the KTX mirror

Source of truth: `C:\Users\benya\.claude\jobs\frogbot-study\bot_movement.c`
(byte-identical to `jobs\7bae6c77\tmp\bot_movement_servexeri.c`, the deployed build's
mirror), mode-23 block at lines 3551–3886.

### Verified constants (mirror line → sim)

| constant | mirror | sim | line |
|---|---|---|---|
| pass_r | 130.0 | `PASS_R=130.0` | 3580 |
| wallhug_deg | 40.0 (dead code — see below) | not ported (dead) | 3581 |
| numerator | 9.0 | `NUMERATOR=9.0` | 3582 |
| bootstrap_deg | 25.0 | `BOOTSTRAP_DEG=25.0` | 3583 |
| look | 500.0 | `LOOK=500.0` | 3584 |
| swing | 12.0 | `SWING=12.0` | 3585 |
| turn_thresh | 35.0 | `TURN_THRESH=35.0` | 3586 |
| corner_aim | 68.0 | `CORNER_AIM=68.0` | 3587 |
| corner_thresh | 58.0 | `CORNER_THRESH=58.0` | 3588 |
| sv_maxspeed | 320.0 | `SV_MAXSPEED=320.0` | 3589 |
| carrot guard dz / dist / flags | 18.0 / 280.0 / `JUMP_LEDGE\|WATERJUMP_\|ROCKET_JUMP` | identical | 3616–3618 |
| delegation condition | same triple | identical | 3693–3694 |
| livelock timeout | 3.0 s | `DELEG_TIMEOUT=3.0` | 3706 |
| wall-net threshold | fwd_open < 0.35 at `look` | identical | 3809 |
| weave rotation | acos(numerator/speed), bootstrap below | identical | 3833–3840 |
| hard-corner rotation | min(herr, corner_aim) | identical | 3824–3832 |
| jump suppression | prec ∥ climb ∥ (herr>turn ∧ ¬pass) | identical (prec/climb dead) | 3868–3876 |
| marker bearing | absmin + view_ofs, per tick | identical (see position model) | 3598–3606 |
| marker_dist_sq | horizontal (x²+y²) | identical | 3605 |
| water fall-through | waterlevel > 1 | identical | 3591 |
| nav fallback | dir_move_, dist=1e18 | identical | 3665–3669 |
| edge trigger | per-slot carrot_done latch | identical | 3615/3637 |
| cmd output | yaw=vectoyaw(proposed), move=(maxspeed,0,0) | identical | 3879–3885 |

The c5 lab cfg (`lab.cfg` of every run in the block) sets NONE of the
`k_fb_moveprobe_s19/s20/s21/s23/accel_*` cvars → the in-code defaults above are what
ran live. Verified by grep over all 10 run cfgs.

Dead code ported as dead: `climb` is constant false in the deployed block (wall-hug
never fires, line 3671/3745); the precision governor never engages in c5 (nothing
sets `prec_marker`; lines 3849–3861 only clear it).

### Emulations and simplifications (what is NOT a line-by-line port)

1. **Zone travel-time tables → exact Dijkstra.** Frogbot's
   `ZoneMarker`+`SubZoneArrivalTime` read precomputed zone/subzone tables; the sim
   runs Dijkstra over the same path graph with frogbot's own edge times
   (`TravelTimeForPath`: dist3D(nav,nav)/320; water legs /224 — `sv_maxwaterspeed =
   0.7*sv_maxspeed`, bot_commands.c:2661; teleporter-source paths 0; ROCKET_JUMP
   paths excluded because `canRocketJump` is false — the bot carries no RL/rockets
   on this rung). Zone-table quantization can deviate from true shortest time and
   flip near-ties; measured impact: the 4.6% argmax mismatches in §4.2.
2. **g_random → `random.Random(seed)`** uniform [0,1) (live: xorshift, `(rng>>8 &
   0xffffff)/2^24`). Same distribution; different stream — that is the point of the
   30-seed design.
3. **Vanilla actuation on delegated legs** → grounded walk straight at the marker
   (yaw = bearing, fwd 800, no jump). Skips vanilla's `ApplyPhysics` wishdir
   optimizer (only active grounded above 256 u/s), hazard/obstruction logic, and
   organic ledge jumps (live evidence: delegated stair walks carry 0 jump inputs;
   ledge-jump legs are never delegated by construction).
4. **Marker positions** from the FBMARKER dump origin + engine `SV_LinkEdict`
   FL_ITEM abs expansion (xy −15, z unexpanded) + classname mins/view_ofs tables
   (KTX items.c / marker_load / bot_loadmap). For "marker"-class the expansion
   exactly cancels the (80,80,24) view_ofs → nav = dumped origin. Validated live:
   1,187 carrot triggers cap at 131.1 qu vs the 130.0 threshold (one cmd-quantum
   past). `adjust_view_ofs_z` floor-drop applied to spawnpoint/teledest/plat
   classes only (matches the bot_loadmap call sites — .bot markers are NOT
   adjusted). Plat marker boxes are approximate (their absmin rides the brush; the
   route never approaches them, and pmove does not trace plats anyway).
5. **Inert subsystems** (solo matchless): enemies/combat/dodge, item pickup +
   respawn prediction, DM3CampLogic (gated on `NumberOfClients() > 1`), WAIT/lift
   logic, hazard avoidance (only changes dir_move_/jumping, both overridden by the
   probe outside delegated legs). dm3 path flags present: only 0 / 0x200(RJ) /
   0x400(JUMP_LEDGE) — no WATERJUMP_/WAIT_GROUND/CURLJUMP paths exist on this map.
6. **Cmd cadence**: seeded empirical mixture of the live msec histogram
   (10/11/20/21 ms at 0.512/0.218/0.136/0.134). Think cadence: grounded → every
   frame, airborne → 0.15+0.015·r s (`SetNextThinkTime`); marker-touch processing
   on 0.03 s `TimeTrigger` frames; touch rules = `check_marker` (closest-of-frame
   by 3D dist to nav pos, z-condition with the player's −1 abs expansion,
   CanDamage rays player-origin → marker-origin + half-bbox corners, hull-0).
7. **Teleporters**: volumes/destinations from the BSP entities lump;
   `teleport_player` semantics (dest origin +27 z, velocity = 300·forward(mangle))
   + `BotsPostTeleport` marker handover. sng_shortcut2 sanctions no teleporter, so
   any sim teleport ride truncates the attempt via `legit_segment` exactly as live.
8. **pmove caveats inherited** (from its validation report): submodels (plats/
   doors) and player-player collision not traced; float64 vs float32.

### Binding constraint (named)

The calibration's binding constraint is **physics at the two precision gates, not
navigation** — the same constraint P2 found live: sim failures are 12/18
ATTEMPTED_JUMP_FELL_SHORT + 6/18 REACHED_LEDGE_NO_JUMP at the final 238 qu gap
(required 437 qu/s), mirroring the live failure classes. The nav stub is NOT binding:
98.9% of live selections are inside its noise band.

### What bounds sweep trust (for A2 #74)

- Sim-c5 is +5.8% fast on arrival-tws median and −0.20 on reach rate vs live point
  estimates (both inside the pre-registered tolerances; the reach CI at live n=10 is
  wide). Treat sweep results as RANKINGS, not absolute reach predictions; confirm
  the sweep winner live before adoption (the plan's transfer protocol already
  requires this).
- The 4.6% selection mismatches concentrate on near-tie corners (e.g. 217/216/215 →
  208 vs 217); a sweep config that lives or dies on one specific near-tie marker
  choice is not resolvable offline.
- c4-vs-c5-style guard nuances that hinge on jump-flagged grounded handovers occur
  too rarely (0 in 30×48 s) to rank offline.
- Runtime: ~0.4 s per 48 s attempt (single core) → ~7,500 attempts/hour; a
  1000-config × 30-seed sweep is ~4 h.

## 6. Reproduction

```
python scripts/mode23_sim.py audit-selection                  # nav-stub vs live logs
python scripts/mode23_sim.py calibrate --config c5 --seeds 30 # the gate block
python scripts/mode23_sim.py calibrate --config c1 --seeds 30 # error structure
python scripts/mode23_sim.py calibrate --config c4 --seeds 30
python -m unittest discover -s tests -p "test_*.py"           # 212 tests
```

Inputs: `evidence/fbmarker-dm3.txt` (committed live-graph dump; live regenerated
copy preferred when `artifacts/lab-runs/20260609T213552Z/screen.log` exists),
`C:\nQuake\qw\maps\dm3.bsp`, census + human replay via `verify_route.load_route`.
Outputs: `evidence/calibration-c{1,4,5}.json` (committed copies of the
`artifacts/p3b-calibration/` originals).
