"""catalog_etl_mvd.py — populate the MOVE catalog from human 4on4 dm3 `.mvd` demos (F-DATA-2).

Pure standard library only (sqlite3, json, math, hashlib, subprocess, pathlib, argparse,
logging, multiprocessing). NO third-party imports — this module obeys the same stdlib-only
gate as the rest of `scripts/` (the merge gate runs it on bare Python 3.12). Heavy deps stay
under `ml/`. (`pmove_sim`, `features.agent_observation`, `catalog_load` are stdlib-only repo
modules — OK to import.)

WHAT THIS IS — the MVD sibling of `catalog_etl_qwd.py`
-----------------------------------------------------
`catalog_etl_qwd.py` builds the MOVE catalog from self-POV `.qwd` demos, where the recording
player's usercmd INPUT stream (forwardmove/sidemove/upmove/jump/yaw) is recorded verbatim, so
action labels are GROUND TRUTH (label_source='qwd_usercmd', confidence=1.0).

This driver builds the SAME per-tick MOVE catalog from server-side `.mvd` demos, where the
input stream is ABSENT: an MVD records server-frame STATE (positions, view-angles, and a
finite-differenced velocity) but NOT the inputs. So the action labels must be RECOVERED from
state via inverse dynamics (label_source='idm', confidence<1.0). The believable-bunnyhop BC
corpus then draws from MANY more demos (the servexeri human 4on4 dm3 corpus, ~1537 demos)
than the handful of self-POV `.qwd` recordings.

Per demo it loads:
    demos        <- one row per .mvd (source='mvd')
    players      <- each active player's handle (real name from the MVD stream)
    episodes     <- contiguous trajectory segments per player, split at teleport/respawn
                    discontinuities (pmove_sim.detect_teleports) + a hard length cap
    player_ticks <- the per-player per-tick STATE spine (o, v, angles, hspeed, geometric
                    onground, onground_is_proxy=TRUE), msec from consecutive `t` deltas
    actions      <- the IDM-RECOVERED (state,action) labels (sidemove SIGN, jump, view
                    angles), label_source='idm', confidence<1.0, is_interp on unreliable rows
    teams        <- roster team names (one row per distinct `team` string), side A/B          (T4)
    actor_ticks  <- the OMNISCIENT all-players world per ego-episode tick (every player's full
                    state + forward-filled health/armor/armor_type + alive + team_id)          (T4)
    item_events  <- pickup/respawn timeline (item phases) + dropped-weapon backpacks           (T4)
    frag_events  <- kill timeline (killer/victim/weapon/isSuicide/isTeamKill)                   (T4)

All of T4's tables read the SAME single `-view full` decode the movement spine already runs (the
schema-33 JSON carries the per-player resource step-timelines + the match-level frags/items/backpacks
streams) — NO extra binary invocation. See the T4 helper block for the empirically-verified shapes.

A train/val/test split is assigned GROUPED BY demo (no demo's frames straddle the boundary),
but — unlike the QWD ETL's positional assign_splits — the bucket is picked per demo from its
content hash (split_for_sha), so each demo streams to SQLite the moment its parse finishes (no
global ordering, bounded memory; see build()). The episodes carry the VERSIONED provenance
split_policy='group_by_demo_sha256_bucket_v1' (SPLIT_POLICY) so a generated catalog records
exactly which assignment produced `split`. See data/catalog/dataset_spec.yaml.

MVD INPUT FORMAT (schema-33 qw-analyze)
---------------------------------------
Each `.mvd` is parsed with the schema-33 qw-analyze binary:
    <binary> -view full -include positions,view,velocity <demo.mvd>
yielding JSON with `streams.players[]` (~8 for a 4on4). Each player has `name`, `team`, and
`pos` = a COLUMN-ORIENTED per-tick stream of PARALLEL ARRAYS:
    {t, x, y, z, li, vp, vya, vx, vy, vz}   (all same length, cadence ~13-14 ms ≈ 72 Hz)
  t            = ms timestamp
  x,y,z        = origin (qu)
  vya          = view YAW   in angle16 units (int16, ±32768); deg = vya*360/65536
  vp           = view PITCH in angle16 units;                  deg = vp *360/65536
  vx,vy,vz     = velocity qu/s (the analyzer already finite-differences it — used DIRECTLY)
  li           = loc index (unused here)

RESOURCE STATE (T3) — a SECOND, best-effort decode of the discrete event stream:
    <binary> -view events -event-types health,armor <demo.mvd>
yields `events: [{t (s), type, player(name), detail:{value}}]`. The per-player health/armor
VALUE step-timelines are forward-filled onto each pos tick (joined by demo-time + player name)
and written to player_ticks.health/armor. armor_type and weapon stay NULL: this stream carries
the STAT-equivalent health/armor values but NOT the armor skin/type, and its weapon events are
gain/lose INVENTORY changes, not STAT_ACTIVEWEAPON (the "active weapon id" the column means).
Best-effort: a failed/empty event decode leaves health/armor NULL; movement is never gated on it.

⚠️ BINARY-VERSION GUARD: the OLDER qw-analyze build emits schema 21, whose `pos` has only
{t,x,y,z,li} — NO vp/vya/vx/vy/vz — which would silently kill strafe-sign recovery. This ETL
HARD-FAILS unless schemaVersion>=33 AND `pos` carries `vya` and `vx` (see _validate_analysis).
The correct binary on aws-dev is ~/qw-sim/bin/qw-analyze-v20 (schema 33, sha256 6954ffb6...).

THE 3 DE-RISK REQUIREMENTS (from experiments/mvd_action_recovery, branch diag/mvd-action-recovery)
-------------------------------------------------------------------------------------------------
(req 1) onground from GEOMETRY (#316), NOT vz-spikes. Each tick's onground is a downward
        floor trace from the player origin against the dm3 BSP hull-1 (the same
        PM_CategorizePosition idiom pmove_sim uses): onground iff a 1-qu down trace hits a
        surface whose normal_z >= MIN_STEP_NORMAL, with the vz>MAXGROUNDSPEED early-out.
        onground_is_proxy=TRUE (MVD has no server onground flag; this is geometric).

(req 2) sidemove SIGN = -sign(yaw_rate), yaw_rate via the CANONICAL agent_observation.
        yaw_rate_degps (train/serve parity). The air-accel sign rule is ~90%+ reliable ONLY
        in the sustained-bunnyhop regime, so the strafe-sign label is GATED to hspeed >=
        STRAFE_SIGN_GATE (400 qu/s): at/above the gate it is a confident label
        (confidence=STRAFE_CONF, is_interp=False); below the gate (accel phase) the row is
        emitted with is_interp=TRUE so the trainer can exclude it. Magnitude is LOST in MVD,
        so |sidemove| is set from the de-risk prior (SIDEMOVE_MAG ≈ full, the human move-speed
        cvar, since |sidemove| when strafing is near-constant-full). forwardmove is GENUINELY
        LOST (the de-risk found it nonzero in 50-71% of air frames but unrecoverable, and
        fwd-press is the behavior we do NOT want cloned) → set to FORWARDMOVE_PRIOR (0) with
        confidence FORWARD_CONF (low).

(req 3) jump = rhythm/noise-tolerant, from geometric-onground TRUE->FALSE transitions with
        upward intent (vz>0 around the transition), NOT per-tick vz-spike thresholding.
        Single-tick onground flicker is tolerated (a jump is only emitted on a transition
        that stays airborne for >= JUMP_MIN_AIR ticks). Encoded in buttons (jump bit &2) and
        upmove (+SIDEMOVE_MAG on a jump tick). AIM (view angles) is lossless in MVD:
        cmd_yaw/cmd_pitch = the view angles directly, confidence=AIM_CONF (high).

USAGE
-----
    python scripts/catalog_etl_mvd.py \
        --catalog-dir data/catalog \
        --manifest    data/corpus/human_4on4_dm3_mvd_manifest.json \
        --db          data/catalog/dm3_4on4_mvd.sqlite \
        --bsp         /home/ubuntu/nquakesv/qw/maps/dm3.bsp \
        --qw-analyze  ~/qw-sim/bin/qw-analyze-v20 \
        --workers 4 [--limit N]

Repo destination: scripts/catalog_etl_mvd.py
"""
from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import logging
import math
import os
import subprocess
import sqlite3
import sys
import time
from concurrent.futures import ProcessPoolExecutor, FIRST_COMPLETED, wait
from pathlib import Path

