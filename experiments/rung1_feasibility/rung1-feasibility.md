# A4 #116 — Rung-1 first-jump feasibility (sng_shortcut2), offline

**Everything below is offline** — live FBMARKER graph dump + BSP + existing
lab traces + the validated sim/pmove stack. No lab contact, no map edits.

## Plain words (read this first)

**The jump is buildable, and it does NOT spend dm3's last marker slot.**
The leap connects two markers that already exist: **m210 (the ledge "lip"
marker) → m97 (the landing-strip marker)**. m210 has exactly one free path
slot (7 of 8 used), m97 already has a walk path to the goal marker 191. The
one free marker slot (299/300) stays untouched — the bridge plan keeps it.

**The bot already carries enough speed at this lip.** In all 70 directed
runs on disk, the bot gets grounded, takeoff-capable moments near the lip;
the best of them is at median 440 qu/s (max 467), and 50 of 70 runs hit the
censused requirement of 437. The physics check (validated pmove port, real
collision) says the requirement is actually friendlier than the census
number: launched 25 qu before the edge on the right line, **370 qu/s
already clears**; 437 buys ~40 qu of takeoff-window slack.

**The two real risks are aim and timing, not speed.**
1. *Aim:* the clearing heading window is only ~12° wide ([−4°..+8°] around
   the line to m97) — west of it the flight hits a z=184 wall block, east
   of it misses the landing strip's tip. The bot's weave wobbles about ±12°
   at launch, so roughly half of launches will be aimed well enough.
2. *Gate timing (the important design finding):* the D1-style gate tests
   speed when the link is *selected* (EvalPath at the carrot handover),
   which happens ~220 qu before the lip — where the live bot is still slow
   (median 305; **0 of 70 runs would pass a 437 selection gate**) even
   though 66/70 exceed 437 inside that same area seconds later. **A
   selection-time threshold of 437 would mean the link never fires.** The
   gate threshold must be a cvar and start low (~320), with the census 437
   kept as the *launch* requirement that physics itself enforces.

**Falling short is cheap here.** The "void" is the lifts-corridor floor
(rest z 8..32) — the bot survives, walks back, retries. No death pit, no
quad-area detour. This is exactly why rung 1 is the right first jump.

**What the sim adds, honestly:** the offline sim reproduces its A1 anchor
exactly, but at this specific feature it is measurably ~8–15 % slower than
live (matched c5 block: live 407.5 vs sim 375.8 at the crossing; grounded
near-lip live 433–440 vs sim ~380). In-sim, no config reaches 437 at the
lip and every end-to-end sim launch falls short — **that is the measured
sim bias, not a prediction of live failure**; the live traces, which are
the primary evidence here, show the speed is there. (The pre-registered
"no config reaches 437 in sim" escalation is therefore reported as a sim
artifact, with the live measurement overriding it — see §5.)

**Honest live-success estimate** (component-wise, not a fake single
number): reaching the lip area ~0.87/attempt (live), speed sufficient
~0.5–0.7 (live), heading in window ~0.4–0.6 (pmove), takeoff position
~0.4–0.7 (pmove on measured states) → **roughly 0.1–0.45 cleared jumps per
48-s directed run, i.e. the first-ever trick jump is near-certain within a
standard 10-run block** (P ≥ ~90 % under mid assumptions). The A5 smoke
block measures the real number; no offline method can pin it tighter,
because the post-link approach line does not exist in any live trace today.

---

## 1. Gap geometry + slot cost (geometry.json)

Census gap (route sng_shortcut2, its single/final hard gap):

| | |
|---|---|
| launch edge | (−161.0, 728.8, z 135.5) — rest-z 120 plateau tip |
| landing | (−291.2, 529.4, z 135.5) — strip rest-z 120 |
| span | 238.2 qu (BSP re-measure along the census line: 238.1 ✓) |
| required | 437.0 (ballistic, from the edge-crossing state) |
| human at edge | 458.8 (margin +21.9), vz +218 (jumped ~30 qu before the edge) |
| below the gap | corridor floor rest-z 8..32 (recoverable; NOT a pit) |

Nearest live markers (FBMARKER dump, run 20260609T213552Z):

| end | marker | org | dist | paths used | note |
|---|---|---|---|---|---|
| launch | **m210** | (−75, 750, 104) | 94.0 | **7/8 → ONE free path slot** | the P2 "Gate-1 lip" marker; ON the walkable route skeleton 214→208→**210**→209→211→206→207→191 |
| launch alt | m209 | (−172, 847, 120) | 119.7 | 8/8 FULL | unusable without replacing a path |
| landing | **m97** | (−335, 512, 120) | 49.6 | 6/8 | **existing path 97→191** (goal) |

