#!/usr/bin/env python3
"""smoke_broad_bc.py — OFFLINE, DEPS-FREE CPU smoke for the broad-BC trainer.

Proves the SHARD CONTRACT + trainer scaffold end-to-end with NO torch/numpy (the
host has neither when offline). It:
  1. generates a tiny synthetic multi-demo BROAD corpus (synth_shard) whose action
     depends on BOTH self obs AND the observed-other entity channel — so fitting it
     REQUIRES the broad input (a move-only model could not);
  2. reads it through the SAME loader/split/label-encoding the torch trainer uses
     (broad_bc.core), building the broad input [obs | pooled(entities) | audio | team];
  3. trains the pure-python reference MLP to completion (multi-head CE, SGD);
  4. runs the WHOLE thing TWICE and asserts the per-epoch loss is byte-identical
     (seed reproducibility);
  5. emits checkpoint (model weights JSON) + metrics.json (per-head val accuracy)
     + model-card stub (git_sha / registry_version / norm artifact_version / seed).

This is the offline counterpart of the pinnacle GPU run; the GPU path
(`ml/train_broad_bc.py`) reuses the same contract/split/labels/metrics/model-card,
so a green smoke here is evidence the contract is sound. See ml/BROAD_BC.md.

Run (offline, from repo root, bare python3 — no venv needed):
    python3 ml/smoke_broad_bc.py --out /tmp/broad_bc_smoke
"""
from __future__ import annotations

import logging
import argparse
import json
import sys
import tempfile
from pathlib import Path


LOGGER = logging.getLogger(__name__)
HERE = Path(__file__).resolve().parent          # ml/
REPO_ROOT = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from broad_bc import shard_contract as SC      # noqa: E402
from broad_bc import synth_shard               # noqa: E402
from broad_bc import core                      # noqa: E402


