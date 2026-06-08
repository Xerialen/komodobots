#!/usr/bin/env python3
"""Faithful-enough QW pmove sim to QUICKLY validate the bunnyhop theories offline.

Physics from mvdsv/src/pmove.c (the version audited this session):
  - PM_AirAccelerate: wishspd = min(wishspeed, 30); addspeed = wishspd - (vel.wishdir);
    accelspeed = min(accel*wishspeed*ft, addspeed); vel += accelspeed*wishdir.
    With accel=10, wishspeed=320, ft=0.013 -> accelspeed=41.6 >> addspeed(<=30), so each AIR
    frame gains exactly (30 - vel.wishdir) along wishdir while vel.wishdir < 30. THE 30-CAP.
  - Ground: PM_Friction then PM_Accelerate (cap maxspeed). Jump sets vz=+270, leaves ground.
  - gravity 800, friction 4, stopspeed 100, maxspeed 320.
Flat-floor model: trick5 is airborne ~97%, and horizontal air-accel depends only on
(vel_xy, wishdir, airborne) -- independent of map geometry -- so a flat floor reproduces the
HORIZONTAL speed evolution (what every theory is about) even though it won't match z exactly.

Two drivers:
  replay  -- feed trick5's EXACT usercmds (yaw,fwd,side,jump). TRUST CHECK: must reproduce ~880/1088.
  policy  -- the v2 SteerSign figure-8 (sign-corrected). THEORY SWEEP.
"""
import json, math, sys

# ---- movevars (QW defaults) ----
MV = dict(maxspeed=320.0, accel=10.0, friction=4.0, stopspeed=100.0,
          gravity=800.0, jumpspeed=270.0, aircap=30.0)

def load_cmds(path):
    fr = []
    with open(path) as f:
        for line in f:
            if line.startswith("#") or not line.strip(): continue
            p = line.split()
            if len(p) < 14: continue
            fr.append(dict(msec=float(p[0]), ox=float(p[1]), oy=float(p[2]), oz=float(p[3]),
                           vx=float(p[4]), vy=float(p[5]), vz=float(p[6]),
                           yaw=float(p[8]), fwd=float(p[10]), side=float(p[11]),
                           up=float(p[12]), jump=1 if (int(float(p[13])) & 2) else 0))
    return fr

def fwd_right(yaw_deg):
    a = math.radians(yaw_deg)
    f = (math.cos(a), math.sin(a))      # forward (x,y) for yaw (0=+x, CCW)
    r = (math.sin(a), -math.cos(a))     # right = forward rotated -90 (QW: +side strafes right)
    return f, r

def pmove_step(st, yaw, fmove, smove, jump, ft, mv=MV):
    vx, vy, vz, z = st["vx"], st["vy"], st["vz"], st["z"]
    onground = (z <= 0.001 and vz <= 0.0)
    # jump
    if onground and jump:
        vz = mv["jumpspeed"]; onground = False
    # friction (ground only)
    if onground:
        sp = math.hypot(vx, vy)
        if sp > 0:
            ctrl = sp if sp > mv["stopspeed"] else mv["stopspeed"]
            nsp = sp - ctrl * mv["friction"] * ft
            if nsp < 0: nsp = 0.0
            vx *= nsp / sp; vy *= nsp / sp
    # wishvel from view + move
    f, r = fwd_right(yaw)
    wx = f[0]*fmove + r[0]*smove
    wy = f[1]*fmove + r[1]*smove
    wishspeed = math.hypot(wx, wy)
    if wishspeed > 0:
        wdx, wdy = wx/wishspeed, wy/wishspeed
    else:
        wdx = wdy = 0.0
    capped = wishspeed
    if capped > mv["maxspeed"]: capped = mv["maxspeed"]
    # accelerate
    if onground:
        cur = vx*wdx + vy*wdy
        add = capped - cur
        if add > 0:
            acc = mv["accel"] * capped * ft
            if acc > add: acc = add
            vx += acc*wdx; vy += acc*wdy
    else:
        cur = vx*wdx + vy*wdy
        wishspd = capped if capped < mv["aircap"] else mv["aircap"]
        add = wishspd - cur
        if add > 0:
            acc = mv["accel"] * capped * ft
            if acc > add: acc = add
            vx += acc*wdx; vy += acc*wdy
        vz -= mv["gravity"] * ft
    # integrate
    z += vz * ft
    if z <= 0.0:
        z = 0.0
        if vz < 0: vz = 0.0
    st["vx"], st["vy"], st["vz"], st["z"] = vx, vy, vz, z
    return st

