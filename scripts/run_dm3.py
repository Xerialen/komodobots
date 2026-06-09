#!/usr/bin/env python3
"""One-command dm3 SNG->RL lab attempt with full observability.

Wraps run_frobodm2_lab.py so a dm3 attempt is NEVER run blind: it always
  * forces every-frame command logging (--moveprobe-log-commands --moveprobe-log-interval 0),
    so the per-tick origin/velocity/onground/move stream is captured;
  * builds the unified trace (build_trace.py);
  * scores it with the goal-true metric (verify_route.py);
  * mirrors demo.mvd to C:\\nQuake\\qw\\tricks\\dm3\\<run_id>.mvd for ezQuake review.

Any extra args are passed through to run_frobodm2_lab.py, e.g.:
  python run_dm3.py --moveprobe-mode 21 --duration 46 \
      --ktx-extra-cvars "k_fb_moveprobe_s21_corner_thresh 58;..."

Defaults: --map dm3 --bot-count 1 --replay-cmds artifacts/replay/dm3_sng_to_rl.cmds
(override by passing them explicitly).
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LAB = REPO / "scripts" / "run_frobodm2_lab.py"
TRICKS = Path(r"C:\nQuake\qw\tricks\dm3")
# Prefer a live (regenerated) replay under artifacts/ (gitignored); fall back to
# the committed copy in the experiment evidence dir so the one-command default
# works on a clean checkout (Codex PR #58). run_frobodm2_lab raises if the path
# is not a file, so this must resolve to something that exists.
_LIVE_REPLAY = REPO / "artifacts" / "replay" / "dm3_sng_to_rl.cmds"
_COMMITTED_REPLAY = (REPO / "experiments" / "dm3_sng_to_rl_observability"
                     / "evidence" / "dm3_sng_to_rl.cmds")
DEFAULT_REPLAY = str(_LIVE_REPLAY if _LIVE_REPLAY.exists() else _COMMITTED_REPLAY)


def main():
    passthrough = sys.argv[1:]
    have = lambda flag: any(a == flag or a.startswith(flag + "=") for a in passthrough)

    cmd = [sys.executable, str(LAB)]
    if not have("--map"):
        cmd += ["--map", "dm3"]
    if not have("--bot-count"):
        cmd += ["--bot-count", "1"]
    if not have("--replay-cmds"):
        cmd += ["--replay-cmds", DEFAULT_REPLAY]
    # forced observability defaults
    if not have("--moveprobe-log-commands"):
        cmd += ["--moveprobe-log-commands"]
    if not have("--moveprobe-log-interval"):
        cmd += ["--moveprobe-log-interval", "0"]
    cmd += passthrough

    print(">>", " ".join(cmd), flush=True)
    out = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
    sys.stdout.write(out.stdout)
    sys.stderr.write(out.stderr)
    m = re.search(r"run_id=(\S+)", out.stdout)
    if not m:
        print("\nERROR: could not parse run_id from lab output", file=sys.stderr)
        sys.exit(1)
    run_id = m.group(1)
    run_dir = REPO / "artifacts" / "lab-runs" / run_id

    # Mirror the raw demo first so it is preserved even if a measurement step
    # below fails (the demo is the irreplaceable artifact).
    demo = run_dir / "demo.mvd"
    if demo.exists():
        TRICKS.mkdir(parents=True, exist_ok=True)
        dst = TRICKS / f"{run_id}.mvd"
        shutil.copy2(demo, dst)
        print(f"\nmirrored demo -> {dst}  (playdemo tricks/dm3/{run_id}; track 2 for bot POV)")
    else:
        print(f"\nWARNING: {demo} not found -- demo not mirrored", file=sys.stderr)

    # "Never run blind": a failed trace/score must NOT exit 0 (Codex PR #58 P2),
    # or automation could treat a failed measurement as a completed lab run.
    print(f"\n=== build_trace {run_id} ===", flush=True)
    rc = subprocess.run([sys.executable, str(REPO / "scripts" / "build_trace.py"), run_id], cwd=REPO).returncode
    if rc != 0:
        print(f"\nERROR: build_trace failed (rc={rc}) -- no valid trace produced; "
              f"check the BSP path and that command logging was on", file=sys.stderr)
        sys.exit(rc)

    print(f"\n=== verify_route {run_id} ===", flush=True)
    rc = subprocess.run([sys.executable, str(REPO / "scripts" / "verify_route.py"), run_id], cwd=REPO).returncode
    if rc != 0:
        print(f"\nERROR: verify_route failed (rc={rc}) -- run not scored", file=sys.stderr)
        sys.exit(rc)


if __name__ == "__main__":
    main()
