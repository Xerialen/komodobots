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

## Next (PR-B / PR-C)

PR-B wires this unit into KTX — `frogbot-moveprobe-perslot.patch` gains a new
moveprobe **mode 30** that, at the `BotApplyMoveProbe` → `trap_SetBotCMD` seam,
calls `mwv_state_features` on the bot's `self->s.v.velocity` + view angles,
`mshm_write_view`, then `mshm_read_move` with a freshness/fallback check, mapping
the result onto `direction` / `*jumping` (aim + fire stay stock). PR-C runs the
live 5-minute test on the box and records the on-KTX p99.
