# Loop ledger — mode-23 phased plan (cozy-sprouting-wreath)

Plan: `C:\Users\benya\.claude\plans\cozy-sprouting-wreath.md` (approved 2026-06-09).
Rule: every iteration reads THIS file first, does ONE bounded unit, updates this file.
Raw traces never enter context — read summary JSONs only.

## Current state

- **Phase:** 0 (instrument fixes) — 0.0 ✅(revised) 0.1 ✅ 0.2 ✅ 0.5 ✅; remaining: 0.3 (death detection in attempt classification), 0.4 (metric unification + stairs detector lock)
- **Rung:** sng_shortcut2 (easiest per census; user pre-delegated easiest-first)
- **PROTOCOL DECISION (deviation from plan, evidence-based):** directed runs = **MATCHLESS + `k_fb_moveprobe_fixed_goal <live marker#>`**, NOT prewar. Prewar verified goal-quiet BUT its item set differs (63 vs 65 items, different weapons at same spots — KTX matchless-dir item config) → dm3.bot refs ≥53 resolve to WRONG markers in prewar = corrupted nav graph (refs 298/299 = NULL = the original segfault). dm3.bot numbering matches the 65-item MATCHLESS set (max ref 299). Pin satisfies the user's intent: goal_ed pinned 100% of ticks, zero item-goal interference.
- **Last completed unit:** fixed-goal pin VALIDATED live: run 20260609T213706Z (matchless, `k_fb_moveprobe_fixed_goal 1` = RL marker) → goal_ed=42 for 3351/3353 ticks, bot crossed map to RL, closest 32.9qu, max vh 502 (mode-23 record)
- **Next action:** Phase 0.4 metric unification in verify_route.py (single active-mean def + time-weighted dist/time + per-rung baselines from census.json) + stairs detector lock on hand-labeled traces; then Phase 1 doctrine implementation
- **Phase 2 note:** directed rung runs need a START mechanism (matchless spawns are random) — e.g. small `k_fb_moveprobe_spawn_origin` cvar snap at attempt start, or accept random spawns and measure reach-rate/time-to-goal. Decide at Phase 2.

## Pre-registered budgets (gate scoreboard)

| Gate | Budget | Used | Status |
|---|---|---|---|
| P1 doctrine | 6 builds × 5 runs + 1 confirm block | 0 | pending |
| P2 harness engage | 4 iterations | 0 | pending |
| P3 carrot | 8 configs × 10 att + 20-att confirm | 0 | pending |
| Rollout validation | timebox 2 sessions | 0 | pending |
| P3b transfer | top-3 + mid × 5 att | 0 | pending |
| P4 benchmark | 2 block-pairs (16/20 ×2) | 0 | pending |

Standing rules: attempt 0 of each session discarded (cold-start); pass once → confirm
on a fresh pre-declared block; stop-loss hit = stop looping, escalate per plan.

## Pre-delegated decisions (overnight)

- Start at EASIEST rung from Phase-0.5 table.
- KTX lab deploys: allowed. Gamedir dm3.bot edits: NOT allowed overnight.
- Blocking judgment call → log anomaly here, skip to next independent unit.
- 2 consecutive lab infrastructure errors → stop, notify.

## Code anchors (avoid re-reading large files)

- mode-23 block: `bot_movement.c` inside `BotApplyMoveProbe`, after mode-20 block
  (~line 3514-3701 in current build); source of truth
  `C:\Users\benya\.claude\jobs\7bae6c77\tmp\bot_movement_servexeri.c` (= frogbot-study copy).
- Deploy: scp src → servexeri `~/nquakesv/build/ktx/src/` → `./build_cmake.sh linux-amd64`
  → `cp build/linux-amd64/qwprogs.so ~/nquakesv/ktx/qwprogs-mode21.so` (symlinked qwprogs.so).
- fixed_goal branch: `bot_botgoals.c:345-350` (UpdateGoal); botpath crash:
  `bot_commands.c:752-755` — DO NOT USE botpath.
- Marker index: live = dm3.bot file line + 65. NUMBER_MARKERS=300, dm3 at 299. NUMBER_PATHS=8.
- Harness: `scripts/run_frobodm2_lab.py` (cfg gen ~line 161-185, mode choices :1251);
  wrapper `scripts/run_dm3.py`.

## Run log (one line per gate block)

