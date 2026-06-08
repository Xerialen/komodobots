#!/usr/bin/env python3
"""Confinement check: does the (validated) figure-8 stay inside trick.bsp at the 880 OMEGA?
Integrates origin; optional position-feedback reversal (reverse early when far from center AND
moving outward) to hold the 8 in the room without a speed-killing centering term.

trick.bsp open area: half-width ~1008 qu (mode-16 source comment); human trick5 bbox was 1788."""
import math
from qwsim import air_step

DT = 0.013
ROOM_HALF = 1008.0   # trick.bsp playable half-width (from KTX mode-16 comment)
HUMAN_BBOX = 1788.0

def wrap180(d):
    while d > 180: d -= 360
    while d < -180: d += 360
    return d

def run(OMEGA=185.0, LOBE=100.0, R_confine=None, n=8000, seed=400.0):
    st = dict(vx=seed, vy=0.0); x = y = 0.0
    s = 1; dh = 0.0; H_prev = 0.0; cur_yaw = 0.0
    traj = []
    for k in range(n):
        H = math.degrees(math.atan2(st["vy"], st["vx"]))
        dh += abs(wrap180(H - H_prev)); H_prev = H
        reverse = dh >= LOBE
        if R_confine is not None:
            dist = math.hypot(x, y)
            outward = (x*st["vx"] + y*st["vy"]) > 0   # velocity has an outward radial component
            if dist > R_confine and outward:
                reverse = True
        if reverse:
            s = -s; dh = 0.0
        cur_yaw = wrap180(cur_yaw + s*OMEGA*DT)
        air_step(st, cur_yaw, 0.0, -s*400.0, DT)
        x += st["vx"]*DT; y += st["vy"]*DT
        traj.append((x, y, math.hypot(st["vx"], st["vy"])))
    h = traj[len(traj)//2:]                       # steady state
    xs = [p[0] for p in h]; ys = [p[1] for p in h]; sp = sorted(p[2] for p in h)
    bbox = max(max(xs)-min(xs), max(ys)-min(ys))
    maxdist = max(math.hypot(p[0], p[1]) for p in h)
    # drift: centroid of first vs last fifth of the steady-state window
    q = len(h)//5
    c0 = (sum(p[0] for p in h[:q])/q, sum(p[1] for p in h[:q])/q)
    c1 = (sum(p[0] for p in h[-q:])/q, sum(p[1] for p in h[-q:])/q)
    drift = math.hypot(c1[0]-c0[0], c1[1]-c0[1])
    return dict(median=sp[len(sp)//2], peak=max(sp), bbox=bbox, maxdist=maxdist, drift=drift)

def show(tag, r):
    fit = "FITS" if r["maxdist"] < ROOM_HALF else "OUT-OF-ROOM"
    print(f"{tag:30} med={r['median']:4.0f} peak={r['peak']:4.0f}  bbox={r['bbox']:5.0f} "
          f"maxdist={r['maxdist']:5.0f} drift={r['drift']:5.0f}  -> {fit}")

print(f"room half-width={ROOM_HALF:.0f}, human bbox={HUMAN_BBOX:.0f}\n")
print("=== PURE CIRCLE (never reverse) — is a confined orbit alone enough for 880? ===")
for om in (130, 145, 160, 175, 185, 205):
    show(f"OMEGA={om} circle", run(OMEGA=om, LOBE=1e9))

print("\n=== BARE figure-8 (no position feedback) — does it drift out? ===")
for om in (160, 175, 185, 205):
    show(f"OMEGA={om} bare", run(OMEGA=om))

print("\n=== CONFINED (reverse early when dist>R AND outward) at OMEGA=185 (~880) ===")
for rc in (500, 650, 800, 900):
    show(f"R_confine={rc}", run(OMEGA=185, R_confine=rc))

print("\n=== CONFINED sweep: can we hold the room AND keep ~880? ===")
for om in (160, 175, 185, 200):
    show(f"OMEGA={om} R=700", run(OMEGA=om, R_confine=700))
