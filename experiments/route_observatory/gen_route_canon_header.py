#!/usr/bin/env python3
"""Generate the C route-canon header for the Commander/Motor-Cortex handoff gate (#422, T3.1).

`data/catalog/route_canon.dm3.json` (`komodobots.route_canon.v1`) is the declarative source
for dm3's Route-Canon highways. Phase-1 movement consumes the `route_class=='base'` highways
ONLY (the JSON's own `_phase1_consumption` note), so this script filters to those, downsamples
each base highway's traced (x,y) trajectory to a small polyline, and emits a self-contained C
header (`experiments/ktx_moveprobe/live/route_canon_dm3.h`). The KTX handoff gate
(`move_highway.c`) includes that header to decide — purely from geometry — whether the bot is on
a trained base highway and should yield movement to the Motor Cortex.

This mirrors the repo's generate-first idiom (`scripts/generate_from_registry.py`): the header is
GENERATED and committed, carries an `AUTO-GENERATED — DO NOT HAND-EDIT` banner, and `--check`
fails on any drift (the anti-drift guard the CI floor runs). Pure standard library so it runs in
the deterministic CI floor (Python 3.12, no third-party deps).

The handoff radii live in `move_highway.h`; only `R_OFF` is mirrored here, used solely to WARN
when two base polylines pass within `2*R_OFF` in (x,y) — the documented trigger for adding
z-disambiguation (deferred for the 2D PoC, #422).

Usage:
    python3 experiments/route_observatory/gen_route_canon_header.py            # (re)write the header
    python3 experiments/route_observatory/gen_route_canon_header.py --check     # write nothing; assert zero-drift
    python3 experiments/route_observatory/gen_route_canon_header.py -o <path>   # write to a chosen path
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from pathlib import Path

LOGGER = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_JSON = REPO_ROOT / "data" / "catalog" / "route_canon.dm3.json"
OUTPUT_H = REPO_ROOT / "experiments" / "ktx_moveprobe" / "live" / "route_canon_dm3.h"

# Default polyline cap. The membership radius R_ON and this cap interact: a coarse stride on a
# high-curvature leg can pull the polyline > R_ON off the true path -> spurious DISENGAGE. Tune
# the cap and the radii together by-eye in the live run (#422 PoC default).
DEFAULT_MAX_PTS = 72

# Mirrors MHW_R_OFF in move_highway.h (qu) — used ONLY for the overlap WARN threshold below.
R_OFF = 96.0


# =============================================================================
# load / select
# =============================================================================
def load_canon(path: Path = SOURCE_JSON) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def base_highways(canon: dict) -> "list[dict]":
    """The `route_class=='base'` highways, in source order (Phase-1 consumes base ONLY)."""
    return [h for h in canon.get("highways", []) if h.get("route_class") == "base"]


def traj_xy(highway: dict) -> "list[tuple[float, float]]":
    """The (x,y) of segment[0]'s traced trajectory ([t,x,y,z] points)."""
    seg = highway["segments"][0]
    return [(float(p[1]), float(p[2])) for p in seg["trajectory"]]


# =============================================================================
# downsample
# =============================================================================
def downsample(pts: "list[tuple[float, float]]", cap: int) -> "list[tuple[float, float]]":
    """Reduce a polyline to <= cap points, always keeping the first and last.

    Picks `cap` evenly-spaced indices spanning [0, n-1] (so index 0 and n-1 are always in), then
    dedups — collisions from rounding only shrink the result, never exceed `cap`.
    """
    n = len(pts)
    if cap < 2:
        raise ValueError("cap must be >= 2")
    if n <= cap:
        return list(pts)
    idxs = sorted({round(i * (n - 1) / (cap - 1)) for i in range(cap)})
    return [pts[i] for i in idxs]


# =============================================================================
# overlap WARN (2D membership caveat)
# =============================================================================
def _seg_dist2(px, py, ax, ay, bx, by) -> float:
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    if l2 <= 0.0:
        return (px - ax) ** 2 + (py - ay) ** 2
    t = ((px - ax) * dx + (py - ay) * dy) / l2
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    cx, cy = ax + t * dx, ay + t * dy
    return (px - cx) ** 2 + (py - cy) ** 2


def _min_poly_dist(poly_a, poly_b) -> float:
    """Min Euclidean (x,y) distance between any vertex of poly_a and any segment of poly_b."""
    best = math.inf
    for (px, py) in poly_a:
        for i in range(len(poly_b) - 1):
            d2 = _seg_dist2(px, py, poly_b[i][0], poly_b[i][1], poly_b[i + 1][0], poly_b[i + 1][1])
            if d2 < best:
                best = d2
    return math.sqrt(best)


def check_overlaps(polys: "list[list[tuple[float, float]]]") -> "list[tuple[int, int, float]]":
    """Pairs (i,j,dist) of base polylines passing within 2*R_OFF in (x,y) — z would disambiguate."""
    warnings: "list[tuple[int, int, float]]" = []
    thresh = 2.0 * R_OFF
    for i in range(len(polys)):
        for j in range(i + 1, len(polys)):
            d = min(_min_poly_dist(polys[i], polys[j]), _min_poly_dist(polys[j], polys[i]))
            if d < thresh:
                warnings.append((i, j, d))
    return warnings


