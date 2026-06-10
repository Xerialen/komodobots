#!/usr/bin/env python3
"""Shared metric library for komodobots route scoring (Phase 0.4 metric unification).

ONE definition of each speed metric, used by every scorer/gate:

  * time_weighted_speed(rows, ...)  -- THE HEADLINE / PRIMARY GATE METRIC.
    Total xy distance / total wall time over the legit segment, excluding
    the instantaneous displacement of a sanctioned teleport (the throw is
    not player movement). A bot that dead-stops accumulates time but no
    distance, so this cannot be gamed by standing still (unlike an "active
    mean" that drops vh<=threshold ticks).

  * active_mean_speed(rows, ...)    -- the legacy diagnostic metric: mean vh
    over ticks with vh > threshold (default 1), truncated at goal arrival.
    Kept for continuity with existing run reports and the human-baseline
    speed%% column in verify_route.py. Gates use time_weighted_speed as
    primary; active_mean_speed is secondary/diagnostic only.

  * edge_speed(rows, gap, ...)      -- THE LAUNCH-EDGE METRIC (issue #63):
    speed carried at the crossing of a censused gap's launch edge. ">= 526
    qu/s at the launch edge" is the sprint pass condition; this is its one
    definition. None (not 0.0) when the trajectory never crosses the edge.

All metrics sit on top of legit_segment(): the stray-teleport truncation
that stops counting at the first teleporter the route does NOT sanction.
DO NOT weaken or bypass it -- a previous rewrite dropped it and produced a
false "442/79-short" reading from a stray teleporter dumping the bot near
the goal (see MEMORY: "Preserve validator guards on rewrite").

Row format: dicts with at least t, x, y, z, vh; "dist_goal" (distance to the
route goal) is required by the arrival-truncation options.
"""

from __future__ import annotations

import math

# Single-frame origin jump beyond this = a teleport (same constant as the
# original verify_route.py scorer; covers every dm3 teleporter throw).
TELEPORT_JUMP = 250.0

# edge_speed() crossing gates. The launch plane is the vertical plane through
# the censused edge point, perpendicular (in xy) to the edge->land direction.
EDGE_CROSS_EPS = 0.5     # census coords are rounded to 0.1 qu; a real approach
                         # tick at launch speed is ~5-7 qu, so 0.5 only absorbs
                         # that rounding and can never skip a real tick.
EDGE_CORRIDOR = 160.0    # crossing must be within this cross-track distance of
                         # the censused edge point (same half-width as the
                         # verify_route leap-attempt corridor |y-ey| < 160).
EDGE_Z_WINDOW = 100.0    # ... and within this much z of the censused edge
                         # height. The census's own DEEP_DROP criterion: > 100
                         # qu below the lip is the pit, not a launch; +100
                         # bounds it above (jump apex is ~46 qu).


def legit_segment(rows, tele_entrances=(), teleport_jump=TELEPORT_JUMP):
    """Truncate an attempt at the first STRAY teleport.

    `tele_entrances` is the list of (x, y) entrances of teleporters the route
    legitimately uses (e.g. dm3 SNG->RL uses exactly one). Each sanctioned
    entrance may be used ONCE; any other large single-frame origin jump means
    the bot took a wrong teleporter and left the intended route, so we stop
    counting there. Without this, a stray teleporter that dumps the bot near
    the goal's xy (but at the wrong height) is a false positive -- the exact
    trap the old scorer guarded against. DO NOT weaken this.

    With a single entrance this is behaviour-identical to the original
    verify_route.legit_segment (one legit teleport, gated on proximity).
    """
    if not rows:
        return rows
    out = [rows[0]]
    used = [False] * len(tele_entrances)
    for a, b in zip(rows, rows[1:]):
        jump = math.hypot(b["x"] - a["x"], b["y"] - a["y"]) + abs(b["z"] - a["z"])
        if jump > teleport_jump:
            legit = False
            for i, (ex, ey) in enumerate(tele_entrances):
                if not used[i] and math.hypot(a["x"] - ex, a["y"] - ey) < teleport_jump:
                    used[i] = True
                    legit = True
                    break
            if legit:
                out.append(b)        # accept the one legit teleport landing
                continue
            break                    # stray teleport -> truncate the attempt
        out.append(b)
    return out


def _truncate_at_arrival(rows, reach, dist_key="dist_goal"):
    """Cut the idle tail: keep rows up to and including the first tick within
    `reach` qu of the goal (matches the original active-mean end=i+1 rule)."""
    end = len(rows)
    for i, r in enumerate(rows):
        if r[dist_key] < reach:
            end = i + 1
            break
    return rows[:end]


def time_weighted_speed(rows, tele_entrances=(), reach=None, dist_key="dist_goal",
                        teleport_jump=TELEPORT_JUMP):
    """HEADLINE speed metric: total xy distance / total time (qu/s).

    * Applies legit_segment() internally (idempotent if the caller already
      truncated) so a stray teleport can never inflate the distance sum.
    * A SANCTIONED teleport's landing row is kept in the segment (so play
      continues to count), but its instantaneous entrance->exit displacement
      is NOT player movement, so teleport-sized per-tick deltas are excluded
      from the distance sum (Codex PR #60 P2). Real movement never trips
      this: even 1400 qu/s at 77 fps is ~18 qu/tick, far below the threshold.
    * If `reach` is given, the segment is further truncated at the first tick
      within `reach` qu of the goal, so an idle tail after arrival does not
      dilute the metric -- but dead-stops DURING the run do (by design; that
      is what makes this ungameable versus active_mean_speed).
    * Returns 0.0 for segments with < 2 ticks or no elapsed time.

    This is the PRIMARY metric for pass/fail gates.
    """
    rows = legit_segment(rows, tele_entrances, teleport_jump)
    if reach is not None:
        rows = _truncate_at_arrival(rows, reach, dist_key)
    if len(rows) < 2:
        return 0.0
    dist = sum(step for a, b in zip(rows, rows[1:])
               if (step := math.hypot(b["x"] - a["x"], b["y"] - a["y"])) <= teleport_jump)
    dt = rows[-1]["t"] - rows[0]["t"]
    return dist / dt if dt > 0 else 0.0


