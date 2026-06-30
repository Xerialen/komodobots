"""Pure-stdlib polyline geometry helpers (shared by the live-metrics panel test and
the #427 Phase-2 reward).

These were the in-test re-implementations of the pure functions in
`lab/dashboard/.../LiveMetricsPanel.tsx` (kept in sync with the TS by
`tests/test_live_metrics_panel.py`). They are promoted here unchanged so the #427
reward (`reward_onspeed.py`) can project a bot position onto its route's human-reference
polyline — arc-length progress (Progress+) and the local route tangent (the direction
the Velocity+ term projects onto) — without importing from a test module.

stdlib only (math). No torch/numpy — lands in the gating test floor.
"""

import logging
import math

LOGGER = logging.getLogger(__name__)


def dist3_sq(ax, ay, az, bx, by, bz):
    dx, dy, dz = bx - ax, by - ay, bz - az
    return dx*dx + dy*dy + dz*dz


def project_onto_segment(px, py, pz, ax, ay, az, bx, by, bz):
    """Return (t, dist_sq) where t in [0,1] is the clamp parameter."""
    abx, aby, abz = bx - ax, by - ay, bz - az
    ab_len_sq = abx*abx + aby*aby + abz*abz
    if ab_len_sq == 0:
        return 0.0, dist3_sq(px, py, pz, ax, ay, az)
    apx, apy, apz = px - ax, py - ay, pz - az
    dot = apx*abx + apy*aby + apz*abz
    t = max(0.0, min(1.0, dot / ab_len_sq))
    projx = ax + t*abx
    projy = ay + t*aby
    projz = az + t*abz
    return t, dist3_sq(px, py, pz, projx, projy, projz)


def project_onto_polyline(px, py, pz, polyline):
    """
    Returns dict with arcFrac, distSq, segIndex, segT; or None if <2 points.
    """
    n = len(polyline)
    if n < 2:
        return None

    seg_lens = []
    total_len = 0.0
    for i in range(n - 1):
        ax, ay, az = polyline[i]
        bx, by, bz = polyline[i + 1]
        seg_len = math.sqrt(dist3_sq(ax, ay, az, bx, by, bz))
        seg_lens.append(seg_len)
        total_len += seg_len

    if total_len == 0:
        return None

    best_dist_sq = float('inf')
    best_seg = 0
    best_t = 0.0

    for i in range(n - 1):
        ax, ay, az = polyline[i]
        bx, by, bz = polyline[i + 1]
        t, dist_sq = project_onto_segment(px, py, pz, ax, ay, az, bx, by, bz)
        if dist_sq < best_dist_sq:
            best_dist_sq = dist_sq
            best_seg = i
            best_t = t

    arc_to_seg = sum(seg_lens[:best_seg])
    arc_pos = arc_to_seg + best_t * seg_lens[best_seg]
    arc_frac = arc_pos / total_len

    return {
        'arcFrac': arc_frac,
        'distSq': best_dist_sq,
        'segIndex': best_seg,
        'segT': best_t,
    }


def interpolate_speed_at_arc(arc_frac, polyline, speeds):
    """Linear interpolation of speed at arc_frac from per-vertex speed array."""
    n = len(polyline)
    if n < 2 or len(speeds) != n:
        return None

    total_len = 0.0
    cum_len = [0.0]
    for i in range(n - 1):
        ax, ay, az = polyline[i]
        bx, by, bz = polyline[i + 1]
        seg_len = math.sqrt(dist3_sq(ax, ay, az, bx, by, bz))
        total_len += seg_len
        cum_len.append(total_len)

    if total_len == 0:
        return speeds[0]

    target = arc_frac * total_len

    # Binary search for the segment containing target.
    lo, hi = 0, n - 1
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if cum_len[mid] <= target:
            lo = mid
        else:
            hi = mid

    seg_len = cum_len[lo + 1] - cum_len[lo]
    t = (target - cum_len[lo]) / seg_len if seg_len > 0 else 0.0
    return speeds[lo] + t * (speeds[lo + 1] - speeds[lo])
