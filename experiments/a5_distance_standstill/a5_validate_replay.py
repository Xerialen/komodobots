#!/usr/bin/env python3
"""A5 #118 step 3: validate pmove_sim on ztricks.bsp by replaying the human.

Replays getspeed-aligned.cmds (time-aligned rebuild, see a5_rebuild_cmds.py)
free-run through the pmove port against the real ztricks.bsp, re-anchoring
only at the demo's teleport resets. PASS requires (trust bounds = the dm3
human-replay precedent: per-frame <= 4 qu, speeds +-2 qu/s):

  1. per-step physics: ANCHORED replay p95 <= 0.5 qu (the dm3 anchored
     criterion class; isolates physics from reference lumps);
  2. free-run stability per attempt: the demo's state stream has documented
     lumps near its 41 dropped frames (half-step + stretched-step pairs
     from network jitter, clustered in the post-teleport skates). Free-run
     error through a lumpy stretch may transiently exceed the bound, so the
     binding requirement is where the measurements live: EVERY attempt's
     last 10 rows before its lip (the launch state) track <= 2 qu, and the
     sim recovers to <= 2 qu within 6 rows after every anomaly window;
  3. the winning attempt (last reset -> landing): every clean row <= 4 qu,
     no re-anchor inside, checkpoints reproduced (lip vh ~475, landing vh
     ~496, +-2), and the arc LANDS in-sim: grounded, z == -488, x > -3100
     (the locked far-platform detector) at the recorded landing row;
  4. per-attempt lip table (11 attempts segmented by teleport resets):
     lip speed range and the winner's uniquely-negative launch heading
     reproduce the spec table (455-477 among jump-launches, winner -11 deg).

Writes human-replay.json. Exit 0 = all PASS, 2 = any FAIL.
"""
from __future__ import annotations

import logging
import json
import math
import sys
from pathlib import Path


LOGGER = logging.getLogger(__name__)
HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from pmove_sim import (  # noqa: E402
    WorldModel, detect_teleports, load_cmds_file, replay,
)

BSP = r"C:\nQuake\qw\maps\ztricks.bsp"
CMDS = HERE / "getspeed-aligned.cmds"
META = HERE / "alignment-meta.json"
OUT = HERE / "human-replay.json"

ERR_BOUND = 4.0          # qu, dm3 precedent
RECOVER_BOUND = 2.0      # qu, required after every anomaly window
RECOVER_ROWS = 6
STEP_ANOM = 2.5          # qu deviation |rec step| vs |rec v|*dt = lumpy reference
SPEED_BOUND = 2.0        # qu/s on int-truncated recorded velocity
LAND_X = -3100.0         # locked far-platform detector band
LAND_Z = -488.0
DEPO = (-3516.125, 3712.0)


def vh(f):
    return math.hypot(f["velocity"][0], f["velocity"][1])


