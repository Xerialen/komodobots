"""map_regions.py — load named control REGIONS for a map + deterministic region assignment.

Phase 0.3 (#317). This is the region ASSIGNMENT layer the #319 route segmenter consumes.
It replaces the coarse blanket nearest-LANDMARK snap used by the #315 demo
(`scripts/dm3_leg_traffic.py`), which snapped over 26 raw landmarks at a 600 qu radius and
produced phantom intra-area "legs" like RA.low<->RA and YA.box<->YA. Here each region MERGES
an item's sub-points/adjacent fixtures into ONE named area, so those phantom shuffles
collapse into a single region.

Region file (default): `lab/dashboard/public/data/map_regions/<map>.json`. Each region is a
sphere = `center` [x, y, z] (quake units) + `radius_qu`. See that file's `doc` block for the
geometry model and the granularity rationale.

ASSIGNMENT CONTRACT (deterministic NEAREST-REGION-WITH-CAP)
----------------------------------------------------------
`assign_region(x, y, z)` returns the name of the region whose 3D-Euclidean center is NEAREST
to (x, y, z), but ONLY if that nearest distance is <= that region's `radius_qu`; otherwise it
returns None (the position is outside every region's cap — a mid-corridor / transition point).

Because the nearest center wins, a point is assigned to EXACTLY ONE region (or None) — two
regions can never both claim the same point even if their spheres visually overlap. The radii
are therefore membership CAPS (None vs assigned), not a hard spatial partition. Distance is 3D
on purpose: dm3 is heavily multi-level, so the Z term separates stacked areas (water floor,
hill/bridge, RL/window, Quad/Ring, RA) that a 2D test would conflate.

Determinism with ties: centers are distinct, but if two centers were ever exactly equidistant,
the region defined EARLIER in the file wins (stable: the strict `<` comparison keeps the first
seen). Loading preserves file order.

Pure standard library (json + math + pathlib). Obeys the scripts/ stdlib-only gate.

Usage (library):
    from map_regions import load_regions, assign_region, RegionSet
    rs = load_regions()                      # default dm3 region file
    name = rs.assign(x, y, z)                # -> "RA" | ... | None
    # module-level convenience (lazy-loads the default dm3 set once):
    name = assign_region(x, y, z)

Usage (CLI, smoke):
    python3 scripts/map_regions.py --x 256 --y -704 --z 304     # -> RA
    python3 scripts/map_regions.py --list                       # list regions
"""
from __future__ import annotations

import logging
import argparse
import json
import math
from pathlib import Path


LOGGER = logging.getLogger(__name__)
HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
DEFAULT_REGIONS = (REPO_ROOT / "lab" / "dashboard" / "public" / "data"
                   / "map_regions" / "dm3.json")


class Region:
    """One named spherical control region: center (x, y, z) qu + radius_qu cap."""

    __slots__ = ("name", "cx", "cy", "cz", "radius_qu")

    def __init__(self, name: str, center, radius_qu: float):
        self.name = str(name)
        self.cx = float(center[0])
        self.cy = float(center[1])
        self.cz = float(center[2])
        self.radius_qu = float(radius_qu)

    def dist(self, x: float, y: float, z: float) -> float:
        """3D Euclidean distance from this region's center to (x, y, z)."""
        return math.sqrt((x - self.cx) ** 2 + (y - self.cy) ** 2 + (z - self.cz) ** 2)

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return (f"Region({self.name!r}, center=({self.cx:.0f},{self.cy:.0f},"
                f"{self.cz:.0f}), radius_qu={self.radius_qu:.0f})")


class RegionSet:
    """An ordered set of named regions for one map + the deterministic assignment rule."""

    def __init__(self, map_name: str, regions: list[Region]):
        self.map = str(map_name)
        self.regions = list(regions)

    def __len__(self) -> int:
        return len(self.regions)

    def names(self) -> list[str]:
        return [r.name for r in self.regions]

    def assign(self, x: float, y: float, z: float) -> str | None:
        """Deterministic nearest-region-with-cap.

        Return the name of the region whose 3D center is nearest to (x, y, z) when that
        nearest distance is within the region's radius_qu cap; otherwise None.

        Nearest-wins => a point is claimed by at most one region (no double assignment),
        so regions cannot overlap-ambiguously even if their spheres intersect. Ties resolve
        to the region defined earlier in the file (strict `<` keeps the first seen).
        """
        best: Region | None = None
        best_d = math.inf
        for r in self.regions:
            d = r.dist(x, y, z)
            if d < best_d:
                best_d = d
                best = r
        if best is None:
            return None
        if best_d <= best.radius_qu:
            return best.name
        return None


def load_regions(path: Path | str = DEFAULT_REGIONS) -> RegionSet:
    """Load a map-regions JSON file into a RegionSet (file order preserved).

    Expected shape (see lab/dashboard/public/data/map_regions/dm3.json):
        {"map": "dm3", "regions": [{"name": ..., "center": [x,y,z], "radius_qu": N}, ...]}
    """
    p = Path(path)
    doc = json.loads(p.read_text(encoding="utf-8"))
    map_name = doc.get("map", p.stem)
    regions: list[Region] = []
    seen: set[str] = set()
    for r in doc.get("regions", []):
        name = r["name"]
        if name in seen:
            raise ValueError(f"duplicate region name {name!r} in {p}")
        seen.add(name)
        center = r["center"]
        if len(center) != 3:
            raise ValueError(f"region {name!r} center must be [x, y, z]")
        radius = float(r["radius_qu"])
        if radius <= 0:
            raise ValueError(f"region {name!r} radius_qu must be > 0, got {radius}")
        regions.append(Region(name, center, radius))
    if not regions:
        raise ValueError(f"no regions loaded from {p}")
    return RegionSet(map_name, regions)


# --- module-level convenience: lazily load the default dm3 region set once ---
_DEFAULT_SET: RegionSet | None = None


def _default_set() -> RegionSet:
    global _DEFAULT_SET
    if _DEFAULT_SET is None:
        _DEFAULT_SET = load_regions(DEFAULT_REGIONS)
    return _DEFAULT_SET


def assign_region(x: float, y: float, z: float) -> str | None:
    """Assign (x, y, z) to a region of the DEFAULT (dm3) region set, or None.

    Convenience wrapper over `load_regions(...).assign(...)` for callers that just want the
    dm3 layer (e.g. the #319 segmenter / coverage checks). The default set is cached after
    the first call. For other maps or explicit control, use `load_regions(path).assign(...)`.
    """
    return _default_set().assign(x, y, z)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Load map regions; assign a point or list regions.")
    ap.add_argument("--regions", type=Path, default=DEFAULT_REGIONS,
                    help="map_regions JSON (default: committed dm3 region file)")
    ap.add_argument("--x", type=float)
    ap.add_argument("--y", type=float)
    ap.add_argument("--z", type=float)
    ap.add_argument("--list", action="store_true", help="list region names + centers + radii")
    args = ap.parse_args(argv)

    rs = load_regions(args.regions)
    if args.list:
        print(f"map={rs.map}  regions={len(rs)}")
        for r in rs.regions:
            print(f"  {r.name:10s} center=({r.cx:7.0f},{r.cy:7.0f},{r.cz:7.0f}) "
                  f"radius_qu={r.radius_qu:.0f}")
        return 0
    if args.x is None or args.y is None or args.z is None:
        ap.error("provide --x --y --z (to assign a point) or --list")
    name = rs.assign(args.x, args.y, args.z)
    print(name if name is not None else "None")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
