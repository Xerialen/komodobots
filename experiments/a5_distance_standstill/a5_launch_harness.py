#!/usr/bin/env python3
"""A5 #118 step 4: standstill -> circle-build -> jump -> far platform, in sim.

Point-goal harness over the VALIDATED stack: pmove_sim physics on the real
ztricks.bsp + the DEPLOYED mode-23 control law (mode23_sim.mode23_step is
imported and run verbatim — carrot disabled, nav supplied as a fixed POINT,
exactly the audit-law mode). The circle-jump launch is the deployed A2b/A3
block (cvars k_fb_moveprobe_s23_launch_vh/_launch_angle semantics).

One attempt = the live retry loop's unit: snap to the human's per-attempt
start (the teleport deposit `(-3516.125, 3712, -453.125)`, yaw 0, zero
velocity — the bot falls ~35 qu to the platform like the human), run the
law with nav_dir = unit(target - origin), until:

  LANDED   the locked far-platform detector: grounded, |z+488| < 0.5,
           x > -3100 (y sanity band [3600, 3824]);
  MISS     the map's catcher teleporter under the gap fires (arrival back
           at the deposit) — the attempt boundary, exactly like live;
  TIMEOUT  budget exhausted (counts as a miss).

A5 control variant (sim-first per the ticket; OFF by default = deployed
semantics): `lip_gate_dmax > 0` additionally requires the release to happen
within [0, dmax] qu of the lip line (x = -3348) — otherwise the circle
keeps turning and tries again next lap. Geometry forces something like it:
a flat +270 jump at 475 qu/s carries ~320 qu and the gap's far floor starts
~300 qu past the lip, so releases more than ~35 qu early land in the gap no
matter how good the aim. Suggested KTX cvars for the live phase:
k_fb_moveprobe_s23_launch_target "x y z" (release toward a point, also the
nav substitute on .bot-less maps) and _s23_launch_lipgate (the window).

Round-2 variant (ledger section 7.1/9; OFF by default = deployed semantics):
the TERMINAL CARVE — the human's actual move. While the launch is armed:
ARM (latched) when grounded AND d_lip <= carve.d AND vh >= carve.vh; while
armed hold the wishdir carve.deg toward the target side of the velocity
(jump suppressed — a carve IS a swept wishdir, it keeps ground-building);
RELEASE (jump, aimed at the target) when |herr_to_target| <= carve.tol OR
d_lip <= 8. The carve REPLACES the deployed speed+aim release (deferred
exactly like the lip gate above); the deployed 3 s LAUNCH_TIMEOUT safeguard
is kept verbatim. Mutually exclusive with lip_gate_dmax. Live shape:
k_fb_moveprobe_s23_launch_target + _s23_launch_carve.

CLI:
  python a5_launch_harness.py probe --launch-vh 455 --launch-angle 50 \
      [--swing 12] [--sign -1] [--lip-gate 0] [--carve-d 0 --carve-deg 52 \
      --carve-vh 430 --carve-tol 6] [--seeds 1..5] [--dump]
  python a5_launch_harness.py sweep --out sweep-results.json [--workers 8]
  python a5_launch_harness.py carve-sweep [--out carve-sweep-results.json]
  python a5_launch_harness.py baseline-check   # refactor-safety vs round 1
  python a5_launch_harness.py carve-selfcheck  # synthetic carve geometry
"""
from __future__ import annotations

import argparse
import gzip
import itertools
import json
import math
import random
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import NamedTuple

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from pmove_sim import Cmd, PlayerState, Pmove, WorldModel  # noqa: E402
import mode23_sim as m23  # noqa: E402

BSP = r"C:\nQuake\qw\maps\ztricks.bsp"

# the human's per-attempt start (start-point.json; binding per #118)
DEPOSIT = (-3516.125, 3712.0, -453.125)
DEPOSIT_YAW = 0.0

