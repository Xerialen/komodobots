#!/usr/bin/env python3
"""Spike-3 self-POV classifier for the dm3 4on4 POV corpus.

Prior work (challenge-tv-archive/) catalogued 548 dm3 POV demos and decompressed
the .qwz to .qwd, but classification was *filename-heuristic only*. This script
does the thing spike-3 actually requires: PARSE each .qwd and decide, per demo,
whether dem_cmd carries a single player's REAL first-person inputs (self-POV) or
a camera operator's idle inputs (spectator / autotrack / commentary).

Discriminators (all computed from the dem_cmd stream via qwd_usercmd):
  - move_nonzero_frac : fraction of usercmds with nonzero forward/side/up move.
       Self-POV humans press move keys most of the time (corpus avg ~72%).
       A spectator parked on autotrack emits long runs of zero-move frames.
  - move_active_frac  : fraction with |forward| or |side| >= 200 (a real key press,
       not analog drift). cl_forwardspeed is 200/400; spectators rarely hit this.
  - yaw_activity      : median |delta yaw| per second between consecutive cmds.
       A human aiming has continuous yaw motion; an autotrack camera SNAPS
       (rare huge jumps, mostly flat) -> low median, high max.
  - yaw_jump_frac     : fraction of consecutive-frame yaw deltas > 60 deg
       (camera target switches). High in autotrack/spectator.
  - cmd_rate_fps      : usercmds per second. Self-POV ~ 72-77 (or 1000/cl_maxfps).
       Pure spectator MVD-style recordings can be much lower / irregular.

Decision (calibrated on labelled samples, see census .md):
  SELF_POV if move_active_frac >= 0.45 AND move_nonzero_frac >= 0.55
  SPECTATOR if move_nonzero_frac < 0.20 (camera idle)
  AMBIGUOUS otherwise (reported separately; not counted toward the floor).

Run in WSL2 (parser is pure-python, but corpus lives at ~/ctv_decomp).
"""
from __future__ import annotations
import csv
import json
import statistics
import sys
from pathlib import Path

# qwd_usercmd parser (komodobots-ml worktree copy)
PARSER_DIR = "/mnt/c/Users/benya/projects/quakeworld/komodobots-ml/tools/qwd_usercmd"
sys.path.insert(0, PARSER_DIR)
import qwd_usercmd as q  # noqa: E402

CTV_DECOMP = Path.home() / "ctv_decomp"           # 477 decompressed .qwd
RAW_QWD_DIR = Path("/mnt/c/Users/benya/projects/quakeworld/data/challenge-tv-archive/stage_dm3")  # 70 raw .qwd
MANIFEST = RAW_QWD_DIR / "manifest.tsv"
OUT_DIR = Path("/mnt/c/Users/benya/projects/quakeworld/komodobots-ml/experiments/stage0/data-census")

ACTIVE_MOVE = 200          # a deliberate key press (cl_forwardspeed floor)
YAW_JUMP_DEG = 60.0        # consecutive-frame yaw delta that reads as a camera snap


def wrap180(d: float) -> float:
    d = (d + 180.0) % 360.0 - 180.0
    return d


def analyse(cmds) -> dict:
    n = len(cmds)
    if n == 0:
        return dict(frames=0)
    nonzero = sum(1 for c in cmds if c.forwardmove or c.sidemove or c.upmove)
    active = sum(1 for c in cmds if abs(c.forwardmove) >= ACTIVE_MOVE or abs(c.sidemove) >= ACTIVE_MOVE)
    # yaw activity from recorded view angles (index 1 = yaw)
    yaw_deltas = []
    jumps = 0
    prev = None
    for c in cmds:
        yaw = c.view_angles[1]
        if prev is not None:
            d = abs(wrap180(yaw - prev))
            yaw_deltas.append(d)
            if d > YAW_JUMP_DEG:
                jumps += 1
        prev = yaw
    med_yaw = statistics.median(yaw_deltas) if yaw_deltas else 0.0
    max_yaw = max(yaw_deltas) if yaw_deltas else 0.0
    return dict(
        frames=n,
        move_nonzero_frac=round(nonzero / n, 4),
        move_active_frac=round(active / n, 4),
        med_yaw_delta=round(med_yaw, 3),
        max_yaw_delta=round(max_yaw, 2),
        yaw_jump_frac=round(jumps / max(1, len(yaw_deltas)), 4),
    )


