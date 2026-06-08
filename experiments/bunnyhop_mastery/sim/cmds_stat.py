#!/usr/bin/env python3
"""Cheap classifier over the .cmds corpus: frames, duration, peak/median hspeed,
net heading rotation (turns), jump fraction. Identifies figure-8 human trick runs."""
import glob, math, os

COLS = "msec ox oy oz vx vy vz pitch yaw roll fwd side up buttons".split()

def load(path):
    fr = []
    with open(path) as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            p = line.split()
            if len(p) < 14:
                continue
            fr.append([float(x) for x in p[:13]] + [int(float(p[13]))])
    return fr

def stat(path):
    fr = load(path)
    if len(fr) < 5:
        return None
    dur = sum(f[0] for f in fr) / 1000.0
    hs = [math.hypot(f[4], f[5]) for f in fr]
    peak = max(hs)
    med = sorted(hs)[len(hs)//2]
    # net heading rotation: unwrap velocity heading over moving frames
    cont, last, total = None, None, 0.0
    for f in fr:
        s = math.hypot(f[4], f[5])
        if s < 100:
            continue
        h = math.degrees(math.atan2(f[5], f[4]))
        if last is not None:
            d = h - last
            while d > 180: d -= 360
            while d < -180: d += 360
            total += d
        last = h
    turns = abs(total) / 360.0
    jump = sum(1 for f in fr if f[13] & 2) / len(fr)
    # bbox
    xs = [f[1] for f in fr]; ys = [f[2] for f in fr]
    bbox = max(max(xs)-min(xs), max(ys)-min(ys))
    return dict(frames=len(fr), dur=dur, peak=peak, med=med, turns=turns,
               jump_frac=jump, bbox=bbox)

base = r"C:\Users\benya\projects\komodobots\artifacts\replay"
print(f"{'file':24} {'frm':>5} {'dur':>5} {'peak':>5} {'med':>4} {'turns':>5} {'jump%':>5} {'bbox':>5}")
for path in sorted(glob.glob(os.path.join(base, "*.cmds"))):
    s = stat(path)
    if not s:
        continue
    name = os.path.basename(path)
    print(f"{name:24} {s['frames']:5d} {s['dur']:5.1f} {s['peak']:5.0f} "
          f"{s['med']:4.0f} {s['turns']:5.2f} {100*s['jump_frac']:5.1f} {s['bbox']:5.0f}")
