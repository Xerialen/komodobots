#!/usr/bin/env python3
"""Mode-23 control-law + frogbot-nav simulation over pmove_sim (issue #69, P3b A1).

Closed-loop offline simulation of the deployed mode-23 bot on dm3:

  * PHYSICS: scripts/pmove_sim.py (validated mvdsv pmove port) — unchanged.
  * CONTROL LAW: a line-by-line port of the mode-23 block in the deployed KTX
    fork's BotApplyMoveProbe (source of truth:
    C:/Users/benya/.claude/jobs/frogbot-study/bot_movement.c, lines 3551-3886,
    byte-identical to the servexeri build mirror). Config variants:
      c1 = carrot, NO climb guard on the handover
      c4 = carrot + BROAD guard (onground && marker_dz > 18 only)
      c5 = carrot + DELEGATION-EXACT guard (adds dist < 280 && !jump-flags)
    Delegation (the grounded-climb early-return to vanilla actuation, with the
    3 s same-marker livelock release) is present in ALL configs (P1 v8).
  * NAV: a frogbot navigation stub driven by the LIVE marker graph (FBMARKER
    dump from matchless run 20260609T213552Z) with frogbot's own selection
    machinery ported (ProcessNewLinkedMarker -> PathScoringLogic -> EvalPath,
    g_random replaced by a seeded RNG). ZoneMarker/SubZoneArrivalTime's
    precomputed zone tables are emulated with exact Dijkstra over the path
    graph using frogbot's own edge times (TravelTimeForPath: dist/320, water
    dist/224, teleporter source 0) — see the seam audit for the difference.
  * MARKER TOUCH: engine trigger-intersection (FL_ITEM abs-box expansion) +
    check_marker rules (closest-of-frame by 3D distance to absmin+view_ofs,
    z-condition, CanDamage line-of-sight) on 0.03 s marker frames.
  * TELEPORTERS: trigger volumes + destinations parsed from the BSP entities
    lump; teleport_player semantics (origin = dest+27z at spawn, velocity =
    300 * forward(mangle)) + BotsPostTeleport marker handover.

Metrics are NEVER computed here: trace rows are handed to route_metrics /
verify_route (single metric implementation).

CLI:
  python mode23_sim.py calibrate --config c5 --seeds 30 --out artifacts/p3b-calibration
  python mode23_sim.py run --config c5 --seed 1            # one attempt, summary
  python mode23_sim.py audit-selection                     # nav stub vs live c5 logs
"""

from __future__ import annotations

import argparse
import heapq
import json
import math
import random
import re
import statistics
import struct
import sys
from pathlib import Path

sys.setrecursionlimit(20000)

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from pmove_sim import (  # noqa: E402
    CONTENTS_EMPTY, CONTENTS_SOLID, CONTENTS_WATER,
    Cmd, PlayerState, Pmove, Trace, WorldModel, _recursive_hull_check,
)

REPO = SCRIPTS.parent
RUNS = REPO / "artifacts" / "lab-runs"
EVID = REPO / "experiments" / "p3b_calibration" / "evidence"

DEFAULT_BSP = r"C:\nQuake\qw\maps\dm3.bsp"
FBMARKER_RUN = "20260609T213552Z"   # matchless run with k_fb_moveprobe_dump_markers 1

# ── frogbot constants (include/fb_globals.h; ledger-verified 0x200=ROCKET_JUMP) ──
WATERJUMP_ = 1 << 1
ROCKET_JUMP = 1 << 9
JUMP_LEDGE = 1 << 10
JUMP_FLAGS = JUMP_LEDGE | WATERJUMP_ | ROCKET_JUMP
PATH_SCORE_NULL = -1e6          # sufficiently below any reachable score
NUMBER_PATHS = 8

# mode-23 cvar defaults (bot_movement.c:3580-3589; the c5 lab cfg sets none of
# the k_fb_moveprobe_s2*/accel cvars, so the in-code defaults below applied)
PASS_R = 130.0
NUMERATOR = 9.0
BOOTSTRAP_DEG = 25.0
LOOK = 500.0
SWING = 12.0
TURN_THRESH = 35.0
CORNER_AIM = 68.0
CORNER_THRESH = 58.0
SV_MAXSPEED = 320.0
SV_MAXWATERSPEED = SV_MAXSPEED * 0.7    # bot_commands.c:2661
DELEG_DZ = 18.0
DELEG_DIST = 280.0
DELEG_TIMEOUT = 3.0

LOOKAHEAD_TIME = 17.5   # skill.lookahead_time at k_fb_skill 10:
                        # RangeOverSkill(10, 5, 30) = 5 + 0.5*25 (bot_botimp.c:161)

# live cmd cadence on the c5 block (msec histogram over 10 runs; the four
# dominant buckets, renormalized — see calibration report)
MSEC_CHOICES = (10, 11, 20, 21)
MSEC_WEIGHTS = (0.512, 0.218, 0.136, 0.134)

MARKER_FRAME_INTERVAL = 0.03    # bot_commands.c:2701 TimeTrigger
PLAYER_MINS = (-16.0, -16.0, -24.0)
PLAYER_MAXS = (16.0, 16.0, 32.0)
FL_ITEM_EXPAND = 15.0           # SV_LinkEdict FL_ITEM xy expansion
NONITEM_EXPAND = 1.0

# sng_shortcut2 directed-run parameters (live c5 block 20260610T013959Z-014904Z)
SPAWN = (385.5, 614.25, 56.0)
GOAL_MARKER = 191               # k_fb_moveprobe_fixed_goal 191
RUN_BUDGET_S = 48.1             # live cmd-log window (t 7.32 -> 55.40)


# ── vector / angle helpers (QC semantics) ────────────────────────────────────
def vectoyaw(v):
    if v[1] == 0 and v[0] == 0:
        return 0.0
    yaw = math.degrees(math.atan2(v[1], v[0]))
    return yaw + 360.0 if yaw < 0 else yaw


def rotate2d(v, deg):
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    return [v[0] * c - v[1] * s, v[0] * s + v[1] * c, 0.0]


