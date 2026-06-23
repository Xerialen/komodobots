#!/usr/bin/env python3
"""Render a top-down technique clip from a .cmds bunnyhop trace.

Shows, per frame: the path, a CYAN arrow for the view (where the mouse points), an ORANGE
arrow for the velocity (where the player actually moves), speed, the strafe key, and the
look-vs-move angle. The point is to make the mouse<->movement coupling visible (a POV render
hides the velocity vector). Frames are piped as raw RGB to ffmpeg -> H.264 mp4.

Dependency-light: Pillow + an ffmpeg binary. Usage:
  python scripts/render_demo_topdown.py --cmds artifacts/replay/trick5.cmds --out out.mp4 \
      --ffmpeg "<path to ffmpeg.exe>" --fps 50
"""
import logging
import argparse
import math
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont


LOGGER = logging.getLogger(__name__)
W = H = 720
MARGIN = 70
TRAIL = 90          # frames of bright trail
VIEW_LEN = 95       # px, fixed
VEL_MAX_LEN = 150   # px at ~1100 qu/s


def load(path):
    fr = []
    with open(path) as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            p = line.split()
            if len(p) < 14:
                continue
            fr.append({
                "msec": float(p[0]), "x": float(p[1]), "y": float(p[2]),
                "vx": float(p[4]), "vy": float(p[5]),
                "yaw": float(p[8]), "side": float(p[11]),
            })
    return fr


def font(sz, bold=False):
    for name in ([r"C:\Windows\Fonts\arialbd.ttf"] if bold else [r"C:\Windows\Fonts\arial.ttf"]):
        try:
            return ImageFont.truetype(name, sz)
        except Exception:
            pass
    return ImageFont.load_default()


def arrow(draw, x, y, heading_deg, length, color, width=5):
    """heading_deg in world yaw (0=+X/east, CCW). Image Y is inverted."""
    a = math.radians(heading_deg)
    ex = x + length * math.cos(a)
    ey = y - length * math.sin(a)
    draw.line([(x, y), (ex, ey)], fill=color, width=width)
    # arrowhead
    back = math.radians(heading_deg + 180)
    for off in (28, -28):
        b = back + math.radians(off)
        draw.line([(ex, ey), (ex + 16 * math.cos(b), ey - 16 * math.sin(b))], fill=color, width=width)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cmds", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--ffmpeg", required=True)
    ap.add_argument("--fps", type=int, default=50)
    ap.add_argument("--label", default="human trick5")
    args = ap.parse_args()

    fr = load(args.cmds)
    # skip the standstill at the very start
    start = 0
    for i, f in enumerate(fr):
        if math.hypot(f["vx"], f["vy"]) > 60:
            start = max(0, i - 20)
            break
    fr = fr[start:]

    xs = [f["x"] for f in fr]
    ys = [f["y"] for f in fr]
    xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
    span = max(xmax - xmin, ymax - ymin) + 1
    scale = (H - 2 * MARGIN) / span
    cxw, cyw = (xmin + xmax) / 2, (ymin + ymax) / 2

    def to_px(wx, wy):
        px = W / 2 + (wx - cxw) * scale
        py = H / 2 - (wy - cyw) * scale  # invert Y (north up)
        return px, py

    pts = [to_px(f["x"], f["y"]) for f in fr]

    # static background: faint full path + frame + legend
    bg = Image.new("RGB", (W, H), (16, 18, 22))
    d = ImageDraw.Draw(bg)
    d.line(pts, fill=(54, 58, 66), width=2)
    d.rectangle([2, 2, W - 3, H - 3], outline=(70, 75, 85), width=2)
    f_small = font(17)
    f_big = font(30, bold=True)
    f_med = font(20, bold=True)
    d.text((14, H - 58), "cyan  = where you LOOK (mouse)", fill=(90, 220, 240), font=f_small)
    d.text((14, H - 34), "orange = where you MOVE (velocity)", fill=(245, 165, 60), font=f_small)
    d.text((W - 220, H - 30), args.label, fill=(120, 125, 135), font=f_small)

    ff = subprocess.Popen(
        [args.ffmpeg, "-y", "-f", "rawvideo", "-pixel_format", "rgb24",
         "-video_size", f"{W}x{H}", "-framerate", str(args.fps), "-i", "-",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "21", "-movflags", "+faststart",
         args.out],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    t = 0.0
    for i, f in enumerate(fr):
        t += f["msec"] / 1000.0
        im = bg.copy()
        dr = ImageDraw.Draw(im)
        # bright trail
        lo = max(0, i - TRAIL)
        if i - lo >= 1:
            dr.line(pts[lo:i + 1], fill=(120, 130, 245), width=4)
        x, y = pts[i]
        spd = math.hypot(f["vx"], f["vy"])
        velh = math.degrees(math.atan2(f["vy"], f["vx"])) if spd > 20 else f["yaw"]
        # velocity arrow (orange), then view arrow (cyan) on top
        arrow(dr, x, y, velh, 40 + VEL_MAX_LEN * min(spd, 1100) / 1100, (245, 165, 60), 6)
        arrow(dr, x, y, f["yaw"], VIEW_LEN, (90, 220, 240), 5)
        dr.ellipse([x - 6, y - 6, x + 6, y + 6], fill=(255, 255, 255))
        # telemetry
        lvm = f["yaw"] - velh
        while lvm > 180:
            lvm -= 360
        while lvm < -180:
            lvm += 360
        key = "RIGHT →" if f["side"] > 50 else ("← LEFT" if f["side"] < -50 else "–")
        dr.text((16, 14), f"{spd:4.0f} qu/s", fill=(255, 255, 255), font=f_big)
        dr.text((16, 54), f"t = {t:4.1f}s", fill=(200, 205, 215), font=f_med)
        dr.text((16, 80), f"strafe: {key}", fill=(245, 165, 60), font=f_med)
        dr.text((16, 106), f"look vs move: {lvm:+.0f}°", fill=(90, 220, 240), font=f_med)
        ff.stdin.write(im.tobytes())

    ff.stdin.close()
    err = ff.stderr.read().decode(errors="ignore")
    rc = ff.wait()
    if rc != 0:
        print(err[-1500:], file=sys.stderr)
        return rc
    print(f"wrote {args.out}  ({len(fr)} frames @ {args.fps}fps)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
