"""route_grade.py — the honest OFFLINE route-completion grade for the Phase-2 RL policy (D1).

Grades ONE closed-loop trajectory (the PPO policy driving pmove_sim) against its human-reference
route. The docs/28 goal is information-honest SUPERHUMAN movement, validated route-first — so the
grade is NOT route-shape MSE alone: adherence-MSE is speed-blind, so a non-bhop forward+strafe
"hybrid" that hugs the human line scores a good MSE (the observed R5 failure). The honest gate pairs
three criteria, ALL required to pass:

  1. on_route          — lateral (horizontal) RMSE off the human polyline within a LOOSE containment
                         tolerance (still running the route / not lost into a wall). NOT a centerline
                         match: matching the human line would cap the bot at the human's path (docs/28).
  2. faster_than_human — median along-route speedup ratio (v_along / human v_ref here) >= 1.0, i.e. at
                         least human speed on the stretch. Uses reward_onspeed.route_speedup so the
                         gate's ratio is IDENTICAL to the one the reward optimizes.
  3. clean_mechanism   — the fraction of AIRBORNE ticks holding +forward (fwd_am==2) is capped: a clean
                         air-strafe bhop releases forward in the air (the 30-qu/s air cap makes forward
                         add ~0 speed there; QWD action oracle / #427 D6), a bulldoze-hybrid does not.

Route-shape RMSE is measured HORIZONTALLY (z zeroed) so a bhop's vertical bounce does not inflate it.

Pure stdlib (math) — lands in the merge-gate test floor. The torch-side driving of the policy through
pmove_sim (ml/eval_broad_closedloop.py) feeds trajectories into grade_trajectory().
"""

import logging
import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from route_geom import project_onto_polyline  # noqa: E402
from reward_onspeed import route_speedup      # noqa: E402  (pure stdlib; shares the ratio the reward uses)

LOGGER = logging.getLogger(__name__)

# All thresholds are TUNABLE (owned by #428 eval-metric tuning / #429 search). Defensible defaults,
# NOT human-match targets.
DEFAULT_GRADE_CFG = {
    # (1) route-shape adherence: a LOOSE horizontal containment floor (qu of lateral RMSE), NOT a
    #     centerline match — a superhuman line may legitimately differ from the human's.
    "rmse_tol": 128.0,
    # (2) faster-than-human floor: median along-route speed >= human's here (1.0 = at least human;
    #     raise above 1.0 to demand strictly superhuman).
    "min_ratio": 1.0,
    # (3) anti-bulldoze-hybrid: max fraction of AIRBORNE ticks holding +forward.
    "max_air_forward_frac": 0.20,
}

# fwd_am value meaning "+forward held" (mirrors the reward / usercmd forwardmove +400 class == 2).
_FWD_PRESS = 2


def _median(xs):
    s = sorted(xs)
    n = len(s)
    if n == 0:
        return 0.0
    mid = n // 2
    if n % 2:
        return s[mid]
    return 0.5 * (s[mid - 1] + s[mid])


def _polyline_len(polyline):
    total = 0.0
    for i in range(len(polyline) - 1):
        ax, ay, az = polyline[i]
        bx, by, bz = polyline[i + 1]
        total += math.sqrt((bx - ax) ** 2 + (by - ay) ** 2 + (bz - az) ** 2)
    return total


def _empty_grade(cfg):
    return {
        "route_rmse_qu": 0.0, "median_speedup_ratio": 0.0, "mean_speedup_ratio": 0.0,
        "faster_than_human_frac": 0.0, "air_frac": 0.0, "air_forward_press_frac": 0.0,
        "n_ticks": 0, "on_route": False, "faster_than_human": False,
        "clean_mechanism": False, "passed": False, "cfg": cfg,
    }


def grade_trajectory(traj, route, cfg=None):
    """Grade ONE closed-loop trajectory against its human-reference route (the D1/D2 honest gate).

    traj  : list of per-tick dicts, each with keys ox, oy, oz, vx, vy, onground (bool),
            fwd_am (int; 2 == +forward held). Extra keys are ignored.
    route : dict with polyline=[(x,y,z),...], speeds=[per-vertex human speed], total_len (optional).
    cfg   : threshold overrides (see DEFAULT_GRADE_CFG).

    Returns a grade dict: route_rmse_qu, speedup stats, mechanism fractions, the three per-criterion
    booleans (on_route / faster_than_human / clean_mechanism), and the overall `passed` (all three).
    """
    c = dict(DEFAULT_GRADE_CFG)
    if cfg:
        c.update(cfg)
    polyline = route.get("polyline") or []
    speeds = route.get("speeds") or []
    n = len(traj)
    if n == 0 or len(polyline) < 2:
        return _empty_grade(c)
    total_len = route.get("total_len") or _polyline_len(polyline)
    # Horizontal polyline for the lateral RMSE (so a bhop's vertical bounce does not count as deviation).
    polyline_2d = [(float(p[0]), float(p[1]), 0.0) for p in polyline]

    sum_dist_sq = 0.0
    ratios = []
    fth_ticks = 0
    air_ticks = 0
    air_fwd_ticks = 0
    for t in traj:
        ox, oy, oz = float(t["ox"]), float(t["oy"]), float(t["oz"])
        vx, vy = float(t.get("vx", 0.0)), float(t.get("vy", 0.0))
        proj2 = project_onto_polyline(ox, oy, 0.0, polyline_2d)
        if proj2 is not None:
            sum_dist_sq += proj2["distSq"]
        _v_along, _v_ref, ratio, _arc = route_speedup(ox, oy, oz, vx, vy, polyline, speeds, total_len)
        ratios.append(ratio)
        if ratio > 1.0:
            fth_ticks += 1
        if not bool(t.get("onground", False)):
            air_ticks += 1
            if int(t.get("fwd_am", 0)) == _FWD_PRESS:
                air_fwd_ticks += 1

    rmse = math.sqrt(sum_dist_sq / n)
    median_ratio = _median(ratios)
    mean_ratio = sum(ratios) / n
    air_fwd_frac = (air_fwd_ticks / air_ticks) if air_ticks else 0.0

    on_route = rmse <= c["rmse_tol"]
    faster_than_human = median_ratio >= c["min_ratio"]
    clean_mechanism = air_fwd_frac <= c["max_air_forward_frac"]

    return {
        "route_rmse_qu": round(rmse, 3),
        "median_speedup_ratio": round(median_ratio, 4),
        "mean_speedup_ratio": round(mean_ratio, 4),
        "faster_than_human_frac": round(fth_ticks / n, 4),
        "air_frac": round(air_ticks / n, 4),
        "air_forward_press_frac": round(air_fwd_frac, 4),
        "n_ticks": n,
        "on_route": on_route,
        "faster_than_human": faster_than_human,
        "clean_mechanism": clean_mechanism,
        "passed": bool(on_route and faster_than_human and clean_mechanism),
        "cfg": c,
    }