def norm2d(v):
    l = math.hypot(v[0], v[1])
    if l <= 0:
        return [0.0, 0.0, 0.0], 0.0
    return [v[0] / l, v[1] / l, 0.0], l


def norm3d(v):
    l = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if l <= 0:
        return [0.0, 0.0, 0.0], 0.0
    return [v[0] / l, v[1] / l, v[2] / l], l


def line_fraction(world: WorldModel, start, end):
    """KTX traceline equivalent: point trace through worldmodel hull 0."""
    tr = Trace(list(end))
    _recursive_hull_check(world.hull0, world.hull0.firstclipnode, 0.0, 1.0,
                          list(start), list(end), tr)
    return tr.fraction


# ── BSP entities lump (teleporters + submodel bounds) ────────────────────────
def parse_bsp_entities(path):
    data = Path(path).read_bytes()
    eo, el = struct.unpack_from("<ii", data, 4 + 0 * 8)   # lump 0 = entities
    text = data[eo:eo + el].split(b"\0")[0].decode("latin-1")
    ents, cur = [], None
    for line in text.splitlines():
        line = line.strip()
        if line == "{":
            cur = {}
        elif line == "}":
            if cur is not None:
                ents.append(cur)
            cur = None
        elif cur is not None:
            m = re.match(r'"([^"]+)"\s+"([^"]*)"', line)
            if m:
                cur[m.group(1)] = m.group(2)
    # submodel bounds (models lump: 9 floats = mins, maxs, origin)
    mo, ml = struct.unpack_from("<ii", data, 4 + 14 * 8)
    nmodels = ml // 64
    bounds = []
    for k in range(nmodels):
        m = struct.unpack_from("<9f", data, mo + k * 64)
        bounds.append(((m[0], m[1], m[2]), (m[3], m[4], m[5])))
    return ents, bounds


class Teleporter:
    __slots__ = ("absmin", "absmax", "dest", "mangle_yaw")

    def __init__(self, absmin, absmax, dest, mangle_yaw):
        self.absmin = absmin
        self.absmax = absmax
        self.dest = dest            # destination origin (already +27 z)
        self.mangle_yaw = mangle_yaw


def load_teleporters(bsp_path):
    """trigger_teleport volumes + info_teleport_destination targets.

    Stored bounds = the trigger's ABS box only: brush bounds resized by
    fb_spawn_trigger_teleport (mins-32 / maxs+32 on xy) plus the engine
    non-FL_ITEM abs expansion (+-1 all axes; BecomeMarker sets no FL_ITEM).
    The player's own abs box is applied at the intersection test in
    run_attempt — NOT here (Codex PR #83 P2: double expansion made the
    trigger ~17 qu too large per side)."""
    ents, bounds = parse_bsp_entities(bsp_path)
    dests = {}
    for e in ents:
        if e.get("classname") == "info_teleport_destination":
            org = [float(x) for x in e["origin"].split()]
            org[2] += 27.0          # SP_info_teleport_destination
            dests[e.get("targetname", "")] = (org, float(e.get("angle", 0)))
    teles = []
    for e in ents:
        if e.get("classname") != "trigger_teleport":
            continue
        model = e.get("model", "")
        if not model.startswith("*"):
            continue
        mins, maxs = bounds[int(model[1:])]
        dest, yaw = dests.get(e.get("target", ""), (None, 0.0))
        if dest is None:
            continue
        grow = 32.0 + NONITEM_EXPAND
        absmin = (mins[0] - grow, mins[1] - grow, mins[2] - NONITEM_EXPAND)
        absmax = (maxs[0] + grow, maxs[1] + grow, maxs[2] + NONITEM_EXPAND)
        teles.append(Teleporter(absmin, absmax, dest, yaw))
    return teles


# ── marker graph ─────────────────────────────────────────────────────────────
# classname -> (mins, maxs) per the KTX spawn code (items.c / marker_load /
# bot_loadmap). "marker" / spawnpoints / teleport destinations use the marker
# box. All are FL_ITEM (xy +-15 abs expansion, no z expansion).
CLASS_BBOX = {
    "marker": ((-65, -65, -24), (65, 65, 32)),
    "info_player_deathmatch": ((-65, -65, -24), (65, 65, 32)),
    "info_teleport_destination": ((-65, -65, -51), (65, 65, 32)),
    "weapon_supershotgun": ((-16, -16, 0), (16, 16, 56)),
    "weapon_nailgun": ((-16, -16, 0), (16, 16, 56)),
    "weapon_supernailgun": ((-16, -16, 0), (16, 16, 56)),
    "weapon_grenadelauncher": ((-16, -16, 0), (16, 16, 56)),
    "weapon_rocketlauncher": ((-16, -16, 0), (16, 16, 56)),
    "weapon_lightning": ((-16, -16, 0), (16, 16, 56)),
    "item_shells": ((0, 0, 0), (32, 32, 56)),
    "item_spikes": ((0, 0, 0), (32, 32, 56)),
    "item_rockets": ((0, 0, 0), (32, 32, 56)),
    "item_cells": ((0, 0, 0), (32, 32, 56)),
    "item_health": ((0, 0, 0), (32, 32, 56)),
    "item_armor1": ((-16, -16, 0), (16, 16, 56)),
    "item_armor2": ((-16, -16, 0), (16, 16, 56)),
    "item_armorInv": ((-16, -16, 0), (16, 16, 56)),
    "item_artifact_invulnerability": ((-16, -16, -24), (16, 16, 32)),
    "item_artifact_invisibility": ((-16, -16, -24), (16, 16, 32)),
    "item_artifact_super_damage": ((-16, -16, -24), (16, 16, 32)),
}
VIEW_OFS = (80.0, 80.0, 24.0)   # StartItemFB / spawn_marker
# classes whose view_ofs z is floor-adjusted at load (adjust_view_ofs_z is
# called by the bot_loadmap spawners, NOT by the .bot marker loader)
FLOOR_ADJUST_CLASSES = {"info_player_deathmatch", "info_teleport_destination",
                        "plat", "trigger_teleport"}

FBMARKER_RE = re.compile(
    r"FBMARKER (\d+) (\S+) (-?\d+) (-?\d+) (-?\d+) G(\d+) Z(\d+) P\[ (.*?)\]")