def _run_once(corpus_paths, schema, *, hidden, epochs, lr, seed, val_frac, batch,
              quiet=True):
    rows, in_dim = core.iter_corpus(corpus_paths, schema)
    tr, va, val_demos = core.split_by_demo(rows, val_frac=val_frac, seed=seed)
    head_specs = [(n, k) for (n, k, _c, _kind) in schema.heads()]
    head_dims = [k for (_n, k) in head_specs]
    log = None if quiet else (lambda m: print("   " + m, flush=True))
    model, history = core.train_ref(
        tr, in_dim, head_dims, hidden=hidden, epochs=epochs, lr=lr, seed=seed,
        batch=batch, log=log,
    )
    metrics = core.evaluate_heads(model, va, head_specs)
    return {
        "model": model, "history": history, "metrics": metrics,
        "in_dim": in_dim, "head_specs": head_specs,
        "n_train": len(tr), "n_val": len(va), "val_demos": val_demos,
        "n_demos": len({r["demo_id"] for r in rows}),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=Path(tempfile.gettempdir()) / "broad_bc_smoke")
    ap.add_argument("--demos", type=int, default=5)
    ap.add_argument("--windows-per-demo", type=int, default=200)
    ap.add_argument("--epochs", type=int, default=8)
    ap.add_argument("--hidden", type=int, default=24)
    ap.add_argument("--lr", type=float, default=0.2)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--val-frac", type=float, default=0.2)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--obs-dim", type=int, default=16)
    ap.add_argument("--ent-dim", type=int, default=10)
    args = ap.parse_args(argv)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    schema = SC.ShardSchema()

    print(f"[smoke] broad-BC offline CPU smoke (deps-free)  out={out}", flush=True)
    print(f"[smoke] contract={SC.SHARD_CONTRACT_VERSION} "
          f"registry_version={SC.EXPECTS_REGISTRY_VERSION}", flush=True)

    # --- 1. synthetic corpus (deterministic) --------------------------------
    corpus_dir = out / "synth_corpus"
    corpus_paths = synth_shard.make_synthetic_corpus(
        corpus_dir, n_demos=args.demos, windows_per_demo=args.windows_per_demo,
        seed=args.seed, obs_dim=args.obs_dim, ent_dim=args.ent_dim,
    )
    print(f"[smoke] generated {len(corpus_paths)} synthetic shards "
          f"({corpus_paths[0].name} ...)", flush=True)

    # --- 2+3. train (run #1, verbose) ---------------------------------------
    print("[smoke] run #1 (training reference MLP to completion):", flush=True)
    r1 = _run_once(corpus_paths, schema, hidden=args.hidden, epochs=args.epochs,
                   lr=args.lr, seed=args.seed, val_frac=args.val_frac,
                   batch=args.batch, quiet=False)
    print(f"[smoke]   input_dim={r1['in_dim']}  (= self_obs + pooled_entities + "
          f"n_vis_frac + audio + team)", flush=True)
    print(f"[smoke]   demos={r1['n_demos']} train_rows={r1['n_train']} "
          f"val_rows={r1['n_val']} val_demos={r1['val_demos']}", flush=True)

    # --- 4. reproducibility: run #2, identical loss -------------------------
    print("[smoke] run #2 (reproducibility check, same seed):", flush=True)
    r2 = _run_once(corpus_paths, schema, hidden=args.hidden, epochs=args.epochs,
                   lr=args.lr, seed=args.seed, val_frac=args.val_frac,
                   batch=args.batch, quiet=True)
    loss1 = [h["train_loss"] for h in r1["history"]]
    loss2 = [h["train_loss"] for h in r2["history"]]
    reproducible = loss1 == loss2
    print(f"[smoke]   run1 loss curve = {loss1}", flush=True)
    print(f"[smoke]   run2 loss curve = {loss2}", flush=True)
    print(f"[smoke]   REPRODUCIBLE (identical loss): {reproducible}", flush=True)

    # --- learnability sanity: loss must drop, val acc must beat majority -----
    loss_dropped = loss1[-1] < loss1[0]
    beats_baseline = all(
        m["val_acc"] >= m["majority_baseline"] for m in r1["metrics"].values()
    )
    print(f"[smoke]   loss dropped ({loss1[0]:.4f} -> {loss1[-1]:.4f}): {loss_dropped}",
          flush=True)
    for name, m in r1["metrics"].items():
        print(f"[smoke]   val_acc[{name}]={m['val_acc']:.3f} "
              f"(majority {m['majority_baseline']:.3f})", flush=True)

    # --- 5. emit artifacts --------------------------------------------------
    model = r1["model"]
    ckpt = {
        "arch": "RefMLP (pure-python reference; torch path = BroadBCPolicy)",
        "in_dim": model.in_dim, "hidden": model.hidden,
        "head_dims": model.head_dims,
        "W1": model.W1, "b1": model.b1, "Wh": model.Wh, "bh": model.bh,
        "head_names": SC.head_names(),
        "seed": args.seed,
        "contract_version": SC.SHARD_CONTRACT_VERSION,
    }
    ckpt_path = out / "broad_bc_smoke.ckpt.json"
    ckpt_path.write_text(json.dumps(ckpt), encoding="utf-8")

    metrics_doc = {
        "run_kind": "cpu_smoke",
        "reproducible": reproducible,
        "loss_curve": loss1,
        "loss_dropped": loss_dropped,
        "val_action_accuracy": r1["metrics"],   # per-head val accuracy (the headline metric)
        "beats_majority_baseline": beats_baseline,
        "n_demos": r1["n_demos"],
        "n_train_rows": r1["n_train"],
        "n_val_rows": r1["n_val"],
        "val_demos": r1["val_demos"],
        "input_dim": r1["in_dim"],
        "input_is_broad": True,
        "input_includes_observed_others": True,
        "seed": args.seed,
        "epochs": args.epochs,
        "hidden": args.hidden,
    }
    metrics_path = out / "metrics.json"
    metrics_path.write_text(json.dumps(metrics_doc, indent=2), encoding="utf-8")

    card = core.build_model_card(
        run_kind="cpu_smoke", schema=schema, in_dim=r1["in_dim"], hidden=args.hidden,
        head_specs=r1["head_specs"], metrics=r1["metrics"], history=r1["history"],
        seed=args.seed, repo_root=REPO_ROOT,
        norm_artifact_version="SYNTH-0 (smoke: no real norm artifact)",
        registry_version=SC.EXPECTS_REGISTRY_VERSION,
        dataset_version="synthetic-smoke-corpus",
        extra={"note": "CPU smoke (deps-free reference trainer). Real run = "
                       "ml/train_broad_bc.py on pinnacle; see ml/BROAD_BC.md."},
    )
    card_path = out / "model_card.json"
    card_path.write_text(json.dumps(card, indent=2), encoding="utf-8")

    # also drop the resolved contract for the record
    SC.write_contract_doc(out / "shard_contract.resolved.json", schema)

    print(f"[smoke] wrote checkpoint  -> {ckpt_path}", flush=True)
    print(f"[smoke] wrote metrics     -> {metrics_path}", flush=True)
    print(f"[smoke] wrote model card  -> {card_path}", flush=True)

    ok = reproducible and loss_dropped and beats_baseline
    print(f"\n[smoke] RESULT: {'PASS' if ok else 'FAIL'} "
          f"(reproducible={reproducible} loss_dropped={loss_dropped} "
          f"beats_baseline={beats_baseline})", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
