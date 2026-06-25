"""assemble_obs_template.py — the WORKED training-connection template (T9 #397, capstone).

A runnable, **stdlib-only** consumer that assembles an observation transition `(s, s')`
from the now-populated catalog (T3-T8 fields), honoring the two highest-risk leakage
properties of the data contract:

  1. **PIT / as-of leakage guard (00-DATA-ARCHITECTURE §7, spec §6).** Every value an obs
     at tick T reads is timestamped `<= T`. The catalog-side joins here are EITHER
     equal-tick (player_ticks / actor_ticks PK is (episode_id, tick) — an exact-tick read,
     never tick+1) OR a point-in-time **as-of** join over an event timeline
     (`item_events`): the value attached at tick T is the LATEST event at-or-before T's
     server clock. The as-of is implemented in stdlib (`asof_latest_leq` — bisect over a
     time-sorted event list, `t_event <= t_obs`), so it needs no DuckDB `ASOF JOIN`. A
     naive "nearest" or "next" join would leak a future pickup into the obs; the T9 test
     constructs exactly that adversarial fixture and asserts this code does NOT leak.

  2. **Clean-movement gating of the AMP reference set (spec §6.5, T8 #396).** The AMP
     `(s, s')` human-prior reference set must be drawn from CLEAN-MOVEMENT segments only
     (no enemy-with-LOS within THREAT_R; provably-zero damage). This template gates each
     transition through `scripts.catalog_etl_mvd.tick_is_clean` — the SAME predicate the
     ETL uses — and is FAIL-CLOSED on era-gated-unknown damage (a demo whose
     `demos.damage_available` is not TRUE can never certify a tick clean). So the reference
     set the template emits is technique, not evasion.

This is a TEMPLATE: small, documented, runnable on a fixture catalog (the T9 test builds
one in-memory). It REUSES the shared feature math — `scripts/features/agent_observation`
(the SELF + entity encoder the live bot and ml/pipeline/build_features both call) — so the
obs vector is the SAME contract (feature_registry v5 order); it does NOT reinvent the
feature order. The heavy windowed Parquet build is ml/pipeline/build_features.py (DuckDB/
pyarrow); THIS module is the dependency-light worked example a new consumer copies to learn
the connection + the leakage discipline.

Run:  python3 ml/pipeline/assemble_obs_template.py --db catalog.sqlite --split train
"""
from __future__ import annotations

import argparse
import bisect
import json
import logging
import sqlite3
import sys
from pathlib import Path


LOGGER = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from features import agent_observation as AO   # noqa: E402  (SHARED obs encoder, stdlib)
# §6.5 clean predicate + its THREAT_R default — imported from the SAME module the ETL uses
# (no local re-implementation, no local re-default), so the template gates EXACTLY as the ETL.
from catalog_etl_mvd import (                    # noqa: E402
    tick_is_clean,
    CLEAN_THREAT_R_QU as AO_CLEAN_THREAT_R,
)

FRAME_DT_MS = 13.0   # fallback per-tick frame time (mirrors build_features.FRAME_DT_MS)


# =============================================================================
# The point-in-time / as-of join primitive (the leakage guard, in stdlib).
# =============================================================================
def asof_latest_leq(events: list[tuple], t_obs: float):
    """Return the LATEST event at-or-before t_obs, or None.

    `events` is a list of (t_event, payload) tuples; it is sorted by t_event here so the
    caller may pass it unsorted. The returned event satisfies `t_event <= t_obs` and is the
    maximal such — i.e. an as-of (point-in-time) join keyed on t_obs. This is the leakage
    guard: NO event with `t_event > t_obs` can ever be returned, so an obs at tick T can
    never read a value timestamped after T. (A naive implementation that returned the
    NEAREST event, or the next event >= t_obs, WOULD leak the future — the T9 leakage test
    builds that adversarial fixture and asserts this function refuses it.)"""
    if not events:
        return None
    ev = sorted(events, key=lambda e: e[0])
    times = [e[0] for e in ev]
    # bisect_right finds the first index with time > t_obs; everything left is <= t_obs.
    idx = bisect.bisect_right(times, t_obs) - 1
    if idx < 0:
        return None
    return ev[idx]


