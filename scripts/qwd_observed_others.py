"""qwd_observed_others.py — decode the OBSERVED-OTHER players (in-PVS) from a POV .qwd.

Pure standard library only (struct, math, dataclasses) — obeys the same stdlib-only
gate as the rest of `scripts/`. NO third-party imports.

WHY THIS EXISTS
---------------
A QuakeWorld CLIENT demo (`.qwd`) records the full server->client message stream the
recording client RECEIVED. That stream includes `svc_playerinfo` for EVERY player in the
client's PVS (the players it could see), not just self — see mvdsv
`SV_WritePlayersToClient` (src/sv_ents.c): the per-player loop runs over all
`SV_PlayerVisibleToClient` players and writes one `svc_playerinfo` each. For the
recording client's own entity the server CLEARS `PF_MSEC|PF_COMMAND` (sv_ents.c:645);
for every OTHER player those bits stay set, and the player carries a delta-usercmd with
its commanded view angles.

`build_replay_command_file.build_replay_frames` (the P1 self-POV path) recovers ONLY the
self player's `svc_playerinfo` (anchored at the network-message body offset, playernum ==
serverdata.playernum). That is why the P1 catalog has `actor_ticks = 0`. This module
closes that gap: it does a FULL sequential `svc_*` walk of each QWD server-message body
(the protocol skip table is ported from the authoritative mvd_analyzer Go reader
`parser.skipCommand` + mvdsv `sv_ents.c`), decoding every `svc_playerinfo` (the QWD/PF_
client form, NOT the MVD/DF_ form) at its true offset. The result is the POMDP
**agent_observation** layer (docs/12): the masked view of other actors the human
actually received and acted on — the correct input for behavioral cloning.

SCOPE / LIMITS (reported, not silently assumed):
- Targets the classic CTV/SmackDown `.qwd` corpus: PROTOCOL 28, standard QW, NO FTE
  protocol extensions, NO float coords. `decode_qwd_observed` asserts the serverdata
  protocol and refuses (returns an error) on FTE/floatcoord demos so a wrong skip table
  can never silently corrupt offsets.
- This is the DEMO-OBSERVED presence/state of others (a strong visibility signal, exactly
  what the client saw). The PVS/LOS-mask refinement (bsp_geom raycast -> actor_visibility)
  stays DEFERRED; demo presence is already the visibility ground truth for who was in-PVS.
- A walk that hits an unknown/out-of-table opcode STOPS at that message body (records the
  reason) rather than guessing a length and drifting — same safety stance as the Go reader.
"""
from __future__ import annotations