def classify(m: dict) -> str:
    if m.get("frames", 0) < 100:
        return "too_short"
    nz = m["move_nonzero_frac"]
    act = m["move_active_frac"]
    if act >= 0.45 and nz >= 0.55:
        return "self_pov"
    if nz < 0.20:
        return "spectator"
    return "ambiguous"


def load_manifest() -> dict:
    """staged_name(.stem) -> player, mode"""
    out = {}
    if not MANIFEST.exists():
        return out
    with MANIFEST.open(encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            stem = Path(r["staged_name"]).stem
            out[stem] = dict(player=r["player"], mode=r["mode"])
    return out


def main() -> int:
    manifest = load_manifest()
    # gather all .qwd: decompressed + raw
    files = sorted(CTV_DECOMP.glob("*.qwd"))
    raw = sorted(RAW_QWD_DIR.glob("*.qwd"))
    files += raw
    rows = []
    parse_fail = 0
    for f in files:
        stem = f.stem
        meta = manifest.get(stem, {})
        try:
            res = q.parse_qwd_path(f)
        except Exception as e:  # noqa: BLE001
            parse_fail += 1
            rows.append(dict(file=f.name, klass="parse_fail",
                             player=meta.get("player", "?"), mode=meta.get("mode", "?"),
                             frames=0, err=f"{type(e).__name__}: {e}"[:80]))
            continue
        m = analyse(res.commands)
        rows.append(dict(
            file=f.name,
            player=meta.get("player", "?"),
            mode=meta.get("mode", "?"),
            klass=classify(m),
            **m,
            duration_s=res.header.get("total_duration_s"),
            cmd_rate=res.header.get("command_rate_fps"),
            eof_clean=res.header.get("eof_clean"),
        ))

    # write per-demo tsv
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cols = ["file", "klass", "player", "mode", "frames", "move_nonzero_frac",
            "move_active_frac", "med_yaw_delta", "max_yaw_delta", "yaw_jump_frac",
            "duration_s", "cmd_rate", "eof_clean"]
    with (OUT_DIR / "self_pov_per_demo.tsv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, delimiter="\t", fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in sorted(rows, key=lambda r: (r["klass"], -r.get("frames", 0))):
            w.writerow(r)

    # aggregates
    import collections
    by_class = collections.Counter(r["klass"] for r in rows)
    self_rows = [r for r in rows if r["klass"] == "self_pov"]
    self_4on4 = [r for r in self_rows if r["mode"] == "team/4on4"]
    self_frames = sum(r["frames"] for r in self_rows)
    self_4on4_frames = sum(r["frames"] for r in self_4on4)
    self_players = collections.Counter(r["player"] for r in self_4on4)

    summary = dict(
        total_demos=len(rows),
        parse_fail=parse_fail,
        by_class=dict(by_class),
        self_pov_total=len(self_rows),
        self_pov_4on4=len(self_4on4),
        self_pov_total_frames=self_frames,
        self_pov_4on4_frames=self_4on4_frames,
        self_pov_4on4_distinct_players=len([p for p in self_players if p != "?"]),
        self_pov_4on4_player_counts=dict(self_players.most_common()),
    )
    with (OUT_DIR / "self_pov_summary.json").open("w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)

    print(json.dumps(summary, indent=2)[:2000])
    print("\nwrote self_pov_per_demo.tsv + self_pov_summary.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
