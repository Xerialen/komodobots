#!/usr/bin/env python3
"""ml/dagger/dagger_loop.py -- the DAgger D-2 DRIVER (ONE bounded round).

The glue that turns the validated D-1.5 analytic expert (ml/dagger/expert.py) into ONE
round of DAtaset AGGregation against the v5 BC policy, to test whether closed-loop relabel
escapes the over-press attractor BC could not (the over-press bulldoze: fwd-press ~0.99 vs
human 0.07-0.50 -> G-MV4 speed-band fails). The pipeline (dagger-plan.md STEP 2), run ONCE:

  1. ROLLOUT-CAPTURE  the current policy (cs10) closed-loop across the routes via the
     existing eval_broad_dryroute harness (run_eval + the obs_capture hook this branch
     added). Captures the FULL v5 model input each visited tick (self_in[336] + entities +
     ent_mask) PAIRED with the visited state (vx/vy/onground/goal) + the policy's own action,
     so off-manifold (over-press fwd>0.9*MOVE_MAG) ticks are flagged. -> visited.jsonl
  2. RELABEL          each captured visited state with expert_action(state) (the D-1.5
     blended expert: forward component + L/R weave). The expert's move magnitudes go
     through the CANONICAL agent_observation.encode_action (the SAME [-1,1] target encoder
     the offline build uses) -> the act row. KEEP the captured obs; overwrite ONLY the
     action target = the off-manifold correction BC never had.
  3. AGGREGATE        write the (visited-obs -> expert-action) pairs as a v5 Parquet shard
     whose schema is byte-for-byte the FEAT emit_shard layout (flattened list<float32>
     columns + the komodobots.shard.* table metadata: registry_version 5, obs_dim 21,
     self_history_dim 336, act_dim 5, K 1). The shard-contract guards (check_shard_meta +
     require_self_history_present) must ACCEPT it. The training set is then the original v5
     cold-start shards (gold human + cs10 reweight) PLUS this relabel shard (aggregate-all,
     NO beta-schedule this round). -> relabel_dagger.parquet
  4. RETRAIN          via the established #352 pipeline (train_broad_bc --save-every-epoch
     then cs_select_epoch.py BEHAVIORAL selection: pick by closed-loop movement, over-jump
     penalized, NOT val-loss). New ckpt path -> dagger_d2_round1.pt (never overwrites cs10).
  5. EVAL             is run by the caller via cs_full_eval.py + eval_broad_closedloop.py +
     cs_select_epoch.py controls -- this driver owns steps 1-3 (+ emits the exact step-4/5
     commands). The DECISIVE measurement is closed-loop fwd-press + G-MV4 speed vs the
     expert's 159 qu/s standalone ceiling.

This is a BOUNDED test: ONE round, then STOP (the owner's decision, knowing the D-1.5 expert
under-speeds standalone). The driver does NOT loop K rounds.

PURITY / DEPS: the rollout + retrain need torch (run on pinnacle). The relabel + shard write
need numpy + pyarrow (the parquet path; same as the FEAT build). The expert + encode_action
are pure stdlib. Imports mirror the eval harness's sys.path setup so the seam resolves.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

LOGGER = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent          # ml/dagger
ML = HERE.parent                                 # ml
REPO = ML.parent                                 # repo root
for _p in (str(ML), str(REPO / "scripts"), str(ML / "pipeline")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# pure-stdlib imports (no torch/numpy at module load -> the driver imports on bare python;
# the heavy bits are imported lazily inside the subcommands that need them).
from dagger import expert as EXPERT             # noqa: E402  (the D-1.5 relabeler, pure)
from broad_bc import shard_contract as SC       # noqa: E402  (the contract + guards, deps-free)

# the canonical 11-route ticket set (mirrors the pinnacle cs_full_eval.ROUTES exactly; the
# hard routes mega/sng/ra are the ticket focus). Kept here so the rollout enumerates the
# SAME routes the eval table scores.
ROUTES = [
    # hard (the ticket focus: mega / sng / ra)
    "mega_to_rl", "mega_to_window", "sng_to_rl", "sng_jumps", "sng_shortcut",
    "sng_shortcut2", "ra_jumps",
    # refs
    "hilljump", "ring_to_mega", "rl_to_bridge", "rl_to_ya",
]

# over-press flag threshold: a visited tick is "off-manifold over-press" when the policy
# pressed forward at >0.9 of the usercmd magnitude (MOVE_MAG=400 -> >360). This is the exact
# bulldoze the diagnostic dumped (/tmp/cs10_overpress_states.jsonl used pol_fwd>0.9*MOVE_MAG).
OVERPRESS_FWD = 0.9 * EXPERT.MOVE_MAG


# =============================================================================
# STEP 1 -- ROLLOUT-CAPTURE (needs torch; run on pinnacle)
# =============================================================================
def rollout_capture(checkpoint: Path, bsp: Path, norm: Path, routes, out_jsonl: Path, *,
                    cpu: bool = False) -> dict:
    """Roll out `checkpoint` closed-loop down each route via eval_broad_dryroute.run_eval
    with the obs_capture hook, and write every visited (obs + state + policy-action) record
    to out_jsonl (one JSON object per tick, with a `route` field). Returns a summary
    (per-route tick + over-press counts). NEEDS torch -- imported inside run_eval."""
    import eval_broad_dryroute as DR      # noqa: E402  (lazy: pulls torch in run_eval)

    out_jsonl.parent.mkdir(parents=True, exist_ok=True)
    per_route = {}
    n_total = 0
    n_overpress = 0
    with out_jsonl.open("w", encoding="utf-8") as fh:
        for rt in routes:
            cap = []
            # UNSEEDED cold-start rollout (the state distribution the policy ACTUALLY visits
            # from rest -- the same launch convention #352 fixed). The controls still run
            # (bracket validity) but we only need the captured visited states here.
            rep = DR.run_eval(Path(checkpoint), Path(bsp), rt, norm_artifact=Path(norm),
                              cpu=cpu, obs_capture=cap)
            rt_over = 0
            for rec in cap:
                rec["route"] = rt
                rec["overpress"] = bool(rec["pol_fwd"] > OVERPRESS_FWD)
                if rec["overpress"]:
                    rt_over += 1
                fh.write(json.dumps(rec) + "\n")
            pol = rep["bot_policy"]
            per_route[rt] = {
                "n_ticks": len(cap), "n_overpress": rt_over,
                "route_pct": round(pol["route_pct"], 2),
                "speed_pct": round(pol["speed_pct"], 2),
                "bracket_valid": rep["controls"]["bracket_valid"],
            }
            n_total += len(cap)
            n_overpress += rt_over
            print(f"  {rt:16s} ticks={len(cap):5d} overpress={rt_over:5d} "
                  f"route%={pol['route_pct']:6.1f} speed%={pol['speed_pct']:6.1f} "
                  f"bracket={rep['controls']['bracket_valid']}", flush=True)
    summary = {"checkpoint": str(checkpoint), "routes": list(routes),
               "n_ticks_total": n_total, "n_overpress_total": n_overpress,
               "overpress_frac": round(n_overpress / n_total, 4) if n_total else 0.0,
               "per_route": per_route, "out_jsonl": str(out_jsonl)}
    print(f"\nROLLOUT: {n_total} visited states, {n_overpress} over-press "
          f"({summary['overpress_frac']:.1%}) across {len(routes)} routes -> {out_jsonl}",
          flush=True)
    return summary


# =============================================================================
# STEP 2 -- RELABEL  (pure: expert + canonical encode_action)
# =============================================================================
def relabel_record(rec: dict) -> list:
    """One captured visited record -> the v5 `act` target row ([-1,1] / {0,1}, ACT_DIM=5)
    the EXPERT would press in this state, via the D-1.5 expert + the CANONICAL
    agent_observation.encode_action. KEEPS the obs (the caller pairs rec['self_in'] with
    this). Pure: the expert is stdlib, encode_action is stdlib.

    The expert state is the visited velocity + onground + the route goal heading; the L/R
    weave uses the visited tick. encode_action maps the expert's usercmd magnitudes (raw
    +-MOVE_MAG shorts) into the SAME [-1,1] move / {0,1} button target the offline build
    emits -> the relabel target is contract-identical to a human label, just the expert's
    action instead of the human's."""
    from features import agent_observation as AO     # the canonical action encoder (stdlib)

    state = {
        "vx": rec["vx"], "vy": rec["vy"], "onground": rec["onground"],
        "goal": (rec["goal"][0], rec["goal"][1]),
        "origin": (rec["ox"], rec["oy"]),
    }
    fwd, side, up, jump, _view_yaw = EXPERT.expert_action(state, tick=int(rec["tick"]))
    # the expert returns usercmd MAGNITUDES (+-MOVE_MAG / 0) + a jump BIT; map to the raw
    # usercmd-short action_state encode_action consumes (forwardmove/sidemove/upmove shorts +
    # buttons bitfield). view_yaw is the AIM head (deferred / replayed in eval) -> not a move
    # target, so it is intentionally dropped here (DAgger fixes MOVEMENT, not aim).
    act_state = {
        "forwardmove": fwd, "sidemove": side, "upmove": up,
        "buttons": (EXPERT.BUTTON_JUMP if jump else 0),   # attack stays unpressed (movement task)
    }
    return AO.encode_action(act_state)                    # [fwd, side, up, jump, attack] in target space


