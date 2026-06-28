# Pinned KTX base snapshot — `QW-Group/ktx@08807da`

These are verbatim, pinned snapshots of the **only three files the KTX live-mode patch
stack MODIFIES** (`experiments/ktx_moveprobe/frogbot-moveprobe-*.patch`). The stack's
other new units (`src/move_shm.{c,h}`, `src/move_world_view.{c,h}`) are **created** by
`frogbot-moveprobe-live.patch` as new-file hunks, so they need no pre-image here.

| file | blob sha @08807da |
|------|-------------------|
| `CMakeLists.txt`      | `d21126ab165e2a2d47484d66f69bbcc6f38be3bc` |
| `src/bot_botgoals.c`  | `541191f7cc5cf564b3094bff597b5f0a1ba04f1d` |
| `src/bot_movement.c`  | `c0654d1bb3c100278bae2df74be86916b4ee2394` |

**Purpose:** `tests/test_ktx_patch_stack_applies.py` applies the documented patch stack
(perslot → live → dump → p99 → fraction) onto this snapshot and asserts every patch
applies clean (`git apply --recount`, rc=0). This guards against the patches silently
drifting out of sync — the failure that blocked the T3.1 handoff toggle (#422/#454):
`-p99` was refined after `-fraction` was generated, so the committed stack no longer
applied clean-room. The test needs **no network clone and no compiler**, so it is
hermetic and safe in the gating floor.

**To refresh** (only if the pinned base or a patch's base context legitimately changes):
re-extract from a `QW-Group/ktx` checkout at the pinned base —
`git show 08807da:<path> > <path>` for each file above — and update the shas.
