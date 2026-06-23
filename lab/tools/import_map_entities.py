#!/usr/bin/env python3
"""Import static map-entity data from mvd_analyzer into BotLab public data.

The source of truth is the upstream mvd_analyzer map entity corpus:

    mvd-analytics/mapents/data/<map>.json

This importer copies a small, explicit map set into:

    lab/dashboard/public/data/map_entities/

It keeps the upstream per-map JSON payloads byte-for-byte, then writes a compact
index with provenance and entity/type counts.  The committed files are consumed
as a stable dashboard data layer; the dashboard does not reach into a sibling
checkout at runtime.
"""

from __future__ import annotations

import logging
import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any



LOGGER = logging.getLogger(__name__)
REPO = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE_REPO = REPO.parent / "tools" / "mvd_analyzer"
DEFAULT_REF = "upstream/main"
DEFAULT_OUT = REPO / "lab" / "dashboard" / "public" / "data" / "map_entities"
SOURCE_PATH = "mvd-analytics/mapents/data"
SCHEMA = "komodobots.map_entities.v1"
DEFAULT_MAPS = ("dm2", "dm3", "e1m2", "phantombase", "schloss", "ztricks")


class ImportErrorWithContext(RuntimeError):
    """Raised for import failures with a user-readable message."""


def git_bytes(source_repo: Path, args: list[str]) -> bytes:
    proc = subprocess.run(
        ["git", "-C", str(source_repo), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", errors="replace").strip()
        raise ImportErrorWithContext(
            f"git {' '.join(args)} failed in {source_repo}: {stderr}"
        )
    return proc.stdout


def resolve_commit(source_repo: Path, ref: str) -> str:
    return git_bytes(source_repo, ["rev-parse", ref]).decode("utf-8").strip()


def load_map_blob(source_repo: Path, ref: str, map_name: str) -> tuple[bytes, dict[str, Any]]:
    rel = f"{SOURCE_PATH}/{map_name}.json"
    raw = git_bytes(source_repo, ["show", f"{ref}:{rel}"])
    try:
        data = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ImportErrorWithContext(f"{rel} is not valid JSON at {ref}: {exc}") from exc
    validate_map_entity_doc(map_name, data)
    if not raw.endswith(b"\n"):
        raw += b"\n"
    return raw, data


def validate_map_entity_doc(map_name: str, data: dict[str, Any]) -> None:
    if data.get("map") != map_name:
        raise ImportErrorWithContext(
            f"{map_name}.json map field {data.get('map')!r} does not match {map_name!r}"
        )
    if data.get("version") != 1:
        raise ImportErrorWithContext(
            f"{map_name}.json version {data.get('version')!r} is not 1"
        )
    entities = data.get("entities")
    if not isinstance(entities, list) or not entities:
        raise ImportErrorWithContext(f"{map_name}.json must contain a non-empty entities list")
    for index, entity in enumerate(entities):
        if not isinstance(entity, dict):
            raise ImportErrorWithContext(f"{map_name}.json entity[{index}] is not an object")
        missing = {"type", "class", "x", "y", "z"} - set(entity)
        if missing:
            raise ImportErrorWithContext(
                f"{map_name}.json entity[{index}] missing required keys {sorted(missing)}"
            )


def type_counts(entities: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entity in entities:
        entity_type = str(entity["type"])
        counts[entity_type] = counts.get(entity_type, 0) + 1
    return dict(sorted(counts.items()))


def build_index(
    source_repo: Path,
    ref: str,
    commit: str,
    map_docs: list[tuple[str, dict[str, Any]]],
) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "v": 1,
        "source": {
            "repo": "https://github.com/galfthan/mvd_analyzer",
            "ref": ref,
            "commit": commit,
            "path": SOURCE_PATH,
        },
        "maps": [
            {
                "map": map_name,
                "file": f"{map_name}.json",
                "entities": len(doc["entities"]),
                "types": type_counts(doc["entities"]),
            }
            for map_name, doc in map_docs
        ],
    }


def render_index(data: dict[str, Any]) -> bytes:
    return (json.dumps(data, indent=2) + "\n").encode("utf-8")


def import_map_entities(
    *,
    source_repo: Path = DEFAULT_SOURCE_REPO,
    ref: str = DEFAULT_REF,
    out_dir: Path = DEFAULT_OUT,
    maps: tuple[str, ...] = DEFAULT_MAPS,
) -> list[Path]:
    if not source_repo.is_dir():
        raise ImportErrorWithContext(f"mvd_analyzer checkout not found: {source_repo}")

    commit = resolve_commit(source_repo, ref)
    out_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    map_docs: list[tuple[str, dict[str, Any]]] = []
    for map_name in maps:
        raw, doc = load_map_blob(source_repo, ref, map_name)
        target = out_dir / f"{map_name}.json"
        target.write_bytes(raw)
        written.append(target)
        map_docs.append((map_name, doc))

    index = build_index(source_repo, ref, commit, map_docs)
    index_path = out_dir / "index.json"
    index_path.write_bytes(render_index(index))
    written.append(index_path)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Import BotLab map-entity JSON from mvd_analyzer."
    )
    parser.add_argument(
        "--source-repo",
        type=Path,
        default=DEFAULT_SOURCE_REPO,
        help=f"mvd_analyzer checkout (default: {DEFAULT_SOURCE_REPO})",
    )
    parser.add_argument(
        "--ref",
        default=DEFAULT_REF,
        help=f"git ref to import from (default: {DEFAULT_REF})",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT,
        help=f"output directory (default: {DEFAULT_OUT})",
    )
    parser.add_argument(
        "--maps",
        nargs="+",
        default=list(DEFAULT_MAPS),
        help=f"map names to import (default: {' '.join(DEFAULT_MAPS)})",
    )
    args = parser.parse_args(argv)

    try:
        written = import_map_entities(
            source_repo=args.source_repo,
            ref=args.ref,
            out_dir=args.out_dir,
            maps=tuple(args.maps),
        )
    except ImportErrorWithContext as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    for path in written:
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
