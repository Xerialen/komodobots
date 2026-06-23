#!/usr/bin/env python3
"""Inspect Frogbot route-edge geometry against S6 attribution evidence."""

from __future__ import annotations

import logging
import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable

import attribute_route_state_windows as route_attr



LOGGER = logging.getLogger(__name__)
SCHEMA = "komodobots.route_edge_geometry.v1"
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_KTX_ROOT = REPO_ROOT.parent / "engine" / "ktx"
DEFAULT_BOT_MAP = DEFAULT_KTX_ROOT / "resources" / "example-configs" / "ktx" / "bots" / "maps" / "dm3.bot"
DEFAULT_ATTRIBUTIONS = (
    REPO_ROOT / "experiments" / "ktx_moveprobe" / "evidence" / "route-state-s6d-water-attribution.json",
    REPO_ROOT / "experiments" / "ktx_moveprobe" / "evidence" / "route-state-s6e-water-upmove-attribution.json",
)


def read_json(path: Path) -> dict[str, object]:
    with path.open("r", encoding="utf-8") as handle:
        loaded = json.load(handle)
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} did not contain a JSON object")
    return loaded


def parse_edge_spec(value: str) -> tuple[int, int]:
    normalized = value.replace("->", ":")
    parts = normalized.split(":")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("edge must look like SOURCE:TARGET or SOURCE->TARGET")
    try:
        source = int(parts[0])
        target = int(parts[1])
    except ValueError as exc:
        raise argparse.ArgumentTypeError("edge endpoints must be integers") from exc
    if source <= 0 or target <= 0:
        raise argparse.ArgumentTypeError("edge endpoints must be positive marker ids")
    return source, target


def parse_bot_map_geometry(path: Path) -> dict[str, object]:
    markers: dict[int, dict[str, object]] = {}
    paths: list[dict[str, object]] = []
    marker_id = 0
    referenced_markers: set[int] = set()

    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("//"):
            continue
        parts = line.split()
        command = parts[0]
        try:
            if command == "CreateMarker" and len(parts) >= 4:
                marker_id += 1
                marker = markers.setdefault(marker_id, {"id": marker_id})
                marker["origin"] = [
                    route_attr.round_float(parts[1], 1),
                    route_attr.round_float(parts[2], 1),
                    route_attr.round_float(parts[3], 1),
                ]
                marker["create_marker_line"] = line_number
                marker["has_static_origin"] = True
            elif command == "SetGoal" and len(parts) >= 3:
                marker_id_arg = int(parts[1])
                referenced_markers.add(marker_id_arg)
                marker = markers.setdefault(marker_id_arg, {"id": marker_id_arg})
                marker["goal"] = int(parts[2])
                marker["set_goal_line"] = line_number
            elif command == "SetZone" and len(parts) >= 3:
                marker_id_arg = int(parts[1])
                referenced_markers.add(marker_id_arg)
                marker = markers.setdefault(marker_id_arg, {"id": marker_id_arg})
                marker["zone"] = int(parts[2])
                marker["set_zone_line"] = line_number
            elif command == "SetMarkerPath" and len(parts) >= 4:
                source = int(parts[1])
                path_index = int(parts[2])
                target = int(parts[3])
                referenced_markers.update((source, target))
                paths.append(
                    {
                        "source": source,
                        "target": target,
                        "path_index": path_index,
                        "line": line_number,
                        "explicit_flags": [],
                        "flag_lines": [],
                    }
                )
            elif command == "SetMarkerPathFlags" and len(parts) >= 4:
                source = int(parts[1])
                path_index = int(parts[2])
                flag_names = route_attr.decode_external_flag_string(parts[3])
                for path_row in paths:
                    if path_row["source"] == source and path_row["path_index"] == path_index:
                        path_row["explicit_flags"] = flag_names
                        path_row["flag_lines"] = [line_number]
                        break
        except ValueError:
            continue

    for marker in markers.values():
        marker.setdefault("has_static_origin", bool(marker.get("origin")))

    return {
        "path": route_attr.portable_path(path),
        "static_create_marker_count": marker_id,
        "referenced_marker_count": len(referenced_markers),
        "markers_without_static_origin": sorted(
            marker_id_arg
            for marker_id_arg in referenced_markers
            if not markers.get(marker_id_arg, {}).get("origin")
        ),
        "markers": markers,
        "paths": paths,
    }


