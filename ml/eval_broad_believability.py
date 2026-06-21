#!/usr/bin/env python3
"""eval_broad_believability.py — OPEN-LOOP action-believability eval for the BROAD BC policy.

WHAT THIS IS (and is honestly NOT)
==================================
This harness scores whether the trained BROAD behavioral-cloning policy
(`ml/train_broad_bc.py` :: BroadBCPolicy) PRODUCES human-like ACTION PATTERNS on
HELD-OUT human demos. It is an **open-loop** eval:

  * we feed the policy the REAL held-out human `agent_observation` per tick (the
    SAME shared encoder training used — `scripts/features/agent_observation.py`;
    v5: the SELF input is the FLAT last-SELF_HISTORY-tick history assembled by the
    shared AO.assemble_self_history, identical to the build + closed-loop paths),
  * read its predicted usercmd (argmax per head -> fwd/side/up/jump/attack),
  * and compare the PREDICTED action stream against the HUMAN's own action stream
    on those same demos.

We DO NOT roll the policy forward in a simulator. There is no pmove rollout, no
AIM/yaw head (the policy clones movement+jump+attack but NOT view — `cmd_delta_yaw`
is carried in the catalog but NOT cloned, deferred to a future AIM head). So:

  MEANINGFUL here (predicted-action vs human-action, same demos):
    * strafe cadence  — L/R sidemove sign-flips per minute (airborne-moving ticks)
    * jump rate, attack rate
    * movement-class distributions (fwd / side / up 3-way)
    * per-head action agreement (argmax == human class) — the val-acc analog

  N/A in open-loop (recorded in the report's `caveats`, NOT silently skipped):
    * G-MV1 face-and-run        — needs the AIM/yaw head AND resulting closed-loop motion
    * G-MV4 speed band          — open-loop speed is the HUMAN's state, not the policy's
    * route retention           — needs a closed-loop rollout (the F5 pmove_sim wave)

  The strafe-cadence ANCHOR BAND is also a known gap: the dm3 4on4 anchor
  (`references/dm3_4on4_anchors.json`) carries movement metrics on the MVD
  finite-difference plane (speed, air ratios, airborne-run `jump_cadence_per_min`)
  but has NO L/R-sidemove strafe-cadence band — the MVD plane has no usercmd
  sidemove to measure it from. So this harness ALWAYS reports the policy-vs-human
  strafe cadence (the meaningful open-loop signal), and attaches the anchor band
  ONLY if a future anchor adds one; otherwise it records `anchor_band: null` with
  the reason. Pass/fail against the anchor is emitted only when a band exists.

WHERE IT RUNS
=============
The policy forward needs torch and the catalog read needs duckdb, so this runs on
the GPU host (pinnacle), inside the ml venv. The pure-python METRIC MATH is
factored out (module-level `metrics_*` / `cadence_*` functions) and unit-tested
deps-free in `ml/tests/test_eval_believability.py`; only `run_eval()` (which does
the torch forward + duckdb read) needs the heavy deps.

CLI
===
  python -m ml.eval_broad_believability \
      --checkpoint ~/broad_bc_policy.pt \
      --db ~/komodobots/data/catalog/dm3_4on4_slice.sqlite \
      --norm-artifact ~/komodobots/ml/gold/norm/normalization_stats.json \
      --split val --out report.json \
      [--anchors references/dm3_4on4_anchors.json] [--map dm3] [--n-max 7] [--cpu]

The believability NUMBERS can only come from the pinnacle run (no torch here).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent          # ml/
REPO_ROOT = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

# DEPS-FREE imports only at module load (the contract / head order). torch, numpy,
# duckdb, the agent_observation encoder and the pipeline loader are imported LAZILY
# inside run_eval(), so this module (and its pure-python metric helpers) imports on
# bare stdlib python for the unit tests.
from broad_bc import shard_contract as SC       # noqa: E402  (deps-free)


# =============================================================================
# Action-class vocabulary (frozen to the trainer's heads).
# heads (shard_contract.ACTION_HEADS order): fwd/side/up (sign3) + jump/attack (bin).
# sign3 classes: {0: back/left/down, 1: none, 2: fwd/right/up}.
# bin classes:   {0: not pressed, 1: pressed}.
# =============================================================================
HEAD_NAMES = SC.head_names()                     # ["fwd","side","up","jump","attack"]
SIGN3_HEADS = ("fwd", "side", "up")
BIN_HEADS = ("jump", "attack")
# usercmd reconstruction: sign3 class -> signed move component in {-1,0,+1}
SIGN3_TO_MOVE = {0: -1, 1: 0, 2: +1}


# =============================================================================
# PURE-PYTHON METRIC HELPERS  (no torch / numpy / duckdb — unit-tested deps-free)
# These take plain python sequences of per-tick integer classes (the argmax of
# each head) plus the raw self state, and return the believability metrics. The
# torch CLI (run_eval) calls EXACTLY these after it has produced the predictions.
# =============================================================================

# Frame rate of the catalog tick stream. dm3 4on4 .qwd usercmd recovery is at the
# physics frame rate; the catalog `actions`/`player_ticks` are one row per physics
# frame. 77.x is the QW physics-equivalent the program uses elsewhere; expose it so
# the cadence "per minute" conversion is explicit and overridable.
DEFAULT_TICKS_PER_SEC = 77.0

# A tick counts as "airborne-moving" (eligible for the strafe-cadence count) when
# the player is off the ground AND actually moving horizontally — strafe-jumping is
# the airborne L/R rhythm we care about; standing/ground turns are not strafe cadence.
AIRBORNE_HSPEED_FLOOR = 80.0     # qu/s; mirrors agent_observation's vel-heading floor


def side_class_to_sign(side_class: int) -> int:
    """side 3-way class -> {-1,0,+1} L/R sign (sign3: 0=left, 1=none, 2=right)."""
    return SIGN3_TO_MOVE[int(side_class)]


def count_sign_flips(signs) -> int:
    """Number of LEFT<->RIGHT reversals in a sequence of {-1,0,+1} side signs.

    A "flip" is a sign change between two consecutive NON-ZERO signs (the zeros —
    no-strafe ticks — are skipped, they neither start nor break a strafe rhythm).
    This is the strafe-cadence primitive: e.g. signs [+1,+1,-1,-1,+1] has 2 flips
    (+ -> - , - -> +). A sequence that never reverses (all +1, or all 0) -> 0 flips
    (the believability red flag: a bot that never alternates strafe keys).
    """
    flips = 0
    prev = 0
    for s in signs:
        s = int(s)
        if s == 0:
            continue
        if prev != 0 and s != prev:
            flips += 1
        prev = s
    return flips


def strafe_cadence_per_min(side_signs, eligible, *,
                           ticks_per_sec: float = DEFAULT_TICKS_PER_SEC) -> dict:
    """L/R strafe-cadence over the ELIGIBLE (airborne-moving) ticks.

    `side_signs[i]`  = {-1,0,+1} side sign for tick i (from the side head class).
    `eligible[i]`    = bool, tick i is airborne-moving (counts toward cadence).

    Returns {flips, eligible_ticks, eligible_seconds, flips_per_min}. Cadence =
    flips / eligible_seconds * 60. With zero eligible ticks the rate is 0.0 (and
    `eligible_ticks` says why — no airborne-moving sample to measure cadence on).
    Computing the rate over ELIGIBLE seconds (not wall-clock) keeps it comparable
    between policy and human on the SAME tick subset.
    """
    elig_signs = [int(s) for s, e in zip(side_signs, eligible) if e]
    flips = count_sign_flips(elig_signs)
    n_elig = len(elig_signs)
    elig_seconds = n_elig / ticks_per_sec if ticks_per_sec > 0 else 0.0
    rate = (flips / elig_seconds * 60.0) if elig_seconds > 0 else 0.0
    return {
        "flips": flips,
        "eligible_ticks": n_elig,
        "eligible_seconds": round(elig_seconds, 4),
        "flips_per_min": round(rate, 4),
    }


def bin_rate(bin_classes) -> dict:
    """Fraction of ticks a binary head is pressed (class==1). For jump/attack rate."""
    n = len(bin_classes)
    pressed = sum(1 for c in bin_classes if int(c) == 1)
    return {"n": n, "pressed": pressed,
            "rate": round(pressed / n, 6) if n else 0.0}


def class_distribution(classes, n_classes: int) -> dict:
    """Count + fraction per class id in [0, n_classes). For the 3-way move-class and
    2-way button-class distributions. Returns {counts:[...], fracs:[...], n}."""
    counts = [0] * n_classes
    for c in classes:
        ci = int(c)
        if 0 <= ci < n_classes:
            counts[ci] += 1
    n = sum(counts)
    fracs = [round(c / n, 6) if n else 0.0 for c in counts]
    return {"counts": counts, "fracs": fracs, "n": n}


def head_agreement(pred_classes, human_classes) -> dict:
    """Fraction of ticks predicted argmax == human class (the open-loop val-acc
    analog / cross-check). Lengths must match."""
    n = min(len(pred_classes), len(human_classes))
    agree = sum(1 for i in range(n) if int(pred_classes[i]) == int(human_classes[i]))
    return {"n": n, "agree": agree,
            "agreement": round(agree / n, 6) if n else 0.0}


def total_variation(p_fracs, q_fracs) -> float:
    """Total-variation distance between two class-fraction vectors:
    0.5 * sum |p_i - q_i|. 0 = identical distribution, 1 = disjoint. Used to score
    how close the policy's movement-class mix is to the human's."""
    n = min(len(p_fracs), len(q_fracs))
    return round(0.5 * sum(abs(float(p_fracs[i]) - float(q_fracs[i])) for i in range(n)), 6)


def airborne_moving_mask(onground_seq, hspeed_seq, *,
                         hspeed_floor: float = AIRBORNE_HSPEED_FLOOR):
    """Per-tick eligibility for strafe cadence: airborne (onground==0/False) AND
    horizontal speed >= floor. Returns a list[bool] aligned with the inputs.

    NOTE: `onground`/`hspeed` are the HUMAN's RAW self state in BOTH the policy and
    human cadence — open-loop, the policy does not move the player, so airborne-ness
    is a property of the demo tick, not of who produced the action. We deliberately
    use the SAME eligibility mask for policy and human so the cadence is measured on
    an identical tick subset (apples-to-apples on the policy's action pattern vs the
    human's action pattern at the same airborne-moving moments)."""
    out = []
    for og, hs in zip(onground_seq, hspeed_seq):
        airborne = not bool(og)
        moving = (hs is not None) and (float(hs) >= hspeed_floor)
        out.append(airborne and moving)
    return out


def _mask_seq(seq, human_valid):
    """Keep only the entries of `seq` where the aligned `human_valid[i]` is truthy.
    Used to drop weight==0 human rows (null/interpolated/zero-confidence labels —
    the trainer's loss-excluded rows) from the HUMAN-side numerator AND denominator
    so a fabricated 'idle' label can't pollute the human believability stats."""
    return [s for s, keep in zip(seq, human_valid) if keep]


def compute_demo_metrics(pred, human, raw, *,
                         ticks_per_sec: float = DEFAULT_TICKS_PER_SEC,
                         human_weight=None) -> dict:
    """All per-demo believability metrics from already-decoded per-tick CLASSES.

    `pred` / `human`: dict head_name -> list[int class] (same length, tick-ordered).
        pred  = policy argmax classes; human = catalog-action classes.
    `raw`: {"onground": [...], "hspeed": [...]} the demo's RAW self state per tick.
    `human_weight`: OPTIONAL per-tick loss weight for the HUMAN label (the trainer's
        `weight` = action confidence, 0 on a null/interpolated/zero-confidence frame
        — see ml/pipeline/build_features.py). When given, every HUMAN-side metric
        (human strafe cadence, human jump/attack rate, human move-class dist, and
        per-head agreement) is computed ONLY over weight>0 ticks, excluding the
        fabricated 'idle' rows from both numerator and denominator. The POLICY side
        is always unmasked (the policy predicts every tick). Default None = no mask
        (back-compat: every tick counts), so existing callers are unaffected.

    Pure python — this is the function the deps-free unit tests exercise and the
    torch CLI calls per demo. Returns policy + human strafe cadence, jump/attack
    rates, the 3-way move-class distributions, per-head agreement, and the
    distribution distances (policy vs human).
    """
    n = len(pred["side"])
    eligible = airborne_moving_mask(raw.get("onground", [False] * n),
                                    raw.get("hspeed", [0.0] * n))

    pred_side_signs = [side_class_to_sign(c) for c in pred["side"]]
    human_side_signs = [side_class_to_sign(c) for c in human["side"]]

    # HUMAN-side validity mask (weight>0). None -> all ticks valid (back-compat).
    if human_weight is None:
        human_valid = [True] * n
    else:
        human_valid = [float(w) > 0.0 for w in human_weight]
    # Human strafe cadence is measured on airborne-moving AND human-valid ticks; the
    # policy keeps the full airborne-moving mask (apples-to-apples on the policy side).
    human_eligible = [e and v for e, v in zip(eligible, human_valid)]

    def _hmask(seq):
        return _mask_seq(seq, human_valid)

    out = {
        "n_ticks": n,
        "airborne_moving_ticks": sum(1 for e in eligible if e),
        "strafe_cadence_per_min": {
            "policy": strafe_cadence_per_min(pred_side_signs, eligible,
                                             ticks_per_sec=ticks_per_sec),
            "human": strafe_cadence_per_min(human_side_signs, human_eligible,
                                            ticks_per_sec=ticks_per_sec),
        },
        "jump_rate": {"policy": bin_rate(pred["jump"]),
                      "human": bin_rate(_hmask(human["jump"]))},
        "attack_rate": {"policy": bin_rate(pred["attack"]),
                        "human": bin_rate(_hmask(human["attack"]))},
        "move_class_dist": {},
        "head_agreement": {},
    }
    for h in SIGN3_HEADS:
        pdist = class_distribution(pred[h], 3)
        hdist = class_distribution(_hmask(human[h]), 3)
        out["move_class_dist"][h] = {
            "policy": pdist, "human": hdist,
            "tv_distance": total_variation(pdist["fracs"], hdist["fracs"]),
        }
    for h in BIN_HEADS:
        pdist = class_distribution(pred[h], 2)
        hdist = class_distribution(_hmask(human[h]), 2)
        out["move_class_dist"][h] = {
            "policy": pdist, "human": hdist,
            "tv_distance": total_variation(pdist["fracs"], hdist["fracs"]),
        }
    for h in HEAD_NAMES:
        # agreement over human-valid ticks only (a weight==0 human row is a fabricated
        # label — counting it as agree/disagree skews the val-acc analog either way).
        out["head_agreement"][h] = head_agreement(_hmask(pred[h]), _hmask(human[h]))
    return out


def aggregate_metrics(per_demo: dict, *,
                      ticks_per_sec: float = DEFAULT_TICKS_PER_SEC) -> dict:
    """Pool per-demo CLASS streams into corpus-level metrics (so a long demo weights
    proportionally, matching how the human cadence is anchored).

    `per_demo[demo_id]` = {"pred": {...}, "human": {...}, "raw": {...}, optional
    "human_weight": [...]} of the same per-tick class lists `compute_demo_metrics`
    consumes. Pure python.

    Strafe-cadence FLIP COUNTS are summed PER DEMO, never counted across the pooled
    stream: a sign-flip is only meaningful WITHIN one demo's continuous tick sequence,
    so concatenating demos and counting once would inject one spurious flip at every
    demo boundary (e.g. demo A ending on a right strafe followed by demo B opening on
    a left strafe is not a real L<->R reversal). Distributions / rates / agreement are
    plain counts and DO pool by concatenation with no boundary artifact, so those are
    still computed on the pooled stream (with the same weight>0 human mask).
    """
    pooled_pred = {h: [] for h in HEAD_NAMES}
    pooled_human = {h: [] for h in HEAD_NAMES}
    pooled_raw = {"onground": [], "hspeed": []}
    pooled_weight = []
    any_weight = False
    # per-demo strafe-cadence flips, summed (NOT counted across demo boundaries)
    pol_flips = hum_flips = 0
    pol_elig_ticks = hum_elig_ticks = 0
    for _did, d in sorted(per_demo.items()):
        n_d = len(d["pred"]["side"])
        hw = d.get("human_weight")
        if hw is not None:
            any_weight = True
            pooled_weight.extend([float(w) for w in hw])
        else:
            pooled_weight.extend([1.0] * n_d)
        for h in HEAD_NAMES:
            pooled_pred[h].extend(d["pred"][h])
            pooled_human[h].extend(d["human"][h])
        pooled_raw["onground"].extend(d["raw"].get("onground", []))
        pooled_raw["hspeed"].extend(d["raw"].get("hspeed", []))
        # this demo's OWN strafe cadence (segment-local flip count), then accumulate.
        dm = compute_demo_metrics(d["pred"], d["human"], d["raw"],
                                  ticks_per_sec=ticks_per_sec, human_weight=hw)
        pol_flips += dm["strafe_cadence_per_min"]["policy"]["flips"]
        hum_flips += dm["strafe_cadence_per_min"]["human"]["flips"]
        pol_elig_ticks += dm["strafe_cadence_per_min"]["policy"]["eligible_ticks"]
        hum_elig_ticks += dm["strafe_cadence_per_min"]["human"]["eligible_ticks"]

    out = compute_demo_metrics(
        pooled_pred, pooled_human, pooled_raw, ticks_per_sec=ticks_per_sec,
        human_weight=(pooled_weight if any_weight else None))
    # Overwrite the pooled (boundary-contaminated) flip counts with the per-demo sum.
    out["strafe_cadence_per_min"]["policy"] = _cadence_from_flips(
        pol_flips, pol_elig_ticks, ticks_per_sec)
    out["strafe_cadence_per_min"]["human"] = _cadence_from_flips(
        hum_flips, hum_elig_ticks, ticks_per_sec)
    return out


def _cadence_from_flips(flips: int, eligible_ticks: int, ticks_per_sec: float) -> dict:
    """Rebuild a strafe_cadence_per_min block from an ALREADY-SUMMED flip count and
    eligible-tick count (used by aggregate_metrics, which sums flips per demo rather
    than re-counting across demo boundaries). Same shape `strafe_cadence_per_min`
    returns; the rate is flips / eligible_seconds * 60."""
    elig_seconds = eligible_ticks / ticks_per_sec if ticks_per_sec > 0 else 0.0
    rate = (flips / elig_seconds * 60.0) if elig_seconds > 0 else 0.0
    return {
        "flips": flips,
        "eligible_ticks": eligible_ticks,
        "eligible_seconds": round(elig_seconds, 4),
        "flips_per_min": round(rate, 4),
    }


# =============================================================================
# Anchor band resolution (strafe cadence). The dm3 4on4 anchor has NO L/R strafe
# band today (MVD plane has no usercmd sidemove); return null + the reason unless a
# future anchor adds a `strafe_cadence_per_min` field under metrics.movement.fields.
# =============================================================================
def resolve_strafe_anchor(anchors_path: Path | None) -> dict:
    if anchors_path is None:
        return {"anchor_band": None,
                "reason": "no --anchors provided"}
    try:
        anchors = json.loads(Path(anchors_path).read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return {"anchor_band": None,
                "reason": f"could not read anchors: {e}"}
    fields = (anchors.get("metrics", {}).get("movement", {}).get("fields", {}))
    band = fields.get("strafe_cadence_per_min")
    if not band:
        return {
            "anchor_band": None,
            "reason": (
                "anchor has no 'strafe_cadence_per_min' field. The dm3 4on4 anchor "
                "movement plane is mvd_event_rate_finite_difference (speed / air "
                "ratios / airborne-run jump_cadence_per_min) computed from MVD "
                "position events, which carry NO usercmd sidemove — so an L/R "
                "strafe-cadence band cannot be built on that plane. Policy-vs-human "
                "strafe cadence (reported here) is the meaningful open-loop signal; "
                "a strafe band would need a usercmd-bearing (.qwd) anchor pass."
            ),
            "anchor_schema": anchors.get("schema"),
        }
    pool = band.get("pool", {})
    return {
        "anchor_band": {"min": pool.get("min"), "max": pool.get("max"),
                        "mean": pool.get("mean")},
        "reason": "resolved from anchors metrics.movement.fields.strafe_cadence_per_min",
        "anchor_schema": anchors.get("schema"),
    }


def cadence_pass_fail(policy_value: float, anchor_band: dict | None) -> dict:
    """Pass iff the policy strafe cadence sits inside the elite per-player envelope
    [min,max]. When no band exists -> {pass: null} with the open-loop note (the band
    gap, NOT the policy, is the reason there is no verdict)."""
    if not anchor_band or anchor_band.get("min") is None or anchor_band.get("max") is None:
        return {"pass": None,
                "note": "no strafe-cadence anchor band — see caveats.strafe_cadence_anchor"}
    lo, hi = float(anchor_band["min"]), float(anchor_band["max"])
    return {"pass": bool(lo <= float(policy_value) <= hi),
            "band": [lo, hi], "policy_value": round(float(policy_value), 4)}


# =============================================================================
# The OPEN-LOOP caveats block — recorded verbatim in every report so a reader can
# never mistake an open-loop number for a closed-loop / aim-aware result.
# =============================================================================
def build_caveats(strafe_anchor: dict) -> dict:
    return {
        "eval_mode": "open_loop",
        "what_open_loop_means": (
            "The policy is fed the REAL held-out human agent_observation per tick and "
            "its predicted usercmd is read; the policy is NOT rolled forward in a "
            "simulator. Self state (position, velocity, onground, hspeed) at every "
            "tick is the HUMAN's, not a consequence of the policy's actions."
        ),
        "aim_head": "NOT_CLONED",
        "aim_head_detail": (
            "The BROAD policy clones movement (fwd/side/up) + jump + attack only. "
            "View/aim (cmd_delta_yaw) is carried in the catalog `actions` but is NOT "
            "cloned (deferred AIM head). So any metric needing facing/yaw is N/A."
        ),
        "na_metrics": {
            "G-MV1_face_and_run": (
                "N/A-open-loop: needs the AIM/yaw head (facing) AND the resulting "
                "motion from a closed-loop rollout. The policy controls neither here."
            ),
            "G-MV4_speed_band": (
                "N/A-open-loop: the per-tick speed is the HUMAN's recorded state, not "
                "the policy's — feeding the policy human states cannot move the speed "
                "off the human's. Needs a closed-loop pmove_sim rollout."
            ),
            "route_retention": (
                "N/A-open-loop: route/trajectory retention requires rolling the policy "
                "forward (closed loop). Open-loop predictions never advance position."
            ),
        },
        "what_is_measured": (
            "MEANINGFUL open-loop signals (predicted action pattern vs the human's own "
            "action pattern on the same demos): strafe cadence (L/R sidemove flips/min "
            "over airborne-moving ticks), jump rate, attack rate, fwd/side/up "
            "movement-class distributions, and per-head action agreement."
        ),
        "closed_loop_followup": (
            "G-MV1 / G-MV4 / route-retention require the F5 closed-loop pmove_sim "
            "rollout wave AND an AIM head; this harness is the open-loop precursor."
        ),
        "strafe_cadence_anchor": strafe_anchor.get("reason"),
    }


# =============================================================================
# TORCH + DUCKDB PATH — the only part that needs the heavy deps (runs on pinnacle).
# Everything above is pure python and unit-tested without torch/numpy/duckdb.
# =============================================================================
def _build_policy_from_checkpoint(ckpt, device):
    """Rebuild BroadBCPolicy from the checkpoint's STORED dims/head_dims (never
    hard-coded). Mirrors how train_broad_bc.py saved it (state_dict + dims +
    head_dims + hidden + ent_out + the SELF GRU config). torch is imported by the
    caller.

    The SELF input fed at inference is UNCHANGED — still the flat F_obs (=dims["f_obs"])
    last-SELF_HISTORY-tick history the rollouts/open-loop build via
    AO.assemble_self_history; the GRU reshapes it internally. We reconstruct the GRU's
    per-tick input width (self_dim) and hidden width (gru_hidden) from the checkpoint so
    the rebuilt module matches the saved state_dict exactly (defaults cover a checkpoint
    saved before the config was stamped: self_dim = the 21-wide SELF, hidden = GRU_HIDDEN).
    """
    import torch  # noqa: F401  (ensure torch present; tensors built by caller)
    from train_broad_bc import BroadBCPolicy, GRU_HIDDEN

    dims = ckpt["dims"]
    head_dims = ckpt["head_dims"]
    hidden = int(ckpt.get("hidden", 256))
    ent_out = int(ckpt.get("ent_out", 64))
    # SELF GRU encoder config — the model INPUT contract (f_obs) is unchanged; these only
    # describe the internal temporal encoder so the reconstructed GRU matches the weights.
    self_dim = int(ckpt.get("self_dim", SC.EXPECTS_SELF_DIM))
    gru_hidden = int(ckpt.get("gru_hidden", GRU_HIDDEN))
    model = BroadBCPolicy(
        dims["f_obs"], dims["f_ent"], dims["f_aux"], dims["n_max"],
        ent_out=ent_out, hidden=hidden, head_dims=tuple(head_dims),
        self_dim=self_dim, gru_hidden=gru_hidden,
    ).to(device)
    model.load_state_dict(ckpt["state_dict"])
    model.eval()
    return model, dims, head_dims


def _human_action_classes(act_state, schema: SC.ShardSchema) -> dict:
    """One catalog `actions` row -> per-head HUMAN class labels, via the SAME shared
    encoder + label-encoding the trainer used (encode_action -> encode_action_row).
    Returns {head_name: int class}. A None action encodes as idle (all-none/0)."""
    from features import agent_observation as AO
    act_vec = AO.encode_action(act_state)               # [fwd,side,up,jump,attack] in [-1,1]/{0,1}
    labels = SC.encode_action_row(act_vec, schema)      # per-head int classes (ACTION_HEADS order)
    return {name: int(labels[i]) for i, name in enumerate(HEAD_NAMES)}


def _human_action_weight(act_state) -> float:
    """Per-tick HUMAN loss weight, identical to the trainer's rule in
    ml/pipeline/build_features.py: a NULL label OR an interpolated frame -> 0.0,
    else the action `confidence` (default 1.0). A weight==0 tick is one the trainer
    excludes from the loss, so the believability metrics must exclude it from the
    human side too (otherwise the fabricated all-idle label inflates the human
    idle/no-strafe/no-jump rates and corrupts head agreement)."""
    if act_state is None:
        return 0.0
    if act_state.get("is_interp"):
        return 0.0
    return float(act_state.get("confidence", 1.0))


def run_eval(checkpoint: Path, db: Path, norm_artifact: Path, *,
             split: str = "val", map_name: str = "dm3", n_max: int = 7,
             anchors: Path | None = None, ticks_per_sec: float = DEFAULT_TICKS_PER_SEC,
             cpu: bool = False) -> dict:
    """Open-loop believability eval. NEEDS torch (policy forward) + duckdb (catalog).

    Flow:
      1. load checkpoint -> rebuild BroadBCPolicy from its stored dims/heads.
      2. read the held-out `split` episodes from the catalog via the SAME loader the
         feature build uses (ml/pipeline/build_features._load_episode_ticks): per
         (episode,tick) RAW self state + observed-others + the human `actions` row.
      3. per tick: build the agent_observation (normalized, shared encoder) -> policy
         forward -> argmax per head -> PREDICTED usercmd classes; encode the HUMAN
         action -> human classes; collect both + raw self state (onground, hspeed).
      4. compute per-demo + aggregate metrics (the pure-python helpers above).
    """
    import torch
    import numpy as np  # noqa: F401  (parity w/ trainer tensor build path)
    from features import agent_observation as AO
    # in-tree catalog loader (duckdb) — the SAME mirror the feature build reads with.
    sys.path.insert(0, str(REPO_ROOT / "ml" / "pipeline"))
    from build_features import _load_episode_ticks

    device = "cpu" if cpu else ("cuda" if torch.cuda.is_available() else "cpu")
    ckpt = torch.load(Path(checkpoint).expanduser(), map_location=device)
    model, dims, head_dims = _build_policy_from_checkpoint(ckpt, device)
    schema = SC.ShardSchema()
    norm = json.loads(Path(norm_artifact).expanduser().read_text(encoding="utf-8"))

    # episode -> tick list (RAW self + others + human act), + episode->demo_id
    episodes, ep_demo = _load_episode_ticks(Path(db).expanduser(), split=split)

    # head index in the model's output list == ACTION_HEADS order == HEAD_NAMES order.
    per_demo: dict = {}
    n_ticks_total = 0
    for eid in sorted(episodes):
        ticks = episodes[eid]
        if not ticks:
            continue
        did = str(ep_demo.get(eid, eid))
        bucket = per_demo.setdefault(did, {
            "pred": {h: [] for h in HEAD_NAMES},
            "human": {h: [] for h in HEAD_NAMES},
            "raw": {"onground": [], "hspeed": []},
            # per-tick HUMAN loss weight (action confidence; 0 on a null/interpolated/
            # zero-confidence label) — the SAME rule the trainer applies in
            # build_features.py. Lets the metrics drop fabricated 'idle' human rows.
            "human_weight": [],
        })
        # batch the whole episode through the model in one forward. The v5 policy SELF
        # input is the FLAT last-SELF_HISTORY-tick history (not the single-tick SELF); each
        # tick's history is assembled by the SHARED AO.assemble_self_history over the SELF
        # vectors UP TO that tick in this episode (left-pad-repeat-first at the episode
        # start) — byte-identical to the offline build (the SAME window-tick assembly) and
        # the closed-loop / dry-route rollouts (the SAME shared helper). Open-loop is still
        # exact: each tick's history is a function only of state at/<= that tick (no future
        # leak), so a single batched forward over the precomputed per-tick histories holds.
        OBS, ENT, EM = [], [], []
        window_selves: list = []
        for t in ticks:
            enc = AO.encode_observation(t["self"], t["others"], norm, map_name, n_max)
            window_selves.append(enc["self"])
            OBS.append(AO.assemble_self_history(window_selves, AO.SELF_HISTORY))
            ENT.append(enc["ents"])
            EM.append(enc["mask"])
        obs_t = torch.tensor(OBS, dtype=torch.float32, device=device)
        f_ent = dims["f_ent"]
        if f_ent > 0:
            ent_t = torch.tensor(ENT, dtype=torch.float32, device=device)
            em_t = torch.tensor(EM, dtype=torch.float32, device=device)
        else:
            ent_t = torch.zeros((len(OBS), n_max, 0), device=device)
            em_t = torch.zeros((len(OBS), n_max), device=device)
        aux_t = torch.zeros((len(OBS), dims["f_aux"]), device=device)  # .qwd => 0-width
        with torch.no_grad():
            logits = model(obs_t, ent_t, em_t, aux_t)          # list per head
        pred_cls = [lg.argmax(dim=1).tolist() for lg in logits]  # [head][tick]

        for j, t in enumerate(ticks):
            for hi, name in enumerate(HEAD_NAMES):
                bucket["pred"][name].append(int(pred_cls[hi][j]))
            act_state = t.get("act")
            hc = _human_action_classes(act_state, schema)
            for name in HEAD_NAMES:
                bucket["human"][name].append(hc[name])
            bucket["human_weight"].append(_human_action_weight(act_state))
            self_state = t["self"]
            og = self_state.get("onground")
            hs = self_state.get("hspeed")
            if hs is None:
                vx = float(self_state.get("vx", 0.0) or 0.0)
                vy = float(self_state.get("vy", 0.0) or 0.0)
                hs = (vx * vx + vy * vy) ** 0.5
            bucket["raw"]["onground"].append(bool(og) if og is not None else False)
            bucket["raw"]["hspeed"].append(float(hs))
            n_ticks_total += 1

    # per-demo + aggregate believability metrics (pure-python helpers)
    per_demo_metrics = {
        did: compute_demo_metrics(d["pred"], d["human"], d["raw"],
                                  ticks_per_sec=ticks_per_sec,
                                  human_weight=d.get("human_weight"))
        for did, d in sorted(per_demo.items())
    }
    agg = aggregate_metrics(per_demo, ticks_per_sec=ticks_per_sec)

    strafe_anchor = resolve_strafe_anchor(anchors)
    agg_policy_cadence = agg["strafe_cadence_per_min"]["policy"]["flips_per_min"]
    cadence_verdict = cadence_pass_fail(agg_policy_cadence, strafe_anchor["anchor_band"])

    from broad_bc import core as _core
    report = {
        "schema": "komodobots.eval_broad_believability.v1",
        "eval_mode": "open_loop",
        "inputs": {
            "checkpoint": str(Path(checkpoint).expanduser()),
            "db": str(Path(db).expanduser()),
            "norm_artifact": str(Path(norm_artifact).expanduser()),
            "split": split, "map": map_name, "n_max": n_max,
            "ticks_per_sec": ticks_per_sec,
            "anchors": str(anchors) if anchors else None,
        },
        "checkpoint_meta": {
            "arch": ckpt.get("arch"), "dims": dims, "head_dims": head_dims,
            "head_names": ckpt.get("head_names"),
            "contract_version": ckpt.get("contract_version"),
            "seed": ckpt.get("seed"), "epoch": ckpt.get("epoch"),
            "trained_val_action_accuracy": ckpt.get("val_acc"),
        },
        "corpus": {
            "n_demos": len(per_demo),
            "n_episodes": sum(1 for eid in episodes if episodes[eid]),
            "n_ticks": n_ticks_total,
            "demos": sorted(per_demo.keys()),
        },
        "aggregate": agg,
        "strafe_cadence_anchor": strafe_anchor,
        "strafe_cadence_verdict_open_loop": cadence_verdict,
        "per_demo": per_demo_metrics,
        "caveats": build_caveats(strafe_anchor),
        "provenance": {
            "git_sha": _core.git_sha(REPO_ROOT),
            "norm_artifact_version": norm.get("artifact_version", "UNSET"),
            "registry_version": norm.get("registry_version"),
            "torch": getattr(torch, "__version__", None),
            "device": device,
        },
    }
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--checkpoint", type=Path, required=True,
                    help="broad_bc_policy.pt (train_broad_bc.py output)")
    ap.add_argument("--db", type=Path, required=True,
                    help="catalog .sqlite with held-out `val` split episodes")
    ap.add_argument("--norm-artifact", type=Path, required=True,
                    help="normalization_stats.json (SAME artifact training used)")
    ap.add_argument("--split", default="val")
    ap.add_argument("--out", type=Path, required=True, help="report.json path")
    ap.add_argument("--anchors", type=Path, default=None,
                    help="references/dm3_4on4_anchors.json (optional strafe band)")
    ap.add_argument("--map", default="dm3")
    ap.add_argument("--n-max", type=int, default=7)
    ap.add_argument("--ticks-per-sec", type=float, default=DEFAULT_TICKS_PER_SEC)
    ap.add_argument("--cpu", action="store_true", help="force CPU forward")
    args = ap.parse_args(argv)

    report = run_eval(
        args.checkpoint, args.db, args.norm_artifact,
        split=args.split, map_name=args.map, n_max=args.n_max,
        anchors=args.anchors, ticks_per_sec=args.ticks_per_sec, cpu=args.cpu,
    )
    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    agg = report["aggregate"]
    pol = agg["strafe_cadence_per_min"]["policy"]
    hum = agg["strafe_cadence_per_min"]["human"]
    print(f"wrote {out}", flush=True)
    print(f"  demos={report['corpus']['n_demos']} ticks={report['corpus']['n_ticks']}",
          flush=True)
    print(f"  strafe cadence/min  policy={pol['flips_per_min']}  human={hum['flips_per_min']}",
          flush=True)
    print(f"  jump rate  policy={agg['jump_rate']['policy']['rate']} "
          f"human={agg['jump_rate']['human']['rate']}", flush=True)
    print(f"  attack rate  policy={agg['attack_rate']['policy']['rate']} "
          f"human={agg['attack_rate']['human']['rate']}", flush=True)
    print(f"  strafe verdict (open-loop): {report['strafe_cadence_verdict_open_loop']}",
          flush=True)
    print("  CAVEATS: open-loop; no AIM head; G-MV1/G-MV4/route-retention N/A "
          "(need closed-loop F5).", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