# =============================================================================
# emit
# =============================================================================
_GUARD = "KOMODO_ROUTE_CANON_DM3_H"


def _fmt(v: float) -> str:
    fv = float(v)
    if fv == 0.0:  # collapse -0.0 -> 0.0 so the output is sign-stable
        fv = 0.0
    return f"{fv:.6f}"


def build_header(canon: dict, max_pts: int = DEFAULT_MAX_PTS) -> str:
    base = base_highways(canon)
    if not base:
        raise ValueError("no route_class=='base' highways in the canon")

    polys = [downsample(traj_xy(h), max_pts) for h in base]
    ends = [(float(h["end_xyz"][0]), float(h["end_xyz"][1])) for h in base]
    npts = [len(p) for p in polys]
    pad = max(npts)

    # Overlap WARN (2D membership caveat — see module docstring).
    for (i, j, d) in check_overlaps(polys):
        LOGGER.warning(
            "base polylines %d (%s) and %d (%s) pass within %.1f qu < 2*R_OFF=%.0f in (x,y); "
            "2D membership may be ambiguous there (z-disambiguation deferred, #422)",
            i, base[i].get("id", "?"), j, base[j].get("id", "?"), d, 2.0 * R_OFF)

    prov = canon.get("_provenance", {})
    lines: "list[str]" = []
    lines.append("/* AUTO-GENERATED — DO NOT HAND-EDIT.")
    lines.append(" * Generated from data/catalog/route_canon.dm3.json by")
    lines.append(" * experiments/route_observatory/gen_route_canon_header.py")
    lines.append(" * Regenerate: python3 experiments/route_observatory/gen_route_canon_header.py")
    lines.append(" *")
    lines.append(" * Base-highway (route_class=='base') (x,y) trajectory polylines for the")
    lines.append(" * Commander/Motor-Cortex handoff gate (move_highway.c, #422 T3.1).")
    lines.append(f" * source schema: {canon.get('schema', '?')} | map: {canon.get('map', '?')}")
    lines.append(f" * source date: {prov.get('date', '?')} | n_base: {len(base)} | max_pts: {max_pts}")
    lines.append(" */")
    lines.append(f"#ifndef {_GUARD}")
    lines.append(f"#define {_GUARD}")
    lines.append("")
    lines.append(f"#define MHW_N_BASE {len(base)}")
    lines.append(f"#define MHW_MAX_PTS {pad}")
    lines.append("")
    lines.append("/* Real point count per base highway (the padding tail below is never iterated). */")
    lines.append("static const int MHW_NPTS[MHW_N_BASE] = {")
    lines.append("\t" + ", ".join(str(n) for n in npts))
    lines.append("};")
    lines.append("")
    lines.append("/* End (x,y) of each base highway (the arrival + intent target). */")
    lines.append("static const double MHW_END[MHW_N_BASE][2] = {")
    for k, (ex, ey) in enumerate(ends):
        lines.append(f"\t{{ {_fmt(ex)}, {_fmt(ey)} }},  /* {base[k].get('id', k)} */")
    lines.append("};")
    lines.append("")
    lines.append("/* Downsampled (x,y) polyline per base highway, padded to MHW_MAX_PTS with the")
    lines.append(" * last point (padding is inert: MHW_NPTS bounds every read). */")
    lines.append("static const double MHW_PTS[MHW_N_BASE][MHW_MAX_PTS][2] = {")
    for k, poly in enumerate(polys):
        padded = list(poly) + [poly[-1]] * (pad - len(poly))
        lines.append(f"\t{{  /* {base[k].get('id', k)} ({npts[k]} pts) */")
        for (x, y) in padded:
            lines.append(f"\t\t{{ {_fmt(x)}, {_fmt(y)} }},")
        lines.append("\t},")
    lines.append("};")
    lines.append("")
    lines.append(f"#endif /* {_GUARD} */")
    return "\n".join(lines) + "\n"


# =============================================================================
# main
# =============================================================================
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--output", type=Path, default=OUTPUT_H,
                    help="header path to write (default: the committed route_canon_dm3.h)")
    ap.add_argument("--source", type=Path, default=SOURCE_JSON, help="route_canon JSON source")
    ap.add_argument("--max-pts", type=int, default=DEFAULT_MAX_PTS,
                    help=f"downsample cap per base polyline (default {DEFAULT_MAX_PTS})")
    ap.add_argument("--check", action="store_true",
                    help="write nothing; exit 1 if the committed header differs from a fresh regen")
    args = ap.parse_args(argv)

    canon = load_canon(args.source)
    text = build_header(canon, args.max_pts)

    if args.check:
        if not args.output.exists():
            print(f"FAIL: {args.output} missing (run the generator)", file=sys.stderr)
            return 1
        if args.output.read_text(encoding="utf-8") != text:
            print(f"FAIL: {args.output} STALE — regenerate "
                  f"(python3 {Path(__file__).relative_to(REPO_ROOT)})", file=sys.stderr)
            return 1
        print(f"route_canon header up to date ({args.output.name})")
        return 0

    args.output.write_text(text, encoding="utf-8")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    raise SystemExit(main())
