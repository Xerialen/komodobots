# A3 (#75) — live transfer gate: the sim tail did NOT transfer (per the pre-registered bar), and the live block localizes exactly where it leaks

**VERDICT: ALL FOUR SCREENS FAIL** the pre-registered pass rule (>=2/5 attempts >= 526):
S1 launch 0/5 (best 460.7), S2 deleg320 0/5 (best 483.1), S3 C4 **1/5 (best 570.7)**,
S4 control 0/5 (best 487.0). No confirmation block was run; #75 stays OPEN; this is the
escalation document.

**The headline anyway:** attempt 1 of screen 3 carried **570.7 qu/s over the launch edge —
the first live >=526 ever recorded on this gap** (census requirement 525.3, the human
reference 528.6). The target is provably reachable by the live bot; what failed is making
it *regular*.

In plain words: we taught the bot the on-purpose circle-jump start, and the spin-up part
works perfectly live (five out of five runs hit 400+ speed within a third of a second,
exactly like the sim). What breaks is the moment right after: live, the bot releases from
its circle slightly off the line the sim had, and either falls off the walkway into the
pit (3 of 5 runs) or takes the corner wide and bleeds the speed it brought. Meanwhile the
one live 570.7 run looks exactly like the sim's "lucky" runs — a late, wandering approach
that happened to hit the runway on a clean line. The mechanism is real and present live;
the deliberate trigger misses the geometry.

Date: 2026-06-10. Lab servexeri :28599, mvdsv-lab, serial, 27 runs total, production
28501-28503 untouched. Pre-registration: ledger budget row written BEFORE run 1
(`artifacts/loop-state.md`). Metric and 526 target unchanged throughout.

---

## 1. The KTX change (deployed before any run)

Module `qwprogs-mode21.so` md5 **`ae815cc7871a8cc241d9b4e6145b3403`** (replaces c5
`654149794d3106ea4c4604cb172917e3`); source synced to both local mirrors. Three additive
cvars, all **default 0 = off = the deployed c5 law unchanged**, per the #111 §7 spec:

* `k_fb_moveprobe_s23_launch_vh` / `k_fb_moveprobe_s23_launch_angle` — the one-shot
  circle-jump launch, ported 1:1 from `mode23_sim.mode23_step`: per-slot latch re-armed
  with the spawn-snap latch; engage ray (LOOK=500 toward nav_dir, >=0.9 open); grounded
  circle = wishdir held launch_angle deg off velocity with the jump suppressed; release
  at vh >= launch_vh AND |signed_to_goal| <= swing, or 3 s safeguard.
* `k_fb_moveprobe_s23_deleg_vh_max` — gates BOTH the delegation condition AND the
  carrot's delegation-exact guard on horizontal speed (sim semantics, vh <= max).

**Inertness verdict (gate passed before any screen):**

| check | result |
|---|---|
| code inspection | all new paths cvar-gated; unset => launch block never entered, deleg gate constant-true; compile clean, no warnings |
| free-roam x3 (C1 protocol, cvars unset) | tws **212.8 / 201.7 / 246.6** — all inside [150,280], mean 220.4 >= floor 173; C1 reference 205.2 +/- 31.8 |
| stairs x3 (c5 protocol, cvars unset) | **3/3 arrive 0.9-1.1 s, zero pre-crest presses** — same single crest-resume signature as the c5-era anchor runs |
| discarded cold-start (attempt 0) | 20260610T131048Z, tws 232.6 (standing rule) |

## 2. Screens — per-attempt table (the complete record, no selection)

Protocol per attempt: matchless, mode 23, `--duration 22`, spawn_origin "1959 -425 -24",
fixed_goal 148, config cvars; scored by `scripts/a3_surrogate.py edge` = A0
`route_metrics.edge_speed` at the census sng_to_rl final hard gap over
`legit_segment(rows, ())` truncated at the first 60-qu arrival vs marker-148 nav,
over exactly 20.0 s of trace (the sim budget). Scorer validated before run 1
(stairs anchors reproduce the ledger verdict; rung-A runs give edge=None per STEP-0).

| screen | a1 | a2 | a3 | a4 | a5 | n>=526 | best | median |
|---|---|---|---|---|---|---|---|---|
| S1 launch (p100 n5 s12 t35 c45-85 + cj400a42) | 460.2 | 460.7 | 213.6 | None | 432.1 | **0/5** | 460.7 | 446.2 |
| S2 deleg320 (p130 n5 s12 t35 c45-85 + dvh320) | 428.4 | 469.8 | 483.1 | None | 398.4 | **0/5** | 483.1 | 449.1 |
| S3 C4 (p100 n9 s24 t50 c45-85, cvar-only) | **570.7** | None | 446.9 | 448.6 | 445.5 | **1/5** | 570.7 | 447.8 |
| S4 control (c5 defaults) | 458.9 | 420.5 | 474.3 | 487.0 | None | **0/5** | 487.0 | 466.6 |

(run ids in `screens.json`; medians over present values, None = never crossed, never 0.)

## 3. Sim vs live — the honest deltas

| quantity | sim (fresh 31..60) | live (this block) | delta |
|---|---|---|---|
| S1 launch: median | 496.7 | 446.2 (n=4 present) | **-10.2%** |
| S1 launch: P(>=526) | 7/30 (23%) | 0/5 | n=5 has only ~33% power to pass at the sim rate (see §6) |
| S4 control: median | 459.8 | 466.6 (n=4 present) | **+1.5%** — the base law is calibrated |
| S2 deleg-only: median | 446.8-468.5 (probe) | 449.1 | in band (the 512-median premise was corrected pre-flight, §5) |
| S3 C4: max | 478.1 (30 seeds) | **570.7** (5 attempts) | live tail FATTER than sim's at this config |