D1-style pre-checks, transposed to rung 1: (a) source on the directed
walkable route — **YES** (210 is the Gate-1 crest the route already
climbs); (b) NUMBER_PATHS free slot on source — **YES** (7/8).

**VERDICT: the trick link is 210 → 97 between two EXISTING markers. Marker
slot cost = 0. The dm3.bot edit adds ONE path entry (m210's 8th), not a
marker.** The one free marker slot stays available for the bridge (D2 #78).

Aim-corridor bound: a z=184 block (x −400..−300, y ~440..680 with the
strip notched in at y 480..540) walls the west side of the flight line;
the strip tip (x ≤ −290, y 500..540, rest-z 120) is the landing. m97 sits
on the strip 47 qu horizontal from the census landing point.

## 2. Lip speed today — live (live-lip.json, handover-speed.json)

All 70 directed rung-A runs on disk (lab.cfg cvar triple: mode 23 + pin
191 + spawn "385.5 614.25 56"; every match included, none excluded). The
P3 c1/c2/c3 gate run dirs no longer exist on disk (cleaned; cf. B5
"ssd-only 41") — blocks present: the invalidated 18-s pre-block (10), the
P2 baseline (10), four carrot-family blocks of 10 (00:48–01:36 UTC; exact
sub-config not pinned by the ledger), and the A1 c5 comparator block (10).

Conditioning of record: verify_route attempt segmentation → legit_segment
(stray-teleport guard intact) → arrival truncation at 60 qu. 87 attempts.

| measurement | value |
|---|---|
| reached the lip area (z>96, <80 qu of edge) | **76/87 attempts (87 %)** |
| vh at closest lip approach (median) | 419.4 (mostly mid-hop, airborne) |
| best takeoff-capable vh near lip, per run (haf<4, ≤150 qu) | **median 440.1, max 466.7, ≥437 in 50/70 runs, ≥395 in 70/70** |
| A0 edge_speed crossings (rung-1 gap) | 70/87; median 440.3, max 478.6, ≥437: 36 |

**Cross-track audit (do not over-read the A0 number):** 63/70 qualifying
crossings sit 100–160 qu cross-track from the edge point — they are the
walkable detour traversing the launch *plane* up on the ledge, not
launches. Only 7 crossings are within 80 qu of the lip, and those are slow
(165–407: Gate-1 wobble). The per-run takeoff-capable stat (haf<4 within
150 qu) is the honest "speed at the lip" number. The onground flag was
audited against haf<4: onground never fires where haf<4 does not (0
onground-only rows); haf<4 adds 351 rows — both conventions reported,
haf<4 primary (the locked climb_detector convention).

Per block (A0 edge crossings): pre-18s 392.5 (n=7) | baseline-v8 339.9
(n=10) | carrot-family 428–469 (n=40) | c5-comparator 407.5 (n=13).

**Selection-point speed (the D1 gate would sample here):** vh at FIRST
entry of pass_r(130) around m210 — median 304.9, **0/70 ≥ 437**, 6/70
≥ 410, 16/70 ≥ 350. Max vh while inside pass_r: median 455.6, **66/70
≥ 437**. The bot builds ~150 qu/s INSIDE the handover zone (the grounded
arc up the 16-qu steps — the same mechanism the human uses: the human
enters at ~330 and leaves the lip at 458.8).

## 3. Lip speed — sim, n=30 declared seeds (sim-lip.json)

Pre-declared: seeds 1..30 (A1/A2 convention), RUNG_A protocol exactly,
configs = deployed c5 + the four A2 transfer candidates + the A2b
circle-jump launch config. A1 anchor reproduced exactly (c5: reach 12/30,
tws 279.4) before reading anything else.

| config | reach | lip share | edge_n | edge med | ≥437 | grounded near med | max |
|---|---|---|---|---|---|---|---|
| c5-live | 12/30 | 0.95 | 37 | 375.8 | 0 | 379.8 | 409.3 |
| a2-c1 (gpos60, lead .3) | 16/30 | 1.00 | 27 | 387.1 | 0 | 386.0 | 423.0 |
| a2-c2 (gvel60) | 14/30 | 0.94 | 32 | 383.2 | 0 | 381.1 | 406.3 |
| a2-c3 (gpos75, lead .3) | 17/30 | 1.00 | 28 | 387.0 | 0 | 384.8 | 423.0 |
| a2-c4 (cvar-only) | 23/30 | 1.00 | 23 | 383.4 | 0 | 379.4 | 394.7 |
| cj-launch | 10/30 | 0.20 | 0 | — | 0 | 378.9 | 385.9 |

**No config reaches 437 at the lip in-sim** (best grounded 423). The A2
candidates rank ~7–11 qu/s above c5 — ordering only. cj-launch craters
exactly as A2b disclosed (circle wall-locks in the tight spawn room; the
launch cvars are per-protocol instruments, wrong room here).

**Sim-vs-live bias at this feature (measured, like-for-like):** matched c5
block — live edge median 407.5 vs sim 375.8 (live +8.4 %); grounded
near-lip — live c5-block 433.0 / pooled 436–440 vs sim 379.8 (live
+14 %). Direction consistent with A3's divergence finding (live converts
runways better than sim; live spike 570.7 vs sim max 478.1). The A1
calibration bounded *route-level tws* at +5.8 % sim-fast; the *lip-local*
bias goes the other way and is larger — worth carrying into every future
sim-vs-437 readout.

## 4. Jump test — pmove, real collision (jump-sim.json)

Deterministic (no RNG; inputs pre-declared in the script header):
envelope = takeoff d_pre ∈ {10,25,40,60} qu before the census edge along
the aim line × speed 340..500 × heading error −16..+20°; jump frame 0
(ktjump +270), neutral flight (QW air-accel adds nothing along-velocity).

Minimum clearing speed (aim at m97, err 0): **d10 350, d25 370, d40 390,
d60 420** (analytic flat-jump: 368/390/412/442 — the pmove numbers agree
to ~1 grid step). The census 437 corresponds to a launch ~55–60 qu before
the edge — it is the *conservative* end of the at-lip range, i.e. carrying
437 makes the whole last ~55 qu of the plateau a valid takeoff window.

Heading window (the binding constraint): at d25 the clearing window is
**err ∈ [−4..+8]°** at speeds 390–500 (D-probe at vh 440: m97-aim window
[−2..+8], census-landing-aim window [−8..+4] — m97 sits ~5° west of the
corridor center; the west wall is the 184 block, the east edge is the
strip tip). Width ~12–14°, comparable to the weave's ±12° release wobble →
P(heading) ≈ 0.4–0.6. Straight-line flights are conservative: the live law
air-steers (the human curved −141°→−123° in flight).

Overshoot: only at d10 + vh ≥ 490 (lands past the strip into the block) —
irrelevant at measured speeds ≤ 467.

Measured-state clearance: jumping AT each run's fastest takeoff-capable
state aimed at m97: **24/70 clear** (the other 46 are takeoff states
60–150 qu before the lip — jumping there is too early; the hop chain would
ground again closer). Same speeds advanced to the census takeoff point:
**70/70 clear at err 0; 64/70 at +8; 0/70 at −8** (the block wall).

## 5. End-to-end sim with the link in the graph (link-sim.json)

The trick link 210→97 (flag bit, free slot) + a D1-style EvalPath speed
gate were installed in the SIM's parsed graph (scripts/ untouched; zone
tables exclude the trick edge like ROCKET_JUMP links — recommended live
semantics, costs nothing on rung 1 since 210 is already on the route).
Cells: {c5-live, a2-c4} × gate {437, 410, 0} × seeds 1..30.

