# Mode 14 — orbit + carve (generative confined bunnyhop)

The generative controller the replay-seed result pointed to, built on the user's directional
insight: *"you can carve to build speed, but without knowing the direction it won't work.
Tricks is round, so you adjust to it — like dancing: you do all kinds of body moves but you
must face your partner, and you're not always going straight."*

## Two layers, two frequencies (from the trick5 fingerprint)

- **Direction (the lead / "facing the partner") — slow, ~5–10°/s.** A per-slot **base heading**
  that follows trick.bsp's round wall: each frame a `traceline` is cast ahead along the base
  heading; if it hits a wall (`trace_fraction < 1`), the base heading is steered **consistently
  one way** (`k_fb_moveprobe_orbit_dir`), harder the closer the wall, so the heading curves
  along the wall → the bot **orbits the room interior** instead of spiralling out. This is the
  direction the bot was missing in mode 13.
- **Carving (the footwork) — fast, ~145°/s.** Mode-13's air-strafe, but rotated around the
  **base heading** instead of raw velocity: in the air the wish-dir is set to the speed-optimal
  angle `acos(K/|v|)` off the base heading, sign flipped each hop (S-strafe). Net velocity
  tracks the base heading, so the bot stays confined while the capped air-accel builds speed.

Mode 13 carved around raw velocity → radius grew as v² → spiral into walls. Mode 14 carves
around a wall-following base heading → bounded orbit. Same speed mechanism, plus direction.

## New cvars (read via `cvar()`, default when ≤0; set via `--ktx-extra-cvars`)
- `k_fb_moveprobe_orbit_dir` — orbit direction: `<0` = CW, else CCW (default CCW).
- `k_fb_moveprobe_orbit_lookahead` — base wall-sense reach in qu (default 200; `reach = lookahead + 0.3·speed`).
- `k_fb_moveprobe_orbit_turnrate` — deg/s the base heading steers away from a sensed wall (default 120).
- reuses `k_fb_moveprobe_accel_numerator` (K, carve angle) and `_bootstrap_deg`.

## Success metric (same fingerprint)
Live trick.bsp run, single bot, scored by `extract_bunnyhop_fingerprint.py` + `plot_path_ascii.py`:
sustained p50 toward 880, **bounded bbox (~1500–1800) that does NOT grow with time**, wall-hit
−324 resets → ~0, and the path is a **confined orbit** (the bot circles the room, not a spiral).
Mastery = bounded confined orbit at the human speed band, generated (no replay).

## Status
Implemented (`bot_movement.c` mode-14 block; patch regenerated). Pending: Codex review →
build on servexeri → orbit-dir/lookahead/turnrate sweep → score.
