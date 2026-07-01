"""route_grade.py — the honest OFFLINE route-completion grade for the Phase-2 RL policy (D1).

Grades ONE closed-loop trajectory (the PPO policy driving pmove_sim) against its human-reference
route. The docs/28 goal is information-honest SUPERHUMAN movement, validated route-first — so the
grade is NOT route-shape MSE alone: adherence-MSE is speed-blind, so a non-bhop forward+strafe
"hybrid" that hugs the human line scores a good MSE (the observed R5 failure). The honest gate combines
four criteria, ALL required to pass:

  1. on_route          — lateral (horizontal) RMSE off the human polyline within a LOOSE containment
                         tolerance (still running the route / not lost into a wall). NOT a centerline
                         match: matching the human line would cap the bot at the human's path (docs/28).
  2. faster_than_human — median along-route speedup ratio (v_along / human v_ref here) >= 1.0, i.e. at
                         least human speed on the stretch. Uses reward_onspeed.route_speedup so the
                         gate's ratio is IDENTICAL to the one the reward optimizes.
  3. clean_mechanism   — the fraction of AIRBORNE ticks holding +forward (fwd_am==2) is capped: a clean
                         air-strafe bhop releases forward in the air (the 30-qu/s air cap makes forward
                         add ~0 speed there; QWD action oracle / #427 D6), a bulldoze-hybrid does not.
  4. completed_route   — net along-route ARC coverage ((arc_last − arc_first) / total_len) clears a
                         floor: the trajectory must materially TRAVERSE the route, not just sample fast
                         locally. Without it a one-tick probe at the route start (fast, on-line, clean)
                         false-certifies as PASS though it completes nothing (the Codex P1 gap).

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
    # (4) route-completion floor: min net along-route arc coverage the trajectory must traverse
    #     ((arc_last−arc_first)/total_len). A "materially traversed the route" floor that rejects a
    #     non-completing local speed sample — NOT a human-match target.
    "min_coverage_frac": 0.5,
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
        "route_coverage_frac": 0.0, "n_ticks": 0, "on_route": False, "faster_than_human": False,
        "clean_mechanism": False, "completed_route": False, "passed": False, "cfg": cfg,
    }


def grade_trajectory(traj, route, cfg=None):
    """Grade ONE closed-loop trajectory against its human-reference route (the D1/D2 honest gate).

    traj  : list of per-tick dicts, each with keys ox, oy, oz, vx, vy, onground (bool),
            fwd_am (int; 2 == +forward held). Extra keys are ignored.
    route : dict with polyline=[(x,y,z),...], speeds=[per-vertex human speed], total_len (optional).
    cfg   : threshold overrides (see DEFAULT_GRADE_CFG).

    Returns a grade dict: route_rmse_qu, speedup stats, mechanism fractions, route_coverage_frac, the
    four per-criterion booleans (on_route / faster_than_human / clean_mechanism / completed_route), and
    the overall `passed` (all four).
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
    arc_first = None
    arc_last = None
    for t in traj:
        ox, oy, oz = float(t["ox"]), float(t["oy"]), float(t["oz"])
        vx, vy = float(t.get("vx", 0.0)), float(t.get("vy", 0.0))
        proj2 = project_onto_polyline(ox, oy, 0.0, polyline_2d)
        if proj2 is not None:
            sum_dist_sq += proj2["distSq"]
        _v_along, _v_ref, ratio, arc_now = route_speedup(ox, oy, oz, vx, vy, polyline, speeds, total_len)
        if arc_now is not None:                 # net arc progress (first→last tick) = route coverage
            if arc_first is None:
                arc_first = arc_now
            arc_last = arc_now
        ratios.append(ratio)
        # Reporting-only stat: a FIXED ratio>1.0 count (fraction of ticks strictly above human speed),
        # independent of the tunable `min_ratio` gate — which tests the MEDIAN ratio below, not this.
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
    if total_len > 0 and arc_first is not None and arc_last is not None:
        route_coverage_frac = max(0.0, min(1.0, (arc_last - arc_first) / total_len))
    else:
        route_coverage_frac = 0.0

    on_route = rmse <= c["rmse_tol"]
    faster_than_human = median_ratio >= c["min_ratio"]
    clean_mechanism = air_fwd_frac <= c["max_air_forward_frac"]
    completed_route = route_coverage_frac >= c["min_coverage_frac"]

    return {
        "route_rmse_qu": round(rmse, 3),
        "median_speedup_ratio": round(median_ratio, 4),
        "mean_speedup_ratio": round(mean_ratio, 4),
        "faster_than_human_frac": round(fth_ticks / n, 4),
        "air_frac": round(air_ticks / n, 4),
        "air_forward_press_frac": round(air_fwd_frac, 4),
        "route_coverage_frac": round(route_coverage_frac, 4),
        "n_ticks": n,
        "on_route": on_route,
        "faster_than_human": faster_than_human,
        "clean_mechanism": clean_mechanism,
        "completed_route": completed_route,
        "passed": bool(on_route and faster_than_human and clean_mechanism and completed_route),
        "cfg": c,
    }


