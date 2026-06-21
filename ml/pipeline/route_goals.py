#!/usr/bin/env python3
"""route_goals.py — route-conditioning v4 hindsight GOAL labelling (offline, stdlib).

The v4 SELF feature (agent_observation.goal_heading_sincos + goal_dist_norm) needs a
per-tick GOAL = where the player is heading. OFFLINE (training) that goal is the HINDSIGHT
next resource the player actually REACHED on its current leg (goal-conditioned imitation /
GCSL); at INFERENCE the tactical/spawn layer supplies it instead. The goal MATH
(origin+goal -> the 3 channels) is the SHARED scripts/features.agent_observation.goal_vector
(train/serve parity); THIS module is the offline LABELLING only — it never runs live.

Resource visits are detected by POSITION (player within `rho` qu of an item entity), the
SAME flicker-immune segmentation as experiments/route_observatory/route_legs.resource_visits
(`pos.li` flickers at speed -> li legs are geometrically wrong; position legs terminate at
the destination item, validated 89/89 routes). Pure standard library — importable and
testable with no duckdb/numpy, unlike build_features.py (which consumes these).
"""
from __future__ import annotations

import json
import math
from pathlib import Path

# qu resource-visit radius (== experiments/route_observatory/route_legs.DEFAULT_RHO; dm3
# resources are spaced > 2*rho apart, so the nearest-within-rho resource is unambiguous).
GOAL_RHO = 200.0


def load_resource_coords(path) -> dict:
    """{resource_name: (x, y)} from a resource_coords.<map>.json artifact ({} if absent)."""
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError:
        return {}
    return {k: (float(v[0]), float(v[1])) for k, v in d.get("resources", {}).items()}


def resource_visits(positions, coords, rho: float = GOAL_RHO) -> list:
    """Position-based resource visits over one episode's (ox, oy) sequence.

    Returns the [(tick_index, resource_name), ...] where the player ENTERS the rho-radius
    of a resource (nearest within rho wins), collapsing consecutive same-resource ticks and
    ignoring the gap between resources. A None position counts as "at no resource"; `last`
    is held across a gap so a re-dip into the same resource is NOT a new visit. Flicker-
    immune; mirrors the validated route_legs.resource_visits."""
    visits = []
    last = None
    for i, p in enumerate(positions):
        here = None
        if p[0] is not None and p[1] is not None:
            best = rho
            for name, (gx, gy) in coords.items():
                dxy = math.hypot(p[0] - gx, p[1] - gy)
                if dxy <= best:
                    best, here = dxy, name
        if here is not None and here != last:
            visits.append((i, here))
        if here is not None:
            last = here
    return visits


def label_episode_goals(positions, coords, rho: float = GOAL_RHO) -> list:
    """Per-tick hindsight goal (gx, gy) | None for one episode (GCSL).

    A tick's goal is the destination resource of its current leg: between consecutive visits
    (i0->a, i1->b) every tick in [i0, i1] is heading to b -> goal=coords[b]. Ticks outside
    any leg (before the first visit / after the last) -> None (free-roam). Mirrors the leg
    goal in experiments/route_observatory/route_condition.py."""
    goals = [None] * len(positions)
    if not coords:
        return goals
    visits = resource_visits(positions, coords, rho)
    for (i0, _a), (i1, b) in zip(visits, visits[1:]):
        g = coords.get(b)
        if g is None:
            continue
        for i in range(i0, i1 + 1):
            goals[i] = g
    return goals
