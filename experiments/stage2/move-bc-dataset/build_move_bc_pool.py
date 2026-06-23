#!/usr/bin/env python3
"""Build the Stage-2 MOVE behavioural-cloning POOL dataset from the self-POV
4on4 dm3 corpus (references/12 Stage 2, §5 MOVE bullet).

This is a thin orchestration wrapper around the already-validated lab tooling:

  scripts/build_replay_command_file.build_replay_frames  -> per-frame
      {state=(o,v,a,onground,pm_code), action=(fwd,side,up,buttons)} + the
      time-aligned svc_playerinfo state recovery.
  scripts/pmove_sim.{load_cmds_file,detect_teleports,replay}  -> LABEL-INTEGRITY
      replay: re-simulate the recorded usercmds through the validated MVDSV
      pmove port and measure trajectory divergence (1s-segmented free-run with
      teleporter/respawn re-anchoring, exactly as the human-replay validation in
      experiments/nav_doctrine/evidence/pmove-validation-report.md).

For each demo it:
  1. builds the (state,action) frames (the BC labels),
  2. writes a per-demo NDJSON shard (one row per frame) to --shard-dir,
  3. renders the .cmds and replays it through pmove_sim to score label integrity,
  4. records per-demo movement-quality + label-integrity stats into the manifest.

A demo PASSES label integrity if, after teleport/respawn re-anchoring, the
1s-segmented free-run keeps the bulk of segments within tolerance -- i.e. the
recorded actions reproduce the recorded trajectory through the validated sim.
Demos that fail are flagged (not silently dropped) with their failing-segment
count, so submodel/lift/teleport/player-collision contamination is auditable.

POOL dataset: per-player depth is thin (most players 1-2 demos), so this builds
the pooled elite-self-POV set for pretraining, NOT a single-player clone.

Pure-stdlib; runs under WSL2 Python against the Windows-side repo + BSP and the
WSL-local demo corpus (machine hosting policy: heavy compute in WSL2).
"""
from __future__ import annotations

import logging
import argparse
import json
import math
import os
import sys
import time
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed


LOGGER = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parents[3]
for _p in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import build_replay_command_file as brc  # noqa: E402
import pmove_sim  # noqa: E402

# 1 s at the ~72-77 Hz command rate of these demos. The validated human replay
# used SEGMENT=77; the corpus is the same full-precision wire-angle plane, so
# the same segment length applies.
SEGMENT = 77
DIVERGE_THRESH = 4.0  # qu, same as the validated pmove_sim default
# A segment "fails" if its max origin error exceeds this. Human-quality replay
# segments sit at ~0.1-0.6 qu; submodel/lift/player-collision segments blow past
# tens of qu. Pass the demo if >= SEG_PASS_FRAC of segments stay clean.
SEG_FAIL_QU = DIVERGE_THRESH
SEG_PASS_FRAC = 0.90


def _pctl(vals, q):
    if not vals:
        return None
    s = sorted(vals)
    return s[min(len(s) - 1, int(q * (len(s) - 1)))]


# Module-level worker globals (set once per process to avoid re-loading the BSP
# for every demo -- WorldModel.load parses the whole dm3 BSP).
_WORLD = None
_BSP_PATH = None
_SHARD_DIR = None


def _init_worker(bsp_path: str, shard_dir: str):
    global _WORLD, _BSP_PATH, _SHARD_DIR
    sys.setrecursionlimit(20000)
    _BSP_PATH = bsp_path
    _SHARD_DIR = shard_dir
    _WORLD = pmove_sim.WorldModel.load(bsp_path)


