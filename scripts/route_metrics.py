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

Both metrics sit on top of legit_segment(): the stray-teleport truncation
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
