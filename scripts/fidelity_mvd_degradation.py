"""MVD-degradation fidelity experiment (Demo Extraction Spec docs/27 §4).

Replays a dm3 POV .qwd twice through pmove_sim and prints anchored per-step bhop-regime
(hspeed>=400) horizontal-speed error: (a) GROUND-TRUTH real usercmds, (b) the same inputs
DEGRADED to the MVD/IDM representation (forwardmove->0; sidemove=-sign(yaw_rate)*400 gated
|yaw_rate|>=20 deg/s; jump from geometric-onground T->F with vz>1; yaw angle16-quantized,
step-held -- verbatim catalog_etl_mvd.py). Isolates what the MVD lossy action representation
costs vs ground truth. CPU-only.

  python3 scripts/fidelity_mvd_degradation.py <demo.qwd> [n_frames] [dm3.bsp]
"""
import sys, json, math, statistics as st
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.setrecursionlimit(20000)
import build_replay_command_file as brc
import pmove_sim as P
from features.agent_observation import yaw_rate_degps

# --- MVD/IDM degradation constants (verbatim from catalog_etl_mvd.py) -----------
ANGLE16 = 360.0 / 65536.0
DEADBAND = 20.0          # YAW_RATE_DEADBAND deg/s
SIDEMAG = 400.0          # SIDEMOVE_MAG
FWD_PRIOR = 0.0          # FORWARDMOVE_PRIOR (unrecoverable)
JUMP_MIN_AIR = 2
JUMP_VZ_MIN = 1.0
BUTTON_JUMP = P.BUTTON_JUMP


def q16(deg):
    # quantize a float view angle (deg) to angle16 wire resolution (what MVD stores)
    return round(deg / ANGLE16) * ANGLE16


def onground_series(world, frames):
    return [P.derive_onground(world, f["origin"], f["velocity"]) for f in frames]


def recover_jumps(onground, frames):
    # _recover_jumps verbatim: onground T->F with vz>JUMP_VZ_MIN, sustained >=JUMP_MIN_AIR ticks,
    # press attributed to tick i (last grounded tick).
    n = len(frames); jump = [False] * n
    for i in range(n - 1):
        if not (onground[i] and not onground[i + 1]):
            continue
        if frames[i + 1]["velocity"][2] <= JUMP_VZ_MIN:
            continue
        air = 0
        for j in range(i + 1, min(n, i + 1 + JUMP_MIN_AIR)):
            if onground[j]:
                break
            air += 1
        if air >= JUMP_MIN_AIR:
            jump[i] = True
    return jump


def degrade(frames, world):
    # build the usercmd stream the MVD/IDM representation would yield from this trajectory.
    onground = onground_series(world, frames)
    jump = recover_jumps(onground, frames)
    out = []
    prev_yaw = None
    for i, f in enumerate(frames):
        msec = int(f["msec"]); dt = msec * 0.001
        pitch_q = q16(f["angles"][0]); yaw_q = q16(f["angles"][1])
        yr = yaw_rate_degps(yaw_q, prev_yaw, dt)   # canonical helper, quantized yaw (ETL parity)
        prev_yaw = yaw_q
        if abs(yr) >= DEADBAND:
            side = -SIDEMAG if yr > 0.0 else SIDEMAG   # sign(side) == -sign(yaw_rate)
        else:
            side = 0.0
        j = jump[i]
        buttons = BUTTON_JUMP if j else 0
        up = SIDEMAG if j else 0.0
        out.append({
            "origin": f["origin"], "velocity": f["velocity"],   # MVD is omniscient about STATE
            "angles": (pitch_q, yaw_q, 0.0),                    # angle16-quantized, step-held
            "move": (FWD_PRIOR, side, up),                      # fwd lost, side=IDM sign, up=jump
            "buttons": buttons, "msec": msec,
        })
    return out


DEMO = sys.argv[1]; N = int(sys.argv[2]) if len(sys.argv) > 2 else 4000
BSP = sys.argv[3] if len(sys.argv) > 3 else '/home/xerial/komodo-phase4/dm3.bsp'
world = P.WorldModel.load(BSP)
allf, meta = brc.build_replay_frames(Path(DEMO), alignment="time")
gt = allf[:N]
deg = degrade(gt, world)
tele = set(i for i in P.detect_teleports(allf) if i < len(gt))


def hsp(v):
    return math.hypot(v[0], v[1])


rec = [hsp(f["velocity"]) for f in gt]
mean = lambda xs: round(st.mean(xs), 2) if xs else None


def speed_err(rows):
    o = []; hi = []
    for r in rows:
        k = r["frame"]
        if r.get("teleport_reanchor") or k >= len(rec):
            continue
        e = abs(r["sim_vh"] - rec[k]); o.append(e)
        if rec[k] >= 400:
            hi.append(e)
    return mean(o), mean(hi), len(hi)


# ground-truth baseline (anchored per-step), re-run for in-script parity
gt_an, gt_rows = P.replay(world, gt, anchored=True, reanchor_at=tele)
gt_all, gt_hi, gt_n = speed_err(gt_rows)
# MVD-degraded (anchored per-step + 1s segmented horizon)
dg_an, dg_rows = P.replay(world, deg, anchored=True, reanchor_at=tele)
dg_all, dg_hi, dg_n = speed_err(dg_rows)
dg_seg, dg_segrows = P.replay(world, deg, reanchor_every=77, reanchor_at=tele)

onground = onground_series(world, gt)
jumps = recover_jumps(onground, gt)
print(json.dumps({
    "demo": Path(DEMO).name, "n": len(gt), "teleports": len(tele),
    "recorded_hspeed": {"mean": mean(rec), "max": round(max(rec), 1),
                        "frames_ge400": sum(1 for x in rec if x >= 400)},
    "n_jumps_recovered": sum(1 for j in jumps if j),
    "n_onground": sum(1 for g in onground if g),
    "GROUND_TRUTH_anchored_SPEED_err": {"overall": gt_all, "bhop_ge400": gt_hi, "frames": gt_n},
    "MVD_DEGRADED_anchored_SPEED_err": {"overall": dg_all, "bhop_ge400": dg_hi, "frames": dg_n},
    "MVD_DEGRADED_anchored_origin_err": {k: dg_an[k] for k in ("max_err", "mean_err", "p95_err")},
    "MVD_DEGRADED_seg1s_origin_err": {k: dg_seg[k] for k in ("max_err", "mean_err", "p95_err", "first_divergence_frame")},
}, indent=1))
