#!/usr/bin/env python3
"""Emit a content manifest for a QuakeWorld POV ``.qwd`` (or compressed ``.qwz``).

The manifest reports the TRUE content read from the demo's recorded network
stream (the map, the protocol, the roster, the recording client identity),
never anything inferred from the filename.

Grounding (all little-endian, verified against ezQuake ``src/cl_parse.c`` and
``src/qwprot/src/protocol.h``):

CONTAINER (reused via ``tools/qwd_usercmd``): a flat sequence of records, each
with a 5-byte header (``float32`` demotime + ``byte`` raw_type;
``message_type = raw_type & 7``).  ``dem_cmd`` carries a 24-byte ``usercmd_t``
plus 12 bytes of viewangles; ``dem_read`` carries an ``int32`` length prefix
then that many bytes of concatenated svc messages.

dem_read body framing: the network-message bodies in these POV demos begin
with two ``int32`` sequence numbers (8 bytes) before the svc stream.  We detect
the svc start by trying offset 0 first and falling back to offset 8 (matching
``scripts/probe_qwd_route_applicability.QWD_NET_MESSAGE_BODY_OFFSET``).

SVC stream: concatenated, NOT individually length-framed.  We size each opcode
to advance.  We DECODE svc_serverdata(11), svc_modellist(45),
svc_updateuserinfo(40), svc_setinfo(51), svc_serverinfo(52); we size the other
opcodes we can; on an opcode we cannot size we abandon the rest of THAT
dem_read block and continue at the next record (``blocks_abandoned``).

This module reuses, and does NOT modify, the readers in
``tools/qwd_usercmd/qwd_usercmd.py`` (container framing, primitive readers,
usercmd struct) and ``scripts/probe_qwd_route_applicability.py``
(``read_c_string``, ``read_coord``).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.qwd_usercmd import qwd_usercmd
from scripts.probe_qwd_route_applicability import read_c_string, read_coord

SCHEMA = "komodobots.qwd_content_manifest.v1"

# --- svc opcodes (src/qwprot/src/protocol.h) ---
SVC_BAD = 0
SVC_NOP = 1
SVC_DISCONNECT = 2
SVC_UPDATESTAT = 3
NQ_SVC_VERSION = 4
NQ_SVC_SETVIEW = 5
SVC_SOUND = 6
NQ_SVC_TIME = 7
SVC_PRINT = 8
SVC_STUFFTEXT = 9
SVC_SETANGLE = 10
SVC_SERVERDATA = 11
SVC_LIGHTSTYLE = 12
NQ_SVC_UPDATENAME = 13
SVC_UPDATEFRAGS = 14
NQ_SVC_CLIENTDATA = 15
SVC_STOPSOUND = 16
NQ_SVC_UPDATECOLORS = 17
NQ_SVC_PARTICLE = 18
SVC_DAMAGE = 19
SVC_SPAWNSTATIC = 20
SVC_FTE_SPAWNSTATIC2 = 21
SVC_SPAWNBASELINE = 22
SVC_TEMP_ENTITY = 23
SVC_SETPAUSE = 24
NQ_SVC_SIGNONNUM = 25
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
SVC_FTE_MODELLISTSHORT = 60
SVC_FTE_SPAWNBASELINE2 = 66
SVC_QIZMOVOICE = 83
SVC_FTE_VOICECHAT = 84

# protocol preamble extension tags (read as int32, each followed by one int32)
FTEX = 0x58455446
FTE2 = 0x32455446
MVD1 = 0x3144564D

PROTOCOL_MIN = 24
PROTOCOL_MAX = 28

# playerinfo flags (POV path)
PF_MSEC = 1 << 0
PF_COMMAND = 1 << 1
PF_VELOCITY1 = 1 << 2
PF_VELOCITY2 = 1 << 3
PF_VELOCITY3 = 1 << 4
PF_MODEL = 1 << 5
PF_SKINNUM = 1 << 6
PF_EFFECTS = 1 << 7
PF_WEAPONFRAME = 1 << 8

# usercmd delta bits (svc_playerinfo PF_COMMAND, MSG_ReadDeltaUsercmd)
CM_ANGLE1 = 1 << 0
CM_ANGLE3 = 1 << 1
CM_FORWARD = 1 << 2
CM_SIDE = 1 << 3
CM_UP = 1 << 4
CM_BUTTONS = 1 << 5
CM_IMPULSE = 1 << 6
CM_ANGLE2 = 1 << 7

# sound flags (CL_ParseStartSoundPacket)
SND_VOLUME = 1 << 15
SND_ATTENUATION = 1 << 14

# packetentities delta bits (CL_ParseDelta / protocol.h U_*)
U_MOREBITS = 1 << 15
U_ORIGIN1 = 1 << 9
U_ORIGIN2 = 1 << 10
U_ORIGIN3 = 1 << 11
U_ANGLE2 = 1 << 12
U_FRAME = 1 << 13
U_REMOVE = 1 << 14
U_ANGLE1 = 1 << 0
U_ANGLE3 = 1 << 1
U_MODEL = 1 << 2
U_COLORMAP = 1 << 3
U_SKIN = 1 << 4
U_EFFECTS = 1 << 5
U_SOLID = 1 << 6

# temp-entity types (protocol.h TE_*) that read a byte count before position
TE_GUNSHOT = 2
TE_EXPLOSION = 3
TE_LIGHTNING1 = 5
TE_LIGHTNING2 = 6
TE_LIGHTNING3 = 9
TE_BLOOD = 12
TE_LIGHTNINGBLOOD = 13

# POV demos default to short coords / char angles (msg_coordsize=2, msg_anglesize=1).
COORD_SIZE = 2
ANGLE_SIZE = 1

# A real .qwd is a clean record container: each record header is a finite
# non-negative float32 demotime plus a valid dem_* type, and length-prefixed
# bodies fit inside the file.  A qizmo container is not, and additionally
# begins with a recognizable signature byte pair.  We validate by walking a
# handful of records rather than trusting any single demotime magnitude
# (legitimate client demos can start at large local demotimes).
QWD_SNIFF_RECORDS = 6
# Largest demotime we will accept for record 0 (seconds).  Generous: covers
# demos that begin well into a server's uptime.
MAX_FIRST_DEMOTIME = 1.0e7

# Autotrack / observer POV name heuristic.
AUTOTRACK_NAME_TOKENS = ("cam", "commentary", "spec", "flood", "qtv")

YAW_CONTINUITY_THRESHOLD_DEG = 60.0
MOVEMENT_CMD_FRACTION_ELIGIBLE = 0.2

QIZMO_BUNDLE_TGZ = Path(
    "/mnt/c/Users/benya/projects/quakeworld/data/challenge-tv-archive/qizmo_bundle.tgz"
)


class SvcSizeError(Exception):
    """Raised when an svc opcode cannot be sized (abandon the dem_read block)."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _norm_angle_yaw(value: float) -> float:
    """Wrap to (-180, 180]."""
    value = math.fmod(value, 360.0)
    if value > 180.0:
        value -= 360.0
    elif value <= -180.0:
        value += 360.0
    return value


