"""catalog_etl_qwd.py — populate the Strategy-A relational catalog from REAL demos (P1).

Pure standard library only (sqlite3, json, math, pathlib, argparse, multiprocessing).
NO third-party imports — this module obeys the same stdlib-only gate as the rest of
`scripts/` (the merge gate runs it on bare Python 3.12). Heavy deps stay under `ml/`.

WHAT THIS IS FOR
----------------
`catalog_load.py` builds the catalog's STATIC spine (maps/items/markers/nav) plus a
single hand-extracted fixture's identity/team/frag rows. It does NOT populate the
per-tick trajectory tables (`episodes`, `player_ticks`, `actions`). Until now the only
demos-derived row source was the single `dm3_milton_211436` fixture.

This driver closes that gap for the SELF-POV / movement layer of the catalog: it runs
the validated `.qwd` extractor (`build_replay_command_file.build_replay_frames`, the
exact path the Stage-2 MOVE-BC pool uses) over a list of real dm3 4on4 self-POV demos
and loads, per demo:

    demos        <- one row per .qwd (source='qwd', the POV action-fidelity tier)
    players      <- the POV player handle
    episodes     <- contiguous trajectory segments, split at teleport/respawn
                    discontinuities (pmove_sim.detect_teleports) so an episode never
                    straddles a teleporter ride or a death/respawn
    player_ticks <- the ego-self per-tick STATE spine (o, v, angles, hspeed, onground,
                    pm_code), finite-differenced velocity from the dense input path
    actions      <- the recovered (state,action) LABELS (forwardmove/sidemove/upmove,
                    buttons, commanded view angles), label_source='qwd_usercmd',
                    confidence=1.0 (ground-truth human inputs)

A train/val/test split is then assigned GROUPED BY demo_id (round-robin over distinct
demos) and written to episodes.split, so no demo's frames straddle the split boundary.

WHAT THIS DOES NOT DO (reported, not silently skipped)
------------------------------------------------------
The OMNISCIENT all-actor world state (`actor_ticks`), the POMDP visibility layer
(`actor_visibility`), audio (`audio_cues`), and the item/region timelines come from the
server-side `.mvd` path (mvd_analyzer getStateAt/getEvents/getRegionControl), not from a
self-POV `.qwd`. A `.qwd` only carries the recording player's own state + inputs. Those
layers are populated from `.mvd` demos in a follow-up (the broadening step). To keep the
relational tables that DO have fixture data non-empty, `--with-fixture` additionally
folds the `dm3_milton_211436` fixture's teams/frag_events/item_events/region_control
rows in (the same content `catalog_load.load_fixture` covers, extended here to the
item/region samples) so a populated catalog exercises the team layer too.

USAGE
-----
    python scripts/catalog_etl_qwd.py \
        --catalog-dir data/catalog \
        --demo-list   <player TAB abspath.qwd per line> \
        --db          data/catalog/dm3_4on4.sqlite \
        --with-fixture data/fixtures/dm3_milton_211436 \
        --workers 2 [--limit N]

Repo destination: scripts/catalog_etl_qwd.py
"""
from __future__ import annotations

