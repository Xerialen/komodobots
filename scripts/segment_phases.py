#!/usr/bin/env python3
"""Segment a bunnyhop .cmds trace into STRAIGHT vs TURN phases and report per-phase stats.

A straight S-strafe wobbles the instantaneous heading left/right every hop but nets ~0
rotation; an end-turn rotates the heading one way and *sustains* it. So we classify by the
WINDOWED NET heading rate (deg/s over a +/-window), not the instantaneous frame-to-frame rate:
the oscillation cancels in the window, the turn does not.

Per STRAIGHT segment we report length (qu, along path), entry/exit/peak speed, and dv/dx (the
straight-line build rate the figure-8 lives on). Per TURN we report entry/exit speed (the bleed),
net angle, and speed-loss %. These are the empirical control law that seeds moveprobe mode 15 and
the Step-0 geometry sim.

.cmds columns: msec ox oy oz vx vy vz pitch yaw roll fwd side up buttons
Dependency-free (stdlib only).
"""
import argparse
import json
import math
import sys


def load_cmds(path):
    frames = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            p = line.split()
            if len(p) < 14:
                continue
            frames.append({
                "msec": float(p[0]),
                "ox": float(p[1]), "oy": float(p[2]), "oz": float(p[3]),
                "vx": float(p[4]), "vy": float(p[5]), "vz": float(p[6]),
                "yaw": float(p[8]),
                "buttons": int(p[13]),
            })
    return frames


def hspeed(fr):
    return math.hypot(fr["vx"], fr["vy"])


def build_timeline(frames, moving_speed):
    """Return per-frame arrays: cumulative time(s), hspeed, continuous(unwrapped) heading(deg),
    cumulative path distance(qu). Heading only defined on moving frames; carried otherwise."""
    n = len(frames)
    t = [0.0] * n
    spd = [0.0] * n
    head = [None] * n
    dist = [0.0] * n
    tc = 0.0
    for i, fr in enumerate(frames):
        if i > 0:
            tc += frames[i]["msec"] / 1000.0
            dx = fr["ox"] - frames[i - 1]["ox"]
            dy = fr["oy"] - frames[i - 1]["oy"]
            dist[i] = dist[i - 1] + math.hypot(dx, dy)
        t[i] = tc
        spd[i] = hspeed(fr)
        if spd[i] >= moving_speed:
            head[i] = math.degrees(math.atan2(fr["vy"], fr["vx"]))
    # unwrap heading into a continuous curve, carrying last-known across gaps
    cont = [None] * n
    last = None
    for i in range(n):
        h = head[i]
        if h is None:
            cont[i] = last
            continue
        if last is None:
            cont[i] = h
        else:
            d = h - (last % 360.0 if last is not None else h)
            # bring raw h near last
            base = last
            cand = h
            while cand - base > 180.0:
                cand -= 360.0
            while cand - base < -180.0:
                cand += 360.0
            cont[i] = cand
        last = cont[i]
    return t, spd, cont, dist


def windowed_rate(t, cont, i, half_window_s):
    """Net heading rate (deg/s) over +/- half_window_s around frame i."""
    n = len(t)
    lo = i
    while lo > 0 and t[i] - t[lo] < half_window_s:
        lo -= 1
    hi = i
    while hi < n - 1 and t[hi] - t[i] < half_window_s:
        hi += 1
    if cont[lo] is None or cont[hi] is None or t[hi] - t[lo] <= 0:
        return 0.0
    return (cont[hi] - cont[lo]) / (t[hi] - t[lo])


def classify(t, spd, cont, half_window_s, turn_rate_thresh, warm_speed):
    """Per-frame label: 'straight', 'turn', or None (cold/standstill)."""
    n = len(t)
    labels = [None] * n
    for i in range(n):
        if cont[i] is None or spd[i] < warm_speed:
            labels[i] = None
            continue
        r = abs(windowed_rate(t, cont, i, half_window_s))
        labels[i] = "turn" if r >= turn_rate_thresh else "straight"
    return labels


def merge_segments(labels, t, min_dur_s):
    """Collapse runs of equal label into segments [start,end,label]; drop/absorb sub-min-duration
    runs into the previous segment to denoise."""
    n = len(labels)
    segs = []
    i = 0
    while i < n:
        if labels[i] is None:
            i += 1
            continue
        j = i
        while j + 1 < n and labels[j + 1] == labels[i]:
            j += 1
        segs.append([i, j, labels[i]])
        i = j + 1
    # absorb short segments into the previous kept segment
    out = []
    for s in segs:
        dur = t[s[1]] - t[s[0]]
        if out and dur < min_dur_s and out[-1][2] != s[2]:
            # extend previous segment over this short blip
            out[-1][1] = s[1]
        else:
            out.append(s)
    return out


