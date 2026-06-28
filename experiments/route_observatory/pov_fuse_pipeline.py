#!/usr/bin/env python3
"""pov_fuse_pipeline.py — the linked, canon-driven POV-fusion pipeline (#421 T2.2).

ONE command turns a #420 Route Canon highway into (a) the quantified human-movement signature and
(b) a fused POV+route contact sheet that passes an eval-integrity (L1) pixel check — instead of
running the three tools by hand. Links the existing trio:
   pov_fuse_extract.build_leg  ->  pov_fuse_render.py  ->  pov_fuse_shot.js
This is the Phase-1 LIVE TEST (docs/28:85): "pov_fuse contact sheet + pixel checks (eval-integrity)
+ by-eye sanity. Not testing whether the bot is good yet" — a plumbing gate.

L1 eval-integrity (per fused row): the POV frame is PRESENT, NON-DEGENERATE, and its match-second
falls inside the leg window. The frame<->state OFFSET is per-frame-SOURCE and is calibrated BY-EYE
once per demo (reuse the demo-eyecheck skill: a HUD armor/health drop on the tick a decoded item
pickup / self-damage fires), then passed as --offset; pass --offset-verified once you have eyeballed
that anchor. Without it, rows are flagged `offset-unverified` (fail-loud, never silently aligned) —
this closes the silent warmup-desync risk. Frame VARIANCE needs Pillow (integration-only); absent
it, L1 still runs present + window + offset checks and records variance as "skipped".

The seed line is #428's MSE centerline; this pipeline VALIDATES + quantifies it, it does not score it.

Usage:
  pov_fuse_pipeline.py <route_canon.json> <highway-id> --analysis <alias>=<full.json>
                       --frames <dir> [--offset 1695] [--offset-verified] [--out-dir <dir>]
                       [--no-shot]
  Env: POV_FUSE_NODE_PATH (node_modules for pov_fuse_shot.js; default /home/ubuntu/mapviz/node_modules)
"""
import logging
import json
import math
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from pov_fuse_extract import build_leg  # noqa: E402

LOGGER = logging.getLogger(__name__)

VAR_FLOOR = 25.0   # grayscale pixel variance below this = a black/error/blank frame (real ~10^2-10^3)
DEFAULT_NODE_PATH = "/home/ubuntu/mapviz/node_modules"


# ---- pure L1 decision logic (unit-tested in tests/test_pov_fuse_pipeline.py) --------------------
def l1_row_verdict(present, variance, var_floor, s, t0_s, t1_s, offset_verified):
    """Decide one fused row's eval-integrity. Pure (no I/O). Returns (status, reason) where status
    is one of 'pass' | 'fail' | 'offset-unverified'. variance is None when Pillow is absent (the
    variance check is skipped, NOT failed)."""
    if not present:
        return "fail", f"POV frame for second {s} missing"
    if not (math.floor(t0_s) <= s <= math.ceil(t1_s)):
        return "fail", f"frame second {s} outside leg window [{t0_s}, {t1_s}]"
    if variance is not None and variance < var_floor:
        return "fail", f"degenerate frame (variance {round(variance, 1)} < {var_floor})"
    if not offset_verified:
        return "offset-unverified", "frame<->state offset not anchor-verified for this demo"
    return "pass", "ok" if variance is not None else "ok (variance skipped — no Pillow)"


def frame_variance(path):
    """Mean grayscale pixel variance via Pillow; None if Pillow absent (integration-only). A real
    game frame is high-variance; a black/error frame is ~0."""
    try:
        from PIL import Image, ImageStat
    except ImportError:
        return None
    try:
        return ImageStat.Stat(Image.open(path).convert("L")).var[0]
    except Exception as e:                       # noqa: BLE001 — any decode failure = unusable frame
        LOGGER.warning("variance read failed for %s: %s", path, e)
        return None


def l1_check(leg, frames_dir, offset_verified, var_floor=VAR_FLOOR):
    """Run L1 over a leg bundle's frames. Returns (rows, summary)."""
    t0, t1 = leg["match_t0"], leg["match_t1"]
    rows, counts = [], {"pass": 0, "fail": 0, "offset-unverified": 0}
    for fr in leg["frames"]:
        path = os.path.join(frames_dir, fr["file"])
        present = fr.get("exists") and os.path.exists(path)
        var = frame_variance(path) if present else None
        status, reason = l1_row_verdict(present, var, var_floor, fr["s"], t0, t1, offset_verified)
        counts[status] += 1
        rows.append({"s": fr["s"], "file": fr["file"], "video_t": fr["video_t"],
                     "variance": (round(var, 1) if var is not None else None),
                     "status": status, "reason": reason})
    return rows, counts