import argparse
import bisect
import json
import math
import sqlite3
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
for _p in (str(REPO_ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import catalog_load  # noqa: E402  (stdlib-only sibling)
import build_replay_command_file as brc  # noqa: E402  (stdlib-only; .qwd extractor)
import pmove_sim  # noqa: E402  (stdlib-only; detect_teleports for episode boundaries)
import qwd_observed_others as obs  # noqa: E402  (stdlib-only; observed-OTHERS decoder, P2)
from tools.qwd_usercmd import qwd_usercmd  # noqa: E402  (stdlib-only; absolute command times)

BUTTON_JUMP = pmove_sim.BUTTON_JUMP  # 2

# An episode is a contiguous run of frames between discontinuities. Besides the
# teleport/respawn jumps pmove_sim.detect_teleports finds, cap episode length so a
# single 20-minute demo becomes several training-sized trajectories rather than one
# enormous one (matches the continuity-split intent of the `episodes` table).
MAX_EPISODE_FRAMES = 2048
MIN_EPISODE_FRAMES = 24  # drop slivers (consistent with the MOVE-BC clean-run floor)

# Observed-OTHER alignment (P2 / agent_observation): each self episode-tick samples,
# per OTHER player, that player's most recently-RECEIVED svc_playerinfo state. We attach
# an observed-other to a tick only if its latest sample is within this staleness window;
# beyond it the other is treated as not-currently-observed (it has left PVS / gone stale).
# 0.5 s ≈ several server frames at 77 fps — generous enough to bridge a single dropped/
# choked update, tight enough that a long-gone player does not linger in the omniscient
# table. (The carried-forward BELIEF/memory of stale players is the DEFERRED
# actor_visibility layer, not actor_ticks.)
OBSERVED_MAX_STALENESS_S = 0.5


def _hspeed(v) -> float:
    return math.hypot(float(v[0]), float(v[1]))


def extract_demo(demo_path: str) -> dict:
    """Worker: parse one .qwd into the per-tick rows for the catalog.

    Returns a JSON-serializable dict (so it crosses the process boundary cleanly):
        {ok, demo, sha256, map_level, playernum, n_frames, coverage,
         episodes:[{start,end,n,frames:[...]}]}  on success
        {ok:False, demo, error}                  on failure
    Never raises into the pool — a bad demo is recorded and skipped.
    """
    demo = Path(demo_path)
    try:
        data = demo.read_bytes()
        frames, meta = brc.build_replay_frames(demo, alignment="time")
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "demo": demo.name, "error": f"build:{type(e).__name__}: {e}"}
    if not frames:
        return {"ok": False, "demo": demo.name, "error": "no frames"}

    # Absolute QWD demo-time per self frame. build_replay_frames emits exactly one frame
    # per outgoing usercmd (1:1, in order), so the command stream's time_s aligns by index.
    # actor_ticks is sampled on this absolute clock, so we must carry it onto each tick.
    try:
        cmd_times = [c.time_s for c in qwd_usercmd.parse_qwd_bytes(data, source_path=demo).commands]
    except Exception:  # noqa: BLE001
        cmd_times = []
    for i, f in enumerate(frames):
        f["abs_t_s"] = cmd_times[i] if i < len(cmd_times) else None

    # Observed-OTHER players (the in-PVS agent_observation layer). Decode is best-effort:
    # a demo that is not protocol-28 / is FTE just yields no observed-others (reported),
    # the self movement layer is unaffected.
    observed = _decode_observed_for_demo(data)

    # episode boundaries: teleport/respawn discontinuities + a hard length cap.
    tele = set(pmove_sim.detect_teleports(frames))  # index k => break between k and k+1
    episodes = []
    seg_start = 0
    n = len(frames)
    for k in range(n):
        boundary = (k in tele) or (k - seg_start + 1 >= MAX_EPISODE_FRAMES) or (k == n - 1)
        if boundary:
            seg = frames[seg_start : k + 1]
            if len(seg) >= MIN_EPISODE_FRAMES:
                episodes.append(_pack_episode(seg, seg_start))
            seg_start = k + 1

    return {
        "ok": True,
        "demo": demo.name,
        "sha256": meta.get("source_sha256"),
        "map_level": meta.get("map_level"),
        "playernum": meta.get("playernum"),
        "n_frames": n,
        "coverage": meta.get("paired_coverage"),
        "duration_s": meta.get("total_duration_s"),
        "server_fps": meta.get("command_rate_fps"),
        "episodes": episodes,
        "observed": observed,
    }


def _decode_observed_for_demo(data: bytes) -> dict:
    """Decode observed-OTHER players and return a JSON-serializable per-player timeline
    (sorted by received time) so it crosses the ProcessPool boundary cleanly.

        {ok, self_playernum, n_playerinfo, bodies, bodies_clean, stop_reasons,
         others: {pnum_str: [[t_s, ox,oy,oz, vx,vy,vz, pitch,yaw,roll,
                              alive(0/1), onground(0/1), solid(0/1), pm_code], ...]}}
    """
    res = obs.decode_qwd_observed(data)
    if not res.get("ok"):
        return {"ok": False, "error": res.get("error"), "others": {}}
    others_packed = {}
    for pnum, rows in res["others_by_pnum"].items():
        rows_sorted = sorted(rows, key=lambda a: a.time_s)
        others_packed[str(pnum)] = [
            [round(a.time_s, 4),
             round(a.origin[0], 3), round(a.origin[1], 3), round(a.origin[2], 3),
             a.velocity[0], a.velocity[1], a.velocity[2],
             round(a.pitch, 4), round(a.yaw, 4), round(a.roll, 4),
             1 if a.alive else 0, 1 if a.onground else 0, 1 if a.solid else 0, a.pm_code]
            for a in rows_sorted
        ]
    return {
        "ok": True,
        "self_playernum": res["self_playernum"],
        "n_playerinfo": res["n_playerinfo"],
        "bodies": res["n_bodies"],
        "bodies_clean": res["bodies_clean"],
        "stop_reasons": res["stop_reasons"],
        "others": others_packed,
    }


def _pack_episode(seg, start_tick: int) -> dict:
    """Pack one contiguous frame run into compact per-tick rows (state + action)."""
    rows = []
    t_s = 0.0
    for i, f in enumerate(seg):
        o, v, a = f["origin"], f["velocity"], f["angles"]
        msec = int(f["msec"])
        rows.append({
            "tick": i,
            "t_s": round(t_s, 4),
            "abs_t_s": f.get("abs_t_s"),  # absolute QWD demo-time (for actor_ticks join)
            "msec": msec,
            "ox": o[0], "oy": o[1], "oz": o[2],
            "vx": v[0], "vy": v[1], "vz": v[2],
            "pitch": a[0], "yaw": a[1], "roll": a[2],
            "hspeed": round(_hspeed(v), 3),
            "onground": bool(f["onground"]),
            "pm_code": int(f["pm_code"]) if f.get("pm_code") is not None else None,
            "fwd": int(f["move"][0]), "side": int(f["move"][1]), "up": int(f["move"][2]),
            "buttons": int(f["buttons"]),
            "interp": bool(f.get("reference_interpolated")),
        })
        t_s += msec * 0.001
    return {"start": start_tick, "end": start_tick + len(seg) - 1, "n": len(seg), "frames": rows}


def insert_demo(con: sqlite3.Connection, map_id: int, rec: dict, split: str,
                player: str = "") -> dict:
    """Insert one extracted demo's demos/players/episodes/player_ticks/actions rows.
    `split` is the train/val/test label for ALL of this demo's episodes (group-by-demo).
    `player` is the parsed human handle from the demo-list (empty if the list had none).

    (A) The `demos` table has UNIQUE(sha256). The corpus DOES contain byte-identical .qwd
    files under different names; a plain INSERT of a second identical sha256 raises
    sqlite3.IntegrityError and crashes the whole batch. So we pre-check by sha256 and, if
    that content was already loaded this run, SKIP the demo entirely (insert NO
    demos/episodes/player_ticks/actions rows -> no orphan children) and report it."""
    dup = con.execute(
        "SELECT demo_id, path FROM demos WHERE sha256=?", (rec["sha256"],)
    ).fetchone()
    if dup is not None:
        # Already-loaded identical content. Return a sentinel and touch nothing else.
        return {"skipped_duplicate": True, "demo": rec["demo"],
                "sha256": rec["sha256"], "duplicate_of": dup[1], "duplicate_of_id": dup[0]}

    cur = con.execute(
        """INSERT INTO demos
           (path, source, map_id, demo_kind, duration_s, server_fps, sha256, parser_commit)
           VALUES (?,?,?,?,?,?,?,?)""",
        (rec["demo"], "qwd", map_id, "4on4",
         rec.get("duration_s"), rec.get("server_fps") or 77.0,
         rec["sha256"], "build_replay_frames:%s" % brc.SCHEMA),
    )
    demo_id = cur.lastrowid

    # POV player handle. (C) Prefer the parsed human handle from the demo-list so the same
    # human across multiple demos maps to ONE player_id (catalog consumers group/hold-out by
    # players.player_id). Match catalog_load.load_fixture's convention (lowercased name).
    # Fall back to the demo+slot key when the list carried no player (don't regress that case).
    player = (player or "").strip()
    if player:
        handle = player.lower()
    else:
        handle = "qwd:%s#p%s" % (Path(rec["demo"]).stem[:48], rec.get("playernum"))
    con.execute("INSERT OR IGNORE INTO players (handle, is_bot) VALUES (?,0)", (handle,))
    player_id = con.execute("SELECT player_id FROM players WHERE handle=?", (handle,)).fetchone()[0]

    # Register each OBSERVED-OTHER player as a players row and build a time-sorted
    # sample array per other (for the per-tick nearest-sample join). Keyed by demo+slot
    # like the POV handle, so the same person across demos stays distinct (no false
    # cross-demo identity — .qwd carries no name for others).
    obs_rec = rec.get("observed") or {}
    others = obs_rec.get("others") or {}
    other_pid: dict[int, int] = {}        # playernum -> players.player_id
    other_samples: dict[int, dict] = {}   # playernum -> {"t":[...], "rows":[...]}
    for pnum_str, rows in others.items():
        pnum = int(pnum_str)
        oh = "qwd:%s#o%s" % (Path(rec["demo"]).stem[:48], pnum)
        con.execute("INSERT OR IGNORE INTO players (handle, is_bot) VALUES (?,0)", (oh,))
        other_pid[pnum] = con.execute(
            "SELECT player_id FROM players WHERE handle=?", (oh,)).fetchone()[0]
        # rows already sorted by t_s in _decode_observed_for_demo; split the time key out
        # so a single bisect locates the most-recent sample at-or-before a tick time.
        other_samples[pnum] = {"t": [r[0] for r in rows], "rows": rows}

    n_ep = n_tick = n_act = n_actor = 0
    for ep in rec["episodes"]:
        c = con.execute(
            """INSERT INTO episodes
               (demo_id, player_id, map_id, start_tick, end_tick, n_steps, split, split_policy)
               VALUES (?,?,?,?,?,?,?,?)""",
            (demo_id, player_id, map_id, ep["start"], ep["end"], ep["n"], split, "group_by_demo_id"),
        )
        episode_id = c.lastrowid
        n_ep += 1
        for r in ep["frames"]:
            con.execute(
                """INSERT INTO player_ticks
                   (episode_id, tick, t_s, msec, ox, oy, oz, vx, vy, vz,
                    pitch, yaw, roll, hspeed, onground, onground_is_proxy, weapon)
                   VALUES (?,?,?,?, ?,?,?, ?,?,?, ?,?,?, ?,?,?, ?)""",
                (episode_id, r["tick"], r["t_s"], r["msec"],
                 r["ox"], r["oy"], r["oz"], r["vx"], r["vy"], r["vz"],
                 r["pitch"], r["yaw"], r["roll"], r["hspeed"],
                 r["onground"], False, None),
            )
            n_tick += 1
            con.execute(
                """INSERT INTO actions
                   (episode_id, tick, forwardmove, sidemove, upmove, buttons,
                    cmd_yaw, cmd_pitch, cmd_roll, label_source, confidence, is_interp)
                   VALUES (?,?,?,?,?,?, ?,?,?, ?,?,?)""",
                (episode_id, r["tick"], r["fwd"], r["side"], r["up"], r["buttons"],
                 r["yaw"], r["pitch"], r["roll"], "qwd_usercmd", 1.0, r["interp"]),
            )
            n_act += 1

            # actor_ticks (OMNISCIENT-from-POV world state). Self ego appears here too
            # (schema: "EVERY player"); its row reuses the already-validated self state.
            con.execute(
                """INSERT OR IGNORE INTO actor_ticks
                   (episode_id, tick, actor_id, team_id, alive, ox, oy, oz, vx, vy, vz,
                    pitch, yaw, roll, hspeed, onground, onground_is_proxy)
                   VALUES (?,?,?,?,?, ?,?,?, ?,?,?, ?,?,?, ?,?,?)""",
                (episode_id, r["tick"], player_id, None, True,
                 r["ox"], r["oy"], r["oz"], r["vx"], r["vy"], r["vz"],
                 r["pitch"], r["yaw"], r["roll"], r["hspeed"], r["onground"], False),
            )
            n_actor += 1

            # Each OTHER player the client was RECEIVING at (nearest-at-or-before) this
            # absolute tick time, within the staleness window. abs_t_s may be None for a
            # rare unmatched/interpolated self frame; skip the join there (others stay
            # absent that tick rather than being mis-timed).
            abs_t = r.get("abs_t_s")
            if abs_t is None:
                continue
            for pnum, samp in other_samples.items():
                row = _nearest_observed(samp, abs_t, OBSERVED_MAX_STALENESS_S)
                if row is None:
                    continue
                # row = [t, ox,oy,oz, vx,vy,vz, pitch,yaw,roll, alive, ong, solid, pm]
                vx, vy, vz = row[4], row[5], row[6]
                con.execute(
                    """INSERT OR IGNORE INTO actor_ticks
                       (episode_id, tick, actor_id, team_id, alive, ox, oy, oz, vx, vy, vz,
                        pitch, yaw, roll, hspeed, onground, onground_is_proxy)
                       VALUES (?,?,?,?,?, ?,?,?, ?,?,?, ?,?,?, ?,?,?)""",
                    (episode_id, r["tick"], other_pid[pnum], None, bool(row[10]),
                     row[1], row[2], row[3], vx, vy, vz,
                     row[7], row[8], row[9], round(math.hypot(vx, vy), 3),
                     bool(row[11]), False),
                )
                n_actor += 1
    return {"demo_id": demo_id, "player_id": player_id,
            "episodes": n_ep, "player_ticks": n_tick, "actions": n_act,
            "actor_ticks": n_actor, "observed_others": len(other_pid),
            "observed_ok": obs_rec.get("ok", False)}


def _nearest_observed(samp: dict, t: float, max_staleness_s: float):
    """Return the OTHER-player sample most recently received at-or-before time `t`
    (the state the client currently had for that player), or None if the latest such
    sample is staler than `max_staleness_s` (player not currently observed). Binary
    search over the per-player time array; falls back to the nearest forward sample
    only inside the window (covers a tick landing a hair before the first sample)."""
    times = samp["t"]
    if not times:
        return None
    i = bisect.bisect_right(times, t) - 1
    if i >= 0 and (t - times[i]) <= max_staleness_s:
        return samp["rows"][i]
    # tick just before this player's first/next sample — accept if within the window
    j = i + 1
    if j < len(times) and (times[j] - t) <= max_staleness_s:
        return samp["rows"][j]
    return None


def load_fixture_relational(con: sqlite3.Connection, fixture_dir: Path, map_id: int) -> dict:
    """Fold the dm3_milton_211436 fixture's TEAM-LAYER rows into the catalog so the
    relational tables that have real fixture data (teams/frag_events/item_events/
    region_control_timeline) are exercised. Reuses catalog_load.load_fixture for the
    demo/teams/players/frag identity, then adds item_events + region_control_timeline
    from the fixture samples (which load_fixture does not cover)."""
    summ = catalog_load.load_fixture(con, fixture_dir, map_id)
    demo_id = summ["demo_id"]
    pid = summ["player_ids"]            # name -> player_id
    tid = summ["team_ids"]              # name -> team_id

    # item_events: Milton's weapon pickups (world + backpack) from the sample slice.
    ie = json.loads((fixture_dir / "item_events.sample.json").read_text(encoding="utf-8"))
    n_ie = 0
    for p in ie.get("milton_weapon_pickups", []):
        kind = "backpack_pickup" if p.get("source") == "backpack" else "pickup"
        con.execute(
            """INSERT INTO item_events
               (demo_id, item_id, t_s, event_kind, player_id, item_type, team_id)
               VALUES (?,?,?,?,?,?,?)""",
            (demo_id, None, p["time"] / 1000.0, kind, pid.get("Milton"),
             p.get("weapon"), tid.get("Book")),
        )
        n_ie += 1
    for d in ie.get("backpack_drops_by_SS", []):
        o = d.get("origin") or [None, None, None]
        con.execute(
            """INSERT INTO item_events
               (demo_id, item_id, t_s, event_kind, player_id, origin_x, origin_y, origin_z,
                item_type, team_id)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (demo_id, None, d["time"] / 1000.0, "drop", pid.get("SS"),
             o[0], o[1], o[2], d.get("weapon"), tid.get("3b")),
        )
        n_ie += 1

    # region_control_timeline: per-bucket control fractions from the sample.
    rc = json.loads((fixture_dir / "region_control.sample.json").read_text(encoding="utf-8"))
    n_rc = _load_region_control(con, demo_id, rc)

    return {"fixture_demo_id": demo_id, "team_frags": summ["team_frags"],
            "n_frag_events": summ["n_frag_events"], "n_item_events": n_ie,
            "n_region_control": n_rc}


# bucketStates char -> (teamA_control, teamB_control, contested). Legend from the
# fixture sample's _bucket_legend. A=strong A, a=weak A, B=strong B, b=weak B,
# c/C=contested, _=empty. We encode strong=1.0, weak=0.4, contested=0.5 each side.
_BUCKET_CHAR = {
    "A": (1.0, 0.0, False), "a": (0.4, 0.0, False),
    "B": (0.0, 1.0, False), "b": (0.0, 0.4, False),
    "c": (0.5, 0.5, True),  "C": (0.3, 0.3, True),
    "_": (0.0, 0.0, False),
}
_BUCKET_SECONDS = 5.0  # getRegionControl windowMs=5000 (one char per 5 s bucket)


def _load_region_control(con: sqlite3.Connection, demo_id: int, rc: dict) -> int:
    """Decode the fixture's region_control sample into region_control_timeline rows.

    Canonical shape (the fixture): {regions:[{name, bucketStates:"<chars>"}]} where each
    char is one 5 s control bucket (legend in the sample). We also tolerate a couple of
    list-of-dict shapes (timeline / buckets) for forward-compat with other extractions."""
    n = 0
    regions = rc.get("regions") or rc.get("region_control")
    if isinstance(regions, list):
        for reg in regions:
            if not isinstance(reg, dict):
                continue
            name = reg.get("name") or reg.get("region_name") or "?"
            states = reg.get("bucketStates")
            if isinstance(states, str):
                for i, ch in enumerate(states):
                    a, b, contested = _BUCKET_CHAR.get(ch, (None, None, None))
                    n += _insert_region_bucket(
                        con, demo_id, name,
                        {"bucket_idx": i, "t_s": round(i * _BUCKET_SECONDS, 3),
                         "teamA": a, "teamB": b, "contested": contested})
            for b in (reg.get("timeline") or []):
                n += _insert_region_bucket(con, demo_id, name, b)
    elif isinstance(regions, dict):
        for name, body in regions.items():
            for b in ((body or {}).get("timeline") or []):
                n += _insert_region_bucket(con, demo_id, name, b)
    for b in rc.get("buckets", []) or []:
        n += _insert_region_bucket(con, demo_id, b.get("region") or b.get("region_name") or "?", b)
    return n


def _insert_region_bucket(con: sqlite3.Connection, demo_id: int, name, b) -> int:
    if not isinstance(b, dict):
        return 0
    a = b.get("teamA", b.get("A", b.get("teamA_control")))
    bb = b.get("teamB", b.get("B", b.get("teamB_control")))
    t_s = b.get("t_s", b.get("time_ms", b.get("time")))
    if t_s is not None and t_s > 10000:  # looks like ms
        t_s = t_s / 1000.0
    idx = b.get("bucket_idx", b.get("bucket"))
    if idx is None:
        idx = con.execute(
            "SELECT COUNT(*) FROM region_control_timeline WHERE demo_id=? AND region_name=?",
            (demo_id, str(name)),
        ).fetchone()[0]
    try:
        con.execute(
            """INSERT OR IGNORE INTO region_control_timeline
               (demo_id, bucket_idx, t_s, region_name, teamA_control, teamB_control, contested)
               VALUES (?,?,?,?,?,?,?)""",
            (demo_id, int(idx), t_s, str(name), a, bb, b.get("contested")),
        )
        return 1
    except (sqlite3.IntegrityError, ValueError, TypeError):
        return 0


def load_demo_list(list_file: Path):
    """Each line: <player>\t<abspath.qwd>  (player optional, tab-separated)."""
    out = []
    for ln in list_file.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        parts = ln.split("\t")
        out.append((parts[0].strip() if len(parts) > 1 else "", parts[-1].strip()))
    return out


def assign_splits(n_demos: int, ratios=(0.7, 0.15, 0.15)) -> list[str]:
    """Deterministic group-by-demo split: round-robin demos into train/val/test by a
    cumulative-ratio schedule. Guarantees no demo straddles a split (a demo gets exactly
    one label) and that every present split has >=1 demo when n_demos allows."""
    labels = []
    train_n = max(1, round(n_demos * ratios[0]))
    val_n = max(1, round(n_demos * ratios[1])) if n_demos >= 3 else 0
    for i in range(n_demos):
        if i < train_n:
            labels.append("train")
        elif i < train_n + val_n:
            labels.append("val")
        else:
            labels.append("test")
    return labels


def build(catalog_dir: Path, demo_list: Path, db_path: str,
          with_fixture: Path | None = None, workers: int = 2, limit: int = 0) -> dict:
    """Build a fresh populated catalog: static spine + per-tick rows from real demos
    (+ optional fixture team-layer rows). Returns a summary dict."""
    demos = load_demo_list(demo_list)
    if limit:
        demos = demos[:limit]
    paths = [p for _, p in demos]
    player_by_path = {p: pl for pl, p in demos}

    # static spine first (maps/items/markers/nav) via the existing loader.
    con, base = catalog_load.build(catalog_dir, fixture_dir=None, db_path=db_path)
    map_id = con.execute("SELECT map_id FROM maps WHERE name='dm3'").fetchone()[0]

    # extract demos in parallel (CPU-bound .qwd parse), insert serially (sqlite writer).
    t0 = time.time()
    extracted = []
    errors = []
    print("ETL: extracting %d demos with %d workers ..." % (len(paths), workers), flush=True)
    if workers > 1 and len(paths) > 1:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(extract_demo, p): p for p in paths}
            for fut in as_completed(futs):
                r = fut.result()
                (extracted if r.get("ok") else errors).append(r)
                done = len(extracted) + len(errors)
                print("  %d/%d  %s  (%s)" % (
                    done, len(paths), r.get("demo"),
                    ("%d frames" % r.get("n_frames", 0)) if r.get("ok") else "ERR: " + r.get("error", "")),
                    flush=True)
    else:
        for p in paths:
            r = extract_demo(p)
            (extracted if r.get("ok") else errors).append(r)

    # deterministic order (by filename) so splits + ids are reproducible.
    extracted.sort(key=lambda r: r["demo"])
    splits = assign_splits(len(extracted))

    # map each extracted demo name back to the path the demo-list gave (for the parsed
    # human handle); first match wins (same filename -> same intended player handle).
    path_by_name = {}
    for p in paths:
        path_by_name.setdefault(Path(p).name, p)

    per_demo = []
    skipped_dups = []
    for rec, split in zip(extracted, splits):
        src_path = path_by_name.get(rec["demo"], "")
        player = player_by_path.get(src_path, "")
        ins = insert_demo(con, map_id, rec, split, player=player)
        if ins.get("skipped_duplicate"):
            # (A) byte-identical content already loaded this run: recorded, not inserted.
            ins.update(player=player, n_frames=rec.get("n_frames"))
            skipped_dups.append(ins)
            print("  SKIP duplicate sha256: %s (== %s)" % (
                rec["demo"], ins.get("duplicate_of")), flush=True)
            continue
        ins.update(demo=rec["demo"], player=player,
                   split=split, coverage=rec.get("coverage"), n_frames=rec.get("n_frames"))
        per_demo.append(ins)

    fixture_summary = None
    if with_fixture is not None:
        fixture_summary = load_fixture_relational(con, with_fixture, map_id)

    con.commit()
    counts = table_counts(con)
    summary = {
        "db": db_path,
        "catalog_dir": str(catalog_dir),
        "static_spine": base,
        "demos_attempted": len(paths),
        # (A) only demos that actually produced rows count as loaded; byte-identical
        # duplicates are skipped (no rows) and reported separately, not counted here.
        "demos_loaded": len(per_demo),
        "demos_failed": len(errors),
        "demos_skipped_duplicate": len(skipped_dups),
        "extract_secs": round(time.time() - t0, 1),
        "split_counts": _split_counts(per_demo),
        "table_counts": counts,
        "observed_others": _observed_summary(con, per_demo),
        "per_demo": per_demo,
        "skipped_duplicate_demos": skipped_dups,
        "fixture": fixture_summary,
        "errors": [{"demo": e["demo"], "error": e["error"]} for e in errors],
    }
    return {"con": con, "summary": summary}


def _observed_summary(con: sqlite3.Connection, per_demo) -> dict:
    """Aggregate the agent_observation layer: actor_ticks rows, demos that yielded
    observed-others, and the observed-OTHERS-per-tick distribution (how many other
    actors are present at a tick — i.e. how rich the masked POMDP view is)."""
    demos_with_obs = sum(1 for d in per_demo if d.get("observed_others"))
    total_others = sum(d.get("observed_others", 0) for d in per_demo)
    # others-per-tick = actor_ticks rows per (episode_id,tick) minus the 1 self ego row.
    dist: dict[int, int] = {}
    try:
        dist_rows = con.execute(
            "SELECT others, COUNT(*) FROM ("
            "  SELECT episode_id, tick, COUNT(*)-1 AS others FROM actor_ticks"
            "  GROUP BY episode_id, tick) GROUP BY others ORDER BY others"
        ).fetchall()
        dist = {int(o): int(n) for o, n in dist_rows}
    except sqlite3.OperationalError:
        dist = {}
    return {
        "demos_with_observed_others": demos_with_obs,
        "distinct_other_actors_total": total_others,
        "actor_ticks_rows": con.execute("SELECT COUNT(*) FROM actor_ticks").fetchone()[0],
        "observed_others_per_tick_distribution": dist,
    }


def _split_counts(per_demo) -> dict:
    out = {"train": 0, "val": 0, "test": 0}
    for d in per_demo:
        out[d["split"]] = out.get(d["split"], 0) + 1
    return out


TABLES = ["maps", "items", "markers", "nav_edges", "players", "demos", "teams",
          "episodes", "player_ticks", "actions", "actor_ticks", "item_events",
          "frag_events", "region_control_timeline"]


def table_counts(con: sqlite3.Connection) -> dict:
    out = {}
    for t in TABLES:
        try:
            out[t] = con.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
        except sqlite3.OperationalError:
            out[t] = None
    return out


def main(argv=None) -> int:
    sys.setrecursionlimit(20000)
    ap = argparse.ArgumentParser(description="Populate the relational catalog from real .qwd demos")
    ap.add_argument("--catalog-dir", type=Path, required=True)
    ap.add_argument("--demo-list", type=Path, required=True,
                    help="TSV: player<TAB>abspath.qwd, one self-POV dm3 4on4 demo/line")
    ap.add_argument("--db", required=True, help="output .sqlite path")
    ap.add_argument("--with-fixture", type=Path, default=None,
                    help="optional dm3_milton_211436 fixture dir to fold team-layer rows")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--allow-empty", action="store_true",
                    help="exit 0 even when NO requested .qwd demos loaded (static-only "
                         "catalog). Default: a zero-demo load is an error (non-zero exit) so "
                         "automation that keys off exit status can't accept an empty catalog.")
    args = ap.parse_args(argv)

    # fresh DB each run (the schema CREATEs are not IF NOT EXISTS).
    dbp = Path(args.db)
    if dbp.exists():
        dbp.unlink()
    dbp.parent.mkdir(parents=True, exist_ok=True)

    res = build(args.catalog_dir, args.demo_list, args.db,
                with_fixture=args.with_fixture, workers=args.workers, limit=args.limit)
    print(json.dumps(res["summary"], indent=2, default=str))

    # (B) A catalog with zero loaded .qwd demos has no real episodes/player_ticks/actions
    # (only the static spine + optional fixture). Returning 0 here lets automation that
    # keys off exit status silently accept that empty catalog. Fail unless --allow-empty.
    if res["summary"]["demos_loaded"] == 0 and not args.allow_empty:
        print("ERROR: no .qwd demos loaded (0 episodes/player_ticks/actions from real "
              "demos); failing. Pass --allow-empty to accept a static-only catalog.",
              file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
