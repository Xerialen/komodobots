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

import logging
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn


LOGGER = logging.getLogger(__name__)
HERE = Path(__file__).resolve().parent          # ml/
REPO_ROOT = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from broad_bc import shard_contract as SC      # noqa: E402
from broad_bc import core                      # noqa: E402


# GRU hidden width of the SELF temporal encoder (the v5-seqaware brain). The policy reads
# the SAME flat [SELF_HISTORY*SELF_DIM] SELF input the flatten model did, but encodes it as
# a 16-step sequence with this-wide recurrent state so it learns the bunnyhop RHYTHM rather
# than "jump a lot" (the flatten model overshot in closed loop). Named constant so the
# checkpoint can record it and the loader reconstruct it.
GRU_HIDDEN = 64


# =============================================================================
# Model: SELF temporal encoder (GRU) + per-entity encoder + masked mean-pool
#        (DeepSets) + trunk + multi-head
# =============================================================================
class BroadBCPolicy(nn.Module):
    """BROAD policy (v5 SEQUENCE-AWARE, GRU SELF encoder).

    Inputs (already normalized by FEAT — UNCHANGED from the flatten model):
      obs   : [B, F_obs]            self input — the FLAT last-SELF_HISTORY-tick SELF
                                    history (F_obs = SELF_HISTORY*SELF_DIM = 336 at v5),
                                    OR the single-tick SELF (F_obs = SELF_DIM = 21) on a
                                    legacy shard. The caller passes the SAME flat F_obs
                                    SELF vector it always did (shard / inference / norm
                                    unchanged); this module reshapes it INTERNALLY to a
                                    [B, T, SELF_DIM] sequence (T = F_obs // SELF_DIM).
      ent   : [B, N_max, F_ent]     per observed-other egocentric vectors
      emask : [B, N_max]            1=real other-actor, 0=pad
      aux   : [B, F_aux]            concat(audio, team)  (may be width 0)

    SELF ENCODER (the ONLY change vs. the flatten model): instead of feeding the flat
    336 straight into the trunk, the policy reshapes the (already-normalized) flat SELF
    history to [B, T, SELF_DIM] — TIME-MAJOR (dim1 = tick OLDEST->NEWEST, dim2 = the
    SELF_DIM channels), which matches assemble_self_history's row-major oldest->newest
    flatten (tick t's SELF_DIM channels live at flat[t*SELF_DIM:(t+1)*SELF_DIM]) — and
    runs a small 1-layer GRU (hidden GRU_HIDDEN) over the T-step sequence. The LAST
    timestep hidden state [B, GRU_HIDDEN] is the SELF representation. This lets the policy
    learn the bunnyhop CADENCE/rhythm (a temporal pattern) rather than overshooting on a
    flattened "jump a lot" feature. The entity encoder, the masked DeepSets pool, the
    trunk, and the 5 heads are UNCHANGED — only the SELF input path (flatten -> GRU) and
    the trunk's SELF-side input width (F_obs -> GRU_HIDDEN) differ. Each per-tick SELF row
    is the 21-wide goal-conditioned vector, so the goal signal flows through the GRU too.

    The model still RECEIVES a flat F_obs SELF vector: the 336-dim input contract, the v5
    shard, the normalization and the inference deque are all reused byte-for-byte; the
    reshape + GRU are purely internal.
    """

    def __init__(self, f_obs, f_ent, f_aux, n_max, *, ent_hidden=64, ent_out=64,
                 hidden=256, head_dims=(3, 3, 3, 2, 2),
                 self_dim=SC.EXPECTS_SELF_DIM, gru_hidden=GRU_HIDDEN):
        super().__init__()
        self.n_max = n_max
        self.f_ent = f_ent
        # SELF temporal encoder: the flat F_obs SELF input is reshaped to a
        # [B, f_obs//self_dim, self_dim] sequence (TIME-MAJOR, oldest->newest) and run
        # through a 1-layer GRU; the last hidden state is the SELF summary. f_obs MUST be a
        # whole multiple of self_dim (336 = 16*21 at v5; 21 = 1*21 on a legacy single-tick
        # shard -> a 1-step sequence). self_dim/gru_hidden are stored so the checkpoint can
        # record them and _build_policy_from_checkpoint can reconstruct the GRU.
        if f_obs % self_dim != 0:
            raise ValueError(
                f"f_obs {f_obs} is not a whole multiple of self_dim {self_dim}; the SELF "
                f"input must be a flat [T*self_dim] history so it can reshape to "
                f"[B, T, self_dim] for the GRU")
        self.self_dim = self_dim
        self.gru_hidden = gru_hidden
        self.self_steps = f_obs // self_dim          # T (16 at v5; 1 legacy single-tick)
        self.self_gru = nn.GRU(input_size=self_dim, hidden_size=gru_hidden,
                               num_layers=1, batch_first=True)
        self.ent_enc = nn.Sequential(
            nn.Linear(f_ent, ent_hidden), nn.ReLU(),
            nn.Linear(ent_hidden, ent_out), nn.ReLU(),
        ) if f_ent > 0 else None
        # the SELF side of the trunk is now the GRU hidden width (was f_obs).
        trunk_in = gru_hidden + (ent_out if f_ent > 0 else 0) + f_aux
        self.trunk = nn.Sequential(
            nn.Linear(trunk_in, hidden), nn.ReLU(),
            nn.Linear(hidden, hidden), nn.ReLU(),
        )
        self.heads = nn.ModuleList([nn.Linear(hidden, k) for k in head_dims])

    def forward(self, obs, ent, emask, aux):
        # SELF: reshape the flat [B, T*self_dim] history to [B, T, self_dim] (TIME-MAJOR:
        # dim1 = tick oldest->newest, dim2 = the self_dim channels — matches
        # assemble_self_history's row-major flatten), run the GRU, take the LAST timestep
        # hidden state as the SELF representation. (.reshape is safe across contiguous /
        # non-contiguous obs and this is exactly the assemble_self_history memory layout.)
        B = obs.shape[0]
        seq = obs.reshape(B, self.self_steps, self.self_dim)  # [B, T, self_dim]
        _out, h_n = self.self_gru(seq)                        # h_n: [1, B, gru_hidden]
        self_repr = h_n[-1]                                   # last layer's final hidden [B, H]
        parts = [self_repr]
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
        # Reject stale/future/mislabelled shards BEFORE the GPU run rather than silently
        # training on misaligned inputs/labels. The shared SC.check_shard_meta enforces
        # BOTH guards (so the rule cannot drift between trainer and eval):
        #   * registry_version present and != EXPECTS_REGISTRY_VERSION (the stale-v2
        #     equality guard — a v2 16-channel SELF shard must not bind to v3's 18-channel
        #     layout), AND
        #   * obs_dim present and != EXPECTS_SELF_DIM (catches a hand-edited
        #     v3-LABELLED-but-16-channel artifact whose SELF width never grew).
        # A shard that OMITS a field is treated as matching (legacy / minimal smoke).
        SC.check_shard_meta(meta, where=f"shard={p}, demo_id={default_demo}")
        # v5 SEQUENCE input: the policy SELF input is the FLAT last-SELF_HISTORY-tick
        # history (self_history), NOT the single-tick `obs`. self_history is now ONE [HD]
        # history PER WINDOW (the build stores only the last-real-tick history — the single
        # tick this trainer reads — so it is indexed [wi], NOT [wi][ti]). Legacy/pre-v5
        # shards omit it -> fall back to the single-tick obs[wi][ti] (then f_obs == SELF_DIM,
        # the v4 behavior). The single-tick `obs` is still read for the reject guard.
        obs = shard[SC.KEY_OBS]
        self_history = shard.get(SC.KEY_SELF_HISTORY)
        # v5 contract: a registry_version>=5 shard MUST carry the self_history array, else the
        # single-tick fallback below would silently train the GRU at x_len=SELF_DIM (21) instead
        # of the required HD (336). The SAME shared guard the deps-free loader calls — raises for
        # a v5-labelled shard that omits the array; pre-v5 shards keep the fallback.
        SC.require_self_history_present(
            meta, self_history is not None, where=f"shard={p}, demo_id={default_demo}")
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
            # the SELF input: the flat last-real-tick self_history[wi] (v5, [HD], one per
            # window) when present, else the single-tick obs[wi][ti] (legacy). Its width sets
            # f_obs (336 with history, SELF_DIM without). OBS/ent/act stay indexed by `ti`.
            self_vec = self_history[wi] if self_history is not None else obs[wi][ti]
            OBS.append([float(v) for v in self_vec])
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


