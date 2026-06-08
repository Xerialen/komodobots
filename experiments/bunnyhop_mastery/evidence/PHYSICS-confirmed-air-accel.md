# Authoritative QW air-accel model (read from mvdsv source) + what it means for the controller

Date 2026-06-08. Source of truth: `mvdsv/src/pmove.c` (`PM_AirAccelerate`, `PM_AirMove`,
`PM_Accelerate`) — the exact physics the lab server runs. This supersedes every hand-derived
model in this experiment (and the KTX *predictor* at `bot_movement.c:157` which is `FIXME:
assumption`-laden and uses `wishspeed=320` with no cap — that is NOT what the server runs).

## The real air acceleration (per airborne frame)

```
wishspd     = min(wishspeed, 30)          // THE 30-CAP IS REAL
currentspeed = velocity · wishdir          // = |v|·cos(theta)
addspeed    = 30 - currentspeed
if addspeed <= 0: return                    // NO accel unless v·wishdir < 30
accelspeed  = min(accel*wishspeed*frametime, addspeed)   // ~min(41, 30-v·wishdir)
velocity   += accelspeed * wishdir          // add ~ (30 - v·wishdir) along wishdir
```

Consequences (now certain, not guessed):
- **Acceleration requires `v·wishdir < 30`**, i.e. `theta > acos(30/|v|)` — at 900 qu/s that's
  **> 88°**: wishdir must be ~perpendicular to velocity. This is exactly the "productive angle"
  the user and the QW docs describe.
- **Per-frame magnitude added ≈ `(30 - v·wishdir)` along wishdir** (≈30 when ~perpendicular),
  giving a speed gain along velocity of `(30 - v·wishdir)·cos(theta)` ≈ 1 qu/s/frame ≈ **~80
  qu/s²** at speed — matches the human's measured accel rate.
- **Optimal angle that maximises speed gain:** maximise `(30 - v·cos theta)·cos theta`
  → `cos theta = 15/|v|` → **theta\*(v) = acos(15/|v|)** (≈ 81° at 100, 88° at 500, 89° at 900).
  So the ideal is *just under perpendicular*, tightening toward 90° as speed rises.
- **Ground frames** use `PM_Accelerate` (full `wishspeed`, no 30-cap) + friction → the bunnyhop
  jumps every ground frame to avoid friction and keep the gain in the air. (Modes 13/15 already
  jump every ground frame.)

## No server speed cap
`bunnyspeedcap` is **not set** on the lab server (default 0 = off); `sv_maxspeed 320` is only the
wishspeed clamp. So nothing server-side caps horizontal speed — **the ~540 plateau was entirely
the controller**, which is now triple-confirmed (mode-15 v1 already hit 657 > 540).

## Why my empirical angle measurements were wrong (32–55°)
The demo's `svc_playerinfo` velocity is **network-quantized**, so per-frame velocity *direction*
is noisy; angle-of-(view, velocity) computed off it is unreliable (it gave 32–55° on "accel"
frames, which the real rule forbids). The **code is ground truth**, and the **replay (mode 10)
already proved code + the human's exact commands → 880** — so the model is validated end-to-end;
only my per-frame angle read off quantized velocity was bad. Trust the code: optimal ≈ acos(15/v).

## What this settles about the past attempts
- **Mode 13** carved wishdir at `acos(26/v)` ≈ 88° off velocity — *essentially the real optimum*
  — and accelerated to **656**. Its angle was right; it **capped only because it spiralled into
  a wall** (no confinement), not because acceleration stopped.
- **Mode 15** (open-loop constant-side view turn) abandoned the velocity-closed-loop and the
  near-perpendicular wishdir → stalled. Correctly retired.

## The controller to build (now fully grounded)
Per-frame, airborne, closed-loop on velocity:
1. **Accel:** set wishdir at `acos(K/|v|)` off the current velocity, `K ≈ 15–26` (near-perpendicular,
   tightening with speed) — the real optimum; reuse mode 13's proven carve.
2. **Curl phase-switch:** alternate the side/curl sign **smoothly in the jump rhythm** (the user's
   model: "left strafe + leftward curl, then right strafe + rightward curl", smooth not jerky).
3. **Confinement = curl BIAS (the missing piece):** make the alternation *asymmetric* so the net
   path curves — balanced = straight, biased = a turning lobe — keeping it in the room instead of
   spiralling out (mode 13's failure). Swap the bias periodically to alternate lobes → a confined
   figure-8 at the human speed band. No center-anchor state machine, no per-hop pump.

The accel is solved and physics-optimal; **the entire remaining gap to 880 is the curl-bias
confinement layer.**
