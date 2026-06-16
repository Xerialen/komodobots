#!/usr/bin/env python3
"""Emit the MAINTAINED list of demos the MOVE-BC policy was trained on.

Ground truth = the training input itself (`~/move_bc_dataset.npz`): its `demos`
metadata (demo/tier/player/n_clean) and per-frame `demo_id`. We reproduce
train.py's EXACT by-demo split (split_by_demo, seed=0, val_frac=0.15) to tag each
demo train/val, count the clean frames each contributed, and join provenance
(source_sha256, raw frame count, map, speed stats) from the pool manifest.

This is the canonical training-provenance record. REGENERATE after every
training run that changes ~/move_bc_dataset.npz or ~/move_bc_policy.pt:

    python experiments/stage2/move-bc-train/build_trained_demos_manifest.py

Writes (committed):
    experiments/stage2/move-bc-train/trained-demos.tsv   (one row per demo)
    experiments/stage2/move-bc-train/TRAINED_DEMOS.md    (totals + how-to + run id)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent


def split_by_demo(demo_id, val_frac, seed):
    """VERBATIM copy of train.py split_by_demo (must stay in sync)."""
    demos = np.unique(demo_id)
    rng = np.random.default_rng(seed)
    rng.shuffle(demos)
    n_val = max(1, int(round(val_frac * len(demos))))
    val_demos = set(demos[:n_val].tolist())
    return val_demos


def sha256_file(p: Path, cap=None):
    if not p.exists():
        return None
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.path.expanduser("~/move_bc_dataset.npz"))
    ap.add_argument("--ckpt", default=os.path.expanduser("~/move_bc_policy.pt"))
    ap.add_argument("--manifest", type=Path,
                    default=REPO_ROOT / "experiments/stage2/move-bc-dataset/manifest.json")
    ap.add_argument("--val-frac", type=float, default=0.15)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out-tsv", type=Path, default=HERE / "trained-demos.tsv")
    ap.add_argument("--out-md", type=Path, default=HERE / "TRAINED_DEMOS.md")
    args = ap.parse_args(argv)

    data_path = Path(args.data)
    d = np.load(data_path, allow_pickle=True)
    demos_meta = json.loads(str(d["demos"]))
    demo_id = d["demo_id"]
    n_demo_slots = len(demos_meta)

    # frames per demo slot (only slots that actually contributed appear in demo_id)
    frames_per = np.bincount(demo_id, minlength=n_demo_slots)
    trained_slots = set(int(i) for i in np.unique(demo_id))
    val_demos = split_by_demo(demo_id, args.val_frac, args.seed)

    # provenance join from the pool manifest (by demo filename)
    man = json.loads(args.manifest.read_text())
    prov = {e["demo"]: e for e in man.get("demos", [])}

    rows = []
    for i, m in enumerate(demos_meta):
        if i not in trained_slots:
            continue  # slot had a shard but produced no clean frames -> not trained
        name = m["demo"]
        p = prov.get(name, {})
        rows.append({
            "demo": name,
            "player": m.get("player", ""),
            "tier": m.get("tier", ""),
            "split": "val" if i in val_demos else "train",
            "trained_frames": int(frames_per[i]),
            "raw_frames": p.get("frames", ""),
            "paired_cov": p.get("paired_coverage", ""),
            "peak_hspeed": p.get("peak_hspeed", ""),
            "p50_hspeed": p.get("p50_hspeed", ""),
            "source_sha256": p.get("source_sha256", ""),
        })
    rows.sort(key=lambda r: (r["split"], r["player"], r["demo"]))

    cols = ["demo", "player", "tier", "split", "trained_frames", "raw_frames",
            "paired_cov", "peak_hspeed", "p50_hspeed", "source_sha256"]
    with open(args.out_tsv, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\t".join(cols) + "\n")
        for r in rows:
            fh.write("\t".join(str(r[c]) for c in cols) + "\n")

    n_train = sum(1 for r in rows if r["split"] == "train")
    n_val = sum(1 for r in rows if r["split"] == "val")
    tot_frames = sum(r["trained_frames"] for r in rows)
    train_frames = sum(r["trained_frames"] for r in rows if r["split"] == "train")
    val_frames = sum(r["trained_frames"] for r in rows if r["split"] == "val")
    from collections import Counter
    tier_ct = Counter(r["tier"] for r in rows)
    player_ct = Counter(r["player"] for r in rows)

    data_sha = sha256_file(data_path)
    ckpt_sha = sha256_file(Path(args.ckpt))

    md = []
    md.append("# Trained demos — MOVE-BC policy (maintained provenance record)\n")
    md.append("Canonical list of every demo the MOVE behavioural-cloning policy was "
              "trained on. Generated from the training input itself "
              "(`~/move_bc_dataset.npz`) by `build_trained_demos_manifest.py`. "
              "Full per-demo rows: [`trained-demos.tsv`](trained-demos.tsv).\n")
    md.append("**REGENERATE after every training run** that changes the dataset or "
              "the checkpoint:\n```\npython experiments/stage2/move-bc-train/"
              "build_trained_demos_manifest.py\n```\n")
    md.append("## Run identity\n")
    md.append(f"- dataset: `{data_path.name}`  sha256 `{data_sha}`")
    md.append(f"- checkpoint: `{Path(args.ckpt).name}`  sha256 `{ckpt_sha}`")
    md.append(f"- split: by demo, seed={args.seed}, val_frac={args.val_frac} "
              "(verbatim train.py `split_by_demo`)\n")
    md.append("## Totals\n")
    md.append(f"- **demos trained on: {len(rows)}**  ({n_train} train / {n_val} val)")
    md.append(f"- clean frames: {tot_frames:,}  ({train_frames:,} train / {val_frames:,} val)")
    md.append(f"- tiers: " + ", ".join(f"{k}={tier_ct[k]}" for k in sorted(tier_ct)))
    md.append(f"- distinct players: {len([p for p in player_ct if p])}\n")
    md.append("## Per-player demo count\n")
    md.append("| player | demos | clean frames |")
    md.append("|---|---|---|")
    pf = {}
    for r in rows:
        pf.setdefault(r["player"], [0, 0])
        pf[r["player"]][0] += 1
        pf[r["player"]][1] += r["trained_frames"]
    for pl, (c, fr) in sorted(pf.items(), key=lambda x: -x[1][1]):
        md.append(f"| {pl or '(unknown)'} | {c} | {fr:,} |")
    md.append("")
    args.out_md.write_text("\n".join(md), encoding="utf-8")

    print(f"demos trained on: {len(rows)} ({n_train} train / {n_val} val); "
          f"frames {tot_frames:,} ({train_frames:,}/{val_frames:,})")
    print(f"wrote {args.out_tsv}")
    print(f"wrote {args.out_md}")


if __name__ == "__main__":
    main()
