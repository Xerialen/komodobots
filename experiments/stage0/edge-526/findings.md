# Stage-0 Spike 1 — 526 reachability as geometry, not "KTX accel ceiling"

Status: spike complete. Offline, no ML, no torch, no live server. All physics
from the validated MVDSV pmove port (`scripts/pmove_sim.py`) rolled out on the
real dm3 BSP v29 (`scripts/bsp_geom.py`). Probe: `probe_edge_526.py`; raw numbers:
`results.json`.

## Verdict (one line)

**REACHABLE.** A believable, physically-legal approach can carry **>= 526 qu/s**
at the actual dm3 SNG->RL launch edge — with margin. **This is NOT a physics-ceiling
finding.** The binding constraint is **controller quality / reliable bunnyhop
navigation to the edge**, the same navigation gap the dm3 instrument already
flagged — not the accel model, not the run-up distance, not through-air retention.

| Question | Answer | Evidence |
|---|---|---|
| Reachable under a believable approach? | **YES** | three independent lines below |
| Binding constraint | **navigation / controller quality** (carry speed through the corridor to the edge) | greedy controller never reaches edge xy |
| Best achieved edge speed | **528 (human)** / 552 (free-air optimal) / 432 (best synthetic hand controller on-map) | C/B below |
| Physics-ceiling finding to surface? | **NO** | substrate permits it with margin |

## The geometry (Task 1)

From `dm3_jump_geom.json` (validated: human clears by ~2 qu/s) and `bsp_geom`:

- **Launch edge:** ~(1477, 53, +5.5), grounded, human carries **528.2 qu/s** horizontal.
- **Gap:** 339.5 qu over a void floor at z = -392; **drop** to landing at (1615, 363, -60).
- **Flight time** ~0.645 s at g = 800 => **required launch speed = 526.2 qu/s.**
- **Run-up path / available room (the re-framed question):** the legit approach
  is gated by the **single sanctioned SNG->exit teleporter** (entrance ~(-539,-454)).
  The teleporter **dumps the player at (224,-320,+75) carrying only ~299.8 qu/s**
  (measured at the human's frame 128). So the *effective* run-up to the edge is:
  - **distance:** ~**2242 qu** of xy arc (teleporter exit -> launch edge),
  - **time / frame budget:** ~**383 frames** (~5.0 s at 13 ms/frame),
  - **of which the human spends 342 airborne, 41 on the ground** (re-derived by
    replaying the human inputs through `pmove_sim`).
  - Entry speed **300 -> 528** over that run-up. The full route arc (start->edge,
    including the pre-teleport segment) is ~3542 qu, but the teleporter resets
    speed, so **only the post-teleport 2242 qu / 342 air-frames is the binding
    accelerating window.**

## The probes (Tasks 2-3) — all on the real dm3 BSP / validated sim

**Port validation first.** Replaying the human `.cmds` free-run through
`pmove_sim` reproduces the entire route to **max error 0.2 qu**, and the
launch-edge speed reproduces as **529.1 qu/s** (recorded 528.2). The sim is
ground truth; every controller below is judged on the same sim.

### A — Free-air accel ceiling (geometry-free)
Optimal perpendicular air-strafe (`|v|^2 += 900` per air frame, the mvdsv 30-cap
optimum) from 300 qu/s needs **208 air-frames** to reach 526. The run-up provides
**342** air-frames. => **The air-frame budget is ample — accel is not the ceiling.**
(Consistent with the program's note that KTX already sustains ~810/peak 1452 on
trick.bsp; raw accel was never the wall.)

### B — Run-up-bounded straight strafe-jump (free-air upper bound)
A perfect serpentine strafe-jump whose net travel is a straight line, integrating
the exact mvdsv air-accel with real ground-friction hop landings, **reaches 552.8
qu/s while covering the 2242 qu run-up** (best of a wobble/hop-cadence sweep;
reproducible). => **The run-up distance is sufficient; through-air retention is
sufficient.** (The sweep is sensitive to serpentine parameters — some configs
spiral — so B is read as an existence-style *upper bound*, not a precise optimum.)

### C — On the real dm3 BSP, along the human corridor (teleporter exit -> edge)
- **Human replay:** 529.1 qu/s (validation).
- **Greedy one-step-lookahead hand controller** (mode-20 style; per-frame yaw
  chosen to maximise next-frame speed via real-pmove lookahead while steering to
  the edge): **387.3 qu/s, peak 477.** Its *per-air-frame* gain is actually good
  (1.22 vs the human's 1.02), but it only logs **146 air-frames vs the human's
  342** and **never reaches the edge xy** (stalls near x~1000 vs the edge at
  x~1477) — it scrapes the floor instead of bunnyhopping cleanly through the
  corridor.
- **Best fixed-angle strafe sweep:** **432 qu/s** (theta=45deg).

So the synthetic hand controllers fall ~94 qu/s short of 526 **on the map** — but
the shortfall is diagnosed as **failure to bunnyhop the corridor to the edge**
(low air-frame fraction, never arrives), exactly the "unreliable navigation to the
edge" the dm3 README already named, **not** an accel/retention limit.

## Binding constraint (Task 3, quantified)

| Candidate constraint | Status | Number |
|---|---|---|
| Accel model (raw) | **not binding** | 208 air-frames needed << 342 available |
| Run-up distance | **not binding** | 552 reached over 2242 qu (req 526) |
| Through-air retention | **not binding** | free-air straight run holds to 552 |
| Approach line / edge geometry | **not binding** | human clears the same edge at 528 on the sim |
| **Controller quality / navigation to the edge** | **BINDING** | synthetic best 432 / greedy never reaches edge xy |

## Surface-or-tune-around discipline

Per the program's rule ("if a target is unreachable under the substrate, surface
it as a finding — don't tune around it"): **526 IS reachable under the substrate,
so there is no physics-ceiling finding to surface here.** The honest finding to
carry forward is the opposite and useful: **the Stage-1+ movement blocker is
reliable bunnyhop navigation that carries speed through this corridor to the
edge**, not whether 526 is physically possible. That question is now **retired** —
the hand-mover (Stage 1) and learned MOVE (Stage 2) are aimed at a target that is
known-achievable with margin (human 528, free-air 552 vs required 526).

## Reproduce

```
python experiments/stage0/edge-526/probe_edge_526.py
# writes experiments/stage0/edge-526/results.json
# port validation: python scripts/pmove_sim.py replay \
#   --cmds experiments/dm3_sng_to_rl_observability/evidence/dm3_sng_to_rl.cmds
```

## Caveats / honest limits
- `pmove_sim` collides only the worldmodel — **no submodels (lifts/doors/plats)
  and no other players.** The dm3 SNG->RL corridor's lift is therefore not modelled;
  the human replay nonetheless reproduces to 0.2 qu, so the binding accelerating
  window (post-teleport, on the main brushwork) is faithfully captured.
- Experiment B's serpentine integrator is an analytic *upper bound* with known
  parameter sensitivity; the load-bearing reachability evidence is the **human
  existence proof (A's budget + the validated 528 on the same sim)**, which needs
  no synthetic controller to hold.
- The synthetic controllers are deliberately simple (greedy / fixed-angle); a
  better hand controller would close the on-map gap. Their shortfall is reported
  as a *controller-quality* lower bound, not a physics result.