# =============================================================================
# Catalog read (stdlib sqlite3) — the populated T3-T8 slice the obs needs.
# =============================================================================
def _load_split_ticks(con: sqlite3.Connection, split: str):
    """Return per-episode tick-ordered rows for the split, plus the per-demo item-event
    timeline (for the as-of join) and the per-demo damage_available flag (for §6.5).

    The ego self spine is player_ticks (T3 health/armor + T6 ammo/powerup-remaining + T7
    geometry/regime); the omniscient others are actor_ticks (T4 world + T7 geometry); the
    POMDP gate is actor_visibility (T8 FOV/LOS+belief). Every read is keyed on the EXACT
    tick (PK (episode_id, tick)) — an equal-tick join, never tick+1 — so the per-tick state
    is PIT-safe by construction. The item-event timeline is read whole per demo and the
    as-of join is applied per obs-tick below."""
    con.row_factory = sqlite3.Row
    self_rows = con.execute(
        """
        SELECT e.episode_id, e.demo_id, e.player_id, e.map_id,
               pt.tick, pt.t_s, pt.msec,
               pt.ox, pt.oy, pt.oz, pt.vx, pt.vy, pt.vz,
               pt.yaw, pt.pitch, pt.hspeed, pt.onground,
               pt.health, pt.armor,
               pt.shells, pt.nails, pt.rockets, pt.cells,
               pt.quad_rem, pt.pent_rem, pt.ring_rem,
               pt.regime, pt.leg_phase
          FROM player_ticks pt
          JOIN episodes e USING(episode_id)
         WHERE e.split = ?
         ORDER BY e.episode_id, pt.tick
        """,
        (split,),
    ).fetchall()

    # all actor rows (self + observed-others) per (episode, tick) — equal-tick read.
    actor_rows = con.execute(
        """
        SELECT a.episode_id, a.tick, a.actor_id, e.player_id,
               a.ox, a.oy, a.oz, a.vx, a.vy, a.vz, a.yaw, a.alive, a.team_id
          FROM actor_ticks a
          JOIN episodes e USING(episode_id)
         WHERE e.split = ?
         ORDER BY a.episode_id, a.tick
        """,
        (split,),
    ).fetchall()

    # T8 POMDP visibility, per (episode, tick, observer, target) — equal-tick read. Used to
    # feed the §6.5 clean predicate the distances of enemies that ALSO have LOS this tick.
    vis_rows = con.execute(
        """
        SELECT v.episode_id, v.tick, v.observer_id, v.target_id, v.is_visible
          FROM actor_visibility v
          JOIN episodes e USING(episode_id)
         WHERE e.split = ?
        """,
        (split,),
    ).fetchall()

    # per-demo item-event timeline (for the as-of join). Whole-demo read; the PIT cut is
    # applied per obs-tick by asof_latest_leq, NOT in SQL — so the join is auditable here.
    item_rows = con.execute(
        "SELECT demo_id, t_s, event_kind, item_type FROM item_events ORDER BY demo_id, t_s"
    ).fetchall()
    item_timeline: dict[int, list[tuple]] = {}
    for r in item_rows:
        item_timeline.setdefault(r["demo_id"], []).append(
            (float(r["t_s"]), {"event_kind": r["event_kind"], "item_type": r["item_type"]}))

    # per-demo era gate (§6.5 fail-closed): TRUE only if the damage block was present.
    # SQLite stores BOOLEAN as 0/1/NULL; coerce to the Python True/False/None tick_is_clean's
    # strict `is not True` identity check expects (a raw int 1 would WRONGLY fail-close).
    dmg = {}
    for r in con.execute("SELECT demo_id, damage_available FROM demos"):
        raw = r["damage_available"]
        dmg[r["demo_id"]] = None if raw is None else bool(raw)

    return self_rows, actor_rows, vis_rows, item_timeline, dmg


