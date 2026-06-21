#!/usr/bin/env python3
"""Stage-2 MOVE-BC training (docs/12 Stage 2, MLMove-style discrete BC).

Small MLP -> three discrete action heads (fwd 3-way, side 3-way, jump 2-way),
trained by behavioural cloning on the clean-masked elite self-POV corpus.

Why MLP not GRU: the action at tick t is dominated by the *current* velocity-
relative state (speed + look-lead), which is exactly what QW air-accel keys on;
a stateless MLP keeps the eventual ~0.5 ms/tick CPU budget trivial (a few matmuls
on a 6-dim input) and avoids hidden-state carry in the closed-loop replay. A GRU
variant is left as a documented follow-up if the closed-loop gate shows the MLP
needs phase memory for serpentine cadence.

Train/val split is BY DEMO (held-out demos), never by frame, to avoid leakage:
frames from the same match are highly autocorrelated, so a frame-level split
would inflate val accuracy.

Class imbalance: jump is ~3.3% positive; we weight the jump head's CE by inverse
frequency so the policy doesn't collapse to "never jump" (which would kill bhop).
fwd/side are weighted mildly the same way.

CUDA required (RTX 4090, verified separately). Checkpoint -> --out (gitignored
WSL path).
"""
from __future__ import annotations

import logging
import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn



LOGGER = logging.getLogger(__name__)
FEATURE_NAMES = ["hspeed/320", "vz/320", "lvm_sin", "lvm_cos", "moving", "pitch/90"]
FEATURE_DIM = 6


class MoveMLP(nn.Module):
    def __init__(self, in_dim=FEATURE_DIM, hidden=128):
        super().__init__()
        self.trunk = nn.Sequential(
            nn.Linear(in_dim, hidden), nn.ReLU(),
            nn.Linear(hidden, hidden), nn.ReLU(),
        )
        self.fwd_head = nn.Linear(hidden, 3)
        self.side_head = nn.Linear(hidden, 3)
        self.jump_head = nn.Linear(hidden, 2)

    def forward(self, x):
        h = self.trunk(x)
        return self.fwd_head(h), self.side_head(h), self.jump_head(h)


def split_by_demo(demo_id, val_frac, seed):
    demos = np.unique(demo_id)
    rng = np.random.default_rng(seed)
    rng.shuffle(demos)
    n_val = max(1, int(round(val_frac * len(demos))))
    val_demos = set(demos[:n_val].tolist())
    is_val = np.isin(demo_id, list(val_demos))
    return ~is_val, is_val, sorted(val_demos)


def class_weights(y, k):
    cnts = np.bincount(y, minlength=k).astype(np.float64)
    cnts[cnts == 0] = 1
    w = cnts.sum() / (k * cnts)
    return torch.tensor(w, dtype=torch.float32)


def accuracy(logits, y):
    return (logits.argmax(1) == y).float().mean().item()


