# Bunnyhop acceleration on trick.bsp (2026-06-07)

trick.bsp is a pure-acceleration map (open space, no walls/water/hurdles). Acceleration
is the foundational bunnyhop skill — learned before trick jumps — and it was the bottleneck
in the best dm3 corrective-replay run (~20 qu/s under human late-route). So we attack it
directly with a **velocity-aware air-strafe accelerator (KTX moveprobe mode 13)** and measure
**horizontal speed** against the human benchmark.

Human benchmark (your `trick5` demo on trick.bsp): **median 880, peak 1088 qu/s**.

| Arm | run_id | jumps/min | airborne | max hspeed | note |
|---|---|---|---|---|---|
| normal frogbot (mode 0) | 20260607T184752Z | 15 | 8% | 457 | walks the markers, barely hops |
| mode 13, held jump | 20260607T185607Z | **0** | **0%** | 158 | `*jumping=true` every frame → held → spins on the ground |
| mode 13, toggle + air-strafe | 20260607T190104Z | **80** | **96%** | **476** | press on landing / release in air; strafe gated to airborne |

## Findings

1. **Spawn (prerequisite, solved programmatically).** Frogbots only spawn on a map where
   `LoadMap()` set `map_supported = true`, which requires a readable `bots/maps/<map>.bot`.
   trick.bsp ships none, so `addbot` was a silent no-op (the match timed out with no bot).
   `scripts/generate_bot_route.py` builds a `.bot` from a demo trajectory (trick5.cmds → 180
   walkable markers, linked) entirely offline — no in-game waypoint editor, no server-jumping.
   Because the bot is driven by moveprobe, the route graph need not be navigable; it only has
   to load. Confirmed: a bot now spawns and moves on trick.bsp.

2. **Bunnyhop requires a toggled jump (the load-bearing mechanic).** QW's `+jump` jumps once
   then must be *released* before it fires again. The moveprobe modes set `*jumping=true`
   every frame (→ `buttons |= 2` every frame, bot_movement.c), i.e. *held* jump — so the bot
   jumped once and ran on the ground (0 jumps/min, 0% airborne, spinning at ~138 qu/s).
   Toggling the jump on ground contact (press on landing, release in air) **plus** gating the
   velocity-aware air-strafe to the airborne phase (rotating on the ground just spins the bot)
   took the accelerator to **80 jumps/min, 96% airborne, max 476 qu/s**.

3. **Likely explains the chronic weak bot air-speed.** Modes 5–9 and 11 all set
   `*jumping=true` unconditionally → the same held-jump defect → they never bunnyhopped
   properly. This is a strong candidate explanation for S7's "airborne speed 122 vs human 433".

## Status / next

Acceleration is real but **not yet sustained** (median 75, max 476) and far from the human
880/1088. The mechanic is fixed; closing the gap is tuning + refinement, not a new mechanism:
- **numerator sweep** via the retry/auto-tune harness (the controller's strafe aggressiveness),
- **strafe refinement** — the ~90°/frame rotation at speed is too tight (bleeds speed); the
  true optimal angle is smaller, and alternating strafe likely sustains better than a tight circle.

## Apparatus (in this PR)

- KTX `bot_movement.c` (`frogbot-moveprobe.patch`): mode 13 accelerator; jump-toggle;
  the live retry/auto-tune harness on the replay modes (auto-loop, `FBMOVEPROBE_ATTEMPT`
  per-attempt summary, configurable map gate `k_fb_moveprobe_replay_map`, blowup early-abort).
- `scripts/generate_bot_route.py` — demo trajectory → `.bot` spawn-enabler.
- `scripts/run_frobodm2_lab.py` — `--moveprobe-mode 13`, generic `--ktx-extra-cvars` passthrough.
- `experiments/ktx_moveprobe/evidence/trick.bot` — the generated trick.bsp route.
- Demos: `tricks/dm3/trick_accel__*.mvd`.