def _class_weights(y, w, tr_idx, head_specs):
    """Per-head inverse-frequency CE class weights from EFFECTIVE (shard-weighted)
    counts, so a weight=0 row (pad / interpolated / missing label) cannot shift the
    class balance and thus cannot bias the loss/gradients for the real rows."""
    out = []
    for h, (_name, k) in enumerate(head_specs):
        cnts = torch.bincount(y[tr_idx, h], weights=w[tr_idx], minlength=k).clone()
        cnts[cnts == 0] = 1.0
        out.append(cnts.sum() / (k * cnts))
    return out


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
    ap.add_argument("--save-every-epoch", type=Path, default=None, metavar="DIR",
                    help="also save each epoch's checkpoint as DIR/ep<NN>.pt (for "
                         "BEHAVIORAL checkpoint selection — best-mean-val alone picks a "
                         "pre-movement epoch on the thin corpus). Off by default.")
    ap.add_argument("--save-last", type=Path, default=None, metavar="PATH",
                    help="also save the FINAL (last-epoch) checkpoint to PATH, regardless "
                         "of mean-val (the best-val .pt may be an early under-moving epoch).")
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
    ce = [nn.CrossEntropyLoss(weight=cw.to(device), reduction="none")
          for cw in _class_weights(t["y"], t["w"], tr_idx, head_specs)]

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
        # ONE checkpoint dict builder reused by the best-val save, the per-epoch dump,
        # and the final last-epoch save, so the reload contract can never drift between
        # them (the eval loader keys off arch/dims/self_dim/gru_hidden/head_dims).
        def _ckpt(epoch_i, val_i):
            return {
                "state_dict": model.state_dict(),
                "dims": dims, "head_dims": head_dims,
                "head_names": SC.head_names(),
                "hidden": args.hidden, "ent_out": args.ent_out,
                # SELF GRU encoder config (v5-seqaware): the loader reconstructs the GRU
                # from these (input=self_dim per tick, hidden=gru_hidden). f_obs (dims)
                # stays the flat SELF INPUT width (336) — the model input contract is
                # unchanged; these only describe the internal temporal encoder.
                "self_dim": model.self_dim, "gru_hidden": model.gru_hidden,
                "arch": "BroadBCPolicy", "epoch": epoch_i, "val_acc": val_i,
                "contract_version": SC.SHARD_CONTRACT_VERSION,
                "seed": args.seed,
            }
        if mean_val > best:
            best = mean_val
            torch.save(_ckpt(ep, val), Path(args.out).expanduser())
        # Per-epoch dump for BEHAVIORAL checkpoint selection: best-mean-val picked a
        # pre-movement epoch (ep3) on this corpus, so the cold-start retrain selects the
        # checkpoint by a closed-loop dry-route signal instead. Saving every epoch's .pt
        # (off by default) lets a separate selection step score each WITHOUT importing the
        # eval into the trainer. The final epoch is ALSO the "last" checkpoint below.
        if args.save_every_epoch is not None:
            ep_dir = Path(args.save_every_epoch).expanduser()
            ep_dir.mkdir(parents=True, exist_ok=True)
            torch.save(_ckpt(ep, val), ep_dir / f"ep{ep:02d}.pt")
        # the FINAL epoch's checkpoint (the "last", as opposed to the best-mean-val "best").
        if args.save_last is not None and ep == args.epochs - 1:
            last_p = Path(args.save_last).expanduser()
            last_p.parent.mkdir(parents=True, exist_ok=True)
            torch.save(_ckpt(ep, val), last_p)

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
