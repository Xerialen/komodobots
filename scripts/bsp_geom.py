#!/usr/bin/env python3
"""dm3 (Quake1 BSP v29) collision oracle for the SNG->RL bot observability.

Self-contained: parses the BSP with the stdlib `struct` module only (no numpy /
construct), and ports demopasha/phase0/hull_check_cpu.py's `point_contents`
(= Quake's SV_RecursiveHullCheck over the player hull, hull 1). The lump layout
and the tree-walk are taken verbatim from demopasha; only the dependencies are
dropped so this runs on the bare system Python and the lab harness stays
dependency-free.

API:
    bsp = Bsp.load(r"C:\\nQuake\\qw\\maps\\dm3.bsp")
    bsp.contents(x, y, z)      -> CONTENTS_* int (EMPTY/-1, SOLID/-2, WATER/-3, ...)
    bsp.is_solid(x, y, z)      -> bool
    bsp.floor_z(x, y, from_z)  -> float | None   (highest solid surface below; None=void)
    bsp.on_ground(x, y, z)     -> bool            (solid within GROUND_EPS below)

CLI:
    python bsp_geom.py <bsp>            # run sanity self-test
    python bsp_geom.py <bsp> contents X Y Z
    python bsp_geom.py <bsp> floor X Y [FROM_Z]
"""

from __future__ import annotations

import logging
import struct
import sys
from pathlib import Path


LOGGER = logging.getLogger(__name__)
# ── BSP leaf content constants (Quake1) ──────────────────────────────────────
CONTENTS_EMPTY = -1
CONTENTS_SOLID = -2
CONTENTS_WATER = -3
CONTENTS_SLIME = -4
CONTENTS_LAVA = -5
CONTENTS_SKY = -6
CONTENTS_NAMES = {
    CONTENTS_EMPTY: "EMPTY", CONTENTS_SOLID: "SOLID", CONTENTS_WATER: "WATER",
    CONTENTS_SLIME: "SLIME", CONTENTS_LAVA: "LAVA", CONTENTS_SKY: "SKY",
}

# ── Lump indices / sizes (Q1 v29) — from demopasha/phase0/bsp_parse.py ────────
LUMP_PLANES = 1
LUMP_CLIPNODES = 9
LUMP_MODELS = 14
LUMP_COUNT = 15

GROUND_EPS = 2.0   # solid within this many qu below the feet => on ground


