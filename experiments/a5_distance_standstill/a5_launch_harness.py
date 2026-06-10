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

CLI:
  python a5_launch_harness.py probe --launch-vh 455 --launch-angle 50 \
      [--swing 12] [--sign -1] [--lip-gate 0] [--seeds 1..5] [--dump]
  python a5_launch_harness.py sweep --out sweep-results.json [--workers 8]
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
import random
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from types import SimpleNamespace

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
                       sign_override=0, lip_gate_dmax=0.0,
                       target=TARGET, budget_s=ATTEMPT_BUDGET_S):
    """One standstill attempt. Returns a summary dict (+ rows)."""
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
        if (lip_gate_dmax > 0.0 and params.launch_vh > 0.0
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

    return {
        "seed": seed, "outcome": outcome, "t_end": round(t, 2),
        "landed": outcome == "LANDED",
        "release": release, "lip": lip_state,
        "max_vh": round(max(r["vh"] for r in rows), 1),
    }, rows


def _wrap(a):
    while a > 180.0:
        a -= 360.0
    while a < -180.0:
        a += 360.0
    return a


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["probe", "sweep"])
    ap.add_argument("--launch-vh", type=float, default=455.0)
    ap.add_argument("--launch-angle", type=float, default=50.0)
    ap.add_argument("--swing", type=float, default=12.0)
    ap.add_argument("--sign", type=int, default=-1)
    ap.add_argument("--lip-gate", type=float, default=0.0)
    ap.add_argument("--seeds", default="1..5")
    ap.add_argument("--dump", action="store_true",
                    help="print per-row trace of the first seed")
    ap.add_argument("--out", default=str(HERE / "sweep-results.json"))
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    if args.mode == "probe":
        a, b = args.seeds.split("..")
        seeds = list(range(int(a), int(b) + 1))
        world = WorldModel.load(BSP)
        teles = m23.load_teleporters(BSP)
        p = make_params(args.launch_vh, args.launch_angle, args.swing)
        for s in seeds:
            summ, rows = run_launch_attempt(world, teles, s, p,
                                            sign_override=args.sign,
                                            lip_gate_dmax=args.lip_gate)
            print(json.dumps(summ))
            if args.dump and s == seeds[0]:
                for r in rows[:: max(1, len(rows) // 120)]:
                    print(f"  t={r['t']:6.3f} ({r['x']:8.1f},{r['y']:7.1f},"
                          f"{r['z']:7.1f}) vh={r['vh']:5.0f} vz={r['vz']:5.0f}"
                          f" g={r['onground']} yaw={r['yaw']:6.1f} j={r['jump']}")
        return

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
    Path(args.out).write_text(json.dumps(
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
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
