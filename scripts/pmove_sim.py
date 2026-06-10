#!/usr/bin/env python3
"""Offline deterministic re-implementation of QuakeWorld server player movement.

A faithful Python port of mvdsv master src/pmove.c (the engine the komodobots
lab runs: MVDSV 1.20-dev + KTX, serverinfo pm_ktjump=1, all other pm_* at
defaults). A verbatim reference copy of the C source is kept at
artifacts/pmove-validation/reference-mvdsv-pmove.c.

Traces run against the real dm3 BSP: hull 1 for the player (swept
SV_RecursiveHullCheck port returning fraction + plane normal), hull 0 (point
hull, built from the render nodes like Mod_MakeHull0) for waterlevel /
point-contents checks. Only the worldmodel is traced — submodels
(doors/plats/lifts) and other players are NOT collided (known limitation).

This is the substrate for en-masse controller parameter sweeps: replay a
recorded per-frame input stream (human .cmds or bot moveprobe log) through
run_frame() and you reproduce the recorded trajectory without a game server.

Server-side semantics replicated from mvdsv src/sv_user.c SV_RunCmd:
  - pmove.jump_msec is zeroed every command -> the jump_msec pogo path is
    dead server-side; a held jump only auto-jumps on landing if the button
    was pressed while airborne (jump_held stays false in air).
  - "broken ankle": velocity[2] == -270 with jump held -> jump_held forced.
  - cmd.msec > 50 is chopped in half (not needed for these logs, msec <= 26).

Physics constants (mvdsv/KTX defaults, no overrides in the lab cfg):
    gravity 800, friction 4 (x2 at dropoff edges), stopspeed 100,
    maxspeed 320, accelerate 10 (used for BOTH ground and air accel by
    mvdsv PM_AirMove), airaccelerate present but unused by the air path,
    wateraccelerate 10, waterfriction 4, jump +270 (ktjump 1 clamps to
    exactly 270), stepsize 18, entgravity 1.0,
    slidefix 0, airstep 0, pground 0, rampjump 0, bunnyspeedcap 0.

Determinism: pure float math (Python float64 vs the engine's float32 — the
only intentional numeric deviation), no randomness, no wall-clock.

API:
    world = WorldModel.load(r"C:\\nQuake\\qw\\maps\\dm3.bsp")
    pm = Pmove(world)
    st = PlayerState(origin=[...], velocity=[...])
    pm.run_frame(st, Cmd(msec=13, angles=(p, y, r), move=(fwd, side, up), buttons=b))

CLI:
    python pmove_sim.py replay --cmds artifacts/replay/dm3_sng_to_rl.cmds [--anchored]
    python pmove_sim.py replay --botlog artifacts/lab-runs/<run>/moveprobe-commands.json --frames 2000
"""

from __future__ import annotations

import argparse
import json
import math
import struct
import sys
from pathlib import Path

# ── constants (mvdsv pmove.c / bspfile.h) ────────────────────────────────────
CONTENTS_EMPTY = -1
CONTENTS_SOLID = -2
CONTENTS_WATER = -3
CONTENTS_SLIME = -4
CONTENTS_LAVA = -5
CONTENTS_SKY = -6

DIST_EPSILON = 0.03125   # 1/32: keep trace crosspoints on the near side
STOP_EPSILON = 0.1
STEPSIZE = 18.0
MIN_STEP_NORMAL = 0.7
MAX_CLIP_PLANES = 5
BUTTON_JUMP = 2
MAX_JUMPFIX_DOTPRODUCT = -0.1
MAXGROUNDSPEED_DEFAULT = 180.0

BLOCKED_FLOOR = 1
BLOCKED_STEP = 2
BLOCKED_OTHER = 4

PLAYER_MINS = (-16.0, -16.0, -24.0)
PLAYER_MAXS = (16.0, 16.0, 32.0)

# lump indices (BSP v29)
LUMP_PLANES = 1
LUMP_NODES = 5
LUMP_CLIPNODES = 9
LUMP_LEAFS = 10
LUMP_MODELS = 14
LUMP_COUNT = 15


class MoveVars:
    """mvdsv/KTX server movevars (defaults = the lab cfg sets no overrides)."""

    def __init__(self, **kw):
        self.gravity = 800.0
        self.stopspeed = 100.0
        self.maxspeed = 320.0
        self.accelerate = 10.0
        self.airaccelerate = 10.0   # NOTE: mvdsv PM_AirMove passes .accelerate
        self.wateraccelerate = 10.0
        self.friction = 4.0
        self.waterfriction = 4.0
        self.entgravity = 1.0
        self.ktjump = 1.0           # serverinfo pm_ktjump 1
        self.slidefix = False
        self.airstep = False
        for k, v in kw.items():
            if not hasattr(self, k):
                raise TypeError(f"unknown movevar {k}")
            setattr(self, k, v)

    def as_dict(self):
        return dict(vars(self))