# ---------------------------------------------------------------------------
# Compression sniffing / decompression
# ---------------------------------------------------------------------------

_VALID_DEM_TYPES = (
    qwd_usercmd.DEM_CMD,
    qwd_usercmd.DEM_READ,
    qwd_usercmd.DEM_SET,
    qwd_usercmd.DEM_MULTIPLE,
    qwd_usercmd.DEM_SINGLE,
    qwd_usercmd.DEM_STATS,
    qwd_usercmd.DEM_ALL,
)


def looks_like_real_qwd(data: bytes) -> bool:
    """Return True if ``data`` walks as a QWD record container (even if truncated).

    Rather than trusting any single demotime magnitude, validate that the
    leading records have finite non-negative demotimes, valid dem_* types, and
    length-prefixed bodies whose declared length is sane.  A qizmo-compressed
    container fails this on the very first record.

    Truncation is tolerated: if at least ``MIN_CLEAN_RECORDS`` records parsed
    cleanly before a header/body ran past EOF, the input is still a (truncated)
    real ``.qwd`` rather than a compressed container.
    """
    MIN_CLEAN_RECORDS = 2
    if len(data) < qwd_usercmd.RECORD_HEADER_SIZE:
        return False

    cursor = 0
    records = 0
    while cursor < len(data) and records < QWD_SNIFF_RECORDS:
        if cursor + qwd_usercmd.RECORD_HEADER_SIZE > len(data):
            break  # header truncated mid-record
        demotime, raw_type = struct.unpack_from(
            qwd_usercmd.RECORD_HEADER_FORMAT, data, cursor
        )
        if not math.isfinite(demotime) or demotime < 0 or demotime > MAX_FIRST_DEMOTIME:
            return False
        mt = raw_type & 7
        if mt not in _VALID_DEM_TYPES:
            return False
        body_cursor = cursor + qwd_usercmd.RECORD_HEADER_SIZE
        if mt == qwd_usercmd.DEM_CMD:
            body_cursor += qwd_usercmd.USERCMD_STRUCT_SIZE + qwd_usercmd.VIEW_ANGLES_SIZE
        elif mt == qwd_usercmd.DEM_SET:
            body_cursor += 8
        else:  # length-prefixed (READ/SINGLE/STATS/ALL/MULTIPLE)
            if mt == qwd_usercmd.DEM_MULTIPLE:
                body_cursor += 4  # player mask
            if body_cursor + 4 > len(data):
                break  # length prefix truncated
            length, = struct.unpack_from("<i", data, body_cursor)
            body_cursor += 4
            # A declared length that is negative or absurd means this is not a
            # QWD record stream at all.
            if length < 0 or length > qwd_usercmd.MAX_REASONABLE_MESSAGE_BYTES:
                return False
            body_cursor += length
        if body_cursor > len(data):
            # Body runs past EOF: truncated.  Accept only if we have already
            # seen enough clean records to trust the framing.
            return records >= MIN_CLEAN_RECORDS
        cursor = body_cursor
        records += 1

    return records >= 1


