#!/usr/bin/env python3
"""Analyze a .cmds (msec ox oy oz vx vy vz pitch yaw roll fwd side up buttons, fps77)
from the POV of INPUT COMMANDS vs SPEED, with focus on the LAUNCH (standing start ->
ground accel -> first jump -> first airborne hops). Stdlib only.

steering angle = angle between WISHDIR (from fwd/side relative to view) and velocity.
  ~0  on the ground = straight accel to maxspeed.
  large in the air = the air-strafe lever (the 30-cap qu/s air cap depends on it).
"""
import logging
import math, sys


LOGGER = logging.getLogger(__name__)
JUMP = 2  # buttons & 2

def angle_vectors(pitch, yaw, roll):
    ry = math.radians(yaw); rp = math.radians(pitch); rr = math.radians(roll)
    sy, cy = math.sin(ry), math.cos(ry)
    sp, cp = math.sin(rp), math.cos(rp)
    sr, cr = math.sin(rr), math.cos(rr)
    fwd = (cp*cy, cp*sy, -sp)
    right = (-sr*sp*cy + -cr*-sy, -sr*sp*sy + -cr*cy, -sr*cp)
    return fwd, right

def wrap180(d):
    while d > 180: d -= 360
    while d < -180: d += 360
    return d

def load(path):
    rows = []
    with open(path) as f:
        for ln in f:
            if ln.startswith("#") or not ln.strip(): continue
            p = ln.split()
            if len(p) < 14: continue
            rows.append([float(x) for x in p[:13]] + [int(float(p[13]))])
    return rows

