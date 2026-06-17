# `live/` — the C side of the live-brain loop (bot-program T0.3)

This directory is the **C half** of the Phase-0 live-brain loop (docs/18 wall #1
"Live brain pipe", wall #2 "one world-view built the same way offline + live").
KTX's new live mode computes the world-view and talks to the MoveMLP sidecar
(`scripts/move_policy_sidecar.py`, T0.6) over the T0.2 POSIX-shm transport. For
that to be safe the C side must agree with the Python **source of truth**
bit-for-bit; this unit is written to be, and CI-tested for, exactly that.

## Files

| file | what | Python source of truth |
|------|------|------------------------|
| `move_world_view.{c,h}` | the 6 world-view features (hspeed/320, vz/320, lvm_sin, lvm_cos, moving, pitch/90) | `scripts/move_world_view.py:state_features` (T0.4) |
| `move_shm.{c,h}` | `/dev/shm` region layout + odd/even two-guard seqlock + **VIEW writer** (KTX role) + **MOVE reader** (KTX role) + region lifecycle | `scripts/move_policy_sidecar.py` (T0.6) |
| `selftest_main.c` | a CLI harness exercising each production role, driven by the CI gate | — |

KTX is the **writer** of the VIEW record (world-view, KTX → sidecar) and the
**reader** of the MOVE record (decision, sidecar → KTX). The sidecar is the
mirror. This unit implements exactly those two roles plus region create/zero
(KTX owns creation; the sidecar attaches).

### Parity traps deliberately handled

- `wrap180` uses **Python's floored modulo** (`a - floor(a/b)*b`), not C `fmod`
  (which takes the dividend's sign). `(yaw - vhead)` is routinely negative, so
  `fmod` would diverge from `move_world_view.py` on any left-of-heading look.
- features are computed in `double` (matching Python's `math` module) and stored
  as `float` — the f32 wire precision the VIEW record carries, so C and Python
  agree at the bits that actually cross the transport.
- the seqlock marks **both** guards odd before the body and publishes the even
  value trailing-guard-first / leading-last — the Codex-reviewed T0.6 fix
  (sidecar commit `953ad70`); a single odd-leading-guard scheme lets a reader
  accept a torn body.

## The CI byte-match gate

`tests/test_live_c_parity.py` compiles this unit with `cc` (skips clean if no
compiler; GitHub's `ubuntu-latest` has gcc) and asserts, over a shared
`/dev/shm` region, in **both production directions**:

- feature parity at f32 over an 8,250-state grid (negative-yaw / wrap-boundary /
  standstill / overspeed included);
- C writes VIEW → Python `read_view` decodes == inputs;
- Python writes MOVE → C `read_move` decodes == inputs;
- seqlock retry correctness (odd / mismatched-even guards → not-fresh);
- a C-created region attaches clean in Python.

## Build / test locally

```bash
# the gate (compiles the unit + drives it against the Python modules)
python3 -m unittest tests.test_live_c_parity -v

# warning-clean standalone compile
cc -O2 -std=c11 -Wall -Wextra -Werror -o /tmp/live_selftest \
   experiments/ktx_moveprobe/live/move_world_view.c \
   experiments/ktx_moveprobe/live/move_shm.c \
   experiments/ktx_moveprobe/live/selftest_main.c -lm
```

## KTX integration (PR-B): `frogbot-moveprobe-live.patch`

PR-B wires this unit into KTX as a **layered** patch
(`experiments/ktx_moveprobe/frogbot-moveprobe-live.patch`) that applies *on top
of* the baseline `frogbot-moveprobe-perslot.patch` — the tested baseline is left
untouched. The live patch:

- adds `src/move_world_view.{c,h}` + `src/move_shm.{c,h}` to the KTX tree (copies
  of these files; the drift guard `tests/test_live_patch_sync.py` keeps them
  byte-identical to the canonical unit here);
- adds those two `.c` to the `CMakeLists.txt` source list;
- gives `bot_movement.c` a new moveprobe **mode 30** that, at the
  `BotApplyMoveProbe` → `trap_SetBotCMD` seam, calls `mwv_state_features` on
  `self->s.v.velocity` + `self->fb.desired_angle` (`[0]`=pitch, `[1]`=yaw),
  `mshm_write_view`, then `mshm_read_move` with a freshness/fallback check,
  mapping the result onto `direction` / `*jumping` (aim + fire stay stock). A
  missing region / torn read / stale answer leaves the stock-frogbot move
  untouched — the bot never freezes.

**Native-only.** All of the above is `#ifndef Q3_VM`-guarded; the QVM build
compiles the unit to empty TUs and `BotApplyMoveProbeLive` to a no-op, so the box
runs it in the native `qwprogs.so` and the QVM target still builds clean.

### Apply + build (both patches; the box uses `--recount`)

```bash
cd <ktx-checkout-at-08807da>
git apply --recount experiments/ktx_moveprobe/frogbot-moveprobe-perslot.patch  # baseline
git apply --recount experiments/ktx_moveprobe/frogbot-moveprobe-live.patch     # live mode
cmake -DBOT_SUPPORT=1 -DCMAKE_BUILD_TYPE=Release -S . -B build && cmake --build build -j   # -> qwprogs.so
```

Verified in a sandbox clean-room (stock `QW-Group/ktx@08807da` → baseline → live
→ native `qwprogs.so`, warning-clean). The box build (in the exact prod
toolchain) is the remaining confirmation, done in PR-C.

### mode-30 cvars (per-slot via the existing `_s<N>` plumbing)

| cvar | default | meaning |
|------|---------|---------|
| `k_fb_moveprobe_mode_s<N>` | unset | set to `30` to put bot slot N in live mode |
| `k_fb_moveprobe_live_shm_name[_s<N>]` | `komodo_move_t06` | shared region name (must match the sidecar's `--shm-name`) |
| `k_fb_moveprobe_live_stale_ticks` | `3` | freshness window; accept a MOVE answered within this many ticks, else fall back |
| `k_fb_moveprobe_live_log` | off | `1` → throttled `[moveprobe-live] … LIVE/FALLBACK` lines **and** a periodic on-KTX p50/p99/max cost summary (PR-C) to the server log |

## PR-C — live loop validated on the box (#209)

PR-C added CPU torch + the checkpoint on the box, the on-KTX cost instrumentation
(`frogbot-moveprobe-live-p99.patch`), and ran the live loop end to end. Full
runbook + evidence: **`../T0.3_LIVE_MODE.md`** (machine-readable
`../evidence/t0.3_live_mode.json`; launcher `../run_live.sh`).

Result: 1+ bot live on dm3, no freeze, `LIVE` cmds in the log, clean `FALLBACK`
when the sidecar is paused (and `LIVE` on resume), and **on-KTX p99 ≤ 5 µs**
(max 17–83 µs) vs the 0.5 ms budget — ~100× margin, closing the T0.2 loop on the
real server.