def _index_others(actor_rows):
    """{(episode,tick): [other_state...]} + {(episode,tick): self_team_id}."""
    others: dict[tuple, list] = {}
    self_team: dict[tuple, int] = {}
    for r in actor_rows:
        key = (r["episode_id"], r["tick"])
        if r["actor_id"] == r["player_id"]:
            self_team[key] = r["team_id"]
            continue
        others.setdefault(key, []).append({
            "actor_id": r["actor_id"], "ox": r["ox"], "oy": r["oy"], "oz": r["oz"],
            "vx": r["vx"], "vy": r["vy"], "vz": r["vz"], "yaw": r["yaw"],
            "alive": bool(r["alive"]) if r["alive"] is not None else True,
            "team_id": r["team_id"],
        })
    return others, self_team


def _index_visible_enemy_targets(vis_rows):
    """{(episode,tick,observer): set(target_id with LOS)} — the §6.5 'enemy with LOS' set."""
    vis: dict[tuple, set] = {}
    for r in vis_rows:
        if r["is_visible"]:
            vis.setdefault((r["episode_id"], r["tick"], r["observer_id"]), set()).add(r["target_id"])
    return vis


# =============================================================================
# The worked assembly: per (episode, tick) build the SELF+entity obs, gate the
# (s, s') transition through the §6.5 clean predicate, attach the as-of item context.
# =============================================================================
def assemble_amp_reference(con: sqlite3.Connection, norm: dict, split: str = "train",
                           map_name: str = "dm3", threat_r: float = None) -> dict:
    """Assemble the AMP `(s, s')` reference set from CLEAN-MOVEMENT segments of `split`.

    Returns {"transitions": [...], "stats": {...}}. Each transition is
    {episode_id, tick, s, s_next, last_item_event} where:
      - s / s_next are the SHARED agent_observation SELF+entity-encoded obs (feature_registry
        v5 order) at tick T and T+1 (same episode, consecutive ticks),
      - last_item_event is the AS-OF item context (latest item_event at-or-before T's t_s),
      - the pair is emitted ONLY if BOTH ticks pass tick_is_clean (§6.5, fail-closed).

    The fail-closed era gate, the LOS-gated enemy proximity, and the as-of cut are the three
    leakage/cleanliness properties the T9 tests probe."""
    threat_r = AO_CLEAN_THREAT_R if threat_r is None else threat_r
    self_rows, actor_rows, vis_rows, item_timeline, dmg = _load_split_ticks(con, split)
    others, self_team = _index_others(actor_rows)
    visible = _index_visible_enemy_targets(vis_rows)

    # group the ego spine by episode, tick-ordered, carrying everything an obs needs.
    episodes: dict[int, list] = {}
    ep_demo: dict[int, int] = {}
    prev_yaw_by_ep: dict[int, float] = {}
    for r in self_rows:
        eid = r["episode_id"]
        ep_demo[eid] = r["demo_id"]
        key = (eid, r["tick"])
        prev_yaw = prev_yaw_by_ep.get(eid)
        dt_s = (float(r["msec"]) if r["msec"] else FRAME_DT_MS) / 1000.0
        yaw = r["yaw"]
        yaw_rate = AO.yaw_rate_degps(yaw, prev_yaw, dt_s) if yaw is not None else 0.0
        if yaw is not None:
            prev_yaw_by_ep[eid] = float(yaw)
        self_state = {
            "ox": r["ox"], "oy": r["oy"], "oz": r["oz"],
            "vx": r["vx"], "vy": r["vy"], "vz": r["vz"],
            "yaw": yaw, "pitch": r["pitch"], "hspeed": r["hspeed"],
            "onground": bool(r["onground"]) if r["onground"] is not None else False,
            "health": r["health"], "armor": r["armor"],
            "yaw_rate": yaw_rate, "team_id": self_team.get(key),
        }
        episodes.setdefault(eid, []).append({
            "tick": r["tick"], "t_s": float(r["t_s"]), "self": self_state,
            "others": others.get(key, []),
            "observer_id": r["player_id"], "demo_id": r["demo_id"],
        })

    transitions = []
    n_pairs = 0
    n_clean = 0
    n_excluded_unknown_dmg = 0
    n_excluded_combat = 0
    for eid in sorted(episodes):
        ticks = episodes[eid]
        demo_id = ep_demo[eid]
        damage_available = dmg.get(demo_id)
        timeline = item_timeline.get(demo_id, [])
        for i in range(len(ticks) - 1):
            t0, t1 = ticks[i], ticks[i + 1]
            if t1["tick"] != t0["tick"] + 1:
                continue   # not consecutive (episode-continuity gap) -> not an (s,s') pair
            n_pairs += 1
            c0, why0 = _clean(t0, eid, visible, damage_available, threat_r)
            c1, _ = _clean(t1, eid, visible, damage_available, threat_r)
            if not (c0 and c1):
                if why0 == "damage_unknown_fail_closed":
                    n_excluded_unknown_dmg += 1
                else:
                    n_excluded_combat += 1
                continue
            n_clean += 1
            s = AO.encode_observation(t0["self"], t0["others"], norm, map_name, AO.N_MAX_DEFAULT)
            s_next = AO.encode_observation(t1["self"], t1["others"], norm, map_name, AO.N_MAX_DEFAULT)
            # AS-OF item context at the OBS tick (latest pickup/respawn at-or-before t0.t_s).
            asof = asof_latest_leq(timeline, t0["t_s"])
            transitions.append({
                "episode_id": eid, "tick": t0["tick"],
                "s": s["self"], "s_next": s_next["self"],
                "last_item_event": (asof[1] if asof else None),
                "last_item_event_t": (asof[0] if asof else None),
            })

    return {
        "transitions": transitions,
        "stats": {
            "split": split, "map": map_name, "threat_r": threat_r,
            "consecutive_pairs": n_pairs,
            "clean_transitions": n_clean,
            "excluded_combat": n_excluded_combat,
            "excluded_unknown_damage_fail_closed": n_excluded_unknown_dmg,
            "self_dim": AO.SELF_DIM,
            "clean_frac": round(n_clean / n_pairs, 4) if n_pairs else 0.0,
        },
    }


