#!/usr/bin/env python3
"""Detect repeated ATTEMPTS at the same jump in a .cmds: segment the demo by
return-to-start (near the frame-0 origin and slow), and summarize each attempt's
run-up + jump + outcome. Stdlib only.
cols: msec ox oy oz vx vy vz pitch yaw roll fwd side up buttons (fps77)"""
import logging
import math, sys


LOGGER = logging.getLogger(__name__)
JUMP = 2

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
    rows = load(sys.argv[1])
    n = len(rows)
    ox0, oy0, oz0 = rows[0][1], rows[0][2], rows[0][3]
    t = 0.0; T=[0.0]*n; HS=[0.0]*n; D=[0.0]*n; OZ=[0.0]*n; J=[0]*n
    for i, r in enumerate(rows):
        if i>0: t += r[0]/1000.0
        T[i]=t
        HS[i]=math.hypot(r[4], r[5])
        D[i]=math.hypot(r[1]-ox0, r[2]-oy0)
        OZ[i]=r[3]
        J[i]=1 if (int(r[13]) & JUMP) else 0
    # "parked" = near start and slow
    parked = [1 if (D[i] < 220 and HS[i] < 130) else 0 for i in range(n)]
    # attempts = maximal runs that contain a jump press, bounded by parked stretches
    edges = [k for k in range(1,n) if J[k] and not J[k-1]]
    # group jump edges that belong to the same airborne excursion: if two edges have
    # no "parked" frame between them, they're the same attempt (double-tap / multi jump)
    attempts = []
    i = 0
    # walk: find start (leave parked), capture until return to parked for >~0.15s
    in_run = False; run_start = 0
    park_run = 0
    for k in range(n):
        if not in_run:
            if not parked[k] and HS[k] > 140:
                in_run = True; run_start = k; park_run = 0
        else:
            if parked[k]:
                park_run += 1
                if park_run >= 6:  # ~0.08s parked => attempt over
                    attempts.append((run_start, k - park_run + 1))
                    in_run = False
            else:
                park_run = 0
    if in_run:
        attempts.append((run_start, n-1))

    print(f"start origin = ({ox0:.0f},{oy0:.0f},{oz0:.0f})   total {T[-1]:.1f}s, {n} frames")
    print(f"detected {len(attempts)} run-up attempts (return-to-start segmentation)\n")
    print(" att  t0     t_jump  runup_s  spd@jump  peak_runup  jumps  max_dist  far_oz  end:back?")
    for idx,(a,b) in enumerate(attempts):
        seg = list(range(a,b+1))
        js = [k for k in seg if J[k] and (k==0 or not J[k-1])]
        tj = T[js[0]] if js else None
        spd_j = HS[js[0]] if js else None
        peak = max(HS[k] for k in seg)
        maxd = max(D[k] for k in seg)
        kfar = max(seg, key=lambda k: D[k])
        far_oz = OZ[kfar]
        back = parked[b]
        print(f"{idx+1:3d} {T[a]:5.2f} {('%6.2f'%tj) if tj else '   -  '} "
              f"{T[a if not js else a]:.0f}{'':0s}"
              f"  {(T[js[0]]-T[a]) if js else 0:5.2f}  "
              f"{('%7.0f'%spd_j) if spd_j else '   -   '}  {peak:9.0f}  {len(js):4d}  "
              f"{maxd:7.0f}  {far_oz:6.0f}  {'yes' if back else 'no'}")

    # also: where do attempts END (the far point) — same target each time?
    print("\n--- jump launch states (the moment +jump is first pressed each attempt) ---")
    print(" att  t_jump   ox     oy     oz   |  spd   vhead  view_yaw  fwd side")
    for idx,(a,b) in enumerate(attempts):
        js = [k for k in range(a,b+1) if J[k] and not J[k-1]]
        if not js: continue
        k = js[0]; r = rows[k]
        vhead = math.degrees(math.atan2(r[5], r[4]))
        print(f"{idx+1:3d} {T[k]:6.2f}  {r[1]:6.0f} {r[2]:6.0f} {r[3]:5.0f}  | {HS[k]:5.0f} "
              f"{vhead:6.1f}  {r[8]:7.1f}  {int(r[10]):4d} {int(r[11]):4d}")

if __name__ == "__main__":
    main()
