#!/usr/bin/env python3
"""ASCII occupancy plot of the XY trajectory in a replay .cmds file.

Shows the real path SHAPE (straight runway? tight circle? confined loops?) at a
glance, with no plotting dependencies. Denser glyphs = more time spent in a cell.
S = start, E = end. Use to sanity-check a fingerprint's path_shape numbers and to
compare a bot run's trajectory against the human's.

    python scripts/plot_path_ascii.py --cmds artifacts/replay/trick5.cmds
"""
from __future__ import annotations

import logging
import argparse
from pathlib import Path



LOGGER = logging.getLogger(__name__)
def _load_cmds(path: Path):
    pts = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        p = line.split()
        if len(p) < 3:
            continue
        pts.append((float(p[1]), float(p[2])))
    return pts


def _load_events(path: Path, player: int):
    """kind-5 player-origin events from a lab run's events.txt (one JSON per line)."""
    import json

    pts = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("kind") == 5 and e["data"].get("PlayerNum") == player:
            o = e["data"]["Origin"]
            pts.append((o[0], o[1]))
    return pts


def plot(path: Path, w: int = 56, h: int = 26, events_player: int | None = None) -> str:
    pts = _load_events(path, events_player) if events_player is not None else _load_cmds(path)
    if len(pts) < 2:
        return "(insufficient points)"
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    dx = (x1 - x0) or 1.0
    dy = (y1 - y0) or 1.0
    cnt = [[0] * w for _ in range(h)]

    def cell(x, y):
        return int((x - x0) / dx * (w - 1)), int((y - y0) / dy * (h - 1))

    for x, y in pts:
        cx, cy = cell(x, y)
        cnt[cy][cx] += 1
    mx = max(max(r) for r in cnt) or 1
    order = " .:-=+*#%@"
    grid = [[" "] * w for _ in range(h)]
    for cy in range(h):
        for cx in range(w):
            c = cnt[cy][cx]
            if c:
                grid[cy][cx] = order[min(len(order) - 1, int(c / mx * (len(order) - 1)) + 1)]
    sx, sy = cell(*pts[0])
    ex, ey = cell(*pts[-1])
    grid[sy][sx] = "S"
    grid[ey][ex] = "E"
    head = f"XY path  box {x1 - x0:.0f} x {y1 - y0:.0f} qu  ({len(pts)} frames)  S=start E=end"
    body = "\n".join("  " + "".join(r) for r in reversed(grid))
    return head + "\n" + body


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cmds", type=Path, help="A replay .cmds file (human input trace).")
    ap.add_argument("--events", type=Path, help="A lab run's events.txt (bot run).")
    ap.add_argument("--player", type=int, default=1, help="PlayerNum for --events (bot=1).")
    ap.add_argument("--width", type=int, default=56)
    ap.add_argument("--height", type=int, default=26)
    args = ap.parse_args()
    if args.events:
        print(plot(args.events, args.width, args.height, events_player=args.player))
    elif args.cmds:
        print(plot(args.cmds, args.width, args.height))
    else:
        ap.error("provide --cmds or --events")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