class Marker:
    __slots__ = ("num", "cls", "org", "G", "Z", "paths", "nav", "absmin",
                 "absmax", "center", "in_water")

    def __init__(self, num, cls, org, G, Z, paths):
        self.num = num
        self.cls = cls
        self.org = org
        self.G = G
        self.Z = Z
        self.paths = paths          # list[(next_num, flags)]
        self.nav = None             # absmin + view_ofs (frogbot marker position)
        self.absmin = None
        self.absmax = None
        self.center = None          # abs box center (LocateMarker metric)
        self.in_water = False


def parse_fbmarker_dump(path):
    """Parse the FBMARKER dump (live marker graph) out of a screen.log."""
    markers = {}
    for ln in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        m = FBMARKER_RE.search(ln)
        if not m:
            continue
        num = int(m.group(1))
        if num in markers:
            continue                # dump repeats if the cvar stays set
        paths = []
        for p in m.group(8).split():
            n, f = p.split(":")
            paths.append((int(n), int(f, 16)))
        markers[num] = Marker(
            num, m.group(2),
            (float(m.group(3)), float(m.group(4)), float(m.group(5))),
            int(m.group(6)), int(m.group(7)), paths)
    return markers


def _resolve(live: Path, committed: Path) -> Path:
    return live if live.exists() else committed


def default_dump_path():
    return _resolve(RUNS / FBMARKER_RUN / "screen.log", EVID / "fbmarker-dm3.txt")


class NavGraph:
    """Live marker graph + frogbot travel-time emulation."""

    def __init__(self, markers, world: WorldModel, bsp_path=DEFAULT_BSP,
                 model_bounds=None):
        self.markers = markers
        self.world = world
        if model_bounds is None:
            _, model_bounds = parse_bsp_entities(bsp_path)
        self._position_markers(model_bounds)
        self._compute_path_times()

    # — positions —
    def _position_markers(self, model_bounds):
        for mk in self.markers.values():
            if mk.cls == "plat":
                # brush entity: dumped origin is the bmodel origin (0,0,z);
                # find the plat model whose z matches. Plats are NOT traced by
                # pmove_sim (submodel caveat) — positions only used for nav.
                best = None
                for mins, maxs in model_bounds[1:]:
                    if abs(mins[2] + maxs[2]) > 1e9:
                        continue
                    best = best or (mins, maxs)
                # fall back to a box around the dumped origin
                mins = (-32, -32, -8)
                maxs = (32, 32, 8)
                mk.absmin = (mk.org[0] + mins[0], mk.org[1] + mins[1], mk.org[2] + mins[2])
                mk.absmax = (mk.org[0] + maxs[0], mk.org[1] + maxs[1], mk.org[2] + maxs[2])
                mk.nav = (mk.org[0], mk.org[1], mk.org[2] + 8.0)
            elif mk.cls in ("trigger_teleport", "trigger_changelevel"):
                # brush marker; nav = volume center (fb_spawn_trigger_teleport
                # view_ofs = half abs size). Use dumped origin (0,0,0 for
                # brushes) replaced by the model bounds if resolvable — the
                # dump's origin for brush entities is the entity origin; dm3's
                # teleporter triggers have origin 0, so locate by Z later.
                mk.absmin = (mk.org[0] - 66, mk.org[1] - 66, mk.org[2] - 25)
                mk.absmax = (mk.org[0] + 66, mk.org[1] + 66, mk.org[2] + 33)
                mk.nav = mk.org
            else:
                mins, maxs = CLASS_BBOX.get(mk.cls, CLASS_BBOX["marker"])
                mk.absmin = (mk.org[0] + mins[0] - FL_ITEM_EXPAND,
                             mk.org[1] + mins[1] - FL_ITEM_EXPAND,
                             mk.org[2] + mins[2])
                mk.absmax = (mk.org[0] + maxs[0] + FL_ITEM_EXPAND,
                             mk.org[1] + maxs[1] + FL_ITEM_EXPAND,
                             mk.org[2] + maxs[2])
                nav = [mk.absmin[0] + VIEW_OFS[0], mk.absmin[1] + VIEW_OFS[1],
                       mk.absmin[2] + VIEW_OFS[2]]
                if mk.cls in FLOOR_ADJUST_CLASSES:
                    nav[2] = self._floor_adjusted_z(nav, mk.absmin[2])
                mk.nav = tuple(nav)
            mk.center = ((mk.absmin[0] + mk.absmax[0]) * 0.5,
                         (mk.absmin[1] + mk.absmax[1]) * 0.5,
                         (mk.absmin[2] + mk.absmax[2]) * 0.5)
            mk.in_water = self._point_contents(mk.nav) <= CONTENTS_WATER

    def _point_contents(self, p):
        from pmove_sim import hull_point_contents
        return hull_point_contents(self.world.hull0, self.world.hull0.firstclipnode, p)

    def _floor_adjusted_z(self, nav, absmin_z):
        """adjust_view_ofs_z: drop a point from nav+1 to the floor; if it lands
        within 56 below, the marker's nav z becomes the floor z."""
        start = (nav[0], nav[1], nav[2] + 1.0)
        end = (nav[0], nav[1], nav[2] + 1.0 - 256.0)
        tr = Trace(list(end))
        _recursive_hull_check(self.world.hull0, self.world.hull0.firstclipnode,
                              0.0, 1.0, list(start), list(end), tr)
        if tr.fraction >= 1.0:
            return nav[2]
        floor_z = tr.endpos[2]
        if floor_z > start[2] - 56.0:
            return floor_z
        return nav[2]

    # — travel times (TravelTimeForPath emulation) —
    def _compute_path_times(self):
        self.edge_time = {}         # (from, to, idx) -> seconds
        for mk in self.markers.values():
            for idx, (to, flags) in enumerate(mk.paths):
                nxt = self.markers.get(to)
                if nxt is None:
                    continue
                if flags & ROCKET_JUMP:
                    t = 100000.0    # non-RJ table: RJ links effectively absent
                elif mk.cls == "trigger_teleport":
                    t = 0.0
                else:
                    d = math.dist(mk.nav, nxt.nav)
                    speed = SV_MAXWATERSPEED if (mk.in_water or nxt.in_water) else SV_MAXSPEED
                    t = d / speed
                self.edge_time[(mk.num, to, idx)] = t

    def traveltime_to(self, goal_num):
        """Dijkstra over the REVERSED path graph from the goal: emulates
        ZoneMarker+SubZoneArrivalTime's precomputed shortest-time tables."""
        rev = {}
        for (frm, to, idx), t in self.edge_time.items():
            rev.setdefault(to, []).append((frm, t))
        dist = {goal_num: 0.0}
        pq = [(0.0, goal_num)]
        while pq:
            d, n = heapq.heappop(pq)
            if d > dist.get(n, math.inf):
                continue
            for frm, t in rev.get(n, ()):
                nd = d + t
                if nd < dist.get(frm, math.inf):
                    dist[frm] = nd
                    heapq.heappush(pq, (nd, frm))
        return dist