def _ensure_qizmo() -> Path | None:
    """Extract the qizmo bundle into a scratch dir; return the qizmo binary dir."""
    work = Path(tempfile.gettempdir()) / "qwz_work"
    bundle_dir = work / "qizmo_bundle"
    qizmo = bundle_dir / "qizmo"
    if qizmo.exists():
        return bundle_dir
    if not QIZMO_BUNDLE_TGZ.exists():
        return None
    work.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            ["tar", "xzf", str(QIZMO_BUNDLE_TGZ), "-C", str(work)],
            check=True,
            capture_output=True,
        )
    except (subprocess.CalledProcessError, OSError):
        return None
    return bundle_dir if qizmo.exists() else None


def decompress_qwz(src: Path, scratch_dir: Path) -> tuple[Path | None, str | None, str | None]:
    """Decompress a qizmo container into ``scratch_dir``.

    Returns (decompressed_path, decompressor_label, error).  Never writes into
    the source corpus.
    """
    bundle_dir = _ensure_qizmo()
    if bundle_dir is None:
        return None, None, "qizmo decompressor unavailable (bundle missing or extraction failed)"

    scratch_dir.mkdir(parents=True, exist_ok=True)
    # qizmo -D writes <name>.qwd next to the input; copy input into scratch first.
    staged = scratch_dir / (src.stem + ".qwz")
    shutil.copyfile(src, staged)

    ld = bundle_dir / "libs" / "ld-linux.so.2"
    libs = bundle_dir / "libs"
    qizmo = bundle_dir / "qizmo"
    staged_abs = str(staged.resolve())
    cmd: list[str]
    if ld.exists():
        cmd = [str(ld), "--library-path", "./libs", "./qizmo", "-D", staged_abs]
    else:
        cmd = ["./qizmo", "-D", staged_abs]
    try:
        # qizmo loads ``compress.dat`` relative to its working directory, so run
        # from the bundle dir (matches the verified manual invocation).
        proc = subprocess.run(
            cmd,
            cwd=str(bundle_dir),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=300,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, None, f"qizmo invocation failed: {exc}"

    out = scratch_dir / (src.stem + ".qwd")
    if not out.exists():
        # Some qizmo builds emit the original-cased name; search the scratch dir.
        candidates = [p for p in scratch_dir.glob("*.qwd")]
        out = candidates[0] if candidates else out
    if not out.exists():
        tail = (proc.stderr or proc.stdout or b"").decode("latin1", "replace")[-300:]
        return None, None, f"qizmo produced no .qwd output (rc={proc.returncode}): {tail}"
    label = f"qizmo (bundle {QIZMO_BUNDLE_TGZ.name})"
    return out, label, None


# ---------------------------------------------------------------------------
# svc stream sizer / decoder
# ---------------------------------------------------------------------------

class SvcReader:
    """Sequential reader over a single dem_read svc stream."""

    def __init__(self, body: bytes, start: int):
        self.b = body
        self.c = start

    def remaining(self) -> int:
        return len(self.b) - self.c

    def need(self, n: int) -> None:
        if self.c + n > len(self.b):
            raise SvcSizeError(f"need {n} bytes at {self.c}, have {len(self.b) - self.c}")

    def byte(self) -> int:
        self.need(1)
        v = self.b[self.c]
        self.c += 1
        return v

    def char(self) -> int:
        v = self.byte()
        return v - 256 if v >= 128 else v

    def short(self) -> int:
        self.need(2)
        v = struct.unpack_from("<h", self.b, self.c)[0]
        self.c += 2
        return v

    def ushort(self) -> int:
        self.need(2)
        v = struct.unpack_from("<H", self.b, self.c)[0]
        self.c += 2
        return v

    def long(self) -> int:
        self.need(4)
        v = struct.unpack_from("<i", self.b, self.c)[0]
        self.c += 4
        return v

    def string(self) -> str:
        s, self.c = read_c_string(self.b, self.c)
        return s

    def coord(self) -> float:
        v, self.c = read_coord(self.b, self.c)
        return v

    def skip(self, n: int) -> None:
        self.need(n)
        self.c += n


def _size_delta_usercmd(r: SvcReader, protover: int) -> None:
    """Advance past a delta usercmd (MSG_ReadDeltaUsercmd), protover>=27 path."""
    bits = r.byte()
    if protover <= 26:
        if bits & CM_ANGLE1:
            r.skip(2)
        r.skip(2)  # angle2 always sent
        if bits & CM_ANGLE3:
            r.skip(2)
        if bits & CM_FORWARD:
            r.skip(1)
        if bits & CM_SIDE:
            r.skip(1)
        if bits & CM_UP:
            r.skip(1)
    else:
        if bits & CM_ANGLE1:
            r.skip(2)
        if bits & CM_ANGLE2:
            r.skip(2)
        if bits & CM_ANGLE3:
            r.skip(2)
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
    if protover <= 26:
        # CM_MSEC == CM_ANGLE2 bit position in old protocol; ezQuake gates on it.
        if bits & CM_ANGLE2:
            r.skip(1)
    else:
        r.skip(1)  # msec always sent


def _size_playerinfo(r: SvcReader, protover: int) -> None:
    """Advance past svc_playerinfo (POV non-MVD path, no FTE float/trans ext)."""
    r.byte()  # num
    flags = r.ushort()
    # origin: 3 coords
    r.skip(3 * COORD_SIZE)
    r.byte()  # frame
    if flags & PF_MSEC:
        r.byte()
    if flags & PF_COMMAND:
        _size_delta_usercmd(r, protover)
    for bit in (PF_VELOCITY1, PF_VELOCITY2, PF_VELOCITY3):
        if flags & bit:
            r.skip(2)
    for bit in (PF_MODEL, PF_SKINNUM, PF_EFFECTS, PF_WEAPONFRAME):
        if flags & bit:
            r.byte()


def _size_sound(r: SvcReader) -> None:
    channel = r.ushort()
    if channel & SND_VOLUME:
        r.byte()
    if channel & SND_ATTENUATION:
        r.byte()
    r.byte()  # sound_num
    r.skip(3 * COORD_SIZE)  # pos


def _size_baseline(r: SvcReader) -> None:
    # CL_ParseBaseline: modelindex/frame/colormap/skinnum bytes, then 3x(coord+angle)
    r.skip(4)
    for _ in range(3):
        r.skip(COORD_SIZE)
        r.skip(ANGLE_SIZE)


def _size_staticsound(r: SvcReader) -> None:
    r.skip(3 * COORD_SIZE)
    r.skip(3)  # sound_num, vol, atten


class ServerData:
    __slots__ = ("protocol", "playernum_raw", "spectator", "slot", "gamedir", "levelname")

    def __init__(self, protocol, playernum_raw, gamedir, levelname):
        self.protocol = protocol
        self.playernum_raw = playernum_raw
        self.spectator = bool(playernum_raw & 0x80)
        self.slot = playernum_raw & 0x7F
        self.gamedir = gamedir
        self.levelname = levelname


def _decode_serverdata(r: SvcReader) -> ServerData:
    # protocol preamble loop
    protover = None
    for _ in range(8):
        pv = r.long()
        if pv in (FTEX, FTE2, MVD1):
            r.long()  # extension value
            continue
        protover = pv
        break
    if protover is None or not (PROTOCOL_MIN <= protover <= PROTOCOL_MAX):
        raise SvcSizeError(f"implausible protocol version {protover}")
    r.long()  # servercount
    gamedir = r.string()
    # POV path: playernum is a single byte (high bit = spectator).
    playernum_raw = r.byte()
    levelname = r.string()
    # movevars: 10 float32 (protover >= 25)
    if protover >= 25:
        r.skip(10 * 4)
    return ServerData(protover, playernum_raw, gamedir, levelname)


def _decode_modellist(r: SvcReader) -> tuple[int, list[str], int]:
    """Return (start_index, model_strings, continuation_byte)."""
    start_index = r.byte()
    models: list[str] = []
    while True:
        s = r.string()
        if not s:
            break
        models.append(s)
    cont = r.byte()
    return start_index, models, cont


def _decode_soundlist(r: SvcReader) -> None:
    r.byte()  # start index
    while True:
        s = r.string()
        if not s:
            break
    r.byte()  # continuation


def _size_delta_entity(r: SvcReader, word: int) -> None:
    """Advance past one CL_ParseDelta entity (non-FTE POV path).

    ``word`` is the 16-bit header already read; low 9 bits are the entity
    number, upper bits are delta flags.  U_MOREBITS pulls in a low byte.
    """
    bits = word & ~511
    if bits & U_MOREBITS:
        bits |= r.byte()
    # U_REMOVE entities carry no payload.
    if bits & U_REMOVE:
        return
    if bits & U_MODEL:
        r.byte()
    if bits & U_FRAME:
        r.byte()
    if bits & U_COLORMAP:
        r.byte()
    if bits & U_SKIN:
        r.byte()
    if bits & U_EFFECTS:
        r.byte()
    if bits & U_ORIGIN1:
        r.skip(COORD_SIZE)
    if bits & U_ANGLE1:
        r.skip(ANGLE_SIZE)
    if bits & U_ORIGIN2:
        r.skip(COORD_SIZE)
    if bits & U_ANGLE2:
        r.skip(ANGLE_SIZE)
    if bits & U_ORIGIN3:
        r.skip(COORD_SIZE)
    if bits & U_ANGLE3:
        r.skip(ANGLE_SIZE)
    # U_SOLID reads nothing.


def _size_packetentities(r: SvcReader, delta: bool) -> None:
    """Advance past svc_packetentities / svc_deltapacketentities (non-FTE POV)."""
    if delta:
        r.byte()  # from-sequence
    while True:
        word = r.ushort()
        if word == 0:
            break
        _size_delta_entity(r, word)


def _size_nails(r: SvcReader, indexed: bool) -> None:
    """Advance past svc_nails / svc_nails2 (CL_ParseProjectiles)."""
    count = r.byte()
    for _ in range(count):
        if indexed:
            r.byte()  # num
        r.skip(6)  # 48 bits of packed origin/angles


def _size_tent(r: SvcReader) -> None:
    """Advance past svc_temp_entity (QW/non-NQ CL_ParseTEnt)."""
    type_ = r.byte()
    if type_ in (TE_LIGHTNING1, TE_LIGHTNING2, TE_LIGHTNING3):
        # CL_ParseBeam: short ent + start coord3 + end coord3
        r.skip(2)
        r.skip(6 * COORD_SIZE)
        return
    if type_ in (TE_GUNSHOT, TE_BLOOD):
        r.byte()  # count
        r.skip(3 * COORD_SIZE)
        return
    if type_ == TE_LIGHTNINGBLOOD:
        r.skip(3 * COORD_SIZE)
        return
    # All remaining QW temp entities read only a position.
    r.skip(3 * COORD_SIZE)


# ---------------------------------------------------------------------------
# Roster model
# ---------------------------------------------------------------------------

def _parse_userinfo(userinfo: str) -> dict[str, str]:
    """Parse a backslash-delimited ``\\key\\value\\...`` userinfo string."""
    info: dict[str, str] = {}
    parts = userinfo.split("\\")
    # parts[0] is the leading empty token before the first backslash
    it = iter(parts[1:]) if parts and parts[0] == "" else iter(parts)
    pairs = list(it)
    for i in range(0, len(pairs) - 1, 2):
        info[pairs[i]] = pairs[i + 1]
    return info


def _slot_is_spectator(userinfo: str) -> bool:
    info = _parse_userinfo(userinfo)
    return info.get("*spectator") == "1" or info.get("spectator") == "1"


def _slot_name(userinfo: str) -> str:
    return _parse_userinfo(userinfo).get("name", "")


def _slot_team(userinfo: str) -> str:
    return _parse_userinfo(userinfo).get("team", "")


def _name_is_autotrack(name: str) -> bool:
    low = name.lower()
    # Specific cam/observer tokens only -- bare "cam"/"spec" substrings are NOT
    # used (they over-match real players like "camper"/"special").
    strong = ("-cam", "_cam", ".cam", "cam-", "cam.", "commentary",
              "autotrack", "qtv", "flood-cam", "floodcam")
    if any(t in low for t in strong):
        return True
    return low in ("cam", "camera", "spec", "spectator", "observer")


# ---------------------------------------------------------------------------
# Main content walk
# ---------------------------------------------------------------------------

def _walk_svc_block(
    body: bytes,
    start: int,
    protover_holder: dict[str, int],
    state: dict,
) -> bool:
    """Walk one dem_read svc stream from ``start``.

    Mutates ``state`` (serverdata, models, userinfo per slot).  Returns True if
    the block was fully consumed, False if abandoned on an unknown/unsizable
    opcode.
    """
    r = SvcReader(body, start)
    while r.remaining() > 0:
        try:
            cmd = r.byte()
            if cmd == SVC_SERVERDATA:
                sd = _decode_serverdata(r)
                state["serverdata"] = sd
                protover_holder["v"] = sd.protocol
            elif cmd == SVC_MODELLIST:
                start_index, models, _cont = _decode_modellist(r)
                # Models are 1-based; the chunk beginning at start_index stores
                # model_name[start_index+1 ..].  index 1 == worldmodel.
                for i, name in enumerate(models):
                    model_index = start_index + 1 + i
                    state["models"].setdefault(model_index, name)
            elif cmd == SVC_FTE_MODELLISTSHORT:
                # extended: start index is a short
                _start = r.ushort()
                while True:
                    s = r.string()
                    if not s:
                        break
                r.byte()
            elif cmd == SVC_SOUNDLIST:
                _decode_soundlist(r)
            elif cmd == SVC_UPDATEUSERINFO:
                slot = r.byte()
                r.long()  # userid
                userinfo = r.string()
                state["userinfo"][slot] = userinfo
            elif cmd == SVC_SETINFO:
                slot = r.byte()
                key = r.string()
                value = r.string()
                existing = state["userinfo"].get(slot, "")
                merged = _apply_setinfo(existing, key, value)
                state["userinfo"][slot] = merged
            elif cmd == SVC_SERVERINFO:
                key = r.string()
                value = r.string()
                state["serverinfo"][key] = value
            # --- sizers for opcodes we walk past ---
            elif cmd in (SVC_NOP, SVC_DISCONNECT, SVC_KILLEDMONSTER, SVC_FOUNDSECRET,
                         SVC_SELLSCREEN, SVC_SMALLKICK, SVC_BIGKICK):
                pass
            elif cmd == SVC_UPDATESTAT:
                r.skip(2)
            elif cmd == SVC_UPDATESTATLONG:
                r.skip(1)
                r.long()
            elif cmd == NQ_SVC_TIME:
                r.skip(4)
            elif cmd == SVC_PRINT:
                r.byte()  # id
                r.string()
            elif cmd == SVC_STUFFTEXT:
                r.string()
            elif cmd == SVC_CENTERPRINT:
                r.string()
            elif cmd == SVC_FINALE:
                r.string()
            elif cmd == SVC_SETANGLE:
                r.skip(3 * ANGLE_SIZE)
            elif cmd == SVC_LIGHTSTYLE:
                r.byte()
                r.string()
            elif cmd == SVC_SOUND:
                _size_sound(r)
            elif cmd == SVC_STOPSOUND:
                r.skip(2)
            elif cmd == SVC_UPDATEFRAGS:
                r.byte()
                r.skip(2)
            elif cmd == SVC_UPDATEPING:
                r.byte()
                r.skip(2)
            elif cmd == SVC_UPDATEPL:
                r.skip(2)
            elif cmd == SVC_UPDATEENTERTIME:
                r.byte()
                r.skip(4)
            elif cmd == SVC_SPAWNBASELINE:
                r.ushort()  # entity number
                _size_baseline(r)
            elif cmd == SVC_SPAWNSTATIC:
                _size_baseline(r)
            elif cmd == SVC_SPAWNSTATICSOUND:
                _size_staticsound(r)
            elif cmd == SVC_CDTRACK:
                r.byte()
            elif cmd == SVC_INTERMISSION:
                r.skip(3 * COORD_SIZE)
                r.skip(3 * ANGLE_SIZE)
            elif cmd == SVC_MUZZLEFLASH:
                r.skip(2)  # short entity
            elif cmd == SVC_DOWNLOAD:
                size = r.short()
                r.byte()  # percent
                if size > 0:
                    r.skip(size)
            elif cmd == SVC_MAXSPEED:
                r.skip(4)
            elif cmd == SVC_ENTGRAVITY:
                r.skip(4)
            elif cmd == SVC_SETPAUSE:
                r.byte()
            elif cmd == SVC_CHOKECOUNT:
                r.byte()
            elif cmd == SVC_PLAYERINFO:
                _size_playerinfo(r, protover_holder.get("v", PROTOCOL_MAX))
            elif cmd == SVC_DAMAGE:
                # V_ParseDamage: byte armor, byte blood, 3 coords
                r.skip(2)
                r.skip(3 * COORD_SIZE)
            elif cmd == SVC_PACKETENTITIES:
                _size_packetentities(r, delta=False)
            elif cmd == SVC_DELTAPACKETENTITIES:
                _size_packetentities(r, delta=True)
            elif cmd == SVC_NAILS:
                _size_nails(r, indexed=False)
            elif cmd == SVC_NAILS2:
                _size_nails(r, indexed=True)
            elif cmd == SVC_TEMP_ENTITY:
                _size_tent(r)
            else:
                # Opcodes we will not size (svc_qizmovoice, svc_fte_voicechat,
                # FTE delta variants requiring fteprotocolextensions, NQ-only
                # messages, svc_spawnstatic2/baseline2, etc.): abandon this
                # dem_read block and continue at the next record.
                raise SvcSizeError(f"unsizable svc opcode {cmd}")
        except SvcSizeError:
            return False
        except (IndexError, ValueError, struct.error):
            return False
    return True


def _apply_setinfo(userinfo: str, key: str, value: str) -> str:
    """Apply a setinfo key/value onto a backslash userinfo string."""
    info = _parse_userinfo(userinfo)
    if value == "":
        info.pop(key, None)
    else:
        info[key] = value
    return "".join(f"\\{k}\\{v}" for k, v in info.items())


def _choose_svc_start(body: bytes) -> int:
    """Pick the svc-stream start offset within a dem_read body.

    Normal frames start at 0; the QWD network-message bodies in these POV demos
    carry two int32 seqs (8 bytes) first.  Try offset 0; if its first byte is
    not a plausible opcode but offset 8 is, use 8.
    """
    def plausible(off: int) -> bool:
        return off < len(body) and body[off] <= SVC_FTE_VOICECHAT

    if len(body) <= 8:
        # Too short for the 8-byte seq prefix; the svc stream (if any) is at 0.
        return 0
    # Prefer 8 when offset-0 looks like a raw sequence/connectionless byte.
    op0 = body[0]
    op8 = body[8]
    if op0 == 0xFF:  # connectionless (\xff\xff\xff\xff ...)
        return 8 if plausible(8) else 0
    if op0 > SVC_FTE_VOICECHAT and op8 <= SVC_FTE_VOICECHAT:
        return 8
    # These demos consistently prefix 8 bytes; offset 8 is the canonical start.
    if op8 <= SVC_FTE_VOICECHAT:
        return 8
    return 0


def _iter_dem_read_bodies(data: bytes):
    """Yield (record_index, demotime, body) for each dem_read/single/stats/all."""
    cursor = 0
    index = 0
    while cursor < len(data):
        qwd_usercmd.require_available(
            data, cursor, qwd_usercmd.RECORD_HEADER_SIZE, "reading QWD record header"
        )
        demotime, raw_type = struct.unpack_from(
            qwd_usercmd.RECORD_HEADER_FORMAT, data, cursor
        )
        cursor += qwd_usercmd.RECORD_HEADER_SIZE
        mt = raw_type & 7
        if mt == qwd_usercmd.DEM_CMD:
            cursor += qwd_usercmd.USERCMD_STRUCT_SIZE + qwd_usercmd.VIEW_ANGLES_SIZE
        elif mt == qwd_usercmd.DEM_SET:
            cursor += 8
        elif mt == qwd_usercmd.DEM_MULTIPLE:
            cursor += 4
            length, = struct.unpack_from("<i", data, cursor)
            cursor += 4
            qwd_usercmd.require_available(data, cursor, length, "dem_multiple payload")
            cursor += length
        elif mt in (qwd_usercmd.DEM_READ, qwd_usercmd.DEM_SINGLE,
                    qwd_usercmd.DEM_STATS, qwd_usercmd.DEM_ALL):
            length, = struct.unpack_from("<i", data, cursor)
            cursor += 4
            if length < 0 or length > qwd_usercmd.MAX_REASONABLE_MESSAGE_BYTES:
                raise qwd_usercmd.QwdUsercmdError(f"bad dem_read length {length}")
            qwd_usercmd.require_available(data, cursor, length, "dem_read payload")
            body = data[cursor:cursor + length]
            cursor += length
            yield index, demotime, body
        else:
            raise qwd_usercmd.QwdUsercmdError(f"Unsupported QWD record type {mt}")
        index += 1


def _usercmd_metrics(data: bytes) -> dict:
    """Reuse qwd_usercmd to derive command-stream metrics."""
    result = qwd_usercmd.parse_qwd_bytes(data)
    cmds = result.commands
    frame_count = len(cmds)
    has_usercmds = frame_count > 0
    if frame_count:
        movement = sum(
            1 for c in cmds if c.forwardmove != 0 or c.sidemove != 0 or c.upmove != 0
        )
        movement_fraction = round(movement / frame_count, 4)
    else:
        movement_fraction = 0.0

    # yaw continuity over consecutive recorded viewangle yaw deltas
    yaws = [c.view_angles[1] for c in cmds]
    if len(yaws) >= 2:
        under = 0
        total = 0
        for a, b in zip(yaws, yaws[1:]):
            d = abs(_norm_angle_yaw(b - a))
            total += 1
            if d < YAW_CONTINUITY_THRESHOLD_DEG:
                under += 1
        yaw_continuity = round(under / total, 4) if total else None
    else:
        yaw_continuity = None

    duration = float(result.header.get("total_duration_s") or 0.0)
    return {
        "has_usercmds": has_usercmds,
        "frame_count": frame_count,
        "movement_cmd_fraction": movement_fraction,
        "yaw_continuity": yaw_continuity,
        "duration_s": round(duration, 3),
    }


def _strip_map_from_worldmodel(worldmodel: str) -> str | None:
    """``maps/dm3.bsp`` -> ``dm3`` (strip leading '/', dir, extension)."""
    if not worldmodel:
        return None
    name = worldmodel
    if name.startswith("/"):
        name = name[1:]
    name = name.rsplit("/", 1)[-1]
    if name.lower().endswith(".bsp"):
        name = name[:-4]
    return name or None


def _build_roster(state: dict) -> list[dict]:
    roster = []
    for slot in sorted(state["userinfo"]):
        userinfo = state["userinfo"][slot]
        name = _slot_name(userinfo)
        if not name and not userinfo:
            continue
        roster.append({
            "slot": slot,
            "name": name,
            "team": _slot_team(userinfo),
            "spectator": _slot_is_spectator(userinfo),
        })
    return roster


def _classify_mode(active_count: int) -> tuple[str, str | None]:
    if active_count == 2:
        return "1on1", None
    if active_count == 4:
        return "2on2", None
    if active_count == 8:
        return "4on4", None
    return "ambiguous", f"{active_count} active non-spectator players (not 2/4/8)"


def parse_qwd(path: str | Path) -> dict:
    """Parse a ``.qwd``/``.qwz`` and return one manifest record (never raises)."""
    path = Path(path)
    errors: list[str] = []
    record: dict = {
        "path": str(path),
        "sha256": None,
        "ext": None,
        "is_compressed": False,
        "compressed_sha256": None,
        "decompressed_sha256": None,
        "decompressor": None,
        "true_map": None,
        "level_title": None,
        "protocol": None,
        "player_count": 0,
        "team_counts": {},
        "mode": "ambiguous",
        "ambiguity_reason": None,
        "roster": [],
        "roster_timeline_note": None,
        "pov_slot": None,
        "pov_player": None,
        "recording_client_spectator": False,
        "pov_kind": "unknown",
        "self_pov_eligible": False,
        "has_usercmds": False,
        "frame_count": 0,
        "movement_cmd_fraction": 0.0,
        "yaw_continuity": None,
        "duration_s": 0.0,
        "blocks_abandoned": 0,
        "errors": errors,
    }

    if not path.exists():
        errors.append(f"file not found: {path}")
        return record

    ext = path.suffix.lower().lstrip(".")
    record["ext"] = ext

    try:
        raw = path.read_bytes()
    except OSError as exc:
        errors.append(f"read failed: {exc}")
        return record

    record["sha256"] = _sha256(raw)

    # --- compression sniff + decompress ---
    data = raw
    parse_path = path
    if not looks_like_real_qwd(raw):
        record["is_compressed"] = True
        record["compressed_sha256"] = record["sha256"]
        scratch = Path(tempfile.mkdtemp(prefix="qwd_content_"))
        out, label, derr = decompress_qwz(path, scratch)
        if out is None:
            errors.append(derr or "decompression failed")
            return record
        try:
            data = out.read_bytes()
        except OSError as exc:
            errors.append(f"decompressed read failed: {exc}")
            return record
        if not looks_like_real_qwd(data):
            errors.append("decompressed output is still not a plausible .qwd")
            return record
        record["decompressed_sha256"] = _sha256(data)
        record["sha256"] = record["decompressed_sha256"]
        record["decompressor"] = label
        parse_path = out

    # --- usercmd-derived metrics (defensive) ---
    try:
        metrics = _usercmd_metrics(data)
        record.update({
            "has_usercmds": metrics["has_usercmds"],
            "frame_count": metrics["frame_count"],
            "movement_cmd_fraction": metrics["movement_cmd_fraction"],
            "yaw_continuity": metrics["yaw_continuity"],
            "duration_s": metrics["duration_s"],
        })
    except qwd_usercmd.QwdUsercmdError as exc:
        errors.append(f"usercmd walk failed: {exc}")
    except (IndexError, ValueError, struct.error) as exc:
        errors.append(f"usercmd walk error: {exc}")

    # --- content walk (serverdata / modellist / roster) ---
    state = {
        "serverdata": None,
        "models": {},
        "userinfo": {},
        "serverinfo": {},
    }
    protover_holder: dict[str, int] = {}
    blocks_abandoned = 0
    try:
        for _idx, _dt, body in _iter_dem_read_bodies(data):
            start = _choose_svc_start(body)
            ok = _walk_svc_block(body, start, protover_holder, state)
            if not ok:
                blocks_abandoned += 1
    except qwd_usercmd.QwdUsercmdError as exc:
        errors.append(f"container walk stopped: {exc}")
    except (IndexError, ValueError, struct.error) as exc:
        errors.append(f"container walk error: {exc}")

    record["blocks_abandoned"] = blocks_abandoned

    # --- serverdata-derived fields ---
    sd: ServerData | None = state["serverdata"]
    if sd is not None:
        record["protocol"] = sd.protocol
        record["level_title"] = sd.levelname
        record["recording_client_spectator"] = sd.spectator
        record["pov_slot"] = sd.slot
    else:
        errors.append("svc_serverdata not found")

    # --- true map: worldmodel (modellist index 1) is authoritative ---
    worldmodel = state["models"].get(1)
    record["true_map"] = _strip_map_from_worldmodel(worldmodel) if worldmodel else None
    # Cross-check / fallback: the serverinfo "map" key carries the bare map name.
    serverinfo_map = state["serverinfo"].get("map")
    if record["true_map"] is None and serverinfo_map:
        record["true_map"] = serverinfo_map
    if record["true_map"] is None:
        errors.append("worldmodel (modellist index 1) not found; true_map unknown")

    # --- roster ---
    roster = _build_roster(state)
    record["roster"] = roster
    if roster:
        record["roster_timeline_note"] = (
            "Roster reflects userinfo accumulated across all walked dem_read blocks "
            "(latest setinfo/updateuserinfo wins per slot); slots that leave are not "
            "removed. blocks_abandoned indicates dem_read blocks skipped on an "
            "unsizable opcode, which may undercount late roster changes."
        )

    active = [p for p in roster if not p["spectator"] and p["name"]]
    record["player_count"] = len(active)
    team_counts: dict[str, int] = {}
    for p in active:
        team_counts[p["team"]] = team_counts.get(p["team"], 0) + 1
    record["team_counts"] = team_counts

    mode, reason = _classify_mode(len(active))
    record["mode"] = mode
    record["ambiguity_reason"] = reason

    # --- pov player / kind / eligibility ---
    pov_name = ""
    if sd is not None and sd.slot in state["userinfo"]:
        pov_name = _slot_name(state["userinfo"][sd.slot])
    record["pov_player"] = pov_name or None

    pov_slot_spectator = False
    if sd is not None and sd.slot in state["userinfo"]:
        pov_slot_spectator = _slot_is_spectator(state["userinfo"][sd.slot])

    autotrack_name = _name_is_autotrack(pov_name) if pov_name else False
    has_real_movement = (
        record["has_usercmds"]
        and record["movement_cmd_fraction"] > MOVEMENT_CMD_FRACTION_ELIGIBLE
    )
    # Authoritative spectator signals first; then genuine movement => self (a
    # non-spectator with real movement is a player even if the name looks cam-ish,
    # e.g. "camper"). The name heuristic is only a fallback label.
    if record["recording_client_spectator"] or pov_slot_spectator:
        record["pov_kind"] = "autotrack" if autotrack_name else "spectator"
    elif sd is not None and has_real_movement:
        record["pov_kind"] = "self"
    elif autotrack_name:
        record["pov_kind"] = "autotrack"
    elif sd is not None:
        record["pov_kind"] = "self"
    else:
        record["pov_kind"] = "unknown"

    # Eligibility uses only authoritative signals (spectator bit / slot, usercmds,
    # movement fraction) -- NOT the fragile name heuristic, which over-matched real
    # players (e.g. "camper").
    record["self_pov_eligible"] = bool(
        sd is not None
        and not record["recording_client_spectator"]
        and not pov_slot_spectator
        and record["has_usercmds"]
        and record["movement_cmd_fraction"] > MOVEMENT_CMD_FRACTION_ELIGIBLE
    )

    return record


def _cli(argv: Iterable[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Emit a content manifest (JSON) for QuakeWorld POV .qwd/.qwz demos."
    )
    parser.add_argument("demos", nargs="+", type=Path, help="One or more .qwd/.qwz paths.")
    parser.add_argument(
        "--indent", type=int, default=None,
        help="Pretty-print JSON with this indent (single demo only; default compact JSON lines).",
    )
    args = parser.parse_args(list(argv))

    records = [parse_qwd(p) for p in args.demos]
    if len(records) == 1 and args.indent is not None:
        sys.stdout.write(json.dumps(records[0], indent=args.indent, sort_keys=True) + "\n")
    else:
        for rec in records:
            sys.stdout.write(json.dumps(rec, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))
