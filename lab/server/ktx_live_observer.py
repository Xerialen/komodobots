#!/usr/bin/env python3
"""Conservative read-only live observer state for KTX/BotLab/casting.

The post-game KTX stats normalizer is authoritative for combat/economy values.
This module only models values that can be safely observed live without server
mutation and without depending on experimental bot/moveprobe patches:

* connection/status, map, timer/server time,
* team names/scores when an upstream source provides them,
* player identity/team/frags/deaths when an upstream source provides them.

Everything emitted here is `provisional: true` until final KTX post-game stats
arrive. Damage, item pickups, taken-to-die, efficiency, and weapon counters are
post-game-only unless KTX later exposes a read-only event stream for them.
"""

from __future__ import annotations

import logging
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


LOGGER = logging.getLogger(__name__)
SCHEMA = "komodobots.ktx_live_observer.v1"
SAFE_PLAYER_FIELDS = ("slot", "name", "team", "frags", "deaths", "ping")
SAFE_TEAM_FIELDS = ("name", "score")
POST_GAME_ONLY_FIELDS = frozenset(
    {
        "efficiency",
        "damage_done",
        "damage_taken",
        "enemy_weapon_damage",
        "team_weapon_damage",
        "team_kills",
        "health_pickups",
        "quad_pickups",
        "pent_pickups",
        "ring_pickups",
        "rl_pickups",
        "rl_drops",
        "enemy_rl_kills",
        "taken_to_die",
    }
)

OPTIONAL_KTX_EVENT_STREAM_PROPOSAL = {
    "name": "ktx_live_stats_event_stream",
    "default": "disabled",
    "direction": "server-to-observer-read-only",
    "overhead": "low-frequency scoreboard/event deltas only",
    "exclusions": "no bot/moveprobe behavior changes; no control commands",
}


def _safe_number(value: Any) -> int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    return None


def _safe_text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _filter_player(raw: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
    for key in POST_GAME_ONLY_FIELDS & set(raw):
        warnings.append(f"ignored post-game-only live player field: {key}")
    return {
        "slot": _safe_number(raw.get("slot")),
        "name": _safe_text(raw.get("name")),
        "team": _safe_text(raw.get("team")),
        "frags": _safe_number(raw.get("frags")),
        "deaths": _safe_number(raw.get("deaths")),
        "ping": _safe_number(raw.get("ping")),
        "provisional": True,
    }


def _filter_team(raw: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
    for key in POST_GAME_ONLY_FIELDS & set(raw):
        warnings.append(f"ignored post-game-only live team field: {key}")
    return {
        "name": _safe_text(raw.get("name")),
        "score": _safe_number(raw.get("score")),
        "provisional": True,
    }


def normalize_live_frame(frame: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(frame, dict):
        raise TypeError("live frame must be a JSON object")
    warnings: list[str] = []
    for key in POST_GAME_ONLY_FIELDS & set(frame):
        warnings.append(f"ignored post-game-only live match field: {key}")

    teams_raw = frame.get("teams") if isinstance(frame.get("teams"), list) else []
    players_raw = frame.get("players") if isinstance(frame.get("players"), list) else []
    return {
        "schema": SCHEMA,
        "source": {
            "kind": str(frame.get("source") or "read-only-live-observer"),
            "provisional": True,
            "final": False,
        },
        "sequence": _safe_number(frame.get("sequence")),
        "received_at": _safe_text(frame.get("received_at")),
        "status": _safe_text(frame.get("status") or "live"),
        "stale": False,
        "match": {
            "id": _safe_text(frame.get("match_id")),
            "map": _safe_text(frame.get("map")),
            "mode": _safe_text(frame.get("mode")),
            "server_time": _safe_number(frame.get("server_time")),
            "clock": _safe_number(frame.get("clock")),
            "duration": _safe_number(frame.get("duration")),
            "provisional": True,
        },
        "teams": [_filter_team(team, warnings) for team in teams_raw if isinstance(team, dict)],
        "players": [_filter_player(player, warnings) for player in players_raw if isinstance(player, dict)],
        "unavailable_until_final": sorted(POST_GAME_ONLY_FIELDS),
        "warnings": warnings,
    }


@dataclass
class LiveObserverState:
    """Holds the latest provisional frame and ignores stale reconnect frames."""

    snapshot: dict[str, Any] | None = None
    last_sequence: int | float | None = None
    stale_frames: int = 0
    warnings: list[str] = field(default_factory=list)

    def apply_frame(self, frame: dict[str, Any]) -> dict[str, Any]:
        candidate = normalize_live_frame(frame)
        seq = candidate.get("sequence")
        if (
            self.last_sequence is not None
            and seq is not None
            and isinstance(seq, (int, float))
            and seq < self.last_sequence
        ):
            self.stale_frames += 1
            self.warnings.append(f"ignored stale live frame sequence={seq}")
            if self.snapshot is not None:
                self.snapshot.setdefault("warnings", []).append(f"ignored stale live frame sequence={seq}")
                return self.snapshot
        if isinstance(seq, (int, float)):
            self.last_sequence = seq
        self.snapshot = candidate
        return candidate

    def mark_disconnected(self) -> dict[str, Any]:
        if self.snapshot is None:
            self.snapshot = {
                "schema": SCHEMA,
                "source": {"kind": "read-only-live-observer", "provisional": True, "final": False},
                "sequence": None,
                "status": "disconnected",
                "stale": True,
                "match": {"id": None, "map": None, "mode": None, "server_time": None, "clock": None, "duration": None, "provisional": True},
                "teams": [],
                "players": [],
                "unavailable_until_final": sorted(POST_GAME_ONLY_FIELDS),
                "warnings": ["observer disconnected before first frame"],
            }
        else:
            self.snapshot["status"] = "disconnected"
            self.snapshot["stale"] = True
            self.snapshot.setdefault("warnings", []).append("observer disconnected; live values are stale")
        return self.snapshot


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: python lab/server/ktx_live_observer.py <live-frame.json>")
        return 2
    path = Path(args[0])
    data = normalize_live_frame(json.loads(path.read_text(encoding="utf-8")))
    print(json.dumps(data, indent=2, sort_keys=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
