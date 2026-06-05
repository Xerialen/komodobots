# Movement Problem

Status: living document.

## Core problem

The immediate challenge is not route learning.

The immediate challenge is understanding whether QuakeWorld bunnyjumping can be expressed as a controllable, measurable, and eventually learnable movement policy inside the KTX/Frogbot architecture.

## Project-level goal

The goal is not:

`Can Frogbots bunnyhop?`

The goal is:

`Can Frogbots become believable stand-ins for real players?`

Bunnyjumping is currently the most visible bottleneck toward that goal.

## What we believe today

- Frogbots move through real server commands.
- KTX converts bot intent into `forwardmove`, `sidemove`, `upmove`, button presses, angles, and impulses.
- Server physics remain engine-native.
- MVD recording remains engine-native.

## What MVDs can and cannot teach us

MVDs are server-side recordings of game state and events.

They can help us observe:

- player position over time
- derived velocity
- route/area movement
- item, damage, frag, weapon, and state context
- view angles or aim when available through parser/fusion outputs

But MVDs generally do not provide clean normal player usercmd labels:

- exact key presses
- exact mouse deltas
- exact `forwardmove`
- exact `sidemove`
- exact jump button timing

This means learning from Milton or other elite players is probably not simple supervised learning from input labels.

The likely problem is inverse control or engine-in-loop optimization:

`observed elite movement trace -> legal server command policy that produces similar movement`

## Movement literacy before route tricks

Do not start with hard trick routes.

Before high-value DM2 routes such as high RL to quad, RA secret exits, or big-to-tele variants, the bot must first learn movement literacy:

- accelerate into bunnyjumping
- preserve speed across repeated jumps
- alternate strafe/yaw appropriately
- time jumps on landing
- steer without overfitting to a route file
- recover when speed, angle, or timing is wrong

## Frobodm2 vs stock DM2

Use `frobodm2` for the first smoke test if it is the easiest way to prove the lab loop works, because the BSP and Frogbot route file are known to exist.

But `frobodm2` is not the final movement target.

The first real movement target is stock DM2 big room, because it is real target geometry while still open enough to isolate bunnyjumping before route-specific tricks.

## NotebookLM-style force-bunnyhop patches

A crude patch such as:

- always jump whenever moving
- globally enable air-rotation/curljump logic
- lower the ground-speed threshold everywhere

may be useful as a lab probe.

It should not be treated as the solution.

The real target is a movement mode or controller with:

- start conditions
- stop conditions
- tactical permission
- speed/yaw targets
- failure recovery
- skill variation
- human-like imperfection

## What is not yet proven

- Whether movement can be cleanly replaced with useful movement without rewriting the bot stack.
- Whether elite movement can be learned from MVD-derived evidence.
- Whether route logic and movement logic are sufficiently decoupled.
- Whether KTX/Frogbots should remain the substrate or be replaced by a new bot architecture.

## First movement override evidence

The first S2 probe found a candidate command-emission seam in KTX/Frogbots:

`src/bot_movement.c::BotSetCommand()` computes the final bot command and sends it through `trap_SetBotCMD(...)`.

Experiment patch:

`experiments/ktx_moveprobe/frogbot-moveprobe.patch`

Two patched `frobodm2` runs on 2026-06-05 produced different evidence:

- `20260605T213010Z`, moveprobe mode `2`: replacing the final movement command with fixed `yaw=90 forwardmove=800` and forced jump still spawned bots, recorded an MVD, parsed successfully, and produced metrics, but the bots were nearly stationary. This proves the command can be replaced, and also shows a naive fixed command is not useful movement.
- `20260605T213149Z`, moveprobe mode `1`: forcing jump while preserving Frogbot movement direction and combat produced a normal lab run with three frags and strong movement metrics. This proves a small final-command override can ride inside the existing KTX/Frogbot shell without breaking spawn, combat, MVD recording, parsing, or metrics.

The v2a comparison then directly logged the final command values:

- `20260605T222006Z`, stock mode `0`: variable yaw/movement commands and normal firing button values.
- `20260605T222047Z`, forced-jump mode `1`: variable yaw/movement commands preserved, while final buttons included jump (`2` or `3`).
- `20260605T222129Z`, fixed-command mode `2`: both bots emitted constant `yaw=90`, `forward=800`, `side=0`, `up=0`, `buttons=2`, and movement collapsed to roughly `1.6`-`1.9` qu/s average with `0.0%` air proxy.

The v2b route-yaw probe then added moveprobe mode `3`:

- `20260605T224811Z`, route-yaw mode `3`: command logging showed varied route-derived yaw, mostly `forward=800`, and jump-bearing buttons. `/ goldenboy` moved plausibly with avg `330.8` qu/s, p95 `464.6` qu/s, and `27.6%` air proxy. `/ bro` had p95 `442.4` qu/s, but also `59.7%` stationary time and avg only `137.4` qu/s.

The v2c repeatability check added `scripts/summarize_moveprobe_plausibility.py` and reran mode `3`:

- `20260605T225720Z`, `frobodm2`: both bots passed the v2c gate. `/ bro` stationary `6.5%`, low-speed `22.1%`; `/ goldenboy` stationary `0.2%`, low-speed `5.1%`.
- `20260605T225802Z`, `dm3`: both bots passed the v2c gate. `/ bro` stationary `1.1%`, low-speed `1.4%`; `/ goldenboy` stationary `0.0%`, low-speed `1.7%`.

This proves the final emitted command can be observed and replaced, and gives repeatable positive movement-feasibility evidence for a route-derived command policy on two routed maps. It is enough to treat S2 as provisionally satisfied pending review. It does not solve aim/movement separation or bunnyjumping: mode `3` still commandeers view yaw, and the fresh short runs recorded no frags.

## First S3a Bunnyjump-Primitive Evidence

Moveprobe mode `4` adds an alternating route-relative sidemove command on top of mode `3`:

- `20260605T231033Z`, `frobodm2`: both bots passed the stricter S3a gate with nonzero side coverage above `94%`, low stationary/low-speed time, and one RL frag. Movement was plausible, but p95 speeds (`358.9` and `364.5` qu/s) were lower than the mode `3` v2c repeat.
- `20260605T231115Z`, `dm3`: side/jump/forward command coverage was above `93%`, but `/ bro` failed low-speed time at `63.0%`; `/ goldenboy` barely passed low-speed at `39.0%`.

This proves a bounded strafe signal can be emitted and measured, but does not prove better movement. The first S3a primitive is therefore a partial/negative result: alternating `+/-400` sidemove at the current cadence can keep bots moving on `frobodm2`, but appears too disruptive or map-sensitive on `dm3`.

## S3b Sidemove Parameter Diagnosis

S3b reused mode `4` on `dm3` but changed the sidemove magnitude:

- `20260605T231737Z`, `sidemove=200`: both bots passed the side/plausibility gate. `/ bro` low-speed improved from the `400` run's `63.0%` to `26.9%`; `/ goldenboy` low-speed was `28.3%`.
- `20260605T231819Z`, `sidemove=300`: side command coverage still exceeded `91%`, but `/ bro` failed low-speed at `51.1%`; `/ goldenboy` passed at `5.6%`.

This suggests the first usable S3 strafe parameter is smaller than the default `400`. It still does not beat route-yaw mode `3` on speed or simplicity, so the next proof should verify `sidemove=200` across maps/repeats before adding cadence or state.

## Working hypothesis

The largest visible realism gap is movement.

The largest visible movement gap is bunnyjumping.

Therefore movement is the first laboratory target.
