#!/usr/bin/env python3
"""Build the interpolated human reference trace for ztricks Distance."""

from __future__ import annotations

import logging
import argparse
import json
import sys
from pathlib import Path
from typing import Iterable

from ztricks_reference_trace import (
    DEFAULT_CMDS,
    DEFAULT_HUMAN_REPLAY,
    DEFAULT_TRACE_JSON,
    DEFAULT_TRACE_MD,
    build_trace,
    render_markdown,
)



LOGGER = logging.getLogger(__name__)
def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build ztricks Distance reference trace artifacts.")
    parser.add_argument("--cmds", type=Path, default=DEFAULT_CMDS)
    parser.add_argument("--human-replay", type=Path, default=DEFAULT_HUMAN_REPLAY)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_TRACE_JSON)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_TRACE_MD)
    return parser.parse_args(list(argv))


def main(argv: Iterable[str] = sys.argv[1:]) -> int:
    args = parse_args(argv)
    report = build_trace(cmds_path=args.cmds, human_replay_path=args.human_replay)
    args.output_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.output_md.write_text(render_markdown(report), encoding="utf-8")
    print(f"wrote {args.output_json}")
    print(f"wrote {args.output_md}")
    print(render_markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