def main():
    path = sys.argv[1]
    rows = load(path)
    n = len(rows)
    t = 0.0
    F = []
    for i, r in enumerate(rows):
        msec, ox, oy, oz, vx, vy, vz, pitch, yaw, roll, fwd, side, up, btn = r
        if i > 0: t += rows[i][0] / 1000.0
        hs = math.hypot(vx, vy)
        vhead = math.degrees(math.atan2(vy, vx)) if hs > 1 else None
        # wishdir from fwd/side relative to view
        fv, rv = angle_vectors(pitch, yaw, roll)
        wx = fwd*fv[0] + side*rv[0]
        wy = fwd*fv[1] + side*rv[1]
        whead = math.degrees(math.atan2(wy, wx)) if (abs(wx)+abs(wy) > 1) else None
        steer = wrap180(whead - vhead) if (whead is not None and vhead is not None) else None
        F.append(dict(i=i, t=t, hs=hs, vx=vx, vy=vy, vz=vz, oz=oz, yaw=yaw, pitch=pitch,
                      vhead=vhead, whead=whead, steer=steer,
                      fwd=int(fwd), side=int(side), up=int(up),
                      jump=1 if (btn & JUMP) else 0, btn=btn))

    # jump rising edges
    edges = [k for k in range(1, n) if F[k]["jump"] == 1 and F[k-1]["jump"] == 0]
    # airborne: |vz|>10 OR off the start floor (oz0). Start floor:
    oz0 = F[0]["oz"]
    for f in F:
        f["air"] = 1 if (abs(f["vz"]) > 10 or f["oz"] > oz0 + 8) else 0
    # first movement
    mv = next((f for f in F if f["hs"] > 5 or f["side"] != 0 or f["fwd"] != 0 or f["jump"]), F[0])

    hs_all = [f["hs"] for f in F]
    def pctl(v, p):
        s = sorted(v); return s[min(len(s)-1, int(p/100*(len(s)-1)))]

    print("="*78)
    print(f"FILE {path.split(chr(92))[-1]}   frames={n}  dur={F[-1]['t']:.2f}s  fps~77")
    print(f"hspeed  median={pctl(hs_all,50):.0f}  p90={pctl(hs_all,90):.0f}  peak={max(hs_all):.0f} qu/s")
    print(f"first input/move at frame {mv['i']} (t={mv['t']:.2f}s)")
    print(f"jump presses: {len(edges)}  at frames {edges[:20]}{' ...' if len(edges)>20 else ''}")
    print("="*78)

    # ---- LAUNCH detail: standstill -> ground accel -> first jump -> first hops ----
    first_jump = edges[0] if edges else n
    print("\n--- LAUNCH (standstill -> first jump -> early hops) ---")
    print(" frame   t     hs   vz   |  view_yaw vhead  steer | fwd  side up J air")
    # show: every frame from first-move-2 up through ground accel until first jump,
    # then every frame for ~6 hops. Decimate the long stretches lightly.
    start = max(0, mv['i'] - 1)
    # window: through 6th jump edge or +320 frames
    end = (edges[min(5, len(edges)-1)] + 30) if edges else min(n, start + 320)
    prev_print = -99
    for k in range(start, min(end, n)):
        f = F[k]
        is_edge = (k in edges) or (k+1 in edges) or (k-1 in edges)
        is_land = k > 0 and F[k]["air"] == 0 and F[k-1]["air"] == 1
        # print densely near edges/landings & first 40 frames of accel; else every 3rd
        dense = is_edge or is_land or (k - start < 36) or (k - prev_print >= 3)
        if not dense: continue
        prev_print = k
        vh = f"{f['vhead']:6.1f}" if f['vhead'] is not None else "   -- "
        st = f"{f['steer']:5.0f}" if f['steer'] is not None else "  -- "
        mark = ""
        if k in edges: mark = " <== JUMP"
        elif is_land: mark = " <-- land"
        print(f"{f['i']:5d} {f['t']:5.2f} {f['hs']:5.0f} {f['vz']:5.0f} |  {f['yaw']:7.1f} {vh} {st}  |"
              f" {f['fwd']:3d} {f['side']:5d} {f['up']:3d} {f['jump']} {f['air']}{mark}")

    # ---- per-hop recipe ----
    print("\n--- PER-HOP (each jump press -> until next press) ---")
    print(" hop  t_jump  spd@jump  peak_air  spd@land  air_s  side  vyaw_turn  steer(air med)")
    bounds = edges + [n]
    for h in range(len(edges)):
        a, b = edges[h], bounds[h+1]
        seg = F[a:b]
        air = [f for f in seg if f["air"] == 1]
        spd_jump = F[a]["hs"]
        peak_air = max((f["hs"] for f in air), default=spd_jump)
        # land speed = last airborne frame's speed (just before touching down) or seg end
        spd_land = (air[-1]["hs"] if air else seg[-1]["hs"])
        air_s = (air[-1]["t"] - air[0]["t"]) if air else 0.0
        side_sgn = F[a + min(2, len(seg)-1)]["side"]
        yaw_turn = wrap180(F[b-1]["yaw"] - F[a]["yaw"])
        steers = sorted(f["steer"] for f in air if f["steer"] is not None)
        steer_med = steers[len(steers)//2] if steers else float('nan')
        print(f"{h+1:4d} {F[a]['t']:6.2f} {spd_jump:8.0f} {peak_air:9.0f} {spd_land:9.0f}"
              f" {air_s:6.2f} {side_sgn:5d} {yaw_turn:9.1f} {steer_med:10.0f}")

    # ---- ground-accel summary (pre-first-jump) ----
    if edges:
        g = F[mv['i']:first_jump]
        if g:
            print(f"\n--- GROUND-ACCEL (frame {mv['i']}..{first_jump}, before first jump) ---")
            print(f"  duration {g[-1]['t']-g[0]['t']:.2f}s, "
                  f"speed {g[0]['hs']:.0f} -> {g[-1]['hs']:.0f} (peak {max(x['hs'] for x in g):.0f})")
            sides = [x['side'] for x in g if x['side'] != 0]
            fwds = [x['fwd'] for x in g if x['fwd'] != 0]
            yaws = [x['yaw'] for x in g]
            print(f"  inputs: side typical={sorted(sides)[len(sides)//2] if sides else 0}, "
                  f"fwd nonzero frames={len(fwds)}, "
                  f"view_yaw range [{min(yaws):.1f}..{max(yaws):.1f}] (turn {wrap180(yaws[-1]-yaws[0]):.1f})")

if __name__ == "__main__":
    main()