def final_hard_gap(route_census):
    """The route's goal-gating leap: its FINAL censused hard gap.

    `route_census` is one route's entry from the trick census
    (artifacts/trick-census/census.json, committed copy under
    experiments/nav_doctrine/evidence/trick-census/). Same selection rule
    verify_route.load_route uses for leap geometry. None if the route has no
    hard gaps (then there is no launch edge to measure).
    """
    hard = [g for g in route_census.get("gaps", ()) if g.get("hard")]
    return hard[-1] if hard else None


def edge_speed(rows, gap, tele_entrances=(), teleport_jump=TELEPORT_JUMP,
               corridor=EDGE_CORRIDOR, z_window=EDGE_Z_WINDOW):
    """LAUNCH-EDGE metric: horizontal speed (qu/s) carried at the crossing of
    `gap`'s launch edge, or None if the trajectory never crosses it.

    `gap` is a census gap dict (needs "edge" [x,y,z] and "land" [x,y,...]);
    use final_hard_gap(census[route]) for the route's goal-gating leap, so the
    metric is route-parameterized by the census alone.

    Detection is geometric, so it works for arbitrary (bot) trajectories, not
    just the human replay the census indexed by frame:

      * The launch plane is the vertical plane through the censused edge
        point, perpendicular (in xy) to the edge->land direction. The crossing
        is the FIRST row pair a->b with a behind the plane and b at/past it
        (within EDGE_CROSS_EPS; see the constant).
      * b must be within `corridor` qu cross-track of the edge point and
        within `z_window` qu of the edge height -- a bot that already fell
        > 100 qu below the lip is in the pit, not launching (the census's own
        DEEP_DROP criterion), and a plane crossing far from the edge point is
        a different part of the map.
      * Returns b's vh: exactly the census's human_speed_at_edge convention
        (horizontal speed at the first frame over the deep void). Reproduces
        the census anchors from the committed human replays: sng_to_rl 528.6
        qu/s at frame 510 (required 525.3), sng_shortcut2 458.8.
      * Same domain as time_weighted_speed: legit_segment() is applied
        internally (stray teleport truncates the attempt), and a
        teleport-sized step is not player movement, so it can never register
        as a crossing (the sanctioned-teleport exclusion convention).
      * None -- not 0.0 -- when no crossing exists: "never reached the edge"
        is absence of a measurement, and must not average/gate as a dead stop.

    Caveat (locked by test_first_crossing_wins): on routes that traverse the
    same lip more than once (hilljump, rl_to_bridge), the first traversal of
    that plane geometry is measured, which for the human replays reproduces
    the census number of the FIRST gap on that lip, not the final one. For a
    ">= required" gate this under-reports rather than over-reports, so it is
    conservative; attempt segmentation in verify_route keeps bot attempts to
    a single approach anyway.
    """
    if gap is None:
        return None
    ex, ey, ez = (float(v) for v in gap["edge"][:3])
    ux, uy = float(gap["land"][0]) - ex, float(gap["land"][1]) - ey
    norm = math.hypot(ux, uy)
    if norm <= 0:
        return None
    ux, uy = ux / norm, uy / norm
    rows = legit_segment(rows, tele_entrances, teleport_jump)

    def along(r):
        return (r["x"] - ex) * ux + (r["y"] - ey) * uy

    for a, b in zip(rows, rows[1:]):
        if along(a) >= -EDGE_CROSS_EPS or along(b) < -EDGE_CROSS_EPS:
            continue
        step = math.hypot(b["x"] - a["x"], b["y"] - a["y"]) + abs(b["z"] - a["z"])
        if step > teleport_jump:
            continue            # a teleport throw is not a launch
        cross = abs((b["y"] - ey) * ux - (b["x"] - ex) * uy)
        if cross > corridor or abs(b["z"] - ez) > z_window:
            continue            # crossed the plane, but not at this edge
        return float(b["vh"])
    return None


def active_mean_speed(rows, threshold=1.0, reach=60.0, dist_key="dist_goal"):
    """Legacy diagnostic metric: mean vh over ticks with vh > threshold,
    from segment start until the first tick within `reach` qu of the goal
    (excludes the idle tail). THE one canonical definition -- the historical
    vh>1 rule from verify_route.py; every consumer must import this instead
    of re-implementing it. Gameable by dead-stops (stopped ticks are simply
    dropped), which is why gates use time_weighted_speed() as primary and
    this only for continuity with older reports/human baselines.
    """
    rows = _truncate_at_arrival(rows, reach, dist_key)
    sp = [r["vh"] for r in rows if r["vh"] > threshold]
    return sum(sp) / len(sp) if sp else 0.0