def air_step(st, yaw, fmove, smove, ft, mv=MV):
    """Pure horizontal air-accel (no ground, no friction, no gravity) -- isolates the
    air-accel + wishdir physics the theories depend on."""
    vx, vy = st["vx"], st["vy"]
    f, r = fwd_right(yaw)
    wx = f[0]*fmove + r[0]*smove; wy = f[1]*fmove + r[1]*smove
    wishspeed = math.hypot(wx, wy)
    if wishspeed == 0: return st
    wdx, wdy = wx/wishspeed, wy/wishspeed
    capped = min(wishspeed, mv["maxspeed"])
    cur = vx*wdx + vy*wdy
    wishspd = min(capped, mv["aircap"])
    add = wishspd - cur
    if add > 0:
        acc = min(mv["accel"]*capped*ft, add)
        vx += acc*wdx; vy += acc*wdy
    st["vx"], st["vy"] = vx, vy
    return st

def run_replay_air(frames):
    # seed at the first frame where the human is clearly cruising, from his OWN velocity
    i0 = next(i for i,fr in enumerate(frames) if math.hypot(fr["vx"],fr["vy"]) > 400)
    st = dict(vx=frames[i0]["vx"], vy=frames[i0]["vy"])
    sim, rec = [], []
    for fr in frames[i0:]:
        ft = fr["msec"]/1000.0
        air_step(st, fr["yaw"], fr["fwd"], fr["side"], ft)
        sim.append(math.hypot(st["vx"],st["vy"])); rec.append(math.hypot(fr["vx"],fr["vy"]))
    return sim, rec

def hspeed(st): return math.hypot(st["vx"], st["vy"])

def pctl(v, p):
    v = sorted(v); return v[min(len(v)-1, int(p/100*(len(v)-1)))] if v else 0

def run_replay(frames):
    st = dict(vx=0.0, vy=0.0, vz=0.0, z=0.0)
    sim, rec = [], []
    for fr in frames:
        ft = fr["msec"]/1000.0
        pmove_step(st, fr["yaw"], fr["fwd"], fr["side"], fr["jump"], ft)
        sim.append(hspeed(st)); rec.append(math.hypot(fr["vx"], fr["vy"]))
    return sim, rec

def main():
    frames = load_cmds(r"C:\Users\benya\projects\komodobots\artifacts\replay\trick5.cmds")
    sim, rec = run_replay(frames)
    # compare over the moving window (skip the standstill launch frames)
    mv_idx = [i for i in range(len(rec)) if rec[i] > 100]
    s = [sim[i] for i in mv_idx]; r = [rec[i] for i in mv_idx]
    # correlation
    n = len(s); ms = sum(s)/n; mr = sum(r)/n
    cov = sum((s[i]-ms)*(r[i]-mr) for i in range(n))
    ds = math.sqrt(sum((x-ms)**2 for x in s)); dr = math.sqrt(sum((x-mr)**2 for x in r))
    corr = cov/(ds*dr) if ds*dr else 0
    print("=== REPLAY TRUST CHECK (trick5 usercmds -> sim) ===")
    print(f"frames moving: {n}")
    print(f"SIM  median={pctl(s,50):.0f}  p90={pctl(s,90):.0f}  peak={max(s):.0f}")
    print(f"REC  median={pctl(r,50):.0f}  p90={pctl(r,90):.0f}  peak={max(r):.0f}   (target 880/1024/1088)")
    print(f"per-frame corr(sim,rec) = {corr:.3f}")
    rel = abs(pctl(s,50)-pctl(r,50))/pctl(r,50)*100
    print(f"median rel-err = {rel:.1f}%   -> {'TRUSTED' if rel<8 and corr>0.7 else 'NEEDS WORK'}")

    # --- pure-air diagnostic: isolate horizontal air-accel from the ground/z model ---
    sa, ra = run_replay_air(frames)
    n2 = len(sa); ma = sum(sa)/n2; mra = sum(ra)/n2
    cov2 = sum((sa[i]-ma)*(ra[i]-mra) for i in range(n2))
    d2s = math.sqrt(sum((x-ma)**2 for x in sa)); d2r = math.sqrt(sum((x-mra)**2 for x in ra))
    corr2 = cov2/(d2s*d2r) if d2s*d2r else 0
    print("\n=== PURE-AIR DIAGNOSTIC (seed from human velocity, air-accel only) ===")
    print(f"SIM  median={pctl(sa,50):.0f}  p90={pctl(sa,90):.0f}  peak={max(sa):.0f}")
    print(f"REC  median={pctl(ra,50):.0f}  p90={pctl(ra,90):.0f}  peak={max(ra):.0f}")
    print(f"per-frame corr = {corr2:.3f}   median rel-err = {abs(pctl(sa,50)-pctl(ra,50))/pctl(ra,50)*100:.1f}%")
    print(f"-> if this TRACKS, the air-accel+wishdir physics is faithful and the gap was the ground/z model.")

if __name__ == "__main__":
    main()
