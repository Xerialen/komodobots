# Multi-modal sweep → SteerSign Figure-8 policy (+ what the skeptics caught)

Source: a 9-agent dynamic workflow (5 facet extractors → synthesis → 3 perspective-diverse
skeptics) over the one clean human demo, **trick5.cmds** (median 880 / peak 1088, the user's target).
trick1/2/3.cmds are corrupted (impossible 35k qu/s velocities — separate repair needed); dm3_sng is a
different scenario. So the law is learned from trick5 alone (held-out = temporal split of trick5).

Feature table + per-facet aggregations: `jobs/7bae6c77/tmp/trick5_{features,summary}.json`
(extractor: `tmp/extract_features.py`). Full workflow output: task `w4par13h0`.

## The v1 policy (synthesis) — "SteerSign Figure-8"

One master variable `steer_sign s ∈ {+1,-1}` (the figure-8 lobe direction) drives everything,
generatively, from the bot's own state (no demo, no waypoints):

- **View** = slew-rate-limited integrator toward `vel_heading + s·lead(speed)`. Do NOT snap — the
  human's mouse moves at a bounded rate (max 3.58°/frame). `lead` is a **saturating, speed-dependent
  offset** (~12° at 450 → ~66° plateau at ≥850), NOT a fixed angle.
- **Strafe** = `±400` rigid (no deadzone, never released), **forwardmove = 0** (pure lateral strafe;
  fwd only used in the ~1 s launch bootstrap). Sign owned by the lobe machine.
- **Jump** = `1` every frame (continuous bunnyhop; engine self-gates on `onground`). The 0.65 s hop
  period is pure physics (launch_vz 250 / gravity 769), not a clock.
- **Reversal** (the figure-8): flip `s` when integrated `|velocity-heading turned|` since the last
  reversal reaches a lobe target. View + strafe sign **always flip together** off the one `s`.

Verdict on architecture: **all 3 skeptics agree it is seam-realizable AND genuinely generative**
(closed-loop, no replay). The bones are right. The *specifics* are where it's wrong.

## What the skeptics caught (consolidated required fixes = the v2 spec)

**1. CRITICAL — the strafe-sign rule is wrong (2 of 3 skeptics, one by simulation).**
The synthesis set `side_sign = s`, justified by "side == −sign(view_yaw_rate) @ 98.1%." That
correlation is **tautological**: the bot builds its view by slewing in direction `s`, so
`sign(view_yaw_rate)==s` by construction — it proves nothing about which strafe direction *accelerates*.
QW air-accel peaks when **wishdir leads the VELOCITY heading by +60–90°** (the `lvm` geometry, the
84.9% rule the policy dropped). The generative skeptic **simulated both**: `side_sign = s` **collapses
to 421 qu/s (zero accel)**; the accel-correct `side_sign = −sign(dyaw)` **self-sustains**.
→ Fix: hard-code the accel-correct sign (derive strafe from wishdir-vs-**velocity**, not view-slew
direction). Keep the live one-shot dump only as a convention confirmation, not as what picks the sign.

**2. Lead curve is a 2-point overfit.** `clamp(0.13·speed−40, 12, 66)` matches the ≥850 plateau but
over-predicts |lvm| by 14–22° through the 500–700 launch→cruise band. → Refit flatter mid-range
(~12–22° to ~700, then ramp to 66°); sweep `lead_max` 55–72.

**3. Lobe target is one scalar for a bimodal/regime-switching quantity.** Per-lobe `|heading turned|`
is bimodal (short wiggles 40–96° + sustained 165–329°; CV 0.63). A fixed symmetric `LOBE_TARGET=100`
reproduces neither regime and can't trace the high-speed asymmetric lobes that pull the median to 880
(temporal split: 1st half median 732 balanced-wiggle, 2nd half 973 asymmetric-lobe). → Use a 2-state
(wiggle ~90 / sustained ~200) schedule OR a **geometry-gated reversal** (the human's lobe length is
set by trick.bsp's walls, not a fixed integral). Validate by net-signed-heading per 18 s window, not
just median speed.

**4. OMEGA=145 is too low.** High-speed turn heading-rate is med 164 / p90 197°/s; at 145 the bot
under-slews exactly the fast lobes where it must hold its lead → bleeds speed there. → Seed ~175,
sweep 160–195+. (The bot is not bound by human mouse speed — a higher OMEGA may *beat* 880.)

**5. Use REAL KTX frametime** for the `dh_acc` integrator and `OMEGA·dt` slew — not the hardcoded
0.013 s demo tick — or slew rate and lobe trigger mis-scale at the server tickrate. Non-negotiable.

**6. Live-build checks before trusting the sweep:** (a) does the seam honor `jump=1` held every frame,
or is it press-edge-triggered (then need the 1-frame feather)? (b) sidemove sign convention
(`+side` ↔ `view_yaw−90`?) — if mirrored, the bot decelerates.

**7. The t22.8 "artifact" is disputed → treat as a REAL reversal cost.** Facet D called the 1088→811
drop a segmentation artifact; skeptics 1 and 3 checked the exact usercmd stream and found side flips
400→0→−400 with speed collapsing 1087→798 (−27%) — a genuine reversal-induced deceleration near
view/velocity anti-alignment. → Guard the reversal: defer the sign flip until view and velocity are
near re-aligned (`|lvm|` small), so the lobe machine can't fire a decel mid-arc.

## Connection to this session's live mystery

The live mode-16 bot ran **median ~130 / peak ~270** all session — collapsed, no real high-speed
accel. Skeptic 3's sim shows how a single **strafe-vs-velocity sign error collapses accel to ~421**.
Different controller formulation, but the same failure class. **Strong lead: audit the existing
mode-16 carve's strafe/wishdir sign and the "instrument calibration" (mvdsv-lab physics) before
trusting any live number.**

## Validation oracle (for the live sweep)
- `R = v/ω` table: 201@550 .. 315@880 .. 386@1050 (pick ω so measured R matches at target speed).
- Per-18s-window net-signed-heading (catches the symmetric-8-can't-reach-880 failure).
- A second clean demo before locking any scalar (every load-bearing param is fit to trick5 alone).

## OFFLINE VALIDATION — theories confirmed in a sim trusted to 0.1% (2026-06-08)

Built a faithful QW pmove sim (`jobs/.../tmp/qwsim.py`, physics from mvdsv pmove.c: the 30-cap
air-accel). **Trust check:** replaying trick5's exact usercmds pure-air reproduces **median 896 vs
his 895 (0.1% err)**, p90 1021 vs 1026, peak 1079 vs 1088 → the horizontal air-accel is faithful.
(Full sim with my flat-floor ground model was 19% low — mistimed friction — so the ground/launch
model is the weak part, NOT the air-accel.)

**Policy sweep (`qwpolicy.py`), the key fix: the view must ROTATE CONTINUOUSLY through a lobe**
(slew-to-a-fixed-lead settles at a straight-line fixed point and never enters the 8 — that was the
all-400 dead result). With continuous rotation + strafe on the accel side, the figure-8 self-sustains:
- OMEGA→median speed (monotone, clean): 100→1703, 140→1207, 160→1044, 175→947, **185≈880**, 205→793, 260→606.
- **880 lands at OMEGA≈185°/s; lower OMEGA EXCEEDS the human** (the human's 880 is one point on the curve, not a ceiling).
- LOBE_TARGET is the *size* knob (70→1166 .. 300→1273), OMEGA is the *speed* knob — `R=v/ω`.
- Turns GAIN speed (accelerates through the 8); the greedy 1-frame oracle (652) LOSES to the committed
  figure-8 (1044) — which is exactly why hand-crafted "don't lose speed" carving plateaus.
- Sign nuance: the skeptic's "side=s → 421 collapse" was specific to the SLEW primitive; the
  continuous-rotation primitive self-corrects within a lobe and is sign-robust. **Likely why the live
  carve sits at 130** — wrong primitive, not just wrong sign.

Validated: SPEED (to 0.1%). NOT yet: CONFINEMENT (pure-air has no walls) + ground/friction + the live
seam. Confinement is the next offline check (does the 8 stay in trick.bsp ~±1008 at OMEGA≈185).

## FALLBACK STRATEGY (user, 2026-06-08) — decompose launch vs sustained-accel

If the unified policy underperforms live, split into **two connected-but-distinct control problems**:
1. **Maximize the FIRST jump / launch** — a one-shot optimization: standstill → the best initial
   airborne speed AND heading. Currently this is an un-optimized bootstrap (fwd=400 ~1 s) and the sim
   *seeds at 400, skipping it entirely*. The launch sets the initial conditions the figure-8 builds
   from; a bad launch caps everything downstream.
2. **Accelerate after that** — the sustained figure-8 limit cycle (the part validated above).
Optimize each separately (own metric: launch = peak speed+heading at handoff; accel = sustained
median), then tune the handoff between them. This is the debug axis if the combined mode stalls.

## CONFINEMENT SOLVED — the plain orbit, not the figure-8 (2026-06-08)

`qwconfine.py` integrates origin and checks fit vs trick.bsp half-width ~1008.
- **BARE figure-8 drifts off the map** (maxdist 30k-90k) — it's a coil, not a closed 8.
- **Naive position-feedback centering (reverse early when far+outward) COLLAPSES speed to ~420**
  (med 416-459) — reproduces the live 130-420 and the hand-crafted plateau EXACTLY. Forcing
  reversals breaks the accel rhythm. (The crux problem, now reproduced offline in seconds.)
- **PURE CIRCLE (continuous rotation, never reverse) is the answer:**
  - `OMEGA=205 → med 895, peak 904, bbox 929, maxdist 1005 → FITS` (tighter than the human's 1788).
  - OMEGA is the speed/size knob: 185→991 (maxdist 1020, just over), 130→1410 (out). ~205 is the
    sweet spot for 880-confined.
  - Residual drift ~379 qu / 52 s -> a GENTLE position bias (nudge OMEGA / radius by dist-from-center)
    will pin it WITHOUT the speed collapse, because an orbit has no reversal rhythm to break (unlike
    the figure-8's centering). Untested but low-risk.

**Conclusion:** the "540 single-orbit ceiling" was an artifact; a continuous-rotation orbit at
OMEGA≈205 reaches ~880-900 CONFINED on trick.bsp in the trusted sim. **Implement THIS first**
(one-cvar orbit mode) as the validated quick win; evolve to the drift-pinned + figure-8 versions
after it hits ~880 live. Sim scripts: `jobs/.../tmp/{qwsim,qwpolicy,qwconfine}.py`.

## LIVE VALIDATION (mode 18) — the sim↔live gap (2026-06-08)

Implemented mode 18 (`bot_movement.c`, additive; built clean on servexeri, staged qwprogs-orbit18.so).
Live on trick.bsp the bot ORBITS correctly (view yaw steps ~OMEGA/frame, ground=straight / air=side-
strafe, velocity heading follows) — the structural primitive works and the old wall-stall is gone.
**BUT speed plateaus at ~100, NOT the sim's 895** (trend flat; sign flip doesn't help).

Diagnosis: **the pure-air sim was faithful for the REPLAY (air-accel, 0.1%) but NOT for the POLICY.**
The policy exercises the GROUND frames + launch that the pure-air sim ignored. Live, the per-hop
ground/air handoff forces the view-vs-velocity LEAD into a low-speed equilibrium: a fixed/sawtooth
lead φ gives steady-state `v·cosφ=±30` → low v (~100-140), whereas the sim's continuous open-loop
rotation let the lead self-adjust to the high-speed branch. Open-loop rotation also drifts (the
ground frame advances orbit_yaw while velocity is preserved). So the orbit primitive's *speed* result
did not transfer; only its *shape* did.

**This validates the user's launch-vs-accel decomposition directly:** the launch (get airborne +
initial speed) and the sustained orbit-accel ARE separate control problems, and the per-hop ground/air
HANDOFF is exactly where the speed-building breaks. The pure-air sim hid this by skipping both.

**Next:** make the sim faithful WITH ground+jump+launch (re-trust the instrument for the POLICY
use-case, not just the replay), find the orbit/lead law that builds AND confines under real per-hop
dynamics, solve launch + sustained-accel separately (the decomposition), THEN re-deploy. Still far
faster than pure live tuning. Server: symlink on qwprogs-orbit18.so (mode 16 unchanged, hub fine);
revert to stock when fully done.

## SUBAGENT AUDIT of the sim↔reality gap (2026-06-08) — seam INNOCENT, gap is STRUCTURAL

A code-grounded adversarial audit (file:line, verified vs the LIVE server) overturned the top suspicion:
- **The seam is faithful.** `desired_angle[YAW]` reaches pmove **verbatim, same frame, no rate-limit /
  smoothing / delay** (`pr2_cmds.c:2388-2396`, `sv_phys.c:1074/1094`, `pmove.c:905-906`). Not the gap.
- **All constants match live** (serverinfo on mvdsv-lab:28599): maxspeed 320, accel 10, friction 4,
  stopspeed 100, gravity 800, jump 270, the 30-cap formula (`pmove.c:395-416` == `qwsim.air_step`),
  frametime 1/77≈0.013, and bunnyspeedcap/airstep/pground/slidefix all OFF. So the gap is **structural,
  not parametric** — verifying constants (idea #2) and re-reading PM_AirAccelerate (idea #4) were
  already-answered/redundant.
- **The real gap, proven from live telemetry** (runs 134803Z/134055Z): the sim modeled only
  steady-state pure-air horizontal accel and omits three things the orbit policy hits EVERY hop:
  1. **Landing speed-crash**: each landing knocks horizontal speed ~155 → ~35 in 1-2 frames (vz into
     ground + `PM_ClipVelocity` jump-bug clip `pmove.c:718-721` + friction + onground re-accel). The
     air-only sim has no vz/ground/landing → never crashes.
  2. **Ground-frame phase reset**: `moveprobe_orbit18_yaw = heading` every ground frame
     (`bot_movement.c:2505`) restarts the open-loop orbit each hop — it only accrues ~0.65 s of lead
     before being wiped, so it never winds up the sustained lead the sim built over thousands of
     uninterrupted frames.
  3. **Lead collapses out of the accel band**: live, the view **lags** velocity by ~−11° (not leading
     +90°), so `vel·wishdir ≫ 30` → `addspeed<0` → ~zero accel most air frames. R=v/ω has two operating
     points; the sim found the high-speed branch, live is trapped on the low one (reset to ~35 each hop).

**Two concrete fixes the audit pinpointed:**
- Make the sim's ground model a **full landing model** (vz + gravity + jump 270 + the into-ground
  ClipVelocity + ideally stair-step vs trick.bsp floor) — a friction-only term will still mispredict,
  because the dominant loss is the **landing kinetic-energy crash**.
- Make the orbit **velocity-relative**: set wishdir to lead the **velocity heading** by a target
  (+50-70°), NOT advance an open-loop `orbit_yaw` the ground frame keeps resetting (kill the reset at
  `:2505` / carry phase across hops); decouple from ω at low speed. This self-corrects (no drift, no
  phase-reset) and IS the launch-vs-sustained split: "survive the landing without losing 75% of speed"
  (launch/handoff) vs "hold +60° lead in the air" (sustained accel).

**Bridging plan (ranked):** (1) per-frame replay-diff harness driven by the *logged usercmds* with the
full landing model — success = reproduce the 155→35 crash + ~93 median to <10% (this re-trusts the
instrument); (2) anchor it against mode-13's live ~656 before trusting any sweep; (3) only then re-derive
the velocity-relative orbit law offline. Ideas #1/#5/#6 carry the leverage; #2/#3/#4 are already answered.