def summarize(segs, t, spd, cont, dist):
    straights, turns = [], []
    for a, b, lab in segs:
        entry, exit_ = spd[a], spd[b]
        seg_spd = spd[a:b + 1]
        rec = {
            "t0": round(t[a], 3), "t1": round(t[b], 3),
            "dur_s": round(t[b] - t[a], 3),
            "entry_spd": round(entry, 1), "exit_spd": round(exit_, 1),
            "peak_spd": round(max(seg_spd), 1), "min_spd": round(min(seg_spd), 1),
            "path_qu": round(dist[b] - dist[a], 1),
            "net_angle_deg": round((cont[b] or 0) - (cont[a] or 0), 1),
        }
        if lab == "straight":
            dx = dist[b] - dist[a]
            rec["dvdx_qu_per_qu"] = round((exit_ - entry) / dx, 4) if dx > 5 else None
            straights.append(rec)
        else:
            rec["loss_pct"] = round(100.0 * (entry - exit_) / entry, 1) if entry > 1 else None
            turns.append(rec)
    return straights, turns


def pctl(vals, p):
    vals = sorted(v for v in vals if v is not None)
    if not vals:
        return None
    return round(vals[int(p / 100.0 * (len(vals) - 1))], 2)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cmds", required=True)
    ap.add_argument("--label", default=None)
    ap.add_argument("--half-window-s", type=float, default=0.30,
                    help="+/- window for net heading rate (s). >= S-strafe hop period to cancel wobble.")
    ap.add_argument("--turn-rate-thresh", type=float, default=80.0,
                    help="windowed net deg/s above which a frame is in a TURN.")
    ap.add_argument("--warm-speed", type=float, default=500.0,
                    help="ignore frames below this hspeed (standstill / cold ramp).")
    ap.add_argument("--moving-speed", type=float, default=100.0)
    ap.add_argument("--min-dur-s", type=float, default=0.12, help="absorb segments shorter than this.")
    ap.add_argument("--out-json", default=None)
    args = ap.parse_args()

    frames = load_cmds(args.cmds)
    if len(frames) < 10:
        print("too few frames", file=sys.stderr)
        return 2
    t, spd, cont, dist = build_timeline(frames, args.moving_speed)
    labels = classify(t, spd, cont, args.half_window_s, args.turn_rate_thresh, args.warm_speed)
    segs = merge_segments(labels, t, args.min_dur_s)
    straights, turns = summarize(segs, t, spd, cont, dist)

    law = {
        "label": args.label or args.cmds,
        "frames": len(frames),
        "params": {
            "half_window_s": args.half_window_s, "turn_rate_thresh": args.turn_rate_thresh,
            "warm_speed": args.warm_speed, "min_dur_s": args.min_dur_s,
        },
        "n_straight": len(straights), "n_turn": len(turns),
        "straight": {
            "path_qu": {"p50": pctl([s["path_qu"] for s in straights], 50),
                        "p90": pctl([s["path_qu"] for s in straights], 90),
                        "max": pctl([s["path_qu"] for s in straights], 100)},
            "peak_spd": {"p50": pctl([s["peak_spd"] for s in straights], 50),
                         "max": pctl([s["peak_spd"] for s in straights], 100)},
            "entry_spd_p50": pctl([s["entry_spd"] for s in straights], 50),
            "exit_spd_p50": pctl([s["exit_spd"] for s in straights], 50),
            "dvdx_p50": pctl([s["dvdx_qu_per_qu"] for s in straights], 50),
            "dvdx_p90": pctl([s["dvdx_qu_per_qu"] for s in straights], 90),
        },
        "turn": {
            "entry_spd_p50": pctl([t_["entry_spd"] for t_ in turns], 50),
            "exit_spd_p50": pctl([t_["exit_spd"] for t_ in turns], 50),
            "loss_pct": {"p50": pctl([t_["loss_pct"] for t_ in turns], 50),
                         "p90": pctl([t_["loss_pct"] for t_ in turns], 90)},
            "net_angle_p50": pctl([abs(t_["net_angle_deg"]) for t_ in turns], 50),
            "dur_s_p50": pctl([t_["dur_s"] for t_ in turns], 50),
        },
        "segments": [{"phase": lab, **rec}
                     for (a, b, lab), rec in zip(segs, _flatten(segs, straights, turns))],
    }

    print(json.dumps({k: law[k] for k in law if k != "segments"}, indent=2))
    if args.out_json:
        with open(args.out_json, "w") as f:
            json.dump(law, f, indent=2)
        print(f"\nwrote {args.out_json}  ({law['n_straight']} straights, {law['n_turn']} turns)")
    return 0


def _flatten(segs, straights, turns):
    si = ti = 0
    out = []
    for _, _, lab in segs:
        if lab == "straight":
            out.append(straights[si]); si += 1
        else:
            out.append(turns[ti]); ti += 1
    return out


if __name__ == "__main__":
    raise SystemExit(main())