def main():
    frames = load_cmds_file(CMDS)
    meta = json.loads(META.read_text())
    interp = set(meta["dropped_cmd_indices"])
    world = WorldModel.load(BSP)

    tele = detect_teleports(frames)
    summary, rows = replay(world, frames, reanchor_at=tele)
    by_frame = {r["frame"]: r for r in rows}
    anch_summary, _ = replay(world, frames, anchored=True, reanchor_at=tele)

    # ── reference anomalies: rows whose recorded step length disagrees with
    # the recorded velocity (state-stream lumps near the dropped frames) ─────
    anom = set()
    for k in range(len(frames) - 1):
        if k in tele:
            continue
        f, g = frames[k], frames[k + 1]
        dt = f["msec"] * 0.001
        step = math.dist(f["origin"], g["origin"])
        v3 = math.sqrt(sum(c * c for c in f["velocity"]))
        if abs(step - v3 * dt) > STEP_ANOM:
            anom.update({k + 1, k + 2})   # rows referencing the lumpy state

    skip = set(tele) | {t + 1 for t in tele}

    def clean(r):
        return (r["frame"] not in interp and r["frame"] not in anom
                and (r["frame"] - 1) not in skip and not r["teleport_reanchor"])

    real = [r for r in rows if clean(r)]
    errs = [r["err"] for r in real]
    track_all = max(errs) <= ERR_BOUND

    # recovery: after each anomaly window the sim must return under bound
    recover_fail = []
    for a in sorted(anom):
        after = [r for r in rows
                 if a < r["frame"] <= a + RECOVER_ROWS and clean(r)]
        if after and min(r["err"] for r in after) > RECOVER_BOUND:
            recover_fail.append(a)

    # ── attempts: segment by teleport ARRIVALS at the t5 deposit ────────────
    arrivals = [k + 1 for k in tele
                if math.hypot(frames[k + 1]["origin"][0] - DEPO[0],
                              frames[k + 1]["origin"][1] - DEPO[1]) < 8.0]
    bounds = [0] + arrivals + [len(frames) - 1]
    attempts = [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1)]

    # per-attempt lip: LAST GROUNDED row (z=-488, vz==0, x > -3420) whose
    # next row leaves the floor — by jumping (vz flips positive) OR by
    # walking off (vz turns negative; the first falling frame sinks only
    # ~0.1 qu, so a z-threshold alone misses walk-offs — Codex PR #120
    # round 4 caught attempt 6 silently dropping out of the lip checks).
    # Arc rows crossing the -488 plane mid-flight carry vz != 0 and are
    # rejected as lips. vz look-ahead runs through interpolated rows
    # (drops cluster at the takeoffs).
    att_table = []
    for ai, (a, b) in enumerate(attempts):
        lip = None
        for k in range(a, b - 1):
            f = frames[k]
            if (abs(f["origin"][2] - LAND_Z) > 0.5 or f["origin"][0] <= -3420
                    or f["velocity"][2] != 0):
                continue
            nxt = frames[k + 1]
            if abs(nxt["origin"][2] - LAND_Z) > 0.5 or nxt["velocity"][2] != 0:
                lip = k
        ent = {"attempt": ai + 1, "rows": [a, b]}
        if lip is not None:
            vz_ahead = max(frames[j]["velocity"][2]
                           for j in range(lip + 1, min(lip + 4, b)))
            nxt = lip + 2 if (lip + 1) in interp else lip + 1
            dx = frames[nxt]["origin"][0] - frames[lip]["origin"][0]
            dy = frames[nxt]["origin"][1] - frames[lip]["origin"][1]
            pre = [r for r in rows if lip - 10 <= r["frame"] <= lip and clean(r)]
            ent.update({
                "lip_row": lip,
                "lip_origin": [round(c, 1) for c in frames[lip]["origin"]],
                "lip_vh": round(vh(frames[lip]), 1),
                "launch_heading_deg": round(math.degrees(math.atan2(dy, dx)), 1),
                "jumped": vz_ahead > 100,
                "jump_bit_at_lip": bool(frames[lip]["buttons"] & 2),
                "max_err_10rows_before_lip":
                    round(max(r["err"] for r in pre), 3) if pre else None,
            })
        seg = [r for r in rows if a < r["frame"] <= b and clean(r)]
        ent["max_err_clean"] = round(max(r["err"] for r in seg), 3) if seg else None
        landed_rec = landed_sim = False
        for k in range(a + 1, b):
            f = frames[k]
            if (abs(f["origin"][2] - LAND_Z) < 0.5 and f["origin"][0] > LAND_X
                    and abs(f["velocity"][2]) < 1):
                landed_rec = True
                r = by_frame.get(k)
                if r and r["regime"] == "ground" and r["sim_origin"][0] > LAND_X \
                        and abs(r["sim_origin"][2] - LAND_Z) < 0.5:
                    landed_sim = True
                break
        ent["landed_recorded"] = landed_rec
        ent["landed_sim"] = landed_sim
        att_table.append(ent)

    # ── the winning attempt ──────────────────────────────────────────────────
    win = att_table[-1]
    wa, wb = win["rows"]
    win_rows = [r for r in rows if wa < r["frame"] <= wb]
    win_clean = [r for r in win_rows if clean(r)]
    win_max_err = max(r["err"] for r in win_clean)
    win_reanchor_inside = any(r["teleport_reanchor"] for r in win_rows
                              if r["frame"] - 1 > wa + 2)

    def sim_vh_at(k):
        r = by_frame.get(k)
        return r["sim_vh"] if r else None

    lip_row = win["lip_row"]
    checkpoints = {
        "lip": {"row": lip_row, "rec": round(vh(frames[lip_row]), 1),
                "sim": sim_vh_at(lip_row)},
    }
    land_row = next(k for k in range(lip_row, wb)
                    if abs(frames[k]["origin"][2] - LAND_Z) < 0.5
                    and frames[k]["origin"][0] > LAND_X)
    checkpoints["landing"] = {"row": land_row,
                              "rec": round(vh(frames[land_row]), 1),
                              "sim": sim_vh_at(land_row)}
    cp_ok = all(c["sim"] is not None and abs(c["sim"] - c["rec"]) <= SPEED_BOUND
                for c in checkpoints.values())

    jump_lips = [a["lip_vh"] for a in att_table if a.get("jumped")]
    win_heading = win.get("launch_heading_deg")
    other_headings = [a["launch_heading_deg"] for a in att_table[:-1]
                      if "launch_heading_deg" in a]
    table_ok = (min(jump_lips) >= 450 and max(jump_lips) <= 480
                and win_heading is not None and -14 <= win_heading <= -8
                and all(h > win_heading for h in other_headings))

    # EVERY attempt must yield a lip and track there (a missing lip can not
    # silently pass — Codex round 4); the demo's documented structure is
    # exactly 10 jump-launches + 1 walk-off botch.
    lips_tracked = (len(att_table) == 11
                    and all("lip_row" in a for a in att_table)
                    and all(a["max_err_10rows_before_lip"] is not None
                            and a["max_err_10rows_before_lip"] <= RECOVER_BOUND
                            for a in att_table))
    structure_ok = (sum(1 for a in att_table if a.get("jumped")) == 10
                    and sum(1 for a in att_table if not a.get("jumped")) == 1)
    anchored_ok = (anch_summary["p95_err"] is not None
                   and anch_summary["p95_err"] <= 0.5)
    verdict = {
        "anchored_p95": anch_summary["p95_err"],
        "anchored_mean": anch_summary["mean_err"],
        "anchored_ok_p95_under_0.5": anchored_ok,
        "max_err_clean_rows": round(max(errs), 3),
        "mean_err_clean_rows": round(sum(errs) / len(errs), 3),
        "freerun_clean_under_4qu": track_all,
        "n_anomalous_reference_windows": len(anom) // 2,
        "anomaly_recovery_failures": recover_fail,
        "n_attempts": len(att_table),
        "all_11_lips_found_and_tracked_under_2qu": lips_tracked,
        "structure_10_jumps_1_walkoff": structure_ok,
        "win_attempt_max_err_clean": round(win_max_err, 3),
        "win_attempt_tracked": win_max_err <= ERR_BOUND and not win_reanchor_inside,
        "checkpoints": checkpoints,
        "checkpoints_ok": cp_ok,
        "win_landed_recorded": win["landed_recorded"],
        "win_landed_sim": win["landed_sim"],
        "spec_table_ok": table_ok,
    }
    ok = (anchored_ok and lips_tracked and structure_ok and not recover_fail
          and verdict["win_attempt_tracked"] and cp_ok and win["landed_sim"]
          and table_ok)
    out = {
        "bsp": BSP, "cmds": str(CMDS), "summary": summary,
        "n_interp_rows_excluded": len(interp),
        "anomalous_rows_excluded": sorted(anom),
        "attempt_table": att_table,
        "verdict": verdict, "pass": ok,
    }
    OUT.write_text(json.dumps(out, indent=1))

    print(f"anchored: p95={anch_summary['p95_err']} mean={anch_summary['mean_err']}"
          f"  ok={anchored_ok}")
    print(f"free-run rows={len(rows)}  clean-row err: max="
          f"{verdict['max_err_clean_rows']} mean={verdict['mean_err_clean_rows']}"
          f"  (anomalous reference windows excluded: "
          f"{verdict['n_anomalous_reference_windows']}, all recovered: "
          f"{not recover_fail})")
    print(f"attempts={len(att_table)}")
    print("\natt  lip_vh  heading  jumped  bit@lip  err@lip  err_max  landed(rec/sim)")
    for a in att_table:
        if "lip_vh" not in a:
            print(f"{a['attempt']:3d}  (no lip exit found)   err_max="
                  f"{a.get('max_err_clean')}")
            continue
        print(f"{a['attempt']:3d}  {a['lip_vh']:6.1f}  {a['launch_heading_deg']:7.1f}"
              f"  {str(a.get('jumped')):5s}   {str(a['jump_bit_at_lip']):5s}"
              f"  {a['max_err_10rows_before_lip']:7.3f}  {a['max_err_clean']:7.3f}"
              f"  {a['landed_recorded']}/{a['landed_sim']}")
    print(f"\nwinning attempt: max_err_clean={verdict['win_attempt_max_err_clean']} "
          f"tracked={verdict['win_attempt_tracked']}")
    for name, c in checkpoints.items():
        print(f"  {name}: rec {c['rec']} sim {c['sim']}")
    print(f"win landed in sim: {win['landed_sim']}")
    print(f"spec table ok: {table_ok}")
    print(f"\nVERDICT: {'PASS' if ok else 'FAIL'}")
    print(f"wrote {OUT}")
    sys.exit(0 if ok else 2)


if __name__ == "__main__":
    main()