def evaluate(model, X, Y, device, bs=1 << 18):
    model.eval()
    accs = [0.0, 0.0, 0.0]
    nll = 0.0
    n = len(X)
    ce = nn.CrossEntropyLoss(reduction="sum")
    with torch.no_grad():
        tot = 0
        for i in range(0, n, bs):
            xb = torch.from_numpy(X[i:i+bs]).to(device)
            yb = torch.from_numpy(Y[i:i+bs].astype(np.int64)).to(device)
            lf, ls, lj = model(xb)
            for h, (lg, col) in enumerate([(lf, 0), (ls, 1), (lj, 2)]):
                accs[h] += (lg.argmax(1) == yb[:, col]).float().sum().item()
            nll += (ce(lf, yb[:, 0]) + ce(ls, yb[:, 1]) + ce(lj, yb[:, 2])).item()
            tot += len(xb)
    return [a / tot for a in accs], nll / tot


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="~/move_bc_dataset.npz")
    ap.add_argument("--out", default="~/move_bc_policy.pt")
    ap.add_argument("--metrics-out", default=None)
    ap.add_argument("--epochs", type=int, default=12)
    ap.add_argument("--batch", type=int, default=8192)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--hidden", type=int, default=128)
    ap.add_argument("--val-frac", type=float, default=0.15)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--tiers", default="0,1,2", help="comma tier ids to include (A=0,B=1,C=2)")
    args = ap.parse_args(argv)

    data_path = Path(args.data).expanduser()
    out_path = Path(args.out).expanduser()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    assert device == "cuda", "CUDA required for this run"
    print(f"torch {torch.__version__} device={torch.cuda.get_device_name(0)}", flush=True)

    d = np.load(data_path, allow_pickle=True)
    X = d["X"].astype(np.float32)
    Y = d["Y"].astype(np.int8)
    demo_id = d["demo_id"]
    tier_id = d["tier_id"]
    keep_tiers = set(int(t) for t in args.tiers.split(","))
    tmask = np.isin(tier_id, list(keep_tiers))
    X, Y, demo_id, tier_id = X[tmask], Y[tmask], demo_id[tmask], tier_id[tmask]
    print(f"loaded X={X.shape} tiers={sorted(keep_tiers)} demos={len(np.unique(demo_id))}", flush=True)

    tr, va, val_demos = split_by_demo(demo_id, args.val_frac, args.seed)
    Xtr, Ytr = X[tr], Y[tr]
    Xva, Yva = X[va], Y[va]
    print(f"train frames={len(Xtr)} ({len(np.unique(demo_id[tr]))} demos)  "
          f"val frames={len(Xva)} ({len(val_demos)} demos)", flush=True)

    wf = class_weights(Ytr[:, 0], 3).to(device)
    ws = class_weights(Ytr[:, 1], 3).to(device)
    wj = class_weights(Ytr[:, 2], 2).to(device)
    print(f"class weights fwd={wf.tolist()} side={ws.tolist()} jump={wj.tolist()}", flush=True)

    model = MoveMLP(hidden=args.hidden).to(device)
    n_params = sum(p.numel() for p in model.parameters())
    print(f"model params={n_params}", flush=True)
    opt = torch.optim.Adam(model.parameters(), lr=args.lr)
    ce_f = nn.CrossEntropyLoss(weight=wf)
    ce_s = nn.CrossEntropyLoss(weight=ws)
    ce_j = nn.CrossEntropyLoss(weight=wj)

    # whole train set on GPU (5M x 6 floats = ~140 MB; labels tiny) for speed
    Xtr_t = torch.from_numpy(Xtr).to(device)
    Ytr_t = torch.from_numpy(Ytr.astype(np.int64)).to(device)
    n = len(Xtr_t)

    history = []
    best_val = -1.0
    t0 = time.time()
    for ep in range(args.epochs):
        model.train()
        perm = torch.randperm(n, device=device)
        run_loss = 0.0
        nb = 0
        for i in range(0, n, args.batch):
            idx = perm[i:i+args.batch]
            xb = Xtr_t[idx]; yb = Ytr_t[idx]
            lf, ls, lj = model(xb)
            loss = ce_f(lf, yb[:, 0]) + ce_s(ls, yb[:, 1]) + ce_j(lj, yb[:, 2])
            opt.zero_grad(); loss.backward(); opt.step()
            run_loss += loss.item(); nb += 1
        tr_acc, tr_nll = evaluate(model, Xtr, Ytr, device)
        va_acc, va_nll = evaluate(model, Xva, Yva, device)
        rec = {
            "epoch": ep,
            "train_loss": round(run_loss / nb, 4),
            "train_acc": {"fwd": round(tr_acc[0], 4), "side": round(tr_acc[1], 4), "jump": round(tr_acc[2], 4)},
            "val_acc": {"fwd": round(va_acc[0], 4), "side": round(va_acc[1], 4), "jump": round(va_acc[2], 4)},
            "train_nll": round(tr_nll, 4), "val_nll": round(va_nll, 4),
        }
        history.append(rec)
        print(f"ep{ep:02d} loss={rec['train_loss']:.3f} "
              f"val_acc fwd={va_acc[0]:.3f} side={va_acc[1]:.3f} jump={va_acc[2]:.3f} "
              f"val_nll={va_nll:.3f} ({time.time()-t0:.0f}s)", flush=True)
        score = (va_acc[0] + va_acc[1] + va_acc[2]) / 3
        if score > best_val:
            best_val = score
            torch.save({
                "state_dict": model.state_dict(),
                "hidden": args.hidden, "feature_names": FEATURE_NAMES,
                "feature_dim": FEATURE_DIM, "arch": "MoveMLP",
                "epoch": ep, "val_acc": va_acc,
            }, out_path)

    print(f"\nbest mean val acc={best_val:.4f}; saved {out_path}", flush=True)
    out = {
        "torch": torch.__version__,
        "device": torch.cuda.get_device_name(0),
        "feature_names": FEATURE_NAMES,
        "action_space": {
            "fwd": "{back, none, fwd} 3-way",
            "side": "{left, none, right} 3-way",
            "jump": "{0,1} BUTTON_JUMP",
        },
        "n_params": n_params,
        "hidden": args.hidden,
        "epochs": args.epochs, "batch": args.batch, "lr": args.lr,
        "tiers": sorted(keep_tiers),
        "train_frames": int(len(Xtr)), "val_frames": int(len(Xva)),
        "train_demos": int(len(np.unique(demo_id[tr]))), "val_demos": len(val_demos),
        "class_weights": {"fwd": wf.tolist(), "side": ws.tolist(), "jump": wj.tolist()},
        "history": history,
        "best_mean_val_acc": round(best_val, 4),
        "checkpoint": str(out_path),
    }
    mp = Path(args.metrics_out).expanduser() if args.metrics_out else out_path.with_suffix(".train.json")
    mp.write_text(json.dumps(out, indent=1))
    print(f"wrote {mp}", flush=True)


if __name__ == "__main__":
    main()