def prep_traj_for_grade(traj, route, *, min_vref=1.0):
    """Caller-side guards for the closed-loop route-grade (D1 wiring). Returns the sub-trajectory to
    hand to `grade_trajectory`:

      (iii) STOP at the route end (first tick whose projected arc reaches total_len) — else a genuinely
            FASTER-than-human bot reaches the human route-end early and overruns; `project_onto_polyline`
            clamps the overrun ticks to the final vertex, so their off-route distance = the overrun and
            the horizontal RMSE inflates -> `on_route` FALSE-FAILs exactly the superhuman behaviour docs/28
            is trying to certify (the #466-analog: a judge that penalises the target).
      (iv)  DROP ticks whose human reference speed is ~0 (segment ends / human pauses) — `route_speedup`
            returns ratio 0 when v_ref<=1e-6, and those 0-ratio ticks drag the speedup median -> false-FAIL
            `faster_than_human`.

    Pure stdlib; reuses `route_speedup` so arc + v_ref match the grade exactly. Falls back to the whole
    trajectory on a degenerate route (so grading still runs)."""
    polyline = route.get("polyline") or []
    speeds = route.get("speeds") or []
    total_len = route.get("total_len") or _polyline_len(polyline)
    if len(polyline) < 2 or total_len <= 0.0:
        return list(traj)
    out = []
    for t in traj:
        _v_along, v_ref, _ratio, arc = route_speedup(
            float(t["ox"]), float(t["oy"]), float(t.get("oz", 0.0)),
            float(t.get("vx", 0.0)), float(t.get("vy", 0.0)),
            polyline, speeds, total_len)
        if v_ref is not None and v_ref > min_vref:
            out.append(t)                       # (iv) keep only ticks with a usable human reference
        if arc is not None and arc >= total_len:
            break                               # (iii) stop at the route end — no overrun
    return out or list(traj)


def aggregate_route_grades(grades):
    """Aggregate per-segment grade dicts (from `grade_trajectory`) into one route-grade summary. Each
    boolean criterion becomes a pass-FRACTION across segments; the overall honest route-grade PASS =
    EVERY graded segment fully passed (`all_passed`). Pure stdlib -> gates in the aws-dev floor."""
    clean = [g for g in grades if g]
    n = len(clean)
    if n == 0:
        return {"n_segments": 0, "seg_on_route_frac": 0.0, "seg_faster_frac": 0.0,
                "seg_clean_mechanism_frac": 0.0, "seg_completed_frac": 0.0, "seg_passed_frac": 0.0,
                "all_passed": False, "median_speedup_ratio": 0.0, "median_route_rmse_qu": 0.0}

    def frac(key):
        return round(sum(1 for g in clean if g.get(key)) / n, 4)

    return {
        "n_segments": n,
        "seg_on_route_frac": frac("on_route"),
        "seg_faster_frac": frac("faster_than_human"),
        "seg_clean_mechanism_frac": frac("clean_mechanism"),
        "seg_completed_frac": frac("completed_route"),
        "seg_passed_frac": frac("passed"),
        "all_passed": all(g.get("passed") for g in clean),
        "median_speedup_ratio": _median([g["median_speedup_ratio"] for g in clean]),
        "median_route_rmse_qu": _median([g["route_rmse_qu"] for g in clean]),
    }
