#!/usr/bin/env python3
"""Generate a minimal KTX frogbot route file (.bot) from a replay .cmds trajectory.

Frogbots only spawn on a "supported" map: KTX's LoadMap() sets map_supported=true
only when LoadBotRoutingFromFile() finds a readable bots/maps/<map>.bot. Maps like
trick.bsp ship none, so `addbot` is a no-op there.

For the acceleration harness the bot is driven by moveprobe (not by the route graph),
so the .bot only has to exist and load -- it does NOT need full map coverage. We build
it straight from a human demo's recorded trajectory (.cmds origins are, by definition,
walkable points the player passed through), decimated to a chain of markers linked
forward/back. Output directives match KTX's own writer (marker_load.c / bot_commands.c):

    CreateMarker x y z          (1-based marker order)
    SetZone marker zone
    SetMarkerPath src path# next

No server, no in-game waypoint editor required.
"""

from __future__ import annotations

import logging
import argparse
import math
import sys
from pathlib import Path
from typing import Iterable



LOGGER = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MAX_MARKERS = 180


def read_origins(cmds_path: Path) -> list[tuple[float, float, float]]:
    origins = []
    for line in cmds_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        origins.append((float(parts[1]), float(parts[2]), float(parts[3])))
    return origins


def decimate(origins: list[tuple[float, float, float]], spacing: float,
             max_markers: int) -> list[tuple[float, float, float]]:
    """Keep a marker each time we have travelled `spacing` qu from the last kept one.

    Auto-grows the spacing if the marker count would exceed max_markers, so the file
    stays within the engine's marker array regardless of demo length.
    """
    if not origins:
        return []
    if spacing <= 0:
        raise ValueError(f"spacing must be positive, got {spacing}")
    if max_markers < 1:
        raise ValueError(f"max_markers must be >= 1, got {max_markers}")
    while True:
        kept = [origins[0]]
        for o in origins[1:]:
            if math.dist(o, kept[-1]) >= spacing:
                kept.append(o)
        if len(kept) <= max_markers:
            return kept
        spacing *= 1.5


def render_bot_file(markers: list[tuple[float, float, float]], source: str) -> str:
    lines = [
        f"// komodobots auto-generated route from {source}",
        "// Spawn-enabler only: frogbots are driven by moveprobe, not this graph.",
    ]
    for x, y, z in markers:
        lines.append(f"CreateMarker {int(round(x))} {int(round(y))} {int(round(z))}")
    for i in range(1, len(markers) + 1):
        lines.append(f"SetZone {i} 1")
    # Linear bidirectional chain: path slot 0 -> next, slot 1 -> previous.
    for i in range(1, len(markers) + 1):
        if i < len(markers):
            lines.append(f"SetMarkerPath {i} 0 {i + 1}")
        if i > 1:
            lines.append(f"SetMarkerPath {i} 1 {i - 1}")
    return "\n".join(lines) + "\n"


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate a KTX .bot route from a replay .cmds.")
    p.add_argument("--cmds", type=Path, required=True, help="Input replay .cmds file.")
    p.add_argument("--output", type=Path, required=True, help="Output .bot file.")
    p.add_argument("--spacing", type=float, default=160.0, help="Marker spacing in qu. Default 160.")
    p.add_argument("--max-markers", type=int, default=DEFAULT_MAX_MARKERS, help="Marker cap. Default 180.")
    return p.parse_args(list(argv))


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    origins = read_origins(args.cmds)
    if len(origins) < 2:
        print(f"Too few origins in {args.cmds}", file=sys.stderr)
        return 2
    try:
        markers = decimate(origins, args.spacing, args.max_markers)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_bot_file(markers, args.cmds.name), encoding="utf-8")
    xs = [m[0] for m in markers]
    ys = [m[1] for m in markers]
    zs = [m[2] for m in markers]
    print(f"Wrote {args.output} with {len(markers)} markers (from {len(origins)} origins)")
    print(f"  bounds x[{min(xs):.0f},{max(xs):.0f}] y[{min(ys):.0f},{max(ys):.0f}] z[{min(zs):.0f},{max(zs):.0f}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