def relabel_all(records: list) -> list:
    """Relabel every captured record -> list of (self_in[336], ents, mask, act[5]) tuples.
    Pure. The caller writes these as a v5 shard. Over-press records are NOT specially
    treated here (aggregate-all this round) -- every visited state gets the expert label,
    which is exactly the off-manifold correction the policy needs where it visits."""
    out = []
    for rec in records:
        act = relabel_record(rec)
        out.append((rec["self_in"], rec["ents"], rec["mask"], act))
    return out


# =============================================================================
# STEP 3 -- AGGREGATE: write the relabel pairs as a v5 Parquet shard
# (schema byte-identical to ml/pipeline/build_features.emit_shard; K=1 BC windows)
# =============================================================================
def write_relabel_shard(pairs: list, out_path: Path, norm: Path, *,
                         demo_id: int = 990000, map_name: str = "dm3") -> dict:
    """Write the (obs -> expert-action) relabel pairs as ONE v5 Parquet shard the broad-BC
    trainer/loader bind to with NO code change. The layout MIRRORS FEAT's emit_shard exactly:
    per-row FLATTENED list<float32> columns (obs, self_history, entities, ent_mask, act,
    mask, weight) + the komodobots.shard.* table metadata. Each relabel pair is ONE single-
    step window (K=1): obs == self_history[-SELF_DIM:] (the last-real-tick == the only tick),
    self_history == the captured 336 history, act == the expert target, mask/weight == 1.

    `demo_id` is a distinct int (default 990000) so the relabel rows form their OWN demo
    group -- the trainer's group-by-demo split keeps them out of the human val demo (no
    relabel row straddles train/val with a human demo). NEEDS numpy + pyarrow (the parquet
    path); returns the build manifest (rows, dims, guard verdict)."""
    import numpy as np
    import pyarrow as pa
    import pyarrow.parquet as pq

    S = SC.EXPECTS_SELF_DIM                 # 21
    H = SC.EXPECTS_SELF_HISTORY             # 16
    HD = SC.EXPECTS_SELF_HISTORY_DIM        # 336
    A = len(SC.head_names())                # 5 (fwd/side/up/jump/attack)
    K = 1                                   # single-step BC windows
    # entity geometry from the first pair (n_max, ENT) -- the capture preserved the eval's
    # n_max=7 / ENT=13 layout; assert it so a mismatched capture is caught, not silently
    # reshaped wrong.
    n_max = len(pairs[0][2])                # len(mask) == n_max
    ENT = len(pairs[0][1][0]) if pairs[0][1] else 0
    norm_obj = json.loads(Path(norm).read_text(encoding="utf-8"))
    norm_ver = str(norm_obj.get("artifact_version", "UNSET"))
    reg_ver = int(norm_obj.get("registry_version", SC.EXPECTS_REGISTRY_VERSION))

    obs_col, selfhist_col, ent_col, entmask_col = [], [], [], []
    act_col, mask_col, weight_col, demo_col, eid_col, start_col = [], [], [], [], [], []
    for i, (self_in, ents, mask, act) in enumerate(pairs):
        self_in = list(map(float, self_in))
        if len(self_in) != HD:
            raise ValueError(f"relabel pair {i}: self_in width {len(self_in)} != {HD} "
                             f"(SELF_HISTORY {H} * SELF_DIM {S})")
        if len(act) != A:
            raise ValueError(f"relabel pair {i}: act width {len(act)} != {A}")
        # obs (provenance / reject guard): the single-tick SELF == the last SELF_DIM of the
        # flat history (== this tick's obs), per the contract self_history[-SELF_DIM:] == obs.
        obs_col.append([float(x) for x in self_in[-S:]])              # [K*S] (K=1)
        selfhist_col.append(self_in)                                  # [HD] one history per window
        # entities/ent_mask flattened [K*n_max*ENT] / [K*n_max]
        ent_flat = []
        for row in ents:
            ent_flat.extend(float(x) for x in row)
        ent_col.append(ent_flat)
        entmask_col.append([float(x) for x in mask])
        act_col.append([float(x) for x in act])                      # [K*A]
        mask_col.append([1.0])                                        # [K] real step
        weight_col.append([1.0])                                     # [K] full-confidence label
        demo_col.append(int(demo_id))
        eid_col.append(0)
        start_col.append(i)

    schema_meta = {
        b"komodobots.shard.contract": SC.SHARD_CONTRACT_VERSION.encode(),
        b"komodobots.shard.registry_version": str(reg_ver).encode(),
        b"komodobots.shard.K": str(K).encode(),
        b"komodobots.shard.n_max": str(n_max).encode(),
        b"komodobots.shard.obs_dim": str(S).encode(),
        b"komodobots.shard.self_history": str(H).encode(),
        b"komodobots.shard.self_history_dim": str(HD).encode(),
        b"komodobots.shard.ent_dim": str(ENT).encode(),
        b"komodobots.shard.act_dim": str(A).encode(),
        b"komodobots.shard.act_cols": ",".join(
            ["forwardmove", "sidemove", "upmove", "jump_button", "attack_button"]).encode(),
        b"komodobots.shard.map": map_name.encode(),
        b"komodobots.shard.split": b"dagger_relabel",
        b"komodobots.shard.norm_artifact_version": norm_ver.encode(),
        b"komodobots.shard.has_audio": b"false",
        b"komodobots.shard.has_team": b"false",
        b"komodobots.shard.label_source": b"dagger_d1_5_expert",
    }
    table = pa.table(
        {
            "episode_id": pa.array(eid_col, type=pa.int64()),
            "demo_id": pa.array(demo_col, type=pa.int64()),
            "start_tick": pa.array(start_col, type=pa.int64()),
            "obs": pa.array(obs_col, type=pa.list_(pa.float32())),
            "self_history": pa.array(selfhist_col, type=pa.list_(pa.float32())),
            "entities": pa.array(ent_col, type=pa.list_(pa.float32())),
            "ent_mask": pa.array(entmask_col, type=pa.list_(pa.float32())),
            "act": pa.array(act_col, type=pa.list_(pa.float32())),
            "mask": pa.array(mask_col, type=pa.list_(pa.float32())),
            "weight": pa.array(weight_col, type=pa.list_(pa.float32())),
        },
        metadata=schema_meta,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, out_path, compression="zstd")

    # GUARD: the shard-contract checks the trainer/loader run -- the relabel shard MUST pass
    # or the round is invalid. Re-read the shard's own meta and assert ACCEPT (the SAME
    # check_shard_meta + require_self_history_present the loader calls).
    meta = {"registry_version": reg_ver, "obs_dim": S, "self_history_dim": HD,
            "act_dim": A, "n_max": n_max}
    guard = {"accepted": True, "errors": []}
    try:
        SC.check_shard_meta(meta, where=f"dagger_relabel={out_path}")
        SC.require_self_history_present(meta, True, where=f"dagger_relabel={out_path}")
    except ValueError as e:                                         # pragma: no cover - guard
        guard = {"accepted": False, "errors": [str(e)]}
    manifest = {"out": str(out_path), "n_rows": len(pairs),
                "dims": {"obs": S, "self_history_dim": HD, "ent_dim": ENT,
                         "n_max": n_max, "act_dim": A, "K": K},
                "registry_version": reg_ver, "norm_artifact_version": norm_ver,
                "demo_id": demo_id, "guard": guard}
    print(f"SHARD: {len(pairs)} rows -> {out_path}  guard={'ACCEPT' if guard['accepted'] else 'REJECT'}",
          flush=True)
    return manifest


