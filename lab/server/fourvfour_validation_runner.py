#!/usr/bin/env python3
"""Prepare fixed-roster 4v4 validation run artifacts and control plans.

This module does not contact a server. It builds the roster-intent artifact the
ledger requires and a small control-plan JSON showing the bridge requests needed
to create the lab-only validation lobby. The actual mutation still goes through
`control_bridge.py`, which enforces the lab-port and production-port denials.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import control_bridge as cb
from fourvfour_validation_build import ROSTER_SCHEMA

PLAN_SCHEMA = "komodobots.4v4_validation_plan.v1"
DEFAULT_OUT_ROOT = Path("artifacts") / "4v4-validation-runs"
DEFAULT_CONTROLLER_VERSION = "komodobot-dev"


def utc_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _slot_name(slot: int, komodobot_slot: int) -> str:
    if slot == komodobot_slot:
        return "komodo-dev"
    side = "a" if slot <= 4 else "b"
    return f"{side}-control-{slot}"


def build_roster_intent(
    *,
    run_id: str,
    controller_version: str = DEFAULT_CONTROLLER_VERSION,
    komodobot_slot: int = 1,
    map_name: str = "dm3",
    timelimit: int = 5,
) -> dict[str, Any]:
    if not 1 <= komodobot_slot <= 8:
        raise ValueError("komodobot_slot must be in 1..8")
    if cb.validate_map_name(map_name) is None:
        raise ValueError(f"invalid map name: {map_name!r}")
    if not isinstance(timelimit, int) or timelimit < 5:
        raise ValueError("timelimit must be an integer >= 5")

    players: list[dict[str, Any]] = []
    for slot in range(1, 9):
        team = "Team A" if slot <= 4 else "Team B"
        is_komodo = slot == komodobot_slot
        players.append(
            {
                "slot": slot,
                "id": f"slot-{slot}",
                "name": _slot_name(slot, komodobot_slot),
                "team": team,
                "role": "komodobot" if is_komodo else "control",
                "bot_kind": "komodobot" if is_komodo else "frogbot",
                "bot_skill": 20,
                "controller_version": controller_version if is_komodo else "frogbot-20",
            }
        )

    return {
        "schema": ROSTER_SCHEMA,
        "run_id": run_id,
        "map": map_name,
        "mode": "4on4",
        "deathmatch": 1,
        "teamplay": 2,
        "timelimit": timelimit,
        "controller_version": controller_version,
        "komodobot_slot": komodobot_slot,
        "players": players,
    }


def build_control_plan(
    *,
    run_id: str,
    port: int,
    map_name: str = "dm3",
) -> dict[str, Any]:
    safe_port = cb.validate_lab_port(port)
    if safe_port is None:
        raise ValueError(f"port {port!r} is not in the lab allowlist")
    if cb.validate_map_name(map_name) is None:
        raise ValueError(f"invalid map name: {map_name!r}")
    return {
        "schema": PLAN_SCHEMA,
        "run_id": run_id,
        "port": safe_port,
        "map": map_name,
        "readiness": "dry-run",
        "control_requests": [
            {"op": "session_start", "map": map_name},
            {"op": "game_command", "action": "4v4_validation_prepare"},
        ],
        "expected_bridge_steps": [
            {"kind": kind, "line": line}
            for kind, line in cb.VALIDATION_4V4_STEPS
        ],
        "safety": {
            "lab_ports": list(cb.ALLOWED_LAB_PORTS),
            "denied_ports": list(cb.DENIED_PORTS),
            "production_mutation": "forbidden by control_bridge.validate_lab_port",
        },
    }


def write_run_artifacts(
    out_dir: Path,
    *,
    run_id: str,
    port: int,
    controller_version: str = DEFAULT_CONTROLLER_VERSION,
    komodobot_slot: int = 1,
    map_name: str = "dm3",
    timelimit: int = 5,
) -> dict[str, Path]:
    roster = build_roster_intent(
        run_id=run_id,
        controller_version=controller_version,
        komodobot_slot=komodobot_slot,
        map_name=map_name,
        timelimit=timelimit,
    )
    plan = build_control_plan(run_id=run_id, port=port, map_name=map_name)
    out_dir.mkdir(parents=True, exist_ok=True)
    roster_path = out_dir / "4v4-roster.json"
    plan_path = out_dir / "4v4-plan.json"
    roster_path.write_text(json.dumps(roster, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    plan_path.write_text(json.dumps(plan, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    return {"roster": roster_path, "plan": plan_path}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare fixed-roster 4v4 validation artifacts.")
    parser.add_argument("--run-id", default=utc_run_id())
    parser.add_argument("--port", type=int, default=28599)
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument("--controller-version", default=DEFAULT_CONTROLLER_VERSION)
    parser.add_argument("--komodobot-slot", type=int, default=1)
    parser.add_argument("--map", dest="map_name", default="dm3")
    parser.add_argument("--timelimit", type=int, default=5)
    args = parser.parse_args(argv)

    out_dir = args.out_root / args.run_id
    paths = write_run_artifacts(
        out_dir,
        run_id=args.run_id,
        port=args.port,
        controller_version=args.controller_version,
        komodobot_slot=args.komodobot_slot,
        map_name=args.map_name,
        timelimit=args.timelimit,
    )
    print(f"wrote {paths['roster']}")
    print(f"wrote {paths['plan']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
