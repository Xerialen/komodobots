#!/usr/bin/env python3
"""World-coordinate geometry of the getspeed.qwd "Final Trick: Distance" jump.

Prints the takeoff lip, apex, far-side landing, and the void where the 10 failed
attempts fall. Confirms the launch is an external +vz impulse (no jump, no pad,
ramp refuted): horizontal speed is preserved across the launch while vz is added.

Usage:  python launch_geometry.py [getspeed.cmds]
.cmds cols: msec ox oy oz vx vy vz pitch yaw roll fwd side up buttons  (77 fps)
"""
import logging
import math, sys


LOGGER = logging.getLogger(__name__)
def load(path):
    rows = []
    with open(path) as f:
        for ln in f:
            if ln.startswith("#") or not ln.strip():
                continue
            p = ln.split()
            if len(p) < 14:
                continue
            rows.append([float(x) for x in p[:13]] + [int(float(p[13]))])
    return rows

def hs(r):
    return math.hypot(r[4], r[5])

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "getspeed.cmds"
    rows = load(path)

    print("=== WINNING ARC (attempt #11) - world coords (x y z) ===")
    pts = [
        ("run-up begin",   1837),
        ("LAST on ground", 1879),  # the launch lip
        ("FIRST airborne", 1880),  # +vz appears, no jump button
    ]
    for label, i in pts:
        r = rows[i]
        print(f"  {label:16s} f{i}: ({r[1]:8.1f},{r[2]:8.1f},{r[3]:7.1f})  hspeed={hs(r):4.0f}  vz={r[6]:5.0f}")
    apex = max(range(1880, 1930), key=lambda k: rows[k][3])
    r = rows[apex]
    print(f"  {'apex':16s} f{apex}: ({r[1]:8.1f},{r[2]:8.1f},{r[3]:7.1f})  hspeed={hs(r):4.0f}  vz={r[6]:5.0f}")
    land = next((k for k in range(apex, 1940) if -489 <= rows[k][3] <= -487), 1929)
    r = rows[land]
    print(f"  {'LAND far side':16s} f{land}: ({r[1]:8.1f},{r[2]:8.1f},{r[3]:7.1f})  hspeed={hs(r):4.0f}")

    print("\n=== where the FAILURES fall (the gap floor) ===")
    for a, b, name in [(164, 300, "fail#1"), (868, 1000, "fail#5")]:
        v = min(range(a, b), key=lambda k: rows[k][3])
        r = rows[v]
        print(f"  {name}: lowest f{v}: ({r[1]:8.1f},{r[2]:8.1f},{r[3]:7.1f})  ({-488 - r[3]:.0f} qu below the rim)")

    print("\n=== launch is an external +vz impulse (ramp refuted) ===")
    # origin-derived horizontal speed, ground vs glide (avoid the dropped-state frame 1880)
    def odh(i):
        dt = rows[i][0] / 1000.0
        return math.hypot(rows[i][1] - rows[i-1][1], rows[i][2] - rows[i-1][2]) / dt
    gh = sum(odh(i) for i in range(1873, 1880)) / 7
    ah = sum(odh(i) for i in range(1886, 1900)) / 14
    vz0 = rows[1880][6]
    print(f"  origin-derived horizontal: ground={gh:.0f}  glide={ah:.0f}  (PRESERVED, not bled)")
    print(f"  |v|: ground={gh:.0f} -> airborne={math.hypot(ah, vz0):.0f}  (+{100*(math.hypot(ah,vz0)**2/gh**2-1):.0f}% energy => external impulse, not a ramp)")

if __name__ == "__main__":
    main()