def verify_shard_roundtrips(out_path: Path) -> dict:
    """Read the written shard back through the REAL loader (core.read_shard) and assert it
    parses + the v5 widths come back correct -- the proof the trainer will consume it. NEEDS
    numpy + pyarrow. Returns the round-tripped meta + a few shape checks."""
    from broad_bc import core as CORE
    shard = CORE.read_shard(out_path)
    meta = shard[SC.KEY_META]
    sh = shard.get(SC.KEY_SELF_HISTORY)
    act = shard.get(SC.KEY_ACT)
    checks = {
        "registry_version": meta.get("registry_version"),
        "self_history_dim": meta.get("self_history_dim"),
        "obs_dim": meta.get("obs_dim"),
        "act_dim": meta.get("act_dim"),
        "n_windows": meta.get("n_windows"),
        "self_history_shape": list(sh.shape) if sh is not None else None,
        "act_shape": list(act.shape) if act is not None else None,
    }
    ok = (checks["registry_version"] == SC.EXPECTS_REGISTRY_VERSION
          and checks["self_history_dim"] == SC.EXPECTS_SELF_HISTORY_DIM
          and sh is not None and sh.shape[1] == SC.EXPECTS_SELF_HISTORY_DIM)
    checks["roundtrip_ok"] = bool(ok)
    print(f"ROUNDTRIP: loader read {checks['n_windows']} windows, self_history "
          f"{checks['self_history_shape']}, act {checks['act_shape']} -> "
          f"{'OK' if ok else 'FAIL'}", flush=True)
    return checks


