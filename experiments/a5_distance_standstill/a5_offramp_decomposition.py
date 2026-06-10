#!/usr/bin/env python3
"""A5 #118 off-ramp: WHICH sub-skill fails? (pre-registered analysis)

The 162-config sweep landed 0/4860 attempts. Decompose from the recorded
per-attempt release + lip states (sweep-results.json):

  BUILD    does the circle reach launch speed from standstill?
  RELEASE  does the release fire, where (d_lip), aimed how (herr), or by
           timeout?
  LIP      where do attempts actually cross the lip (y line, heading, vh)?
  ARC      for each lip crossing, the flat-jump ballistic check: does the
           flight reach the far floor (x >= -3048) inside the y band
           [3616, 3804] (platform 3600..3820 inset by the 16 qu hull)?
           Failure classes: SHORT (x reach), Y-OUT (drift off the band),
           NO-JUMP (crossed falling, never jumped).

Writes offramp-decomposition.json and prints the plain-words verdict.
"""
from __future__ import annotations

import gzip
import json
import math
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "sweep-results.json"          # falls back to the committed .gz
OUT = HERE / "offramp-decomposition.json"

FAR_EDGE_X = -3048.0
Y_LO, Y_HI = 3600.0 + 16.0, 3820.0 - 16.0
AIRTIME = 2 * 270.0 / 800.0          # flat +270 jump, z=-488 -> z=-488
AIR_GAIN = 15.0                      # qu of extra carry from air-accel (sim-measured ~10-20)


def main():
    if SRC.exists():
        doc = json.loads(SRC.read_text())
    else:
        with gzip.open(SRC.with_suffix(".json.gz"), "rt", encoding="utf-8") as f:
            doc = json.load(f)
    results = doc["results"]

    n_att = 0
    builds = []          # max_vh per attempt
    releases = []        # release dicts
    timeouts = 0
    never_released = 0
    lips = []            # lip dicts
    arc_classes = Counter()
    per_config = []

    for cfg in results:
        vh_target = cfg["config"]["launch_vh"]
        cfg_classes = Counter()
        for att in cfg["attempts"]:
            n_att += 1
            builds.append((att["max_vh"], vh_target))
            rel = att.get("release")
            if rel:
                releases.append(rel)
                if rel["timeout"]:
                    timeouts += 1
            else:
                never_released += 1
            lip = att.get("lip")
            if lip:
                lips.append(lip)
                # ballistic check from the lip state
                h = math.radians(lip["heading"])
                carry = lip["vh"] * AIRTIME + AIR_GAIN
                x1 = lip["x"] + carry * math.cos(h)
                y1 = lip["y"] + carry * math.sin(h)
                if x1 < FAR_EDGE_X:
                    cls = "SHORT"
                elif not (Y_LO <= y1 <= Y_HI):
                    cls = "Y-OUT"
                else:
                    cls = "WOULD-LAND"
                arc_classes[cls] += 1
                cfg_classes[cls] += 1
            else:
                arc_classes["NO-LIP"] += 1
                cfg_classes["NO-LIP"] += 1
        per_config.append({"name": cfg["name"], **dict(cfg_classes)})

    reached = sum(1 for mv, tgt in builds if mv >= tgt)
    lip_y = Counter()
    for l in lips:
        if l["y"] <= 3620:
            lip_y["south_wall(y<=3620)"] += 1
        elif l["y"] >= 3800:
            lip_y["north_wall(y>=3800)"] += 1
        else:
            lip_y["mid_band"] += 1
    mid_lips = [l for l in lips if 3620 < l["y"] < 3800]
    neg_heading_mid = [l for l in mid_lips if l["heading"] < -3]

    rel_dlip = sorted(r["d_lip"] for r in releases)
    rel_near = sum(1 for r in releases if 0 <= r["d_lip"] <= 45)

    would_land_cfgs = [c for c in per_config if c.get("WOULD-LAND")]

    out = {
        "n_attempts": n_att,
        "build": {
            "reached_launch_vh": reached,
            "share": round(reached / n_att, 3),
            "max_vh_p50": sorted(b[0] for b in builds)[len(builds) // 2],
            "max_vh_p90": sorted(b[0] for b in builds)[int(0.9 * len(builds))],
        },
        "release": {
            "released": len(releases),
            "by_timeout": timeouts,
            "never": never_released,
            "d_lip_p50": rel_dlip[len(rel_dlip) // 2] if rel_dlip else None,
            "released_within_45qu_of_lip": rel_near,
        },
        "lip_crossings": {
            "n": len(lips),
            "y_lines": dict(lip_y),
            "mid_band_with_negative_heading": len(neg_heading_mid),
            "vh_p50": sorted(l["vh"] for l in lips)[len(lips) // 2] if lips else None,
            "heading_hist": dict(Counter(round(l["heading"] / 5) * 5 for l in lips)),
        },
        "arc_classes": dict(arc_classes),
        "configs_with_would_land_lips": would_land_cfgs,
    }
    OUT.write_text(json.dumps(out, indent=1))

    print(f"attempts: {n_att}")
    print(f"BUILD: reached launch_vh in {reached}/{n_att} "
          f"({out['build']['share']:.0%}); max_vh p50={out['build']['max_vh_p50']}"
          f" p90={out['build']['max_vh_p90']}")
    print(f"RELEASE: fired {len(releases)} (timeout {timeouts}, never "
          f"{never_released}); d_lip p50={out['release']['d_lip_p50']}; "
          f"within 45 qu of lip: {rel_near}")
    print(f"LIP: {len(lips)} crossings; y-lines {dict(lip_y)}; "
          f"mid-band negative-heading: {len(neg_heading_mid)}; "
          f"vh p50 {out['lip_crossings']['vh_p50']}")
    print(f"ARC classes: {dict(arc_classes)}")
    print(f"configs with any WOULD-LAND lip state: {len(would_land_cfgs)}")
    for c in would_land_cfgs[:10]:
        print("  ", c)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