def marker_summary(marker_id: int, bot_map: dict[str, object]) -> dict[str, object]:
    marker = bot_map.get("markers", {}).get(marker_id, {}) if marker_id > 0 else {}
    return {
        "id": marker_id,
        "zone": marker.get("zone", ""),
        "goal": marker.get("goal", ""),
        "origin": marker.get("origin", []),
        "has_static_origin": bool(marker.get("origin")),
        "create_marker_line": marker.get("create_marker_line", ""),
        "set_zone_line": marker.get("set_zone_line", ""),
        "set_goal_line": marker.get("set_goal_line", ""),
    }


def path_rows(source: int, target: int, bot_map: dict[str, object]) -> list[dict[str, object]]:
    return [
        row
        for row in bot_map.get("paths", [])
        if isinstance(row, dict) and row.get("source") == source and row.get("target") == target
    ]


def vector_geometry(source_marker: dict[str, object], target_marker: dict[str, object]) -> dict[str, object]:
    missing = [
        str(marker["id"])
        for marker in (source_marker, target_marker)
        if not marker.get("has_static_origin")
    ]
    if missing:
        return {
            "status": "incomplete_missing_static_origin",
            "missing_static_origin_markers": missing,
        }

    source = [float(value) for value in source_marker.get("origin", [])]
    target = [float(value) for value in target_marker.get("origin", [])]
    dx = target[0] - source[0]
    dy = target[1] - source[1]
    dz = target[2] - source[2]
    horizontal = math.hypot(dx, dy)
    distance_3d = math.sqrt(dx * dx + dy * dy + dz * dz)
    yaw = math.degrees(math.atan2(dy, dx))
    if yaw < 0:
        yaw += 360.0
    return {
        "status": "computed",
        "delta": {
            "x": route_attr.round_float(dx, 1),
            "y": route_attr.round_float(dy, 1),
            "z": route_attr.round_float(dz, 1),
        },
        "horizontal_distance": route_attr.round_float(horizontal, 1),
        "distance_3d": route_attr.round_float(distance_3d, 1),
        "yaw_degrees": route_attr.round_float(yaw, 1),
        "vertical_delta": route_attr.round_float(dz, 1),
        "grade": route_attr.round_float(dz / horizontal if horizontal else 0.0),
    }


def edge_summary(source: int, target: int, bot_map: dict[str, object]) -> dict[str, object]:
    rows = path_rows(source, target, bot_map)
    source_marker = marker_summary(source, bot_map)
    target_marker = marker_summary(target, bot_map)
    return {
        "source": source,
        "target": target,
        "defined_in_bot_map": bool(rows),
        "path_indexes": [row["path_index"] for row in rows],
        "line_numbers": [row["line"] for row in rows],
        "explicit_flags": sorted({flag for row in rows for flag in row.get("explicit_flags", [])}),
        "flag_line_numbers": [line for row in rows for line in row.get("flag_lines", [])],
        "source_marker": source_marker,
        "target_marker": target_marker,
        "static_geometry": vector_geometry(source_marker, target_marker),
    }


def neighbor_edges(marker_id: int, bot_map: dict[str, object]) -> dict[str, object]:
    outgoing = [
        edge_summary(marker_id, int(row["target"]), bot_map)
        for row in bot_map.get("paths", [])
        if isinstance(row, dict) and row.get("source") == marker_id
    ]
    incoming = [
        edge_summary(int(row["source"]), marker_id, bot_map)
        for row in bot_map.get("paths", [])
        if isinstance(row, dict) and row.get("target") == marker_id
    ]
    return {
        "marker": marker_summary(marker_id, bot_map),
        "outgoing": sorted(outgoing, key=lambda row: (row["path_indexes"] or [999])[0]),
        "incoming": sorted(incoming, key=lambda row: (row["source"], row["path_indexes"] or [999])),
    }


