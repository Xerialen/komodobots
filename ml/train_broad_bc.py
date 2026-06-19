#!/usr/bin/env python3
"""train_broad_bc.py — BROAD behavioral-cloning trainer for the dm3 4on4 stand-in.

THE PRODUCTION TRAINER. Runs on host `pinnacle` (offline RTX 4090, WSL2) inside the
ml venv (`ml/requirements.txt`: torch + numpy). It is the BROAD counterpart of the
move-only Stage-2 template (`experiments/stage2/move-bc-train/train.py`):

  move-only template          this trainer (BROAD)
  --------------------------  ---------------------------------------------------
  input: 6-dim self-movement  input: full POMDP agent_observation
                                 [ self obs | observed-other entities (+mask) |
                                   audio | team ]   (enemy- AND team-aware)
  heads: fwd/side/jump (3)    heads: fwd/side/up/jump/attack (broad usercmd)
  model: flat MLP             model: per-entity encoder + masked DeepSets pool + MLP

It consumes FEAT's gold shards in the SHARD CONTRACT (see ml/broad_bc/shard_contract.py
and ml/BROAD_BC.md). Train/val split is BY DEMO (dataset_spec split_policy). Emits a
checkpoint, metrics.json (per-head val action-accuracy) and a model-card stub pinning
git_sha / registry_version / norm artifact_version / seed.

The DATA loading, split, label-encoding, metrics and model-card are the SAME deps-free
code the offline CPU smoke uses (`ml/broad_bc/core.py`), so the smoke exercises the
real contract; only the matmul backend (torch here) differs.

Reproducibility: fixed seed across python/numpy/torch + deterministic algorithms.

Run on pinnacle (offline):  see ml/BROAD_BC.md "PINNACLE GPU RUN".
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

HERE = Path(__file__).resolve().parent          # ml/
REPO_ROOT = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from broad_bc import shard_contract as SC      # noqa: E402
from broad_bc import core                      # noqa: E402


# =============================================================================
# Model: per-entity encoder + masked mean-pool (DeepSets) + trunk + multi-head
# =============================================================================
class BroadBCPolicy(nn.Module):
    """BROAD policy.

    Inputs (already normalized by FEAT):
      obs   : [B, F_obs]            self features
      ent   : [B, N_max, F_ent]     per observed-other egocentric vectors
      emask : [B, N_max]            1=real other-actor, 0=pad
      aux   : [B, F_aux]            concat(audio, team)  (may be width 0)

    The entity set is encoded per-slot then mean-pooled over the MASK (permutation-
    and count-invariant; pad slots contribute nothing) -> a fixed entity summary.
    [obs | entity_summary | aux] -> shared trunk -> one linear head per action head.
    """

    def __init__(self, f_obs, f_ent, f_aux, n_max, *, ent_hidden=64, ent_out=64,
                 hidden=256, head_dims=(3, 3, 3, 2, 2)):
        super().__init__()
        self.n_max = n_max
        self.f_ent = f_ent
        self.ent_enc = nn.Sequential(
            nn.Linear(f_ent, ent_hidden), nn.ReLU(),
            nn.Linear(ent_hidden, ent_out), nn.ReLU(),
        ) if f_ent > 0 else None
        trunk_in = f_obs + (ent_out if f_ent > 0 else 0) + f_aux
        self.trunk = nn.Sequential(
            nn.Linear(trunk_in, hidden), nn.ReLU(),
            nn.Linear(hidden, hidden), nn.ReLU(),
        )
        self.heads = nn.ModuleList([nn.Linear(hidden, k) for k in head_dims])

    def forward(self, obs, ent, emask, aux):
        parts = [obs]
        if self.ent_enc is not None and self.f_ent > 0:
            B, N, F = ent.shape
            enc = self.ent_enc(ent.reshape(B * N, F)).reshape(B, N, -1)
            m = emask.unsqueeze(-1)                       # [B,N,1]
            summed = (enc * m).sum(dim=1)                 # masked sum
            cnt = emask.sum(dim=1, keepdim=True).clamp(min=1.0)
            pooled = summed / cnt                         # masked mean
            parts.append(pooled)
        if aux is not None and aux.shape[-1] > 0:
            parts.append(aux)
        h = self.trunk(torch.cat(parts, dim=-1))
        return [head(h) for head in self.heads]


# =============================================================================
# Tensorize the deps-free rows for torch (keeps obs/ent/aux structured so the
# DeepSets pooling sees the real entity set, not a pre-pooled vector).
# =============================================================================
def rows_to_tensors(shard_paths, schema, device):
    """Read shards -> structured tensors. Unlike the smoke (which pre-pools in the
    input vector), here we keep ent + mask so the model pools with learned weights.
    Returns dict of tensors + dims + per-row demo ids + labels."""
    OBS, ENT, EM, AUX, Y, DEMO, W = [], [], [], [], [], [], []
    f_obs = f_ent = n_max = f_aux = None
    for p in shard_paths:
        shard = core.read_shard(p)
        meta = shard.get(SC.KEY_META, {})
        default_demo = meta.get("demo_id", "?")
        # Reject stale/future shards: a shard whose registry_version differs from
        # the version the model card pins (EXPECTS_REGISTRY_VERSION) is misbound —
        # the obs/entities/act column meanings may have changed. Fail BEFORE the
        # GPU run rather than silently train on misaligned inputs/labels. A shard
        # that omits registry_version (e.g. legacy) is treated as matching.
        rv = meta.get("registry_version")
        if rv is not None and int(rv) != SC.EXPECTS_REGISTRY_VERSION:
            raise ValueError(
                f"shard registry_version {rv} != expected "
                f"{SC.EXPECTS_REGISTRY_VERSION} (shard={p}, demo_id={default_demo}); "
                f"refusing to train on a mismatched FEAT shard")
        obs = shard[SC.KEY_OBS]
        ent = shard.get(SC.KEY_ENTITIES)
        em = shard.get(SC.KEY_ENT_MASK)
        audio = shard.get(SC.KEY_AUDIO)
        team = shard.get(SC.KEY_TEAM)
        act = shard[SC.KEY_ACT]
        mask = shard.get(SC.KEY_MASK)
        # per-window demo id (Parquet); .npz falls back to the single meta.demo_id.
        demo_ids = shard.get(SC.KEY_DEMO_IDS)
        weight = shard.get(SC.KEY_WEIGHT)
        for wi in range(len(obs)):
            wmask = mask[wi] if mask is not None else [1.0] * len(obs[wi])
            ti = core._last_real_tick(wmask)
            if float(wmask[ti]) < 0.5:
                continue
            OBS.append([float(v) for v in obs[wi][ti]])
            if ent is not None and em is not None:
                ENT.append([[float(v) for v in slot] for slot in ent[wi][ti]])
                EM.append([float(v) for v in em[wi][ti]])
            aux_row = []
            if audio is not None:
                aux_row += [float(v) for v in audio[wi][ti]]
            if team is not None:
                aux_row += [float(v) for v in team[wi][ti]]
            AUX.append(aux_row)
            Y.append(SC.encode_action_row(act[wi][ti], schema))
            DEMO.append(demo_ids[wi] if demo_ids is not None else default_demo)
            # per-step shard loss weight (action confidence): 0 for pad / interp /
            # missing-label rows. The smoke's deps-free path already honors this;
            # carry it so the torch CE below can mask/weight per-sample (a weight=0
            # row must not move the loss or gradients). Default 1.0 if absent.
            W.append(float(weight[wi][ti]) if weight is not None else 1.0)
    f_obs = len(OBS[0])
    if ENT:
        n_max = len(ENT[0]); f_ent = len(ENT[0][0])
    else:
        n_max = schema.n_max; f_ent = 0
    f_aux = len(AUX[0]) if AUX and AUX[0] else 0
    t = {
        "obs": torch.tensor(OBS, dtype=torch.float32, device=device),
        "ent": (torch.tensor(ENT, dtype=torch.float32, device=device)
                if f_ent > 0 else torch.zeros((len(OBS), n_max, 0), device=device)),
        "emask": (torch.tensor(EM, dtype=torch.float32, device=device)
                  if f_ent > 0 else torch.zeros((len(OBS), n_max), device=device)),
        "aux": (torch.tensor(AUX, dtype=torch.float32, device=device)
                if f_aux > 0 else torch.zeros((len(OBS), 0), device=device)),
        "y": torch.tensor(Y, dtype=torch.long, device=device),
        "w": torch.tensor(W, dtype=torch.float32, device=device),
        "demo": DEMO,
    }
    return t, {"f_obs": f_obs, "f_ent": f_ent, "n_max": n_max, "f_aux": f_aux}


def demo_split_idx(demos, val_frac, seed):
    rows = [{"demo_id": d} for d in demos]
    tr, va, val_demos = core.split_by_demo(rows, val_frac=val_frac, seed=seed)
    val_set = set(val_demos)
    tr_idx = [i for i, d in enumerate(demos) if d not in val_set]
    va_idx = [i for i, d in enumerate(demos) if d in val_set]
    return tr_idx, va_idx, val_demos


def evaluate(model, t, idx, head_specs, bs=8192):
    model.eval()
    accs = [0] * len(head_specs)
    n = len(idx)
    idx_t = torch.tensor(idx, dtype=torch.long, device=t["obs"].device)
    with torch.no_grad():
        for i in range(0, n, bs):
            sl = idx_t[i:i + bs]
            logits = model(t["obs"][sl], t["ent"][sl], t["emask"][sl], t["aux"][sl])
            y = t["y"][sl]
            for h, lg in enumerate(logits):
                accs[h] += (lg.argmax(1) == y[:, h]).sum().item()
    return {name: {"val_acc": round(accs[h] / max(n, 1), 6)}
            for h, (name, _k) in enumerate(head_specs)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--shards", nargs="+", required=True,
                    help="FEAT gold shard files (.parquet — the real build — or .npz), "
                         "or a glob expanded by the shell")
    ap.add_argument("--out", type=Path, default=Path("~/broad_bc_policy.pt").expanduser())
    ap.add_argument("--metrics-out", type=Path, default=None)
    ap.add_argument("--model-card-out", type=Path, default=None)
    ap.add_argument("--norm-artifact", type=Path, default=None,
                    help="normalization_stats.json (for artifact_version in the card)")
    ap.add_argument("--epochs", type=int, default=20)
    ap.add_argument("--batch", type=int, default=4096)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--hidden", type=int, default=256)
    ap.add_argument("--ent-out", type=int, default=64)
    ap.add_argument("--val-frac", type=float, default=0.1)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--cpu", action="store_true", help="force CPU (tiny debug only)")
    args = ap.parse_args(argv)

    # --- reproducibility ----------------------------------------------------
    import random as _random
    _random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    try:
        torch.use_deterministic_algorithms(True, warn_only=True)
    except Exception:  # noqa: BLE001
        pass

    device = "cpu" if args.cpu else ("cuda" if torch.cuda.is_available() else "cpu")
    if device == "cuda":
        torch.cuda.manual_seed_all(args.seed)
        print(f"torch {torch.__version__} device={torch.cuda.get_device_name(0)}",
              flush=True)
    else:
        print(f"torch {torch.__version__} device=cpu", flush=True)

    schema = SC.ShardSchema()
    head_specs = [(n, k) for (n, k, _c, _kind) in schema.heads()]
    head_dims = [k for (_n, k) in head_specs]

    # --- load (structured) --------------------------------------------------
    t, dims = rows_to_tensors(args.shards, schema, device)
    n_rows = t["obs"].shape[0]
    tr_idx, va_idx, val_demos = demo_split_idx(t["demo"], args.val_frac, args.seed)
    print(f"loaded rows={n_rows} dims={dims} "
          f"train={len(tr_idx)} val={len(va_idx)} val_demos={val_demos}", flush=True)

    model = BroadBCPolicy(
        dims["f_obs"], dims["f_ent"], dims["f_aux"], dims["n_max"],
        ent_out=args.ent_out, hidden=args.hidden, head_dims=head_dims,
    ).to(device)
    n_params = sum(p.numel() for p in model.parameters())
    print(f"BroadBCPolicy params={n_params}", flush=True)

    # class-weighted CE per head (inverse frequency; broad heads imbalanced).
    # reduction='none' so we get PER-SAMPLE loss and can additionally apply the
    # per-step shard weight below (the `weight=` arg is the per-CLASS imbalance
    # weight, which we keep; the per-SAMPLE shard weight is a separate factor).
    ce = []
    for h, (_name, k) in enumerate(head_specs):
        cnts = torch.bincount(t["y"][tr_idx, h], minlength=k).float()
        cnts[cnts == 0] = 1.0
        w = cnts.sum() / (k * cnts)
        ce.append(nn.CrossEntropyLoss(weight=w.to(device), reduction="none"))

    opt = torch.optim.Adam(model.parameters(), lr=args.lr)
    tr_idx_t = torch.tensor(tr_idx, dtype=torch.long, device=device)

    history = []
    best = -1.0
    t0 = time.time()
    for ep in range(args.epochs):
        model.train()
        perm = tr_idx_t[torch.randperm(len(tr_idx_t), device=device)]
        run = 0.0
        nb = 0
        for i in range(0, len(perm), args.batch):
            sl = perm[i:i + args.batch]
            logits = model(t["obs"][sl], t["ent"][sl], t["emask"][sl], t["aux"][sl])
            y = t["y"][sl]
            sw = t["w"][sl]                                  # [B] per-sample weight
            # per-sample CE summed over heads (each ce[h] is reduction='none' -> [B])
            per_sample = sum(ce[h](logits[h], y[:, h])
                             for h in range(len(head_specs)))   # [B]
            wsum = sw.sum()
            if float(wsum) > 0.0:
                # weighted mean: zero-weight rows contribute nothing to loss/grad
                loss = (per_sample * sw).sum() / wsum
            else:
                # whole batch zero-weighted -> skip (no signal); keep grads clean
                opt.zero_grad()
                continue
            opt.zero_grad(); loss.backward(); opt.step()
            run += loss.item(); nb += 1
        val = evaluate(model, t, va_idx, head_specs)
        mean_val = sum(v["val_acc"] for v in val.values()) / len(val)
        rec = {"epoch": ep, "train_loss": round(run / max(nb, 1), 6),
               "val_acc": {k: v["val_acc"] for k, v in val.items()},
               "mean_val_acc": round(mean_val, 6)}
        history.append(rec)
        print(f"ep{ep:02d} loss={rec['train_loss']:.4f} mean_val={mean_val:.4f} "
              f"({time.time()-t0:.0f}s)", flush=True)
        if mean_val > best:
            best = mean_val
            torch.save({
                "state_dict": model.state_dict(),
                "dims": dims, "head_dims": head_dims,
                "head_names": SC.head_names(),
                "hidden": args.hidden, "ent_out": args.ent_out,
                "arch": "BroadBCPolicy", "epoch": ep, "val_acc": val,
                "contract_version": SC.SHARD_CONTRACT_VERSION,
                "seed": args.seed,
            }, Path(args.out).expanduser())

    # --- norm artifact version (for the card) -------------------------------
    norm_ver = "UNSET"
    if args.norm_artifact and Path(args.norm_artifact).expanduser().exists():
        try:
            nd = json.loads(Path(args.norm_artifact).expanduser().read_text())
            norm_ver = nd.get("artifact_version", "UNSET")
        except Exception:  # noqa: BLE001
            pass

    val_final = evaluate(model, t, va_idx, head_specs)
    metrics = {
        "run_kind": "gpu_train",
        "device": device,
        "torch": torch.__version__,
        "val_action_accuracy": val_final,
        "best_mean_val_acc": round(best, 6),
        "n_rows": int(n_rows), "n_train": len(tr_idx), "n_val": len(va_idx),
        "val_demos": val_demos, "n_params": n_params,
        "input_is_broad": True, "input_includes_observed_others": dims["f_ent"] > 0,
        "dims": dims, "history": history, "seed": args.seed,
    }
    mpath = Path(args.metrics_out).expanduser() if args.metrics_out \
        else Path(args.out).expanduser().with_suffix(".metrics.json")
    mpath.write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    card = core.build_model_card(
        run_kind="gpu_train", schema=schema, in_dim=dims, hidden=args.hidden,
        head_specs=head_specs, metrics=val_final, history=history, seed=args.seed,
        repo_root=REPO_ROOT, norm_artifact_version=norm_ver,
        registry_version=SC.EXPECTS_REGISTRY_VERSION,
        dataset_version="FEAT-gold-shards",
        torch_version=torch.__version__, device=device,
        extra={"n_params": n_params, "best_mean_val_acc": round(best, 6),
               "checkpoint": str(Path(args.out).expanduser())},
    )
    cpath = Path(args.model_card_out).expanduser() if args.model_card_out \
        else Path(args.out).expanduser().with_suffix(".model_card.json")
    cpath.write_text(json.dumps(card, indent=2), encoding="utf-8")

    print(f"\nbest mean val acc={best:.4f}", flush=True)
    print(f"wrote checkpoint -> {Path(args.out).expanduser()}", flush=True)
    print(f"wrote metrics    -> {mpath}", flush=True)
    print(f"wrote model card -> {cpath}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
