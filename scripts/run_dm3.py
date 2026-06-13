#!/usr/bin/env python3
"""One-command dm3 SNG->RL lab attempt with full observability.

Wraps run_frobodm2_lab.py so a dm3 attempt is NEVER run blind: it always
  * forces every-frame command logging (--moveprobe-log-commands --moveprobe-log-interval 0),
    so the per-tick origin/velocity/onground/move stream is captured;
  * builds the unified trace (build_trace.py);
  * scores it with the goal-true metric (verify_route.py);
  * relies on scripts/demo_archive.py for the canonical SSD demo copy under
    /mnt/usb-ssd/non-games/lab/Komodobots/<map>/<route>__<run_id>.mvd.

Any extra args are passed through to run_frobodm2_lab.py, e.g.:
  python run_dm3.py --moveprobe-mode 21 --duration 46 \
      --ktx-extra-cvars "k_fb_moveprobe_s21_corner_thresh 58;..."

Defaults: --map dm3 --bot-count 1 --moveprobe-mode 21
--replay-cmds artifacts/replay/dm3_sng_to_rl.cmds (committed evidence copy on a
clean checkout). Override any of them by passing them explicitly.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LAB = REPO / "scripts" / "run_frobodm2_lab.py"
RECORDS_BUILD = REPO / "lab" / "server" / "records_build.py"
# Prefer a live (regenerated) replay under artifacts/ (gitignored); fall back to
# the committed copy in the experiment evidence dir so the one-command default
# works on a clean checkout (Codex PR #58). run_frobodm2_lab raises if the path
# is not a file, so this must resolve to something that exists.
_LIVE_REPLAY = REPO / "artifacts" / "replay" / "dm3_sng_to_rl.cmds"
_COMMITTED_REPLAY = (REPO / "experiments" / "dm3_sng_to_rl_observability"
                     / "evidence" / "dm3_sng_to_rl.cmds")
DEFAULT_REPLAY = str(_LIVE_REPLAY if _LIVE_REPLAY.exists() else _COMMITTED_REPLAY)


def build_cmd(passthrough):
    """Lab command line with the SNG->RL observability defaults injected."""
    have = lambda flag: any(a == flag or a.startswith(flag + "=") for a in passthrough)

    cmd = [sys.executable, str(LAB)]
    if not have("--map"):
        cmd += ["--map", "dm3"]
    if not have("--bot-count"):
        cmd += ["--bot-count", "1"]
    if not have("--replay-cmds"):
        cmd += ["--replay-cmds", DEFAULT_REPLAY]
    # The lab's own default is k_fb_moveprobe_mode=0 (off), which silently
    # IGNORES the uploaded replay and measures plain Frogbot (Codex PR #58 P2).
    # Default to mode 21 -- the replay-backed SNG->RL controller the evidence
    # runs used (run.env MOVEPROBE_MODE=21; deployed as qwprogs-mode21.so).
    if not have("--moveprobe-mode"):
        cmd += ["--moveprobe-mode", "21"]
    # forced observability defaults
    if not have("--moveprobe-log-commands"):
        cmd += ["--moveprobe-log-commands"]
    if not have("--moveprobe-log-interval"):
        cmd += ["--moveprobe-log-interval", "0"]
    return cmd + list(passthrough)


def records_update_cmd(run_id):
    """Post-run records-store update (LD-D1, issue #93): rescore this run,
    rebuild records.json against the live SSD archive listing, and publish.
    Additive observability -- the caller treats failure as a loud warning,
    never a lab-run failure."""
    return [sys.executable, str(RECORDS_BUILD), "--append", run_id,
            "--archive-ssh", "servexeri", "--publish"]


def main():
    cmd = build_cmd(sys.argv[1:])
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

    # Records store (LD-D1, issue #93): append this attempt, update records if
    # improved, publish to the SSD. A publish/build failure must NOT fail the
    # lab run -- the run artifacts are the source of truth and records.json is
    # rebuildable (`python lab/server/records_build.py --rebuild --publish`).
    print(f"\n=== records update {run_id} ===", flush=True)
    rc = subprocess.run(records_update_cmd(run_id), cwd=REPO).returncode
    if rc != 0:
        print(f"\nWARNING: records update/publish failed (rc={rc}) -- the lab "
              f"run itself is complete and scored; rebuild records later with: "
              f"python lab/server/records_build.py --rebuild --publish",
              file=sys.stderr)


if __name__ == "__main__":
    main()