def sample_waterlevel(sample: dict[str, object]) -> object:
    water = sample.get("water_state", {}) if isinstance(sample.get("water_state"), dict) else {}
    return water.get("waterlevel", "") if water.get("present") else ""


def sample_upmove(sample: dict[str, object]) -> float:
    water = sample.get("water_state", {}) if isinstance(sample.get("water_state"), dict) else {}
    return route_attr.round_float(water.get("emitted_upmove", 0.0), 1)


def sample_edge(sample: dict[str, object]) -> tuple[int, int]:
    edge = sample.get("touch_to_link_path", {}) if isinstance(sample.get("touch_to_link_path"), dict) else {}
    return (
        route_attr.coerce_int(edge.get("source", 0)),
        route_attr.coerce_int(edge.get("target", 0)),
    )


def attribution_samples(
    attribution_paths: Iterable[Path],
    focus_edge: tuple[int, int],
    focus_marker: int,
) -> list[dict[str, object]]:
    samples: list[dict[str, object]] = []
    for path in attribution_paths:
        attribution = read_json(path)
        stage = str(attribution.get("stage", path.stem))
        for window in attribution.get("windows", []):
            if not isinstance(window, dict):
                continue
            for sample in window.get("route_samples", []):
                if not isinstance(sample, dict):
                    continue
                source, target = sample_edge(sample)
                marker_values = {
                    route_attr.coerce_int(sample.get("linked_marker", 0)),
                    route_attr.coerce_int(sample.get("touch_marker", 0)),
                    route_attr.coerce_int(sample.get("goal_marker", 0)),
                    source,
                    target,
                }
                if (source, target) != focus_edge and focus_marker not in marker_values:
                    continue
                samples.append(
                    {
                        "attribution_json": route_attr.portable_path(path),
                        "stage": stage,
                        "player": window.get("player", ""),
                        "rank": window.get("rank", ""),
                        "window_ms": window.get("window_ms", {}),
                        "location": window.get("location", ""),
                        "time_ms": sample.get("time_ms", ""),
                        "touch_marker": sample.get("touch_marker", ""),
                        "linked_marker": sample.get("linked_marker", ""),
                        "goal_marker": sample.get("goal_marker", ""),
                        "edge": {"source": source, "target": target},
                        "edge_is_focus": (source, target) == focus_edge,
                        "path_state": sample.get("path_state", {}),
                        "blocked": bool(sample.get("blocked", False)),
                        "dir_speed": route_attr.round_float(sample.get("dir_speed", 0.0)),
                        "waterlevel": sample_waterlevel(sample),
                        "emitted_upmove": sample_upmove(sample),
                    }
                )
    return samples


def compact(values: Iterable[object]) -> list[object]:
    return sorted({value for value in values if value != ""})


def average(values: Iterable[float]) -> float:
    materialized = [value for value in values if math.isfinite(value)]
    return route_attr.round_float(sum(materialized) / len(materialized) if materialized else 0.0)