class Bsp:
    def __init__(self, planes, clipnodes, hull1_start, world_mins, world_maxs):
        self.planes = planes              # list of (nx, ny, nz, dist, type)
        self.clipnodes = clipnodes        # list of (planenum, child0, child1)
        self.hull1_start = hull1_start    # root clipnode index for the player hull
        self.world_mins = world_mins      # (x, y, z)
        self.world_maxs = world_maxs

    # ── loading ──────────────────────────────────────────────────────────────
    @classmethod
    def load(cls, path):
        data = Path(path).read_bytes()
        version = struct.unpack_from("<i", data, 0)[0]
        if version != 29:
            raise ValueError(f"expected BSP v29, got {version} ({path})")
        # header: int32 version + 15 * (int32 offset, int32 length)
        lumps = []
        for i in range(LUMP_COUNT):
            off, length = struct.unpack_from("<ii", data, 4 + i * 8)
            lumps.append((off, length))

        # planes: 3f normal, f dist, i type = 20 bytes
        po, pl = lumps[LUMP_PLANES]
        planes = [struct.unpack_from("<3ffi", data, po + k * 20)
                  for k in range(pl // 20)]
        planes = [(p[0], p[1], p[2], p[3], p[4]) for p in planes]

        # clipnodes: i planenum, 2h children = 8 bytes
        co, cl = lumps[LUMP_CLIPNODES]
        clipnodes = [struct.unpack_from("<ihh", data, co + k * 8)
                     for k in range(cl // 8)]

        # models: 9f (mins,maxs,origin), 7i (headnode[4],visleafs,firstface,numfaces)
        mo, _ = lumps[LUMP_MODELS]
        m = struct.unpack_from("<9f7i", data, mo)
        world_mins = (m[0], m[1], m[2])
        world_maxs = (m[3], m[4], m[5])
        # 9 floats (mins,maxs,origin) then ints: headnode[0..3]=m[9..12].
        # hull 1 (player hull) clipnode root = headnode[1] = m[10].
        hull1_start = m[10]

        return cls(planes, clipnodes, hull1_start, world_mins, world_maxs)

    # ── core: point_contents (ported from demopasha hull_check_cpu.py) ─────────
    def contents(self, x, y, z):
        node = self.hull1_start
        while node >= 0:
            planenum, c0, c1 = self.clipnodes[node]
            nx, ny, nz, dist, ptype = self.planes[planenum]
            if ptype == 0:
                d = x - dist
            elif ptype == 1:
                d = y - dist
            elif ptype == 2:
                d = z - dist
            else:
                d = nx * x + ny * y + nz * z - dist
            node = c0 if d >= 0 else c1
        return node  # negative => leaf contents

    def is_solid(self, x, y, z):
        return self.contents(x, y, z) == CONTENTS_SOLID

    # ── floor probe: highest solid surface strictly below from_z ───────────────
    def floor_z(self, x, y, from_z, coarse=4.0, fine=0.25):
        """Drop a vertical probe from `from_z` (expected to be in the player's
        airspace, e.g. the current origin). Return the z at which the player
        ORIGIN comes to rest on the first SOLID below — i.e. the standing-origin
        height (hull 1 is expanded, so this is ~the recorded origin z, not feet).
        Returns None if no solid is found down to the world floor (true void).

        If `from_z` happens to be embedded in a floor brush, climb up a SHORT
        distance (<= CLIMB_CAP) to regain airspace; never run to the ceiling."""
        zmin = self.world_mins[2] - 8.0
        CLIMB_CAP = 48.0
        z = from_z
        if self.is_solid(x, y, z):
            climbed = 0.0
            while climbed <= CLIMB_CAP and self.is_solid(x, y, z):
                z += coarse
                climbed += coarse
            if self.is_solid(x, y, z):
                return None  # embedded deeper than a step-up; not a standing spot
        # coarse: step down to first solid
        zc = z
        hit = None
        while zc > zmin:
            if self.is_solid(x, y, zc):
                hit = zc
                break
            zc -= coarse
        if hit is None:
            return None
        # binary refine between last-empty (hit+coarse) and first-solid (hit)
        lo, hi = hit, hit + coarse   # lo solid, hi empty
        while hi - lo > fine:
            mid = 0.5 * (lo + hi)
            if self.is_solid(x, y, mid):
                lo = mid
            else:
                hi = mid
        return hi  # top of the solid (just-empty side)

    def on_ground(self, x, y, z, eps=GROUND_EPS):
        f = self.floor_z(x, y, z + 2.0)
        return f is not None and (z - f) <= eps + 1e-3


SV_GRAVITY = 800.0


def _load_cmds(path):
    """Return list of [x,y,z,vx,vy,vz] from a komodobots replay .cmds file."""
    out = []
    for ln in open(path):
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        p = ln.split()
        if len(p) < 14:
            continue
        out.append([float(p[1]), float(p[2]), float(p[3]),
                    float(p[4]), float(p[5]), float(p[6])])
    return out


def derive_jump_geom(bsp, cmds_path, void_thresh=-200.0, fps=77.043):
    """Derive the dm3 bridge->RL ballistic-leap geometry from the human demo:
    the launch edge (last ledge before the deep void), the void floor, the
    landing ledge, the horizontal gap, and the horizontal launch speed the
    jump requires. Returns a dict (also self-validates: human launch speed
    must be >= the computed required speed)."""
    import math
    F = _load_cmds(cmds_path)
    floors = [bsp.floor_z(f[0], f[1], f[2] + 8) for f in F]

    # The leap = the longest contiguous run of frames over a deep void
    # (floor below void_thresh). On dm3 SNG->RL that is the ledge->RL chasm.
    # "over void" = no floor at all (None) OR a floor far below (deep chasm).
    def over_void(k):
        return floors[k] is None or floors[k] < void_thresh
    runs, i = [], 0
    while i < len(F):
        if over_void(i):
            j = i
            while j < len(F) and over_void(j):
                j += 1
            runs.append((i, j))
            i = j
        else:
            i += 1
    if not runs:
        raise RuntimeError("no deep-void crossing found")
    a, b = max(runs, key=lambda r: r[1] - r[0])   # widest void crossing

    edge_i = a            # first frame out over the void (just past the ledge lip)
    land_i = b            # first frame back over solid (the landing ledge)
    ex, ey, ez = F[edge_i][:3]
    lx, ly, lz = F[land_i][:3]
    edge_vh = math.hypot(F[edge_i][3], F[edge_i][4])
    edge_vz = F[edge_i][5]
    gap = math.hypot(lx - ex, ly - ey)
    void_floor = min(floors[k] for k in range(a, b) if floors[k] is not None)

    # flight time from edge to landing solving  dz = vz0*t - 0.5*g*t^2  (dz<0 = drop)
    dz = lz - ez
    g = SV_GRAVITY
    disc = edge_vz * edge_vz + 2.0 * g * (-dz + 0.0)  # = vz0^2 + 2g*(drop)
    t_flight = (edge_vz + math.sqrt(max(disc, 0.0))) / g
    v_req = gap / t_flight if t_flight > 0 else float("inf")

    land_floor = bsp.floor_z(lx, ly, lz + 8)
    geom = {
        "map": "dm3", "route": "sng_to_rl", "fps": fps,
        "launch_edge":  {"frame": edge_i, "x": round(ex, 1), "y": round(ey, 1), "z": round(ez, 1),
                          "vh": round(edge_vh, 1), "vz": round(edge_vz, 1)},
        "landing_ledge": {"frame": land_i, "x": round(lx, 1), "y": round(ly, 1), "z": round(lz, 1),
                          "floor_z": round(land_floor, 1) if land_floor is not None else None},
        "void_floor_z": round(void_floor, 1),
        "gap_qu": round(gap, 1),
        "drop_qu": round(-dz, 1),
        "flight_time_s": round(t_flight, 3),
        "required_launch_speed_qu_s": round(v_req, 1),
        "human_launch_speed_qu_s": round(edge_vh, 1),
        "human_clears": edge_vh >= v_req,
        "sv_gravity": SV_GRAVITY,
        "note": ("The bot must reach the launch edge grounded with horizontal "
                 "speed >= required_launch_speed_qu_s AND jump, or it falls into "
                 "the void (floor void_floor_z). Speed at the edge is the binding "
                 "constraint for the leap."),
    }
    return geom


# ── self-test ─────────────────────────────────────────────────────────────────
def _selftest(bsp):
    cx = 0.5 * (bsp.world_mins[0] + bsp.world_maxs[0])
    cy = 0.5 * (bsp.world_mins[1] + bsp.world_maxs[1])
    cz = 0.5 * (bsp.world_mins[2] + bsp.world_maxs[2])
    center = bsp.contents(cx, cy, cz)
    ox = bsp.world_maxs[0] + 1000.0
    outside = bsp.contents(ox, bsp.world_maxs[1] + 1000.0, bsp.world_maxs[2] + 1000.0)
    print(f"planes={len(bsp.planes)} clipnodes={len(bsp.clipnodes)} hull1_start={bsp.hull1_start}")
    print(f"world AABB mins={bsp.world_mins} maxs={bsp.world_maxs}")
    print(f"center ({cx:.0f},{cy:.0f},{cz:.0f}) -> {CONTENTS_NAMES.get(center, center)} (expect EMPTY)")
    print(f"outside -> {CONTENTS_NAMES.get(outside, outside)} (expect SOLID)")
    ok = (center == CONTENTS_EMPTY) and (outside == CONTENTS_SOLID)
    print("SANITY", "PASS" if ok else "FAIL")
    return ok


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    bsp = Bsp.load(sys.argv[1])
    if len(sys.argv) == 2:
        sys.exit(0 if _selftest(bsp) else 1)
    cmd = sys.argv[2]
    if cmd == "contents":
        x, y, z = map(float, sys.argv[3:6])
        c = bsp.contents(x, y, z)
        print(f"contents({x},{y},{z}) = {CONTENTS_NAMES.get(c, c)}")
    elif cmd == "floor":
        x, y = map(float, sys.argv[3:5])
        fz = float(sys.argv[5]) if len(sys.argv) > 5 else bsp.world_maxs[2]
        f = bsp.floor_z(x, y, fz)
        print(f"floor_z({x},{y}, from={fz}) = {f}")
    elif cmd == "derive":
        import json
        cmds = sys.argv[3]
        out = sys.argv[4] if len(sys.argv) > 4 else None
        geom = derive_jump_geom(bsp, cmds)
        print(json.dumps(geom, indent=2))
        if out:
            Path(out).write_text(json.dumps(geom, indent=2) + "\n")
            print(f"\nwrote {out}")
        if not geom["human_clears"]:
            print("WARNING: human launch speed < required -> geometry math suspect", file=sys.stderr)
            sys.exit(1)
    else:
        print(f"unknown cmd {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