# ── BSP loading ───────────────────────────────────────────────────────────────
class Hull:
    __slots__ = ("planes", "clipnodes", "firstclipnode")

    def __init__(self, planes, clipnodes, firstclipnode):
        self.planes = planes          # list[(nx, ny, nz, dist, type)]
        self.clipnodes = clipnodes    # list[(planenum, child0, child1)]
        self.firstclipnode = firstclipnode


class WorldModel:
    """dm3 worldmodel: hull0 (point) + hull1 (player) against the world brushes."""

    def __init__(self, hull0: Hull, hull1: Hull, world_mins, world_maxs):
        self.hull0 = hull0
        self.hull1 = hull1
        self.world_mins = world_mins
        self.world_maxs = world_maxs

    @classmethod
    def load(cls, path):
        data = Path(path).read_bytes()
        version = struct.unpack_from("<i", data, 0)[0]
        if version != 29:
            raise ValueError(f"expected BSP v29, got {version} ({path})")
        lumps = [struct.unpack_from("<ii", data, 4 + i * 8) for i in range(LUMP_COUNT)]

        po, pl = lumps[LUMP_PLANES]            # 20 bytes: 3f normal, f dist, i type
        planes = [struct.unpack_from("<3ffi", data, po + k * 20) for k in range(pl // 20)]

        co, cl = lumps[LUMP_CLIPNODES]         # 8 bytes: i planenum, 2h children
        clipnodes = [struct.unpack_from("<ihh", data, co + k * 8) for k in range(cl // 8)]

        # nodes: i planenum, 2h children, 6h bbox, 2H faces = 24 bytes
        no, nl = lumps[LUMP_NODES]
        nodes = [struct.unpack_from("<i2h", data, no + k * 24) for k in range(nl // 24)]

        # leafs: i contents, i visofs, 6h bbox, 2H marksurf, 4B ambient = 28 bytes
        lo, ll = lumps[LUMP_LEAFS]
        leaf_contents = [struct.unpack_from("<i", data, lo + k * 28)[0] for k in range(ll // 28)]

        mo, _ = lumps[LUMP_MODELS]             # model 0 = world
        m = struct.unpack_from("<9f7i", data, mo)
        world_mins, world_maxs = (m[0], m[1], m[2]), (m[3], m[4], m[5])
        headnode0, headnode1 = m[9], m[10]

        # hull 0 = Mod_MakeHull0: mirror the render node tree as clipnodes,
        # mapping leaf children to their contents.
        hull0_nodes = []
        for planenum, c0, c1 in nodes:
            kids = []
            for c in (c0, c1):
                kids.append(c if c >= 0 else leaf_contents[-1 - c])
            hull0_nodes.append((planenum, kids[0], kids[1]))

        hull0 = Hull(planes, hull0_nodes, headnode0)
        hull1 = Hull(planes, clipnodes, headnode1)
        return cls(hull0, hull1, world_mins, world_maxs)


# ── hull queries (pmovetst.c ports) ───────────────────────────────────────────
def hull_point_contents(hull: Hull, num: int, p) -> int:
    """PM_HullPointContents."""
    planes, clipnodes = hull.planes, hull.clipnodes
    x, y, z = p
    while num >= 0:
        planenum, c0, c1 = clipnodes[num]
        nx, ny, nz, dist, ptype = planes[planenum]
        if ptype == 0:
            d = x - dist
        elif ptype == 1:
            d = y - dist
        elif ptype == 2:
            d = z - dist
        else:
            d = nx * x + ny * y + nz * z - dist
        num = c0 if d >= 0 else c1
    return num


class Trace:
    __slots__ = ("fraction", "endpos", "normal", "plane_dist",
                 "allsolid", "startsolid", "inopen", "inwater", "ent")

    def __init__(self, end):
        self.fraction = 1.0
        self.endpos = [end[0], end[1], end[2]]
        self.normal = [0.0, 0.0, 0.0]
        self.plane_dist = 0.0
        self.allsolid = True
        self.startsolid = False
        self.inopen = False
        self.inwater = False
        self.ent = -1


def _recursive_hull_check(hull: Hull, num: int, p1f, p2f, p1, p2, trace: Trace) -> bool:
    """Verbatim port of SV_RecursiveHullCheck / PM_RecursiveHullCheck."""
    if num < 0:
        if num != CONTENTS_SOLID:
            trace.allsolid = False
            if num == CONTENTS_EMPTY:
                trace.inopen = True
            else:
                trace.inwater = True
        else:
            trace.startsolid = True
        return True  # empty

    planenum, c0, c1 = hull.clipnodes[num]
    nx, ny, nz, dist, ptype = hull.planes[planenum]

    if ptype < 3:
        t1 = p1[ptype] - dist
        t2 = p2[ptype] - dist
    else:
        t1 = nx * p1[0] + ny * p1[1] + nz * p1[2] - dist
        t2 = nx * p2[0] + ny * p2[1] + nz * p2[2] - dist

    if t1 >= 0 and t2 >= 0:
        return _recursive_hull_check(hull, c0, p1f, p2f, p1, p2, trace)
    if t1 < 0 and t2 < 0:
        return _recursive_hull_check(hull, c1, p1f, p2f, p1, p2, trace)

    # put the crosspoint DIST_EPSILON pixels on the near side
    if t1 < 0:
        frac = (t1 + DIST_EPSILON) / (t1 - t2)
    else:
        frac = (t1 - DIST_EPSILON) / (t1 - t2)
    if frac < 0:
        frac = 0.0
    if frac > 1:
        frac = 1.0

    midf = p1f + (p2f - p1f) * frac
    mid = [p1[i] + frac * (p2[i] - p1[i]) for i in range(3)]

    side = 1 if t1 < 0 else 0
    near = c1 if side else c0
    far = c0 if side else c1

    # move up to the node
    if not _recursive_hull_check(hull, near, p1f, midf, p1, mid, trace):
        return False

    if hull_point_contents(hull, far, mid) != CONTENTS_SOLID:
        # go past the node
        return _recursive_hull_check(hull, far, midf, p2f, mid, p2, trace)

    if trace.allsolid:
        return False  # never got out of the solid area

    # the other side of the node is solid: this is the impact point
    if not side:
        trace.normal = [nx, ny, nz]
        trace.plane_dist = dist
    else:
        trace.normal = [-nx, -ny, -nz]
        trace.plane_dist = -dist

    # back up the crosspoint until it is out of the solid (rarely needed)
    while hull_point_contents(hull, hull.firstclipnode, mid) == CONTENTS_SOLID:
        frac -= 0.1
        if frac < 0:
            trace.fraction = midf
            trace.endpos = mid
            return False
        midf = p1f + (p2f - p1f) * frac
        mid = [p1[i] + frac * (p2[i] - p1[i]) for i in range(3)]

    trace.fraction = midf
    trace.endpos = mid
    return False


def player_trace(world: WorldModel, start, end) -> Trace:
    """PM_PlayerTrace: swept hull-1 move against the world (physent 0 only)."""
    tr = Trace(end)
    _recursive_hull_check(world.hull1, world.hull1.firstclipnode, 0.0, 1.0,
                          list(start), list(end), tr)
    if tr.allsolid:
        tr.startsolid = True
    if tr.startsolid:
        tr.fraction = 0.0
    tr.ent = 0 if tr.fraction < 1.0 else -1
    return tr


# ── small vector helpers ──────────────────────────────────────────────────────
def _normalize(v):
    l = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if l:
        v[0] /= l
        v[1] /= l
        v[2] /= l
    return l


def angle_vectors(angles):
    """AngleVectors (degrees -> forward, right)."""
    d2r = math.pi * 2.0 / 360.0
    pitch, yaw, roll = angles
    ay = yaw * d2r
    sy, cy = math.sin(ay), math.cos(ay)
    ap = pitch * d2r
    sp, cp = math.sin(ap), math.cos(ap)
    ar = roll * d2r
    sr, cr = math.sin(ar), math.cos(ar)
    forward = [cp * cy, cp * sy, -sp]
    right = [(-1 * sr * sp * cy + -1 * cr * -sy),
             (-1 * sr * sp * sy + -1 * cr * cy),
             -1 * sr * cp]
    return forward, right


def clip_velocity(vin, normal, overbounce):
    """PM_ClipVelocity."""
    backoff = (vin[0] * normal[0] + vin[1] * normal[1] + vin[2] * normal[2]) * overbounce
    out = [0.0, 0.0, 0.0]
    for i in range(3):
        change = normal[i] * backoff
        out[i] = vin[i] - change
        if -STOP_EPSILON < out[i] < STOP_EPSILON:
            out[i] = 0.0
    return out


# ── pmove state ───────────────────────────────────────────────────────────────
class Cmd:
    __slots__ = ("msec", "angles", "move", "buttons")

    def __init__(self, msec, angles, move, buttons):
        self.msec = msec
        self.angles = tuple(angles)   # pitch, yaw, roll (degrees)
        self.move = tuple(move)       # forwardmove, sidemove, upmove
        self.buttons = buttons


class PlayerState:
    """Persistent player state across commands (mirrors what SV_RunCmd
    carries over: origin, velocity, FL_ONGROUND, teleport_time, jump_held)."""
    __slots__ = ("origin", "velocity", "jump_held", "waterjumptime",
                 "onground", "waterlevel", "watertype", "groundnormal")

    def __init__(self, origin, velocity, jump_held=False, waterjumptime=0.0,
                 onground=False):
        self.origin = list(origin)
        self.velocity = list(velocity)
        self.jump_held = jump_held
        self.waterjumptime = waterjumptime
        self.onground = onground
        self.waterlevel = 0
        self.watertype = CONTENTS_EMPTY
        self.groundnormal = [0.0, 0.0, 0.0]


class Pmove:
    """Per-frame QW server player movement (mvdsv PM_PlayerMove port)."""

    def __init__(self, world: WorldModel, movevars: MoveVars | None = None):
        self.world = world
        self.mv = movevars or MoveVars()
        # per-frame scratch
        self._fwd = [1.0, 0.0, 0.0]
        self._right = [0.0, -1.0, 0.0]
        self.frametime = 0.0

    # ── PM_TestPlayerPosition ────────────────────────────────────────────────
    def _test_position(self, pos):
        return hull_point_contents(self.world.hull1, self.world.hull1.firstclipnode,
                                   pos) != CONTENTS_SOLID

    def _point_contents(self, pos):
        return hull_point_contents(self.world.hull0, self.world.hull0.firstclipnode, pos)

    # ── PM_NudgePosition (mvdsv: x innermost, plus 1..18 unstick climb) ──────
    def _nudge_position(self, s: PlayerState):
        base = list(s.origin)
        sign = (0, -1, 1)
        for z in range(3):
            for y in range(3):
                for x in range(3):
                    s.origin[0] = base[0] + sign[x] * 0.125
                    s.origin[1] = base[1] + sign[y] * 0.125
                    s.origin[2] = base[2] + sign[z] * 0.125
                    if self._test_position(s.origin):
                        return
        # some maps spawn the player several units into the ground
        for z in range(1, 19):
            s.origin[0] = base[0]
            s.origin[1] = base[1]
            s.origin[2] = base[2] + z
            if self._test_position(s.origin):
                return
        s.origin[:] = base

    # ── PM_CategorizePosition (pground=0, rampjump=0) ────────────────────────
    def _categorize(self, s: PlayerState):
        tr = None
        if s.velocity[2] > MAXGROUNDSPEED_DEFAULT:
            s.onground = False
        else:
            point = (s.origin[0], s.origin[1], s.origin[2] - 1.0)
            tr = player_trace(self.world, s.origin, point)
            far = tr.fraction == 1.0 or tr.normal[2] < MIN_STEP_NORMAL
            if not far:
                s.groundnormal = list(tr.normal)
            if far:
                s.onground = False
            else:
                s.onground = True
                s.waterjumptime = 0.0

        # get waterlevel
        s.waterlevel = 0
        s.watertype = CONTENTS_EMPTY
        point = [s.origin[0], s.origin[1], s.origin[2] + PLAYER_MINS[2] + 1.0]
        cont = self._point_contents(point)
        if cont <= CONTENTS_WATER:
            s.watertype = cont
            s.waterlevel = 1
            point[2] = s.origin[2] + (PLAYER_MINS[2] + PLAYER_MAXS[2]) * 0.5
            cont = self._point_contents(point)
            if cont <= CONTENTS_WATER:
                s.waterlevel = 2
                point[2] = s.origin[2] + 22.0
                cont = self._point_contents(point)
                if cont <= CONTENTS_WATER:
                    s.waterlevel = 3

        # !pground: snap to ground so we can't jump higher than we're supposed to
        if s.onground and s.waterlevel < 2 and tr is not None:
            if not tr.startsolid and not tr.allsolid:
                s.origin[:] = tr.endpos

    # ── PM_CheckJump ─────────────────────────────────────────────────────────
    def _check_jump(self, s: PlayerState, cmd: Cmd):
        if not (cmd.buttons & BUTTON_JUMP):
            s.jump_held = False
            return
        if s.waterjumptime:
            return
        if s.waterlevel >= 2:
            # swimming, not jumping
            s.onground = False
            if s.watertype == CONTENTS_WATER:
                s.velocity[2] = 100.0
            elif s.watertype == CONTENTS_SLIME:
                s.velocity[2] = 80.0
            else:
                s.velocity[2] = 50.0
            return
        if not s.onground:
            return  # in air, so no effect
        if s.jump_held:  # jump_msec is always 0 server-side (SV_RunCmd)
            return  # don't pogo stick

        # !pground jump-bug fix: clip a velocity pointing into the ground
        v, n = s.velocity, s.groundnormal
        if v[2] < 0 and (v[0] * n[0] + v[1] * n[1] + v[2] * n[2]) < MAX_JUMPFIX_DOTPRODUCT:
            s.velocity = clip_velocity(v, n, 1.0)

        s.onground = False
        s.velocity[2] += 270.0
        kt = self.mv.ktjump
        if kt > 0:
            if kt > 1:
                kt = 1.0
            if s.velocity[2] < 270.0:
                s.velocity[2] = s.velocity[2] * (1.0 - kt) + 270.0 * kt
        s.jump_held = True  # don't jump again until released

    # ── PM_CheckWaterJump ────────────────────────────────────────────────────
    def _check_water_jump(self, s: PlayerState):
        if s.waterjumptime:
            return
        if s.velocity[2] < -180:
            return  # don't hop out if we just jumped in
        flat = [self._fwd[0], self._fwd[1], 0.0]
        _normalize(flat)
        spot = [s.origin[0] + 24 * flat[0], s.origin[1] + 24 * flat[1], s.origin[2] + 8.0]
        if self._point_contents(spot) != CONTENTS_SOLID:
            return
        spot[2] += 24.0
        if self._point_contents(spot) != CONTENTS_EMPTY:
            return
        # jump out of water
        s.velocity = [flat[0] * 50.0, flat[1] * 50.0, 310.0]
        s.waterjumptime = 2.0
        s.jump_held = True

    # ── PM_Friction ──────────────────────────────────────────────────────────
    def _friction(self, s: PlayerState):
        if s.waterjumptime:
            return
        v = s.velocity
        speed = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
        if speed < 1:
            v[0] = 0.0
            v[1] = 0.0
            return

        if s.waterlevel >= 2:
            drop = speed * self.mv.waterfriction * s.waterlevel * self.frametime
        elif s.onground:
            friction = self.mv.friction
            # if the leading edge is over a dropoff, increase friction
            start = [s.origin[0] + v[0] / speed * 16,
                     s.origin[1] + v[1] / speed * 16,
                     s.origin[2] + PLAYER_MINS[2]]
            stop = [start[0], start[1], start[2] - 34.0]
            tr = player_trace(self.world, start, stop)
            if tr.fraction == 1.0:
                friction *= 2.0
            control = self.mv.stopspeed if speed < self.mv.stopspeed else speed
            drop = control * friction * self.frametime
        else:
            return  # in air, no friction

        newspeed = speed - drop
        if newspeed < 0:
            newspeed = 0.0
        newspeed /= speed
        v[0] *= newspeed
        v[1] *= newspeed
        v[2] *= newspeed

    # ── PM_Accelerate / PM_AirAccelerate ─────────────────────────────────────
    def _accelerate(self, s: PlayerState, wishdir, wishspeed, accel):
        if s.waterjumptime:
            return
        v = s.velocity
        currentspeed = v[0] * wishdir[0] + v[1] * wishdir[1] + v[2] * wishdir[2]
        addspeed = wishspeed - currentspeed
        if addspeed <= 0:
            return
        accelspeed = accel * self.frametime * wishspeed
        if accelspeed > addspeed:
            accelspeed = addspeed
        for i in range(3):
            v[i] += accelspeed * wishdir[i]

    def _air_accelerate(self, s: PlayerState, wishdir, wishspeed, accel):
        if s.waterjumptime:
            return
        wishspd = 30.0 if wishspeed > 30 else wishspeed
        v = s.velocity
        currentspeed = v[0] * wishdir[0] + v[1] * wishdir[1] + v[2] * wishdir[2]
        addspeed = wishspd - currentspeed
        if addspeed <= 0:
            return
        accelspeed = accel * wishspeed * self.frametime
        if accelspeed > addspeed:
            accelspeed = addspeed
        for i in range(3):
            v[i] += accelspeed * wishdir[i]

    # ── PM_SlideMove ─────────────────────────────────────────────────────────
    def _slide_move(self, s: PlayerState):
        numbumps = 4
        blocked = 0
        original_velocity = list(s.velocity)
        primal_velocity = list(s.velocity)
        planes = []
        time_left = self.frametime

        for _ in range(numbumps):
            end = [s.origin[i] + time_left * s.velocity[i] for i in range(3)]
            tr = player_trace(self.world, s.origin, end)

            if tr.startsolid or tr.allsolid:
                s.velocity = [0.0, 0.0, 0.0]
                return 3
            if tr.fraction > 0:
                s.origin[:] = tr.endpos
                planes = []
            if tr.fraction == 1:
                break  # moved the entire distance

            if tr.normal[2] >= MIN_STEP_NORMAL:
                blocked |= BLOCKED_FLOOR
            elif not tr.normal[2]:
                blocked |= BLOCKED_STEP
            else:
                blocked |= BLOCKED_OTHER

            time_left -= time_left * tr.fraction

            if len(planes) >= MAX_CLIP_PLANES:
                s.velocity = [0.0, 0.0, 0.0]
                break
            planes.append(list(tr.normal))

            # modify original_velocity so it parallels all of the clip planes
            ok_plane = False
            for i in range(len(planes)):
                cand = clip_velocity(original_velocity, planes[i], 1.0)
                ok = True
                for j in range(len(planes)):
                    if j != i:
                        if (cand[0] * planes[j][0] + cand[1] * planes[j][1] +
                                cand[2] * planes[j][2]) < 0:
                            ok = False
                            break
                if ok:
                    s.velocity = cand
                    ok_plane = True
                    break
            if not ok_plane:
                # go along the crease
                if len(planes) != 2:
                    s.velocity = [0.0, 0.0, 0.0]
                    break
                p0, p1 = planes
                dirv = [p0[1] * p1[2] - p0[2] * p1[1],
                        p0[2] * p1[0] - p0[0] * p1[2],
                        p0[0] * p1[1] - p0[1] * p1[0]]
                d = (dirv[0] * s.velocity[0] + dirv[1] * s.velocity[1] +
                     dirv[2] * s.velocity[2])
                s.velocity = [dirv[0] * d, dirv[1] * d, dirv[2] * d]

            # if velocity is against the original velocity, stop dead
            # to avoid tiny occilations in sloping corners
            if (s.velocity[0] * primal_velocity[0] + s.velocity[1] * primal_velocity[1] +
                    s.velocity[2] * primal_velocity[2]) <= 0:
                s.velocity = [0.0, 0.0, 0.0]
                break

        if s.waterjumptime:
            s.velocity = primal_velocity
        return blocked

    # ── PM_StepSlideMove ─────────────────────────────────────────────────────
    def _step_slide_move(self, s: PlayerState, in_air: bool):
        original = list(s.origin)
        originalvel = list(s.velocity)

        blocked = self._slide_move(s)
        if not blocked:
            return blocked  # moved the entire distance

        if in_air:
            # don't step up unless it's indeed a step we bumped into
            if not (blocked & BLOCKED_STEP):
                return blocked
            org = s.origin if originalvel[2] < 0 else original
            dest = [org[0], org[1], org[2] - STEPSIZE]
            tr = player_trace(self.world, org, dest)
            if tr.fraction == 1.0 or tr.normal[2] < MIN_STEP_NORMAL:
                return blocked
            stepsize = STEPSIZE - (org[2] - tr.endpos[2])
        else:
            stepsize = STEPSIZE

        down = list(s.origin)
        downvel = list(s.velocity)

        s.origin[:] = original
        s.velocity[:] = originalvel

        # move up a stair height
        dest = [s.origin[0], s.origin[1], s.origin[2] + stepsize]
        tr = player_trace(self.world, s.origin, dest)
        if not tr.startsolid and not tr.allsolid:
            s.origin[:] = tr.endpos

        if in_air and originalvel[2] < 0:
            s.velocity[2] = 0.0

        self._slide_move(s)

        # press down the stepheight
        dest = [s.origin[0], s.origin[1], s.origin[2] - stepsize]
        tr = player_trace(self.world, s.origin, dest)
        use_down = False
        if tr.fraction != 1.0 and tr.normal[2] < MIN_STEP_NORMAL:
            use_down = True
        else:
            if not tr.startsolid and not tr.allsolid:
                s.origin[:] = tr.endpos
            if s.origin[2] < original[2]:
                use_down = True
            else:
                up = list(s.origin)
                # decide which one went farther
                downdist = ((down[0] - original[0]) ** 2 + (down[1] - original[1]) ** 2)
                updist = ((up[0] - original[0]) ** 2 + (up[1] - original[1]) ** 2)
                if downdist >= updist:
                    use_down = True

        if use_down:
            s.origin[:] = down
            s.velocity[:] = downvel
            return blocked

        # copy z value from slide move
        s.velocity[2] = downvel[2]

        if not s.onground and s.waterlevel < 2 and (blocked & BLOCKED_STEP):
            # pm_airstep mode: walking up a 16 unit step kills 16% of horiz vel
            scale = 1.0 - 0.01 * (s.origin[2] - original[2])
            s.velocity[0] *= scale
            s.velocity[1] *= scale

        return blocked

    # ── PM_AirMove ───────────────────────────────────────────────────────────
    def _air_move(self, s: PlayerState, cmd: Cmd):
        fmove, smove = float(cmd.move[0]), float(cmd.move[1])
        fwd = [self._fwd[0], self._fwd[1], 0.0]
        right = [self._right[0], self._right[1], 0.0]
        _normalize(fwd)
        _normalize(right)

        wishvel = [fwd[0] * fmove + right[0] * smove,
                   fwd[1] * fmove + right[1] * smove,
                   0.0]
        wishdir = list(wishvel)
        wishspeed = _normalize(wishdir)

        # clamp to server defined max speed
        if wishspeed > self.mv.maxspeed:
            wishspeed = self.mv.maxspeed

        if s.onground:
            if self.mv.slidefix:
                if s.velocity[2] > 0:
                    s.velocity[2] = 0.0
                self._accelerate(s, wishdir, wishspeed, self.mv.accelerate)
                s.velocity[2] -= self.mv.entgravity * self.mv.gravity * self.frametime
            else:
                s.velocity[2] = 0.0
                self._accelerate(s, wishdir, wishspeed, self.mv.accelerate)
            if not s.velocity[0] and not s.velocity[1]:
                s.velocity[2] = 0.0
                return 0
            return self._step_slide_move(s, False)
        else:
            # not on ground, so little effect on velocity
            # (mvdsv passes movevars.accelerate here, not airaccelerate)
            self._air_accelerate(s, wishdir, wishspeed, self.mv.accelerate)
            # add gravity
            s.velocity[2] -= self.mv.entgravity * self.mv.gravity * self.frametime
            if self.mv.airstep:
                return self._step_slide_move(s, True)
            return self._slide_move(s)

    # ── PM_WaterMove ─────────────────────────────────────────────────────────
    def _water_move(self, s: PlayerState, cmd: Cmd):
        fmove, smove, umove = (float(cmd.move[0]), float(cmd.move[1]), float(cmd.move[2]))
        wishvel = [self._fwd[i] * fmove + self._right[i] * smove for i in range(3)]
        if not fmove and not smove and not umove:
            wishvel[2] -= 60.0  # drift towards bottom
        else:
            wishvel[2] += umove

        wishdir = list(wishvel)
        wishspeed = _normalize(wishdir)
        if wishspeed > self.mv.maxspeed:
            wishspeed = self.mv.maxspeed
        wishspeed *= 0.7

        # water acceleration
        self._accelerate(s, wishdir, wishspeed, self.mv.wateraccelerate)
        return self._step_slide_move(s, False)

    # ── PM_PlayerMove (per-frame entry) ──────────────────────────────────────
    def run_frame(self, s: PlayerState, cmd: Cmd):
        self.frametime = cmd.msec * 0.001
        self._fwd, self._right = angle_vectors(cmd.angles)

        # SV_RunCmd "broken ankle" carry-in
        if s.velocity[2] == -270.0 and (cmd.buttons & BUTTON_JUMP):
            s.jump_held = True

        self._nudge_position(s)

        # set onground, watertype, and waterlevel
        self._categorize(s)

        if s.waterlevel == 2:
            self._check_water_jump(s)

        if s.velocity[2] < 0:
            s.waterjumptime = 0.0

        if s.waterjumptime:
            s.waterjumptime -= self.frametime
            if s.waterjumptime < 0:
                s.waterjumptime = 0.0

        # (jump_msec is always zero server-side; no accumulation)
        self._check_jump(s, cmd)

        self._friction(s)

        if s.waterlevel >= 2:
            self._water_move(s, cmd)
        else:
            self._air_move(s, cmd)

        # set onground, watertype, and waterlevel for final spot
        self._categorize(s)

        # !pground: landing clip (landing sound / falling damage correctness)
        if s.onground and s.velocity[2] < -300:
            v, n = s.velocity, s.groundnormal
            if (v[0] * n[0] + v[1] * n[1] + v[2] * n[2]) < MAX_JUMPFIX_DOTPRODUCT:
                s.velocity = clip_velocity(v, n, 1.0)
        return s


# ── replay input loaders ──────────────────────────────────────────────────────
def load_cmds_file(path):
    """komodobots.replay.v1: msec ox oy oz vx vy vz pitch yaw roll fwd side up buttons."""
    frames = []
    for ln in Path(path).read_text().splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        p = ln.split()
        if len(p) < 14:
            continue
        frames.append({
            "msec": int(p[0]),
            "origin": [float(p[1]), float(p[2]), float(p[3])],
            "velocity": [float(p[4]), float(p[5]), float(p[6])],
            "angles": [float(p[7]), float(p[8]), float(p[9])],
            "move": [int(p[10]), int(p[11]), int(p[12])],
            "buttons": int(p[13]),
        })
    return frames


def load_botlog(path, collapse_duplicates=True):
    """moveprobe-commands.json -> same per-frame dict shape as load_cmds_file.

    collapse_duplicates: KTX occasionally emits two FBMOVEPROBE_CMD records in
    the same server frame (identical time_s + origin + velocity); only the LAST
    SetBotCMD of a frame is executed by SV_RunBots, so the first record of each
    duplicate pair is dropped (its cmd never ran).
    """
    doc = json.loads(Path(path).read_text())
    frames = []
    for r in doc["commands"]:
        a, m, o = r["angles"], r["move"], r["origin"]
        wv = r.get("water_state", {}).get("velocity", {})
        frames.append({
            "msec": int(r["msec"]),
            "origin": [o["x"], o["y"], o["z"]],
            "velocity": [wv.get("x", 0.0), wv.get("y", 0.0), wv.get("z", 0.0)],
            "angles": [a["pitch"], a["yaw"], a["roll"]],
            "move": [m["forward"], m["side"], m["up"]],
            "buttons": int(r["buttons"]),
            "time_s": r.get("time_s"),
        })
    if collapse_duplicates:
        dup = set()
        for k in range(len(frames) - 1):
            f, g = frames[k], frames[k + 1]
            if (f["time_s"] == g["time_s"] and f["origin"] == g["origin"]
                    and f["velocity"] == g["velocity"]):
                dup.add(k)
        frames = [f for k, f in enumerate(frames) if k not in dup]
    return frames


def detect_teleports(frames, slack=64.0):
    """Frames where the recorded displacement exceeds what the recorded velocity
    could produce — teleporter rides / respawns in the recording. Returns the
    set of indices k where the jump happens between row k and row k+1."""
    out = []
    for k in range(len(frames) - 1):
        f, g = frames[k], frames[k + 1]
        dt = f["msec"] * 0.001
        vmax = max(math.hypot(f["velocity"][0], f["velocity"][1]),
                   math.hypot(g["velocity"][0], g["velocity"][1]))
        budget = (vmax + 320.0) * dt + slack
        d = math.dist(f["origin"][:2], g["origin"][:2])
        if d > budget:
            out.append(k)
    return out


# ── replay / validation ───────────────────────────────────────────────────────
def replay(world, frames, max_frames=None, anchored=False, movevars=None,
           diverge_thresh=4.0, reanchor_at=(), reanchor_every=None,
           force_jump_held=()):
    """Replay recorded inputs through pmove.

    Free-run (default): start from frame0 recorded state, integrate forward,
    compare sim origin to the recorded origin of the NEXT frame (recorded row k
    = state before cmd k).

    Anchored: reset state to the recorded state every frame before stepping —
    isolates per-step physics error from compounding drift.

    reanchor_at: frame indices where the recording teleports (teleporter /
    respawn); the sim state is reset to the recorded post-teleport state.

    reanchor_every: also re-anchor every N frames (segmented free-run; per-
    segment horizon fidelity when the input log is quantized).

    force_jump_held: frame indices where jump_held is forced true before the
    cmd runs (documented server-side input seams, e.g. the bot's first
    post-spawn jump which the live server ate).
    """
    pm = Pmove(world, movevars)
    n = len(frames) - 1
    if max_frames is not None:
        n = min(n, max_frames)
    reanchor_at = set(reanchor_at)
    force_jump_held = set(force_jump_held)

    s = PlayerState(frames[0]["origin"], frames[0]["velocity"])
    rows = []
    first_div = None
    water_frames = 0

    for k in range(n):
        f = frames[k]
        if (anchored or (k > 0 and (k - 1) in reanchor_at)
                or (reanchor_every and k % reanchor_every == 0 and k > 0)):
            s = PlayerState(f["origin"], f["velocity"], jump_held=s.jump_held,
                            waterjumptime=s.waterjumptime)
        if k in force_jump_held:
            s.jump_held = True
        cmd = Cmd(f["msec"], f["angles"], f["move"], f["buttons"])
        pm.run_frame(s, cmd)
        if s.waterlevel >= 2:
            water_frames += 1
            regime = "water"
        elif s.onground:
            regime = "ground"
        else:
            regime = "air"

        rec = frames[k + 1]
        dx = s.origin[0] - rec["origin"][0]
        dy = s.origin[1] - rec["origin"][1]
        dz = s.origin[2] - rec["origin"][2]
        err = math.sqrt(dx * dx + dy * dy + dz * dz)
        vh = math.hypot(s.velocity[0], s.velocity[1])
        rows.append({
            "frame": k + 1,
            "err": round(err, 3),
            "err_h": round(math.hypot(dx, dy), 3),
            "err_v": round(abs(dz), 3),
            "sim_origin": [round(c, 3) for c in s.origin],
            "rec_origin": rec["origin"],
            "sim_vh": round(vh, 2),
            "sim_vz": round(s.velocity[2], 2),
            "regime": regime,
            "waterlevel": s.waterlevel,
            "teleport_reanchor": k in reanchor_at,
        })
        if first_div is None and err > diverge_thresh and k not in reanchor_at:
            first_div = k + 1

    errs = [r["err"] for r in rows if not r["teleport_reanchor"]]
    summary = {
        "frames_simulated": len(rows),
        "first_divergence_frame": first_div,
        "max_err": round(max(errs), 3) if errs else None,
        "mean_err": round(sum(errs) / len(errs), 3) if errs else None,
        "p95_err": round(sorted(errs)[int(0.95 * (len(errs) - 1))], 3) if errs else None,
        "water_frames": water_frames,
        "anchored": anchored,
        "diverge_thresh": diverge_thresh,
        "reanchor_at": sorted(reanchor_at),
        "reanchor_every": reanchor_every,
        "force_jump_held": sorted(force_jump_held),
    }
    return summary, rows


def speed_at_frame(rows, frame):
    for r in rows:
        if r["frame"] == frame:
            return r["sim_vh"]
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["replay"])
    ap.add_argument("--bsp", default=r"C:\nQuake\qw\maps\dm3.bsp")
    ap.add_argument("--cmds", help="human .cmds replay file")
    ap.add_argument("--botlog", help="moveprobe-commands.json bot log")
    ap.add_argument("--frames", type=int, default=None, help="max frames to simulate")
    ap.add_argument("--anchored", action="store_true",
                    help="re-anchor to recorded state each frame (per-step error)")
    ap.add_argument("--reanchor-every", type=int, default=None,
                    help="segmented free-run: re-anchor every N frames")
    ap.add_argument("--force-jump-held", default="",
                    help="comma-separated frame indices to force jump_held=true")
    ap.add_argument("--no-teleport-reanchor", action="store_true",
                    help="do not re-anchor at detected recording teleports")
    ap.add_argument("--json", help="write per-frame rows + summary to this JSON file")
    args = ap.parse_args()

    world = WorldModel.load(args.bsp)

    if args.cmds:
        frames = load_cmds_file(args.cmds)
    elif args.botlog:
        frames = load_botlog(args.botlog)
    else:
        ap.error("need --cmds or --botlog")

    fjh = [int(x) for x in args.force_jump_held.split(",") if x.strip()]
    tele = [] if args.no_teleport_reanchor else detect_teleports(frames)
    summary, rows = replay(world, frames, max_frames=args.frames,
                           anchored=args.anchored, reanchor_at=tele,
                           reanchor_every=args.reanchor_every,
                           force_jump_held=fjh)
    print(json.dumps(summary, indent=2))
    if args.json:
        Path(args.json).write_text(json.dumps(
            {"summary": summary, "rows": rows}, indent=1))
        print(f"wrote {args.json}")


if __name__ == "__main__":
    sys.setrecursionlimit(20000)
    main()