LOGGER = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
for _p in (str(REPO_ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import catalog_load  # noqa: E402  (stdlib-only sibling; static spine)
import pmove_sim  # noqa: E402  (stdlib-only; WorldModel + player_trace + detect_teleports)
from features.agent_observation import yaw_rate_degps  # noqa: E402  (canonical turn-rate)

BUTTON_JUMP = pmove_sim.BUTTON_JUMP  # 2
DEFAULT_QW_ANALYZE = str(Path("~/qw-sim/bin/qw-analyze-v20").expanduser())
DEFAULT_BSP = "/home/ubuntu/nquakesv/qw/maps/dm3.bsp"

# --- angle16 -> degrees (QW wire format) -------------------------------------
ANGLE16_TO_DEG = 360.0 / 65536.0

# --- episode packing (mirror catalog_etl_qwd) --------------------------------
MAX_EPISODE_FRAMES = 2048
MIN_EPISODE_FRAMES = 24

# --- recovery constants (the 3 de-risk requirements) -------------------------
# (req 2) strafe-sign confidence regime. The QW air-accel sign rule sign(sidemove)==
# -sign(yaw_rate) is ~90%+ reliable only above the sustained-bunnyhop speed gate (the
# de-risk reproduced 89.6% @>=400, 92.3% @>=450). Below the gate (acceleration phase /
# ground strafe) the sign is unreliable -> emit with is_interp=TRUE so the trainer excludes.
STRAFE_SIGN_GATE = 400.0   # qu/s; at/above => confident strafe-sign label
YAW_RATE_DEADBAND = 20.0   # deg/s; below this the turn is too small to sign confidently
# (req 2) magnitude prior. |sidemove| when strafing is near-constant-full in the de-risk
# (p50 = the player's move-speed cvar, 400). MVD loses the analog magnitude, so we emit a
# constant full-deflection side label whose SIGN is the recovered air-strafe direction.
SIDEMOVE_MAG = 400.0
# (req 2) forwardmove is GENUINELY LOST (and fwd-press is the behavior we do NOT want
# cloned). Default near 0 in air with low confidence rather than fabricating a press.
FORWARDMOVE_PRIOR = 0.0

# (req 3) jump = noise-tolerant onground TRUE->FALSE transition with upward intent.
JUMP_MIN_AIR = 2           # ticks the player must stay airborne after the transition
                           # for it to count as a jump (tolerates single-tick flicker)
JUMP_VZ_MIN = 1.0          # qu/s; require upward intent (vz>0) at the transition

# per-signal confidence (all < 1.0 per the actions.confidence contract for IDM rows).
AIM_CONF = 0.95            # view angles are lossless in MVD (angle16 == client resolution)
STRAFE_CONF = 0.9          # air-strafe sign in the >=gate bhop regime (de-risk: 89-92%)
FORWARD_CONF = 0.2         # forwardmove is unrecoverable -> low-confidence prior
BELOW_GATE_CONF = 0.4      # below-gate strafe sign (still recorded, is_interp=TRUE)

# the per-tick STATE confidence does not exist as a column; per-row `confidence` is the
# action-label confidence. We take the row confidence = min over the labels we trust this
# tick (aim is always present; strafe gated; forward low). The dominant believability label
# is the air-strafe sign, so above-gate rows carry STRAFE_CONF and below-gate rows the lower
# BELOW_GATE_CONF + is_interp=TRUE.

# --- geometric onground (req 1): a thin downward floor-trace prober ----------
MIN_STEP_NORMAL = pmove_sim.MIN_STEP_NORMAL              # 0.7
MAXGROUNDSPEED_DEFAULT = pmove_sim.MAXGROUNDSPEED_DEFAULT  # 180.0


class OngroundProber:
    """Geometric onground via a 1-qu downward hull-1 floor trace (PM_CategorizePosition
    idiom from pmove_sim). NOT a vz-spike: this is the same world geometry the .qwd path's
    onground comes from. Loads the dm3 BSP once per worker (the WorldModel is reused for
    every tick of every player in the demo)."""

    def __init__(self, bsp_path: str):
        self.world = pmove_sim.WorldModel.load(bsp_path)

    def onground(self, origin, vz: float) -> bool:
        # PM_CategorizePosition early-out: moving up faster than the ground-speed cap can't
        # be standing on a floor.
        if vz > MAXGROUNDSPEED_DEFAULT:
            return False
        point = (origin[0], origin[1], origin[2] - 1.0)
        tr = pmove_sim.player_trace(self.world, origin, point)
        far = tr.fraction == 1.0 or tr.normal[2] < MIN_STEP_NORMAL
        return not far


# ---------------------------------------------------------------------------
def _validate_analysis(data: dict, demo_name: str) -> None:
    """Hard-fail (ValueError) unless this is a schema-33+ analysis whose `pos` stream carries
    the velocity + view-yaw fields. Guards the schema-21 binary-version gotcha that would
    silently kill strafe-sign recovery."""
    sv = data.get("schemaVersion")
    if not isinstance(sv, int) or sv < 33:
        raise ValueError(
            "%s: schemaVersion=%r but the MVD ETL requires schema>=33. The stock "
            "qw-analyze-v20 on some boxes is an OLDER schema-21 build whose `pos` has only "
            "{t,x,y,z,li} (no velocity/view) -> strafe-sign recovery silently fails. Use the "
            "schema-33 binary (aws-dev: ~/qw-sim/bin/qw-analyze-v20, sha256 6954ffb6...)."
            % (demo_name, sv)
        )
    players = (data.get("streams") or {}).get("players") or []
    if not players:
        raise ValueError("%s: schema-33 analysis has no streams.players" % demo_name)
    pos = players[0].get("pos") or {}
    missing = [k for k in ("vya", "vp", "vx", "vy", "vz") if k not in pos]
    if missing:
        raise ValueError(
            "%s: `pos` stream missing %r — not a schema-33 positions,view,velocity export. "
            "Run qw-analyze with `-include positions,view,velocity` and the schema-33 binary."
            % (demo_name, missing)
        )


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _player_frames(pos: dict) -> list[dict]:
    """Turn one player's column-oriented `pos` stream into per-tick frame dicts carrying the
    keys pmove_sim.detect_teleports needs (origin, velocity, msec) plus view angles.

    velocity (vx,vy,vz) is used DIRECTLY — the analyzer already finite-differences it (a real
    MVD has no velocity wire field). msec is the consecutive `t` delta (ms); the last tick
    reuses the previous delta (no following sample). View angles are converted from angle16."""
    t = pos["t"]
    x, y, z = pos["x"], pos["y"], pos["z"]
    vx, vy, vz = pos["vx"], pos["vy"], pos["vz"]
    vya, vp = pos["vya"], pos["vp"]
    n = len(t)
    frames = []
    for i in range(n):
        if i + 1 < n:
            msec = int(t[i + 1]) - int(t[i])
        elif i > 0:
            msec = int(t[i]) - int(t[i - 1])
        else:
            msec = 13
        if msec <= 0:
            msec = 13  # guard a duplicate/non-monotonic timestamp
        frames.append({
            "origin": [float(x[i]), float(y[i]), float(z[i])],
            "velocity": [float(vx[i]), float(vy[i]), float(vz[i])],
            "yaw": float(vya[i]) * ANGLE16_TO_DEG,
            "pitch": float(vp[i]) * ANGLE16_TO_DEG,
            "msec": msec,
            "t_ms": int(t[i]),  # absolute demo-time (ms); the join key for the resource timeline
        })
    return frames


def _resource_timeline(events: list, player_name: str) -> dict:
    """Build one player's step-function resource timeline (health/armor) from the `-view events
    -event-types health,armor` stream, keyed for an at-or-before lookup against a tick's t_ms.

    The events stream is `[{t (seconds, demo-time), type, player (name), detail:{value,...}}]`.
    `health` / `armor` events carry an ABSOLUTE STAT value in detail.value at each change time
    (the spec §3.4 STAT_HEALTH/STAT_ARMOR equivalents). We keep, per type, the sorted change
    times (in ms, same origin as the pos stream's `t`) and their values, so _fill_resource can
    forward-fill the most-recent value at-or-before each tick. Returns {"health": (ts, vs),
    "armor": (ts, vs)} with parallel sorted arrays (empty when the player has no such events)."""
    out = {"health": ([], []), "armor": ([], [])}
    for e in events:
        if e.get("player") != player_name:
            continue
        typ = e.get("type")
        if typ not in out:
            continue
        val = (e.get("detail") or {}).get("value")
        if val is None:
            continue
        t_ms = int(round(float(e.get("t", 0.0)) * 1000.0))  # seconds -> ms (pos-stream origin)
        out[typ][0].append(t_ms)
        out[typ][1].append(int(val))
    for typ in out:  # the analyzer emits change-events in time order, but sort to be safe
        ts, vs = out[typ]
        if ts != sorted(ts):
            order = sorted(range(len(ts)), key=lambda i: ts[i])
            out[typ] = ([ts[i] for i in order], [vs[i] for i in order])
    return out


def _fill_resource(timeline: tuple, t_ms: int):
    """Most-recent step value at-or-before t_ms (forward-fill); None before the first event."""
    ts, vs = timeline
    if not ts:
        return None
    i = bisect.bisect_right(ts, t_ms) - 1
    return vs[i] if i >= 0 else None


# =============================================================================
# T4 — the OMNISCIENT MVD world (actor_ticks + item_events + frag_events + teams).
#
# These all read the SAME single `-view full` decode the movement spine already runs (no extra
# binary invocation): the schema-33 `-view full` JSON carries, alongside `streams.players[].pos`,
# the per-player resource step-timelines (`h`/`a`/`at`), per-player death-tick list (`d`), and the
# match-level top-level streams `frags.frags` (killer/victim/weapon/isSuicide/isTeamKill),
# `items.items[].phases[]` (pickup/respawn), and `backpacks` (dropped-weapon origins). The roster
# `teams` come from each player's `team` string.
#
# EMPIRICALLY VERIFIED against ~/qw-sim/bin/qw-analyze-v20 (schema 33, sha 6954ffb6) on the real
# 4on4 MVD 20250405-1941_4on4_book_vs_mix[dm3].mvd. Two finds that the conceptual verb names hid:
#   * the discrete `-view events -event-types frag/death` streams are DEGENERATE for a kill table —
#     `frag` is a SCORE-DELTA per scorer ({player,delta,team}) and `death` is victim-only ({player});
#     neither pairs killer<->victim<->weapon. The HONEST kill timeline is the top-level `frags.frags`
#     ([{time,killer,victim,weapon,isSuicide,isTeamKill}]) in the same `-view full` JSON.
#   * `at` (armor TYPE: 'ra'/'ya'/'ga'/'') IS present in `-view full` per player — so actor_ticks can
#     fill armor_type even though the T3 player_ticks path (a separate `-event-types armor` decode)
#     could not. `weapon` (active-weapon id) stays NULL everywhere (same reason as T3: the streams
#     carry gain/lose INVENTORY, not STAT_ACTIVEWEAPON).
# Era-gating: an older/again-different demo whose `-view full` lacks a stream just yields NO rows for
# that table (the helpers iterate whatever is present); the movement spine is never affected.
# =============================================================================
ARMOR_TYPE_CODE = {"ga": 0, "ya": 1, "ra": 2}  # 'at' string -> armor_type int (0/1/2 = GA/YA/RA)


def _step_timeline(steps) -> tuple:
    """Turn a `-view full` per-player `[{t (ms), v}]` step list into sorted (ts, vs) parallel
    arrays for an at-or-before forward-fill (same shape _fill_resource consumes)."""
    ts, vs = [], []
    for s in steps or []:
        if not isinstance(s, dict) or "t" not in s:
            continue
        ts.append(int(s["t"]))
        vs.append(s.get("v"))
    if ts != sorted(ts):
        order = sorted(range(len(ts)), key=lambda i: ts[i])
        ts, vs = [ts[i] for i in order], [vs[i] for i in order]
    return ts, vs


def _alive_timeline(death_ms: list, spawn_steps) -> tuple:
    """Build an (ts, vs) alive step-timeline (vs in {True,False}) from a player's death-tick list
    `d` (ms) and spawn-event step list (the `sp` stream, when present). A death sets alive=False;
    the next spawn-after-a-death restores alive=True. Without a spawn stream we still mark the
    DEATH instants (alive flips False at each death, back True at the next death's preceding window
    is unknown) — so we conservatively encode each death as a False step and, if spawn steps exist,
    each spawn as a True step. Empty input => empty timeline => alive stays NULL (unknown)."""
    events = []
    for t in death_ms or []:
        events.append((int(t), False))
    for s in spawn_steps or []:
        if isinstance(s, dict) and "t" in s:
            events.append((int(s["t"]), True))
    events.sort(key=lambda e: e[0])
    return [e[0] for e in events], [e[1] for e in events]


def _actor_samples(player: dict) -> dict:
    """Build one player's OMNISCIENT time-sorted state samples for actor_ticks alignment.

    Returns {"t":[ms...], "rows":[{ox,oy,oz,vx,vy,vz,pitch,yaw,roll,hspeed,health,armor,
    armor_type,alive}...]} — the full per-frame world state, keyed by absolute demo-time (ms) so
    insert_demo can align EVERY player onto each episode's ticks (MVD is omniscient: no staleness
    window, the server frame holds every player's exact state). onground is NOT carried here: it
    needs the per-worker BSP prober and is filled tick-by-tick at alignment time would require the
    world model in the insert process; actor_ticks.onground/onground_is_proxy are left NULL for the
    observed-others world (the geometric proxy lives on the ego player_ticks spine). health/armor/
    armor_type/alive forward-fill the player's `h`/`a`/`at`/`d` step-timelines."""
    pos = player.get("pos") or {}
    t = pos.get("t") or []
    n = len(t)
    if not n:
        return {"t": [], "rows": []}
    x, y, z = pos["x"], pos["y"], pos["z"]
    vx, vy, vz = pos["vx"], pos["vy"], pos["vz"]
    vya, vp = pos["vya"], pos["vp"]
    h_tl = _step_timeline(player.get("h"))
    a_tl = _step_timeline(player.get("a"))
    at_tl = _step_timeline(player.get("at"))
    alive_tl = _alive_timeline(player.get("d") or [], player.get("sp"))
    ts, rows = [], []
    for i in range(n):
        t_ms = int(t[i])
        hp = _fill_resource(h_tl, t_ms)
        ap = _fill_resource(a_tl, t_ms)
        at_s = _fill_resource(at_tl, t_ms)
        at_code = ARMOR_TYPE_CODE.get(at_s) if isinstance(at_s, str) and at_s else None
        alive = _fill_resource(alive_tl, t_ms)  # None before first death/spawn -> NULL (alive unknown)
        ts.append(t_ms)
        rows.append({
            "ox": float(x[i]), "oy": float(y[i]), "oz": float(z[i]),
            "vx": float(vx[i]), "vy": float(vy[i]), "vz": float(vz[i]),
            "pitch": float(vp[i]) * ANGLE16_TO_DEG, "yaw": float(vya[i]) * ANGLE16_TO_DEG, "roll": 0.0,
            "hspeed": round(math.hypot(float(vx[i]), float(vy[i])), 3),
            "health": hp, "armor": ap, "armor_type": at_code,
            "alive": (None if alive is None else bool(alive)),
        })
    return {"t": ts, "rows": rows}


def _extract_teams(data: dict) -> list[str]:
    """Distinct roster team names (the `team` string on each `-view full` player). Order-stable."""
    out = []
    for p in (data.get("streams") or {}).get("players") or []:
        team = (p.get("team") or "").strip()
        if team and team not in out:
            out.append(team)
    return out


def _extract_item_events(data: dict) -> list[dict]:
    """Pickup/respawn timeline from `items.items[].phases[]` + dropped-weapon `backpacks`.

    items.items: [{name, kind, x,y,z, phases:[{availableFrom, takenAt, takenBy, team, respawnAt}]}].
    Each phase yields a PICKUP (takenAt/takenBy/team, at the item's static origin) and, when the
    item respawned within the demo (respawnAt present), a RESPAWN event (no player). backpacks:
    [{time, player, team, weapon, origin}] -> a 'drop' event at the backpack's world origin.

    Returns decoder-honest dicts with t_s (seconds), event_kind, the picker NAME + team NAME, the
    item kind, and origin (item static or backpack drop). insert_demo resolves names->ids and the
    kind+origin spatial join to items.item_id."""
    out = []
    for it in (data.get("items") or {}).get("items") or []:
        if not isinstance(it, dict):
            continue
        kind = it.get("kind")
        ox, oy, oz = it.get("x"), it.get("y"), it.get("z")
        for ph in it.get("phases") or []:
            if not isinstance(ph, dict):
                continue
            taken_at = ph.get("takenAt")
            if taken_at is not None:
                out.append({"kind": "pickup", "t_ms": int(taken_at), "player": ph.get("takenBy"),
                            "team": ph.get("team"), "item_type": kind,
                            "ox": ox, "oy": oy, "oz": oz})
            resp = ph.get("respawnAt")
            # respawnAt == 0 means "still held / unknown" (_source-schemas.md), NOT a real
            # respawn at match start — emitting it would poison respawn-ETA / item-control.
            if resp is not None and int(resp) > 0:
                out.append({"kind": "respawn", "t_ms": int(resp), "player": None,
                            "team": None, "item_type": kind, "ox": ox, "oy": oy, "oz": oz})
    for bp in data.get("backpacks") or []:
        if not isinstance(bp, dict):
            continue
        o = bp.get("origin") or [None, None, None]
        out.append({"kind": "drop", "t_ms": int(bp.get("time", 0)), "player": bp.get("player"),
                    "team": bp.get("team"), "item_type": bp.get("weapon"),
                    "ox": o[0], "oy": o[1], "oz": o[2]})
    out.sort(key=lambda e: e["t_ms"])
    return out


def _extract_frag_events(data: dict) -> list[dict]:
    """Kill timeline from the top-level `frags.frags` ([{time, killer, victim, weapon, isSuicide,
    isTeamKill}]). NOTE (empirically verified): the discrete `-view events` frag/death streams are
    degenerate (score-delta / victim-only); `frags.frags` is the only honest killer<->victim<->weapon
    source. Returns name-keyed dicts; insert_demo resolves killer/victim NAME -> player_id."""
    out = []
    for f in (data.get("frags") or {}).get("frags") or []:
        if not isinstance(f, dict):
            continue
        killer, victim = f.get("killer"), f.get("victim")
        out.append({
            "t_ms": int(f.get("time", 0)),
            "killer": killer, "victim": victim, "weapon": f.get("weapon"),
            # honor explicit decoder flags; fall back to killer==victim for suicide if unflagged.
            "is_suicide": bool(f.get("isSuicide", killer is not None and killer == victim)),
            "is_teamkill": bool(f.get("isTeamKill", False)),
        })
    out.sort(key=lambda e: e["t_ms"])
    return out


def _nearest_sample(times: list, t_ms: int):
    """Index of the omniscient state sample nearest to t_ms (at-or-before preferred, else the very
    first sample). MVD is omniscient so there is no staleness gap to honor — every player's exact
    state exists at every server frame; we pick the closest recorded frame to the ego tick time."""
    if not times:
        return None
    i = bisect.bisect_right(times, t_ms) - 1
    if i < 0:
        return 0
    if i + 1 < len(times) and (times[i + 1] - t_ms) < (t_ms - times[i]):
        return i + 1
    return i


def _recover_onground(frames: list[dict], prober: OngroundProber) -> list[bool]:
    """(req 1) geometric onground per tick — a floor trace, NOT a vz-spike."""
    return [prober.onground(f["origin"], f["velocity"][2]) for f in frames]


def _recover_jumps(onground: list[bool], frames: list[dict]) -> list[bool]:
    """(req 3) jump press per tick from geometric-onground TRUE->FALSE transitions with
    upward intent, noise-tolerant. A jump is a transition where the player was on the ground
    at tick i, leaves the ground at i+1 with vz>0, AND stays airborne >= JUMP_MIN_AIR ticks
    (so a single-tick onground flicker does NOT register a jump). The jump press is attributed
    to tick i (the last grounded tick — the tick a +jump usercmd would have been issued)."""
    n = len(frames)
    jump = [False] * n
    for i in range(n - 1):
        if not (onground[i] and not onground[i + 1]):
            continue
        if frames[i + 1]["velocity"][2] <= JUMP_VZ_MIN:
            continue  # no upward intent -> a fall off a ledge, not a jump
        # require a sustained airborne run after the transition (flicker tolerance)
        air = 0
        for j in range(i + 1, min(n, i + 1 + JUMP_MIN_AIR)):
            if onground[j]:
                break
            air += 1
        if air >= JUMP_MIN_AIR:
            jump[i] = True
    return jump


def _pack_episode(seg, seg_onground, seg_jump, start_tick: int) -> dict:
    """Pack one contiguous frame run into compact per-tick rows (STATE + recovered ACTION).

    Recovery per tick:
      onground = seg_onground (geometric)                          (req 1)
      sidemove = -sign(yaw_rate) * SIDEMOVE_MAG, yaw_rate canonical (req 2), gated to
                 hspeed>=STRAFE_SIGN_GATE; below the gate the row is is_interp=TRUE.
      jump     = seg_jump (onground TRUE->FALSE transition)        (req 3) -> buttons &2 + upmove
      cmd_yaw/cmd_pitch = the view angles directly                 (aim lossless)
    """
    rows = []
    t_s = 0.0
    prev_yaw = None
    for i, f in enumerate(seg):
        o, v = f["origin"], f["velocity"]
        yaw, pitch = f["yaw"], f["pitch"]
        msec = int(f["msec"])
        dt = msec * 0.001
        hspeed = math.hypot(v[0], v[1])

        # (req 2) air-strafe SIGN from the canonical turn-rate helper (train/serve parity).
        yr = yaw_rate_degps(yaw, prev_yaw, dt)
        prev_yaw = yaw
        above_gate = hspeed >= STRAFE_SIGN_GATE
        confident_turn = abs(yr) >= YAW_RATE_DEADBAND
        if confident_turn:
            side = -SIDEMOVE_MAG if yr > 0.0 else SIDEMOVE_MAG  # sign(side)==-sign(yaw_rate)
        else:
            side = 0.0  # turn too small to sign -> no strafe label this tick

        jump = bool(seg_jump[i])
        onground = bool(seg_onground[i])
        buttons = BUTTON_JUMP if jump else 0
        upmove = SIDEMOVE_MAG if jump else 0.0

        # per-signal reliability (kept for the per-head-weight phase): an above-gate confident
        # turn is the believability-critical strafe-sign label (STRAFE_CONF); below the gate the
        # sign is unreliable (BELOW_GATE_CONF) or absent (FORWARD_CONF).
        if above_gate and confident_turn:
            confidence = STRAFE_CONF
        else:
            confidence = BELOW_GATE_CONF if confident_turn else FORWARD_CONF
        # INTERIM HOLD-OUT (anti-poisoning): the trainer scales the WHOLE action vector by ONE
        # row weight, and forwardmove here is a fabricated prior (FORWARDMOVE_PRIOR), so any
        # trainable idm row would clone "no forward" at high confidence (label poisoning, not
        # mere low confidence). Until per-head weights exist (the [K,H] shard/trainer change),
        # EVERY idm row is is_interp=TRUE so NO move head trains on it. side/jump/confidence are
        # still emitted so the per-head phase can re-enable them without re-extracting 1537 demos.
        is_interp = True

        rows.append({
            "tick": i,
            "t_s": round(t_s, 4),
            "t_ms": int(f.get("t_ms", 0)),  # absolute demo-time (ms): the actor_ticks alignment key
            "msec": msec,
            "ox": o[0], "oy": o[1], "oz": o[2],
            "vx": v[0], "vy": v[1], "vz": v[2],
            "pitch": pitch, "yaw": yaw, "roll": 0.0,
            "hspeed": round(hspeed, 3),
            "onground": onground,
            # resource state forward-filled from the events stream in extract_demo (T3).
            # armor_type/weapon stay NULL: the -event-types stream carries STAT-equivalent
            # health/armor VALUES but not the armor skin/type nor STAT_ACTIVEWEAPON.
            "health": f.get("health"), "armor": f.get("armor"),
            "fwd": FORWARDMOVE_PRIOR, "side": side, "up": upmove,
            "buttons": buttons,
            "cmd_yaw": yaw, "cmd_pitch": pitch,
            "confidence": confidence,
            "is_interp": is_interp,
        })
        t_s += dt
    return {"start": start_tick, "end": start_tick + len(seg) - 1, "n": len(seg), "frames": rows}


def _decode_resource_events(qw_analyze: str, demo: Path) -> list:
    """Best-effort decode of the discrete event stream for resource state (T3).

    Runs `<binary> -view events -event-types health,armor <demo>` and returns its `events`
    list (`[{t, type, player, detail}]`). Best-effort: ANY failure (the binary lacks the flag,
    a malformed/empty export, a parse error) returns [] so health/armor stay NULL and the
    movement spine is unaffected — resource state is additive context, never a hard gate."""
    try:
        proc = subprocess.run(
            [qw_analyze, "-view", "events", "-event-types", "health,armor", str(demo)],
            capture_output=True, check=True,
        )
        ev = json.loads(proc.stdout).get("events")
        return ev if isinstance(ev, list) else []
    except Exception:  # noqa: BLE001  (resource state is best-effort; never fail the demo on it)
        return []


def extract_demo(demo_path: str, qw_analyze: str, bsp_path: str,
                 expected_sha256: str | None = None) -> dict:
    """Worker: parse one .mvd into per-player per-tick STATE + recovered ACTION rows.

    Returns a JSON-serializable dict (crosses the ProcessPool boundary cleanly):
        {ok, demo, sha256, n_players, players:[{name, team, n_frames,
            episodes:[{start,end,n,frames:[...]}]}], ...}  on success
        {ok:False, demo, error}                            on failure
        {ok:False, demo, error, sha_mismatch:True}         on content-lock mismatch (FATAL)
    Never raises into the pool — a bad demo is recorded and skipped. A sha_mismatch is a
    provenance failure (the file on disk is not the bytes the manifest classified) and build()
    aborts the whole run on it."""
    demo = Path(demo_path)
    try:
        sha = _sha256_file(demo)
        if expected_sha256 and sha != expected_sha256:
            return {"ok": False, "demo": demo.name, "sha_mismatch": True,
                    "error": "SHA_MISMATCH manifest=%s on-disk=%s (file replaced/truncated/"
                             "repaired since classification?)" % (expected_sha256, sha)}
        proc = subprocess.run(
            [qw_analyze, "-view", "full", "-include", "positions,view,velocity", str(demo)],
            capture_output=True, check=True,
        )
        data = json.loads(proc.stdout)
        _validate_analysis(data, demo.name)
    except subprocess.CalledProcessError as e:  # noqa: BLE001
        tail = (e.stderr or b"")[-300:].decode("utf-8", "replace")
        return {"ok": False, "demo": demo.name, "error": "qw-analyze:%s %s" % (e.returncode, tail)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "demo": demo.name, "error": "%s: %s" % (type(e).__name__, e)}

    # (T3) resource state: a SECOND, best-effort decode of the discrete event stream for the
    # per-player health/armor step timelines (`-view events -event-types health,armor`). This is
    # a SEPARATE view from `-view full` (one decode each), but the same already-recorded demo.
    # Best-effort by design: a demo whose event view fails/empties just yields NULL health/armor
    # (resource state is additive context, never the movement spine). armor_type and weapon stay
    # NULL — the stream carries STAT-equivalent health/armor VALUES but neither the armor skin/type
    # nor STAT_ACTIVEWEAPON (its weapon events are gain/lose inventory, not the active-weapon id).
    events = _decode_resource_events(qw_analyze, demo)

    try:
        prober = OngroundProber(bsp_path)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "demo": demo.name, "error": "bsp:%s: %s" % (type(e).__name__, e)}

    # (T4) the OMNISCIENT world, read from the SAME `-view full` decode (no extra binary run):
    # the roster, every player's full time-sorted state samples (for actor_ticks), and the
    # match-level item/frag timelines. Per-player team string is carried on each players_out entry.
    teams = _extract_teams(data)
    actor_world = {}  # player name -> {"t":[...], "rows":[...]} omniscient state samples
    item_events = _extract_item_events(data)
    frag_events = _extract_frag_events(data)

    players_out = []
    for p in data["streams"]["players"]:
        pos = p.get("pos") or {}
        if not pos.get("t"):
            continue
        name = p.get("name") or ""
        # (T4) every player's omniscient samples — used to populate actor_ticks for EVERY
        # episode (self + others), keyed by absolute demo-time. Built even for players too short
        # to form their own episodes (they still appear in OTHER players' omniscient world).
        actor_world[name] = _actor_samples(p)
        frames = _player_frames(pos)
        if len(frames) < MIN_EPISODE_FRAMES:
            continue
        # (T3) forward-fill this player's health/armor onto each frame by demo-time (t_ms).
        rt = _resource_timeline(events, p.get("name") or "")
        for f in frames:
            f["health"] = _fill_resource(rt["health"], f["t_ms"])
            f["armor"] = _fill_resource(rt["armor"], f["t_ms"])
        onground = _recover_onground(frames, prober)
        jump = _recover_jumps(onground, frames)

        # episode boundaries: teleport/respawn discontinuities + a hard length cap.
        tele = set(pmove_sim.detect_teleports(frames))
        episodes = []
        seg_start = 0
        n = len(frames)
        for k in range(n):
            boundary = (k in tele) or (k - seg_start + 1 >= MAX_EPISODE_FRAMES) or (k == n - 1)
            if boundary:
                seg = frames[seg_start:k + 1]
                if len(seg) >= MIN_EPISODE_FRAMES:
                    episodes.append(_pack_episode(
                        seg, onground[seg_start:k + 1], jump[seg_start:k + 1], seg_start))
                seg_start = k + 1

        players_out.append({
            "name": p.get("name") or "",
            "team": p.get("team"),
            "n_frames": n,
            "n_onground_true": sum(1 for g in onground if g),
            "n_jumps": sum(1 for j in jump if j),
            "episodes": episodes,
        })

    return {
        "ok": True,
        "demo": demo.name,
        "sha256": sha,
        "n_players": len(players_out),
        "players": players_out,
        # (T4) the omniscient world streams (JSON-serializable; cross the ProcessPool cleanly).
        "teams": teams,                # roster team names
        "actor_world": actor_world,    # player name -> time-sorted omniscient state samples
        "item_events": item_events,    # pickup/respawn/drop timeline (name+kind+origin keyed)
        "frag_events": frag_events,    # kill timeline (killer/victim NAME keyed)
    }


def insert_demo(con: sqlite3.Connection, map_id: int, rec: dict, split: str, demo_id: int) -> dict:
    """Insert one extracted .mvd's demos/players/episodes/player_ticks/actions rows.
    `split` is the train/val/test label for ALL of this demo's episodes (group-by-demo).

    `demo_id` is assigned DETERMINISTICALLY by the caller (sha-rank, see build) — NOT an
    autoincrement side effect of insertion order. The streaming insert lands demos in parallel
    completion order, so an autoincrement id would vary with parse timing across rebuilds; the
    trainer keys its held-out-demo validation split on demo_id, so a content-stable id is required
    for reproducible splits.

    demos has UNIQUE(sha256); a byte-identical demo already loaded this run is SKIPPED
    (no rows -> no orphan children) and reported, exactly like the QWD ETL."""
    dup = con.execute("SELECT demo_id, path FROM demos WHERE sha256=?", (rec["sha256"],)).fetchone()
    if dup is not None:
        return {"skipped_duplicate": True, "demo": rec["demo"], "sha256": rec["sha256"],
                "duplicate_of": dup[1], "duplicate_of_id": dup[0]}

    con.execute(
        """INSERT INTO demos (demo_id, path, source, map_id, demo_kind, sha256, parser_commit)
           VALUES (?,?,?,?,?,?,?)""",
        (demo_id, rec["demo"], "mvd", map_id, "4on4", rec["sha256"], "qw-analyze:schema33"),
    )

    stem = Path(rec["demo"]).stem[:48]

    def _player_id(name: str) -> int:
        """Resolve a per-demo MVD player NAME to a stable players.player_id (handle disambiguated
        by demo, .mvd carries no persistent id). Shared by the movement spine + the T4 world so a
        killer/victim/picker and an episode owner map to ONE id."""
        nm = (name or "p").strip() or "p"
        handle = "mvd:%s#%s" % (stem, nm.lower())
        con.execute("INSERT OR IGNORE INTO players (handle, is_bot) VALUES (?,0)", (handle,))
        return con.execute("SELECT player_id FROM players WHERE handle=?", (handle,)).fetchone()[0]

    # (T4) teams roster: one row per distinct roster team name, side A/B by first-seen order
    # (the canonical labels region_control_timeline uses; degenerate for FFA/1on1).
    team_id_by_name: dict[str, int] = {}
    for i, tname in enumerate(rec.get("teams") or []):
        side = "A" if i == 0 else ("B" if i == 1 else None)
        c = con.execute("INSERT INTO teams (demo_id, name, side) VALUES (?,?,?)", (demo_id, tname, side))
        team_id_by_name[tname] = c.lastrowid

    # (T4) register EVERY player in the omniscient world (incl. ones too short to own an episode)
    # so actor_ticks / frag_events / item_events can reference them. team_id_by_player maps each
    # to its absolute team for actor_ticks credit attribution.
    actor_world = rec.get("actor_world") or {}
    team_of_player: dict[str, str] = {}
    for p in rec["players"]:
        if p.get("team"):
            team_of_player[(p["name"] or "").strip()] = p["team"]
    pid_by_name: dict[str, int] = {}
    team_id_by_player: dict[str, int] = {}
    for name in actor_world:
        pid = _player_id(name)
        pid_by_name[name] = pid
        tn = team_of_player.get((name or "").strip())
        team_id_by_player[name] = team_id_by_name.get(tn) if tn else None

    # pre-resolve item static origins -> item_id for the item_events spatial join (rounded to int qu,
    # the schema's UNIQUE key resolution; the decoder emits integer item origins).
    item_id_by_origin: dict[tuple, int] = {}
    for iid, ox, oy, oz in con.execute("SELECT item_id, origin_x, origin_y, origin_z FROM items").fetchall():
        item_id_by_origin[(round(ox), round(oy), round(oz))] = iid

    n_pl = n_ep = n_tick = n_act = n_actor = 0
    for p in rec["players"]:
        if not p["episodes"]:
            continue
        # one players row per active player; real MVD name -> stable handle (lowercased).
        # Disambiguate by demo so the same display-name across demos does not falsely merge
        # (.mvd carries no persistent player id).
        name = (p["name"] or "p").strip() or "p"
        player_id = pid_by_name.get(p["name"] or "") or _player_id(name)
        n_pl += 1

        for ep in p["episodes"]:
            c = con.execute(
                """INSERT INTO episodes
                   (demo_id, player_id, map_id, start_tick, end_tick, n_steps, split, split_policy)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (demo_id, player_id, map_id, ep["start"], ep["end"], ep["n"], split, SPLIT_POLICY),
            )
            episode_id = c.lastrowid
            n_ep += 1
            for r in ep["frames"]:
                con.execute(
                    """INSERT INTO player_ticks
                       (episode_id, tick, t_s, msec, ox, oy, oz, vx, vy, vz,
                        pitch, yaw, roll, hspeed, onground, onground_is_proxy, health, armor)
                       VALUES (?,?,?,?, ?,?,?, ?,?,?, ?,?,?, ?,?,?, ?,?)""",
                    (episode_id, r["tick"], r["t_s"], r["msec"],
                     r["ox"], r["oy"], r["oz"], r["vx"], r["vy"], r["vz"],
                     r["pitch"], r["yaw"], r["roll"], r["hspeed"],
                     r["onground"], True,  # onground_is_proxy=TRUE (geometric, no server flag)
                     r.get("health"), r.get("armor")),  # T3 forward-filled; armor_type/weapon NULL
                )
                n_tick += 1
                con.execute(
                    """INSERT INTO actions
                       (episode_id, tick, forwardmove, sidemove, upmove, buttons,
                        cmd_yaw, cmd_pitch, cmd_roll, label_source, confidence, is_interp)
                       VALUES (?,?,?,?,?,?, ?,?,?, ?,?,?)""",
                    (episode_id, r["tick"], r["fwd"], r["side"], r["up"], r["buttons"],
                     r["cmd_yaw"], r["cmd_pitch"], 0.0, "idm", r["confidence"], r["is_interp"]),
                )
                n_act += 1

                # (T4) actor_ticks: the OMNISCIENT world for THIS episode tick — every player's
                # exact state aligned to the ego frame's absolute demo-time (MVD has all players;
                # no PVS/staleness gate, that masking is the separate actor_visibility layer T8).
                # onground/onground_is_proxy/waterlevel/weapon left NULL here: onground needs the
                # per-worker BSP prober (it lives on the ego player_ticks spine); weapon has no
                # honest active-weapon source (same reason as T3). PK (episode_id, tick, actor_id).
                t_ms = r.get("t_ms", 0)
                for aname, samp in actor_world.items():
                    j = _nearest_sample(samp["t"], t_ms)
                    if j is None:
                        continue
                    s = samp["rows"][j]
                    con.execute(
                        """INSERT OR IGNORE INTO actor_ticks
                           (episode_id, tick, actor_id, team_id, alive, ox, oy, oz, vx, vy, vz,
                            pitch, yaw, roll, hspeed, onground, onground_is_proxy,
                            health, armor, armor_type, weapon)
                           VALUES (?,?,?,?,?, ?,?,?, ?,?,?, ?,?,?, ?,?,?, ?,?,?,?)""",
                        (episode_id, r["tick"], pid_by_name[aname], team_id_by_player.get(aname),
                         s["alive"], s["ox"], s["oy"], s["oz"], s["vx"], s["vy"], s["vz"],
                         s["pitch"], s["yaw"], s["roll"], s["hspeed"],
                         None, False, s["health"], s["armor"], s["armor_type"], None),
                    )
                    n_actor += 1

    # (T4) match-level timelines (one set per demo, NOT per episode).
    n_ie = n_fe = 0
    for ev in rec.get("item_events") or []:
        origin = (ev.get("ox"), ev.get("oy"), ev.get("oz"))
        item_id = None
        if None not in origin:
            item_id = item_id_by_origin.get((round(origin[0]), round(origin[1]), round(origin[2])))
        picker = pid_by_name.get(ev.get("player") or "") if ev.get("player") else None
        # a non-static drop (backpack) keeps origin_x/y/z; a static pickup/respawn joins item_id.
        keep_origin = item_id is None and None not in origin
        con.execute(
            """INSERT INTO item_events
               (demo_id, item_id, t_s, event_kind, player_id, origin_x, origin_y, origin_z,
                item_type, team_id)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (demo_id, item_id, ev["t_ms"] / 1000.0, ev["kind"], picker,
             origin[0] if keep_origin else None, origin[1] if keep_origin else None,
             origin[2] if keep_origin else None, ev.get("item_type"),
             team_id_by_name.get(ev.get("team")) if ev.get("team") else None),
        )
        n_ie += 1
    for fr in rec.get("frag_events") or []:
        killer = pid_by_name.get(fr.get("killer") or "") if fr.get("killer") else None
        victim = pid_by_name.get(fr.get("victim") or "") if fr.get("victim") else None
        con.execute(
            """INSERT INTO frag_events
               (demo_id, t_s, killer_id, victim_id, weapon, is_suicide, is_teamkill)
               VALUES (?,?,?,?,?,?,?)""",
            (demo_id, fr["t_ms"] / 1000.0, killer, victim, fr.get("weapon"),
             fr["is_suicide"], fr["is_teamkill"]),
        )
        n_fe += 1

    return {"demo_id": demo_id, "players": n_pl, "episodes": n_ep,
            "player_ticks": n_tick, "actions": n_act, "actor_ticks": n_actor,
            "teams": len(team_id_by_name), "item_events": n_ie, "frag_events": n_fe}


def load_manifest(manifest_path: Path) -> list[dict]:
    """Load the corpus manifest (schema v3) and return the TRAIN demos WITH their content lock.

    Each entry: {"path", "sha256", "size_bytes"}. Selection is EXPLICIT — only rows whose class
    is exactly 'TRAIN' are loaded; a row with a missing/blank class is REJECTED (never silently
    treated as TRAIN), so a malformed manifest can't leak an unlabeled demo into training. The
    sha256/size_bytes are the content lock the extractor verifies before trusting the bytes on
    disk (see extract_demo / build)."""
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        entries = raw
    elif isinstance(raw, dict):
        entries = raw.get("demos") or raw.get("entries") or []
    else:
        entries = []
    out = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        cls = (e.get("classification") or e.get("class") or "").strip().upper()
        if cls != "TRAIN":  # explicit-TRAIN-only: missing/blank/other class is NOT training data
            continue
        path = e.get("path") or e.get("abspath") or e.get("file") or e.get("demo")
        if not path:
            continue
        sha = (e.get("sha256") or "").strip().lower() or None
        size = e.get("size_bytes")
        out.append({"path": str(path), "sha256": sha,
                    "size_bytes": int(size) if isinstance(size, int) else None})
    return out


# Split provenance (audited in episodes.split_policy). MVD episodes are bucketed per demo by a
# hash of the demo's OWN sha256 (split_for_sha) — a DIFFERENT assignment mechanism than the QWD
# ETL's positional assign_splits, even though both share the group-by-demo INVARIANT (no demo
# straddles a split). The value is VERSIONED so a generated catalog records exactly which method
# produced `split`, and a re-run is reconstructable from the hash + thresholds below.
SPLIT_POLICY = "group_by_demo_sha256_bucket_v1"
SPLIT_RATIOS = (0.70, 0.15, 0.15)  # train / val / test; also recorded in the build summary


def split_for_sha(sha: str, ratios=SPLIT_RATIOS) -> str:
    """Pick a demo's train/val/test split from its OWN content hash (policy=SPLIT_POLICY).

    Mechanism (the durable contract — keep in sync with SPLIT_POLICY's version and
    data/catalog/dataset_spec.yaml): u = int(sha256_hex[:8], 16) / 0xFFFFFFFF in [0,1]
    (all-f hashes to exactly 1.0 -> test); train if u < 0.70, val if u < 0.85, else test.

    This is what lets build() stream: a demo's split depends only on its sha256, so each demo
    can be inserted the instant its parse finishes — no global ordering, so we never hold all
    demos in RAM to assign positions (the old assign_splits did, which OOM'd the 1537-corpus).
    Content-stable too: the same demo always lands in the same split as the corpus grows or
    reorders (positional round-robin reshuffled every demo when one was added/removed). Still
    group-by-demo — one label for ALL of a demo's episodes, so nothing straddles the boundary."""
    u = int((sha or "0")[:8], 16) / 0xFFFFFFFF
    train_hi, val_hi = ratios[0], ratios[0] + ratios[1]
    return "train" if u < train_hi else ("val" if u < val_hi else "test")


def build(catalog_dir: Path, manifest: Path, db_path: str, bsp_path: str,
          qw_analyze: str, workers: int = 2, limit: int = 0) -> dict:
    """Build a populated MOVE catalog: static spine + per-tick rows recovered from .mvd demos."""
    entries = load_manifest(manifest)
    if limit:
        entries = entries[:limit]

    # provenance gate (req): every TRAIN row must carry a content lock, and each file's bytes
    # must match it before we trust them. A missing lock or a mismatch is FATAL — fail loud.
    missing_lock = [e["path"] for e in entries if not e["sha256"]]
    if missing_lock:
        raise RuntimeError(
            "manifest provenance: %d TRAIN rows lack a sha256 content lock (need a schema-v3 "
            "manifest); first: %s" % (len(missing_lock), missing_lock[:3]))

    con, base = catalog_load.build(catalog_dir, fixture_dir=None, db_path=db_path)
    map_id = con.execute("SELECT map_id FROM maps WHERE name='dm3'").fetchone()[0]

    # Deterministic demo_id from content identity (sha-rank), NOT an autoincrement side effect of
    # parallel completion order: the streaming insert lands demos as they finish parsing, so an
    # autoincrement id would vary with timing across rebuilds. The trainer keys its held-out-demo
    # validation split on demo_id, so the same manifest+bytes must always yield the same ids.
    demo_id_by_sha = {sha: i + 1 for i, sha in enumerate(sorted({e["sha256"] for e in entries}))}

    t0 = time.time()
    errors, per_demo, skipped_dups = [], [], []
    total = len(entries)
    LOGGER.info("MVD ETL: extracting %d demos with %d workers (streaming insert) ...", total, workers)

    def _consume(r):
        """Insert one finished demo, commit, and let it go. This is the memory bound: a demo's
        heavy per-tick frames live only from parse to insert — never all N demos at once, which
        is what the old accumulate-then-insert did and what OOM'd the 1537-corpus."""
        if r.get("sha_mismatch"):  # provenance failure -> abort the whole run (corpus corruption)
            raise RuntimeError(
                "manifest provenance: %s failed sha256 verification (the bytes on disk are not "
                "what was classified); aborting: %s" % (r.get("demo"), r.get("error")))
        if not r.get("ok"):
            errors.append(r)
        else:
            split = split_for_sha(r.get("sha256"))
            ins = insert_demo(con, map_id, r, split, demo_id_by_sha[r["sha256"]])
            if ins.get("skipped_duplicate"):
                skipped_dups.append(ins)
                LOGGER.info("  SKIP duplicate sha256: %s (== %s)", r["demo"], ins.get("duplicate_of"))
            else:
                ins.update(demo=r["demo"], split=split, n_players_extracted=r.get("n_players"))
                per_demo.append(ins)
            con.commit()  # flush per demo so SQLite (not RAM) holds the growing corpus
        done = len(per_demo) + len(errors) + len(skipped_dups)
        if r.get("ok"):
            LOGGER.info("  %d/%d  %s  (%d players)", done, total, r.get("demo"), r.get("n_players", 0))
        else:
            LOGGER.info("  %d/%d  %s  (ERR: %s)", done, total, r.get("demo"), r.get("error", ""))

    # If the streaming loop aborts (e.g. a fatal provenance sha_mismatch mid-run), CLOSE the
    # connection before the exception reaches main() — otherwise main()'s _purge() of the
    # `.partial` DB fails on Windows (WinError 32: cannot unlink a file with an open handle).
    try:
        if workers > 1 and total > 1:
            window = max(2, workers * 2)  # keep ~2x workers in flight, NOT all `total` at once
            with ProcessPoolExecutor(max_workers=workers) as ex:
                pending, nxt = set(), 0
                while nxt < total and len(pending) < window:
                    e = entries[nxt]; nxt += 1
                    pending.add(ex.submit(extract_demo, e["path"], qw_analyze, bsp_path, e["sha256"]))
                while pending:
                    finished, pending = wait(pending, return_when=FIRST_COMPLETED)
                    for fut in finished:
                        _consume(fut.result())
                        if nxt < total:  # refill: one new parse per completion keeps the window full
                            e = entries[nxt]; nxt += 1
                            pending.add(ex.submit(extract_demo, e["path"], qw_analyze, bsp_path, e["sha256"]))
        else:
            for e in entries:
                _consume(extract_demo(e["path"], qw_analyze, bsp_path, e["sha256"]))
    except BaseException:
        con.close()  # release the handle so main() can purge the .partial (Windows-safe)
        raise

    con.commit()
    counts = table_counts(con)
    summary = {
        "db": db_path,
        "catalog_dir": str(catalog_dir),
        "static_spine": base,
        "demos_attempted": len(entries),
        "demos_loaded": len(per_demo),
        "demos_failed": len(errors),
        "demos_skipped_duplicate": len(skipped_dups),
        "extract_secs": round(time.time() - t0, 1),
        "split_policy": SPLIT_POLICY,  # recorded per-episode in catalog.episodes.split_policy too
        "split_spec": {  # the durable, reconstructable split contract (gate item 2: provenance)
            "method": SPLIT_POLICY,
            "assignment": "per-demo sha256 bucket",
            "hash_input": "int(sha256_hex[:8], 16) / 0xFFFFFFFF",
            "thresholds": {"train": SPLIT_RATIOS[0], "val": SPLIT_RATIOS[0] + SPLIT_RATIOS[1]},
            "ratios": {"train": SPLIT_RATIOS[0], "val": SPLIT_RATIOS[1], "test": SPLIT_RATIOS[2]},
            "invariant": "group_by_demo (no demo straddles a split)",
        },
        "split_counts": _split_counts(per_demo),
        "table_counts": counts,
        "onground_distinct": _onground_distinct(con),
        "strafe_label_stats": _strafe_label_stats(con),
        "per_demo": per_demo,
        "skipped_duplicate_demos": skipped_dups,
        "errors": [{"demo": e["demo"], "error": e["error"]} for e in errors],
    }
    return {"con": con, "summary": summary}


def _split_counts(per_demo) -> dict:
    out = {"train": 0, "val": 0, "test": 0}
    for d in per_demo:
        out[d["split"]] = out.get(d["split"], 0) + 1
    return out


def _onground_distinct(con: sqlite3.Connection) -> list:
    try:
        return sorted(int(bool(r[0])) for r in
                      con.execute("SELECT DISTINCT onground FROM player_ticks").fetchall())
    except sqlite3.OperationalError:
        return []


def _strafe_label_stats(con: sqlite3.Connection) -> dict:
    """Report the recovered-label health AND the interim hold-out state.

    `above_gate_strafe_sign_rows` is the RECOVERABLE signal — bhop-regime confident-turn rows
    whose strafe sign is good (these become trainable once per-head weights land). `trainable_*`
    is what trains TODAY: currently 0, because every idm row is held out (is_interp=1) to avoid
    the forwardmove poisoning until per-head weights exist. The two differing is expected."""
    try:
        above_gate = con.execute(
            "SELECT COUNT(*) FROM actions WHERE label_source='idm' AND sidemove != 0 "
            "AND confidence >= ?", (STRAFE_CONF,)).fetchone()[0]
        trainable = con.execute(
            "SELECT COUNT(*) FROM actions WHERE is_interp=0 AND sidemove != 0").fetchone()[0]
        total_actions = con.execute("SELECT COUNT(*) FROM actions").fetchone()[0]
        held_out = con.execute("SELECT COUNT(*) FROM actions WHERE is_interp=1").fetchone()[0]
        jump_rows = con.execute("SELECT COUNT(*) FROM actions WHERE (buttons & 2) != 0").fetchone()[0]
        return {
            "above_gate_strafe_sign_rows": above_gate,   # recoverable bhop-regime sign signal
            "trainable_strafe_sign_rows": trainable,     # trains today (0 during the hold-out)
            "held_out_action_rows": held_out,            # == total during the interim hold-out
            "total_action_rows": total_actions,
            "jump_press_rows": jump_rows,
            "jump_press_rate": round(jump_rows / total_actions, 5) if total_actions else None,
        }
    except sqlite3.OperationalError:
        return {}


TABLES = ["maps", "items", "markers", "nav_edges", "players", "demos",
          "episodes", "player_ticks", "actions",
          "teams", "actor_ticks", "item_events", "frag_events"]  # T4 omniscient world


def table_counts(con: sqlite3.Connection) -> dict:
    out = {}
    for t in TABLES:
        try:
            out[t] = con.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
        except sqlite3.OperationalError:
            out[t] = None
    return out


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    sys.setrecursionlimit(20000)
    ap = argparse.ArgumentParser(description="Populate the MOVE catalog from human 4on4 dm3 .mvd demos")
    ap.add_argument("--catalog-dir", type=Path, required=True)
    ap.add_argument("--manifest", type=Path, required=True,
                    help="corpus manifest (schema v3); only rows with an explicit class=='TRAIN' "
                         "are loaded, and each must carry a sha256 content lock")
    ap.add_argument("--db", required=True, help="output .sqlite path")
    ap.add_argument("--bsp", default=DEFAULT_BSP, help="dm3 BSP for geometric onground floor-trace")
    ap.add_argument("--qw-analyze", default=DEFAULT_QW_ANALYZE,
                    help="schema-33 qw-analyze binary (default ~/qw-sim/bin/qw-analyze-v20)")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--allow-empty", action="store_true",
                    help="exit 0 even when NO demos loaded (static-only catalog). Default: a "
                         "zero-demo load is an error so automation can't accept an empty catalog.")
    args = ap.parse_args(argv)

    qw_analyze = str(Path(args.qw_analyze).expanduser())
    bsp_path = str(Path(args.bsp).expanduser())
    if not Path(qw_analyze).exists():
        LOGGER.error("qw-analyze binary not found: %s", qw_analyze)
        return 2
    if not Path(bsp_path).exists():
        LOGGER.error("dm3 BSP not found: %s", bsp_path)
        return 2

    # ATOMIC PUBLISH (fail-closed artifact): build into a `.partial` sibling and rename to the
    # canonical --db ONLY after the run succeeds AND passes the non-empty gate. Because the
    # streaming insert commits each demo as it lands, a fatal mid-run abort (e.g. a provenance
    # sha_mismatch) WOULD otherwise leave a partial, consumable catalog at the canonical path that
    # a downstream job could mistake for a complete corpus. With this, the canonical path only
    # ever holds a complete, gate-passed catalog; a failed run leaves nothing there.
    dbp = Path(args.db)
    tmp = dbp.parent / (dbp.name + ".partial")
    dbp.parent.mkdir(parents=True, exist_ok=True)

    def _purge(p: Path) -> None:  # remove a sqlite db and its exact -wal/-shm/-journal sidecars
        for suffix in ("", "-wal", "-shm", "-journal"):
            Path(str(p) + suffix).unlink(missing_ok=True)

    # Do NOT delete an existing canonical --db up front: build into the .partial and let the
    # success-path os.replace() overwrite it ATOMICALLY. A failed/empty rebuild then PRESERVES the
    # previous known-good catalog (an expensive verified corpus) instead of destroying it; only the
    # new partial is purged on failure. (os.replace overwrites the destination on POSIX and Windows.)
    _purge(tmp)   # clear only a leftover partial from a prior aborted run; the canonical db is untouched

    # Build into the .partial, then publish atomically. The `finally` purges the partial unless we
    # PUBLISHED — so EVERY non-success path fails closed and leaves no consumable partial catalog at
    # the predictable path: a RuntimeError provenance abort, a sqlite OperationalError /
    # BrokenProcessPool / packing error mid-insert, the empty-gate, or any unexpected error.
    published = False
    try:
        res = build(args.catalog_dir, args.manifest, str(tmp), bsp_path, qw_analyze,
                    workers=args.workers, limit=args.limit)
        con = res.get("con")
        if con is not None:
            con.close()  # summary is built; close before the rename so no open handle blocks it (Windows)
        # record the CANONICAL published path, not the internal .partial build() wrote to — the
        # printed/committed summary must point at where the catalog actually lands (rc=0).
        res["summary"]["db"] = str(dbp)
        print(json.dumps(res["summary"], indent=2, default=str))
        # non-empty hard gate: a run that loaded demos but produced NO rows (analyzer export too
        # short/malformed after the schema guard, every demo zero-episode) must FAIL, not exit 0
        # with an empty catalog. Require player_ticks>0 AND actions>0 for a non-empty run.
        tc = res["summary"].get("table_counts") or {}
        empty = (res["summary"]["demos_loaded"] == 0
                 or not tc.get("player_ticks") or not tc.get("actions"))
        if empty and not args.allow_empty:
            LOGGER.error("empty load: demos_loaded=%s player_ticks=%s actions=%s — a non-empty run "
                         "requires player_ticks>0 AND actions>0. Pass --allow-empty for a "
                         "static-only catalog.", res["summary"]["demos_loaded"],
                         tc.get("player_ticks"), tc.get("actions"))
            return 2
        # Publish safely. A leftover canonical -wal/-shm carries the WAL's own page-1 header, so it
        # WOULD shadow a freshly replaced main DB — a reader opens the path in WAL mode and replays
        # the OLD frames despite rc=0 (verified empirically). Stale sidecars MUST therefore be
        # cleared before the new catalog is visible. But first make the OLD catalog SELF-CONSISTENT
        # so nothing we delete is an unrecovered recovery record: opening the db lets SQLite roll
        # back any hot -journal (and remove it), and a WAL checkpoint(TRUNCATE) folds any -wal into
        # the main file. Both are lossless — an interrupted, uncommitted transaction is correctly
        # discarded. Then a failed replace still leaves a complete, consistent old catalog. If any
        # step is blocked (a live reader / locked sidecar), FAIL CLOSED: do not publish.
        wal = Path(str(dbp) + "-wal")
        try:
            if dbp.exists():
                rec = sqlite3.connect(str(dbp))
                try:
                    rec.execute("PRAGMA schema_version")  # forces a read lock -> hot-journal rollback
                    if wal.exists():
                        busy, _log, _ck = rec.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                        if busy:  # a reader/writer blocked the fold — removing -wal would lose data
                            raise RuntimeError("WAL checkpoint busy (the canonical catalog is held open)")
                finally:
                    rec.close()
            for suffix in ("-wal", "-shm", "-journal"):
                Path(str(dbp) + suffix).unlink(missing_ok=True)
        except (OSError, sqlite3.Error, RuntimeError) as e:
            LOGGER.error("cannot make the canonical catalog consistent / clear its sidecars before "
                         "publish (locked / live reader?): %s — NOT publishing; preserved.", e)
            return 2
        try:
            os.replace(tmp, dbp)  # atomic publish: the canonical path now holds the new catalog
        except OSError as e:
            LOGGER.error("publish failed (could not replace canonical db): %s — existing catalog "
                         "preserved (its WAL was folded in, so no committed data is lost).", e)
            return 2
        published = True
        return 0
    except RuntimeError as e:
        LOGGER.error("FATAL provenance/build error: %s", e)
        return 3
    finally:
        if not published:
            _purge(tmp)  # any non-published outcome (incl. an unexpected re-raised error) leaves nothing


if __name__ == "__main__":
    raise SystemExit(main())