# ── frogbot nav stub (selection machinery) ───────────────────────────────────
class NavState:
    """The fb.* fields the mode-23 loop reads/writes."""

    def __init__(self):
        self.touch_marker = None        # marker num
        self.linked_marker = None
        self.old_linked_marker = None
        self.path_state = 0
        self.linked_marker_time = 0.0
        self.touch_marker_time = 0.0
        self.goal_refresh_time = 0.0
        self.frogbot_nextthink = 0.0
        self.prev_touch_marker = None
        self.aware = False
        self.dir_move = [0.0, 0.0, 0.0]
        self.touch_distance = 1e6


class FrogbotBrain:
    """ProcessNewLinkedMarker / PathScoringLogic / marker-touch port."""

    def __init__(self, graph: NavGraph, goal_num: int, rng: random.Random):
        self.g = graph
        self.goal = goal_num
        self.rng = rng
        self.tt = graph.traveltime_to(goal_num)    # traveltime m -> goal

    # — EvalPath (bot_routing.c:46) —
    def eval_path(self, test_num, desc, path_time, origin, player_dir,
                  current_goal_time, goal_late_time):
        if desc & ROCKET_JUMP:
            return PATH_SCORE_NULL          # canRocketJump false (no RL/rockets)
        mk = self.g.markers[test_num]
        d, l = norm3d([mk.nav[0] - origin[0], mk.nav[1] - origin[1],
                       mk.nav[2] - origin[2]])
        same_dir = d[0] * player_dir[0] + d[1] * player_dir[1] + d[2] * player_dir[2]
        score = same_dir + self.rng.random()
        traveltime = self.tt.get(test_num, math.inf)
        total = path_time + traveltime
        if total > goal_late_time:
            if traveltime < current_goal_time:
                score += LOOKAHEAD_TIME - total
            elif total > current_goal_time + 1.25:
                score -= total
        return score

    # — PathScoringLogic (bot_routing.c:198) —
    def path_scoring(self, touch_num, origin, velocity):
        player_dir, _ = norm3d(list(velocity))
        current_goal_time = self.tt.get(touch_num, math.inf)
        if current_goal_time < 2.5:
            goal_late_time = (0.0 - self.rng.random() * 5) - 1e6
        else:
            goal_late_time = (0.0 - self.rng.random() * 10) - 1e6
        # goal_respawn_time is 0 for a pinned plain-marker goal, so
        # goal_late_time is hugely negative -> the bonus branch always applies.
        best = PATH_SCORE_NULL
        new_linked, new_state = None, 0
        # direct: stay on the touch marker itself
        s = self.eval_path(touch_num, 0, 0.0, origin, player_dir,
                           current_goal_time, goal_late_time)
        if s > best:
            best, new_linked, new_state = s, touch_num, 0
        # all paths out of the touch marker
        mk = self.g.markers[touch_num]
        for idx, (to, flags) in enumerate(mk.paths):
            if to not in self.g.markers:
                continue
            pt = self.g.edge_time.get((touch_num, to, idx), math.inf)
            s = self.eval_path(to, flags, pt, origin, player_dir,
                               current_goal_time, goal_late_time)
            if s > best:
                best, new_linked, new_state = s, to, flags
        return new_linked, new_state

    def exists_path(self, frm, to):
        if frm is None or to is None:
            return None
        for nxt, flags in self.g.markers[frm].paths:
            if nxt == to:
                return flags
        return None

    # — ProcessNewLinkedMarker (bot_botpath.c:258), solo-matchless reduction —
    def pnlm(self, nav: NavState, origin, velocity, now):
        # (WaitingToHitGround: WAIT_GROUND unused on dm3 -> skip)
        if nav.linked_marker == nav.touch_marker:
            if nav.touch_marker == self.goal:
                return                      # arrived at the pinned goal: hold
        else:
            f1 = self.exists_path(nav.old_linked_marker, nav.touch_marker)
            if f1 is not None:
                f2 = self.exists_path(nav.touch_marker, nav.linked_marker)
                if f2 is not None:
                    # ExistsPath writes through the SAME pointer twice: the
                    # second call's flags win (bot_botpath.c:299-305)
                    nav.path_state = f2
                    return
        if nav.touch_marker is None:
            return
        new_linked, new_state = self.path_scoring(nav.touch_marker, origin, velocity)
        if new_linked is None:
            new_linked = nav.linked_marker
        nav.linked_marker = new_linked
        nav.path_state = new_state
        nav.linked_marker_time = now + (0.3 if nav.touch_marker == nav.linked_marker else 5.0)
        nav.old_linked_marker = nav.touch_marker

    # — check_marker (marker_util.c:19) + engine trigger intersection —
    def process_touches(self, nav: NavState, origin, now):
        nav.touch_distance = 1e6            # BotPreThink per-frame reset
        pmin = (origin[0] + PLAYER_MINS[0] - 1, origin[1] + PLAYER_MINS[1] - 1,
                origin[2] + PLAYER_MINS[2] - 1)
        pmax = (origin[0] + PLAYER_MAXS[0] + 1, origin[1] + PLAYER_MAXS[1] + 1,
                origin[2] + PLAYER_MAXS[2] + 1)
        for mk in self.g.markers.values():
            if (pmin[0] > mk.absmax[0] or pmax[0] < mk.absmin[0]
                    or pmin[1] > mk.absmax[1] or pmax[1] < mk.absmin[1]
                    or pmin[2] > mk.absmax[2] or pmax[2] < mk.absmin[2]):
                continue
            dist = math.dist(mk.nav, origin)
            if dist >= nav.touch_distance:
                continue
            # player absmin[2] = origin + mins - 1 (non-FL_ITEM abs expansion)
            if not (mk.absmin[2] - 20 < origin[2] + PLAYER_MINS[2] - 1):
                continue
            if not self._can_damage(origin, mk):
                continue
            nav.touch_distance = dist
            nav.touch_marker = mk.num
            nav.touch_marker_time = now + 5.0

    def _can_damage(self, frm, mk):
        """KTX CanDamage(targ=marker, inflictor=player) (combat.c:78): rays
        from the player origin to the marker ORIGIN, then to the four
        half-size bbox corners (origin + mins/maxs * 0.5 on xy)."""
        to = mk.org
        if line_fraction(self.g.world, frm, to) == 1.0:
            return True
        mins, maxs = CLASS_BBOX.get(mk.cls, CLASS_BBOX["marker"])
        for dx, dy in ((maxs[0] * 0.5, maxs[1] * 0.5), (mins[0] * 0.5, maxs[1] * 0.5),
                       (mins[0] * 0.5, mins[1] * 0.5), (maxs[0] * 0.5, mins[1] * 0.5)):
            if line_fraction(self.g.world, frm, (to[0] + dx, to[1] + dy, to[2])) == 1.0:
                return True
        return False

    # — LocateMarker (marker_util.c:162) —
    def locate_marker(self, origin):
        best, best_d = None, 1e6
        for mk in self.g.markers.values():
            d = math.dist(mk.center, origin)
            if d > 1000.0:
                continue
            if line_fraction(self.g.world, origin, mk.center) != 1.0:
                d += 1000.0
            if d < best_d:
                best, best_d = mk.num, d
        return best

    # — BotsThinkTime / PeriodicAllClientLogic (bot_botthink.c) —
    def think(self, nav: NavState, st: PlayerState, now):
        if not (nav.prev_touch_marker != nav.touch_marker or now >= nav.frogbot_nextthink):
            return
        # SetNextThinkTime
        if not st.onground:
            nav.frogbot_nextthink += 0.15 + 0.015 * self.rng.random()
            if nav.frogbot_nextthink <= now:
                nav.frogbot_nextthink = now + 0.16
        nav.prev_touch_marker = nav.touch_marker
        if now >= nav.touch_marker_time:
            located = self.locate_marker(st.origin)
            if located is not None:
                nav.touch_marker = located
                nav.touch_marker_time = now + 5.0
                nav.touch_distance = 0.0
        if nav.touch_marker is None:
            return
        if not nav.aware:
            nav.aware = True
            nav.goal_refresh_time = 0.0
            nav.old_linked_marker = None
            return
        # BotTouchMarkerLogic (goal pinned: UpdateGoal is a timer no-op)
        if now >= nav.goal_refresh_time:
            nav.goal_refresh_time = now + 2 + self.rng.random()
        if now >= nav.linked_marker_time:
            nav.old_linked_marker = None
        if nav.old_linked_marker != nav.touch_marker:
            self.pnlm(nav, st.origin, st.velocity, now)
        if nav.linked_marker is not None:
            self._move_towards_linked(nav, st)

    # — BotMoveTowardsLinkedMarker + BotOnGroundMovement (z-zero) —
    def _move_towards_linked(self, nav: NavState, st: PlayerState):
        mk = self.g.markers[nav.linked_marker]
        d, _ = norm3d([mk.nav[0] - st.origin[0], mk.nav[1] - st.origin[1],
                       mk.nav[2] - st.origin[2]])
        if nav.linked_marker == nav.touch_marker and nav.touch_marker != self.goal:
            # linked==touch and the goal entity is elsewhere: stand
            # (bot_botthink.c:258-271; at the goal itself dir_move is KEPT,
            # the live bot mills around the pinned marker)
            d = [0.0, 0.0, 0.0]
        if st.waterlevel <= 1:
            d[2] = 0.0
        nav.dir_move = d