def _segmented_replay(frames):
    """1s-segmented free-run with teleport/respawn re-anchoring.

    Returns (label_integrity_dict). Mirrors the validated human-replay method:
    detect recording teleports, re-anchor there, and additionally re-anchor
    every SEGMENT frames so a single contaminated segment cannot poison the
    whole-demo divergence number.
    """
    tele = pmove_sim.detect_teleports(frames)
    summary, rows = pmove_sim.replay(
        _WORLD, frames,
        reanchor_at=tele,
        reanchor_every=SEGMENT,
        diverge_thresh=DIVERGE_THRESH,
    )
    # Per-segment max error (between re-anchor points), excluding the re-anchor
    # rows themselves.
    seg_max = []
    cur = 0.0
    for i, r in enumerate(rows):
        if i > 0 and (i % SEGMENT == 0):
            seg_max.append(cur)
            cur = 0.0
        if not r["teleport_reanchor"]:
            cur = max(cur, r["err"])
    seg_max.append(cur)
    n_seg = len(seg_max)
    n_fail = sum(1 for m in seg_max if m > SEG_FAIL_QU)
    n_clean = n_seg - n_fail
    clean_frac = (n_clean / n_seg) if n_seg else 0.0
    passed = clean_frac >= SEG_PASS_FRAC
    return {
        "method": "1s-segmented free-run, teleport+periodic reanchor",
        "frames_simulated": summary["frames_simulated"],
        "teleport_reanchors": len(tele),
        "segments": n_seg,
        "segments_clean": n_clean,
        "segments_failed": n_fail,
        "clean_segment_frac": round(clean_frac, 4),
        "seg_max_err_p50": round(_pctl(seg_max, 0.5), 3) if seg_max else None,
        "seg_max_err_p95": round(_pctl(seg_max, 0.95), 3) if seg_max else None,
        "seg_max_err_max": round(max(seg_max), 3) if seg_max else None,
        "whole_demo_max_err": summary["max_err"],
        "whole_demo_p95_err": summary["p95_err"],
        "diverge_thresh_qu": DIVERGE_THRESH,
        "seg_pass_frac_threshold": SEG_PASS_FRAC,
        "passed": passed,
    }


def process_one(demo_path: str):
    demo = Path(demo_path)
    t0 = time.time()
    try:
        frames, meta = brc.build_replay_frames(demo, alignment="time")
    except Exception as e:  # noqa: BLE001
        return {"demo": demo.name, "ok": False, "error": f"build:{type(e).__name__}: {e}"}
    if not frames:
        return {"demo": demo.name, "ok": False, "error": "no frames"}

    # movement-quality stats over the BC labels
    hspeeds, air_h, jumps = [], [], 0
    for f in frames:
        vx, vy = f["velocity"][0], f["velocity"][1]
        h = math.hypot(vx, vy)
        hspeeds.append(h)
        if not f["onground"]:
            air_h.append(h)
        if int(f["buttons"]) & pmove_sim.BUTTON_JUMP:
            jumps += 1

    # write the NDJSON BC shard (state + action per frame)
    shard = Path(_SHARD_DIR) / (demo.stem + ".ndjson")
    with shard.open("w", encoding="utf-8") as fh:
        for i, f in enumerate(frames):
            row = {
                "demo": demo.name, "map": meta.get("map_level"), "frame": i,
                "msec": f["msec"], "o": f["origin"], "v": f["velocity"],
                "a": f["angles"], "m": f["move"], "buttons": f["buttons"],
                "onground": f["onground"], "pm_code": f["pm_code"],
            }
            fh.write(json.dumps(row, separators=(",", ":")) + "\n")

    # LABEL INTEGRITY: replay the recorded usercmds through the validated sim.
    # build_replay_frames already carries everything load_cmds_file needs.
    sim_frames = [
        {"msec": f["msec"], "origin": f["origin"], "velocity": f["velocity"],
         "angles": f["angles"], "move": f["move"], "buttons": f["buttons"]}
        for f in frames
    ]
    try:
        li = _segmented_replay(sim_frames)
    except Exception as e:  # noqa: BLE001
        li = {"error": f"replay:{type(e).__name__}: {e}", "passed": False}

    return {
        "demo": demo.name, "ok": True, "map": meta.get("map_level"),
        "frames": len(frames),
        "paired_coverage": meta.get("paired_coverage"),
        "playernum": meta.get("playernum"),
        "source_sha256": meta.get("source_sha256"),
        "peak_hspeed": round(max(hspeeds), 1),
        "p50_hspeed": round(_pctl(hspeeds, 0.5), 1),
        "p90_hspeed": round(_pctl(hspeeds, 0.9), 1),
        "air_frac": round(len(air_h) / len(frames), 3),
        "jumps": jumps,
        "shard": shard.name,
        "label_integrity": li,
        "label_pass": bool(li.get("passed")),
        "build_secs": round(time.time() - t0, 2),
    }


