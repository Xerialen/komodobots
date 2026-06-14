#!/usr/bin/env python3
"""Read-only ingest for real KTX games used in commentary/casting.

This is intentionally a thin wrapper over `ktx_match_stats.normalize_match`.
It does not know about BotLab fixed rosters, does not require bots, and does
not import or call any control/runner mutation path.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import ktx_match_stats as kms


def ingest(raw: dict[str, Any], *, source_path: str | None = None) -> dict[str, Any]:
    data = kms.normalize_match(raw, source_path=source_path)
    data["source"]["notes"].append("Read-only casting ingest; no BotLab fixed-roster fields are required.")
    data["source"]["casting_read_only"] = True
    return data


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def summarize(data: dict[str, Any]) -> str:
    match = data["match"]
    lines = [
        f"{match.get('map') or '?'} {match.get('mode') or '?'} "
        f"{match.get('duration') or '?'}s teams={len(data['teams'])} players={len(data['players'])}",
    ]
    for team in data["teams"]:
        top = sorted(
            [p for p in data["players"] if p["identity"].get("team") == team["name"]],
            key=lambda p: p["stats"]["frags"],
            reverse=True,
        )[:2]
        top_text = ", ".join(f"{p['identity']['name']} {p['stats']['frags']}" for p in top)
        lines.append(f"{team['name']}: {team['score']} ({top_text})")
    if data["warnings"]:
        lines.append("warnings: " + "; ".join(data["warnings"]))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only normalize a real KTX 4v4/casting stats JSON.")
    parser.add_argument("input", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)

    data = ingest(load_json(args.input), source_path=str(args.input))
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