# ── mode-23 control law (bot_movement.c:3551-3886 port) ──────────────────────
class LawState:
    """The per-slot statics the mode-23 block uses."""

    def __init__(self):
        self.strafe_sign = 0            # moveprobe_accel_strafe_sign
        self.jump_press = False         # moveprobe_accel_jump_press
        self.deleg_since = 0.0          # moveprobe_s23_deleg_since
        self.deleg_marker = None        # moveprobe_s23_deleg_marker
        self.carrot_done = None         # moveprobe_s23_carrot_done


CONFIGS = ("c1", "c4", "c5")


def mode23_step(law: LawState, nav: NavState, brain: FrogbotBrain,
                st: PlayerState, now, config="c5", trace_fn=None,
                carrot_enabled=True):
    """One BotApplyMoveProbe mode-23 evaluation.

    Returns (yaw, move, jump) or None for the vanilla fall-through
    (water / no nav direction / delegated climb leg).

    carrot_enabled=False skips the handover block (the audit-law mode: nav
    state is supplied externally from a live log, so the law itself can be
    compared tick-for-tick against the recorded commands)."""
    g = brain.g
    trace_fn = trace_fn or (lambda a, b: line_fraction(g.world, a, b))
    onground = st.onground
    if st.waterlevel > 1:
        return None

    path_flags = nav.path_state
    if nav.linked_marker is not None and nav.linked_marker != nav.touch_marker:
        mk = g.markers[nav.linked_marker]
        nav_dir = [mk.nav[0] - st.origin[0], mk.nav[1] - st.origin[1],
                   mk.nav[2] - st.origin[2]]
        marker_dist_sq = nav_dir[0] * nav_dir[0] + nav_dir[1] * nav_dir[1]
        marker_dz = nav_dir[2]

        # CARROT: edge-triggered early handover at pass_r, guarded per config
        guard = False
        if config == "c4":      # broad guard (config-2/4): any close climb
            guard = onground and marker_dz > DELEG_DZ
        elif config == "c5":    # delegation-exact guard
            guard = (onground and marker_dz > DELEG_DZ
                     and marker_dist_sq < DELEG_DIST * DELEG_DIST
                     and not (path_flags & JUMP_FLAGS))
        if (carrot_enabled
                and marker_dist_sq < PASS_R * PASS_R
                and law.carrot_done != nav.linked_marker
                and not guard):
            passed = nav.linked_marker
            law.carrot_done = passed
            # SetMarker(self, passed)
            nav.touch_marker = passed
            nav.touch_marker_time = now + 5.0
            nav.touch_distance = 0.0
            brain.pnlm(nav, st.origin, st.velocity, now)
            if (nav.linked_marker is not None and nav.linked_marker != passed
                    and nav.linked_marker != nav.touch_marker):
                mk = g.markers[nav.linked_marker]
                nav_dir = [mk.nav[0] - st.origin[0], mk.nav[1] - st.origin[1],
                           mk.nav[2] - st.origin[2]]
                marker_dist_sq = nav_dir[0] * nav_dir[0] + nav_dir[1] * nav_dir[1]
                marker_dz = nav_dir[2]
            path_flags = nav.path_state
    else:
        nav_dir = list(nav.dir_move)
        marker_dist_sq = 1e18
        marker_dz = 0.0

    nav_dir[2] = 0.0
    nav_dir, l = norm2d(nav_dir)
    if l <= 0:
        return None

    pass_through = marker_dist_sq < PASS_R * PASS_R

    # DELEGATION: grounded climb legs go to vanilla actuation (all configs)
    if (onground and marker_dz > DELEG_DZ
            and marker_dist_sq < DELEG_DIST * DELEG_DIST
            and not (path_flags & JUMP_FLAGS)):
        if law.deleg_marker != nav.linked_marker:
            law.deleg_marker = nav.linked_marker
            law.deleg_since = now
        if (now - law.deleg_since) < DELEG_TIMEOUT:
            return None
    else:
        law.deleg_marker = None

    cur_dir, hs = norm2d([st.velocity[0], st.velocity[1], 0.0])
    hor_speed_sq = hs * hs
    if hs <= 0:
        cur_dir = list(nav_dir)

    goal_yaw = vectoyaw(nav_dir)
    vel_yaw = vectoyaw(cur_dir)
    signed_to_goal = goal_yaw - vel_yaw
    while signed_to_goal > 180.0:
        signed_to_goal -= 360.0
    while signed_to_goal < -180.0:
        signed_to_goal += 360.0
    herr = abs(signed_to_goal)

    if onground:
        # ground frame: full redirect at the marker (climb/wall-hug is dead
        # code in the deployed build: `climb` is constant false)
        proposed = list(nav_dir)
    else:
        hard_corner = False
        if herr > TURN_THRESH and not pass_through:
            sign = 1 if signed_to_goal >= 0 else -1
            law.strafe_sign = sign
            if herr > CORNER_THRESH:
                hard_corner = True
        elif pass_through:
            if law.strafe_sign == 0:
                law.strafe_sign = 1
            sign = law.strafe_sign
        else:
            if law.strafe_sign == 0:
                law.strafe_sign = 1 if signed_to_goal >= 0 else -1
            if law.strafe_sign > 0 and signed_to_goal < -SWING:
                law.strafe_sign = -1
            elif law.strafe_sign < 0 and signed_to_goal > SWING:
                law.strafe_sign = 1
            sign = law.strafe_sign

        # wall safety net
        fp = [st.origin[0] + LOOK * cur_dir[0], st.origin[1] + LOOK * cur_dir[1],
              st.origin[2]]
        fwd_open = trace_fn(st.origin, fp)
        if fwd_open < 0.35:
            ld = rotate2d(cur_dir, 45.0)
            rd = rotate2d(cur_dir, -45.0)
            lp = [st.origin[0] + LOOK * ld[0], st.origin[1] + LOOK * ld[1], st.origin[2]]
            rp = [st.origin[0] + LOOK * rd[0], st.origin[1] + LOOK * rd[1], st.origin[2]]
            left_open = trace_fn(st.origin, lp)
            right_open = trace_fn(st.origin, rp)
            sign = 1 if left_open >= right_open else -1
            law.strafe_sign = sign
            hard_corner = False

        if hard_corner:
            rotation = min(herr, CORNER_AIM)
        elif hor_speed_sq > NUMERATOR * NUMERATOR:
            rotation = math.degrees(math.acos(NUMERATOR / math.sqrt(hor_speed_sq)))
        else:
            rotation = BOOTSTRAP_DEG
        proposed = rotate2d(cur_dir, rotation * sign)
        proposed, pl = norm2d(proposed)
        if pl <= 0:
            proposed = list(cur_dir)

    # (precision governor: REMOVED in config-5; prec_marker is never set)

    if herr > TURN_THRESH and not pass_through:
        press_jump = False
    else:
        press_jump = onground and not law.jump_press
    law.jump_press = press_jump

    yaw = vectoyaw(proposed)
    return yaw, (SV_MAXSPEED, 0, 0), press_jump


