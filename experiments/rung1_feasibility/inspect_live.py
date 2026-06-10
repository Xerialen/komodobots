#!/usr/bin/env python3
"""Ad-hoc inspection of live-lip.json (run groupings + crossing character)."""
import json
import sys
from collections import Counter
from pathlib import Path
from statistics import median

EXP = Path(__file__).resolve().parent
d = json.loads((EXP / "live-lip.json").read_text())

print("=== run id clusters (gap > 5 min starts a new cluster) ===")
ids = [r["run_id"] for r in d["runs"]]


def mins(rid):
    """Run-id timestamp in minutes (YYYYMMDDTHHMMSSZ)."""
    return (int(rid[6:8]) * 1440 + int(rid[9:11]) * 60 + int(rid[11:13])
            + int(rid[13:15]) / 60.0)


clusters, cur = [], [ids[0]]
for a, b in zip(ids, ids[1:]):
    if mins(b) - mins(a) > 5:
        clusters.append(cur)
        cur = []
    cur.append(b)
clusters.append(cur)
for c in clusters:
    print(f"  n={len(c):2d}  {c[0]} .. {c[-1]}")

print("\n=== crossing audit: cross_track / position / vh ===")
xs = [a["crossing"] for r in d["runs"] for a in r["attempts"] if a["crossing"]]
ct = sorted(x["cross_track"] for x in xs)
print(f"crossings {len(xs)}; cross_track min/med/max = {ct[0]}/{median(ct)}/{ct[-1]}")
print("cross_track histogram (20-qu bins):",
      dict(sorted(Counter(int(x["cross_track"] // 20) * 20 for x in xs).items())))
print("edge_hdist histogram (40-qu bins):",
      dict(sorted(Counter(int(x["edge_hdist"] // 40) * 40 for x in xs).items())))
lo = [x for x in xs if x["cross_track"] <= 80]
print(f"\nlow-cross-track (<=80) crossings: {len(lo)}; vh sorted: "
      f"{sorted(round(x['vh']) for x in lo)}")
hi = [x for x in xs if x["cross_track"] > 80]
print(f"high-cross-track (>80) crossings: {len(hi)}; vh sorted: "
      f"{sorted(round(x['vh']) for x in hi)}")

print("\n=== lip approach: hdist / vh / heading / grounded ===")
ap = [a["lip_approach"] for r in d["runs"] for a in r["attempts"]
      if a["lip_approach"]]
print(f"approaches {len(ap)}")
print("hdist sorted:", sorted(round(a["hdist"]) for a in ap))
inlip = [a for a in ap if a["hdist"] < 80]
print(f"\nwithin 80 qu (= reached_lip): {len(inlip)}")
print("  vh sorted:", sorted(round(a["vh"]) for a in inlip))
print("  grounded share:", sum(a["onground"] for a in inlip), "/", len(inlip))
print("  headings:", sorted(a["heading"] for a in inlip if a["heading"] is not None))
print("  z values:", sorted(round(a["z"]) for a in inlip))