import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
for _p in (str(REPO_ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Reuse the validated QWD-framing record walker + serverdata recovery (stdlib siblings).
import probe_qwd_route_applicability as probe  # noqa: E402
from tools.qwd_usercmd import qwd_usercmd  # noqa: E402

# ----------------------------------------------------------------------------
# svc opcodes (QW protocol 28). Authoritative: mvd-reader/mvd/types.go.
# ----------------------------------------------------------------------------
SVC_BAD = 0
SVC_NOP = 1
SVC_DISCONNECT = 2
SVC_UPDATESTAT = 3
SVC_SETVIEW = 5
SVC_SOUND = 6
SVC_TIME = 7
SVC_PRINT = 8
SVC_STUFFTEXT = 9
SVC_SETANGLE = 10
SVC_SERVERDATA = 11
SVC_LIGHTSTYLE = 12
SVC_UPDATEFRAGS = 14
SVC_STOPSOUND = 16
SVC_DAMAGE = 19
SVC_SPAWNSTATIC = 20
SVC_SPAWNBASELINE = 22
SVC_TEMP_ENTITY = 23
SVC_SETPAUSE = 24
SVC_CENTERPRINT = 26
SVC_KILLEDMONSTER = 27
SVC_FOUNDSECRET = 28
SVC_SPAWNSTATICSOUND = 29
SVC_INTERMISSION = 30
SVC_FINALE = 31
SVC_CDTRACK = 32
SVC_SELLSCREEN = 33
SVC_SMALLKICK = 34
SVC_BIGKICK = 35
SVC_UPDATEPING = 36
SVC_UPDATEENTERTIME = 37
SVC_UPDATESTATLONG = 38
SVC_MUZZLEFLASH = 39
SVC_UPDATEUSERINFO = 40
SVC_DOWNLOAD = 41
SVC_PLAYERINFO = 42
SVC_NAILS = 43
SVC_CHOKECOUNT = 44
SVC_MODELLIST = 45
SVC_SOUNDLIST = 46
SVC_PACKETENTITIES = 47
SVC_DELTAPACKETENTITIES = 48
SVC_MAXSPEED = 49
SVC_ENTGRAVITY = 50
SVC_SETINFO = 51
SVC_SERVERINFO = 52
SVC_UPDATEPL = 53
SVC_NAILS2 = 54

# PF_* player flags (QWD/client form). Authoritative: qwprot protocol.h, sv_ents.c.
PF_MSEC = 1 << 0
PF_COMMAND = 1 << 1
PF_VELOCITY1 = 1 << 2
PF_MODEL = 1 << 5
PF_SKINNUM = 1 << 6
PF_EFFECTS = 1 << 7
PF_WEAPONFRAME = 1 << 8
PF_DEAD = 1 << 9
PF_GIB = 1 << 10
PF_PMC_SHIFT = 11
PF_PMC_MASK = 7
PF_ONGROUND = 1 << 14   # non-PEXT-TRANS offset (sv_ents.c writes here when FTE trans off)
PF_SOLID = 1 << 15

# CM_* delta-usercmd field bits. Authoritative: protocol.h (note ANGLE2/ANGLE3 ordering),
# writer MSG_WriteDeltaUsercmd (common.c).
CM_ANGLE1 = 1 << 0
CM_ANGLE3 = 1 << 1
CM_FORWARD = 1 << 2
CM_SIDE = 1 << 3
CM_UP = 1 << 4
CM_BUTTONS = 1 << 5
CM_IMPULSE = 1 << 6
CM_ANGLE2 = 1 << 7

# U_* entity-delta bits (svc_packetentities). Authoritative: parser.go skipEntityDelta.
U_ORIGIN1 = 1 << 9
U_ORIGIN2 = 1 << 10
U_ORIGIN3 = 1 << 11
U_ANGLE2 = 1 << 12
U_FRAME = 1 << 13
U_MOREBITS = 1 << 15
U_ANGLE1 = 1 << 0
U_ANGLE3 = 1 << 1
U_MODEL = 1 << 2
U_COLORMAP = 1 << 3
U_SKIN = 1 << 4
U_EFFECTS = 1 << 5

MAX_CLIENTS = 32
ANGLE16_TO_DEG = 360.0 / 65536.0


class QwdDecodeError(RuntimeError):
    """Raised when a body cannot be walked (caller records and moves on)."""


@dataclass(frozen=True)
class ObservedActor:
    """One observed OTHER player at one received-message time."""
    time_s: float
    playernum: int
    origin: tuple  # (x, y, z) qu
    velocity: tuple  # (vx, vy, vz) qu/s
    pitch: float  # deg (commanded view, from delta-usercmd; None-filled 0.0 if absent)
    yaw: float
    roll: float
    frame: int
    alive: bool
    onground: bool
    solid: bool
    pm_code: int


class _Reader:
    """Little-endian cursor over a server-message body. Raises QwdDecodeError on overrun
    so a malformed/truncated body is skipped, never silently misread."""

    __slots__ = ("b", "i", "n")

    def __init__(self, b: bytes, start: int = 0):
        self.b = b
        self.i = start
        self.n = len(b)

    def _need(self, k: int):
        if self.i + k > self.n:
            raise QwdDecodeError("overrun")

    def byte(self) -> int:
        self._need(1)
        v = self.b[self.i]
        self.i += 1
        return v

    def skip(self, k: int):
        if k < 0:
            raise QwdDecodeError("negative skip")
        self._need(k)
        self.i += k

    def short(self) -> int:
        self._need(2)
        v = struct.unpack_from("<h", self.b, self.i)[0]
        self.i += 2
        return v

    def ushort(self) -> int:
        self._need(2)
        v = struct.unpack_from("<H", self.b, self.i)[0]
        self.i += 2
        return v

    def cstring(self):
        end = self.b.find(0, self.i)
        if end < 0:
            raise QwdDecodeError("unterminated string")
        self.i = end + 1


def _skip_delta_usercmd(r: _Reader) -> tuple:
    """Skip a MSG_WriteDeltaUsercmd; return commanded (pitch,yaw,roll) deg (delta vs null,
    so an unset angle means 0.0 in the from=nullcmd encoding the server uses)."""
    bits = r.byte()
    pitch = yaw = roll = 0.0
    if bits & CM_ANGLE1:
        pitch = r.ushort() * ANGLE16_TO_DEG
    if bits & CM_ANGLE2:
        yaw = r.ushort() * ANGLE16_TO_DEG
    if bits & CM_ANGLE3:
        roll = r.ushort() * ANGLE16_TO_DEG
    if bits & CM_FORWARD:
        r.skip(2)
    if bits & CM_SIDE:
        r.skip(2)
    if bits & CM_UP:
        r.skip(2)
    if bits & CM_BUTTONS:
        r.skip(1)
    if bits & CM_IMPULSE:
        r.skip(1)
    r.skip(1)  # msec always written
    return pitch, yaw, roll


def _read_playerinfo(r: _Reader, time_s: float) -> ObservedActor:
    """Decode one svc_playerinfo (QWD/PF_ client form) at r (opcode byte already consumed).
    Mirrors sv_ents.c SV_WritePlayersToClient write order exactly (protocol 28, no FTE)."""
    pnum = r.byte()
    flags = r.ushort()
    ox = r.short() / 8.0
    oy = r.short() / 8.0
    oz = r.short() / 8.0
    frame = r.byte()
    if flags & PF_MSEC:
        r.skip(1)
    pitch = yaw = roll = 0.0
    if flags & PF_COMMAND:
        pitch, yaw, roll = _skip_delta_usercmd(r)
    vel = [0, 0, 0]
    for k in range(3):
        if flags & (PF_VELOCITY1 << k):
            vel[k] = r.short()
    if flags & PF_MODEL:
        r.skip(1)
    if flags & PF_SKINNUM:
        r.skip(1)
    if flags & PF_EFFECTS:
        r.skip(1)
    if flags & PF_WEAPONFRAME:
        r.skip(1)
    return ObservedActor(
        time_s=time_s,
        playernum=pnum,
        origin=(ox, oy, oz),
        velocity=(vel[0], vel[1], vel[2]),
        pitch=pitch, yaw=yaw, roll=roll,
        frame=frame,
        alive=not bool(flags & (PF_DEAD | PF_GIB)),
        onground=bool(flags & PF_ONGROUND),
        solid=bool(flags & PF_SOLID),
        pm_code=(flags >> PF_PMC_SHIFT) & PF_PMC_MASK,
    )


def _skip_entity_delta(r: _Reader, word: int) -> None:
    """Skip a packetentities entity delta (protocol 28, no FTE). Mirrors skipEntityDelta."""
    bits = word & ~0x01FF  # clear entity-number bits 0..8
    low = 0
    if bits & U_MOREBITS:
        low = r.byte()
        bits |= low
    if bits & U_MODEL:
        r.skip(1)
    if bits & U_FRAME:
        r.skip(1)
    if bits & U_COLORMAP:
        r.skip(1)
    if bits & U_SKIN:
        r.skip(1)
    if bits & U_EFFECTS:
        r.skip(1)
    if bits & U_ORIGIN1:
        r.skip(2)
    if low & U_ANGLE1:
        r.skip(1)
    if bits & U_ORIGIN2:
        r.skip(2)
    if bits & U_ANGLE2:
        r.skip(1)
    if bits & U_ORIGIN3:
        r.skip(2)
    if low & U_ANGLE3:
        r.skip(1)


def _skip_packetentities(r: _Reader, delta: bool) -> None:
    if delta:
        r.skip(1)  # from-sequence byte
    while True:
        word = r.ushort()
        if word == 0:
            return
        _skip_entity_delta(r, word)


def _skip_sound(r: _Reader) -> None:
    channel = r.ushort()
    if channel & 0x8000:
        r.skip(1)  # volume
    if channel & 0x4000:
        r.skip(1)  # attenuation
    r.skip(1)      # sound_num
    r.skip(6)      # 3 short coords


def _skip_temp_entity(r: _Reader) -> None:
    te = r.byte()
    if te in (0, 1, 3, 4, 7, 8, 10, 11, 13):
        r.skip(6)
    elif te in (2, 12):
        r.skip(1 + 6)
    elif te in (5, 6, 9):
        r.skip(2 + 12)
    else:
        raise QwdDecodeError("unknown TE %d" % te)


def _skip_spawnbaseline(r: _Reader) -> None:
    r.skip(4)  # model, frame, colormap, skin
    for _ in range(3):
        r.skip(2)  # short coord
        r.skip(1)  # angle byte


def _skip_stringlist(r: _Reader) -> None:
    r.skip(1)  # start index
    while True:
        before = r.i
        r.cstring()
        if r.i - before == 1:  # empty string terminator
            break
    r.skip(1)  # next index


def walk_body(body: bytes, observed: list, time_s: float, body_offset: int = 8) -> dict:
    """Sequentially walk one QWD server-message body from `body_offset` (the QWD
    net-message body offset = 8, past the 2x uint32 sequence header), appending every
    decoded OTHER-or-self svc_playerinfo (as ObservedActor) to `observed`.

    Returns {'playerinfo': n, 'stopped': reason|None}. A body that hits an unknown opcode
    or overruns STOPS cleanly (records the reason) — never guesses a length."""
    if len(body) <= body_offset:
        return {"playerinfo": 0, "stopped": "short_body"}
    r = _Reader(body, body_offset)
    n_pi = 0
    while r.i < r.n:
        try:
            op = r.byte()
            if op == SVC_PLAYERINFO:
                observed.append(_read_playerinfo(r, time_s))
                n_pi += 1
            elif op in (SVC_PACKETENTITIES, SVC_DELTAPACKETENTITIES):
                _skip_packetentities(r, delta=(op == SVC_DELTAPACKETENTITIES))
            elif op == SVC_NOP or op == SVC_BAD:
                pass
            elif op == SVC_TIME:
                r.skip(4)
            elif op == SVC_UPDATESTAT:
                r.skip(2)
            elif op == SVC_UPDATESTATLONG:
                r.skip(5)
            elif op == SVC_UPDATEFRAGS:
                r.skip(3)
            elif op == SVC_UPDATEPING:
                r.skip(3)
            elif op == SVC_UPDATEPL:
                r.skip(2)
            elif op == SVC_UPDATEENTERTIME:
                r.skip(5)
            elif op == SVC_SETANGLE:
                r.skip(3)
            elif op == SVC_SOUND:
                _skip_sound(r)
            elif op == SVC_STOPSOUND:
                r.skip(2)
            elif op == SVC_DAMAGE:
                r.skip(8)
            elif op == SVC_TEMP_ENTITY:
                _skip_temp_entity(r)
            elif op == SVC_MUZZLEFLASH:
                r.skip(2)
            elif op == SVC_SMALLKICK or op == SVC_BIGKICK:
                pass
            elif op == SVC_CHOKECOUNT:
                r.skip(1)
            elif op == SVC_SETPAUSE:
                r.skip(1)
            elif op == SVC_CDTRACK:
                r.skip(1)
            elif op == SVC_SETVIEW:
                r.skip(2)
            elif op == SVC_MAXSPEED or op == SVC_ENTGRAVITY:
                r.skip(4)
            elif op == SVC_NAILS or op == SVC_NAILS2:
                cnt = r.byte()
                r.skip(cnt * (7 if op == SVC_NAILS2 else 6))
            elif op == SVC_SPAWNBASELINE:
                r.skip(2)  # entity number
                _skip_spawnbaseline(r)
            elif op == SVC_SPAWNSTATIC:
                _skip_spawnbaseline(r)
            elif op == SVC_SPAWNSTATICSOUND:
                r.skip(9)
            elif op == SVC_KILLEDMONSTER or op == SVC_FOUNDSECRET:
                pass
            elif op == SVC_PRINT:
                r.skip(1)  # level byte
                r.cstring()
            elif op == SVC_CENTERPRINT or op == SVC_STUFFTEXT or op == SVC_FINALE:
                r.cstring()
            elif op == SVC_LIGHTSTYLE:
                r.skip(1)
                r.cstring()
            elif op == SVC_UPDATEUSERINFO:
                r.skip(1)       # player
                r.skip(4)       # userid (int)
                r.cstring()     # info string
            elif op == SVC_SETINFO:
                r.skip(1)       # player
                r.cstring()     # key
                r.cstring()     # value
            elif op == SVC_SERVERINFO:
                r.cstring()     # key
                r.cstring()     # value
            elif op == SVC_MODELLIST or op == SVC_SOUNDLIST:
                _skip_stringlist(r)
            elif op == SVC_INTERMISSION:
                r.skip(6 + 3)   # pos(3 coord) + angles(3 byte)
            elif op == SVC_DISCONNECT:
                return {"playerinfo": n_pi, "stopped": "disconnect"}
            else:
                return {"playerinfo": n_pi, "stopped": "opcode_%d" % op}
        except QwdDecodeError as e:
            return {"playerinfo": n_pi, "stopped": str(e)}
    return {"playerinfo": n_pi, "stopped": None}


def iter_observed_actors(data: bytes) -> Iterator[ObservedActor]:
    """Yield every observed actor (self + others) across all QWD server-message bodies."""
    observed: list = []
    for rec in probe.iter_qwd_payload_records(data):
        if rec.payload is None:
            continue
        observed.clear()
        walk_body(rec.payload, observed, rec.time_s)
        yield from observed


def decode_qwd_observed(data: bytes) -> dict:
    """Decode all observed-OTHER players from a POV .qwd.

    Returns:
        {ok, self_playernum, level, protocol, n_bodies, n_playerinfo, bodies_clean,
         self_rows, other_rows, others_by_pnum:{pnum:[ObservedActor...]}, stop_reasons:{}}
    On a non-protocol-28 / FTE / floatcoords demo: {ok:False, error, protocol, level}.
    """
    states, sd, scan = probe.extract_playerinfo_samples(data)
    if sd is None:
        return {"ok": False, "error": "no serverdata", "protocol": None, "level": None}
    # Refuse anything but classic protocol-28 standard-coord QW (our skip table's scope).
    if sd.protocol != 28:
        return {"ok": False, "error": "unsupported protocol %d (skip table is proto-28)" % sd.protocol,
                "protocol": sd.protocol, "level": sd.level_name}
    self_num = sd.playernum

    others: dict = {}
    self_rows = 0
    n_bodies = 0
    n_pi = 0
    bodies_clean = 0
    stop_reasons: dict = {}
    observed: list = []
    for rec in probe.iter_qwd_payload_records(data):
        if rec.payload is None:
            continue
        n_bodies += 1
        observed.clear()
        res = walk_body(rec.payload, observed, rec.time_s)
        n_pi += res["playerinfo"]
        if res["stopped"] is None:
            bodies_clean += 1
        else:
            stop_reasons[res["stopped"]] = stop_reasons.get(res["stopped"], 0) + 1
        for a in observed:
            if a.playernum == self_num:
                self_rows += 1
            elif a.playernum < MAX_CLIENTS:
                others.setdefault(a.playernum, []).append(a)

    other_rows = sum(len(v) for v in others.values())
    return {
        "ok": True,
        "self_playernum": self_num,
        "level": sd.level_name,
        "protocol": sd.protocol,
        "n_bodies": n_bodies,
        "n_playerinfo": n_pi,
        "bodies_clean": bodies_clean,
        "self_rows": self_rows,
        "other_rows": other_rows,
        "others_by_pnum": others,
        "stop_reasons": stop_reasons,
    }
