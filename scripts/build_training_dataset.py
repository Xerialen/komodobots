#!/usr/bin/env python3
"""Batch-extract a directory of POV .qwd demos into per-demo (state,action) NDJSON
training shards + a master manifest, for imitation-learning the QW bunnyhop.

Each NDJSON row is one frame (state + action):
  {demo, map, frame, msec, o:[x,y,z], v:[x,y,z], a:[pitch,yaw,roll],
   m:[fwd,side,up], buttons, onground, pm_code}

The manifest carries per-demo movement-quality stats (peak/median hspeed, air
fraction, jump count) so we can FILTER to high-retention (sustained high-speed)
runs before fitting the policy table -- the trick packs include slides/RJ/telebugs
that are not high-speed bunnyhop.

Reuses build_replay_command_file.build_replay_frames (widened to carry
onground/pm_code) -- the single genuine batch-runner gap the scouts flagged.
"""
from __future__ import annotations

import logging
import argparse
import json
import math
import os
import sys
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed


LOGGER = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from build_replay_command_file import build_replay_frames  # widened: carries onground/pm_code


def _pctl(vals, q):
    if not vals:
        return 0.0
    s = sorted(vals)
    return s[min(len(s) - 1, int(q * (len(s) - 1)))]


def process_one(demo_path: str, out_dir: str):
    demo = Path(demo_path)
    try:
        frames, meta = build_replay_frames(demo)
    except Exception as e:  # noqa: BLE001 - record and skip, never abort the batch
        return {"demo": demo.name, "ok": False, "error": f"{type(e).__name__}: {e}"}
    if not frames:
        return {"demo": demo.name, "ok": False, "error": "no frames"}

    hspeeds, air_hspeeds, jumps = [], [], 0
    for f in frames:
        vx, vy = f["velocity"][0], f["velocity"][1]
        h = math.hypot(vx, vy)
        hspeeds.append(h)
        if not f["onground"]:
            air_hspeeds.append(h)
        if int(f["buttons"]) & 2:
            jumps += 1

    out_path = Path(out_dir) / (demo.stem + ".ndjson")
    with out_path.open("w", encoding="utf-8") as fh:
        for i, f in enumerate(frames):
            row = {
                "demo": demo.name, "map": meta.get("map_level"), "frame": i,
                "msec": f["msec"], "o": f["origin"], "v": f["velocity"],
                "a": f["angles"], "m": f["move"], "buttons": f["buttons"],
                "onground": f["onground"], "pm_code": f["pm_code"],
            }
            fh.write(json.dumps(row, separators=(",", ":")) + "\n")

    return {
        "demo": demo.name, "ok": True, "map": meta.get("map_level"),
        "frames": len(frames), "paired_coverage": meta.get("paired_coverage"),
        "peak_hspeed": round(max(hspeeds), 1),
        "p50_hspeed": round(_pctl(hspeeds, 0.5), 1),
        "p90_hspeed": round(_pctl(hspeeds, 0.9), 1),
        "air_frac": round(len(air_hspeeds) / len(frames), 3),
        "jumps": jumps, "ndjson": out_path.name,
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo-dir", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--workers", type=int, default=os.cpu_count())
    ap.add_argument("--limit", type=int, default=0, help="process only first N (0=all)")
    args = ap.parse_args(argv)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    demos = sorted(args.demo_dir.glob("*.qwd"))
    if args.limit:
        demos = demos[: args.limit]
    print(f"extracting {len(demos)} demos -> {args.out_dir} with {args.workers} workers", flush=True)

    manifest, ok, fail = [], 0, 0
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(process_one, str(d), str(args.out_dir)): d for d in demos}
        for fut in as_completed(futs):
            r = fut.result()
            manifest.append(r)
            ok += int(r["ok"]); fail += int(not r["ok"])
            if (ok + fail) % 100 == 0:
                print(f"  {ok+fail}/{len(demos)} (ok={ok} fail={fail})", flush=True)

    (args.out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1))
    ok_rows = [m for m in manifest if m["ok"]]
    print(f"DONE ok={ok} fail={fail}")
    if ok_rows:
        peaks = sorted((m["peak_hspeed"] for m in ok_rows), reverse=True)
        hi = [m for m in ok_rows if m["peak_hspeed"] > 700]
        print(f"  peak hspeed: max={peaks[0]} median={peaks[len(peaks)//2]}")
        print(f"  demos peak>700: {len(hi)} / {len(ok_rows)}")
        from collections import Counter
        maps = Counter(m.get("map") for m in ok_rows)
        print(f"  maps: {dict(maps.most_common(15))}")
    if fail:
        errs = [m for m in manifest if not m["ok"]][:8]
        for e in errs:
            print(f"  FAIL {e['demo']}: {e.get('error')}")


if __name__ == "__main__":
    main()
