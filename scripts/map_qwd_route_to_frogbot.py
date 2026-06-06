#!/usr/bin/env python3
"""Map extracted QWD waypoints onto the existing Frogbot dm3 route graph.

This is a decision probe, not a route importer. It asks whether one human POV
trajectory is close enough to the existing Frogbot `.bot` marker graph that the
next server-loop experiment should use route following, command imitation, or a
hybrid waypoint/controller target.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import tempfile
from collections import deque
from pathlib import Path
from typing import Iterable, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import attribute_route_state_windows as route_attr
import probe_qwd_route_applicability as qwd_probe


SCHEMA = "komodobots.qwd_frogbot_route_mapping.v1"
DEFAULT_DEMO = (
    REPO_ROOT.parent
    / "data"
    / "quake-development"
    / "clients"
    / "xerialqw-bench"
    / "qw"
    / "matchinfo"
    / "demos"
    / "tricks"
    / "dm3_sng_shortcut.qwd"
)
DEFAULT_BOT_MAP = (
    REPO_ROOT.parent
    / "engine"
    / "ktx"
    / "resources"
    / "example-configs"
    / "ktx"
    / "bots"
    / "maps"
    / "dm3.bot"
)
DEFAULT_OUTPUT_JSON = REPO_ROOT / "experiments" / "qwd_route_probe" / "evidence" / "qwd-frogbot-route-map-dm3-sng-shortcut.json"
DEFAULT_OUTPUT_MD = REPO_ROOT / "experiments" / "qwd_route_probe" / "evidence" / "qwd-frogbot-route-map-dm3-sng-shortcut.md"


def percentile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * q
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[int(rank)]
    weight = rank - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def round_float(value: object, digits: int = 3) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return round(number, digits)


def distance_3d(a: Sequence[float], b: Sequence[float]) -> float:
    return math.dist(a, b)


def load_qwd_waypoints(demo: Path, *, waypoint_spacing: float) -> tuple[dict[str, object], list[dict[str, object]]]:
    with tempfile.TemporaryDirectory() as temp_dir:
        raw_dir = Path(temp_dir)
        demo_summary = qwd_probe.summarize_demo(demo, waypoint_spacing_qu=waypoint_spacing, raw_output_dir=raw_dir)
        waypoint_path = raw_dir / f"{demo.stem}.waypoints.json"
        waypoints = json.loads(waypoint_path.read_text(encoding="utf-8"))
    if not isinstance(waypoints, list):
        raise ValueError(f"{waypoint_path} did not contain a JSON list")
    return demo_summary, waypoints


def static_markers(bot_map: dict[str, object]) -> list[dict[str, object]]:
    markers: list[dict[str, object]] = []
    for marker_id, marker in bot_map.get("markers", {}).items():
        if not isinstance(marker, dict) or not marker.get("origin"):
            continue
        markers.append(
            {
                "id": int(marker_id),
                "origin": [float(value) for value in marker["origin"]],
                "zone": marker.get("zone", ""),
                "goal": marker.get("goal", ""),
            }
        )
    return sorted(markers, key=lambda row: row["id"])


def nearest_marker(point: Sequence[float], markers: Sequence[dict[str, object]]) -> dict[str, object]:
    best = min(markers, key=lambda marker: distance_3d(point, marker["origin"]))
    distance = distance_3d(point, best["origin"])
    return {
        "id": best["id"],
        "origin": [round_float(value, 3) for value in best["origin"]],
        "distance_qu": round_float(distance, 3),
        "zone": best.get("zone", ""),
        "goal": best.get("goal", ""),
    }


def map_waypoints_to_markers(waypoints: Sequence[dict[str, object]], markers: Sequence[dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for waypoint in waypoints:
        origin = [float(value) for value in waypoint["origin"]]
        nearest = nearest_marker(origin, markers)
        rows.append(
            {
                "segment": waypoint.get("segment", 0),
                "frame": waypoint.get("frame"),
                "time_s": waypoint.get("time_s"),
                "waypoint_origin": [round_float(value, 3) for value in origin],
                "nearest_marker": nearest,
            }
        )
    return rows


def collapse_marker_sequence(mapped_waypoints: Sequence[dict[str, object]]) -> list[dict[str, object]]:
    collapsed: list[dict[str, object]] = []
    for row in mapped_waypoints:
        marker = row["nearest_marker"]
        marker_id = int(marker["id"])
        if collapsed and int(collapsed[-1]["marker_id"]) == marker_id:
            collapsed[-1]["last_frame"] = row.get("frame")
            collapsed[-1]["last_time_s"] = row.get("time_s")
            collapsed[-1]["waypoint_count"] += 1
            collapsed[-1]["max_nearest_distance_qu"] = max(
                float(collapsed[-1]["max_nearest_distance_qu"]),
                float(marker["distance_qu"]),
            )
            continue
        collapsed.append(
            {
                "marker_id": marker_id,
                "marker_origin": marker["origin"],
                "zone": marker.get("zone", ""),
                "goal": marker.get("goal", ""),
                "first_frame": row.get("frame"),
                "last_frame": row.get("frame"),
                "first_time_s": row.get("time_s"),
                "last_time_s": row.get("time_s"),
                "waypoint_count": 1,
                "first_waypoint_origin": row["waypoint_origin"],
                "nearest_distance_qu": marker["distance_qu"],
                "max_nearest_distance_qu": marker["distance_qu"],
            }
        )
    return collapsed


def adjacency(bot_map: dict[str, object]) -> dict[int, list[int]]:
    graph: dict[int, list[int]] = {}
    for key in bot_map.get("paths", {}):
        source, target = key
        graph.setdefault(int(source), []).append(int(target))
    for values in graph.values():
        values.sort()
    return graph


def shortest_path(graph: dict[int, list[int]], source: int, target: int, *, max_depth: int = 32) -> list[int] | None:
    if source == target:
        return [source]
    queue: deque[tuple[int, list[int]]] = deque([(source, [source])])
    seen = {source}
    while queue:
        node, path = queue.popleft()
        if len(path) > max_depth:
            continue
        for neighbor in graph.get(node, []):
            if neighbor in seen:
                continue
            next_path = [*path, neighbor]
            if neighbor == target:
                return next_path
            seen.add(neighbor)
            queue.append((neighbor, next_path))
    return None


def analyze_marker_transitions(collapsed: Sequence[dict[str, object]], bot_map: dict[str, object]) -> list[dict[str, object]]:
    graph = adjacency(bot_map)
    transitions: list[dict[str, object]] = []
    paths = bot_map.get("paths", {})
    for left, right in zip(collapsed, collapsed[1:]):
        source = int(left["marker_id"])
        target = int(right["marker_id"])
        direct = paths.get((source, target), {}) if isinstance(paths, dict) else {}
        reverse = paths.get((target, source), {}) if isinstance(paths, dict) else {}
        shortest = shortest_path(graph, source, target)
        reverse_shortest = shortest_path(graph, target, source)
        transitions.append(
            {
                "source": source,
                "target": target,
                "defined_direct_edge": bool(direct),
                "defined_reverse_edge": bool(reverse),
                "direct_path_indexes": direct.get("path_indexes", []) if isinstance(direct, dict) else [],
                "direct_explicit_flags": direct.get("explicit_flags", []) if isinstance(direct, dict) else [],
                "shortest_path_edges": len(shortest) - 1 if shortest else None,
                "shortest_path": shortest[:16] if shortest else [],
                "reverse_shortest_path_edges": len(reverse_shortest) - 1 if reverse_shortest else None,
            }
        )
    return transitions


def summarize_mapping(mapped: Sequence[dict[str, object]], collapsed: Sequence[dict[str, object]], transitions: Sequence[dict[str, object]]) -> dict[str, object]:
    distances = [float(row["nearest_marker"]["distance_qu"]) for row in mapped]
    direct_edges = sum(1 for row in transitions if row["defined_direct_edge"])
    reverse_edges = sum(1 for row in transitions if row["defined_reverse_edge"])
    graph_reachable = [row for row in transitions if row["shortest_path_edges"] is not None]
    shortest_lengths = [float(row["shortest_path_edges"]) for row in graph_reachable if row["shortest_path_edges"] is not None]
    transition_count = len(transitions)
    return {
        "waypoint_count": len(mapped),
        "collapsed_marker_count": len(collapsed),
        "transition_count": transition_count,
        "nearest_marker_distance_qu": {
            "p50": round_float(percentile(distances, 0.50)),
            "p95": round_float(percentile(distances, 0.95)),
            "max": round_float(max(distances) if distances else None),
            "within_128_ratio": round_float(sum(value <= 128.0 for value in distances) / len(distances) if distances else None),
            "within_192_ratio": round_float(sum(value <= 192.0 for value in distances) / len(distances) if distances else None),
        },
        "bot_graph_alignment": {
            "direct_edge_count": direct_edges,
            "direct_edge_ratio": round_float(direct_edges / transition_count if transition_count else None),
            "reverse_edge_count": reverse_edges,
            "graph_reachable_count": len(graph_reachable),
            "graph_reachable_ratio": round_float(len(graph_reachable) / transition_count if transition_count else None),
            "shortest_path_edges_p50": round_float(percentile(shortest_lengths, 0.50)),
            "shortest_path_edges_p95": round_float(percentile(shortest_lengths, 0.95)),
            "shortest_path_edges_max": round_float(max(shortest_lengths) if shortest_lengths else None),
        },
    }


def choose_probe_recommendation(mapping_summary: dict[str, object], demo_summary: dict[str, object]) -> dict[str, object]:
    distances = mapping_summary["nearest_marker_distance_qu"]
    graph = mapping_summary["bot_graph_alignment"]
    commands = demo_summary.get("commands", {}) if isinstance(demo_summary.get("commands"), dict) else {}
    marker_fit = (distances.get("p95") or 9999) <= 192 and (distances.get("within_128_ratio") or 0) >= 0.75
    direct_fit = (graph.get("direct_edge_ratio") or 0) >= 0.6
    graph_fit = (graph.get("graph_reachable_ratio") or 0) >= 0.9 and (graph.get("shortest_path_edges_p50") or 9999) <= 5
    side_dominant = (commands.get("nonzero_side_ratio") or 0) > (commands.get("nonzero_forward_ratio") or 0)

    if marker_fit and direct_fit:
        recommendation = "route_following_probe"
        confidence = "medium"
        reason = (
            "The human waypoints align with existing markers and most consecutive markers are direct Frogbot edges."
        )
    elif marker_fit and graph_fit:
        recommendation = "hybrid_waypoint_controller_probe"
        confidence = "medium"
        reason = (
            "The human route is spatially close to Frogbot markers, but consecutive human waypoints usually require "
            "multi-edge graph paths rather than direct `.bot` edges."
        )
    elif marker_fit:
        recommendation = "hybrid_waypoint_controller_probe"
        confidence = "medium_low"
        reason = (
            "The marker cloud is close enough for spatial context, but the existing `.bot` topology does not match "
            "the human shortcut well enough for pure route following."
        )
    else:
        recommendation = "command_imitation_probe"
        confidence = "low"
        reason = (
            "The extracted route is not close enough to existing Frogbot markers to justify route reuse as the first probe."
        )

    if side_dominant:
        reason += " The QWD action labels are side-move dominant, so the controller probe should preserve local command imitation rather than reducing the move to a simple forward waypoint chase."

    return {
        "next_probe": recommendation,
        "confidence": confidence,
        "reason": reason,
        "north_star_relevance": (
            "This chooses the smallest server-loop test that could turn human QWD evidence into better DM3 Frogbot movement without rebuilding physics, collision, combat, or recording."
        ),
        "stop_conditions": [
            "Do not claim success from reaching waypoints if movement buckets regress against S7/S7k baselines.",
            "Do not mutate dm3.bot route data until a controller/waypoint probe shows the human route is executable under KTX physics.",
            "Preserve route, water, probe-activation, command, and cadence diagnostics in any follow-up run.",
        ],
    }


def build_report(args: argparse.Namespace) -> dict[str, object]:
    demo_summary, waypoints = load_qwd_waypoints(args.demo, waypoint_spacing=args.waypoint_spacing)
    bot_map = route_attr.parse_bot_map(args.bot_map)
    markers = static_markers(bot_map)
    mapped = map_waypoints_to_markers(waypoints, markers)
    collapsed = collapse_marker_sequence(mapped)
    transitions = analyze_marker_transitions(collapsed, bot_map)
    mapping_summary = summarize_mapping(mapped, collapsed, transitions)
    recommendation = choose_probe_recommendation(mapping_summary, demo_summary)
    return {
        "schema": SCHEMA,
        "stage": args.stage,
        "source": {
            "demo": args.demo.name,
            "demo_sha256": demo_summary.get("source_sha256"),
            "bot_map": route_attr.portable_path(args.bot_map),
            "waypoint_spacing_qu": args.waypoint_spacing,
        },
        "qwd_demo_summary": {
            "command_frames": demo_summary["command_frames"],
            "state_frames": demo_summary["state_frames"],
            "paired_coverage": demo_summary["paired_coverage"],
            "motion": demo_summary["motion"],
            "commands": demo_summary["commands"],
        },
        "bot_map_summary": {
            "static_marker_count": len(markers),
            "path_count": len(bot_map.get("paths", {})),
            "markers_without_static_origin_count": len(bot_map.get("markers_without_static_origin", [])),
            "marker_index_invariant": bot_map.get("marker_index_invariant", ""),
        },
        "mapping_summary": mapping_summary,
        "nearest_marker_sequence": collapsed,
        "transition_analysis": transitions,
        "recommendation": recommendation,
    }


def render_markdown(report: dict[str, object]) -> str:
    mapping = report["mapping_summary"]
    distance = mapping["nearest_marker_distance_qu"]
    graph = mapping["bot_graph_alignment"]
    recommendation = report["recommendation"]
    commands = report["qwd_demo_summary"]["commands"]
    lines = [
        "# QWD to Frogbot route mapping",
        "",
        "## Verdict",
        "",
        f"- Recommended next probe: `{recommendation['next_probe']}`.",
        f"- Confidence: `{recommendation['confidence']}`.",
        f"- Reason: {recommendation['reason']}",
        "",
        "## Evidence",
        "",
        f"- Demo: `{report['source']['demo']}`.",
        f"- Command/state coverage: `{report['qwd_demo_summary']['paired_coverage']}`.",
        f"- QWD waypoints: `{mapping['waypoint_count']}`.",
        f"- Collapsed nearest-marker sequence: `{mapping['collapsed_marker_count']}` markers.",
        f"- Nearest-marker p50/p95/max: `{distance['p50']}` / `{distance['p95']}` / `{distance['max']}` qu.",
        f"- Waypoints within 128 qu of a static marker: `{distance['within_128_ratio']}`.",
        f"- Direct Frogbot edge ratio across collapsed transitions: `{graph['direct_edge_ratio']}`.",
        f"- Graph reachable ratio: `{graph['graph_reachable_ratio']}`.",
        f"- Shortest-path edge p50/p95/max: `{graph['shortest_path_edges_p50']}` / `{graph['shortest_path_edges_p95']}` / `{graph['shortest_path_edges_max']}`.",
        f"- QWD command profile: nonzero forward `{commands.get('nonzero_forward_ratio')}`, nonzero side `{commands.get('nonzero_side_ratio')}`, jump `{commands.get('jump_button_ratio')}`.",
        "",
        "## Marker Sequence",
        "",
        "| # | marker | nearest distance | frame span | waypoint count |",
        "| ---: | ---: | ---: | --- | ---: |",
    ]
    for index, row in enumerate(report["nearest_marker_sequence"], start=1):
        lines.append(
            f"| {index} | {row['marker_id']} | {row['nearest_distance_qu']} | {row['first_frame']}..{row['last_frame']} | {row['waypoint_count']} |"
        )
    lines.extend(
        [
            "",
            "## Transition Check",
            "",
            "| source | target | direct edge | shortest path edges |",
            "| ---: | ---: | --- | ---: |",
        ]
    )
    for row in report["transition_analysis"]:
        lines.append(
            f"| {row['source']} | {row['target']} | `{row['defined_direct_edge']}` | {row['shortest_path_edges']} |"
        )
    lines.extend(
        [
            "",
            "## Stop Conditions",
            "",
            *[f"- {condition}" for condition in recommendation["stop_conditions"]],
            "",
        ]
    )
    return "\n".join(lines)


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Map one QWD trajectory onto the Frogbot dm3 route graph.")
    parser.add_argument("--stage", default="qwd-dm3-sng-route-map", help="Stage label for outputs.")
    parser.add_argument("--demo", type=Path, default=DEFAULT_DEMO, help="QWD demo to map.")
    parser.add_argument("--bot-map", type=Path, default=DEFAULT_BOT_MAP, help="Frogbot .bot map file.")
    parser.add_argument("--waypoint-spacing", type=float, default=64.0, help="QWD waypoint spacing in qu.")
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    return parser.parse_args(list(argv))


def main(argv: Iterable[str] = sys.argv[1:]) -> int:
    args = parse_args(argv)
    report = build_report(args)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.output_md.write_text(render_markdown(report) + "\n", encoding="utf-8")
    print(f"Wrote QWD route mapping: {args.output_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