def _clean(tick_obj, eid, visible, damage_available, threat_r):
    """Run the SHARED §6.5 tick_is_clean predicate for one tick.

    Feeds it (a) the distances of enemy actors that ALSO have line-of-sight to the ego this
    tick (from the T8 actor_visibility index — an enemy behind a wall is NOT active combat),
    and (b) the per-demo damage_available era flag (fail-closed: not-TRUE => unknown =>
    NOT clean, BEFORE any event check). Returns (is_clean, reason)."""
    self_state = tick_obj["self"]
    self_team = self_state.get("team_id")
    observer = tick_obj["observer_id"]
    los_set = visible.get((eid, tick_obj["tick"], observer), set())
    # distances of LOS-having enemies (different team) to the ego this tick.
    enemy_los_dists = []
    sx, sy, sz = self_state["ox"], self_state["oy"], self_state["oz"]
    for o in tick_obj["others"]:
        if self_team is not None and o["team_id"] == self_team:
            continue   # teammate, not a threat
        if o["actor_id"] not in los_set:
            continue   # no line-of-sight -> not active combat (T8 gate)
        dx, dy, dz = o["ox"] - sx, o["oy"] - sy, o["oz"] - sz
        enemy_los_dists.append((dx * dx + dy * dy + dz * dz) ** 0.5)
    return tick_is_clean(
        t_s=tick_obj["t_s"],
        threat_distances_with_los=enemy_los_dists,
        damage_available=damage_available,
        damage_event_times_s=[],   # template: no per-hit damage rows joined here
        threat_r=threat_r,
    )


def load_norm(stats_path: Path) -> dict:
    return json.loads(Path(stats_path).read_text(encoding="utf-8"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Worked AMP (s,s') obs-assembly template from a catalog")
    ap.add_argument("--db", type=Path, required=True, help="catalog .sqlite")
    ap.add_argument("--stats", type=Path,
                    default=REPO_ROOT / "data" / "catalog" / "normalization_stats.template.json")
    ap.add_argument("--split", default="train")
    ap.add_argument("--map", default="dm3")
    ap.add_argument("--limit", type=int, default=5, help="print this many transitions")
    args = ap.parse_args(argv)

    norm = load_norm(args.stats)
    con = sqlite3.connect(str(args.db))
    try:
        out = assemble_amp_reference(con, norm, split=args.split, map_name=args.map)
    finally:
        con.close()
    print(json.dumps({"stats": out["stats"],
                      "sample_transitions": out["transitions"][: args.limit]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