# ── attempt runner ───────────────────────────────────────────────────────────
class AttemptResult:
    def __init__(self, rows, events):
        self.rows = rows
        self.events = events


def run_attempt(world, graph, seed, config="c5", budget_s=RUN_BUDGET_S,
                spawn=SPAWN, goal_marker=GOAL_MARKER, goal_pos=None,
                teleporters=None, floor_fn=None):
    """Simulate one directed attempt; returns trace rows in the verify_route
    row shape (t, x, y, z, vh, onground, over_void, dist_goal)."""
    rng = random.Random(seed)
    brain = FrogbotBrain(graph, goal_marker, rng)
    nav = NavState()
    law = LawState()
    pm = Pmove(world)
    st = PlayerState(list(spawn), [0.0, 0.0, 0.0])
    teleporters = teleporters if teleporters is not None else []
    if goal_pos is None:
        goal_pos = graph.markers[goal_marker].nav

    t = 0.0
    next_marker_time = 0.0
    rows, events = [], []
    last_yaw = 90.0

    while t < budget_s:
        msec = rng.choices(MSEC_CHOICES, weights=MSEC_WEIGHTS)[0]
        # StartFrame: marker frame trigger (TimeTrigger 0.03)
        marker_frame = t >= next_marker_time
        if marker_frame:
            next_marker_time += MARKER_FRAME_INTERVAL
            if next_marker_time <= t:
                next_marker_time = t + MARKER_FRAME_INTERVAL

        # BotSetCommand: mode-23 law (may carrot -> SetMarker+PNLM)
        out = mode23_step(law, nav, brain, st, t, config=config)
        if out is not None:
            yaw, move, jump = out
        else:
            # vanilla fall-through: walk toward dir_move_ (delegated climb,
            # water, or no-nav frames); vanilla jumping is false here (no
            # enemies, no JUMP_LEDGE delegation, stairs walked grounded)
            dm, dl = norm2d(list(nav.dir_move)) if st.waterlevel <= 1 else norm3d(list(nav.dir_move))
            if dl <= 0:
                yaw, move, jump = last_yaw, (0, 0, 0), False
            else:
                yaw, move, jump = vectoyaw(dm), (800, 0, 0), False
            # NOTE: the C early-returns leave moveprobe_accel_jump_press
            # untouched, so the toggle static is NOT reset here either
        last_yaw = yaw

        # record the row at cmd time (matches the live moveprobe log)
        vh = math.hypot(st.velocity[0], st.velocity[1])
        fz = floor_fn(st.origin[0], st.origin[1], st.origin[2] + 8.0) if floor_fn else 0.0
        rows.append({
            "t": round(t, 3), "x": st.origin[0], "y": st.origin[1], "z": st.origin[2],
            "vh": vh, "onground": int(st.onground),
            "over_void": int(fz is None or (fz is not None and fz < -200.0)) if floor_fn else 0,
            "dist_goal": math.dist(st.origin, goal_pos),
            "touch": nav.touch_marker, "linked": nav.linked_marker,
        })

        cmd = Cmd(msec, (0.0, yaw, 0.0), move, 2 if jump else 0)
        pm.run_frame(st, cmd)
        t += msec * 0.001

        # teleporter volumes (engine trigger touch during the move)
        for tp in teleporters:
            if (st.origin[0] + PLAYER_MINS[0] - 1 <= tp.absmax[0]
                    and st.origin[0] + PLAYER_MAXS[0] + 1 >= tp.absmin[0]
                    and st.origin[1] + PLAYER_MINS[1] - 1 <= tp.absmax[1]
                    and st.origin[1] + PLAYER_MAXS[1] + 1 >= tp.absmin[1]
                    and st.origin[2] + PLAYER_MINS[2] - 1 <= tp.absmax[2]
                    and st.origin[2] + PLAYER_MAXS[2] + 1 >= tp.absmin[2]):
                st.origin = list(tp.dest)
                r = math.radians(tp.mangle_yaw)
                st.velocity = [300 * math.cos(r), 300 * math.sin(r), 0.0]
                # BotsPostTeleport: marker handover + immediate think
                dest_mk = brain.locate_marker(st.origin)
                if dest_mk is not None:
                    if nav.linked_marker is not None and nav.touch_marker == nav.linked_marker:
                        nav.linked_marker = dest_mk
                    nav.touch_marker = dest_mk
                    nav.touch_marker_time = t + 5.0
                nav.frogbot_nextthink = t
                events.append({"t": round(t, 3), "event": "teleport"})
                break

        # marker touches (trigger touches happen during the move; processed on
        # marker frames only — bot_commands.c TimeTrigger 0.03)
        if marker_frame:
            brain.process_touches(nav, st.origin, t)

        # PlayerPostThink -> BotsThinkTime
        brain.think(nav, st, t)

    return AttemptResult(rows, events)


