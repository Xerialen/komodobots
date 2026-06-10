#!/usr/bin/env python3
"""A5 #118 off-ramp: WHICH sub-skill fails? (pre-registered analysis)

The 162-config sweep landed 0/4860 attempts. Decompose from the recorded
per-attempt release + lip states (sweep-results.json):

  BUILD    does the circle reach launch speed from standstill?
  RELEASE  does the release fire, where (d_lip), aimed how (herr), or by
           timeout?
  LIP      where do attempts actually cross the lip (y line, heading, vh)?
  ARC      classify each lip crossing FIRST by whether the launch had
           RELEASED at-or-before the crossing (release fires the jump on
           the spot, so released-by-then == jumped): un-released crossings
           are NO-JUMP walk-offs — they fall from platform height and can
           NEVER reach the same-height far floor, no arc math applied
           (Codex PR #120 P2: applying jump airtime to walk-offs would
           fake their reach). JUMPED crossings get the flat-jump ballistic
           check: carry vh*0.675 (+air gain) must reach the far floor
           (x >= -3048) inside the y band [3616, 3804] (platform
           3600..3820 inset by the 16 qu hull). Classes: NO-JUMP,
           SHORT (x reach), Y-OUT (off the band), WOULD-LAND.

Writes offramp-decomposition.json and prints the plain-words verdict.

Round 2 (carve sweep): same decomposition over carve results via
  python a5_offramp_decomposition.py --src carve-sweep-results.json \
      --out carve-offramp-decomposition.json
Attempts carrying the additive "carve" key additionally get the CARVE
funnel: armed share, release-rule histogram, armed/release geometry vs the
round-1 wall-slide family (y=3824, heading 0, vh 430-435) — did the carve
bend the release -8..-12 deg and lift vh toward ~470? Zero-arg behavior is
unchanged (round-1 source, round-1 output, no funnel block).
"""
from __future__ import annotations

import argparse
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


def _pct(sorted_vals, p):
    return sorted_vals[min(len(sorted_vals) - 1, int(p * len(sorted_vals)))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(SRC),
                    help="sweep results json (falls back to <src>.gz)")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()
    src, out_path = Path(args.src), Path(args.out)

    if src.exists():
        doc = json.loads(src.read_text())
    else:
        with gzip.open(src.with_suffix(".json.gz"), "rt", encoding="utf-8") as f:
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
    carve_enabled = 0    # attempts carrying the additive "carve" key
    carve_armed = []     # the non-None carve records
    carve_releases = []  # release dicts of carve-armed attempts

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
            if "carve" in att:                 # round-2 records only
                carve_enabled += 1
                if att["carve"] is not None:
                    carve_armed.append(att["carve"])
                    if rel:
                        carve_releases.append(rel)
            lip = att.get("lip")
            if lip:
                lips.append(lip)
                # jumped at the crossing? The recorded cmd bit at the last
                # grounded row is the ground truth (harness lip_state
                # "jump"; Codex round 2 — release timestamps are recorded
                # one tick late and cannot separate an on-lip release from
                # a post-lip mid-air timeout). Walk-offs fall from z=-488
                # and can never reach the same-height far floor.
                jumped = lip.get("jump") == 1
                if not jumped:
                    cls = "NO-JUMP"
                else:
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

    # round-2 carve funnel (only when the records carry the "carve" key)
    carve_funnel = None
    if carve_enabled:
        rules = Counter((c["rule"] or "none") for c in carve_armed)
        a_vh = sorted(c["armed_vh"] for c in carve_armed)
        a_herr = sorted(c["armed_herr"] for c in carve_armed)
        a_dlip = sorted(c["armed_d_lip"] for c in carve_armed)
        ticks = sorted(c["ticks"] for c in carve_armed)
        r_vh = sorted(r["vh"] for r in carve_releases)
        r_head = sorted(r["heading"] for r in carve_releases)
        r_dlip = sorted(r["d_lip"] for r in carve_releases)
        r_y = sorted(r["pos"][1] for r in carve_releases)
        carve_funnel = {
            "enabled_attempts": carve_enabled,
            "armed": len(carve_armed),
            "armed_share": round(len(carve_armed) / carve_enabled, 3),
            "rules": dict(rules),
            "armed_vh_p50": _pct(a_vh, 0.5) if a_vh else None,
            "armed_herr_p50": _pct(a_herr, 0.5) if a_herr else None,
            "armed_d_lip_p50": _pct(a_dlip, 0.5) if a_dlip else None,
            "carve_ticks_p50": _pct(ticks, 0.5) if ticks else None,
            # vs the round-1 wall-slide family (y=3824, heading 0, vh 430-435):
            # the pre-registered question is whether the carve bent the
            # release -8..-12 deg and lifted vh toward ~470
            "release_vh_p50": _pct(r_vh, 0.5) if r_vh else None,
            "release_vh_p90": _pct(r_vh, 0.9) if r_vh else None,
            "release_heading_p50": _pct(r_head, 0.5) if r_head else None,
            "release_d_lip_p50": _pct(r_dlip, 0.5) if r_dlip else None,
            "release_y_p50": _pct(r_y, 0.5) if r_y else None,
        }

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
    if carve_funnel is not None:
        out["carve_funnel"] = carve_funnel
    out_path.write_text(json.dumps(out, indent=1))

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
    if carve_funnel is not None:
        cf = carve_funnel
        print(f"CARVE funnel: armed {cf['armed']}/{cf['enabled_attempts']} "
              f"({cf['armed_share']:.0%}); rules {cf['rules']}")
        print(f"  armed: vh p50 {cf['armed_vh_p50']}, herr p50 "
              f"{cf['armed_herr_p50']}, d_lip p50 {cf['armed_d_lip_p50']}, "
              f"ticks p50 {cf['carve_ticks_p50']}")
        print(f"  release vs wall-slide (y=3824, heading 0, vh 430-435): "
              f"vh p50 {cf['release_vh_p50']} p90 {cf['release_vh_p90']}, "
              f"heading p50 {cf['release_heading_p50']}, d_lip p50 "
              f"{cf['release_d_lip_p50']}, y p50 {cf['release_y_p50']}")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