def load_demo_list(list_file: Path):
    """Each line: <player>\t<full_path_to_qwd>  (player optional, tab-sep)."""
    demos = []
    for ln in list_file.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        parts = ln.split("\t")
        path = parts[-1].strip()
        player = parts[0].strip() if len(parts) > 1 else ""
        demos.append((player, path))
    return demos


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo-list", type=Path, required=True,
                    help="TSV: player<TAB>abspath, one self-POV 4on4 dm3 demo per line")
    ap.add_argument("--shard-dir", type=Path, required=True,
                    help="GITIGNORED output dir for NDJSON frame shards (WSL ~ path)")
    ap.add_argument("--manifest", type=Path, required=True,
                    help="output manifest json path")
    ap.add_argument("--bsp", default="/mnt/c/nQuake/qw/maps/dm3.bsp")
    ap.add_argument("--workers", type=int, default=os.cpu_count())
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args(argv)

    args.shard_dir.mkdir(parents=True, exist_ok=True)
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    demos = load_demo_list(args.demo_list)
    if args.limit:
        demos = demos[: args.limit]
    player_by_path = {p: pl for pl, p in demos}
    paths = [p for _, p in demos]
    t0 = time.time()
    print(f"MOVE-BC pool build: {len(paths)} demos, {args.workers} workers, "
          f"bsp={args.bsp}", flush=True)

    rows = []
    ok = fail = 0
    with ProcessPoolExecutor(
        max_workers=args.workers,
        initializer=_init_worker,
        initargs=(args.bsp, str(args.shard_dir)),
    ) as ex:
        futs = {ex.submit(process_one, p): p for p in paths}
        for fut in as_completed(futs):
            r = fut.result()
            r["player"] = player_by_path.get(futs[fut], "")
            rows.append(r)
            ok += int(r["ok"]); fail += int(not r["ok"])
            done = ok + fail
            if done % 25 == 0 or done == len(paths):
                el = time.time() - t0
                print(f"  {done}/{len(paths)} ok={ok} fail={fail} "
                      f"({el:.0f}s, {el/max(done,1):.2f}s/demo)", flush=True)

    ok_rows = [r for r in rows if r["ok"]]
    total_frames = sum(r["frames"] for r in ok_rows)
    pass_rows = [r for r in ok_rows if r["label_pass"]]
    pass_frames = sum(r["frames"] for r in pass_rows)
    players = sorted({r["player"] for r in ok_rows if r["player"]})
    maps = {}
    for r in ok_rows:
        maps[r.get("map")] = maps.get(r.get("map"), 0) + 1

    summary = {
        "schema": "komodobots.stage2.move_bc_pool.v1",
        "generated_unix": int(time.time()),
        "wall_clock_secs": round(time.time() - t0, 1),
        "bsp": args.bsp,
        "demos_attempted": len(paths),
        "demos_ok": ok,
        "demos_build_fail": fail,
        "total_frames": total_frames,
        "distinct_players": len(players),
        "label_integrity_pass_demos": len(pass_rows),
        "label_integrity_pass_rate": round(len(pass_rows) / max(len(ok_rows), 1), 4),
        "label_integrity_pass_frames": pass_frames,
        "label_integrity_pass_frame_rate": round(pass_frames / max(total_frames, 1), 4),
        "label_integrity_method": (
            f"1s-segmented ({SEGMENT}-frame) free-run through validated MVDSV "
            f"pmove_sim port, teleport+respawn re-anchored; demo passes if "
            f">= {int(SEG_PASS_FRAC*100)}% of segments stay within {DIVERGE_THRESH} qu"
        ),
        "maps": maps,
    }
    out = {"summary": summary, "demos": sorted(rows, key=lambda r: -r.get("frames", 0))}
    args.manifest.write_text(json.dumps(out, indent=1))
    print("\n=== DONE ===")
    print(json.dumps(summary, indent=1))
    if fail:
        for r in rows:
            if not r["ok"]:
                print(f"  BUILD-FAIL {r['demo']}: {r.get('error')}")


if __name__ == "__main__":
    sys.setrecursionlimit(20000)
    main()