# geometry (scratch probe, committed numbers in the report)
TARGET = (-3044.0, 3760.0, -488.0)     # census landing point (winner's)
LIP_X = -3348.0                        # run-up platform east edge (hull center)
PLATFORM_Z = -488.0
LAND_X = -3100.0                       # locked detector band
Y_BAND = (3600.0, 3824.0)
RUNUP_X_MIN = -3540.0

ATTEMPT_BUDGET_S = 25.0


def run_launch_attempt(world, teles, seed, params: m23.LawParams,
                       sign_override=0, lip_gate_dmax=0.0, carve=None,
                       target=TARGET, budget_s=ATTEMPT_BUDGET_S):
    """One standstill attempt. Returns a summary dict (+ rows)."""
    if carve is not None and lip_gate_dmax > 0.0:
        raise ValueError("carve and lip_gate_dmax are mutually exclusive "
                         "(the carve supersedes the gate)")
    rng = random.Random(seed)
    law = m23.LawState()
    nav = m23.NavState()
    brain = SimpleNamespace(g=SimpleNamespace(world=world))
    pm = Pmove(world)
    st = PlayerState(list(DEPOSIT), [0.0, 0.0, 0.0])

    t = 0.0
    rows = []
    last_yaw = DEPOSIT_YAW
    outcome = "TIMEOUT"
    release = None
    carve_armed = False
    carve_rec = None

    while t < budget_s:
        msec = rng.choices(m23.MSEC_CHOICES, weights=m23.MSEC_WEIGHTS)[0]

        d = [target[0] - st.origin[0], target[1] - st.origin[1], 0.0]
        dn, dl = m23.norm2d(d)
        nav.dir_move = dn if dl > 0 else [1.0, 0.0, 0.0]

        # pin the circle direction (the air weave during the deposit fall
        # flip-flops strafe_sign; the live cvar analog pins it per protocol)
        if (sign_override and params.launch_vh > 0.0 and not law.launch_done):
            law.strafe_sign = sign_override

        # A5 lip-gate: while the launch is armed and about to release on
        # speed+aim, require the lip window too — implemented OUTSIDE the
        # law by raising the effective herr (deferring release) when far
        # from the lip. Cleanest faithful form: temporarily disarm by
        # checking the deployed release condition ourselves.
        out = None
        if (carve is not None and params.launch_vh > 0.0
                and not law.launch_done and law.launch_since is not None):
            out, carve_armed, carve_rec = _carve_step(
                carve, params, law, st, nav.dir_move, t,
                carve_armed, carve_rec)
        elif (lip_gate_dmax > 0.0 and params.launch_vh > 0.0
                and not law.launch_done and law.launch_since is not None
                and st.onground):
            hs = math.hypot(st.velocity[0], st.velocity[1])
            cur, _ = m23.norm2d([st.velocity[0], st.velocity[1], 0.0])
            herr = abs(_wrap(m23.vectoyaw(nav.dir_move) - m23.vectoyaw(cur)))
            d_lip = LIP_X - st.origin[0]
            if (hs >= params.launch_vh and herr <= params.swing
                    and not (0.0 <= d_lip <= lip_gate_dmax)
                    and t - law.launch_since < m23.LAUNCH_TIMEOUT):
                # hold the circle this tick instead of releasing
                if law.strafe_sign == 0:
                    law.strafe_sign = 1
                circ = m23.rotate2d(cur, params.launch_angle * law.strafe_sign)
                law.jump_press = False
                out = (m23.vectoyaw(circ), (m23.SV_MAXSPEED, 0, 0), False)

        if out is None:
            out = m23.mode23_step(law, nav, brain, st, t, config="c5",
                                  carrot_enabled=False, params=params)

        if out is not None:
            yaw, move, jump = out
        else:  # vanilla fall-through (water / no dir) — walk at the target
            yaw, move, jump = last_yaw, (800, 0, 0), False
        last_yaw = yaw

        # release detection (one-shot latch transition)
        if release is None and law.launch_done and law.launch_since is not None:
            hs = math.hypot(st.velocity[0], st.velocity[1])
            vy = m23.vectoyaw([st.velocity[0], st.velocity[1], 0.0])
            release = {
                "t": round(t, 3),
                "pos": [round(c, 1) for c in st.origin],
                "vh": round(hs, 1),
                "heading": round(_wrap(vy), 1),
                "herr_to_target": round(_wrap(
                    m23.vectoyaw(nav.dir_move) - vy), 1),
                "d_lip": round(LIP_X - st.origin[0], 1),
                "timeout": t - law.launch_since >= m23.LAUNCH_TIMEOUT - 0.05,
            }
            # carve enabled + release arrived with no carve rule = the
            # deployed 3 s force-release fired (carve stood aside)
            if (carve is not None and carve_rec is not None
                    and carve_rec["rule"] is None and release["timeout"]):
                carve_rec["rule"] = "timeout"

        vh = math.hypot(st.velocity[0], st.velocity[1])
        rows.append({"t": round(t, 3), "x": st.origin[0], "y": st.origin[1],
                     "z": st.origin[2], "vh": vh, "vz": st.velocity[2],
                     "onground": int(st.onground), "yaw": yaw,
                     "jump": int(jump)})

        cmd = Cmd(msec, (0.0, yaw, 0.0), move, 2 if jump else 0)
        pm.run_frame(st, cmd)
        t += msec * 0.001

        # catcher teleporter = MISS (attempt boundary, like live)
        teleported = False
        for tp in teles:
            if (st.origin[0] + m23.PLAYER_MINS[0] - 1 <= tp.absmax[0]
                    and st.origin[0] + m23.PLAYER_MAXS[0] + 1 >= tp.absmin[0]
                    and st.origin[1] + m23.PLAYER_MINS[1] - 1 <= tp.absmax[1]
                    and st.origin[1] + m23.PLAYER_MAXS[1] + 1 >= tp.absmin[1]
                    and st.origin[2] + m23.PLAYER_MINS[2] - 1 <= tp.absmax[2]
                    and st.origin[2] + m23.PLAYER_MAXS[2] + 1 >= tp.absmin[2]):
                teleported = True
                break
        if teleported:
            outcome = "MISS"
            break

        # locked landing detector
        if (st.onground and abs(st.origin[2] - PLATFORM_Z) < 0.5
                and st.origin[0] > LAND_X
                and Y_BAND[0] <= st.origin[1] <= Y_BAND[1]):
            outcome = "LANDED"
            break

    # lip-crossing extraction: last grounded row on the run-up platform
    lip = None
    for i in range(len(rows) - 1):
        r, nx = rows[i], rows[i + 1]
        if (r["onground"] and abs(r["z"] - PLATFORM_Z) < 0.5
                and RUNUP_X_MIN < r["x"] <= LIP_X + 8 and not nx["onground"]):
            lip = i
    lip_state = None
    if lip is not None and lip + 1 < len(rows):
        r, nx = rows[lip], rows[lip + 1]
        heading = math.degrees(math.atan2(nx["y"] - r["y"], nx["x"] - r["x"]))
        # "jump" = the cmd bit actually issued at the last grounded row —
        # the ground-truth jumped/walk-off signal for the arc classifier
        # (Codex PR #120 round 2: release timestamps are one tick late and
        # cannot separate an on-lip release from a post-lip mid-air timeout)
        lip_state = {"t": r["t"], "x": round(r["x"], 1), "y": round(r["y"], 1),
                     "vh": round(r["vh"], 1), "heading": round(heading, 1),
                     "jump": int(r["jump"])}

    summary = {
        "seed": seed, "outcome": outcome, "t_end": round(t, 2),
        "landed": outcome == "LANDED",
        "release": release, "lip": lip_state,
        "max_vh": round(max(r["vh"] for r in rows), 1),
    }
    if carve is not None:
        # additive key, present only in carve runs (None = never armed) —
        # round-1 records and the decomposition's schema stay byte-identical
        summary["carve"] = carve_rec
    return summary, rows


