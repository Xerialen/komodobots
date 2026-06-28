#!/usr/bin/env python3
"""Build a labelled contact sheet from demoshots t<sec>.jpg frames, for reading an event by eye.

Runs on the box that HAS Pillow (the GPU box / winnacle Python) — aws-dev has none, so the driver
builds the sheet remotely and pulls the JPG. Each cell is captioned with its demo-second so you can
map a frame straight back to the timeline.

    python contact_sheet.py <frames_dir> <lo_sec> <hi_sec> [cols=5] [cell_width=320]
        -> writes <frames_dir>/sheet_<lo>-<hi>.jpg
"""
import os
import sys
from PIL import Image, ImageDraw


def build(frames_dir, lo, hi, cols=5, w=320):
    imgs = []
    for s in range(lo, hi + 1):
        p = os.path.join(frames_dir, "t%06d.jpg" % s)
        if not os.path.exists(p):
            continue
        im = Image.open(p).convert("RGB")
        im = im.resize((w, int(im.height * w / im.width)))
        dr = ImageDraw.Draw(im)
        dr.rectangle([0, 0, 78, 20], fill="black")
        dr.text((4, 4), "t%d" % s, fill="yellow")
        imgs.append(im)
    if not imgs:
        raise SystemExit("no t<sec>.jpg frames in [%d,%d] under %s" % (lo, hi, frames_dir))
    rows = (len(imgs) + cols - 1) // cols
    cw, ch = imgs[0].size
    sheet = Image.new("RGB", (cols * cw, rows * ch), "gray")
    for i, im in enumerate(imgs):
        sheet.paste(im, ((i % cols) * cw, (i // cols) * ch))
    out = os.path.join(frames_dir, "sheet_%d-%d.jpg" % (lo, hi))
    sheet.save(out, quality=85)
    print("WROTE", out, sheet.size)
    return out


if __name__ == "__main__":
    if len(sys.argv) < 4:
        raise SystemExit("usage: contact_sheet.py <frames_dir> <lo_sec> <hi_sec> [cols] [cell_width]")
    d = sys.argv[1]
    lo, hi = int(sys.argv[2]), int(sys.argv[3])
    cols = int(sys.argv[4]) if len(sys.argv) > 4 else 5
    w = int(sys.argv[5]) if len(sys.argv) > 5 else 320
    build(d, lo, hi, cols, w)
