#!/usr/bin/env python3
"""Validate the bunnyhop theories in the TRUSTED pure-air sim (qwsim air-accel, 0.1% on trick5).
Generative SteerSign policy: no demo. Tests (1) the sign theory, (2) OMEGA/lead/lobe sweeps."""
import logging
import math
from qwsim import air_step, MV


LOGGER = logging.getLogger(__name__)
DT = 0.013

def wrap180(d):
    while d > 180: d -= 360
    while d < -180: d += 360
    return d

def run_policy(OMEGA=160.0, LOBE=100.0, side_mag=400.0, sign_mode="accel",
               n=6000, seed_speed=400.0):
    """View ROTATES continuously at OMEGA in the lobe direction s (an air-strafe never
    stops turning mid-lobe); strafe sits on the accelerating side. Reversal flips s after
    the velocity heading has swept LOBE degrees -> the figure-8."""
    st = dict(vx=seed_speed, vy=0.0)
    s = 1; dh_acc = 0.0
    H_prev = 0.0; cur_yaw = 0.0
    trace = []
    for k in range(n):
        speed = math.hypot(st["vx"], st["vy"])
        H = math.degrees(math.atan2(st["vy"], st["vx"]))
        dh_acc += abs(wrap180(H - H_prev)); H_prev = H
        if dh_acc >= LOBE:
            s = -s; dh_acc = 0.0
        cur_yaw = wrap180(cur_yaw + s*OMEGA*DT)          # continuous rotation
        if sign_mode == "accel":   side_sign = -s        # the accelerating side (turn dir s)
        elif sign_mode == "decel": side_sign =  s        # the WRONG side (the v1 bug)
        else:                                            # greedy oracle
            a = dict(st); air_step(a, cur_yaw, 0.0, +side_mag, DT)
            b = dict(st); air_step(b, cur_yaw, 0.0, -side_mag, DT)
            side_sign = 1 if math.hypot(a["vx"],a["vy"]) >= math.hypot(b["vx"],b["vy"]) else -1
        air_step(st, cur_yaw, 0.0, side_sign*side_mag, DT)
        trace.append(math.hypot(st["vx"], st["vy"]))
    warm = sorted(trace[len(trace)//2:])
    return dict(median=warm[len(warm)//2], p90=warm[int(0.9*len(warm))],
                peak=max(trace), end=trace[-1])

def show(tag, r):
    print(f"{tag:34} median={r['median']:4.0f}  p90={r['p90']:4.0f}  peak={r['peak']:4.0f}  end={r['end']:4.0f}")

print("=== (1) SIGN THEORY (view rotating at OMEGA=160) ===")
show("strafe ACCEL side (-s)  [v2 fix]", run_policy(OMEGA=160, sign_mode="accel"))
show("strafe DECEL side (+s)  [v1 bug]", run_policy(OMEGA=160, sign_mode="decel"))
show("strafe greedy-optimal   [oracle]", run_policy(OMEGA=160, sign_mode="optimal"))

print("\n=== (2) OMEGA sweep (accel sign) -> which view-rate yields ~880? ===")
for om in (100,120,140,160,175,190,205,230,260):
    show(f"OMEGA={om}", run_policy(OMEGA=om, sign_mode="accel"))

print("\n=== (3) LOBE_TARGET sweep (accel, OMEGA at the ~880 point) — figure-8 size ===")
for lb in (70,100,140,200,300):
    show(f"LOBE={lb}", run_policy(OMEGA=140, LOBE=lb, sign_mode="accel"))