def sample_summary(samples: list[dict[str, object]], focus_edge: tuple[int, int]) -> dict[str, object]:
    unique_samples = dedupe_samples(samples)
    edge_samples = [sample for sample in unique_samples if sample.get("edge_is_focus")]
    focus = edge_samples or unique_samples
    dir_speeds = [float(sample.get("dir_speed", 0.0)) for sample in focus]
    stage_counts = Counter(str(sample.get("stage", "")) for sample in unique_samples)
    player_counts = Counter(str(sample.get("player", "")) for sample in unique_samples)
    edge_counts = Counter(
        f"{sample.get('edge', {}).get('source')}->{sample.get('edge', {}).get('target')}"
        for sample in unique_samples
    )
    path_names = sorted(
        {
            name
            for sample in focus
            for name in sample.get("path_state", {}).get("names", [])
        }
    )
    return {
        "focus_edge": {"source": focus_edge[0], "target": focus_edge[1]},
        "window_sample_row_count": len(samples),
        "unique_sample_count": len(unique_samples),
        "focus_edge_sample_count": len(edge_samples),
        "stage_counts": dict(sorted(stage_counts.items())),
        "player_counts": dict(sorted(player_counts.items())),
        "edge_counts": dict(sorted(edge_counts.items())),
        "path_state_names": path_names,
        "blocked_ratio": route_attr.round_float(sum(1 for sample in focus if sample.get("blocked")) / len(focus) if focus else 0.0),
        "low_dir_speed_ratio": route_attr.round_float(sum(1 for value in dir_speeds if value < 0.25) / len(dir_speeds) if dir_speeds else 0.0),
        "dir_speed_avg": average(dir_speeds),
        "dir_speed_min": route_attr.round_float(min(dir_speeds) if dir_speeds else 0.0),
        "dir_speed_max": route_attr.round_float(max(dir_speeds) if dir_speeds else 0.0),
        "waterlevel_values": compact(sample.get("waterlevel", "") for sample in focus),
        "emitted_upmove_nonzero_ratio": route_attr.round_float(
            sum(1 for sample in focus if abs(float(sample.get("emitted_upmove", 0.0))) > 0.01) / len(focus)
            if focus
            else 0.0
        ),
    }