| cell | gate evals | med vh @eval | passes | launched | cleared | reach |
|---|---|---|---|---|---|---|
| c5 gate437 | 533 | 332.8 | 0 | 7* | 0 | 12/30 |
| c5 gate410 | 532 | 332.8 | 1 | 7* | 0 | 12/30 |
| c5 gate0 | 958 | 331.6 | all | 21 | **0** | 6/30 |
| c4 gate437 | 208 | 339.6 | 0 | 0 | 0 | 23/30 |
| c4 gate410 | 208 | 339.6 | 0 | 0 | 0 | 23/30 |
| c4 gate0 | 297 | 338.0 | all | 25 | **0** | 8/30 |

(*the 7 launches under closed gates are organic detour falls at the lip,
not link-induced — the control behaves.)

Findings the spec must absorb:
1. **Gate-blocked world ≡ no-link baseline, per-seed 30/30 on both
   configs** (reached + arrival_t identical) — the D1 "provably unchanged"
   smoke property holds by construction (the gate returns NULL before the
   RNG draw, preserving the stream).
2. **Selection-time speed ≠ launch speed.** Sim evals sample ~332 median;
   live first-entry 305. A 437 selection gate never fires (0 passes live
   bracket, 0–1/30 sim).
3. **Ungated at slow speeds = trap loop.** With the gate open, the sim bot
   (which launches at 318–404) takes the shortcut every pass, falls short
   every time (0/46 cleared), and reach craters (12→6, 23→8). At LIVE lip
   speeds most launches clear instead — but the floor exists to protect
   exactly the slow tail.
