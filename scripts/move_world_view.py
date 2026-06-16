#!/usr/bin/env python3
"""Shared world-view feature module (bot-program T0.4).

SINGLE SOURCE OF TRUTH for the MoveMLP world-view feature vector.

The same feature computation MUST be used everywhere a world-view is built:
  - OFFLINE: the dataset builder (experiments/stage2/move-bc-train/build_dataset.py)
    and the open/closed-loop evaluators (eval_openloop.py / eval_closedloop.py).
  - LIVE (future, T0.6): the policy sidecar that serves MoveMLP per tick.

If offline and live build the feature vector differently the policy sees
train/serve skew and gets confused (docs/18 wall #2: "one world-view, built the
SAME way offline + live"). Routing every caller through this one function makes
that skew impossible by construction and gives the T0.5 golden-vector parity
test a single thing to pin.

This module is intentionally PURE STDLIB (math only) -- no numpy, no torch -- so
that:
  * the unit test runs on the CI stdlib floor (.github/workflows/pr-tests.yml),
  * the live sidecar can import it with a minimal dependency footprint.

THE FEATURES (state-only, velocity-relative, map-agnostic -- never derived from
the action being predicted, so the policy cannot cheat). See
docs/13_FIRST_DM3_TRAINING_RUN.md and docs/18_BENCH_ITERATED_BOT_PROGRAM.md:

  hspeed/320          horizontal speed, maxspeed-normalised
  vz/320              vertical velocity, maxspeed-normalised
  lvm_sin, lvm_cos    look-lead = signed angle(view-yaw - velocity-heading),
                      the air-accel 'lvm' control axis, as sin/cos (continuous,
                      wrap-safe). When |v_h| ~ 0 the heading is undefined -> 0.
  moving              1 if |v_h| >= 1 else 0 (heading-valid flag)
  pitch/90            view pitch (small, but tells the net up/down look)

This is exactly the *state* side of fit_air_law.frame_quantities; the action
side (wishdir-vs-velocity 'rotation') is the LABEL space, not an input.

NOTE on `onground`/`pm_code`: the .qwd POV svc_playerinfo recovery does NOT
carry server-side ground/pmove flags -- every offline shard row has
onground=false, pm_code=0. So onground is deliberately NOT a feature here (it is
constant and uninformative offline). Ground state is re-derived from dm3
geometry inside pmove_sim where it is actually needed; it never enters the
world-view feature vector.

Provenance / canonicalisation (T0.4): before this module the identical
computation was duplicated inline in build_dataset.py and in
eval_openloop.state_features (imported by eval_closedloop). Those copies were
bit-for-bit identical; this module is now the canonical definition and the
callers import from here.
"""
from __future__ import annotations

import math

# Ordered names of the world-view features this module produces. The order is
# load-bearing: it is the column order of the offline dataset X matrix and the
# input order MoveMLP was trained on. Do not reorder without retraining.
FEATURE_NAMES = ["hspeed/320", "vz/320", "lvm_sin", "lvm_cos", "moving", "pitch/90"]
FEATURE_DIM = len(FEATURE_NAMES)

# Canonical full-deflection / maxspeed normaliser (qu/s). Horizontal speed and
# vertical velocity are divided by this so the net sees order-1 magnitudes.
MAXSPEED = 320.0

# Below this horizontal speed (qu/s) the velocity heading is numerically
# meaningless, so the look-lead angle is undefined and reported as not-moving.
MOVING_EPS = 1.0

# View pitch normaliser (degrees). Pitch is clamped to +/-90 by the engine.
PITCH_NORM = 90.0


def wrap180(d: float) -> float:
    """Wrap an angle in degrees to (-180, 180].

    Matches build_dataset.wrap180 / eval_openloop.wrap180 exactly.
    """
    return (d + 180.0) % 360.0 - 180.0


def state_features(vx: float, vy: float, vz: float, yaw: float, pitch: float):
    """Compute the MoveMLP world-view feature vector for one frame's STATE.

    Inputs are the raw state quantities available BOTH offline (from a decoded
    .qwd frame: velocity + recorded view angles) AND live (from the server each
    tick: the bot's velocity + current view angles) -- so this is the single
    function the offline builder and the live sidecar (T0.6) both call.

    Args:
        vx, vy, vz: velocity components in quake units / second.
        yaw:        view yaw in degrees (angles[1]).
        pitch:      view pitch in degrees (angles[0]).

    Returns:
        tuple of FEATURE_DIM python floats, in FEATURE_NAMES order:
        (hspeed/320, vz/320, lvm_sin, lvm_cos, moving, pitch/90).

    The body is byte-for-byte the previous inline computation (build_dataset
    _features_and_labels and eval_openloop.state_features); see module docstring.
    """
    hsp = math.hypot(vx, vy)
    moving = 1.0 if hsp >= MOVING_EPS else 0.0
    if moving:
        vhead = math.degrees(math.atan2(vy, vx))
        lvm = math.radians(wrap180(yaw - vhead))
        lvm_sin, lvm_cos = math.sin(lvm), math.cos(lvm)
    else:
        lvm_sin, lvm_cos = 0.0, 0.0
    return (hsp / MAXSPEED, vz / MAXSPEED, lvm_sin, lvm_cos, moving, pitch / PITCH_NORM)
