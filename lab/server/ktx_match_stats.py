#!/usr/bin/env python3
"""Normalize KTX 4v4/team match stats for BotLab validation and casting.

KTX writes useful post-game JSON, but the shape is KTX-native:

* 4v4 is reported as ordinary team mode (`mode == "team"`, `dm == 1`,
  `tp == 2`), not as a distinct `"4on4"` mode.
* team scores are not serialized as a team block; they are the sum of player
  `stats.frags` by team.
* weapon and item blocks are emitted only when non-zero.
* `dmg["taken-to-die"] == 99999` means the player did not die.

This module preserves those source facts and exposes a compact canonical schema
that can be consumed by the BotLab validation ledger and read-only casting
views without making fixed-roster assumptions.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

SCHEMA = "komodobots.ktx_match_stats.v1"

HEALTH_ITEMS = ("health_15", "health_25", "health_100")
ARMOR_ITEMS = ("ya", "ra")
POWERUP_ITEMS = {"quad": "q", "pent": "p", "ring": "r"}
OPTIONAL_ZERO_SOURCE = "absent optional KTX block -> 0"


def _as_number(value: Any) -> int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        try:
            if "." in value:
                return float(value)
            return int(value)
        except ValueError:
            return None
    return None


def _number_at(obj: dict[str, Any], path: list[str], default: int | float | None = None) -> int | float | None:
    cur: Any = obj
    for part in path:
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    value = _as_number(cur)
    return default if value is None else value


def _text_at(obj: dict[str, Any], path: list[str], default: str | None = None) -> str | None:
    cur: Any = obj
    for part in path:
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    if cur is None:
        return default
    return str(cur)


def _has_path(obj: dict[str, Any], path: list[str]) -> bool:
    cur: Any = obj
    for part in path:
        if not isinstance(cur, dict) or part not in cur:
            return False
        cur = cur[part]
    return True


def _source(player_index: int, *parts: str) -> str:
    suffix = "".join(f"[{p!r}]" for p in parts)
    return f"players[{player_index}]{suffix}"


def _path(player_index: int, dotted: str) -> str:
    return _source(player_index, *dotted.split("."))


def _metric_sources(player_index: int) -> dict[str, str | list[str]]:
    return {
        "frags": _path(player_index, "stats.frags"),
        "deaths": _path(player_index, "stats.deaths"),
        "kills": _path(player_index, "stats.kills"),
        "efficiency": [_path(player_index, "stats.kills"), _path(player_index, "stats.deaths")],
        "team_kills": _path(player_index, "stats.tk"),
        "damage_done": _path(player_index, "dmg.given"),
        "damage_taken": _path(player_index, "dmg.taken"),
        "team_damage": _path(player_index, "dmg.team"),
        "self_damage": _path(player_index, "dmg.self"),
        "team_weapon_damage": _path(player_index, "dmg.team-weapons"),
        "enemy_weapon_damage": _path(player_index, "dmg.enemy-weapons"),
        "taken_to_die": _path(player_index, "dmg.taken-to-die"),
        "xfer_rl": _source(player_index, "xferRL"),
        "xfer_lg": _source(player_index, "xferLG"),
        "avg_speed": _path(player_index, "speed.avg"),
        "max_speed": _path(player_index, "speed.max"),
        "health_pickups": [_source(player_index, "items", name, "took") for name in HEALTH_ITEMS],
        "pill_pickups": _source(player_index, "items", "health_15", "took"),
        "brick_pickups": _source(player_index, "items", "health_25", "took"),
        "mega_pickups": _source(player_index, "items", "health_100", "took"),
        "ya_pickups": _source(player_index, "items", "ya", "took"),
        "ra_pickups": _source(player_index, "items", "ra", "took"),
        "quad_pickups": _source(player_index, "items", "q", "took"),
        "pent_pickups": _source(player_index, "items", "p", "took"),
        "ring_pickups": _source(player_index, "items", "r", "took"),
        "rl_pickups": _source(player_index, "weapons", "rl", "pickups", "taken"),
        "rl_drops": _source(player_index, "weapons", "rl", "pickups", "dropped"),
        "enemy_rl_kills": _source(player_index, "weapons", "rl", "kills", "enemy"),
        "lg_pickups": _source(player_index, "weapons", "lg", "pickups", "taken"),
    }


def _item_took(player: dict[str, Any], name: str) -> int:
    return int(_number_at(player, ["items", name, "took"], 0) or 0)


def _weapon_stat(player: dict[str, Any], weapon: str, *path: str) -> int:
    return int(_number_at(player, ["weapons", weapon, *path], 0) or 0)


def _identity_key(slot: int, player: dict[str, Any]) -> str:
    team = _text_at(player, ["team"], "") or ""
    name = _text_at(player, ["name"], "") or ""
    login = _text_at(player, ["login"], "") or ""
    raw = f"{slot:02d}:{team}:{login or name}"
    return re.sub(r"\s+", "_", raw.strip().lower())


def _normalize_player(player: dict[str, Any], index: int, warnings: list[str]) -> dict[str, Any]:
    slot = index + 1
    stats = player.get("stats")
    dmg = player.get("dmg")
    if not isinstance(stats, dict):
        warnings.append(f"players[{index}] missing required stats block")
        stats = {}
    if not isinstance(dmg, dict):
        warnings.append(f"players[{index}] missing required dmg block")
        dmg = {}

    missing_required = []
    for dotted in (
        "stats.frags",
        "stats.deaths",
        "stats.kills",
        "stats.tk",
        "dmg.given",
        "dmg.taken",
        "dmg.enemy-weapons",
        "dmg.taken-to-die",
    ):
        if not _has_path(player, dotted.split(".")):
            missing_required.append(dotted)
    if missing_required:
        warnings.append(f"players[{index}] missing required fields: {', '.join(missing_required)}")

    frags = int(_number_at(player, ["stats", "frags"], 0) or 0)
    deaths = int(_number_at(player, ["stats", "deaths"], 0) or 0)
    kills = int(_number_at(player, ["stats", "kills"], 0) or 0)
    denom = kills + deaths
    efficiency = round(kills / denom, 4) if denom > 0 else None

    taken_to_die_raw = int(_number_at(player, ["dmg", "taken-to-die"], 0) or 0)
    survived_without_death = deaths == 0 and taken_to_die_raw == 99999
    taken_to_die = None if survived_without_death else taken_to_die_raw

    health_pickups = sum(_item_took(player, item) for item in HEALTH_ITEMS)
    armor_pickups = {
        name: _item_took(player, name)
        for name in ARMOR_ITEMS
    }
    powerups = {
        label: _item_took(player, source_name)
        for label, source_name in POWERUP_ITEMS.items()
    }

    flat_stats = {
        "frags": frags,
        "deaths": deaths,
        "kills": kills,
        "efficiency": efficiency,
        "team_kills": int(_number_at(player, ["stats", "tk"], 0) or 0),
        "spawn_frags": int(_number_at(player, ["stats", "spawn-frags"], 0) or 0),
        "suicides": int(_number_at(player, ["stats", "suicides"], 0) or 0),
        "damage_done": int(_number_at(player, ["dmg", "given"], 0) or 0),
        "damage_taken": int(_number_at(player, ["dmg", "taken"], 0) or 0),
        "team_damage": int(_number_at(player, ["dmg", "team"], 0) or 0),
        "self_damage": int(_number_at(player, ["dmg", "self"], 0) or 0),
        "team_weapon_damage": int(_number_at(player, ["dmg", "team-weapons"], 0) or 0),
        "enemy_weapon_damage": int(_number_at(player, ["dmg", "enemy-weapons"], 0) or 0),
        "taken_to_die": taken_to_die,
        "taken_to_die_raw": taken_to_die_raw,
        "survived_without_death": survived_without_death,
        "xfer_rl": int(_number_at(player, ["xferRL"], 0) or 0),
        "xfer_lg": int(_number_at(player, ["xferLG"], 0) or 0),
        "avg_speed": _number_at(player, ["speed", "avg"], None),
        "max_speed": _number_at(player, ["speed", "max"], None),
        "health_pickups": health_pickups,
        "pill_pickups": _item_took(player, "health_15"),
        "brick_pickups": _item_took(player, "health_25"),
        "mega_pickups": _item_took(player, "health_100"),
        "ya_pickups": armor_pickups["ya"],
        "ra_pickups": armor_pickups["ra"],
        "quad_pickups": powerups["quad"],
        "pent_pickups": powerups["pent"],
        "ring_pickups": powerups["ring"],
        "rl_pickups": _weapon_stat(player, "rl", "pickups", "taken"),
        "rl_drops": _weapon_stat(player, "rl", "pickups", "dropped"),
        "enemy_rl_kills": _weapon_stat(player, "rl", "kills", "enemy"),
        "lg_pickups": _weapon_stat(player, "lg", "pickups", "taken"),
    }

    bot_info = player.get("bot")
    return {
        "slot": slot,
        "id": _identity_key(slot, player),
        "identity": {
            "name": _text_at(player, ["name"], f"player-{slot}"),
            "team": _text_at(player, ["team"], ""),
            "login": _text_at(player, ["login"], ""),
            "ping": _number_at(player, ["ping"], None),
            "top_color": _number_at(player, ["top-color"], None),
            "bottom_color": _number_at(player, ["bottom-color"], None),
            "is_bot": isinstance(bot_info, dict),
            "bot": bot_info if isinstance(bot_info, dict) else None,
        },
        "stats": flat_stats,
        "pickups": {
            "health": {
                "total": health_pickups,
                **{item: _item_took(player, item) for item in HEALTH_ITEMS},
            },
            "armor": armor_pickups,
            "powerups": powerups,
        },
        "weapons": {
            "rl": {
                "pickups_taken": flat_stats["rl_pickups"],
                "dropped": flat_stats["rl_drops"],
                "enemy_kills": flat_stats["enemy_rl_kills"],
            },
            "lg": {
                "pickups_taken": flat_stats["lg_pickups"],
                "dropped": _weapon_stat(player, "lg", "pickups", "dropped"),
                "enemy_kills": _weapon_stat(player, "lg", "kills", "enemy"),
            },
        },
        "sources": _metric_sources(index),
    }


def _team_totals(players: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for player in players:
        team = str(player["identity"].get("team") or "")
        grouped.setdefault(team, []).append(player)

    teams: list[dict[str, Any]] = []
    for team_name in sorted(grouped):
        members = grouped[team_name]
        totals: dict[str, int | float | None] = {}
        for key in (
            "frags",
            "deaths",
            "kills",
            "team_kills",
            "damage_done",
            "damage_taken",
            "enemy_weapon_damage",
            "team_weapon_damage",
            "health_pickups",
            "pill_pickups",
            "brick_pickups",
            "mega_pickups",
            "ya_pickups",
            "ra_pickups",
            "quad_pickups",
            "pent_pickups",
            "ring_pickups",
            "rl_pickups",
            "rl_drops",
            "enemy_rl_kills",
            "lg_pickups",
        ):
            totals[key] = sum(int(p["stats"].get(key) or 0) for p in members)
        denom = int(totals["kills"] or 0) + int(totals["deaths"] or 0)
        totals["efficiency"] = round(int(totals["kills"] or 0) / denom, 4) if denom else None
        avg_speeds = [
            p["stats"].get("avg_speed")
            for p in members
            if isinstance(p["stats"].get("avg_speed"), (int, float))
            and not isinstance(p["stats"].get("avg_speed"), bool)
        ]
        max_speeds = [
            p["stats"].get("max_speed")
            for p in members
            if isinstance(p["stats"].get("max_speed"), (int, float))
            and not isinstance(p["stats"].get("max_speed"), bool)
        ]
        to_die_values = [
            p["stats"].get("taken_to_die")
            for p in members
            if isinstance(p["stats"].get("taken_to_die"), (int, float))
            and not isinstance(p["stats"].get("taken_to_die"), bool)
        ]
        totals["avg_speed"] = round(sum(avg_speeds) / len(avg_speeds), 1) if avg_speeds else None
        totals["max_speed"] = max(max_speeds) if max_speeds else None
        totals["taken_to_die"] = round(sum(to_die_values) / len(to_die_values), 1) if to_die_values else None
        teams.append(
            {
                "name": team_name,
                "player_count": len(members),
                "score": totals["frags"],
                "player_ids": [p["id"] for p in members],
                "totals": totals,
                "score_source": "sum(players[].stats.frags) because KTX JSON has no team score block",
            }
        )
    return teams


def _extract_match(raw: dict[str, Any]) -> tuple[dict[str, Any], str]:
    if isinstance(raw.get("demoInfo"), dict):
        return raw["demoInfo"], "mvd_analyzer.demoInfo"
    return raw, "ktxstats"


def _first_number(*values: int | float | None) -> int | float | None:
    for value in values:
        if value is not None:
            return value
    return None


def normalize_match(raw: dict[str, Any], *, source_path: str | None = None) -> dict[str, Any]:
    """Return canonical `komodobots.ktx_match_stats.v1`.

    The normalizer is deliberately permissive: wrong-mode and partial fixtures
    are returned with warnings instead of raising, so downstream validation can
    explain why a match was skipped.
    """
    if not isinstance(raw, dict):
        raise TypeError("raw KTX stats must be a JSON object")

    match, source_kind = _extract_match(raw)
    warnings: list[str] = []
    if not isinstance(match, dict):
        raise TypeError("KTX stats payload must be an object")

    raw_players = match.get("players")
    if not isinstance(raw_players, list):
        raw_players = []
        warnings.append("match has no players array")

    mode = _text_at(match, ["mode"], None)
    timelimit = _first_number(
        _number_at(match, ["tl"], None),
        _number_at(match, ["timelimit"], None),
        _number_at(raw, ["metadata", "matchSettings", "timelimit"], None),
        _number_at(raw, ["metadata", "serverInfo", "timelimit"], None),
    )
    dm = _first_number(
        _number_at(match, ["dm"], None),
        _number_at(match, ["deathmatch"], None),
        _number_at(raw, ["metadata", "matchSettings", "deathmatch"], None),
        _number_at(raw, ["metadata", "serverInfo", "deathmatch"], None),
    )
    tp = _first_number(
        _number_at(match, ["tp"], None),
        _number_at(match, ["teamplay"], None),
        _number_at(raw, ["metadata", "matchSettings", "teamplay"], None),
        _number_at(raw, ["metadata", "serverInfo", "teamplay"], None),
    )
    if mode not in ("team", "4on4"):
        warnings.append(f"mode is {mode!r}, not KTX team/4on4")
    if dm != 1:
        warnings.append(f"deathmatch dm is {dm!r}, not 1")
    if tp != 2:
        warnings.append(f"teamplay tp is {tp!r}, not 2")
    if _has_path(match, ["tl"]) and _has_path(match, ["fl"]) and match.get("tl") == match.get("fl"):
        warnings.append("KTX fl matches tl; treating fl as reported/possibly echoed, not authoritative fraglimit")

    players = [
        _normalize_player(player if isinstance(player, dict) else {}, idx, warnings)
        for idx, player in enumerate(raw_players)
    ]
    teams = _team_totals(players)

    declared_teams = match.get("teams")
    if not isinstance(declared_teams, list):
        declared_teams = [team["name"] for team in teams]

    return {
        "schema": SCHEMA,
        "source": {
            "kind": source_kind,
            "path": source_path,
            "raw_version": match.get("version"),
            "notes": [
                "KTX 4v4 is identified by team mode plus dm/tp/player/team shape.",
                "Optional item/weapon blocks omitted by KTX are normalized as zero.",
            ],
        },
        "match": {
            "date": match.get("date"),
            "map": match.get("map"),
            "hostname": match.get("hostname"),
            "ip": match.get("ip"),
            "port": match.get("port"),
            "matchtag": match.get("matchtag"),
            "mode": mode,
            "timelimit": timelimit,
            "fraglimit_reported": _number_at(match, ["fl"], None),
            "deathmatch": dm,
            "teamplay": tp,
            "duration": _number_at(match, ["duration"], None),
            "demo": match.get("demo"),
            "teams_declared": declared_teams,
            "is_ktx_teamplay": mode in ("team", "4on4") and dm == 1 and tp == 2,
        },
        "players": players,
        "teams": teams,
        "warnings": warnings,
    }


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def summarize(data: dict[str, Any]) -> str:
    lines = [
        f"{data['match'].get('map') or '?'} {data['match'].get('mode') or '?'} "
        f"duration={data['match'].get('duration')} players={len(data['players'])}",
    ]
    for team in data["teams"]:
        lines.append(
            f"{team['name'] or '(no team)'} score={team['score']} "
            f"players={team['player_count']} dmg={team['totals']['damage_done']}"
        )
    if data["warnings"]:
        lines.append("warnings: " + "; ".join(data["warnings"]))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Normalize KTX/mvd_analyzer match stats JSON.")
    parser.add_argument("input", type=Path, help="raw KTX stats JSON or analyzer JSON containing demoInfo")
    parser.add_argument("--out", type=Path, help="write canonical JSON to this path")
    parser.add_argument("--summary", action="store_true", help="print a compact match/team summary")
    args = parser.parse_args(argv)

    data = normalize_match(load_json(args.input), source_path=str(args.input))
    text = json.dumps(data, indent=2, sort_keys=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    if args.summary:
        print(summarize(data), file=sys.stderr if not args.out else sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