# ── analysis (verify_route conditioning, metrics imported) ───────────────────
def analyze_attempt(rows, route):
    """Apply verify_route's attempt segmentation + classification + metrics to
    a sim trace. Returns the per-run dict (reach, arrival attempt tws, ...)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("verify_route", SCRIPTS / "verify_route.py")
    vr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vr)
    from route_metrics import legit_segment, time_weighted_speed

    segs = vr.segment_attempts(rows, route)
    out = {"attempts": [], "reached": False, "arrival_tws": None, "arrival_t": None}
    for s, e in segs:
        seg = legit_segment(rows[s:e], route["tele_entrances"])
        if len(seg) < 3:
            continue
        cls, crl, _, _ = vr.classify(seg, route["geom"])
        tws = time_weighted_speed(seg, route["tele_entrances"], reach=vr.REACH_RL)
        att = {"cls": cls, "closest": round(crl, 1), "tws": round(tws, 1),
               "t0": seg[0]["t"], "t1": seg[-1]["t"]}
        arr_i = next((i for i, r in enumerate(seg) if r["dist_goal"] < vr.REACH_RL), None)
        if arr_i is not None:
            att["arrival_t"] = round(seg[arr_i]["t"] - seg[0]["t"], 1)
        out["attempts"].append(att)
        if cls == "REACHED_RL" and not out["reached"]:
            out["reached"] = True
            out["arrival_tws"] = round(tws, 1)
            out["arrival_t"] = att.get("arrival_t")
    return out


def load_route_cfg():
    import importlib.util
    spec = importlib.util.spec_from_file_location("verify_route", SCRIPTS / "verify_route.py")
    vr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vr)
    return vr.load_route("sng_shortcut2")


# ── selection audit (nav stub vs live c5 logs) ───────────────────────────────
C5_RUNS = ["20260610T013959Z", "20260610T014100Z", "20260610T014200Z",
           "20260610T014301Z", "20260610T014401Z", "20260610T014502Z",
           "20260610T014603Z", "20260610T014703Z", "20260610T014804Z",
           "20260610T014904Z"]


def audit_selection(graph, goal=GOAL_MARKER, runs=C5_RUNS, rng_seed=7):
    """Replay every live (touch -> linked) selection event through the ported
    scorer; report deterministic-part agreement. The g_random noise band means
    near-ties can legitimately flip; 'within_band' counts live choices whose
    deterministic score is within the +-(1+spread) reachable band of argmax."""
    rng = random.Random(rng_seed)
    brain = FrogbotBrain(graph, goal, rng)

    class _ZeroRng:
        def random(self):
            return 0.5
    det = FrogbotBrain(graph, goal, _ZeroRng())

    total = match = within = 0
    mismatches = {}
    for run in runs:
        path = RUNS / run / "moveprobe-commands.json"
        if not path.exists():
            continue
        doc = json.loads(path.read_text())
        prev = None
        for c in doc["commands"]:
            rs, o, w = c["route_state"], c["origin"], c["water_state"]
            if prev is not None:
                prs = prev["route_state"]
                if (rs["linked_marker"] != prs["linked_marker"]
                        and rs["linked_marker"] > 0 and rs["touch_marker"] > 0
                        and rs["touch_marker"] in graph.markers
                        and rs["linked_marker"] in graph.markers):
                    origin = (o["x"], o["y"], o["z"])
                    vel = (w["velocity"]["x"], w["velocity"]["y"], w["velocity"]["z"])
                    picked, _ = det.path_scoring(rs["touch_marker"], origin, vel)
                    total += 1
                    if picked == rs["linked_marker"]:
                        match += 1
                    else:
                        key = (rs["touch_marker"], rs["linked_marker"], picked)
                        mismatches[key] = mismatches.get(key, 0) + 1
                        # band check: is the live choice within the random band?
                        live_s = det.eval_path(
                            rs["linked_marker"],
                            det.exists_path(rs["touch_marker"], rs["linked_marker"]) or 0,
                            _edge_time_for(graph, rs["touch_marker"], rs["linked_marker"]),
                            origin, norm3d(list(vel))[0],
                            det.tt.get(rs["touch_marker"], math.inf), -1e6)
                        best_s = det.eval_path(
                            picked,
                            det.exists_path(rs["touch_marker"], picked) or 0,
                            _edge_time_for(graph, rs["touch_marker"], picked),
                            origin, norm3d(list(vel))[0],
                            det.tt.get(rs["touch_marker"], math.inf), -1e6)
                        if live_s >= best_s - 1.0:
                            within += 1
            prev = c
    return {"events": total, "argmax_match": match,
            "match_pct": round(100.0 * match / total, 1) if total else None,
            "flippable_by_rng": within,
            "explained_pct": round(100.0 * (match + within) / total, 1) if total else None,
            "top_mismatches": sorted(mismatches.items(), key=lambda kv: -kv[1])[:10]}


def _edge_time_for(graph, frm, to):
    for idx in range(NUMBER_PATHS):
        t = graph.edge_time.get((frm, to, idx))
        if t is not None:
            return t
    return 0.0


# ── CLI ──────────────────────────────────────────────────────────────────────
def build_world_and_graph(bsp=DEFAULT_BSP, dump=None):
    world = WorldModel.load(bsp)
    markers = parse_fbmarker_dump(dump or default_dump_path())
    graph = NavGraph(markers, world, bsp_path=bsp)
    return world, graph


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["calibrate", "run", "audit-selection"])
    ap.add_argument("--bsp", default=DEFAULT_BSP)
    ap.add_argument("--dump", default=None, help="FBMARKER dump (screen.log)")
    ap.add_argument("--config", default="c5", choices=CONFIGS)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--seeds", type=int, default=30, help="seed count (1..N)")
    ap.add_argument("--budget", type=float, default=RUN_BUDGET_S)
    ap.add_argument("--out", default=None, help="output dir for calibrate")
    args = ap.parse_args()

    world, graph = build_world_and_graph(args.bsp, args.dump)

    if args.mode == "audit-selection":
        print(json.dumps(audit_selection(graph), indent=2, default=str))
        return

    from bsp_geom import Bsp
    bsp_geom = Bsp.load(args.bsp)
    teles = load_teleporters(args.bsp)
    route = load_route_cfg()
    goal_pos = route["goal"]

    def floor_fn(x, y, z):
        return bsp_geom.floor_z(x, y, z)

    if args.mode == "run":
        res = run_attempt(world, graph, args.seed, config=args.config,
                          budget_s=args.budget, goal_pos=goal_pos,
                          teleporters=teles, floor_fn=floor_fn)
        print(json.dumps(analyze_attempt(res.rows, route), indent=2))
        return

    # calibrate: n seeds for the requested config
    outdir = Path(args.out) if args.out else REPO / "artifacts" / "p3b-calibration"
    outdir.mkdir(parents=True, exist_ok=True)
    results = []
    for seed in range(1, args.seeds + 1):
        res = run_attempt(world, graph, seed, config=args.config,
                          budget_s=args.budget, goal_pos=goal_pos,
                          teleporters=teles, floor_fn=floor_fn)
        a = analyze_attempt(res.rows, route)
        a["seed"] = seed
        a["events"] = res.events
        results.append(a)
        print(f"seed {seed:2d} reach={a['reached']} arrival_tws={a['arrival_tws']} "
              f"arrival_t={a['arrival_t']} attempts={[x['cls'][:12] for x in a['attempts']]}")
    reach = sum(1 for r in results if r["reached"])
    tws = sorted(r["arrival_tws"] for r in results if r["arrival_tws"] is not None)
    # zero-arrival blocks (e.g. a hopeless sweep candidate) must still record
    # their evidence: median is None, never an IndexError (Codex PR #83 P2)
    med = statistics.median(tws) if tws else None
    summary = {"config": args.config, "n": args.seeds, "reach": reach,
               "reach_rate": round(reach / args.seeds, 3),
               "arrival_tws_values": tws,
               "arrival_tws_median": round(med, 1) if med is not None else None}
    print(json.dumps(summary, indent=2))
    (outdir / f"calibration-{args.config}.json").write_text(
        json.dumps({"summary": summary, "results": results}, indent=1))
    print(f"wrote {outdir / f'calibration-{args.config}.json'}")


if __name__ == "__main__":
    main()