def _wrap(a):
    while a > 180.0:
        a -= 360.0
    while a < -180.0:
        a += 360.0
    return a


class CarveCfg(NamedTuple):
    """Terminal-carve knobs (ledger section 7.1 variant; section 9 pre-reg)."""
    d: float    # arm window: d_lip <= d (qu from the lip line x = -3348)
    deg: float  # wishdir angle off the velocity, toward the target side
    vh: float   # arm speed floor (qu/s)
    tol: float  # release when |herr_to_target| <= tol (deg)


CARVE_DLIP_RELEASE = 8.0   # hard release backstop at the lip (ledger 7.1)


def _carve_step(carve, params, law, st, nav_dir, t, armed, rec):
    """One terminal-carve evaluation for a launch tick.

    Free of world/RNG access (reads st/law scalars, mutates law latches
    only) so the selfcheck can drive it with fabricated states. Returns
    (out_or_None, armed, rec); out=None means fall through to mode23_step
    (air tick, timeout window elapsed, or natural below-speed circle).
    """
    if t - law.launch_since >= m23.LAUNCH_TIMEOUT:
        return None, armed, rec      # deployed 3 s force-release owns it
    if not st.onground:
        return None, armed, rec      # air ticks: deployed weave as-is
    hs = math.hypot(st.velocity[0], st.velocity[1])
    cur, _ = m23.norm2d([st.velocity[0], st.velocity[1], 0.0])
    herr_s = _wrap(m23.vectoyaw(nav_dir) - m23.vectoyaw(cur))
    d_lip = LIP_X - st.origin[0]
    if not armed:
        if d_lip <= carve.d and hs >= carve.vh:
            # LATCH: a terminal carve never disarms — a speed dip mid-bend
            # is part of the maneuver, not a reason to resume orbiting.
            # No lower d_lip bound: a grounded lip-edge tick arms and
            # releases via the d_lip backstop below, converting a round-1
            # walk-off into a last-instant jump.
            armed = True
            rec = {"armed_t": round(t, 3), "armed_d_lip": round(d_lip, 1),
                   "armed_vh": round(hs, 1), "armed_herr": round(herr_s, 1),
                   "rule": None, "ticks": 0}
        elif hs >= params.launch_vh and abs(herr_s) <= params.swing:
            # the carve REPLACES the deployed speed+aim release: defer it
            # with a circle-hold tick (verbatim the lip-gate pattern)
            if law.strafe_sign == 0:
                law.strafe_sign = 1
            circ = m23.rotate2d(cur, params.launch_angle * law.strafe_sign)
            law.jump_press = False
            return ((m23.vectoyaw(circ), (m23.SV_MAXSPEED, 0, 0), False),
                    armed, rec)
        else:
            return None, armed, rec  # below-speed circle: deployed law
    if abs(herr_s) <= carve.tol or d_lip <= CARVE_DLIP_RELEASE:
        # release: the harness emits the jump itself — the deployed jump
        # gate (herr > turn_thresh suppression, mode23_sim) would turn a
        # poor-aim d_lip release into the round-1 silent walk-off
        law.launch_done = True
        law.jump_press = True
        rec["rule"] = "herr" if abs(herr_s) <= carve.tol else "dlip"
        return ((m23.vectoyaw(nav_dir), (m23.SV_MAXSPEED, 0, 0), True),
                armed, rec)
    # hold the carve: wishdir carve.deg toward the target side of the
    # velocity, recomputed per tick (an overshoot past the target heading
    # flips the side and bends back — discretization self-corrects)
    side = 1 if herr_s >= 0 else -1
    wish = m23.rotate2d(cur, carve.deg * side)
    law.jump_press = False
    rec["ticks"] += 1
    return ((m23.vectoyaw(wish), (m23.SV_MAXSPEED, 0, 0), False),
            armed, rec)


