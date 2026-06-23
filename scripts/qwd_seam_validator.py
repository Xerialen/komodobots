#!/usr/bin/env python3
"""Audit the QWD action-label seam used by replay and imitation tools.

Important terminology: a POV QWD does not contain raw device mouse deltas. It
contains the post-input per-frame view-angle result (`view_angles` /
`usercmd_t.angles`) plus movement commands/buttons. That is still the right
actuation label for KTX replay because the server consumes absolute
`cmd.angles`.
"""

from __future__ import annotations

import logging
import argparse
import json
import sys
from pathlib import Path
from typing import Iterable, Sequence



LOGGER = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import build_replay_command_file as replay_builder
import probe_qwd_route_applicability as probe
from tools.qwd_usercmd import qwd_usercmd


SCHEMA = "komodobots.qwd_seam_audit.v1"


def zip_time_delta_summary(
    commands: Sequence[qwd_usercmd.UsercmdRecord],
    states: Sequence[probe.PlayerInfoSample],
) -> dict[str, object]:
    count = min(len(commands), len(states))
    deltas = [states[index].time_s - commands[index].time_s for index in range(count)]
    abs_deltas = [abs(value) for value in deltas]
    unsafe = len(commands) != len(states) or (max(abs_deltas) if abs_deltas else 0.0) > 0.020
    return {
        "paired_frames": count,
        "paired_coverage": round(count / len(commands), 3) if commands else 0.0,
        "time_delta_s": replay_builder.summarize_values(deltas, digits=6),
        "time_delta_abs_s": replay_builder.summarize_values(abs_deltas, digits=6),
        "unsafe_zip_pairing": unsafe,
    }


def validate_demo(path: Path, *, state_shift: int = 0) -> dict[str, object]:
    data = path.read_bytes()
    parsed = qwd_usercmd.parse_qwd_bytes(data, source_path=path, strict_plausibility=False)
    commands = parsed.commands
    states, serverdata, scan = probe.extract_playerinfo_samples(data)
    _state_for_cmd, alignment = replay_builder.match_states_by_time(
        commands,
        states,
        state_shift=state_shift,
    )

    return {
        "demo": path.name,
        "path": str(path),
        "source_sha256": parsed.header["source_sha256"],
        "map_level": serverdata.level_name if serverdata else None,
        "playernum": serverdata.playernum if serverdata else None,
        "raw_mouse_deltas_available": False,
        "angle_label_kind": "per-frame absolute view-angle result",
        "authoritative_angle_channel": "view_angles",
        "command_frames": len(commands),
        "state_frames": len(states),
        "command_msec": replay_builder.summarize_msec(commands),
        "angle_channel_delta_deg": replay_builder.summarize_angle_channels(commands),
        "zip_pairing": zip_time_delta_summary(commands, states),
        "time_alignment": alignment,
        "scan_counts": scan,
    }


def render_markdown(report: dict[str, object]) -> str:
    lines = [
        "# QWD seam validator",
        "",
        (
            "POV QWD provides per-frame absolute view angles and movement commands; "
            "it does not provide raw device mouse deltas."
        ),
        "",
        "| demo | cmds | states | zip coverage | zip unsafe | yaw p95 delta | msec p50 | time unmatched |",
        "| --- | ---: | ---: | ---: | --- | ---: | ---: | ---: |",
    ]
    for demo in report["demos"]:
        yaw = demo["angle_channel_delta_deg"]["yaw"]
        msec = demo["command_msec"]
        zip_pairing = demo["zip_pairing"]
        alignment = demo["time_alignment"]
        lines.append(
            "| {demo} | {cmds} | {states} | {cov:.3f} | {unsafe} | {yaw_p95} | {msec_p50} | {unmatched} |".format(
                demo=demo["demo"],
                cmds=demo["command_frames"],
                states=demo["state_frames"],
                cov=zip_pairing["paired_coverage"],
                unsafe=str(zip_pairing["unsafe_zip_pairing"]),
                yaw_p95=yaw["p95"],
                msec_p50=msec["p50"],
                unmatched=alignment["unmatched_command_frames"],
            )
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- `view_angles` is the replay channel; `cmd_angles` is retained for audit comparison.",
            "- `zip unsafe=True` means state drops or drift make frame-order command/state pairing unsafe.",
            "- Time alignment can still produce interpolated reference rows; inspect the JSON before lockstep claims.",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit QWD command/state and angle-channel seams.")
    parser.add_argument("--demo", type=Path, action="append", required=True, help="POV .qwd to audit.")
    parser.add_argument(
        "--state-shift",
        type=int,
        default=0,
        help="State shift to evaluate in time alignment metadata. Defaults to 0.",
    )
    parser.add_argument("--output-json", type=Path, help="Write machine-readable audit JSON.")
    parser.add_argument("--output-md", type=Path, help="Write a compact Markdown report.")
    return parser.parse_args(list(argv))


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    demos = [validate_demo(path, state_shift=args.state_shift) for path in args.demo]
    report = {
        "schema": SCHEMA,
        "state_shift": args.state_shift,
        "demos": demos,
    }
    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    rendered = render_markdown(report)
    if args.output_md:
        args.output_md.parent.mkdir(parents=True, exist_ok=True)
        args.output_md.write_text(rendered + "\n", encoding="utf-8")
    if not args.output_json and not args.output_md:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