# ---- driver -------------------------------------------------------------------------------------
def _find_highway(canon, hid):
    for h in canon["highways"]:
        if h["id"] == hid:
            return h
    raise SystemExit(f"highway {hid!r} not found; have: {[h['id'] for h in canon['highways']]}")


def run(canon_path, hid, amap, frames_dir, offset, offset_verified, out_dir, do_shot):
    os.makedirs(out_dir, exist_ok=True)
    canon = json.loads(open(canon_path, encoding="utf-8").read())
    hw = _find_highway(canon, hid)
    seed = hw["seed"]
    apath = amap.get(seed["demo"])
    if not apath:
        raise SystemExit(f"no --analysis mapping for highway seed demo {seed['demo']!r}")
    d = json.loads(open(apath, encoding="utf-8").read())

    leg = build_leg(d, seed["player"], float(seed["start_s"]), float(seed["end_s"]),
                    frames_dir, offset, label=hw["label"])
    leg_path = os.path.join(out_dir, f"{hid}.leg.json")
    json.dump(leg, open(leg_path, "w", encoding="utf-8"))

    html = os.path.join(out_dir, f"{hid}.pov_fuse.html")
    subprocess.run([sys.executable, os.path.join(HERE, "pov_fuse_render.py"), leg_path,
                    frames_dir, html], check=True)

    png = os.path.join(out_dir, f"{hid}.pov_fuse.png")
    if do_shot:
        env = dict(os.environ, NODE_PATH=os.environ.get("POV_FUSE_NODE_PATH", DEFAULT_NODE_PATH))
        rows_dir = os.path.join(out_dir, f"{hid}.rows")
        os.makedirs(rows_dir, exist_ok=True)
        r = subprocess.run(["node", os.path.join(HERE, "pov_fuse_shot.js"), html, png,
                            "--rows", rows_dir], env=env)
        if r.returncode != 0:
            LOGGER.warning("pov_fuse_shot.js exited %d — sheet HTML still written to %s",
                           r.returncode, html)

    rows, counts = l1_check(leg, frames_dir, offset_verified)
    sig = leg["signature"]
    report = {
        "schema": "komodobots.pov_fuse_report.v1",
        "highway": hid, "label": hw["label"], "route_class": hw["route_class"],
        "seed": seed, "offset": offset, "offset_verified": offset_verified,
        "signature": sig, "contact_sheet": os.path.basename(png) if do_shot else None,
        "l1": {"counts": counts, "var_floor": VAR_FLOOR, "rows": rows},
    }
    rpath = os.path.join(out_dir, f"{hid}.pov_fuse_report.json")
    json.dump(report, open(rpath, "w", encoding="utf-8"), indent=1)

    print(f"highway {hid} [{hw['route_class']}] {hw['label']}")
    print(f"  signature: {sig['dur_s']}s  hspeed {sig['hs_min']}/{sig['hs_mean']}/{sig['hs_max']}  "
          f"{sig['jumps']} jumps (mean int {sig['jump_interval_mean_s']}s)  "
          f"straightness {sig['straightness']}")
    print(f"  L1: {counts['pass']} pass / {counts['fail']} fail / "
          f"{counts['offset-unverified']} offset-unverified  (var_floor {VAR_FLOOR})")
    print(f"  WROTE {rpath}" + (f" + {png}" if do_shot else ""))
    return report


def main(argv):
    canon_path = hid = frames_dir = out_dir = None
    offset, offset_verified, do_shot, amap = 1695, False, True, {}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--analysis":
            key, _, val = argv[i + 1].partition("="); amap[key] = val; i += 2
        elif a == "--frames":
            frames_dir = argv[i + 1]; i += 2
        elif a == "--offset":
            offset = int(argv[i + 1]); i += 2
        elif a == "--offset-verified":
            offset_verified = True; i += 1
        elif a == "--out-dir":
            out_dir = argv[i + 1]; i += 2
        elif a == "--no-shot":
            do_shot = False; i += 1
        elif canon_path is None:
            canon_path = a; i += 1
        elif hid is None:
            hid = a; i += 1
        else:
            raise SystemExit(f"unexpected arg: {a!r}")
    if not (canon_path and hid and frames_dir):
        raise SystemExit("usage: pov_fuse_pipeline.py <route_canon.json> <highway-id> "
                         "--analysis <alias>=<full.json> --frames <dir> [--offset N] "
                         "[--offset-verified] [--out-dir <dir>] [--no-shot]")
    out_dir = out_dir or os.path.join(os.path.dirname(os.path.abspath(canon_path)), "pov_fuse_out")
    run(canon_path, hid, amap, frames_dir, offset, offset_verified, out_dir, do_shot)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    main(sys.argv[1:])