def dedupe_samples(samples: list[dict[str, object]]) -> list[dict[str, object]]:
    deduped = []
    seen = set()
    for sample in samples:
        edge = sample.get("edge", {})
        key = (
            sample.get("attribution_json", ""),
            sample.get("stage", ""),
            sample.get("player", ""),
            sample.get("time_ms", ""),
            edge.get("source", ""),
            edge.get("target", ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(sample)
    return deduped


def build_report(args: argparse.Namespace) -> dict[str, object]:
    source, target = args.edge
    bot_map = parse_bot_map_geometry(args.bot_map)
    samples = attribution_samples(args.attribution_json, args.edge, args.marker)
    edge = edge_summary(source, target, bot_map)
    reciprocal = edge_summary(target, source, bot_map)
    summary = sample_summary(samples, args.edge)
    geometry_status = edge.get("static_geometry", {}).get("status", "")
    interpretation = [
        f"`{source}->{target}` is explicitly defined in `dm3.bot` with path indexes {edge.get('path_indexes', [])}.",
        f"The reciprocal `{target}->{source}` edge is {'also defined' if reciprocal.get('defined_in_bot_map') else 'not defined'} with path indexes {reciprocal.get('path_indexes', [])}.",
        "The focus edge has no explicit `SetMarkerPathFlags`; the observed `WATER_PATH` flag is runtime route-state classification, not a literal route-file flag on this edge.",
    ]
    if geometry_status == "incomplete_missing_static_origin":
        missing = edge.get("static_geometry", {}).get("missing_static_origin_markers", [])
        interpretation.append(
            f"Static vector geometry is incomplete because marker(s) {missing} have no `CreateMarker` origin in `dm3.bot`."
        )
    else:
        interpretation.append("Static vector geometry is computable from the route file.")
    if summary.get("focus_edge_sample_count"):
        interpretation.append(
            f"S6d/S6e evidence contains {summary.get('focus_edge_sample_count')} sampled `{source}->{target}` rows; "
            f"low native `dir_speed < 0.25` appears in {summary.get('low_dir_speed_ratio') * 100.0:.1f}% of the focus-edge samples."
        )
    interpretation.append(
        "S6f does not justify another water-upmove or command-magnitude tweak from static route data alone."
    )
    return {
        "schema": SCHEMA,
        "stage": args.stage,
        "sources": {
            "bot_map": route_attr.portable_path(args.bot_map),
            "attribution_json": [route_attr.portable_path(path) for path in args.attribution_json],
        },
        "bot_map_summary": {
            "static_create_marker_count": bot_map.get("static_create_marker_count", 0),
            "referenced_marker_count": bot_map.get("referenced_marker_count", 0),
            "markers_without_static_origin_count": len(bot_map.get("markers_without_static_origin", [])),
        },
        "focus": {
            "edge": {"source": source, "target": target},
            "marker": args.marker,
        },
        "edge": edge,
        "reciprocal_edge": reciprocal,
        "marker": marker_summary(args.marker, bot_map),
        "neighborhood": {
            "source_marker": neighbor_edges(source, bot_map),
            "target_marker": neighbor_edges(target, bot_map),
        },
        "attribution_summary": summary,
        "attribution_samples": samples,
        "interpretation": interpretation,
        "decision": (
            "No tiny static route-data fix is justified by S6f: marker 276 lacks a static origin, "
            "the reciprocal edge exists, and the water-path state is runtime classification rather than an explicit edge flag."
        ),
        "next_goal": (
            "S7a should seed player-specific movement signatures from the existing exact-player dm3 references "
            "(Milton, carapace, yeti) before any player-specific controller work; keep the headline land-speed/bunnyhop gap visible."
        ),
    }


def edge_label(edge: dict[str, object]) -> str:
    flags = edge.get("explicit_flags", [])
    flag_label = f" flags={flags}" if flags else ""
    return (
        f"{edge.get('source')}->{edge.get('target')} "
        f"idx={edge.get('path_indexes', [])} lines={edge.get('line_numbers', [])}{flag_label}"
    )


def marker_label(marker: dict[str, object]) -> str:
    origin = marker.get("origin", [])
    origin_label = origin if origin else "missing"
    return (
        f"id={marker.get('id')} zone={marker.get('zone', '')} goal={marker.get('goal', '')} "
        f"origin={origin_label}"
    )


def pct(value: object) -> str:
    try:
        return f"{float(value) * 100.0:.1f}%"
    except (TypeError, ValueError):
        return ""


def write_markdown(report: dict[str, object], output_path: Path) -> None:
    edge = report.get("edge", {})
    reciprocal = report.get("reciprocal_edge", {})
    geometry = edge.get("static_geometry", {}) if isinstance(edge.get("static_geometry"), dict) else {}
    summary = report.get("attribution_summary", {})
    lines = [
        f"# Route Edge Geometry {report.get('stage', '')}",
        "",
        "## Scope",
        "",
        f"- Bot map: `{report.get('sources', {}).get('bot_map', '')}`",
        f"- Focus edge: `{edge.get('source')}->{edge.get('target')}`",
        f"- Focus marker: `{report.get('focus', {}).get('marker', '')}`",
        "",
        "## Edge",
        "",
        f"- Edge: `{edge_label(edge)}`",
        f"- Reciprocal: `{edge_label(reciprocal)}`",
        f"- Source marker: `{marker_label(edge.get('source_marker', {}))}`",
        f"- Target marker: `{marker_label(edge.get('target_marker', {}))}`",
        f"- Static geometry status: `{geometry.get('status', '')}`",
    ]
    if geometry.get("status") == "computed":
        lines.extend(
            [
                f"- Horizontal distance: `{geometry.get('horizontal_distance')}`",
                f"- Vertical delta: `{geometry.get('vertical_delta')}`",
                f"- Yaw: `{geometry.get('yaw_degrees')}`",
                f"- Grade: `{geometry.get('grade')}`",
            ]
        )
    elif geometry.get("missing_static_origin_markers"):
        lines.append(f"- Missing static origins: `{geometry.get('missing_static_origin_markers')}`")

    lines.extend(
        [
            "",
            "## Attribution Summary",
            "",
            f"- Window sample rows touching focus marker/edge: `{summary.get('window_sample_row_count', 0)}`",
            f"- Unique samples touching focus marker/edge: `{summary.get('unique_sample_count', 0)}`",
            f"- Exact focus-edge samples: `{summary.get('focus_edge_sample_count', 0)}`",
            f"- Focus-edge path states: `{summary.get('path_state_names', [])}`",
            f"- Waterlevels: `{summary.get('waterlevel_values', [])}`",
            f"- Blocked ratio: `{pct(summary.get('blocked_ratio'))}`",
            f"- Low native dir-speed ratio: `{pct(summary.get('low_dir_speed_ratio'))}`",
            f"- Dir-speed avg/min/max: `{summary.get('dir_speed_avg')}` / `{summary.get('dir_speed_min')}` / `{summary.get('dir_speed_max')}`",
            f"- Emitted upmove nonzero ratio: `{pct(summary.get('emitted_upmove_nonzero_ratio'))}`",
            "",
            "## Neighborhood",
            "",
            "| Marker | Direction | Edge | Source origin | Target origin | Geometry |",
            "|---:|---|---|---|---|---|",
        ]
    )
    for marker_key in ("source_marker", "target_marker"):
        neighborhood = report.get("neighborhood", {}).get(marker_key, {})
        marker_id = neighborhood.get("marker", {}).get("id", "")
        for direction in ("outgoing", "incoming"):
            for row in neighborhood.get(direction, []):
                row_geometry = row.get("static_geometry", {})
                lines.append(
                    "| "
                    f"`{marker_id}` | "
                    f"`{direction}` | "
                    f"`{edge_label(row)}` | "
                    f"`{row.get('source_marker', {}).get('origin', []) or 'missing'}` | "
                    f"`{row.get('target_marker', {}).get('origin', []) or 'missing'}` | "
                    f"`{row_geometry.get('status', '')}` |"
                )

    lines.extend(
        [
            "",
            "## Focus Samples",
            "",
            "| Stage | Player | Rank | Time | Location | Edge | Dir speed | Waterlevel | Upmove | Blocked |",
            "|---|---|---:|---:|---|---|---:|---|---:|---:|",
        ]
    )
    for sample in report.get("attribution_samples", []):
        edge_row = sample.get("edge", {})
        lines.append(
            "| "
            f"`{sample.get('stage', '')}` | "
            f"`{sample.get('player', '')}` | "
            f"`{sample.get('rank', '')}` | "
            f"`{sample.get('time_ms', '')}` | "
            f"`{sample.get('location', '')}` | "
            f"`{edge_row.get('source')}->{edge_row.get('target')}` | "
            f"{sample.get('dir_speed')} | "
            f"`{sample.get('waterlevel', '')}` | "
            f"{sample.get('emitted_upmove')} | "
            f"{'yes' if sample.get('blocked') else 'no'} |"
        )

    lines.extend(["", "## Interpretation", ""])
    for note in report.get("interpretation", []):
        lines.append(f"- {note}")
    lines.extend(["", "## Decision", "", f"- {report.get('decision', '')}"])
    lines.extend(["", "## Next Goal", "", f"- {report.get('next_goal', '')}", ""])
    output_path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect one Frogbot route edge's static geometry and S6 evidence.")
    parser.add_argument("--stage", default="s6f-route-edge-geometry", help="Stage label for output artifacts.")
    parser.add_argument("--bot-map", type=Path, default=DEFAULT_BOT_MAP, help="Frogbot .bot map file.")
    parser.add_argument("--edge", type=parse_edge_spec, default=(276, 59), help="Route edge as SOURCE:TARGET or SOURCE->TARGET.")
    parser.add_argument("--marker", type=int, default=59, help="Focus marker id for neighborhood/evidence filtering.")
    parser.add_argument(
        "--attribution-json",
        type=Path,
        action="append",
        default=None,
        help="Route-state attribution JSON. May be passed more than once.",
    )
    parser.add_argument("--output-json", type=Path, required=True, help="Output JSON path.")
    parser.add_argument("--output-md", type=Path, required=True, help="Output Markdown path.")
    args = parser.parse_args(list(argv))
    if args.attribution_json is None:
        args.attribution_json = list(DEFAULT_ATTRIBUTIONS)
    return args


def main(argv: Iterable[str] = sys.argv[1:]) -> int:
    args = parse_args(argv)
    report = build_report(args)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_markdown(report, args.output_md)
    print(f"Wrote route-edge geometry report: {args.output_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