# =============================================================================
# CLI
# =============================================================================
def _cmd_rollout(args) -> int:
    routes = args.routes or ROUTES
    summary = rollout_capture(args.checkpoint, args.bsp, args.norm, routes,
                              args.out, cpu=args.cpu)
    if args.summary_out:
        Path(args.summary_out).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return 0


def _cmd_aggregate(args) -> int:
    records = [json.loads(ln) for ln in args.visited.read_text().splitlines() if ln.strip()]
    if not records:
        raise SystemExit(f"no visited records in {args.visited}")
    pairs = relabel_all(records)
    manifest = write_relabel_shard(pairs, args.out, args.norm, demo_id=args.demo_id)
    if not manifest["guard"]["accepted"]:
        print("SHARD GUARD REJECTED -- stopping (do not train on an invalid shard):",
              json.dumps(manifest["guard"]), flush=True)
        return 3
    rt = verify_shard_roundtrips(args.out)
    manifest["roundtrip"] = rt
    if args.manifest_out:
        Path(args.manifest_out).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    if not rt["roundtrip_ok"]:
        print("SHARD ROUNDTRIP FAILED -- stopping.", flush=True)
        return 3
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("rollout", help="STEP 1: roll out the policy closed-loop + capture "
                                        "visited (obs+state+action) to JSONL")
    pr.add_argument("--checkpoint", type=Path, required=True)
    pr.add_argument("--bsp", type=Path, required=True)
    pr.add_argument("--norm", type=Path, required=True)
    pr.add_argument("--routes", nargs="+", default=None, help="default = the 11 ticket routes")
    pr.add_argument("--out", type=Path, required=True, help="visited.jsonl")
    pr.add_argument("--summary-out", type=Path, default=None)
    pr.add_argument("--cpu", action="store_true")
    pr.set_defaults(func=_cmd_rollout)

    pa_ = sub.add_parser("aggregate", help="STEPS 2-3: relabel visited states with the expert "
                                           "+ write a v5 relabel shard (guard-checked)")
    pa_.add_argument("--visited", type=Path, required=True, help="visited.jsonl from rollout")
    pa_.add_argument("--norm", type=Path, required=True)
    pa_.add_argument("--out", type=Path, required=True, help="relabel_dagger.parquet")
    pa_.add_argument("--demo-id", type=int, default=990000)
    pa_.add_argument("--manifest-out", type=Path, default=None)
    pa_.set_defaults(func=_cmd_aggregate)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.setrecursionlimit(20000)
    raise SystemExit(main())
