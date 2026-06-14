#!/usr/bin/env python3
"""Build the BotLab fixed-roster 4v4 validation ledger.

`ktx_match_stats.py` is the generic KTX/casting core. This builder adds the
BotLab-specific contract:

* dm3, KTX team mode, dm=1, tp=2.
* exactly eight players split as Team A / Team B, four each.
* one stable Komodobot slot plus seven static skill-20 Frogbot controls,
  recorded before the match in a roster-intent artifact.
* minimum five-minute completed match.
* deltas are computed against the previous valid game only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import ktx_match_stats as kms

SCHEMA = "komodobots.4v4_validation.v1"
ROSTER_SCHEMA = "komodobots.4v4_roster_intent.v1"
DEFAULT_RUNS_DIR = Path("artifacts") / "4v4-validation-runs"
DEFAULT_OUT = Path("artifacts") / "records" / "4v4-validation.json"

STATS_FILENAMES = (
    "analysis.json",
    "ktxstats.json",
    "stats.json",
    "match.json",
)
ROSTER_FILENAMES = (
    "4v4-roster.json",
    "roster.json",
)
VALIDATION_METRICS = (
    "frags",
    "deaths",
    "kills",
    "efficiency",
    "team_kills",
    "damage_done",
    "damage_taken",
    "enemy_weapon_damage",
    "team_weapon_damage",
    "health_pickups",
    "quad_pickups",
    "pent_pickups",
    "ring_pickups",
    "rl_pickups",
    "rl_drops",
    "enemy_rl_kills",
    "taken_to_die",
)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _find_first(run_dir: Path, names: tuple[str, ...]) -> Path | None:
    for name in names:
        path = run_dir / name
        if path.is_file():
            return path
    return None


def _run_id(run_dir: Path, roster: dict[str, Any] | None, match: dict[str, Any] | None) -> str:
    for source in (roster, match):
        if isinstance(source, dict) and source.get("run_id"):
            return str(source["run_id"])
    return run_dir.name


def _roster_players(roster: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(roster, dict):
        return []
    players = roster.get("players")
    return players if isinstance(players, list) else []


def _roster_by_slot(roster: dict[str, Any] | None) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for p in _roster_players(roster):
        if not isinstance(p, dict):
            continue
        slot = p.get("slot")
        if isinstance(slot, int) and not isinstance(slot, bool):
            out[slot] = p
    return out


def _roster_summary(roster: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(roster, dict):
        return None
    players = _roster_players(roster)
    komodo = [p for p in players if isinstance(p, dict) and p.get("role") == "komodobot"]
    return {
        "schema": roster.get("schema"),
        "run_id": roster.get("run_id"),
        "map": roster.get("map"),
        "mode": roster.get("mode"),
        "deathmatch": roster.get("deathmatch"),
        "teamplay": roster.get("teamplay"),
        "timelimit": roster.get("timelimit"),
        "controller_version": roster.get("controller_version"),
        "komodobot_slot": roster.get("komodobot_slot") if roster.get("komodobot_slot") is not None
        else (komodo[0].get("slot") if komodo else None),
        "players": players,
    }


def _validate_roster(roster: dict[str, Any] | None) -> list[str]:
    reasons: list[str] = []
    if not isinstance(roster, dict):
        return ["missing_roster_intent"]
    if roster.get("schema") != ROSTER_SCHEMA:
        reasons.append("wrong_roster_schema")

    players = _roster_players(roster)
    if len(players) != 8:
        reasons.append("roster_not_eight_players")

    slots = [p.get("slot") for p in players if isinstance(p, dict)]
    if sorted(slots) != list(range(1, 9)):
        reasons.append("roster_slots_not_1_through_8")

    team_counts: dict[str, int] = {}
    komodo_count = 0
    control_count = 0
    skill20_controls = 0
    for p in players:
        if not isinstance(p, dict):
            reasons.append("roster_player_not_object")
            continue
        team = str(p.get("team") or "")
        team_counts[team] = team_counts.get(team, 0) + 1
        if p.get("role") == "komodobot":
            komodo_count += 1
        elif p.get("role") == "control":
            control_count += 1
            if p.get("bot_kind") == "frogbot" and p.get("bot_skill") == 20:
                skill20_controls += 1

    if team_counts != {"Team A": 4, "Team B": 4}:
        reasons.append("roster_not_team_a_team_b_4_each")
    if komodo_count != 1:
        reasons.append("roster_must_have_one_komodobot")
    if control_count != 7 or skill20_controls != 7:
        reasons.append("roster_controls_must_be_seven_skill20_frogbots")
    return reasons


def validate_match(normalized: dict[str, Any], roster: dict[str, Any] | None) -> list[str]:
    """Return BotLab fixed-roster invalid reasons; empty means valid."""
    reasons: list[str] = []
    match = normalized["match"]

    if match.get("map") != "dm3":
        reasons.append("map_not_dm3")
    if match.get("mode") not in ("team", "4on4"):
        reasons.append("ktx_mode_not_team")
    if match.get("deathmatch") != 1:
        reasons.append("deathmatch_not_1")
    if match.get("teamplay") != 2:
        reasons.append("teamplay_not_2")
    duration = match.get("duration")
    if not isinstance(duration, (int, float)) or duration < 300:
        reasons.append("under_minimum_duration")

    players = normalized["players"]
    if len(players) != 8:
        reasons.append("player_count_not_8")

    team_counts = {team["name"]: team["player_count"] for team in normalized["teams"]}
    if team_counts != {"Team A": 4, "Team B": 4}:
        reasons.append("teams_not_team_a_team_b_4_each")

    reasons.extend(_validate_roster(roster))
    return sorted(set(reasons))


def _with_roster_fields(player: dict[str, Any], roster_by_slot: dict[int, dict[str, Any]]) -> dict[str, Any]:
    slot = int(player["slot"])
    intent = roster_by_slot.get(slot, {})
    stable_id = str(intent.get("id") or intent.get("name") or player["id"])
    enriched = dict(player)
    enriched["roster"] = {
        "slot": slot,
        "id": stable_id,
        "name": intent.get("name") or player["identity"].get("name"),
        "team": intent.get("team") or player["identity"].get("team"),
        "role": intent.get("role") or "unknown",
        "bot_kind": intent.get("bot_kind"),
        "bot_skill": intent.get("bot_skill"),
        "controller_version": intent.get("controller_version"),
        "tracked": intent.get("role") == "komodobot",
    }
    return enriched


def _version_scope(curr: dict[str, Any], prev: dict[str, Any] | None) -> str:
    if prev is None:
        return "no_previous"
    cver = curr.get("roster", {}).get("controller_version")
    pver = prev.get("roster", {}).get("controller_version")
    return "same-version" if cver == pver else "cross-version"


def _numeric(value: Any) -> int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    return None


def _attach_deltas(game: dict[str, Any], previous: dict[str, Any] | None) -> None:
    previous_by_slot = {
        int(p["slot"]): p
        for p in previous.get("players", [])  # type: ignore[union-attr]
    } if previous else {}
    game["previous_valid_run_id"] = previous.get("run_id") if previous else None
    for player in game["players"]:
        prev = previous_by_slot.get(int(player["slot"]))
        scope = _version_scope(player, prev)
        deltas: dict[str, dict[str, Any]] = {}
        for metric in VALIDATION_METRICS:
            curr_value = _numeric(player["stats"].get(metric))
            prev_value = _numeric(prev["stats"].get(metric)) if prev else None
            deltas[metric] = {
                "current": curr_value,
                "previous": prev_value,
                "value": (round(curr_value - prev_value, 4)
                          if curr_value is not None and prev_value is not None else None),
                "scope": scope,
            }
        player["deltas"] = deltas


def _game_from_artifacts(run_dir: Path, stats_path: Path, roster_path: Path | None) -> tuple[dict[str, Any], list[str]]:
    normalized = kms.normalize_match(_read_json(stats_path), source_path=str(stats_path))
    roster = _read_json(roster_path) if roster_path else None
    run_id = _run_id(run_dir, roster, normalized["match"])
    roster_by_slot = _roster_by_slot(roster)
    players = [_with_roster_fields(p, roster_by_slot) for p in normalized["players"]]
    demo_name = normalized["match"].get("demo")
    game = {
        "run_id": run_id,
        "artifact_dir": str(run_dir),
        "stats_artifact": str(stats_path),
        "roster_artifact": str(roster_path) if roster_path else None,
        "demo": {
            "name": demo_name,
            "url": (demo_name if isinstance(demo_name, str) and demo_name.startswith("/")
                    else f"/demos/files/non-games/lab/Komodobots/4v4/{demo_name}")
            if isinstance(demo_name, str) and demo_name else None,
        },
        "match": normalized["match"],
        "teams": normalized["teams"],
        "players": players,
        "roster": _roster_summary(roster),
        "normalizer_warnings": normalized["warnings"],
    }
    return game, validate_match({**normalized, "players": players}, roster)


def build(runs_dir: Path) -> dict[str, Any]:
    scanned = 0
    skipped: dict[str, int] = {}
    games: list[dict[str, Any]] = []
    invalid_games: list[dict[str, Any]] = []

    run_dirs = sorted(p for p in runs_dir.iterdir() if p.is_dir()) if runs_dir.is_dir() else []
    previous_valid: dict[str, Any] | None = None

    for run_dir in run_dirs:
        scanned += 1
        stats_path = _find_first(run_dir, STATS_FILENAMES)
        if stats_path is None:
            skipped["missing_stats_artifact"] = skipped.get("missing_stats_artifact", 0) + 1
            invalid_games.append({
                "run_id": run_dir.name,
                "artifact_dir": str(run_dir),
                "reasons": ["missing_stats_artifact"],
            })
            continue
        roster_path = _find_first(run_dir, ROSTER_FILENAMES)
        try:
            game, reasons = _game_from_artifacts(run_dir, stats_path, roster_path)
        except (OSError, json.JSONDecodeError, TypeError, KeyError) as exc:
            reason = "artifact_parse_failed"
            skipped[reason] = skipped.get(reason, 0) + 1
            invalid_games.append({
                "run_id": run_dir.name,
                "artifact_dir": str(run_dir),
                "reasons": [reason],
                "detail": f"{type(exc).__name__}: {exc}",
            })
            continue
        if reasons:
            for reason in reasons:
                skipped[reason] = skipped.get(reason, 0) + 1
            invalid_games.append({
                "run_id": game["run_id"],
                "artifact_dir": game["artifact_dir"],
                "match": game.get("match"),
                "reasons": reasons,
            })
            continue
        _attach_deltas(game, previous_valid)
        games.append(game)
        previous_valid = game

    return {
        "schema": SCHEMA,
        "metrics": list(VALIDATION_METRICS),
        "games": games,
        "invalid_games": invalid_games,
        "provenance": {
            "runs_dir": str(runs_dir),
            "runs_scanned": scanned,
            "valid_games": len(games),
            "skipped": dict(sorted(skipped.items())),
            "stats_filenames": list(STATS_FILENAMES),
            "roster_filenames": list(ROSTER_FILENAMES),
            "source_core": kms.SCHEMA,
        },
    }


def summarize(data: dict[str, Any]) -> str:
    lines = ["run_id               | map mode duration | teams | komodo frags delta"]
    for game in data["games"]:
        komodo = next((p for p in game["players"] if p["roster"]["role"] == "komodobot"), None)
        delta = komodo["deltas"]["frags"]["value"] if komodo else None
        lines.append(
            f"{game['run_id']:20s} | {game['match'].get('map') or '?':3s} "
            f"{game['match'].get('mode') or '?':4s} {str(game['match'].get('duration')):>8s} | "
            f"{len(game['teams']):5d} | "
            f"{komodo['stats']['frags'] if komodo else '-'} {delta if delta is not None else '-'}"
        )
    p = data["provenance"]
    lines.append(f"runs: scanned={p['runs_scanned']} valid={p['valid_games']} skipped={p['skipped']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build 4v4-validation.json from BotLab run artifacts.")
    parser.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)

    data = build(args.runs_dir)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    if args.summary:
        print(summarize(data))
    else:
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
