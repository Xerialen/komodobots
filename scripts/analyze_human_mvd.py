#!/usr/bin/env python3
"""Inventory and analyze local human MVD demos.

S4 needs a human anchor for movement plausibility. This script intentionally
keeps that first step small: inventory local candidate demos, parse one selected
human MVD with the same qw-analyze / movement-metrics pipeline used for bot lab
runs, and write a compact summary that says whether the result is map-comparable
to the current S3 bot evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Iterable

from extract_movement_metrics import write_movement_metrics
from run_frobodm2_lab import DEFAULT_ANALYZER, run_analyzer


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DEMO_ROOT = (
    REPO_ROOT.parent
    / "data"
    / "quake-development"
    / "clients"
    / "xerialqw-bench"
    / "qw"
    / "matchinfo"
    / "demos"
)
DEFAULT_ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "human-demos"
DEFAULT_BOT_SUMMARY = REPO_ROOT / "experiments" / "ktx_moveprobe" / "evidence" / "moveprobe-s3g-summary.json"

INVENTORY_SCHEMA = "komodobots.human_mvd_inventory.v1"
SUMMARY_SCHEMA = "komodobots.human_mvd_analysis.v1"
MIN_ACTIVE_TIME_S = 1.0
MIN_ACTIVE_SAMPLE_COUNT = 10
MIN_HORIZONTAL_DISTANCE_QU = 100.0

MAP_TOKENS = (
    "frobodm2",
    "aerowalk",
    "ztndm3",
    "ztricks2",
    "ztricks",
    "e1m2",
    "dm2",
    "dm3",
    "dm4",
    "dm6",
)

MATCH_TITLE_MAPS = {
    "aerowalk": "aerowalk",
    "claustrophobopolis": "dm2",
    "the abandoned base": "dm3",
    "the bad place": "dm4",
    "the dark zone": "dm6",
    "frogbotrophobopolis": "frobodm2",
}


def round_float(value: object, digits: int = 3) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return round(number, digits)


def slugify(value: str, *, fallback: str = "demo") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or fallback


def format_stage_label(value: object) -> str:
    text = str(value or "s4a")
    head, separator, tail = text.partition("-")
    match = re.fullmatch(r"s(\d+)([a-z]?)", head.lower())
    if match:
        label = f"S{match.group(1)}{match.group(2)}"
    else:
        label = head
    return f"{label}{separator}{tail}" if separator else label


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def infer_map_from_text(text: str) -> str:
    normalized = text.lower()
    for token in MAP_TOKENS:
        if re.search(rf"(^|[^a-z0-9]){re.escape(token)}([^a-z0-9]|$)", normalized):
            return token
    return ""


def infer_map_from_match_title(title: object) -> str:
    if not title:
        return ""
    normalized = re.sub(r"\s+", " ", str(title).strip().lower())
    return MATCH_TITLE_MAPS.get(normalized, infer_map_from_text(normalized))


def infer_demo_kind(path: Path) -> str:
    name = path.stem.lower()
    for kind in ("1on1", "2on2", "4on4", "tricks"):
        if name.startswith(kind):
            return kind
    return ""


def relativize(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return path.name


def inventory_demo(path: Path, root: Path) -> dict[str, object]:
    return {
        "name": path.name,
        "path": str(path.resolve()),
        "relative_path": relativize(path, root),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "inferred_map": infer_map_from_text(path.name),
        "demo_kind": infer_demo_kind(path),
    }


def build_inventory(root: Path, *, recursive: bool = False) -> dict[str, object]:
    root = root.resolve()
    paths = sorted(root.rglob("*.mvd") if recursive and root.exists() else root.glob("*.mvd")) if root.exists() else []
    demos = [inventory_demo(path, root) for path in paths if path.is_file()]
    dm2_candidates = [demo for demo in demos if demo.get("inferred_map") == "dm2"]
    maps = sorted({str(demo.get("inferred_map") or "unknown") for demo in demos})
    return {
        "schema": INVENTORY_SCHEMA,
        "root": str(root),
        "recursive": recursive,
        "map_inference_method": "filename_token_heuristic",
        "demo_count": len(demos),
        "maps": maps,
        "dm2_candidate_count": len(dm2_candidates),
        "has_dm2_candidate": bool(dm2_candidates),
        "demos": demos,
    }


def write_inventory_markdown(inventory: dict[str, object], output_path: Path) -> None:
    lines = [
        "# Human MVD Inventory",
        "",
        f"- Root: `{inventory.get('root', '')}`",
        f"- Demos: `{inventory.get('demo_count', 0)}`",
        f"- DM2 filename candidates: `{inventory.get('dm2_candidate_count', 0)}`",
        f"- Map inference: `{inventory.get('map_inference_method', 'filename_token_heuristic')}`",
        "",
        "| Demo | Kind | Inferred map | Bytes | SHA-256 |",
        "|---|---|---|---:|---|",
    ]
    for demo in inventory.get("demos", []):
        lines.append(
            "| "
            f"`{demo.get('relative_path')}` | "
            f"`{demo.get('demo_kind') or ''}` | "
            f"`{demo.get('inferred_map') or 'unknown'}` | "
            f"{demo.get('size_bytes')} | "
            f"`{str(demo.get('sha256', ''))[:12]}` |"
        )
    if not inventory.get("has_dm2_candidate"):
        lines.extend(
            [
                "",
                "No local DM2 filename candidate was inferred from this inventory.",
            ]
        )
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_json_if_present(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def resolve_demo_path(demo: str, root: Path) -> Path:
    candidate = Path(demo)
    if candidate.is_file():
        return candidate.resolve()
    rooted = root / demo
    if rooted.is_file():
        return rooted.resolve()
    raise FileNotFoundError(f"Could not find demo {demo!r} or {rooted}")


def write_run_env(path: Path, values: dict[str, object]) -> None:
    lines = []
    for key, value in values.items():
        rendered = str(value).replace("\r", " ").replace("\n", " ")
        lines.append(f"{key}={rendered}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def compact_player_row(player: dict[str, object]) -> dict[str, object]:
    return {
        "slot": player.get("slot"),
        "name": player.get("name", ""),
        "sample_count": player.get("sample_count", 0),
        "active_time_s": round_float(player.get("active_time_s")),
        "avg_horizontal_speed_qu_per_s": round_float(player.get("avg_horizontal_speed_qu_per_s")),
        "p95_horizontal_speed_qu_per_s": round_float(player.get("p95_horizontal_speed_qu_per_s")),
        "max_horizontal_speed_qu_per_s": round_float(player.get("max_horizontal_speed_qu_per_s")),
        "stationary_time_ratio": round_float(player.get("stationary_time_ratio")),
        "low_speed_time_ratio": round_float(player.get("low_speed_time_ratio")),
        "airborne_proxy_time_ratio": round_float(player.get("airborne_proxy_time_ratio")),
        "jump_cadence_per_min": round_float(player.get("jump_cadence_per_min")),
    }


def is_active_movement_player(player: dict[str, object]) -> bool:
    try:
        sample_count = int(player.get("sample_count", 0))
    except (TypeError, ValueError):
        sample_count = 0
    active_time_s = round_float(player.get("active_time_s"))
    horizontal_distance = round_float(player.get("horizontal_distance_qu"))
    return (
        sample_count >= MIN_ACTIVE_SAMPLE_COUNT
        and active_time_s >= MIN_ACTIVE_TIME_S
        and horizontal_distance >= MIN_HORIZONTAL_DISTANCE_QU
    )


def compact_player_metrics(metrics: dict[str, object]) -> list[dict[str, object]]:
    players = []
    for player in metrics.get("players", []):
        if is_active_movement_player(player):
            players.append(compact_player_row(player))
    return players


def compact_inactive_named_slots(metrics: dict[str, object]) -> list[dict[str, object]]:
    inactive = []
    for player in metrics.get("players", []):
        if player.get("name") and not is_active_movement_player(player):
            inactive.append(compact_player_row(player))
    return inactive


def bot_summary_context(bot_summary_path: Path) -> dict[str, object]:
    summary = load_json_if_present(bot_summary_path)
    runs = summary.get("runs", []) if isinstance(summary, dict) else []
    maps = sorted({str(run.get("map", "")) for run in runs if isinstance(run, dict) and run.get("map")})
    return {
        "path": str(bot_summary_path),
        "available": bool(summary),
        "schema": summary.get("schema", "") if isinstance(summary, dict) else "",
        "maps": maps,
        "run_count": len(runs),
    }


def comparison_verdict(human_map: str, bot_maps: list[str], has_dm2_candidate: bool) -> str:
    if not human_map:
        return "parser_proof_only_unknown_map"
    if human_map in bot_maps:
        return "same_map_human_reference_available"
    if human_map == "dm2":
        return "human_dm2_available_but_s3g_not_dm2"
    if not has_dm2_candidate:
        return "parser_proof_only_no_local_dm2"
    return "parser_proof_only_map_mismatch"


def comparison_note(verdict: str) -> str:
    if verdict == "same_map_human_reference_available":
        return "This is map-matched to at least one S3g bot run and can seed a small comparison."
    if verdict == "human_dm2_available_but_s3g_not_dm2":
        return (
            "Use this as a true-DM2 human anchor, but not as a direct S3g comparison "
            "until bot evidence exists on DM2 or a map-matched human sample exists."
        )
    return "Use this as a parser proof only until a DM2 or map-matched human set is available."


def build_human_summary(
    *,
    run_dir: Path,
    source_demo: Path,
    inventory: dict[str, object],
    parser_exits: dict[str, int],
    bot_summary_path: Path,
    stage: str = "s4a",
) -> dict[str, object]:
    analysis = load_json_if_present(run_dir / "analysis.json")
    metrics = load_json_if_present(run_dir / "movement-metrics.json")
    match = analysis.get("match", {}) if isinstance(analysis, dict) else {}
    match_title = str(match.get("map", "")) if isinstance(match, dict) else ""
    map_from_match = infer_map_from_match_title(match_title)
    map_from_name = infer_map_from_text(source_demo.name)
    human_map = map_from_match or map_from_name
    bot_context = bot_summary_context(bot_summary_path)
    bot_maps = [str(value) for value in bot_context.get("maps", [])]
    same_map = bool(human_map and human_map in bot_maps)
    has_dm2_candidate = bool(inventory.get("has_dm2_candidate"))
    verdict = comparison_verdict(human_map, bot_maps, has_dm2_candidate)

    return {
        "schema": SUMMARY_SCHEMA,
        "stage": stage,
        "run_id": run_dir.name,
        "artifact_dir": str(run_dir),
        "demo": {
            "name": source_demo.name,
            "source_path": str(source_demo),
            "copied_demo": str(run_dir / "demo.mvd"),
            "size_bytes": source_demo.stat().st_size,
            "sha256": sha256_file(source_demo),
            "inferred_map_from_name": map_from_name,
            "map": human_map,
            "demo_kind": infer_demo_kind(source_demo),
        },
        "parser": {
            "exits": parser_exits,
            "event_count": (metrics.get("parser", {}) if isinstance(metrics, dict) else {}).get("event_count", 0),
            "position_event_count": (metrics.get("parser", {}) if isinstance(metrics, dict) else {}).get(
                "position_event_count", 0
            ),
        },
        "match": {
            "map_title": match_title,
            "map": human_map,
            "duration_ms": match.get("duration", "") if isinstance(match, dict) else "",
            "frag_count": len(analysis.get("frags", [])) if isinstance(analysis, dict) else 0,
        },
        "movement_players": compact_player_metrics(metrics if isinstance(metrics, dict) else {}),
        "ignored_named_slots": compact_inactive_named_slots(metrics if isinstance(metrics, dict) else {}),
        "inventory": {
            "root": inventory.get("root", ""),
            "demo_count": inventory.get("demo_count", 0),
            "dm2_candidate_count": inventory.get("dm2_candidate_count", 0),
            "has_dm2_candidate": has_dm2_candidate,
            "map_inference_method": inventory.get("map_inference_method", "filename_token_heuristic"),
        },
        "comparison_context": {
            "bot_summary": bot_context,
            "same_map_comparable_to_s3g": same_map,
            "verdict": verdict,
            "note": comparison_note(verdict),
        },
    }


def pct(value: object) -> str:
    try:
        return f"{float(value) * 100.0:.1f}%"
    except (TypeError, ValueError):
        return ""


def write_human_summary_markdown(summary: dict[str, object], output_path: Path) -> None:
    demo = summary.get("demo", {})
    match = summary.get("match", {})
    inventory = summary.get("inventory", {})
    comparison = summary.get("comparison_context", {})
    bot_summary = comparison.get("bot_summary", {}) if isinstance(comparison, dict) else {}
    stage = format_stage_label(summary.get("stage") or "s4a")

    lines = [
        f"# Human MVD {stage} Summary",
        "",
        "## Demo",
        "",
        f"- Run: `{summary.get('run_id')}`",
        f"- Demo: `{demo.get('name')}`",
        f"- Kind: `{demo.get('demo_kind') or ''}`",
        f"- Map: `{demo.get('map') or 'unknown'}`",
        f"- Match title: `{match.get('map_title') or ''}`",
        f"- Duration: `{match.get('duration_ms')}` ms",
        f"- Frags: `{match.get('frag_count')}`",
        f"- SHA-256: `{demo.get('sha256')}`",
        "",
        "## Inventory Context",
        "",
        f"- Inventory root: `{inventory.get('root')}`",
        f"- Local demos inventoried: `{inventory.get('demo_count')}`",
        f"- Local DM2 filename candidates: `{inventory.get('dm2_candidate_count')}`",
        f"- Inventory map inference: `{inventory.get('map_inference_method', 'filename_token_heuristic')}`",
        f"- Ignored named slots: `{len(summary.get('ignored_named_slots', []))}` "
        f"(active < {MIN_ACTIVE_TIME_S:g}s, samples < {MIN_ACTIVE_SAMPLE_COUNT}, "
        f"or distance < {MIN_HORIZONTAL_DISTANCE_QU:g}qu)",
        "",
        "## Movement Players",
        "",
        "| Player | Samples | Active s | Avg | P95 | Max | Stationary | Low | Air | Cadence/min |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for player in summary.get("movement_players", []):
        lines.append(
            "| "
            f"`{player.get('name')}` | "
            f"{player.get('sample_count')} | "
            f"{player.get('active_time_s'):.3f} | "
            f"{player.get('avg_horizontal_speed_qu_per_s'):.1f} | "
            f"{player.get('p95_horizontal_speed_qu_per_s'):.1f} | "
            f"{player.get('max_horizontal_speed_qu_per_s'):.1f} | "
            f"{pct(player.get('stationary_time_ratio'))} | "
            f"{pct(player.get('low_speed_time_ratio'))} | "
            f"{pct(player.get('airborne_proxy_time_ratio'))} | "
            f"{player.get('jump_cadence_per_min'):.1f} |"
        )
    if not summary.get("movement_players"):
        lines.append("| No named movement players parsed | | | | | | | | | |")

    lines.extend(
        [
            "",
            "## S3g Comparison Context",
            "",
            f"- Bot summary: `{bot_summary.get('path', '')}`",
            f"- Bot maps: `{', '.join(bot_summary.get('maps', []))}`",
            f"- Same-map comparable: `{comparison.get('same_map_comparable_to_s3g')}`",
            f"- Verdict: `{comparison.get('verdict')}`",
            "",
            str(comparison.get("note", "")),
            "",
        ]
    )
    output_path.write_text("\n".join(lines), encoding="utf-8")


def analyze_demo(
    *,
    demo_path: Path,
    inventory: dict[str, object],
    artifact_root: Path,
    run_id: str,
    distro: str,
    analyzer: str,
    bot_summary_path: Path,
    stage: str,
) -> dict[str, object]:
    run_dir = artifact_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    demo_hash = sha256_file(demo_path)
    copied_demo = run_dir / "demo.mvd"
    shutil.copy2(demo_path, copied_demo)
    (run_dir / "source-demo-path.txt").write_text(str(demo_path) + "\n", encoding="utf-8")
    (run_dir / "demo.size").write_text(f"{copied_demo.stat().st_size}\n", encoding="utf-8")
    (run_dir / "demo.sha256").write_text(f"{demo_hash} *demo.mvd\n", encoding="utf-8")

    parser_exits = run_analyzer(run_dir, distro, analyzer)

    analysis = load_json_if_present(run_dir / "analysis.json")
    match = analysis.get("match", {}) if isinstance(analysis, dict) else {}
    match_title = str(match.get("map", "")) if isinstance(match, dict) else ""
    map_name = infer_map_from_match_title(match_title) or infer_map_from_text(demo_path.name)
    write_run_env(
        run_dir / "run.env",
        {
            "RUN_ID": run_id,
            "SOURCE_KIND": "human-demo",
            "SOURCE_DEMO_PATH": demo_path,
            "SOURCE_DEMO_NAME": demo_path.name,
            "SOURCE_DEMO_SHA256": demo_hash,
            "MAP": map_name,
            "MAP_TITLE": match_title,
            "PARSER_JSON_EXIT": parser_exits.get("json", ""),
            "PARSER_MD_EXIT": parser_exits.get("md", ""),
            "PARSER_EVENTS_EXIT": parser_exits.get("events", ""),
        },
    )

    write_movement_metrics(run_dir)
    summary = build_human_summary(
        run_dir=run_dir,
        source_demo=demo_path,
        inventory=inventory,
        parser_exits=parser_exits,
        bot_summary_path=bot_summary_path,
        stage=stage,
    )
    (run_dir / "human-summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_human_summary_markdown(summary, run_dir / "human-summary.md")
    return summary


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inventory and analyze local human QuakeWorld MVD demos.")
    parser.add_argument("--demo-root", type=Path, default=DEFAULT_DEMO_ROOT, help="Directory containing human MVDs.")
    parser.add_argument("--recursive", action="store_true", help="Inventory demos recursively under --demo-root.")
    parser.add_argument("--demo", help="Specific demo path, or filename relative to --demo-root, to analyze.")
    parser.add_argument("--run-id", help="Artifact run id. Defaults to s4a-<demo-stem>.")
    parser.add_argument("--stage", default="s4a", help="Evidence stage label used in summaries and output filenames.")
    parser.add_argument("--artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT, help="Output artifact root.")
    parser.add_argument("--distro", default="Ubuntu-24.04", help="WSL distro containing qw-analyze-v20.")
    parser.add_argument("--analyzer", default=DEFAULT_ANALYZER, help="Analyzer path inside WSL.")
    parser.add_argument(
        "--bot-summary",
        type=Path,
        default=DEFAULT_BOT_SUMMARY,
        help="Bot comparison summary, usually S3g derived evidence.",
    )
    return parser.parse_args(list(argv))


def main(argv: Iterable[str] = sys.argv[1:]) -> int:
    args = parse_args(argv)
    artifact_root = args.artifact_root
    artifact_root.mkdir(parents=True, exist_ok=True)

    inventory = build_inventory(args.demo_root, recursive=args.recursive)
    inventory_json = artifact_root / "human-demo-inventory.json"
    inventory_md = artifact_root / "human-demo-inventory.md"
    inventory_json.write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_inventory_markdown(inventory, inventory_md)

    if not args.demo:
        print(f"Wrote inventory: {inventory_md}")
        return 0

    demo_path = resolve_demo_path(args.demo, args.demo_root)
    stage_slug = slugify(args.stage, fallback="stage")
    run_id = args.run_id or f"{stage_slug}-{slugify(demo_path.stem)}"
    summary = analyze_demo(
        demo_path=demo_path,
        inventory=inventory,
        artifact_root=artifact_root,
        run_id=run_id,
        distro=args.distro,
        analyzer=args.analyzer,
        bot_summary_path=args.bot_summary,
        stage=args.stage,
    )

    summary_json = artifact_root / f"human-demo-{stage_slug}-summary.json"
    summary_md = artifact_root / f"human-demo-{stage_slug}-summary.md"
    summary_json.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_human_summary_markdown(summary, summary_md)
    print(f"Wrote inventory: {inventory_md}")
    print(f"Wrote summary: {summary_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