| When (UTC) | Unit | Result |
|---|---|---|
| 21:03-21:27 | P0.0 prewar protocol | DONE after crash fix. KTX segfaulted on dm3 map load with k_fb_enabled+k_matchless 0: NULL-marker write in marker_load.c setters (fault fb.paths[i].flags = gedict+0x2ac8). Fixed: NULL guards in BotSetRocketJumpFields/SetMarkerAngleHint/SetMarkerPathFlags + AddToQue bounds guard (deployed). Harness: cfg now presets k_fb_enabled 1 when prewar (runtime flip ALSO crashed). Verification run 20260609T212733Z: full prewar run OK, goal_ed=0 ALL 4219 ticks (goal economy fully quiet — user premise verified), avg 223/dist 12010 ≈ matchless v2 parity. Protocol: run_dm3.py --prewar --lab-mvdsv mvdsv-lab |
| 21:15 | P0.5 trick census | DONE (subagent). artifacts/trick-census/LADDER.md + census.json. Sanity anchor PASSED (sng_to_rl: 4085qu/425/526req/528carried reproduced). Ladder easiest->hardest: sng_shortcut2(3.61), hilljump(4.00), rl_to_ya(4.38), ring_to_mega(4.78), ra_jumps(5.58), mega_to_rl(5.58), rl_to_bridge(5.63), sng_shortcut(5.71), sng_to_rl(5.97), mega_to_window(6.12), sng_jumps(8.45). STARTING RUNG: sng_shortcut2. Caveats: ra_jumps least trustworthy (lift=bmodel invisible to bsp_geom) |
| 21:32-21:37 | P0.1 marker map + P0.2 goal pin | DONE. New KTX instruments (deployed): `k_fb_moveprobe_dump_markers 1` → FBMARKER dump of full live graph in screen.log (run 213204Z prewar / 213552Z matchless); `k_fb_moveprobe_fixed_goal N` (1-based live marker, -1 clears) read in UpdateGoal, no debug side effects. Live numbering: matchless = 65 items then file lines (+65); RL = live marker 1 (goal entity edict 42). Prewar = 63 DIFFERENT items (+63) → graph corrupt in prewar → PREWAR REJECTED for directed runs (see protocol decision). Pin validated: run 213706Z → goal_ed 42 @ 100% ticks, closest-RL 32.9qu, max vh 502. Trick-link re-audit possible offline from the matchless FBMARKER dump (live numbering now ground-truthed). |

