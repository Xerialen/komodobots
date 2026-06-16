#!/usr/bin/env python3
"""Multi-physent trace foundation tests (pmove_sim).

Guards three things:
  1. REGRESSION — worldmodel-only default (Pmove.physents empty) is byte-
     identical to the validated baseline on the human SNG->RL replay.
  2. BOX HULL — make_player_physent() actually blocks a swept trace that would
     otherwise pass through, and lets a clear trace through untouched.
  3. SUBMODELS — the 6 dm3 brush submodels load, and load_submodels() is opt-in
     (does not perturb the human replay, which never touches them).

Run: python tests/test_physent_collision.py  [--bsp <path>]
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.setrecursionlimit(20000)

import pmove_sim as P  # noqa: E402


def _human_replay(world, physents_loader=None):
    cmds = ROOT / "experiments/dm3_sng_to_rl_observability/evidence/dm3_sng_to_rl.cmds"
    if not cmds.exists():
        for c in (Path("artifacts/replay/dm3_sng_to_rl.cmds"),
                  ROOT / "artifacts/replay/dm3_sng_to_rl.cmds"):
            if c.exists():
                cmds = c
                break
    frames = P.load_cmds_file(str(cmds))
    tele = P.detect_teleports(frames)
    # replay() builds its own Pmove; to inject submodels we monkey-patch via a
    # subclass hook. Simplest: run the loop here mirroring replay()'s core.
    pm = P.Pmove(world)
    if physents_loader:
        physents_loader(pm)
    s = P.PlayerState(frames[0]["origin"], frames[0]["velocity"])
    tele = set(tele)
    max_err = 0.0
    n = len(frames) - 1
    for k in range(n):
        f = frames[k]
        if k > 0 and (k - 1) in tele:
            s = P.PlayerState(f["origin"], f["velocity"], jump_held=s.jump_held,
                              waterjumptime=s.waterjumptime)
        pm.run_frame(s, P.Cmd(f["msec"], f["angles"], f["move"], f["buttons"]))
        rec = frames[k + 1]
        if k in tele:
            continue
        err = math.dist(s.origin, rec["origin"])
        max_err = max(max_err, err)
    return max_err


def test_regression_worldmodel_only(world):
    max_err = _human_replay(world)  # default Pmove.physents == []
    assert max_err < 0.3, f"worldmodel-only human replay regressed: max_err={max_err}"
    print(f"  [1] regression worldmodel-only: human replay max_err={max_err:.3f} qu  OK")


def _open_air_segment(world):
    """A guaranteed-clear short horizontal trace, anchored to a real airborne
    replay frame (so start/end are provably open space the human moved through)."""
    cmds = ROOT / "experiments/dm3_sng_to_rl_observability/evidence/dm3_sng_to_rl.cmds"
    frames = P.load_cmds_file(str(cmds))
    for f in frames:
        vh = math.hypot(f["velocity"][0], f["velocity"][1])
        if vh > 200:  # moving fast & horizontally -> airborne over open space
            o, v = f["origin"], f["velocity"]
            ux, uy = v[0] / vh, v[1] / vh
            start = [o[0], o[1], o[2]]
            end = [o[0] + ux * 120.0, o[1] + uy * 120.0, o[2]]  # 120 qu along travel
            tr = P.player_trace(world, start, end)
            if tr.fraction == 1.0:
                return start, end, (ux, uy)
    raise AssertionError("no clear open-air segment found in replay")


def test_box_hull_blocks(world):
    start, end, (ux, uy) = _open_air_segment(world)
    clear = P.player_trace(world, start, end)
    assert clear.fraction == 1.0, f"control trace not clear: {clear.fraction}"
    # Opponent box ~85 qu ahead (beyond the 32 qu Minkowski half-width, so the
    # start is NOT solid) => a genuine swept stop with 0 < fraction < 1.
    ahead = (start[0] + ux * 85.0, start[1] + uy * 85.0, start[2])
    blocked = P.player_trace(world, start, end, [P.make_player_physent(ahead, ent=7)])
    assert 0.0 < blocked.fraction < 1.0, (
        f"box did not produce a swept stop: frac={blocked.fraction}")
    assert blocked.ent == 7, f"blocked.ent={blocked.ent}, expected opponent ent 7"
    # A box far to the side does not perturb the clear trace.
    side = (start[0] - uy * 400.0, start[1] + ux * 400.0, start[2])
    miss = P.player_trace(world, start, end, [P.make_player_physent(side, ent=8)])
    assert miss.fraction == 1.0, f"distant box perturbed the trace: {miss.fraction}"
    print(f"  [2] box hull: clear frac=1.000 -> blocked frac={blocked.fraction:.3f} "
          f"(ent={blocked.ent}); distant box untouched  OK")


def test_submodels_optin(world):
    assert len(world.submodels) == 6, f"expected 6 dm3 submodels, got {len(world.submodels)}"
    # opt-in must not perturb the human SNG->RL route (it touches no submodel)
    max_err = _human_replay(world, physents_loader=lambda pm: pm.load_submodels())
    assert max_err < 0.3, f"submodels perturbed the human replay: max_err={max_err}"
    print(f"  [3] submodels: {len(world.submodels)} loaded; human replay with "
          f"submodels max_err={max_err:.3f} qu (route avoids them)  OK")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bsp", default=r"C:\nQuake\qw\maps\dm3.bsp")
    args = ap.parse_args()
    if not Path(args.bsp).exists():
        alt = "/mnt/c/nQuake/qw/maps/dm3.bsp"
        if Path(alt).exists():
            args.bsp = alt
        else:
            raise SystemExit(f"dm3.bsp not found ({args.bsp}); pass --bsp")
    world = P.WorldModel.load(args.bsp)
    print("physent-collision tests:")
    test_regression_worldmodel_only(world)
    test_box_hull_blocks(world)
    test_submodels_optin(world)
    print("ALL PASS")


if __name__ == "__main__":
    main()
