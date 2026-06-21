"""ml/dagger/validate_expert.py -- the D-1 expert validation harness (3 checks).

EVAL-INTEGRITY: every number printed comes from a computation run here on real inputs
(the QWD catalog, the censused dm3 routes + pmove_sim, cs10's regenerated over-press
states). Nothing is hand-entered. Each check is an independent subcommand so a reader can
re-run any one and reproduce the number.

  check-a  human-agreement  -- on real HUMAN air frames (QWD dm3_4on4.sqlite, onground=0,
           |v_h|>min), does the optimal-strafe expert AGREE with the human's actual
           usercmd? side-key sign agreement, yaw-turn-sign agreement, median |yaw_rate|
           error (deg/tick) + its distribution, and the human fwd-press rate on these
           frames (= the band the expert's air fwd=0 must sit near). [needs sqlite catalog]

  check-b  expert-alone believability -- roll out the PURE expert (no policy) as the
           closed-loop controller in pmove_sim across the censused dm3 routes, score the
           G-MV battery (G-MV1 turn-vs-vel / G-MV3 cadence / G-MV4 speed band) + the
           dry-route route%/speed%. The load-bearing check: optimal-but-robotic -> blend
           rec. [needs pmove_sim + verify_route + the censused routes + dm3 anchors]

  check-c  fixes-over-press -- on cs10's CLOSED-LOOP over-press states (air, fwd>=~0.9),
           the fraction where the expert says fwd<=human-band AND side!=0 (target >=90%).
           [needs a state dump; regenerate via the cs10 rollout if not persisted]

The expert is ml/dagger/expert.expert_action (pure). check-b/check-c reuse the SAME
pmove_sim + gmv battery + verify_route the production eval uses (ml/eval_broad_*).
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import sqlite3
import statistics
import sys
from pathlib import Path

_ML = Path(__file__).resolve().parent.parent
_REPO = _ML.parent
for _p in (str(_ML), str(_ML / "dagger"), str(_REPO / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import eval_broad_closedloop as CL   # noqa: E402  (seam + gmv glue; torch-free import)
from dagger import expert as EX      # noqa: E402  (the expert under validation)

LOGGER = logging.getLogger(__name__)

BTN_JUMP = 2
# "moving" floor for air-frame agreement = the gmv G-MV1 floor (below this the velocity
# angle is noise). We also report a looser floor for transparency.
MIN_HSPEED = 150.0
MOVE_MAG = EX.MOVE_MAG


# =============================================================================
# CHECK (a) -- human-agreement on real HUMAN air frames (QWD catalog)
#
# THE KEY GEOMETRY (why the comparison is wishdir-based, not yaw-based): with side-only
# keys the air-strafe WISHDIR is the view yaw's RIGHT vector -- i.e. 90 deg off the view
# yaw. The expert's claim is "wishdir _|_ velocity" (the per-tick speed-optimal). So the
# human comparison must reconstruct the HUMAN's actual wishdir from their real
# (yaw, fwd, side) via the SAME _air_move math the sim uses, then compare WISHDIR geometry
# -- comparing raw view yaws would be wrong (a human aiming ~along velocity is air-strafing
# correctly because their side key rotates the wishdir 90 deg off that aim).
# =============================================================================
def _wrap180(d: float) -> float:
    d = (float(d) + 180.0) % 360.0 - 180.0
    return 180.0 if d == -180.0 else d


def _wishdir_xy(yaw, fwd, side):
    """The horizontal wishdir (unit, [wx,wy]) pmove_sim._air_move builds from a view yaw +
    move keys. Mirrors ml/tests/test_optimal_aim._wishdir (and the engine) exactly. yaw in
    DEGREES; fwd/side are usercmd magnitudes. Returns None when no move key is pressed."""
    import pmove_sim as PM
    f, r = PM.angle_vectors((0.0, float(yaw), 0.0))
    f = [f[0], f[1]]
    r = [r[0], r[1]]
    nf = math.hypot(f[0], f[1]) or 1.0
    nr = math.hypot(r[0], r[1]) or 1.0
    f = [f[0] / nf, f[1] / nf]
    r = [r[0] / nr, r[1] / nr]
    wx = f[0] * fwd + r[0] * side
    wy = f[1] * fwd + r[1] * side
    w = math.hypot(wx, wy)
    if w == 0:
        return None
    return [wx / w, wy / w]


def check_a(catalog: str, *, min_hspeed: float = MIN_HSPEED, limit: int | None = None) -> dict:
    """Compare the EXPERT vs the HUMAN usercmd on real air frames, at the WISHDIR level.

    For each air frame (onground=0, |v_h|>=min_hspeed) with a ground-truth human usercmd
    (player_ticks JOIN actions on episode_id,tick):
      * human_wishdir = _wishdir_xy(human_yaw, human_fwd, human_side)  -- their ACTUAL
        air-accel intent direction (None if no move key -> excluded from wishdir metrics).
      * The expert's optimal wishdir is PERPENDICULAR to velocity. cross(v, wishdir) sign =
        which rotational side of velocity the wishdir leans (the strafe turn side).
      * expert lean side = the side that gives a POSITIVE speed gain toward where the human
        is going. With no per-frame route goal in the catalog, the natural reference is the
        human's own velocity: any perpendicular wishdir gives the SAME (maximal) speed gain,
        so "agreement" is measured as the human's wishdir being (1) in the strafe regime
        (|angle(wishdir, v)| near 90, not ~0/180 = aligned bulldoze) and (2) leaning the
        SAME side the human's pressed SIDE KEY implies the expert would pick.

    Reported (every number from this computation):
      1. side_sign_agreement_pct: among air frames where the human presses a side key, the
         fraction where the SIGN of cross(v, human_wishdir) == sign of cross(v, expert
         wishdir for the human's side-key sign). I.e. is the human leaning the speed-optimal
         side consistent with their own side key (not strafing the WRONG way)?
      2. wishdir_strafe_regime_pct (= "yaw-turn-sign agreement" at the wishdir level): the
         fraction of side-press air frames whose human wishdir is within +-band of the
         perpendicular (|angle(wishdir,v)| in [90-band, 90+band]) -- the human IS air-
         strafing (turn side matches the expert's perpendicular), not running aligned.
      3. median |wishdir-vs-optimal| error (deg) + distribution: the angle between the
         human's wishdir and the EXPERT's optimal wishdir (the perpendicular nearest the
         human's wishdir) -- how far the human's per-tick aim is from speed-optimal.
      + human_fwd_press_rate: fraction of these air frames with forwardmove>0 (= the band
        the expert's air fwd=0 must sit near; elite humans air-strafe with LOW fwd press).
      + human_wishdir_vs_vel_median_deg: median |angle(human_wishdir, velocity)| (the human
        air-strafe separation; the anchors put elite ~36 deg -> here near 90 at wishdir lvl).
    """
    con = sqlite3.connect(catalog)
    cur = con.cursor()
    q = """
        SELECT p.vx, p.vy, p.yaw, p.hspeed, a.forwardmove, a.sidemove
        FROM player_ticks p JOIN actions a
          ON p.episode_id=a.episode_id AND p.tick=a.tick
        WHERE p.onground=0 AND p.hspeed>=?
    """
    if limit:
        q += " LIMIT %d" % int(limit)
    rows = cur.execute(q, (float(min_hspeed),)).fetchall()
    con.close()

    PERP_BAND = 30.0   # within +-30 deg of perpendicular counts as "air-strafe regime"
    n = 0
    n_side_press = 0
    side_agree = 0
    in_strafe_regime = 0
    wishdir_err = []          # |human_wishdir - D-1.5 expert_wishdir| deg
    human_sep = []            # |angle(human_wishdir, velocity)| deg
    expert_sep = []           # |angle(D-1.5 expert_wishdir, velocity)| deg ("(a) improves")
    fwd_press = 0
    for vx, vy, yaw, hspeed, fwd, side in rows:
        if vx is None or vy is None or yaw is None:
            continue
        sp = math.hypot(vx, vy)
        if sp < min_hspeed:
            continue
        n += 1
        fwd = float(fwd or 0.0)
        side = float(side or 0.0)
        if fwd > 0:
            fwd_press += 1

        hw = _wishdir_xy(yaw, fwd, side)
        if hw is None:
            continue   # no move key -> wishdir undefined, excluded from wishdir metrics
        vxn, vyn = vx / sp, vy / sp
        # signed angle of the human wishdir relative to velocity (deg)
        dot = hw[0] * vxn + hw[1] * vyn
        cross = vxn * hw[1] - vyn * hw[0]          # sign = rotational lean side
        sep = abs(math.degrees(math.atan2(cross, dot)))   # |angle(wishdir, v)|
        human_sep.append(sep)
        if abs(sep - 90.0) <= PERP_BAND:
            in_strafe_regime_frame = True
        else:
            in_strafe_regime_frame = False

        # the D-1.5 EXPERT's wishdir for the human's pressed side-key sign. The expert leans
        # its perpendicular reference toward the GOAL heading; on a route the goal ~ where the
        # player is travelling, so the natural per-frame goal proxy here is the human's own
        # VELOCITY heading (observed, NOT their aim choice -> non-circular). This yields the
        # expert's diagonal wishdir; we compare its lean side + its angle to the human's.
        if side != 0:
            n_side_press += 1
            if in_strafe_regime_frame:
                in_strafe_regime += 1
            side_sign_h = 1 if side > 0 else -1
            vel_yaw = math.degrees(math.atan2(vy, vx))   # goal proxy = direction of travel
            exp_st = {"vx": vx, "vy": vy, "onground": False, "goal_dir_yaw": vel_yaw}
            efwd, eside, _, _, exp_yaw = EX.expert_action(exp_st, side_sign=side_sign_h)
            ew = _wishdir_xy(exp_yaw, efwd, eside)
            if ew is not None:
                exp_cross = vxn * ew[1] - vyn * ew[0]
                if (exp_cross > 0) == (cross > 0):
                    side_agree += 1
                # wishdir error = angle between human wishdir and the D-1.5 expert's wishdir
                edot = hw[0] * ew[0] + hw[1] * ew[1]
                wishdir_err.append(abs(math.degrees(math.acos(max(-1.0, min(1.0, edot))))))
                # the expert's own wishdir-vs-velocity separation (should now sit at the
                # human diagonal ~59 deg, NOT 90 -- the D-1.5 "(a) improves" signal)
                edot_v = ew[0] * vxn + ew[1] * vyn
                ecross_v = vxn * ew[1] - vyn * ew[0]
                expert_sep.append(abs(math.degrees(math.atan2(ecross_v, edot_v))))

    def pct(a, b):
        return round(100.0 * a / b, 2) if b else None

    res = {
        "check": "a_human_agreement",
        "catalog": catalog,
        "min_hspeed_qu_per_s": min_hspeed,
        "n_air_frames": n,
        "n_side_press_frames": n_side_press,
        "side_sign_agreement_pct": pct(side_agree, n_side_press),
        "wishdir_strafe_regime_pct": pct(in_strafe_regime, n_side_press),
        "median_abs_wishdir_err_deg": round(statistics.median(wishdir_err), 3) if wishdir_err else None,
        "wishdir_err_p25_deg": round(_pctl(wishdir_err, 0.25), 3) if wishdir_err else None,
        "wishdir_err_p75_deg": round(_pctl(wishdir_err, 0.75), 3) if wishdir_err else None,
        "wishdir_err_p90_deg": round(_pctl(wishdir_err, 0.90), 3) if wishdir_err else None,
        "human_fwd_press_rate": round(fwd_press / n, 4) if n else None,
        "human_wishdir_vs_vel_median_deg": round(statistics.median(human_sep), 3) if human_sep else None,
        "expert_wishdir_vs_vel_median_deg": round(statistics.median(expert_sep), 3) if expert_sep else None,
        "perp_band_deg": PERP_BAND,
        "targets": {"side_sign_agreement_pct": 75.0, "wishdir_strafe_regime_pct": 75.0},
        "note": ("wishdir-level comparison: side-only keys put wishdir 90deg off the view "
                 "yaw, so raw-yaw agreement would be wrong; see module header geometry."),
    }
    return res


def _pctl(vals, q):
    if not vals:
        return 0.0
    s = sorted(vals)
    if len(s) == 1:
        return float(s[0])
    pos = q * (len(s) - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(s) - 1)
    frac = pos - lo
    return float(s[lo]) * (1 - frac) + float(s[hi]) * frac


# =============================================================================
# CHECK (b) -- pure-expert closed-loop believability across the censused routes
# =============================================================================
def _expert_rollout_route(route, world, *, seed_from_human=True, max_ticks=6000):
    """Drive pmove_sim down a censused route with the PURE EXPERT as the controller.

    Mirrors eval_broad_dryroute.run_policy_rollout's loop (sim state fed back each tick),
    but the action each tick is expert_action(visited_state) -- NOT a trained policy. The
    route goal is the COMPASS fallback so the optimal-yaw branch bends toward the goal. The
    scorer rows + gmv ticks are built with the SAME helpers the production eval uses
    (DR.make_row / CL.gmv_tick_from_state) so route%/speed%/G-MV are scored identically.
    Returns (gmv_ticks, scorer_rows).
    """
    import pmove_sim as PM
    import eval_broad_dryroute as DR

    frames = PM.load_cmds_file(str(route["human"]))
    goal = route["goal"]
    floor_z = DR.route_void_floor_z(route)
    pm = PM.Pmove(world)
    f0 = frames[0]
    if seed_from_human:
        st = PM.PlayerState(list(f0["origin"]), list(f0["velocity"]))
    else:
        st = PM.PlayerState(list(f0["origin"]), [0.0, 0.0, 0.0])

    gmv_ticks, rows = [], []
    t = 0.0
    n = min(len(frames) - 1, max_ticks)
    for k in range(n):
        msec = int(frames[k]["msec"])
        gx, gy = float(goal[0]), float(goal[1])
        gdir = math.degrees(math.atan2(gy - st.origin[1], gx - st.origin[0]))
        state = {"vx": st.velocity[0], "vy": st.velocity[1],
                 "onground": bool(st.onground), "goal_dir_yaw": gdir}
        # tick=k drives the L/R weave (the D-1.5 orbit-killer); the expert leans the aim
        # toward gdir by its default forward_blend (the diagonal cap).
        fwd, side, up, jump, view_yaw = EX.expert_action(state, tick=k)
        cmd = PM.Cmd(msec, [0.0, view_yaw, 0.0], [fwd, side, up], int(jump))
        pm.run_frame(st, cmd)
        t += msec / 1000.0
        # gmv tick: sidemove = the expert's strafe intent so G-MV3 cadence sees the bot's
        # OWN side key (the +-MAX L/R weave -> a real flip cadence, not a constant side).
        gmv_ticks.append(CL.gmv_tick_from_state(st.origin, st.velocity, st.onground,
                                                view_yaw, side, msec=msec))
        ov = DR.over_void_at(world, st.origin, floor_z)
        rows.append(DR.make_row(t, st.origin, st.velocity, st.onground, ov, goal))
    return gmv_ticks, rows


def check_b(route_names, *, bsp_path: str, anchors_path: str,
            seed_from_human=True) -> dict:
    """Roll out the pure expert across routes; score G-MV + route%/speed% per route + pooled.

    route%/speed% are delegated to the SAME gated scorer the production dry-route gate uses
    (eval_broad_dryroute.score_rows on the route loaded via load_route_with_human), so the
    numbers are directly comparable to the policy's dry-route gate. G-MV is the pooled
    battery over every route's ticks (CL.score_sequence_gmv -> CL.summarize_gmv)."""
    import pmove_sim as PM
    import eval_broad_dryroute as DR

    anchors = json.loads(Path(anchors_path).read_text())
    world = PM.WorldModel.load(str(Path(bsp_path).expanduser()))

    per_route = {}
    pooled_ticks = []
    for name in route_names:
        try:
            route, _hframes, _hrows, human_tws, _agree = DR.load_route_with_human(name, world)
        except SystemExit as e:
            per_route[name] = {"error": str(e)}
            continue
        gmv_ticks, rows = _expert_rollout_route(route, world, seed_from_human=seed_from_human)
        pooled_ticks.extend(gmv_ticks)
        gmv = CL.score_sequence_gmv(gmv_ticks, anchors=anchors)
        try:
            scored = DR.score_rows(rows, route, human_tws)
            route_pct = scored.get("route_pct")
            speed_pct = scored.get("speed_pct")
            passed = scored.get("passed")
        except Exception as e:
            route_pct = speed_pct = passed = None
            LOGGER.warning("score_rows failed on %s: %s", name, e)
        per_route[name] = {
            "n_ticks": len(gmv_ticks),
            "route_pct": route_pct,
            "speed_pct": speed_pct,
            "dry_route_passed": passed,
            "gmv": CL.summarize_gmv(gmv),
        }
    pooled = CL.score_sequence_gmv(pooled_ticks, anchors=anchors)
    return {
        "check": "b_expert_alone_believability",
        "seed_from_human": seed_from_human,
        "n_routes": len(route_names),
        "pooled_gmv": CL.summarize_gmv(pooled),
        "pooled_n_ticks": len(pooled_ticks),
        "per_route": per_route,
    }


# =============================================================================
# CHECK (c) -- the expert fixes cs10's over-press states
# =============================================================================
def check_c(states_path: str, *, strafe_sep_deg: float = 30.0) -> dict:
    """On cs10's closed-loop over-press states (air, fwd>=~0.9), the fraction where the
    expert's action is a real STRAFE rather than a bulldoze. States = a JSONL/JSON list of
    {vx,vy,onground,...}.

    CONTRACT (D-1.5): the over-press FAILURE is the bulldoze -- a wishdir ~ALIGNED with
    velocity (separation ~0) so air-accel gains ~0 speed. The FIX is a wishdir in the strafe
    REGIME (separated from velocity by >= strafe_sep_deg) AND a pressed side key. This is
    contract-faithful for BOTH the D-1 strict-perp expert (sep ~90) and the D-1.5 diagonal
    expert (sep ~59 with fwd>0): the over-press fix is "not aligned with velocity", NOT
    "fwd==0" (the D-1.5 expert deliberately presses a forward component). The separation is
    computed from the expert's realized wishdir via the SAME _wishdir_xy the engine uses."""
    p = Path(states_path)
    raw = p.read_text().strip()
    if raw.startswith("["):
        states = json.loads(raw)
    else:
        states = [json.loads(ln) for ln in raw.splitlines() if ln.strip()]

    n = 0
    fixed = 0
    air_overpress = 0
    for i, s in enumerate(states):
        n += 1
        st = {"vx": s["vx"], "vy": s["vy"], "onground": bool(s.get("onground", False)),
              "goal_dir_yaw": s.get("goal_dir_yaw", 0.0)}
        fwd, side, up, jump, yaw = EX.expert_action(st, tick=i)
        if not st["onground"]:
            air_overpress += 1
            sp = math.hypot(st["vx"], st["vy"])
            wd = _wishdir_xy(yaw, fwd, side)
            if wd is None or sp < 1.0:
                continue
            vxn, vyn = st["vx"] / sp, st["vy"] / sp
            dot = wd[0] * vxn + wd[1] * vyn
            cross = vxn * wd[1] - vyn * wd[0]
            sep = abs(math.degrees(math.atan2(cross, dot)))  # |angle(wishdir, v)|
            # a real strafe (off-aligned) with a pressed side key = the over-press fix
            if sep >= float(strafe_sep_deg) and side != 0:
                fixed += 1
    return {
        "check": "c_fixes_over_press",
        "states_path": states_path,
        "n_states": n,
        "n_air_states": air_overpress,
        "strafe_sep_deg": strafe_sep_deg,
        "overpress_fix_fraction": round(fixed / air_overpress, 4) if air_overpress else None,
        "target": 0.90,
    }


# =============================================================================
def main(argv=None):
    ap = argparse.ArgumentParser(description="DAgger D-1 expert validation (3 checks).")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("check-a", help="human-agreement on QWD air frames")
    a.add_argument("--catalog", required=True)
    a.add_argument("--min-hspeed", type=float, default=MIN_HSPEED)
    a.add_argument("--limit", type=int, default=None)

    b = sub.add_parser("check-b", help="expert-alone closed-loop believability")
    b.add_argument("--routes", nargs="+", required=True)
    b.add_argument("--bsp", required=True)
    b.add_argument("--anchors", required=True)
    b.add_argument("--unseeded", action="store_true", help="start from rest (test the ground-fwd launch)")

    c = sub.add_parser("check-c", help="fixes cs10 over-press states")
    c.add_argument("--states", required=True)
    c.add_argument("--strafe-sep-deg", type=float, default=30.0)

    args = ap.parse_args(argv)
    if args.cmd == "check-a":
        out = check_a(args.catalog, min_hspeed=args.min_hspeed, limit=args.limit)
    elif args.cmd == "check-b":
        out = check_b(args.routes, bsp_path=args.bsp, anchors_path=args.anchors,
                      seed_from_human=not args.unseeded)
    elif args.cmd == "check-c":
        out = check_c(args.states, strafe_sep_deg=args.strafe_sep_deg)
    print(json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