The control config sitting +1.5% of its sim twin while the launch config sits -10.2% is
the cleanest possible localization: **the divergence is in the launch->runway seam
specifically, not in the law, the physics port, or the metric.**

## 4. Divergence analysis (pre-named dimensions: engage rate / circle gain / release)

From `divergence.json` (trace-level, all 20 screen runs):

* **Launch engage rate: 5/5.** Every S1 attempt hit 400+ vh grounded in 0.28-0.30 s.
  The engage ray never refused; the spawn-snap latch re-armed correctly.
* **Circle speed gain: transfers.** Peak first-3s vh 420-477 live (sim releases at
  ~400-420). The grounded circle-strafe physics is as strong live as simmed.
* **Release geometry: THE LEAK.** 3/5 S1 runs dove to the pit floor (min z -168 within
  2 s of first reaching 400; the sim run stays on the walkway, z >= -40). The live orbit
  translates the bot ~45 qu off the spawn plateau during spin-up, and the release heading
  clips the walkway's north edge / stair lip (both inspected runs crashed to ~120-180
  vh at (1936..1939, -340..-364) z-40 right after release, then fell).
* **Runway conversion: the second leak.** The S1 runs that DID cross entered the last
  1000 path-qu at **424-447 vh — ABOVE the sim lucky median (386)** — yet crossed at only
  432-461: live gain over the runway **+13..+37 vs the sim lucky tries' +143**. Carried
  speed survives to the runway entry but is shed in the corner + weave touches.
* **The 570.7 proves the runway CAN convert live:** entry 453.1 -> crossing 570.7
  (**+118**, sim-lucky-sized), t_cross 15.3 s — a late, wandering, nav-noise approach,
  exactly the sim's natural lucky shape (late cross after a detour). The deliberate
  launch reproduces the *speed* but not the *line*; the rare organic line converts.
* S2/S3/S4 standing-start entries (150-242 vh) cross at 420-487 — the live "clean direct
  run" ceiling, matching the sim's ~470-510 direct-run band and the A2 sweep's 470
  median ceiling.

## 5. Screen-2 premise correction (disclosed BEFORE run 1)

The amendment glossed S2 as the "512-median family". Pre-flight sim probe
(`deleg-only-probe.json`, anchor `spiker_base/train` reproduced the r2 design-grid row
exactly): every 512.3-median config in the autopsy ALSO ran the spin-up loop
(`spinup76@220/4s`), whose goal-seam cvars are not part of this build; `deleg_vh_max 320`
ALONE sims at median 446.8-468.5, n526 0/60, max 511. S2 was run verbatim as amended
(cvar-only) with expectations set honestly low — and landed exactly in the probe band
(449.1 median, max 483.1).

## 6. Honest statistical note on the screen design

5 attempts per config at the sim's own 7/30 rate: P(>=2 hits in 5) ≈ 33%. The
pre-registered screen had ~one-in-three power to pass even if the sim transferred
PERFECTLY. The bar is the bar (it was pre-registered; this block scores against it),
but the 0/5 on S1 is statistically compatible BOTH with "the tail did not transfer" and
with "the tail transferred at a reduced rate" — while the trace-level evidence in §4
(release dives, runway conversion gap) independently shows a real, mechanistic transfer
loss. The S3 570.7 (a config whose sim n526 was 0/30) additionally shows live tail mass
where sim had none.

## 7. What was deployed / left behind

* Module `ae815cc7...` stays deployed: inertness-verified at defaults (free-roam +
  stairs above), and the three cvars remain per-protocol instruments for whatever is
  decided next. Deployed DEFAULTS are byte-equivalent c5 behavior.
* `scripts/a3_surrogate.py` — the live rung-B edge scorer + stairs pre-crest scorer
  (validated on the c5-era anchors; the crest-resume exclusion is derived from the
  law's own DELEG_DZ=18 remaining-rise rule).
* 27/27 session MVDs archived server-side
  (`/mnt/usb-ssd/non-games/lab/Komodobots/dm3/<runid>.mvd`, sha256-verified). Lab left
  clean (no lab mvdsv).

## 8. Decision needed (escalation)

The pre-registered outcome rule says: leave #75 open, user decides. The live data
suggests these options (not a recommendation ranking):

1. **Re-screen with a release fix** — the leak is the release line, not the spin-up:
   e.g. release only when aimed at the FIRST ROUTE LEG's bearing (not the instantaneous
   nav_dir which may point at the next-hop marker the carrot already handed over), or a
   short post-release straight-aim window. Needs a new sim round first (the sim's own
   release was clean; live cmd cadence/view-lag is the suspect seam) + a fresh
   pre-registered live block.
2. **Hunt the organic tail** — S3's 570.7 shows the standing protocol (C4, cvar-only,
   no launch) reaches 526+ via nav-noise flying starts at some live rate; a bigger-n
   block (n=30+) would measure that rate directly. No KTX change needed.
3. **Accept the ceiling finding** — median-wise live tops at ~466-487; D1 #77 (routing)
   stays blocked on this gate per the plan.

Raw: per-attempt JSONs + probe + divergence in this directory; traces under
`artifacts/lab-runs/<runid>/` (gitignored); demos on the lab SSD.