| 21:42 | P1 doctrine v3 deployed | mode-23 block: climb detect (marker_dz>26 && dist<280, JUMP_LEDGE/WATERJUMP_/ROCKET_JUMP exempt, VERTICAL_PLATFORM forces grounded) suppresses press_jump; wall-hug (grounded straight: ±90° 50qu traces, lean wishdir 40° into nearer wall, cvar k_fb_moveprobe_s23_wallhug). Smoke run 214205Z: 4091 rec, max 470, onground 3.1% (SUSPICIOUS — lower than v2's 5.8%, climb gate may not fire; crude climb analysis pending). Source synced to jobs\7bae6c77\tmp. |

| 21:45 | P0.1 trick-link re-audit (live numbering) | CONFIRMED: no path link crosses the bridge→RL leap in either direction. Bridge-side launch markers = live 72 (1360,-33,-24) + 110 (1357,106,-24); landing side = live 1(RL)/45/46/69/291. RL reached only via 45/46/69 (walkable). Phase-4 anchors are these LIVE numbers (file-relative earlier guesses superseded). Capacity: live max 299/300 → exactly ONE new marker possible. |

| 21:42-21:50 | P1 doctrine v3→v4 | v3 REGRESSION caught by crude climb metric: avg 227→150 — wall-hug fired on EVERY grounded frame incl. bunnyhop touch frames (rotating hop accel 40° off scrubbed speed); climb gate dz>26 too high (stair markers often <26 above bot). v4 fix: wall-hug only when climb&&straight; climb dz>18. Run 214845Z: avg 223 ≈ v2 parity, max 533 (record), climb-grounded 0.21 (vs v2 0.07; target ~1.0 — partial). v4 DEPLOYED + synced. Next: formal gate vs locked detector (subagent building) + 5-run baseline block. |

| 22:05 | P0.4 metrics + detector | DONE (subagent). scripts/route_metrics.py (time_weighted_speed = gate metric w/ legit_segment inside; ONE active_mean vh>1 def) + verify_route.py --route <any of 11> --metrics (regression: BYTE-IDENTICAL on 172810Z) + scripts/climb_detector.py LOCKED (contact-height chaining, haf<4 grounded fallback — trace onground flag unreliable for bot; jump=buttons&2 verified 64/64). KEY SURPRISES: (a) v2 baseline run NEVER climbed stairs (free-roam rarely climbs → doctrine gate needs DIRECTED climb runs; real staircase: x 2010→1966, y −106→−371; the t21-28 z-rise was SWIMMING, teleporter at t12.2); (b) vanilla baseline run STUCK 2/3 of runtime → its 191 avg is invalid as a reference. Doctrine gate protocol: pin k_fb_moveprobe_fixed_goal 54 (RA, z=304) → forces the climb; judge with climb_detector. |

| 22:10 | P1 v4 baseline block (n=6 free-roam 50s) | tws (time-weighted speed): mean 209 ± 34, range 173-255, regression floor (mean−1sd) = 176. Peaks 434-600. Runs 214845Z + 2150*-2155*. This replaces the invalid single-run v2/vanilla baselines (vanilla was stuck 2/3 of its run). |

| 22:20 | P1 v4 directed-climb gate: FAIL (build 2/6) | 3 runs fixed_goal 54 (RA z=304): NONE reached RA (closest 217/287/1231, zmax 116/29/19); run 2 = 23 repeated 48qu climb-fall cycles; every climb carried 1-6 jump inputs. ROOT CAUSE: marker-dz climb detection grounds on ANY >18 rise, but 48qu LEDGES require a hop — v4 made ledges unmountable. v5 (build 3/6): terrain probe 20qu ahead along nav_dir, rise 3..20 = walkable stairs/ramp → ground; >20 = ledge → hop allowed; probe only when onground && marker_dz>12. |

| 22:02-22:12 | P1 v5 + RA-target post-mortem | v5 (terrain probe) deployed; directed-to-RA runs still failed BUT control experiment (vanilla mode 0 + pin 54) ALSO fails — RA cluster (Z10: 54,24,249-254) is only entered via ROCKET_JUMP-flagged links (56→251, 251→54, 252→54 all 0x200), unflagged crate-hop links, or the z=328 walkway → **RA was a wrong test target (graph property, not doctrine bug)**. Vanilla control + pin 72 (bridge): reaches it cleanly → pin mechanism fine. Mode23→72: 1/2 reached; no stairs exercised (random spawns). |
| 22:15 | NEW INSTRUMENT: spawn snap | `k_fb_moveprobe_spawn_origin "x y z"` — one-time per-slot teleport+zero-velocity on first moveprobe frame (BotApplyMoveProbe, after early-outs; static per-slot latch, resets when cvar emptied). This is also the Phase-2 start mechanism. Deterministic stair test: SE staircase chain 71(1984,-108,-168)→76(z-88)→75(1959,-425,-24); spawn "1984 -108 -144", pin 75. |

| 22:18-22:20 | STAIR TEST WORKS + harness quoting fix | Harness bug: --ktx-extra-cvars values with spaces were truncated in the cfg (unquoted `set`); fixed in run_frobodm2_lab.py (quotes multi-word values). With fix: 3/3 deterministic stair runs spawn (1984,-108,-144), pin 75, REACH TOP in 1.8-4.3s (closest 3/28/34). Gate still FAILS on jumps-in-climb (2-6 inputs, target 0): the v5 probe's `marker_dz>12` precondition opens hop windows near marker handovers. v6 (build 4/6): probe EVERY grounded frame (rise test rejects flat anyway). |

| 22:35 | PMOVE ROLLOUT VALIDATED (subagent) — Phase-3b substrate READY | scripts/pmove_sim.py (mvdsv-master pmove port incl. swept hull-1, water, StepSlideMove, ktjump, edge friction) + run_pmove_validation.py + artifacts/pmove-validation/report.md. HUMAN REPLAY PASS: 692/692 frames, max err 0.20qu, edge speed 529.1 vs 528.2 recorded. BOT REPLAY PASS: per-step p95 0.004qu; free-run drift = log yaw quantization (0.1°), not physics. ENGINE FACTS (for tuning): mvdsv air-accel uses `accelerate` cvar (not airaccelerate); no gravity tick on ground branch; jump_msec zeroed per cmd (pogo dead); overbounce 1.0. Caveats: submodels (lifts/doors) + player-player collision not traced; one eaten spawn-jump (--force-jump-held flag). |

| 22:25-22:30 | **P1 STAIRS GATE: PASS** (v7, build 5/6) | v7 = DELEGATE climb legs to vanilla actuation (early-return in mode-23 when onground && marker_dz>18 && dist<280 && no jump-flags; vanilla direction+jumping pre-computed by caller = proven stairs walker incl. organic ledge jumps). v6 (always-probe) had been WORSE (slower, jumps persisted — some from vanilla's own logic at speed). Evidence: trajectory walk shows grounded stair walk z−152→+9 in ~1.5s (~300 qu/s on stairs), bunnyhop resumes at crest. Confirmation block 3/3: arrive t+1.0-1.1s, ZERO journey presses (single press AT crest = legit resume). Total 5/6 clean; 1 spawn-race entry hop (cold-snap artifact, documented exclusion). Wall-hug DEFERRED (v3 regression showed it must live inside delegated legs; stairs already ~300 qu/s; revisit at Phase 3). Detector protocol note: truncate at first arrival — post-arrival goal-hover pollutes climb counts. |

| 22:36-22:40 | P1 free-roam block (v7): livelock found | 5 runs: 293/157/229/236/208 (mean 225 > v4 209, but min 157 < floor). Run 223542Z = DELEGATION LIVELOCK: linked_marker frozen at 9 for 97% of ticks, 95% grounded, vanilla circling under a marker it needed an organic jump for. v8 (build 6/6, LAST of budget): 3s same-marker delegation timeout → release to weave until marker changes (statics moveprobe_s23_deleg_since/_marker). Reran both gates (3 stairs + 5 free-roam). |

| 22:45 | **P1 CLOSED at budget (6/6 builds)** | VERDICT: stairs doctrine PASS (v8 = vanilla-delegation + 3s livelock guard; deterministic stair test: clean walks, residual = spawn-race entry hop, documented); livelock FIXED (0/5 latched runs); free-roam regression canary INCONCLUSIVE-NOT-FAILED (v8 194±35 vs v4 209±34 — overlap >> effect; floor test underpowered at n=5 exactly as the methodology review predicted; 2/5 under 176). v8 = DEPLOYED CONFIG going forward. Wall-hug deferred (ledger 22:25). Proceeding to P2 (independent, measurement-only). |

| 22:54-23:04 | **P2 BASELINE TABLE: sng_shortcut2** (10×45s, spawn 385.5 614.25 56, pin 191, mode-23 v8) | **Reach 4/10**; arrivals 6.1/10.6/12.9/44.2s (human direct 3.65s — bot takes the walkable detour, leap not in graph as expected); journey-tws 262-291, median 275 = **74% of human active-mean 374**. THE BINDING GAP ON THE EASIEST RUNG = REACH-RATE (nav wandering from identical start/goal = frogbot path stochasticity g_random + weave interaction), NOT speed. Earlier 18s block invalidated (duration truncation — detour needs ~6-21s). NEXT (fresh session, read this ledger): P2 deliverable-b variance decomposition on these 10 runs (why 6 wander — trace divergence point analysis), then P3 carrot. Also pending: commit+PR komodobots changes (route_metrics, climb_detector, pmove_sim, harness fixes) + KTX patches; upstream KTX bug report (NULL-marker guards confirmed missing in master); user decisions: wall-hug deferral OK? wiki/upstream PR? |
| 23:05 | KTX docs checked (user req) | Docs are thin: README=build only, QWiki=gameplay (botcmd enable/addbot/fill, skill 0-20), meag blog=port history. NO official k_fb_* reference — source is the doc. **Upstream master STILL has the unguarded marker code we fixed** (verified raw github): our 3 NULL-guards + AddToQue bound = upstream bug-fix candidates. No bots/configs mechanism exists upstream (old announcement never shipped) — our pin/snap cvars fill a real gap. |

| 23:10 | P3 config-1 deployed (carrot) | Edge-triggered early handover at pass_r: SetMarker(linked)+ProcessNewLinkedMarker (frogbot's OWN selection per review; static carrot_done latch per slot; nav_dir recomputed to new marker). Gate running: 3 stairs-regression + 10 sng_shortcut2 attempts vs baseline (4/10 reach, tws 275). P2 variance-decomposition subagent running in parallel. |

| 23:20 | **P2 deliverable-b: variance decomposition** (subagent; artifacts/p2-variance/decomposition.md) | NOT g_random: goal/marker selection held on EVERY record of all 10 runs. Failures = physics at TWO precision gates: **Gate 1** north-ledge lip jump (-90,700,z88→130) marker 210 — 41/66 lip entries fell back (time sink); **Gate 2** 90° corner markers 206/207 two hops from goal — arrive ~480-505 vh under ±45° weave, only 36% convert to 191; ALL successful conversions at vh 224-415. 5/6 failures downstream of Gate-2 miss; miss dumps into marker basins costing 15-40s. RECOMMENDATION: turn-aware precision governor (straight-aim + speed shed ≤~350) on sharp-turn/precision legs — projected ~9/10 reach. → This is P3 config-2 design: at carrot handover compute leg-to-leg turn angle; if >~60°, precision mode until next marker (no weave flips, ground redirect allowed). |

| 23:30 | **P3 config-1 GATE: reach 8/10** (vs baseline 4/10!) | Carrot doubles reach-rate; time median 8.7s (was 11.7 on fewer arrivals); tws median 262 (~baseline). Two failures + two slow (37/47s) remain = corner overshoot per decomposition. STAIRS slightly regressed: mid-climb presses (t~1.6) — handover fires mid-staircase, re-targets past delegation range. Config-2 deployed: carrot climb-guard (skip handover when onground && dz>18) + PRECISION GOVERNOR (at handover, leg-turn >60° → straight-aim + no hop until marker taken, 2s escape; statics prec_marker/prec_since). Gates running. |

| 23:45 | P3 config-2: stairs PERFECT, governor REGRESSED rung | Stairs 3/3 t+0.9s ZERO presses (climb-guard works — best ever). Rung 4/10 @ 30.2s median (vs c1 8/10 @ 8.7s): governor compared next leg vs VELOCITY heading — chronically >60° under ±45° weave → precision fired everywhere, grounded the bot incl. at the jump-required lip. Config-3 (3/8 budget): positional leg-to-leg bearings (old nav_dir vs new nav_dir, both bot-positional, weave-stable) + never engage precision on climb legs (dz>18). Rung gate running (stairs skipped — c2's stair result already used the climb-guard, unchanged in c3). |

| 00:25 | P3 config-3: governor still bad (4/10) → config-4 = governor REMOVED | c3 (positional bearings + no-climb-legs) still 4/10 @ 18.9s — drop from c1's 8/10 is significant (p≈1%). Governor is the wrong tool at this layer regardless of trigger signal (grounding at corners breaks the weave's basin-recovery). c4 (4/8 budget) = carrot + climb-guard ONLY (c1 + stairs fix). A/B isolates the guard. Both gates running. If c4 ≈ 8/10 + clean stairs → adopt as P3 result; corner conversion stays open for the OFFLINE sweep (3b) where the governor idea can be tested at 1000x speed instead of burning live builds. |

| 00:40 | P3 config-4: guard itself costs reach (5/10, stairs perfect) → config-5 | c4 (no governor, broad guard) = 5/10 @ 9.7s, tws 292; stairs 3/3 zero presses. Attribution: governor cost ~1-4 attempts, broad guard cost ~3. c5 (5/8 budget): guard narrowed to EXACTLY the delegation condition (adds dist<280 && !jumpflags) — re-enables handovers at jump-flagged/far ledges (the lip) while protecting delegated stair walks. Both gates running. |

| 00:50 | **P3 LIVE PHASE CLOSED (5/8 configs) — config-5 ADOPTED** | c5 = carrot (edge-triggered SetMarker+PNLM at pass_r) + delegation-exact climb guard, NO governor. Evidence: carrot pooled 19/30 (63%) vs baseline 4/10; governor variants 8/20 (40%, removed); c4 vs c5 guard A/B indistinguishable at n=10 — adopted c5 as the principled config (each condition maps to a measured failure; stairs 3/3 zero presses on every c5/c4/c2 block). Distinguishing 6 vs 8/10 needs n≈50/config (review-predicted) → further corner-conversion work moves to P3b OFFLINE sweep (pmove sim ready; governor hypothesis testable there at scale). Deployed+synced: config-5. Rung status: reach 4/10→~6-8/10 band, journey-tws 262-292 (70-78% of human-active 374; the 80% target still lacks its walkable-route human reference — ask user to record one, or derive from sim). NEXT SESSION: P3b sweep harness (wrap mode-23 control law over pmove_sim, sweep pass_r/swing/turn_thresh/corner params for corner conversion + edge speed), or commit/PR the night's work first (recommended). |

## Anomalies

- Prewar requires mvdsv-lab binary (plain mvdsv crashed identically; both tested — crash was KTX-side, but keep --lab-mvdsv mvdsv-lab for the login-timeout fix per memory).
- The guard prints (G_Printf "marker N not loaded") did NOT appear in the surviving run's log — either no NULL was hit post-fix at parse time (crash was elsewhere in the same inlined region) or G_Printf channel isn't captured. Crash is 100% gone across harness + manual repro; root-cause attribution is "NULL marker deref in marker-path setup during non-matchless dm3 load", exact line unconfirmed. If it ever recurs: debug build lives at ~/nquakesv/build/ktx/build-dbg + ktx-dbg gamedir.