4. **Link flap:** the single gate-410 pass (seed 28, eval vh 429.6) was
   re-scored away at the next slow think before launching. Live KTX has
   the same re-think cadence → the D1 implementation should add hysteresis
   (keep a selected trick link unless speed drops further, or latch it
   until the marker changes).

## 6. LINK SPEC (the go/no-go deliverable)

| item | spec |
|---|---|
| link | **m210 → m97** (live numbering; dm3.bot file markers 145 → 32 at the standing live = file + 65 mapping), one-way |
| slots | m210 path slot 8/8 after the edit; **zero marker slots** (the ONE free marker stays for the bridge) |
| flag | the D1 #77 trick path flag (new letter; encode+decode both sides, loud-fail on unknown letters). Keep it pure — do NOT also set JUMP_LEDGE (no delegation interaction at dz≈16; vanilla must never react to the link) |
| EvalPath gate | flagged link → PATH_SCORE_NULL unless mode-23 AND current horizontal speed ≥ **threshold cvar** (suggested `k_fb_trick_gate_speed`). **Default 437 is the safe-deploy value but will never fire on rung 1** (measured: 0/70 live first-entries ≥437); the A5 live block should sweep {320, 410, 437} — 320 ≈ live median at selection, lets the measured +150 qu/s in-zone acceleration produce the 437+ launch. Add pass-hysteresis (finding §5.4) |
| zone tables | exclude trick edges from travel-time tables (like ROCKET_JUMP) — no map-wide slow-bot attraction; rung-1 route hits 210 anyway |
| jump actuation | none needed: mode-23's hop chain launches off edges already (A3 AJFS class); the 437-launch is enforced by physics, not by code |
| gamedir edit | dm3.bot: ONE path entry appended to file marker 145 (live 210) → file 32 (live 97) with the trick flag. Backup first. **User approval required (D2-style) — this ticket only specs it** |
| deploy order | D1 gate code FIRST (with the no-edit smoke = provably unchanged, §5.1), dm3.bot edit second — same ordering as the bridge plan |
| failure cost | recoverable: short fall lands on the corridor floor (rest 8..32), bot re-routes to Gate-1 (~10–25 s); no death pit |
| est. live success | per-run 0.1–0.45 cleared jumps (component band, §plain-words); first-ever jump within a 10-run block ≈ ≥90 %. NOT estimable from the end-to-end sim (measured slow-at-lip bias, §3/§5); A5 smoke block measures it |

## 7. Files

| file | what |
|---|---|
| rung1_lib.py | shared conventions (lip criteria, conditioning, crossing audit) |
| rung1_geometry.py → geometry.json | markers, slots, floor profiles, verdict |
| rung1_lip_live.py → live-lip.json | all 70 directed runs, 87 attempts |
| rung1_handover_speed.py → handover-speed.json | selection-point speeds |
| rung1_lip_sim.py → sim-lip.json | 6 configs × 30 seeds, A1-anchored |
| rung1_jump_sim.py → jump-sim.json | pmove envelope + measured states |
| rung1_link_sim.py → link-sim.json | link-in-graph end-to-end + gate cells |
| inspect_live.py / inspect_grounded.py | audit utilities (cross-track + onground/haf) cited in §2 |

Caveats register: (i) sim lip-local bias quantified §3 — carry it; (ii)
A0 edge_speed on this route mostly measures the detour plane-crossing
(cross-track 100–160) — use the takeoff-capable stat for "speed at the
lip"; (iii) carrot-family block sub-configs not pinned by the ledger (40
runs, 00:48–01:36) — lip physics config-agnostic, per-block numbers
reported; (iv) the 18-s pre-block under-measures slow attempts (duration
truncation) — included for completeness, flagged; (v) post-link approach
line exists in no live trace — all post-link estimates are sim/pmove-based
with the declared assumptions.
