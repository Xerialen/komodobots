#!/usr/bin/env python3
"""Build the BotLab fixed-roster 4v4 validation ledger.

`ktx_match_stats.py` is the generic KTX/casting core. This builder adds the
BotLab-specific contract:

* dm3, KTX team mode, dm=1, tp=2.
* exactly eight players split across the two roster-declared teams, four each.
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

# Roster roles that belong to the "leap" team (our bot). Everything else on the
# eight-player roster is a stock skill-20 Frogbot "control". The leap team is the
# roster team that contains at least one of these roles; the other team is frog.
# This keeps the existing one-komodobot validation roster working (its komodobot
# team is the leap team) while also supporting a full four-leap-vs-four-frog run
# (docs/18 T0.1: "team leap vs team frog, 4 vs 4").
LEAP_ROLES = ("leap", "komodobot")

# R-T damage.matrix gate (docs/18 Phase 0, docs/15): a frog-vs-leap 4v4 is only
# honest when bots actually fight the enemy and almost never their own team.
# "enemy damage > 0" and "intra-team damage ~= 0". intra-team damage is the
# canonical mvdanalyzer dmg.team field (damage dealt to a teammate); skill-20
# Frogbots on teamplay 2 should deal none, so the default tolerance is 0 but is
# configurable for robustness against rare engine rounding.
DEFAULT_INTRA_TEAM_DAMAGE_TOLERANCE = 0

STATS_FILENAMES = (
    "ktxstats.json",
    "stats.json",
    "match.json",
    "analysis.json",
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


def _count_teams(players: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for player in players:
        if not isinstance(player, dict):
            continue
        team = str(player.get("team") or "")
        counts[team] = counts.get(team, 0) + 1
    return counts


def _is_two_teams_four_each(team_counts: dict[str, int]) -> bool:
    return len(team_counts) == 2 and sorted(team_counts.values()) == [4, 4] and "" not in team_counts


def _roster_team_counts(roster: dict[str, Any] | None) -> dict[str, int]:
    return _count_teams(_roster_players(roster))


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

    komodo_count = 0
    leap_count = 0
    control_count = 0
    skill20_controls = 0
    team_counts = _count_teams(players)
    for p in players:
        if not isinstance(p, dict):
            reasons.append("roster_player_not_object")
            continue
        role = p.get("role")
        if role == "komodobot":
            komodo_count += 1
        elif role == "leap":
            leap_count += 1
        elif role == "control":
            control_count += 1
            if p.get("bot_kind") == "frogbot" and p.get("bot_skill") == 20:
                skill20_controls += 1

    if not _is_two_teams_four_each(team_counts):
        reasons.append("roster_not_two_fixed_teams_4_each")

    # Two supported shapes (docs/18 T0.1): one komodobot + seven skill-20 frogbot
    # controls, OR four leap bots + four skill-20 frogbot controls. Both keep
    # exactly two fixed teams of four; the leap team is whichever team holds the
    # komodobot/leap roles.
    one_komodobot_shape = (komodo_count == 1 and leap_count == 0
                           and control_count == 7 and skill20_controls == 7)
    four_leap_shape = (leap_count == 4 and komodo_count == 0
                       and control_count == 4 and skill20_controls == 4)
    if not (one_komodobot_shape or four_leap_shape):
        reasons.append("roster_not_one_komodobot_or_four_leap_vs_four_skill20_frogbots")
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
    if not _is_two_teams_four_each(team_counts):
        reasons.append("teams_not_two_teams_4_each")

    roster_counts = _roster_team_counts(roster)
    if roster_counts and team_counts != roster_counts:
        reasons.append("teams_do_not_match_roster_teams")

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


def _player_role(player: dict[str, Any]) -> str:
    roster = player.get("roster")
    if isinstance(roster, dict):
        return str(roster.get("role") or "unknown")
    return "unknown"


def _player_team(player: dict[str, Any]) -> str:
    roster = player.get("roster")
    if isinstance(roster, dict) and roster.get("team"):
        return str(roster["team"])
    return str(player.get("identity", {}).get("team") or "")


def _is_leap_player(player: dict[str, Any]) -> bool:
    return _player_role(player) in LEAP_ROLES


def _leap_frog_teams(players: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    """Resolve (leap_team, frog_team) from roster roles.

    Leap team = the team that contains any leap/komodobot player. Frog team =
    the single other team. Returns (None, None) when the split is ambiguous
    (no leap role found, leap players spread across both teams, or not exactly
    two teams), so the caller can record a reason instead of a bogus margin.
    """
    teams = sorted({_player_team(p) for p in players if _player_team(p)})
    if len(teams) != 2:
        return None, None
    leap_teams = {_player_team(p) for p in players if _is_leap_player(p) and _player_team(p)}
    if len(leap_teams) != 1:
        return None, None
    leap_team = next(iter(leap_teams))
    frog_team = next(t for t in teams if t != leap_team)
    return leap_team, frog_team


def _team_frags(players: list[dict[str, Any]], team: str) -> int:
    return sum(
        int(p["stats"].get("frags") or 0)
        for p in players
        if _player_team(p) == team
    )


def _bench_margin(game: dict[str, Any]) -> dict[str, Any]:
    """Per-game leap-minus-frog frag margin (docs/18 T0.1).

    Win = total frags. The margin is the leap team's total frags minus the frog
    team's total frags for this single game; positive means leap won this game.
    """
    players = game["players"]
    leap_team, frog_team = _leap_frog_teams(players)
    if leap_team is None or frog_team is None:
        return {
            "resolved": False,
            "reason": "could_not_resolve_leap_vs_frog_teams",
            "leap_team": None,
            "frog_team": None,
            "leap_frags": None,
            "frog_frags": None,
            "frag_margin": None,
        }
    leap_frags = _team_frags(players, leap_team)
    frog_frags = _team_frags(players, frog_team)
    return {
        "resolved": True,
        "leap_team": leap_team,
        "frog_team": frog_team,
        "leap_frags": leap_frags,
        "frog_frags": frog_frags,
        "frag_margin": leap_frags - frog_frags,
        "leap_won": leap_frags > frog_frags,
        "metric": "win=total_frags; margin=leap_team_frags-frog_team_frags",
    }


def _damage_matrix(
    game: dict[str, Any],
    *,
    intra_team_tolerance: int | float = DEFAULT_INTRA_TEAM_DAMAGE_TOLERANCE,
) -> dict[str, Any]:
    """R-T damage.matrix gate for one game (docs/18 Phase 0, docs/15).

    Combat guard is damage DONE (canonical mvdanalyzer `dmg.given`), never
    accuracy. The gate is green when the bots actually fought the enemy
    (enemy_damage > 0) and almost never their own team (intra_team_damage,
    i.e. sum of `dmg.team`, within tolerance). `self_damage` is reported for
    transparency but is not gated on: rocket splash onto oneself is not a
    teammate-damage event.
    """
    players = game["players"]
    enemy_damage = sum(int(p["stats"].get("damage_done") or 0) for p in players)
    intra_team_damage = sum(int(p["stats"].get("team_damage") or 0) for p in players)
    self_damage = sum(int(p["stats"].get("self_damage") or 0) for p in players)

    reasons: list[str] = []
    if enemy_damage <= 0:
        reasons.append("no_enemy_damage")
    if abs(intra_team_damage) > intra_team_tolerance:
        reasons.append("intra_team_damage_above_tolerance")

    return {
        "enemy_damage": enemy_damage,
        "intra_team_damage": intra_team_damage,
        "self_damage": self_damage,
        "intra_team_tolerance": intra_team_tolerance,
        "gate_pass": not reasons,
        "reasons": reasons,
        "source": "canonical mvdanalyzer dmg.given (enemy) / dmg.team (intra-team)",
        "note": "combat guard is damage done, never accuracy",
    }


def _bench_aggregate(games: list[dict[str, Any]]) -> dict[str, Any]:
    """Best-of-N leap-frog frag margin across all valid games (docs/18 T0.1).

    "Bench prints leap frags minus frog frags over best-of-N." This rolls the
    per-game margins into the single bench number plus the per-game series and
    the overall R-T damage.matrix gate verdict.
    """
    resolved = [g for g in games if g.get("bench", {}).get("resolved")]
    margins = [int(g["bench"]["frag_margin"]) for g in resolved]
    leap_wins = sum(1 for g in resolved if g["bench"].get("leap_won"))
    gate_games = [g for g in games if "damage_matrix" in g]
    gate_pass = bool(gate_games) and all(g["damage_matrix"]["gate_pass"] for g in gate_games)
    n = len(margins)
    return {
        "schema": "komodobots.bench_frag_margin.v1",
        "games_scored": n,
        "leap_frag_margin_total": sum(margins) if margins else None,
        "leap_frag_margin_mean": round(sum(margins) / n, 4) if n else None,
        "leap_wins": leap_wins,
        "frog_wins": n - leap_wins if n else 0,
        "per_game": [
            {
                "run_id": g["run_id"],
                "leap_team": g["bench"]["leap_team"],
                "frog_team": g["bench"]["frog_team"],
                "leap_frags": g["bench"]["leap_frags"],
                "frog_frags": g["bench"]["frog_frags"],
                "frag_margin": g["bench"]["frag_margin"],
                "damage_matrix_gate_pass": g.get("damage_matrix", {}).get("gate_pass"),
            }
            for g in resolved
        ],
        "damage_matrix_gate_pass": gate_pass,
        "metric": "win=total_frags; combat_guard=damage_done; accuracy=report-only",
    }


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
        game["bench"] = _bench_margin(game)
        game["damage_matrix"] = _damage_matrix(game)
        games.append(game)
        previous_valid = game

    return {
        "schema": SCHEMA,
        "metrics": list(VALIDATION_METRICS),
        "bench": _bench_aggregate(games),
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
    lines = ["run_id               | map mode duration | leap-frog margin | dmg.matrix gate"]
    for game in data["games"]:
        bench = game.get("bench", {})
        margin = bench.get("frag_margin")
        margin_text = (
            f"{bench.get('leap_frags')}-{bench.get('frog_frags')}={'+' if (margin or 0) > 0 else ''}{margin}"
            if bench.get("resolved") else "unresolved"
        )
        gate = game.get("damage_matrix", {})
        gate_text = "green" if gate.get("gate_pass") else f"RED {gate.get('reasons')}"
        lines.append(
            f"{game['run_id']:20s} | {game['match'].get('map') or '?':3s} "
            f"{game['match'].get('mode') or '?':4s} {str(game['match'].get('duration')):>8s} | "
            f"{margin_text:16s} | {gate_text}"
        )
    bench = data.get("bench", {})
    lines.append(
        f"bench(best-of-{bench.get('games_scored')}): "
        f"leap-frog margin total={bench.get('leap_frag_margin_total')} "
        f"mean={bench.get('leap_frag_margin_mean')} "
        f"leap_wins={bench.get('leap_wins')}/{bench.get('games_scored')} "
        f"damage.matrix gate={'green' if bench.get('damage_matrix_gate_pass') else 'RED'}"
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
