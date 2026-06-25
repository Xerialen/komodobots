#!/usr/bin/env python3
"""Extraction-coverage audit (Demo Extraction Spec v1, docs/27 §3.9/§7) — keystone.

Enumerate the **decoder Result inventory** (what the demos can yield) and diff it against
what the catalog SCHEMA defines, what the feature REGISTRY references, and what each ETL
actually POPULATES — then classify every catalog column as one of:

    extracted              — an ETL writes it from a decoder field today
    derived                — computed from extracted columns (not a raw decoder field)
    excluded-with-reason   — a decoder field deliberately NOT carried (reason recorded)
    GAP                     — promised by the spec/registry but neither extracted nor derived

This is the §7 validation gate and the map that scopes T2–T9. It is **read-only**: it loads
NO database, hits NO network, runs NO heavy compute. It parses only in-repo text artifacts:

  * scripts/catalog_schema.sql            — the OPERATIVE schema (catalog_load.py loads it)
  * data/catalog/feature_registry.yaml    — registry_version 5 feature `source:` references
  * scripts/catalog_etl_mvd.py            — INSERT column lists actually populated (MVD)
  * scripts/catalog_etl_qwd.py            — INSERT column lists actually populated (QWD)
  * tools/qwd_usercmd/qwd_usercmd.py       — the QWD usercmd struct (ground-truth action oracle)

The **decoder Result inventory** itself is a curated, sourced manifest (DECODER_INVENTORY
below) anchored in the committed static reference docs/ml-data-architecture/_source-schemas.md
(mvd_analyzer result/*.go study) + the qw-analyze schema-33 `-include` groups + getStateAt
field codes. It is data, not code, so it is forward-compatible: as the analyzers evolve, edit
the manifest, not the diff logic. mvd_analyzer-src is NOT imported (it is a sibling repo, not a
runtime dependency of komodobots).

Regenerate the committed report:

    python3 scripts/audit_extraction_coverage.py            # writes the report
    python3 scripts/audit_extraction_coverage.py --check     # run self-checks, write nothing
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
from collections import OrderedDict
from pathlib import Path

LOGGER = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_SQL = REPO_ROOT / "scripts" / "catalog_schema.sql"
REGISTRY_YAML = REPO_ROOT / "data" / "catalog" / "feature_registry.yaml"
ETL_MVD = REPO_ROOT / "scripts" / "catalog_etl_mvd.py"
ETL_QWD = REPO_ROOT / "scripts" / "catalog_etl_qwd.py"
QWD_USERCMD = REPO_ROOT / "tools" / "qwd_usercmd" / "qwd_usercmd.py"
SOURCE_SCHEMAS_DOC = "docs/ml-data-architecture/_source-schemas.md"
REPORT = REPO_ROOT / "docs" / "ml-data-architecture" / "extraction-coverage-audit.md"

# Classification labels.
EXTRACTED = "extracted"
DERIVED = "derived"
EXCLUDED = "excluded-with-reason"
GAP = "GAP"

# -----------------------------------------------------------------------------
# DECODER RESULT INVENTORY (the master list — what the demos can yield).
#
# Sourced from the committed static reference docs/ml-data-architecture/_source-schemas.md
# (mvd_analyzer result/*.go study) + qw-analyze schema-33 `-include` groups (cmd/qw-analyze
# /main.go: positions,view,height,liquid,velocity) + getStateAt field codes + the QWD
# usercmd_t struct (tools/qwd_usercmd). Keyed by decoder ROLE (not tool name, per the spec).
#
# Each entry: id -> (origin, availability, note). origin = the decoder endpoint/stream.
# This is forward-compatible DATA: extend it as the analyzers grow; the diff logic is fixed.
# -----------------------------------------------------------------------------
DECODER_INVENTORY: "OrderedDict[str, tuple[str, str, str]]" = OrderedDict([
    # --- MVD omniscient server state (qw-analyze schema-33 -include + getStateAt) ---
    ("mvd.pos.xyz", ("qw-analyze -include positions (native ~77fps track)", "MVD+QWD", "origin qu")),
    ("mvd.pos.loc", ("qw-analyze -include positions (loc index)", "MVD", "nearest named loc")),
    ("mvd.view.pitchyaw", ("qw-analyze -include view (angle16 vya/vp)", "MVD+QWD", "view angles deg; lossless")),
    ("mvd.velocity.xyz", ("qw-analyze -include velocity (finite-differenced)", "MVD+QWD", "qu/s; analyzer-derived")),
    ("mvd.height.floor", ("qw-analyze -include height", "MVD", "height above floor; NOT requested by ETL")),
    ("mvd.liquid.waterlevel", ("qw-analyze -include liquid", "MVD", "waterlevel proxy; NOT requested by ETL")),
    ("state.health", ("getStateAt h (int16)", "MVD", "HP; state-only stream")),
    ("state.armor", ("getStateAt a (int16)", "MVD", "AP")),
    ("state.armor_type", ("getStateAt at ('ga'/'ya'/'ra'/'')", "MVD", "armor type")),
    ("state.weapon_held", ("getStateAt rl/lg/gl/ssg/sng (bools)", "MVD", "held-weapon intervals; no single active-weapon int")),
    ("state.ammo", ("getStateAt sh/nl/rk/cl (int16)", "MVD", "shells/nails/rockets/cells")),
    ("state.powerups", ("getStateAt q/pe/r (bools)", "MVD", "quad/pent/ring held")),
    ("state.spawn_death", ("getStateAt sp/d (bools)", "MVD", "spawn/death event bools")),
    # --- MVD omniscient: ALL players (the world) ---
    ("world.all_players_state", ("getStateAt (every player) / getBuckets", "MVD", "omniscient per-player state -> actor_ticks")),
    ("world.roster_teams", ("getOverview teams/players roster", "MVD", "team membership + frags")),
    # --- MVD item world ---
    ("items.world_coords", ("getMapEntities / getItems x,y,z (float32 qu)", "MVD", "static item spawn coords + classname + spawnflags")),
    ("items.pickup_respawn", ("getItems phases[] (takenAt/respawnAt/takenBy)", "MVD", "pickup + observed respawn timeline")),
    ("items.weapon_pickups", ("getWeaponPickups (world+backpack acquisitions)", "MVD", "slot-weapon pickups + effectiveness")),
    ("items.backpack_drops", ("getBackpacks (origin qu, entNum join key)", "MVD", "RL/LG drop world position (KTX)")),
    # --- MVD combat / events ---
    ("frags.kill_timeline", ("getFrags (time,killer,victim,weapon,isSuicide,isTeamKill)", "MVD", "kill timeline")),
    ("events.life", ("getEvents frag/powerup/streak/spawn/death/weapon/item/chat", "MVD", "authoritative spawn/death log")),
    ("damage.per_hit", ("`-view full` damage.events (attacker,victim,weapon,damage,isSplash/isEnv/isSelf/isTeam)", "MVD (KTX ~2024+)", "per-hit KTX damage; mvdhidden_dmgdone. POPULATED -> damage_events (T5), ERA-GATED via demos.damage_available")),
    # --- MVD spatial / region ---
    ("region.control_timeline", ("getRegionControl bucketStates/stats", "MVD", "bucketed map-region control")),
    ("audio.weapon_item_cues", ("getEvents weapon/item (sound sources)", "MVD", "weapon-fire/item-pickup audio cue sources")),
    ("locgraph.movement", ("getLocGraph / getLocTrails", "MVD", "data-derived loc movement graph (NOT a Frogbot nav mesh)")),
    ("metadata.ruleset", ("getMetadata serverInfo/matchSettings", "MVD", "ruleset: spawnmodel/powerups/noItems")),
    ("demoinfo.scoreboard", ("getDemoInfo (KTX scoreboard, Bot skill)", "MVD (KTX)", "per-player stats; is_bot flag")),
    ("provenance.sha", ("loadDemo sha256 + map + duration", "MVD+QWD", "demo provenance")),
    # --- derivation inputs (NOT a decoder stream — the sha-locked dm3.bsp via pmove_sim traces) ---
    ("geom.dm3_bsp", ("pmove_sim hull-1 traces over the sha-locked dm3.bsp (NOT a decoder field)", "derived", "[G] wall/floor/ledge/ramp from BSP collision geometry (T7)")),
    # --- QWD first-person POV usercmd (the action oracle; tools/qwd_usercmd) ---
    ("qwd.usercmd.forwardmove", ("QWD usercmd_t.forwardmove", "QWD", "ground-truth forward input")),
    ("qwd.usercmd.sidemove", ("QWD usercmd_t.sidemove", "QWD", "ground-truth side input")),
    ("qwd.usercmd.upmove", ("QWD usercmd_t.upmove", "QWD", "ground-truth up input (jump/swim)")),
    ("qwd.usercmd.buttons", ("QWD usercmd_t.buttons", "QWD", "button bitfield (jump/attack)")),
    ("qwd.usercmd.impulse", ("QWD usercmd_t.impulse", "QWD", "weapon switch")),
    ("qwd.usercmd.cmd_angles", ("QWD usercmd_t.angles[3]", "QWD", "commanded view angles deg")),
    ("qwd.usercmd.msec", ("QWD usercmd_t.msec", "QWD", "frame duration ms")),
    ("qwd.view_angles", ("QWD per-record view-angle floats", "QWD", "resulting view angles deg")),
])

# -----------------------------------------------------------------------------
# Per-column classification reasons (the audit verdict).
#
# Keyed "table.column". Each entry: (label, decoder_id_or_None, reason). For derived/excluded
# decoder_id is the upstream field if any. Columns NOT listed default to a structural verdict
# (PK/provenance/static-catalog) computed in classify_column(). This explicit map captures the
# judgment that needs a human-readable reason; the SQL parse supplies the column UNIVERSE so a
# newly-added schema column with no entry surfaces as UNCLASSIFIED (forces a future edit).
# -----------------------------------------------------------------------------
CLASSIFY: "OrderedDict[str, tuple[str, str | None, str]]" = OrderedDict([
    # ---- player_ticks (ego-self state spine) ----
    ("player_ticks.ox", (EXTRACTED, "mvd.pos.xyz", "ETL writes origin x")),
    ("player_ticks.oy", (EXTRACTED, "mvd.pos.xyz", "ETL writes origin y")),
    ("player_ticks.oz", (EXTRACTED, "mvd.pos.xyz", "ETL writes origin z")),
    ("player_ticks.vx", (EXTRACTED, "mvd.velocity.xyz", "ETL writes velocity x (analyzer finite-diff; derived for QWD)")),
    ("player_ticks.vy", (EXTRACTED, "mvd.velocity.xyz", "ETL writes velocity y")),
    ("player_ticks.vz", (EXTRACTED, "mvd.velocity.xyz", "ETL writes velocity z")),
    ("player_ticks.pitch", (EXTRACTED, "mvd.view.pitchyaw", "ETL writes view pitch")),
    ("player_ticks.yaw", (EXTRACTED, "mvd.view.pitchyaw", "ETL writes view yaw")),
    ("player_ticks.roll", (EXTRACTED, "mvd.view.pitchyaw", "ETL writes view roll")),
    ("player_ticks.t_s", (EXTRACTED, "provenance.sha", "ETL writes server-clock seconds")),
    ("player_ticks.msec", (EXTRACTED, "qwd.usercmd.msec", "MVD: tick-delta; QWD: usercmd msec")),
    ("player_ticks.hspeed", (DERIVED, "mvd.velocity.xyz", "hypot(vx,vy) computed by ETL")),
    ("player_ticks.onground", (DERIVED, "mvd.pos.xyz", "geometric onground proxy (pmove_sim); MVD has no server flag")),
    ("player_ticks.onground_is_proxy", (DERIVED, None, "ETL flags proxy provenance (always TRUE for MVD)")),
    ("player_ticks.waterlevel", (EXCLUDED, "mvd.liquid.waterlevel", "decoder CAN emit via -include liquid; ETL does NOT request it -> left NULL")),
    ("player_ticks.health", (EXTRACTED, "state.health", "MVD ETL forward-fills the `-event-types health` value step-timeline onto each tick (T3). NULL on QWD (not yet wired).")),
    ("player_ticks.armor", (EXTRACTED, "state.armor", "MVD ETL forward-fills the `-event-types armor` value step-timeline onto each tick (T3). NULL on QWD.")),
    ("player_ticks.armor_type", (GAP, "state.armor_type", "still GAP after T3: the `-event-types armor` stream carries the AP VALUE but not the armor skin/type; no GA/YA/RA source in the per-tick streams. Deferred (derive from item pickups / T7).")),
    ("player_ticks.weapon", (GAP, "state.weapon_held", "still GAP after T3: the `-event-types weapon` stream is gain/lose INVENTORY, not STAT_ACTIVEWEAPON (the 'active weapon id' the column means); QWD decoder skips SVC_UPDATESTAT. No honest active-weapon source without a decoder change. Deferred.")),
    ("player_ticks.shells", (EXTRACTED, "state.ammo", "MVD ETL forward-fills the `-view full` `sh` step-timeline onto each tick (T6). NULL on QWD.")),
    ("player_ticks.nails", (EXTRACTED, "state.ammo", "MVD ETL forward-fills the `-view full` `nl` step-timeline (T6). NULL on QWD.")),
    ("player_ticks.rockets", (EXTRACTED, "state.ammo", "MVD ETL forward-fills the `-view full` `rk` step-timeline (T6). NULL on QWD.")),
    ("player_ticks.cells", (EXTRACTED, "state.ammo", "MVD ETL forward-fills the `-view full` `cl` step-timeline (T6). NULL on QWD.")),
    ("player_ticks.quad_rem", (EXTRACTED, "state.powerups", "MVD ETL derives remaining-seconds from the `-view full` `q` held-interval [s,e] at each tick (T6); NULL when not held. NULL on QWD.")),
    ("player_ticks.pent_rem", (EXTRACTED, "state.powerups", "MVD ETL derives remaining-seconds from the `-view full` `pe` held-interval at each tick (T6); NULL when not held. NULL on QWD.")),
    ("player_ticks.ring_rem", (EXTRACTED, "state.powerups", "MVD ETL derives remaining-seconds from the `-view full` `r` held-interval at each tick (T6); NULL when not held. NULL on QWD.")),
    # ---- player_ticks [G] geometry + [R] regime + leg-phase (T7 #395; DERIVED, not raw decoder fields) ----
    ("player_ticks.floor_height", (DERIVED, "geom.dm3_bsp", "[G] z - downward hull-1 floor-trace endpoint (matches trace.csv height_above_floor). NULL where the trace startsolids / over void. MVD ETL (T7)")),
    ("player_ticks.over_void", (DERIVED, "geom.dm3_bsp", "[G] 1 if no floor within FLOOR_PROBE_QU OR floor < VOID_THRESH_QU (deep chasm); matches build_trace.py over_void. NULL if startsolid (T7)")),
    ("player_ticks.wall_dist", (DERIVED, "geom.dm3_bsp", "[G] min of the 4 axial ±x/±y hull-1 wall traces, capped at WALL_PROBE_QU. NULL if startsolid (T7)")),
    ("player_ticks.ledge_ahead", (DERIVED, "geom.dm3_bsp", "[G] floor drop along velocity (forward+down trace gap). NULL if hspeed<LEDGE_MIN_HSPEED / void / startsolid (T7)")),
    ("player_ticks.ramp_normal_z", (DERIVED, "geom.dm3_bsp", "[R-input] floor-plane normal z from the downward trace (1.0 flat; <0.95 ramp). NULL over void/startsolid (T7)")),
    ("player_ticks.regime", (DERIVED, None, "[R] accel/cruise/grounded/airborne/water/on-ramp from hspeed+onground+ramp_normal_z (T7)")),
    ("player_ticks.leg_phase", (DERIVED, None, "launch/cruise/approach/land within a resource-to-resource leg (route_legs #334 segmentation); NULL outside any ego goal-conditioned leg (T7)")),
    # ---- actor_ticks (omniscient all-players world) ----
    ("actor_ticks.ox", (EXTRACTED, "world.all_players_state", "QWD ETL writes (self+observed others); MVD ETL writes the omniscient all-players state per episode tick (T4)")),
    ("actor_ticks.oy", (EXTRACTED, "world.all_players_state", "QWD + MVD (T4)")),
    ("actor_ticks.oz", (EXTRACTED, "world.all_players_state", "QWD + MVD (T4)")),
    ("actor_ticks.vx", (EXTRACTED, "world.all_players_state", "QWD + MVD (T4)")),
    ("actor_ticks.vy", (EXTRACTED, "world.all_players_state", "QWD + MVD (T4)")),
    ("actor_ticks.vz", (EXTRACTED, "world.all_players_state", "QWD + MVD (T4)")),
    ("actor_ticks.pitch", (EXTRACTED, "world.all_players_state", "QWD + MVD (T4)")),
    ("actor_ticks.yaw", (EXTRACTED, "world.all_players_state", "QWD + MVD (T4)")),
    ("actor_ticks.roll", (EXTRACTED, "world.all_players_state", "QWD + MVD (MVD writes 0.0; angle16 has no roll) (T4)")),
    ("actor_ticks.alive", (EXTRACTED, "state.spawn_death", "QWD writes; MVD forward-fills the per-player death/spawn step-timeline (T4; NULL before first death/spawn)")),
    ("actor_ticks.hspeed", (DERIVED, "world.all_players_state", "hypot(vx,vy)")),
    ("actor_ticks.onground", (DERIVED, "world.all_players_state", "geometric proxy (QWD); MVD leaves NULL for observed-others (the proxy lives on the ego player_ticks spine)")),
    ("actor_ticks.onground_is_proxy", (DERIVED, None, "proxy-provenance flag")),
    ("actor_ticks.team_id", (EXTRACTED, "world.roster_teams", "MVD writes the absolute team_id from the per-player roster team (T4); QWD writes NULL (no roster join yet)")),
    ("actor_ticks.waterlevel", (EXCLUDED, "mvd.liquid.waterlevel", "decoder CAN emit; not requested -> NULL")),
    ("actor_ticks.health", (EXTRACTED, "state.health", "MVD forward-fills each player's `-view full` `h` step-timeline (T4); QWD NULL")),
    ("actor_ticks.armor", (EXTRACTED, "state.armor", "MVD forward-fills each player's `a` step-timeline (T4); QWD NULL")),
    ("actor_ticks.armor_type", (EXTRACTED, "state.armor_type", "MVD forward-fills each player's `at` ('ga'/'ya'/'ra') step-timeline -> 0/1/2 (T4). The `-view full` `at` stream carries the skin/type the T3 `-event-types armor` decode lacked; QWD NULL")),
    ("actor_ticks.weapon", (GAP, "state.weapon_held", "still GAP after T4: the per-tick weapon stream is gain/lose INVENTORY, not STAT_ACTIVEWEAPON (the active-weapon id the column means) — no honest active-weapon source without a decoder change. Deferred.")),
    ("actor_ticks.shells", (EXTRACTED, "state.ammo", "MVD forward-fills each player's `-view full` `sh` step-timeline (T6); QWD NULL")),
    ("actor_ticks.nails", (EXTRACTED, "state.ammo", "MVD forward-fills each player's `nl` step-timeline (T6); QWD NULL")),
    ("actor_ticks.rockets", (EXTRACTED, "state.ammo", "MVD forward-fills each player's `rk` step-timeline (T6); QWD NULL")),
    ("actor_ticks.cells", (EXTRACTED, "state.ammo", "MVD forward-fills each player's `cl` step-timeline (T6); QWD NULL")),
    ("actor_ticks.quad_rem", (EXTRACTED, "state.powerups", "MVD derives remaining-seconds from each player's `q` held-interval at each tick (T6; NULL when not held); QWD NULL")),
    ("actor_ticks.pent_rem", (EXTRACTED, "state.powerups", "MVD derives remaining-seconds from each player's `pe` held-interval (T6; NULL when not held); QWD NULL")),
    ("actor_ticks.ring_rem", (EXTRACTED, "state.powerups", "MVD derives remaining-seconds from each player's `r` held-interval (T6; NULL when not held); QWD NULL")),
    # ---- actor_ticks [G] geometry + [R] regime (T7 #395; DERIVED from each actor's own origin/velocity) ----
    ("actor_ticks.floor_height", (DERIVED, "geom.dm3_bsp", "[G] per-actor z above floor from the dm3 hull-1 floor trace (T7). NULL if startsolid")),
    ("actor_ticks.over_void", (DERIVED, "geom.dm3_bsp", "[G] per-actor void/deep-chasm-below flag (T7). NULL if startsolid")),
    ("actor_ticks.wall_dist", (DERIVED, "geom.dm3_bsp", "[G] per-actor nearest-wall distance (±x/±y), capped (T7). NULL if startsolid")),
    ("actor_ticks.ledge_ahead", (DERIVED, "geom.dm3_bsp", "[G] per-actor forward floor-drop along velocity (T7). NULL if hspeed<min/void/startsolid")),
    ("actor_ticks.ramp_normal_z", (DERIVED, "geom.dm3_bsp", "[R-input] per-actor floor-plane normal z (T7). NULL over void/startsolid")),
    ("actor_ticks.regime", (DERIVED, None, "[R] per-actor regime from hspeed + a LOCAL geometric onground + ramp_normal_z (T7); the actor_ticks.onground column itself stays NULL by T4 design")),
    ("actor_ticks.leg_phase", (DERIVED, None, "ALWAYS NULL on actor_ticks: leg-phase needs the ego goal/route context, defined only for the episode-owning ego player (T7)")),
    # ---- actions (recovered state->action labels) ----
    ("actions.forwardmove", (EXTRACTED, "qwd.usercmd.forwardmove", "QWD=ground-truth; MVD=IDM-recovered")),
    ("actions.sidemove", (EXTRACTED, "qwd.usercmd.sidemove", "QWD=ground-truth; MVD=IDM sign")),
    ("actions.upmove", (EXTRACTED, "qwd.usercmd.upmove", "QWD=ground-truth; MVD=IDM proxy")),
    ("actions.buttons", (EXTRACTED, "qwd.usercmd.buttons", "QWD=ground-truth; MVD=IDM jump bit")),
    ("actions.impulse", (EXCLUDED, "qwd.usercmd.impulse", "QWD struct carries it; ETL does not write the column (weapon-switch out of movement scope)")),
    ("actions.cmd_yaw", (EXTRACTED, "qwd.usercmd.cmd_angles", "QWD commanded yaw; MVD view-yaw proxy (lossless)")),
    ("actions.cmd_pitch", (EXTRACTED, "qwd.usercmd.cmd_angles", "QWD commanded pitch; MVD view-pitch proxy")),
    ("actions.cmd_roll", (EXTRACTED, "qwd.usercmd.cmd_angles", "QWD commanded roll; MVD writes 0.0")),
    ("actions.label_source", (DERIVED, None, "fidelity tier set by ETL (qwd_usercmd / idm)")),
    ("actions.confidence", (DERIVED, None, "ETL-assigned label confidence")),
    ("actions.align_shift", (EXCLUDED, None, "cmd<->state alignment offset; not written by either ETL (per-frame aligned in place)")),
    ("actions.is_interp", (DERIVED, None, "interp/hold-out flag set by ETL")),
    # ---- item_events ----
    ("item_events.t_s", (EXTRACTED, "items.pickup_respawn", "MVD writes from `-view full` items.items[].phases[] + backpacks (T4); QWD via fixture")),
    ("item_events.event_kind", (EXTRACTED, "items.pickup_respawn", "pickup (phase.takenAt) / respawn (phase.respawnAt) / drop (backpack)")),
    ("item_events.player_id", (EXTRACTED, "items.pickup_respawn", "picker (phase.takenBy / backpack.player); NULL for respawn")),
    ("item_events.item_id", (DERIVED, "items.world_coords", "spatial join to items by origin x/y/z (NULL for backpack drops)")),
    ("item_events.origin_x", (EXTRACTED, "items.backpack_drops", "backpacks.origin for dropped packs (NULL for static pickups, which carry item_id)")),
    ("item_events.origin_y", (EXTRACTED, "items.backpack_drops", "backpacks.origin")),
    ("item_events.origin_z", (EXTRACTED, "items.backpack_drops", "backpacks.origin")),
    ("item_events.item_type", (EXTRACTED, "items.pickup_respawn", "denormalized kind (items.kind / backpack.weapon)")),
    ("item_events.team_id", (EXTRACTED, "world.roster_teams", "team attribution of the pickup (phase.team / backpack.team -> teams)")),
    # ---- frag_events ----
    ("frag_events.t_s", (EXTRACTED, "frags.kill_timeline", "MVD writes from `-view full` frags.frags (T4); QWD via fixture")),
    ("frag_events.killer_id", (EXTRACTED, "frags.kill_timeline", "frags.frags[].killer -> player_id")),
    ("frag_events.victim_id", (EXTRACTED, "frags.kill_timeline", "frags.frags[].victim -> player_id")),
    ("frag_events.weapon", (EXTRACTED, "frags.kill_timeline", "frags.frags[].weapon (rl/lg/sg/.../tele/fall/teamkill)")),
    ("frag_events.is_suicide", (EXTRACTED, "frags.kill_timeline", "frags.frags[].isSuicide")),
    ("frag_events.is_teamkill", (EXTRACTED, "frags.kill_timeline", "frags.frags[].isTeamKill")),
    # ---- damage_events (T5; per-hit KTX damage, ERA-GATED ~2024+; from `-view full` damage.events) ----
    ("demos.damage_available", (EXTRACTED, "damage.per_hit", "era-gate flag: TRUE if the demo carried the `-view full` damage block (per-hit stream authoritative), FALSE => UNKNOWN/pre-era (fail-closed, never zero). MVD ETL writes per demo (T5)")),
    ("damage_events.t_s", (EXTRACTED, "damage.per_hit", "MVD writes from `-view full` damage.events (T5, era-gated); damage.events[].time/1000")),
    ("damage_events.attacker_id", (EXTRACTED, "damage.per_hit", "damage.events[].attacker -> player_id (NULL for 'world'/environmental)")),
    ("damage_events.victim_id", (EXTRACTED, "damage.per_hit", "damage.events[].victim -> player_id")),
    ("damage_events.weapon", (EXTRACTED, "damage.per_hit", "damage.events[].weapon (rl/lg/sg/.../fall/drown/trigger)")),
    ("damage_events.damage", (EXTRACTED, "damage.per_hit", "damage.events[].damage (hit-point amount)")),
    ("damage_events.is_splash", (EXTRACTED, "damage.per_hit", "damage.events[].isSplash")),
    ("damage_events.is_env", (EXTRACTED, "damage.per_hit", "damage.events[].isEnv (fall/drown/trigger)")),
    ("damage_events.is_self", (EXTRACTED, "damage.per_hit", "damage.events[].isSelf (attacker==victim)")),
    ("damage_events.is_teamkill", (EXTRACTED, "damage.per_hit", "damage.events[].isTeam (same-team damage)")),
    # ---- teams ----
    ("teams.name", (EXTRACTED, "world.roster_teams", "MVD writes distinct per-player roster team names (T4); QWD via fixture")),
    ("teams.side", (DERIVED, "world.roster_teams", "canonical A/B side label (first-seen team order)")),
    # ---- region_control_timeline ----
    ("region_control_timeline.t_s", (EXTRACTED, "region.control_timeline", "QWD ETL via fixture; decoder getRegionControl")),
    ("region_control_timeline.region_name", (EXTRACTED, "region.control_timeline", "getRegionControl region")),
    ("region_control_timeline.teamA_control", (EXTRACTED, "region.control_timeline", "side-A control fraction")),
    ("region_control_timeline.teamB_control", (EXTRACTED, "region.control_timeline", "side-B control fraction")),
    ("region_control_timeline.contested", (EXTRACTED, "region.control_timeline", "contested flag")),
    # ---- actor_visibility (POMDP layer; derived offline, no decoder endpoint) ----
    ("actor_visibility.is_visible", (GAP, None, "spec'd POMDP gate (PVS+FOV+LOS); table empty. T8.")),
    ("actor_visibility.pvs_visible", (GAP, None, "BSP visleaf prefilter; empty. T8.")),
    ("actor_visibility.in_fov", (GAP, None, "bearing-in-FOV; empty. T8.")),
    ("actor_visibility.los_clear", (GAP, None, "raycast on hull-0; empty. T8.")),
    ("actor_visibility.last_seen_ox", (GAP, None, "belief/memory block; empty. T8.")),
    ("actor_visibility.time_since_seen_s", (GAP, None, "belief block; empty. T8.")),
    ("actor_visibility.seen_ever", (GAP, None, "belief block; empty. T8.")),
    # ---- audio_cues (derived offline) ----
    ("audio_cues.src_type", (GAP, "audio.weapon_item_cues", "weapon_fire/item_pickup from getEvents + synthesized footstep; table empty. T8.")),
    ("audio_cues.src_x", (GAP, "audio.weapon_item_cues", "sound source world position; empty. T8.")),
    ("audio_cues.intensity0", (GAP, None, "emission intensity (decay model); empty. T8.")),
    ("audio_cues.t_emit_s", (GAP, None, "emission time for decay; empty. T8.")),
    # ---- maps (static; from BSP / maps.v1 — not a per-demo decoder field) ----
    ("maps.x_min", (EXCLUDED, "items.world_coords", "static AABB from maps.v1/BSP, not per-demo decode")),
    ("maps.diagonal", (DERIVED, None, "computed from AABB")),
    ("maps.maxspeed", (EXCLUDED, None, "QW physics constant (default), not a decoder field")),
    # ---- items (static catalog; getMapEntities, not per-demo state) ----
    ("items.origin_x", (EXTRACTED, "items.world_coords", "getMapEntities world spawn coords")),
    ("items.classname", (EXTRACTED, "items.world_coords", "getMapEntities.class")),
    ("items.respawn_seconds", (EXCLUDED, "items.pickup_respawn", "canonical prior (domain), validated against observed phases[]")),
    ("items.static_value", (EXCLUDED, None, "importance prior; fitted/domain, not a decoder field")),
    ("items.nearest_marker", (EXCLUDED, None, "nav-routing denormalization (Frogbot markers); not a decoder field")),
    ("items.coords_verified", (EXCLUDED, None, "provenance flag for getMapEntities-filled coords; not a decoder field")),
    # ---- markers / nav_edges (Frogbot graph; NOT in mvd_analyzer) ----
    ("markers.origin_x", (EXCLUDED, "locgraph.movement", "Frogbot .bot CreateMarker parse; mvd_analyzer has no nav mesh")),
    ("nav_edges.distance_qu", (EXCLUDED, None, "Frogbot path-edge geometry; not a decoder field")),
    # ---- item_value (data-derived model; not a decoder field) ----
    ("item_value.importance_norm", (EXCLUDED, None, "fitted on train split (logreg/pearson); not a decoder field")),
    # ---- feature_partitions (build lineage; not a decoder field) ----
    ("feature_partitions.path", (EXCLUDED, None, "gold-parquet build lineage; not a decoder field")),
])

# Column-FAMILY fallbacks: a column whose name matches a (table, regex) rule inherits the
# verdict of a representative sibling without enumerating every coordinate axis by hand. Keeps
# the audit forward-compatible (a genuinely-new column still falls through to UNCLASSIFIED).
# Each rule: (table, name_regex) -> representative "table.column" key in CLASSIFY.
FAMILY_FALLBACKS: "list[tuple[str, str, str]]" = [
    ("maps", r"^(x|y|z)_(min|max)$", "maps.x_min"),         # AABB axes
    ("maps", r"^center_[xyz]$", "maps.diagonal"),            # computed centre
    ("maps", r"^source_bsp$", "maps.x_min"),                 # static map metadata
    ("maps", r"^(jumpspeed|gravity|friction|stopspeed|accelerate|airaccel_cap)$", "maps.maxspeed"),
    ("markers", r"^origin_[yz]$", "markers.origin_x"),
    ("markers", r"^(zone|goal|is_teleport|is_door)$", "markers.origin_x"),  # Frogbot graph attrs
    ("nav_edges", r"^(from_marker|to_marker|edge_idx|path_flags|is_jump|is_teleport)$", "nav_edges.distance_qu"),
    ("items", r"^origin_[yz]$", "items.origin_x"),
    ("items", r"^(item_type|category)$", "items.classname"),
    ("item_value", r"^(item_type|method|coef|n_rounds|dataset_version)$", "item_value.importance_norm"),
    ("actor_visibility", r"^last_seen_(t_s|o[yz]|v[xyz])$", "actor_visibility.last_seen_ox"),
    ("audio_cues", r"^src_[yz]$", "audio_cues.src_x"),
]

# Columns that are pure structure (PKs, FKs, provenance, split bookkeeping) — verdict
# 'structural', reported separately and never counted as a coverage GAP.
STRUCTURAL_COLUMN_SUFFIXES = (
    "_id", "tick", "split", "split_policy", "sha256", "path", "source", "name",
    "handle", "is_bot", "map_id", "demo_kind", "recorded_at", "duration_s",
    "server_fps", "parser_commit", "start_tick", "end_tick", "n_steps",
    "total_reward", "bucket_idx", "registry_version", "norm_artifact_version",
    "git_sha", "dt", "n_rows",
)

# The 6 genuine gaps named in the plan (epic #388 / buildout plan). The audit confirms its
# findings line up with these — neither inventing gaps nor missing one.
PLAN_GAPS = [
    "G1: no coverage audit (THIS script fills it)",
    "G2: schema-file drift (scripts/catalog_schema.sql operative vs data/catalog/catalog.sql dup "
    "vs registry's dangling `schema/catalog.sql` reference)",
    "G3: damage_events table absent (only frag_events exists) — ADDRESSED by T5 #393: the table is "
    "now schema-defined + populated from `-view full` damage.events, era-gated via "
    "demos.damage_available (fail-closed)",
    "G4: ammo + powerup-remaining source columns absent (registry defines the features) — ADDRESSED "
    "by T6 #394: shells/nails/rockets/cells + quad_rem/pent_rem/ring_rem added to player_ticks + "
    "actor_ticks and populated from the same `-view full` per-player sh/nl/rk/cl + q/pe/r streams "
    "(ammo forward-filled; powerup remaining-seconds derived from the held-interval, NULL when not held)",
    "G5: stored [G] geometry / [R] regime / leg-phase columns absent — ADDRESSED by T7 #395: "
    "floor_height/over_void/wall_dist/ledge_ahead/ramp_normal_z + regime + leg_phase added to "
    "player_ticks + actor_ticks and DERIVED (pmove_sim hull-1 traces over the sha-locked dm3.bsp "
    "for [G]; kinematics+ramp for [R]; route_legs #334 segmentation for leg-phase). They are now "
    "schema-defined + populated, appearing as DERIVED columns above (NULL where undefined, never "
    "fabricated; leg_phase NULL on actor_ticks — no ego goal context)",
    "G6: docs/27 inaccuracies (frag_events/actor_visibility/audio_cues/teams called "
    "greenfield/reserved when schema-defined-but-empty; wrong schema path)",
]


# =============================================================================
# Parsers (read-only, text only)
# =============================================================================
def parse_schema_tables(sql_path: Path) -> "OrderedDict[str, list[str]]":
    """Parse CREATE TABLE blocks -> {table: [column, ...]}. Comment/constraint lines skipped."""
    text = sql_path.read_text(encoding="utf-8")
    tables: "OrderedDict[str, list[str]]" = OrderedDict()
    block_re = re.compile(r"CREATE\s+TABLE\s+(\w+)\s*\((.*?)\n\s*\);", re.DOTALL | re.IGNORECASE)
    constraint_kw = ("PRIMARY", "FOREIGN", "UNIQUE", "CHECK", "CONSTRAINT")
    for m in block_re.finditer(text):
        table = m.group(1)
        cols: list[str] = []
        for raw in m.group(2).splitlines():
            line = raw.strip()
            # strip trailing inline comment, then drop pure-comment / blank lines
            line = re.split(r"--", line, 1)[0].strip()
            if not line:
                continue
            head = line.split()[0].upper()
            if head in constraint_kw:
                continue
            col = line.split()[0]
            # a single physical line can declare several cols (e.g. "x_min REAL, x_max REAL")
            for piece in line.split(","):
                piece = piece.strip()
                if not piece:
                    continue
                first = piece.split()[0]
                if first.upper() in constraint_kw:
                    break
                if re.match(r"^[A-Za-z_]\w*$", first) and first not in cols:
                    cols.append(first)
        tables[table] = cols
    return tables


def parse_etl_inserts(etl_path: Path) -> "dict[str, set[str]]":
    """Parse `INSERT [OR IGNORE] INTO <table> (col, ...)` -> {table: {cols}} actually written."""
    text = etl_path.read_text(encoding="utf-8")
    out: "dict[str, set[str]]" = {}
    ins_re = re.compile(
        r"INSERT(?:\s+OR\s+\w+)?\s+INTO\s+(\w+)\s*\((.*?)\)\s*(?:VALUES|SELECT)",
        re.DOTALL | re.IGNORECASE,
    )
    for m in ins_re.finditer(text):
        table = m.group(1)
        cols = {c.strip() for c in m.group(2).split(",") if c.strip()}
        # ignore SELECT-style INSERTs that captured no clean column list
        cols = {c for c in cols if re.match(r"^[A-Za-z_]\w*$", c)}
        out.setdefault(table, set()).update(cols)
    return out


def parse_registry_sources(yaml_path: Path) -> "dict[str, set[str]]":
    """Map each `table.column` -> {feature names that reference it} from feature `source:`.

    Parsed with a stdlib line-scan rather than PyYAML — this script is part of the
    deterministic CI floor and CI has no PyYAML. Within the `feature_groups:` region we
    track the current `name:` and pull `table.column` tokens out of each `source:` value.
    """
    refs: "dict[str, set[str]]" = {}
    in_groups = False
    cur_name = "?"
    for raw in yaml_path.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not in_groups:
            if re.match(r"^feature_groups\s*:", stripped):
                in_groups = True
            continue
        m = re.match(r"^-?\s*name\s*:\s*(.+?)\s*$", stripped)
        if m:
            cur_name = m.group(1).strip().strip("\"'")
            continue
        if re.match(r"^source\s*:", stripped):
            value = stripped.split(":", 1)[1]
            # column names may carry uppercase/digits (teamA_control, intensity0);
            # table starts with a letter/underscore so numeric literals (0.5) don't match.
            for token in re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*\.[A-Za-z0-9_]+)\b", value):
                refs.setdefault(token, set()).add(cur_name)
    return refs


# =============================================================================
# Classification
# =============================================================================
def is_structural(col: str) -> bool:
    return any(col == s or col.endswith(s) for s in STRUCTURAL_COLUMN_SUFFIXES)


def classify_column(table: str, col: str) -> tuple[str, str | None, str]:
    """Return (label, decoder_id, reason) for a schema column."""
    key = f"{table}.{col}"
    if key in CLASSIFY:
        return CLASSIFY[key]
    # Sibling coordinate/axis columns inherit a representative's family verdict (no per-axis copy).
    for ftable, regex, rep in FAMILY_FALLBACKS:
        if table == ftable and re.match(regex, col):
            return CLASSIFY[rep]
    if is_structural(col):
        return ("structural", None, "PK/FK/provenance/split bookkeeping")
    # Anything else flags UNCLASSIFIED so a genuinely-new schema column forces a review.
    return ("UNCLASSIFIED", None, "no explicit verdict — extend CLASSIFY when the schema grows")


# =============================================================================
# Report
# =============================================================================
def build_report(schema, etl_mvd, etl_qwd, registry_refs) -> tuple[str, dict]:
    counts = {EXTRACTED: 0, DERIVED: 0, EXCLUDED: 0, GAP: 0, "structural": 0, "UNCLASSIFIED": 0}
    lines: list[str] = []
    lines.append("# Extraction-coverage audit — decoder Result inventory vs catalog vs registry")
    lines.append("")
    lines.append("> **GENERATED FILE — do not edit by hand.** Regenerate with:")
    lines.append("> ```")
    lines.append("> python3 scripts/audit_extraction_coverage.py")
    lines.append("> ```")
    lines.append(">")
    lines.append("> Read-only audit for Demo Extraction Spec v1 (`docs/27` §3.9/§7), ticket #389 (T1),")
    lines.append("> epic #388. Loads NO database, hits NO network. It enumerates the decoder Result")
    lines.append(f"> inventory (anchored in `{SOURCE_SCHEMAS_DOC}`) and diffs it against the operative")
    lines.append("> schema `scripts/catalog_schema.sql`, `data/catalog/feature_registry.yaml`, and what")
    lines.append("> `catalog_etl_mvd.py` / `catalog_etl_qwd.py` actually populate. Classifies every")
    lines.append("> catalog column **extracted / derived / excluded-with-reason / GAP**.")
    lines.append("")

    # Per-table classification tables.
    lines.append("## Per-column classification (grouped by table)")
    lines.append("")
    for table, cols in schema.items():
        mvd_cols = etl_mvd.get(table, set())
        qwd_cols = etl_qwd.get(table, set())
        lines.append(f"### `{table}`")
        lines.append("")
        lines.append("| column | class | decoder field | populated by | registry | reason |")
        lines.append("|---|---|---|---|---|---|")
        for col in cols:
            label, decoder_id, reason = classify_column(table, col)
            counts[label] = counts.get(label, 0) + 1
            pops = []
            if col in mvd_cols:
                pops.append("mvd-etl")
            if col in qwd_cols:
                pops.append("qwd-etl")
            populated = ", ".join(pops) if pops else "—"
            reg = "yes" if f"{table}.{col}" in registry_refs else "—"
            dec = decoder_id or "—"
            lines.append(f"| `{col}` | {label} | {dec} | {populated} | {reg} | {reason} |")
        lines.append("")

    # Decoder inventory (the master list, for reference + forward-compat).
    lines.append("## Decoder Result inventory (master list)")
    lines.append("")
    lines.append("Sourced from the committed static reference "
                 f"`{SOURCE_SCHEMAS_DOC}` + qw-analyze schema-33 `-include` groups + getStateAt")
    lines.append("field codes + the QWD `usercmd_t` struct. Referenced by decoder **role**, not tool name.")
    lines.append("")
    lines.append("| decoder field | origin | availability | note |")
    lines.append("|---|---|---|---|")
    for fid, (origin, avail, note) in DECODER_INVENTORY.items():
        lines.append(f"| `{fid}` | {origin} | {avail} | {note} |")
    lines.append("")

    # Summary counts.
    n_class = counts[EXTRACTED] + counts[DERIVED] + counts[EXCLUDED] + counts[GAP]
    lines.append("## Summary")
    lines.append("")
    lines.append("| class | count |")
    lines.append("|---|---|")
    lines.append(f"| extracted | {counts[EXTRACTED]} |")
    lines.append(f"| derived | {counts[DERIVED]} |")
    lines.append(f"| excluded-with-reason | {counts[EXCLUDED]} |")
    lines.append(f"| **GAP** | **{counts[GAP]}** |")
    lines.append(f"| (structural: PK/FK/provenance) | {counts['structural']} |")
    lines.append(f"| (UNCLASSIFIED — needs a verdict) | {counts['UNCLASSIFIED']} |")
    lines.append(f"| classified content columns | {n_class} |")
    lines.append("")

    # GAP reconciliation against the plan.
    lines.append("## GAP reconciliation (vs epic #388 / build-out plan)")
    lines.append("")
    lines.append("The per-column GAPs above are the *defined-but-unpopulated* columns the population")
    lines.append("tickets (T3/T4/T8) fill. They roll up to the **6 genuine gaps** the plan names — the")
    lines.append("only truly-new work — confirming the audit neither invents nor misses a gap:")
    lines.append("")
    for g in PLAN_GAPS:
        lines.append(f"- {g}")
    lines.append("")
    lines.append("**Scoping (which ticket each per-column GAP feeds):** `player_ticks` health/armor -> "
                 "T3 (DONE); the omniscient `actor_ticks` all-players state + health/armor/armor_type + "
                 "team_id, plus `item_events`/`frag_events`/`teams` -> T4 (DONE; from `-view full`). The "
                 "GAPs that REMAIN: `player_ticks.armor_type`/`weapon` + `actor_ticks.weapon` (no honest "
                 "active-weapon / ego armor-skin source without a decoder change), and `actor_visibility.*` "
                 "+ `audio_cues.*` -> T8. The `damage_events` table (G3) is now schema-defined + "
                 "populated (T5 #393, era-gated via `demos.damage_available`), so it appears as extracted "
                 "columns above. The ammo/powerup source columns (G4) are likewise now "
                 "schema-defined + populated (T6 #394: `shells`/`nails`/`rockets`/`cells` + "
                 "`quad_rem`/`pent_rem`/`ring_rem` on `player_ticks` + `actor_ticks`, from the same "
                 "`-view full` streams), so they too appear as extracted columns above. The [G] geometry "
                 "/ [R] regime / leg-phase columns (G5) are now ADDRESSED by T7 #395: "
                 "`floor_height`/`over_void`/`wall_dist`/`ledge_ahead`/`ramp_normal_z` + `regime` + "
                 "`leg_phase` are schema-defined on `player_ticks` + `actor_ticks` and populated by the "
                 "MVD ETL, so they appear as DERIVED columns above (computed from the sha-locked dm3.bsp "
                 "hull-1 traces + kinematics + the route_legs #334 segmentation — NULL where undefined, "
                 "never fabricated; `leg_phase` is NULL on `actor_ticks` for want of an ego goal context). "
                 "No per-column GAP remains absent from the schema entirely.")
    return "\n".join(lines).rstrip("\n") + "\n", counts


# =============================================================================
# Self-checks (the runnable assert gate)
# =============================================================================
def _report_claims_g4_absent(report: str) -> bool:
    """True if the report prose asserts the G4 ammo/powerup columns are absent from the schema.

    Robust to minor wording: requires, within one sentence, both a reference to the
    ammo/powerup (G4) columns AND an "absent from the schema" claim. Matches the substantive
    claim rather than a single brittle string so a future edit can't dodge the guard by
    rephrasing.
    """
    text = report.lower()
    for sentence in re.split(r"(?<=[.!?])\s+|\n", text):
        mentions_g4 = ("ammo/powerup" in sentence
                       or ("g4" in sentence and "g5" not in sentence)
                       or ("ammo" in sentence and "powerup" in sentence))
        claims_absent = "absent from the schema" in sentence
        if mentions_g4 and claims_absent:
            return True
    return False


def _report_claims_g5_absent(report: str) -> bool:
    """True if the report prose asserts the G5 [G]/[R]/leg-phase columns are absent from the schema.

    Mirrors _report_claims_g4_absent (#404 P1): within one sentence, both a reference to the
    G5 geometry/regime/leg-phase columns AND an "absent from the schema" claim. After T7 #395
    those columns are schema-defined + populated, so this contradiction must never reappear.
    """
    text = report.lower()
    for sentence in re.split(r"(?<=[.!?])\s+|\n", text):
        mentions_g5 = ("leg-phase" in sentence or "leg_phase" in sentence
                       or ("g5" in sentence and "g4" not in sentence)
                       or ("[g]" in sentence and "regime" in sentence)
                       or ("geometry" in sentence and "regime" in sentence))
        claims_absent = "absent from the schema" in sentence
        if mentions_g5 and claims_absent:
            return True
    return False


def run_self_checks() -> None:
    schema = parse_schema_tables(SCHEMA_SQL)
    etl_mvd = parse_etl_inserts(ETL_MVD)
    etl_qwd = parse_etl_inserts(ETL_QWD)
    registry_refs = parse_registry_sources(REGISTRY_YAML)

    # Schema parse sanity: the v2 4on4 tables must all be present.
    for t in ("player_ticks", "actor_ticks", "actions", "item_events", "frag_events",
              "damage_events", "teams", "actor_visibility", "audio_cues", "region_control_timeline"):
        assert t in schema, f"schema parse missing table {t}"
    assert "weapon" in schema["player_ticks"], "player_ticks.weapon column not parsed"

    # ETL parse sanity: both ETLs write player_ticks + actions; after T4 the MVD ETL ALSO writes
    # the omniscient world (actor_ticks + item_events + frag_events + teams).
    assert "player_ticks" in etl_mvd and "actions" in etl_mvd
    assert "actor_ticks" in etl_mvd, "MVD ETL must populate actor_ticks (T4 omniscient world)"
    assert "actor_ticks" in etl_qwd, "QWD ETL should populate actor_ticks"
    for t in ("item_events", "frag_events", "teams"):
        assert t in etl_mvd, f"MVD ETL must populate {t} (T4)"

    # The known GAP fields must classify as GAP (the load-bearing audit verdict). After T3,
    # player_ticks.health/armor are EXTRACTED; after T4 the actor_ticks state cols are too. The
    # GAPs that REMAIN: armor_type/weapon on the EGO player_ticks spine (the `-event-types` decode
    # carries the AP value but not the skin/type nor STAT_ACTIVEWEAPON), actor_ticks.weapon (same
    # no-active-weapon-source reason), and the T8 derived layers (actor_visibility / audio_cues).
    known_gaps = [
        ("player_ticks", "armor_type"), ("player_ticks", "weapon"),
        ("actor_ticks", "weapon"),
        ("actor_visibility", "is_visible"), ("audio_cues", "src_type"),
    ]
    for table, col in known_gaps:
        label, _, _ = classify_column(table, col)
        assert label == GAP, f"{table}.{col} expected GAP, got {label}"

    # A known-extracted field must classify extracted; a known-derived derived; excluded excluded.
    assert classify_column("player_ticks", "ox")[0] == EXTRACTED
    # T3: resource health/armor populated by the MVD ETL -> extracted (and actually in its INSERT list)
    assert classify_column("player_ticks", "health")[0] == EXTRACTED
    assert classify_column("player_ticks", "armor")[0] == EXTRACTED
    assert "health" in etl_mvd.get("player_ticks", set()), "MVD ETL must populate player_ticks.health (T3)"
    assert "armor" in etl_mvd.get("player_ticks", set()), "MVD ETL must populate player_ticks.armor (T3)"
    assert classify_column("player_ticks", "hspeed")[0] == DERIVED
    assert classify_column("player_ticks", "waterlevel")[0] == EXCLUDED

    # T4: the omniscient actor_ticks state + resources classify extracted (and are in the INSERT
    # list); armor_type flips GAP->extracted here (the `-view full` `at` stream), weapon stays GAP.
    for col in ("ox", "alive", "team_id", "health", "armor", "armor_type"):
        assert classify_column("actor_ticks", col)[0] == EXTRACTED, f"actor_ticks.{col} should be extracted (T4)"
        assert col in etl_mvd.get("actor_ticks", set()), f"MVD ETL must populate actor_ticks.{col} (T4)"
    assert classify_column("actor_ticks", "weapon")[0] == GAP, "actor_ticks.weapon stays GAP (no active-weapon source)"
    assert classify_column("frag_events", "killer_id")[0] == EXTRACTED
    assert classify_column("teams", "name")[0] == EXTRACTED

    # T5: damage_events is now schema-defined + populated (G3 closed), era-gated via
    # demos.damage_available. Its content columns classify extracted and the MVD ETL writes them.
    for col in ("attacker_id", "victim_id", "weapon", "damage", "is_splash"):
        assert classify_column("damage_events", col)[0] == EXTRACTED, f"damage_events.{col} should be extracted (T5)"
        assert col in etl_mvd.get("damage_events", set()), f"MVD ETL must populate damage_events.{col} (T5)"
    assert classify_column("demos", "damage_available")[0] == EXTRACTED, "demos.damage_available is the era-gate (T5)"

    # T6: ammo + powerup-remaining source columns now exist on BOTH the ego spine and the
    # omniscient world, populated from the same `-view full` per-player sh/nl/rk/cl + q/pe/r
    # (G4 closed). They classify extracted and the MVD ETL writes them on both tables.
    for col in ("shells", "nails", "rockets", "cells", "quad_rem", "pent_rem", "ring_rem"):
        assert classify_column("player_ticks", col)[0] == EXTRACTED, f"player_ticks.{col} should be extracted (T6)"
        assert col in etl_mvd.get("player_ticks", set()), f"MVD ETL must populate player_ticks.{col} (T6)"
        assert classify_column("actor_ticks", col)[0] == EXTRACTED, f"actor_ticks.{col} should be extracted (T6)"
        assert col in etl_mvd.get("actor_ticks", set()), f"MVD ETL must populate actor_ticks.{col} (T6)"

    # T7: [G] geometry + [R] regime + leg-phase derived columns now exist on BOTH tables (G5
    # closed). They classify DERIVED (computed from the dm3.bsp traces + kinematics + route_legs,
    # NOT raw decoder fields) and the MVD ETL writes them. leg_phase is on player_ticks too.
    t7_geom = ("floor_height", "over_void", "wall_dist", "ledge_ahead", "ramp_normal_z")
    for col in t7_geom + ("regime", "leg_phase"):
        assert classify_column("player_ticks", col)[0] == DERIVED, f"player_ticks.{col} should be DERIVED (T7)"
        assert col in etl_mvd.get("player_ticks", set()), f"MVD ETL must populate player_ticks.{col} (T7)"
        assert classify_column("actor_ticks", col)[0] == DERIVED, f"actor_ticks.{col} should be DERIVED (T7)"
        assert col in etl_mvd.get("actor_ticks", set()), f"MVD ETL must populate actor_ticks.{col} (T7)"

    # Every CLASSIFY key must reference a real schema column (no stale verdict).
    valid = {f"{t}.{c}" for t, cols in schema.items() for c in cols}
    stale = [k for k in CLASSIFY if k not in valid]
    assert not stale, f"CLASSIFY references columns absent from schema: {stale}"

    # No content column may be left UNCLASSIFIED (forces a verdict when the schema grows).
    unclassified = []
    for table, cols in schema.items():
        for col in cols:
            if classify_column(table, col)[0] == "UNCLASSIFIED":
                unclassified.append(f"{table}.{col}")
    assert not unclassified, f"UNCLASSIFIED columns (extend CLASSIFY): {unclassified}"

    # Registry sanity: a defined feature references player_ticks.health (the resource GAP).
    assert "player_ticks.health" in registry_refs, "registry should reference player_ticks.health"

    # The 6-gap roll-up must stay enumerated.
    assert len(PLAN_GAPS) == 6, "plan names exactly 6 genuine gaps"

    # Anti-recurrence guard (#404 P1): the report must not SIMULTANEOUSLY classify the T6
    # ammo/powerup G4 columns as extracted AND assert in its prose that those columns are
    # "absent from the schema". Build the report text and detect the contradiction directly so
    # the deterministic gate can never green-light a self-contradictory data contract.
    report, _ = build_report(schema, etl_mvd, etl_qwd, registry_refs)
    t6_cols = ("shells", "nails", "rockets", "cells", "quad_rem", "pent_rem", "ring_rem")
    t6_extracted = all(classify_column("player_ticks", c)[0] == EXTRACTED for c in t6_cols)
    if t6_extracted and _report_claims_g4_absent(report):
        raise AssertionError(
            "report contradiction (#404 P1): T6 ammo/powerup columns classify as extracted, "
            "yet the report prose still asserts the G4 ammo/powerup columns are absent from the "
            "schema. Update the scoping paragraph to mark G4 as ADDRESSED by T6.")

    # Anti-recurrence guard (T7 #395, mirroring #404 P1): the report must not SIMULTANEOUSLY
    # classify the T7 [G]/[R]/leg-phase columns as schema-present (DERIVED) AND assert in its prose
    # that those columns are "absent from the schema". After T7 they are defined + populated.
    t7_present = all(classify_column("player_ticks", c)[0] == DERIVED for c in t7_geom)
    if t7_present and _report_claims_g5_absent(report):
        raise AssertionError(
            "report contradiction (T7 #395): the [G]/[R]/leg-phase columns classify as DERIVED "
            "(schema-defined + populated), yet the report prose still asserts the G5 columns are "
            "absent from the schema. Update the scoping paragraph to mark G5 as ADDRESSED by T7.")

    print("self-checks: OK")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="run self-checks only; write nothing")
    ap.add_argument("--out", type=Path, default=REPORT, help="report output path")
    args = ap.parse_args(argv)

    if args.check:
        run_self_checks()
        return 0

    schema = parse_schema_tables(SCHEMA_SQL)
    etl_mvd = parse_etl_inserts(ETL_MVD)
    etl_qwd = parse_etl_inserts(ETL_QWD)
    registry_refs = parse_registry_sources(REGISTRY_YAML)
    report, counts = build_report(schema, etl_mvd, etl_qwd, registry_refs)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report, encoding="utf-8")
    print(f"wrote {args.out.relative_to(REPO_ROOT)}  "
          f"(extracted={counts[EXTRACTED]} derived={counts[DERIVED]} "
          f"excluded={counts[EXCLUDED]} GAP={counts[GAP]} "
          f"structural={counts['structural']} unclassified={counts['UNCLASSIFIED']})")
    run_self_checks()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
