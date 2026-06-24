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
        })
    return frames


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
            "msec": msec,
            "ox": o[0], "oy": o[1], "oz": o[2],
            "vx": v[0], "vy": v[1], "vz": v[2],
            "pitch": pitch, "yaw": yaw, "roll": 0.0,
            "hspeed": round(hspeed, 3),
            "onground": onground,
            "fwd": FORWARDMOVE_PRIOR, "side": side, "up": upmove,
            "buttons": buttons,
            "cmd_yaw": yaw, "cmd_pitch": pitch,
            "confidence": confidence,
            "is_interp": is_interp,
        })
        t_s += dt
    return {"start": start_tick, "end": start_tick + len(seg) - 1, "n": len(seg), "frames": rows}


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

    try:
        prober = OngroundProber(bsp_path)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "demo": demo.name, "error": "bsp:%s: %s" % (type(e).__name__, e)}

    players_out = []
    for p in data["streams"]["players"]:
        pos = p.get("pos") or {}
        if not pos.get("t"):
            continue
        frames = _player_frames(pos)
        if len(frames) < MIN_EPISODE_FRAMES:
            continue
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

    n_pl = n_ep = n_tick = n_act = 0
    for p in rec["players"]:
        if not p["episodes"]:
            continue
        # one players row per active player; real MVD name -> stable handle (lowercased).
        # Disambiguate by demo so the same display-name across demos does not falsely merge
        # (.mvd carries no persistent player id).
        name = (p["name"] or "p").strip() or "p"
        handle = "mvd:%s#%s" % (Path(rec["demo"]).stem[:48], name.lower())
        con.execute("INSERT OR IGNORE INTO players (handle, is_bot) VALUES (?,0)", (handle,))
        player_id = con.execute("SELECT player_id FROM players WHERE handle=?", (handle,)).fetchone()[0]
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
                        pitch, yaw, roll, hspeed, onground, onground_is_proxy)
                       VALUES (?,?,?,?, ?,?,?, ?,?,?, ?,?,?, ?,?,?)""",
                    (episode_id, r["tick"], r["t_s"], r["msec"],
                     r["ox"], r["oy"], r["oz"], r["vx"], r["vy"], r["vz"],
                     r["pitch"], r["yaw"], r["roll"], r["hspeed"],
                     r["onground"], True),  # onground_is_proxy=TRUE (geometric, no server flag)
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

    return {"demo_id": demo_id, "players": n_pl, "episodes": n_ep,
            "player_ticks": n_tick, "actions": n_act}


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
          "episodes", "player_ticks", "actions"]


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
        # cleared before the new catalog is visible. Clear them BEFORE the replace, but first
        # CHECKPOINT any existing WAL into its main file (lossless) so that if the subsequent replace
        # fails, the preserved old catalog still has every committed row. If any step is blocked
        # (a live reader / locked sidecar), FAIL CLOSED: do not publish, leaving the old db + its
        # sidecars a consistent, complete unit.
        wal = Path(str(dbp) + "-wal")
        try:
            if dbp.exists() and wal.exists():
                cp = sqlite3.connect(str(dbp))
                try:
                    busy, _log, _ck = cp.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                finally:
                    cp.close()
                if busy:  # a reader/writer blocked the fold — removing -wal now would lose data
                    raise RuntimeError("WAL checkpoint busy (the canonical catalog is held open)")
            for suffix in ("-wal", "-shm", "-journal"):
                Path(str(dbp) + suffix).unlink(missing_ok=True)
        except (OSError, sqlite3.Error, RuntimeError) as e:
            LOGGER.error("cannot clear a stale canonical WAL/sidecar before publish (locked / live "
                         "reader?): %s — NOT publishing; existing catalog preserved.", e)
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
