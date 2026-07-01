"""route_grade.py — the honest OFFLINE route-completion grade for the Phase-2 RL policy (D1).

Grades ONE closed-loop trajectory (the PPO policy driving pmove_sim) against its human-reference
route. The docs/28 goal is information-honest SUPERHUMAN movement, validated route-first — so the
grade is NOT route-shape MSE alone: adherence-MSE is speed-blind, so a non-bhop forward+strafe
"hybrid" that hugs the human line scores a good MSE (the observed R5 failure). The honest gate combines
four criteria, ALL required to pass:

  1. on_route          — lateral (horizontal) RMSE off the human polyline within a LOOSE containment
                         tolerance (still running the route / not lost into a wall). NOT a centerline
                         match: matching the human line would cap the bot at the human's path (docs/28).
  2. faster_than_human — median along-route speedup ratio (v_along / human v_ref here). ABSOLUTE bar
                         (>= 1.0 = at least RAW-human speed) by default; when a sim-human control ratio
                         is supplied (#428) the bar is RELATIVE — beat the human RE-SIMULATED in the same
                         sim, which cancels the ~half-speed sim-fidelity factor that makes the absolute
                         bar unreachable in-sim. Uses reward_onspeed.route_speedup so the gate's ratio is
                         IDENTICAL to the one the reward optimizes.
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
    # (2b) degenerate-reference floor (#428): when grading RELATIVE to a human control (human_ref_ratio),
    #      a control ratio <= this means the sim-human itself made ~no along-route progress on this
    #      segment -> `bot >= ~0` would trivially auto-PASS exactly where the instrument is least
    #      trustworthy. Below this floor the segment is NOT certified faster (conservative), not passed.
    "min_ref_ratio": 0.05,
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
        "faster_basis": "absolute", "faster_than_sim_human": None, "human_ref_ratio": None,
        "superhuman_claim": False,
        "clean_mechanism": False, "completed_route": False, "passed": False, "cfg": cfg,
    }


def grade_trajectory(traj, route, cfg=None, human_ref_ratio=None, human_ref_valid=True):
    """Grade ONE closed-loop trajectory against its human-reference route (the D1/D2 honest gate).

    traj  : list of per-tick dicts, each with keys ox, oy, oz, vx, vy, onground (bool),
            fwd_am (int; 2 == +forward held). Extra keys are ignored.
    route : dict with polyline=[(x,y,z),...], speeds=[per-vertex human speed], total_len (optional).
    cfg   : threshold overrides (see DEFAULT_GRADE_CFG).
    human_ref_ratio : optional per-segment RELATIVE bar (#428). The offline pmove sim reproduces only
            ~half the real engine's along-route speed, so even the recorded human re-simulated scores
            well under the absolute 1.0 bar (measured vs the RAW recorded human) -> that bar is
            unreachable in-sim. Pass the recorded-human control's median ratio here to judge
            `faster_than_human` RELATIVELY (bot ratio >= sim-human ratio): the common sim-fidelity
            factor cancels. This is "faster than the SIM-human", NOT a superhuman CLAIM (which needs a
            live recording; docs/28). None -> the absolute `min_ratio` bar (back-compatible default).
    human_ref_valid : whether the sim-human control was itself a VALID route anchor on this segment
            (caller passes on_route AND completed_route of the control). False -> the reference is
            untrustworthy (off-route / incomplete control) and the relative bar is REFUSED, not applied
            (Codex #471 P1: an off-route control with a healthy ratio must not license a policy pass).

    Returns a grade dict: route_rmse_qu, speedup stats, mechanism fractions, route_coverage_frac, the
    four per-criterion booleans (on_route / faster_than_human / clean_mechanism / completed_route), the
    overall `passed` (all four), and #428 provenance (faster_basis / faster_than_sim_human /
    human_ref_ratio / superhuman_claim=False so a relative verdict cannot be misread as absolute).
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
            if int(t.get("fwd_am", 0) or 0) == _FWD_PRESS:   # None (recorded control) -> not pressed
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
    # faster_than_human: absolute (vs the RAW recorded human) UNLESS a sim-human control reference is
    # supplied (#428) -> then judge RELATIVE to the human re-simulated on this route, which cancels the
    # common sim-fidelity factor. TWO ways the reference is refused (not auto-passed): the control was not
    # a valid route anchor (off-route / incomplete -> ratio not trustworthy, Codex #471 P1), or it ~stalled
    # (ratio <= min_ref_ratio -> bot >= ~0 would trivially pass where the instrument is least trusted).
    if human_ref_ratio is None:
        faster_than_human = median_ratio >= c["min_ratio"]
        faster_basis = "absolute"
    elif not human_ref_valid:
        faster_than_human = False
        faster_basis = "relative_ref_invalid"
    elif human_ref_ratio <= c["min_ref_ratio"]:
        faster_than_human = False
        faster_basis = "relative_ref_degenerate"
    else:
        faster_than_human = median_ratio >= human_ref_ratio
        faster_basis = "relative"
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
        # #428 provenance: make the relative meaning machine-readable so a downstream selector (#429)
        # cannot silently promote "faster than the SIM-human" to an absolute "superhuman" claim.
        "faster_basis": faster_basis,
        "faster_than_sim_human": (None if human_ref_ratio is None else faster_than_human),
        "human_ref_ratio": (round(float(human_ref_ratio), 4) if human_ref_ratio is not None else None),
        "superhuman_claim": False,
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
    EVERY graded segment fully passed (`all_passed`). When graded RELATIVE to a sim-human control (#428)
    the summary also carries `n_ref_degenerate` + `n_ref_invalid` (segments whose sim-human reference
    was ~stalled / not a valid route anchor) and `median_human_ref_ratio` (the sim-fidelity ceiling).
    Pure stdlib -> gates in the aws-dev floor."""
    clean = [g for g in grades if g]
    n = len(clean)
    if n == 0:
        return {"n_segments": 0, "seg_on_route_frac": 0.0, "seg_faster_frac": 0.0,
                "seg_clean_mechanism_frac": 0.0, "seg_completed_frac": 0.0, "seg_passed_frac": 0.0,
                "all_passed": False, "median_speedup_ratio": 0.0, "median_route_rmse_qu": 0.0,
                "n_ref_degenerate": 0, "n_ref_invalid": 0, "median_human_ref_ratio": None,
                "superhuman_claim": False}

    def frac(key):
        return round(sum(1 for g in clean if g.get(key)) / n, 4)

    refs = [g["human_ref_ratio"] for g in clean if g.get("human_ref_ratio") is not None]
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
        # #428: segments the relative bar could NOT judge (sim-human ~stalled) are refused, not passed;
        # surface the count + the median sim-fidelity ceiling (the human control ratio) so a reader sees
        # how degraded the instrument is. superhuman_claim stays False — this is a relative ranking only.
        "n_ref_degenerate": sum(1 for g in clean if g.get("faster_basis") == "relative_ref_degenerate"),
        "n_ref_invalid": sum(1 for g in clean if g.get("faster_basis") == "relative_ref_invalid"),
        "median_human_ref_ratio": (_median(refs) if refs else None),
        "superhuman_claim": False,
    }