def make_params(launch_vh, launch_angle, swing):
    # the A2b patternized launch family constants; only the swept knobs vary
    return m23.LawParams(pass_r=100.0, numerator=5.0, swing=float(swing),
                         turn_thresh=35.0, corner_thresh=45.0, corner_aim=85.0,
                         launch_vh=float(launch_vh),
                         launch_angle=float(launch_angle))


def run_config(args):
    (vh, ang, swing, sign, gate, seeds) = args
    world = WorldModel.load(BSP)
    teles = m23.load_teleporters(BSP)
    res = []
    for s in seeds:
        p = make_params(vh, ang, swing)
        summ, _ = run_launch_attempt(world, teles, s, p, sign_override=sign,
                                     lip_gate_dmax=gate)
        res.append(summ)
    landed = sum(r["landed"] for r in res)
    lips = [r["lip"]["vh"] for r in res if r["lip"]]
    heads = [r["lip"]["heading"] for r in res if r["lip"]]
    return {
        "config": {"launch_vh": vh, "launch_angle": ang, "swing": swing,
                   "sign": sign, "lip_gate_dmax": gate},
        "name": f"v{vh}_a{ang}_s{swing}_g{sign:+d}_d{gate:g}",
        "landed": landed, "n": len(seeds),
        "lip_n": len(lips),
        "lip_vh_med": round(sorted(lips)[len(lips) // 2], 1) if lips else None,
        "lip_heading_med":
            round(sorted(heads)[len(heads) // 2], 1) if heads else None,
        "attempts": res,
    }


# pre-registered grid (see the ledger row written BEFORE the scored run)
GRID_VH = (430.0, 455.0, 475.0)
GRID_ANGLE = (45.0, 50.0, 54.0)
GRID_SWING = (4.0, 8.0, 15.0)
GRID_SIGN = (-1, 1)
GRID_GATE = (0.0, 25.0, 45.0)
SEEDS = tuple(range(1, 31))

# round-2 carve sweep (pre-registered in ledger section 9 BEFORE the run).
# Fixed from round-1 data: launch_vh 430 arms the circle earliest and is the
# wall-slide family's cell; angle 50 its dominant sub-cell; sign +1 = 122/122
# of the family (re-mined from the committed sweep-results.json.gz); swing 8
# now scopes only the pre-arm defer check; lip_gate superseded by the carve.
CARVE_FIXED_VH = 430.0
CARVE_FIXED_ANGLE = 50.0
CARVE_FIXED_SWING = 8.0
CARVE_FIXED_SIGN = 1

CARVE_GRID_D = (35.0, 55.0, 80.0)      # release-window / bend-lead arithmetic
CARVE_GRID_DEG = (45.0, 52.0, 60.0)    # accel ceiling 320/cos: 452/520/640
CARVE_GRID_VH = (410.0, 430.0, 450.0)  # strip vh p50 394.9 / p90 424.8
CARVE_GRID_TOL = (3.0, 6.0, 10.0)      # winner band: -8..-12 deg from wall


def run_carve_config(args):
    (cd, cdeg, cvh, ctol, seeds) = args
    world = WorldModel.load(BSP)
    teles = m23.load_teleporters(BSP)
    cfg = CarveCfg(cd, cdeg, cvh, ctol)
    p = make_params(CARVE_FIXED_VH, CARVE_FIXED_ANGLE, CARVE_FIXED_SWING)
    res = []
    for s in seeds:
        summ, _ = run_launch_attempt(world, teles, s, p,
                                     sign_override=CARVE_FIXED_SIGN,
                                     carve=cfg)
        res.append(summ)
    landed = sum(r["landed"] for r in res)
    armed = sum(1 for r in res if r.get("carve"))
    lips = [r["lip"]["vh"] for r in res if r["lip"]]
    heads = [r["lip"]["heading"] for r in res if r["lip"]]
    return {
        "config": {"launch_vh": CARVE_FIXED_VH,
                   "launch_angle": CARVE_FIXED_ANGLE,
                   "swing": CARVE_FIXED_SWING, "sign": CARVE_FIXED_SIGN,
                   "lip_gate_dmax": 0.0,
                   "carve_d": cd, "carve_deg": cdeg,
                   "carve_vh": cvh, "carve_tol": ctol},
        "name": f"cd{cd:g}_cg{cdeg:g}_cv{cvh:g}_ct{ctol:g}",
        "landed": landed, "n": len(seeds), "armed": armed,
        "lip_n": len(lips),
        "lip_vh_med": round(sorted(lips)[len(lips) // 2], 1) if lips else None,
        "lip_heading_med":
            round(sorted(heads)[len(heads) // 2], 1) if heads else None,
        "attempts": res,
    }


# three round-1 cells spanning the variant space; must reproduce the
# committed artifact byte-identically with carve=None (refactor safety)
BASELINE_CELLS = (
    (430.0, 50.0, 8.0, 1, 0.0),
    (455.0, 45.0, 4.0, -1, 25.0),
    (475.0, 54.0, 15.0, 1, 45.0),
)


def baseline_check(workers=8):
    src = HERE / "sweep-results.json.gz"
    with gzip.open(src, "rt", encoding="utf-8") as fh:
        committed = {c["name"]: c for c in json.load(fh)["results"]}
    cells = [(vh, ang, sw, sg, gt, SEEDS)
             for vh, ang, sw, sg, gt in BASELINE_CELLS]
    ok = True
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for fresh in ex.map(run_config, cells):
            ref = committed[fresh["name"]]
            same = all(
                json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
                for a, b in zip(fresh["attempts"], ref["attempts"])
            ) and len(fresh["attempts"]) == len(ref["attempts"])
            print(f"  {fresh['name']:24s} "
                  f"{'BYTE-IDENTICAL' if same else 'DIVERGED'}")
            ok = ok and same
    print(f"baseline-check: {'PASS' if ok else 'FAIL'} "
          f"({len(cells)} cells x {len(SEEDS)} seeds vs {src.name})")
    if not ok:
        sys.exit(1)


def carve_selfcheck():
    """Synthetic carve geometry — no BSP, no RNG, fabricated states."""
    east = [1.0, 0.0, 0.0]                       # nav_dir: goal yaw 0
    cfg = CarveCfg(d=55.0, deg=52.0, vh=430.0, tol=6.0)
    p = make_params(430.0, 50.0, 8.0)
    n = 0

    def mk(x, vel, onground=True):
        return SimpleNamespace(origin=[x, 3700.0, -488.0],
                               velocity=list(vel) + [0.0],
                               onground=onground)

    def law0():
        lw = m23.LawState()
        lw.launch_since = 0.0
        return lw

    # 1. timeout window elapsed -> stands aside (even in the arm window)
    out, armed, rec = _carve_step(cfg, p, law0(), mk(-3398.0, (440.0, 0.0)),
                                  east, 3.5, False, None)
    assert out is None and not armed, "timeout must stand aside"
    n += 1
    # 2. airborne -> stands aside
    out, armed, rec = _carve_step(cfg, p, law0(),
                                  mk(-3398.0, (440.0, 0.0), onground=False),
                                  east, 0.5, False, None)
    assert out is None and not armed, "air tick must stand aside"
    n += 1
    # 3. below launch_vh, far from lip -> deployed circle untouched
    out, armed, rec = _carve_step(cfg, p, law0(), mk(-3448.0, (300.0, 0.0)),
                                  east, 0.5, False, None)
    assert out is None and not armed, "below-speed circle must fall through"
    n += 1
    # 4. deployed release would fire outside the window -> defer (hold tick)
    lw = law0()
    out, armed, rec = _carve_step(cfg, p, lw, mk(-3448.0, (440.0, 0.0)),
                                  east, 0.5, False, None)
    assert out is not None and out[2] is False and not armed, \
        "pre-arm at-speed release must be deferred"
    assert abs(_wrap(out[0] - 50.0)) < 1e-6, "defer = circle at launch_angle"
    assert not lw.launch_done, "defer must not release"
    n += 1
    # 5. arm in window; velocity north (goal CCW err -90) -> carve CW (side -1)
    lw = law0()
    out, armed, rec = _carve_step(cfg, p, lw, mk(-3398.0, (0.0, 440.0)),
                                  east, 0.5, False, None)
    assert armed and rec["armed_d_lip"] == 50.0 and rec["armed_vh"] == 440.0
    assert out is not None and out[2] is False and rec["ticks"] == 1
    assert abs(_wrap(out[0] - (90.0 - 52.0))) < 1e-6, \
        "north entry must carve clockwise toward the target"
    n += 1
    # 6. velocity south -> carve CCW (side +1), symmetric
    lw = law0()
    out, armed, rec = _carve_step(cfg, p, lw, mk(-3398.0, (0.0, -440.0)),
                                  east, 0.5, False, None)
    assert armed and abs(_wrap(out[0] - (270.0 + 52.0))) < 1e-6, \
        "south entry must carve counter-clockwise toward the target"
    n += 1
    # 7. armed + herr within tol -> release: jump, aimed at target, latched
    lw = law0()
    st = mk(-3398.0, (439.4, -23.0))             # yaw ~ -3.0 deg
    out, armed, rec = _carve_step(cfg, p, lw, st, east, 0.5, False, None)
    assert armed and out is not None and out[2] is True
    assert rec["rule"] == "herr" and lw.launch_done and lw.jump_press
    assert abs(_wrap(out[0] - 0.0)) < 1e-6, "release must aim at the target"
    n += 1
    # 8. armed at the lip edge with poor aim -> d_lip backstop releases
    lw = law0()
    out, armed, rec = _carve_step(cfg, p, lw, mk(-3352.0, (0.0, 440.0)),
                                  east, 0.5, False, None)
    assert armed and out is not None and out[2] is True
    assert rec["rule"] == "dlip" and lw.launch_done, \
        "lip-edge arm must release via the d_lip backstop"
    n += 1
    # 9. in window but below carve_vh (and below launch_vh) -> no arm
    out, armed, rec = _carve_step(cfg, p, law0(), mk(-3398.0, (420.0, 0.0)),
                                  east, 0.5, False, None)
    assert out is None and not armed, "below carve_vh must not arm"
    n += 1
    # 10. armed earlier, speed dipped -> still carving (latch holds)
    lw = law0()
    rec0 = {"armed_t": 0.4, "armed_d_lip": 50.0, "armed_vh": 440.0,
            "armed_herr": -90.0, "rule": None, "ticks": 3}
    out, armed, rec = _carve_step(cfg, p, lw, mk(-3398.0, (0.0, 380.0)),
                                  east, 0.5, True, rec0)
    assert armed and out is not None and out[2] is False and rec["ticks"] == 4, \
        "latched carve must survive a speed dip"
    n += 1
    print(f"carve-selfcheck: PASS ({n} checks)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["probe", "sweep", "carve-sweep",
                                     "baseline-check", "carve-selfcheck"])
    ap.add_argument("--launch-vh", type=float, default=455.0)
    ap.add_argument("--launch-angle", type=float, default=50.0)
    ap.add_argument("--swing", type=float, default=12.0)
    ap.add_argument("--sign", type=int, default=-1)
    ap.add_argument("--lip-gate", type=float, default=0.0)
    ap.add_argument("--carve-d", type=float, default=0.0,
                    help="probe: arm window qu (0 = carve off)")
    ap.add_argument("--carve-deg", type=float, default=52.0)
    ap.add_argument("--carve-vh", type=float, default=430.0)
    ap.add_argument("--carve-tol", type=float, default=6.0)
    ap.add_argument("--seeds", default="1..5")
    ap.add_argument("--dump", action="store_true",
                    help="print per-row trace of the first seed")
    ap.add_argument("--out", default=None)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    if args.mode == "carve-selfcheck":
        carve_selfcheck()
        return

    if args.mode == "baseline-check":
        baseline_check(args.workers)
        return

    if args.mode == "probe":
        a, b = args.seeds.split("..")
        seeds = list(range(int(a), int(b) + 1))
        world = WorldModel.load(BSP)
        teles = m23.load_teleporters(BSP)
        p = make_params(args.launch_vh, args.launch_angle, args.swing)
        carve = (CarveCfg(args.carve_d, args.carve_deg, args.carve_vh,
                          args.carve_tol) if args.carve_d > 0 else None)
        for s in seeds:
            summ, rows = run_launch_attempt(world, teles, s, p,
                                            sign_override=args.sign,
                                            lip_gate_dmax=args.lip_gate,
                                            carve=carve)
            print(json.dumps(summ))
            if args.dump and s == seeds[0]:
                for r in rows[:: max(1, len(rows) // 120)]:
                    print(f"  t={r['t']:6.3f} ({r['x']:8.1f},{r['y']:7.1f},"
                          f"{r['z']:7.1f}) vh={r['vh']:5.0f} vz={r['vz']:5.0f}"
                          f" g={r['onground']} yaw={r['yaw']:6.1f} j={r['jump']}")
        return

    if args.mode == "carve-sweep":
        out = args.out or str(HERE / "carve-sweep-results.json")
        cells = [(cd, cdeg, cvh, ctol, SEEDS)
                 for cd, cdeg, cvh, ctol in itertools.product(
                     CARVE_GRID_D, CARVE_GRID_DEG, CARVE_GRID_VH,
                     CARVE_GRID_TOL)]
        print(f"carve-sweep: {len(cells)} configs x {len(SEEDS)} seeds")
        results = []
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            for i, r in enumerate(ex.map(run_carve_config, cells)):
                results.append(r)
                if r["landed"]:
                    print(f"  [{i+1}/{len(cells)}] {r['name']}: "
                          f"LANDED {r['landed']}/{r['n']}")
        results.sort(key=lambda r: (-r["landed"], r["name"]))
        Path(out).write_text(json.dumps(
            {"grid": {"carve_d": CARVE_GRID_D, "carve_deg": CARVE_GRID_DEG,
                      "carve_vh": CARVE_GRID_VH, "carve_tol": CARVE_GRID_TOL,
                      "fixed": {"launch_vh": CARVE_FIXED_VH,
                                "launch_angle": CARVE_FIXED_ANGLE,
                                "swing": CARVE_FIXED_SWING,
                                "sign": CARVE_FIXED_SIGN,
                                "lip_gate_dmax": 0.0},
                      "seeds": [SEEDS[0], SEEDS[-1]], "target": TARGET,
                      "deposit": DEPOSIT, "budget_s": ATTEMPT_BUDGET_S},
             "results": results}, indent=1))
        print("\ntop 10:")
        for r in results[:10]:
            print(f"  {r['name']:24s} landed {r['landed']:2d}/{r['n']}  "
                  f"armed {r['armed']:2d}  lip_med={r['lip_vh_med']} "
                  f"head_med={r['lip_heading_med']} lip_n={r['lip_n']}")
        print(f"wrote {out}")
        return

    out = args.out or str(HERE / "sweep-results.json")
    cells = [(vh, ang, sw, sg, gt, SEEDS)
             for vh, ang, sw, sg, gt in itertools.product(
                 GRID_VH, GRID_ANGLE, GRID_SWING, GRID_SIGN, GRID_GATE)]
    print(f"sweep: {len(cells)} configs x {len(SEEDS)} seeds")
    results = []
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        for i, r in enumerate(ex.map(run_config, cells)):
            results.append(r)
            if r["landed"]:
                print(f"  [{i+1}/{len(cells)}] {r['name']}: "
                      f"LANDED {r['landed']}/{r['n']}")
    results.sort(key=lambda r: (-r["landed"], r["name"]))
    Path(out).write_text(json.dumps(
        {"grid": {"vh": GRID_VH, "angle": GRID_ANGLE, "swing": GRID_SWING,
                  "sign": GRID_SIGN, "gate": GRID_GATE,
                  "seeds": [SEEDS[0], SEEDS[-1]], "target": TARGET,
                  "deposit": DEPOSIT, "budget_s": ATTEMPT_BUDGET_S},
         "results": results}, indent=1))
    print(f"\ntop 10:")
    for r in results[:10]:
        print(f"  {r['name']:24s} landed {r['landed']:2d}/{r['n']}  "
              f"lip_med={r['lip_vh_med']} head_med={r['lip_heading_med']} "
              f"lip_n={r['lip_n']}")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
