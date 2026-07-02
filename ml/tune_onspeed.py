#!/usr/bin/env python3
"""tune_onspeed.py — T5.3 (#429): the automated tuning loop (seeded random search).

WHAT THIS IS
============
Replaces the human hyperparameter guesser: samples configurations from a documented
space, trains each one via `ml/rl_onspeed.py` (subprocess, one offline 4090, strictly
SERIAL), lets every run journal itself into the #426 experiment registry
(`--select-by-route-grade --registry ...`), ranks configurations by the HONEST
route-grade on held-out routes, seed-averages the finalists, and re-grades the single
winner on a TERTIARY never-ranked route set. The verdict is journal-backed and makes
no absolute claim (`superhuman_claim: false` is hard-coded).

DESIGN DECISIONS (dual pre-review folded — auditor + NotebookLM, 2026-07-01; the full
fold lives in plans/tuning-loop-429.md)
---------------------------------------------------------------------------------------
* Random search v1 (nblm: sound at this dimensionality; Hyperband REJECTED — it
  institutionalizes the screening trap). The sampler is one function; a Bayesian
  sampler can replace it later without touching the run/journal/rank machinery.
* NO reduced-step screening tier (nblm: PPO learning curves cross — an early winner
  can be a memorized suboptimum). Every trial runs the SAME full per-trial step
  budget, one documented number, journaled per run.
* Trial 0 is the CONTROL — the named baseline inside the same environment group. Under
  space v2 (D7, plans/d7-sustain-shaping.md) that is the PINNED sweep-2 winner with
  pre-D7 reward geometry (w_sustain 0), ALWAYS seed-verified to the full quota, and the
  verdict emits the pre-registered promotion rule against it (beats_control_margin >=
  one ranked-segment quantum + the tertiary mechanism guard) as executable fields.
  (v1's trial 0 was the trainer-default config; superseded when the PPO dims were
  pinned to the winner so the sweep isolates reward geometry.)
* Driver-owned trial identity (auditor MF-1): `config_id` is NOT computable before
  launch (it hashes the fully-resolved reward config incl. the data-derived band), so
  the resume done-set matches on the deterministic per-trial `--out-ckpt` path, and
  `config_id` is read BACK from the journal records for seed-grouping.
* Lucky-seed guard (nblm): finalists (top K configs) are re-run across
  `--verify-seeds` total seeds; a config's sweep score is the MEAN grade key across
  its runs, and the verdict also reports the WORST seed + the spread (a fragile
  winner — one elite seed, the rest failing — must be visible, never hidden in a mean).
* Tertiary test set (nblm, multiple-comparisons guard): ranking N configs against ONE
  held-out route set can overfit the winner to those routes; the final winner (only
  it) is re-graded once on the NEXT disjoint holdout chunk
  (`select_holdout_offset = reset-prefix skip + select_grade_segments`, where the
  reset-prefix skip is n_reset_segments when resets share --split and 0 when
  --reset-split is disjoint — XR.grade_holdout_offset) and the verdict reports both
  grades.
* The sweep REFUSES to start without a resolvable code version (the registry would
  journal every run provenance-incomplete = ineligible), and REFUSES a verdict when
  the journal holds more than one environment_hash (grades are not comparable across
  different code/data/norm/route pins — mirrors the registry `best` refusal).

Ticket-text note: #429's verification says "minimises the MSE score"; that wording is
superseded by the honest route-grade objective (D5/#469: adherence-MSE is speed-blind
— the observed R5 failure). The objective here is the same ordering checkpoint
selection and the registry use: seg_faster_frac, then median speedup, then lower RMSE.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import random
import re
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "pipeline"))

import experiment_registry as XR   # noqa: E402  (stdlib; the #426 journal)

LOGGER = logging.getLogger(__name__)

SPACE_VERSION = "komodobots.tune_space.v2"
# PRE-REGISTERED off-ramp (plans/tuning-loop-429.md, declared before any sweep runs):
# a winner whose tertiary (never-ranked routes) seg_faster_frac falls below HALF its
# ranked value is "overfit to the ranking routes" — refused, not crowned. A missing
# tertiary grade refuses too (fail closed: absence of evidence is not evidence).
TERTIARY_OFFRAMP_FRACTION = 0.5
# PRE-REGISTERED mechanism guard (D7, plans/d7-sustain-shaping.md §4.3): anchor-off +
# reward-GEOMETRY optimization must never crown a physics/bulldoze artifact — a winner
# whose tertiary seg_clean_mechanism_frac falls below this is refused regardless of its
# faster_frac. Fail closed on a missing field.
MECH_GUARD_MIN_CLEAN_FRAC = 0.9
# v2 space (D7, plans/d7-sustain-shaping.md §3): the PPO dims are PINNED to the sweep-2
# winner config aa1aaf5477a9 (pinnacle sweeps/20260702b verdict.json + registry — the
# 5-seed-verified anchor-off + high-w_press winner) so this sweep isolates REWARD
# GEOMETRY. minibatch 768 is within the 12x256=3072 rollout buffer (the v1 grid cap).
WINNER_PIN = {
    "lr": 0.00017745,
    "clip": 0.2373,
    "kl_coef": 0.0,             # anchor OFF (owner decision-B lane) ...
    "kl_anchor_ceiling": 1e9,   # ... PAIRED with a raised eligibility ceiling (v1 MF-3)
    "ent_coef": 0.0001077,
    "minibatch": 768,
}
# Trial 0 = the CONTROL: the pinned winner with PRE-D7 reward geometry — w_sustain 0 and
# the reward-module defaults for the rebalance dims. The incumbent going into this sweep
# IS that winner (v1's incumbent-default {} would resolve to anchor-ON lr 3e-4 w_press 1.0
# — not a valid control for the D7 question).
CONTROL_CONFIG = dict(WINNER_PIN, w_press=2.516, w_strafe=0.6, w_vel=1.0, w_sustain=0.0)
# Sampled reward-geometry dims; every key MUST exist in reward_onspeed.DEFAULT_WEIGHTS
# (test-locked) — trial_argv routes exactly these through --reward-weight.
REWARD_ARGV_KEYS = ("w_press", "w_strafe", "w_vel", "w_sustain")
SPACE_BOUNDS = {
    "lr": ("pinned", WINNER_PIN["lr"]),
    "clip": ("pinned", WINNER_PIN["clip"]),
    "kl_coef": ("pinned", 0.0),
    "kl_anchor_ceiling": ("pinned", 1e9),
    "ent_coef": ("pinned", WINNER_PIN["ent_coef"]),
    "minibatch": ("pinned", 768),
    "w_press": ("uniform", 2.0, 3.0),
    "w_strafe": ("uniform", 0.0, 0.6),
    "w_vel": ("uniform", 1.0, 3.0),
    "w_sustain": ("mix", "0.0 w.p. 0.3 (rebalance-only arm, P-vs-O readout) else log-uniform", 0.05, 0.6),
}


def sample_config(rng):
    """One config from the v2 space (D7): PPO dims pinned to the sweep-2 winner, reward-
    geometry dims sampled. w_sustain keeps explicit 0.0 arms (P=0.3) so the journal can
    separate hypothesis P (credit path, shaping) from O (optimum, rebalance) — see
    plans/d7-sustain-shaping.md §3. Its sampled range is capped at 0.6 (the gamma-drag
    early-training guard, NotebookLM fold)."""
    cfg = dict(WINNER_PIN)
    cfg["w_press"] = round(rng.uniform(2.0, 3.0), 3)
    cfg["w_strafe"] = round(rng.uniform(0.0, 0.6), 3)
    cfg["w_vel"] = round(rng.uniform(1.0, 3.0), 3)
    if rng.random() < 0.3:
        cfg["w_sustain"] = 0.0
    else:
        cfg["w_sustain"] = round(10 ** rng.uniform(math.log10(0.05), math.log10(0.6)), 4)
    return cfg


def trial_config(sweep_seed, index):
    """Deterministic config for trial `index`. Index 0 = the CONTROL (the pinned sweep-2
    winner with pre-D7 reward geometry). Same (sweep_seed, index) always yields the
    same config, which is what makes the done-set resume sound."""
    if index == 0:
        return dict(CONTROL_CONFIG)
    return sample_config(random.Random(f"{sweep_seed}:{index}"))


def trial_ckpt_path(sweep_dir, index, seed):
    return Path(sweep_dir).resolve() / "ckpts" / f"t{index:03d}_s{seed}.pt"


_TRIAL_RE = re.compile(r"t(\d+)_s(\d+)\.pt$")


def trial_index_from_path(p):
    """Recover (trial_index, seed) from a driver-minted ckpt path; None if foreign."""
    m = _TRIAL_RE.search(str(p))
    return (int(m.group(1)), int(m.group(2))) if m else None


def trial_argv(python, trainer, data, cfg, *, seed, steps, out_ckpt, registry, git_sha,
               grade_segments, n_reset_segments, reset_split=None):
    """The exact rl_onspeed invocation for one trial. --registry is passed ABSOLUTE
    (the child resolves a relative explicit path against ITS cwd) and every trial
    runs --select-by-route-grade so its journal record is ranking-eligible.
    --n-reset-segments is FORWARDED from the sweep (first real sweep 20260702: the
    trainer's default 64 exceeded the val pool of 54 qualifying episodes, so the
    skip-64 holdout was EMPTY and every run was honestly refused — the sweep must
    budget the shared pool: resets + grade + tertiary <= pool). --reset-split (when
    set) moves resets to a DISJOINT split, so the whole --split pool is available
    for grade + tertiary: budget becomes 2 x grade_segments <= pool."""
    argv = [python, str(trainer),
            "--init-ckpt", str(data["init_ckpt"]), "--db", str(data["db"]),
            "--bsp", str(data["bsp"]), "--norm-artifact", str(data["norm_artifact"]),
            "--anchors", str(data["anchors"]), "--map", str(data.get("map", "dm3")),
            "--split", str(data.get("split", "val")),
            "--out-ckpt", str(out_ckpt),
            "--registry", str(Path(registry).expanduser().resolve()),
            "--select-by-route-grade",
            "--select-grade-segments", str(grade_segments),
            "--n-reset-segments", str(n_reset_segments),
            "--steps", str(steps), "--seed", str(seed)]
    if reset_split:
        argv += ["--reset-split", str(reset_split)]
    if data.get("resource_coords"):
        argv += ["--resource-coords", str(data["resource_coords"])]
    if git_sha:
        argv += ["--git-sha", str(git_sha)]
    for k, v in sorted(cfg.items()):
        if k in REWARD_ARGV_KEYS:      # every reward-geometry dim rides --reward-weight
            argv += ["--reward-weight", f"{k}={v}"]
        else:
            argv += ["--" + k.replace("_", "-"), str(v)]
    return argv


def run_trial(argv, log_path, timeout_s):
    """Run one training subprocess, stdout+stderr appended to log_path. Returns the
    exit code (124 on timeout). A crashed/timed-out trial leaves a start-without-final
    journal record — visible, counted, never ranked."""
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "ab") as lf:
        lf.write(f"\n===== {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {' '.join(argv)}\n".encode())
        lf.flush()
        try:
            return subprocess.run(argv, stdout=lf, stderr=subprocess.STDOUT,
                                  timeout=timeout_s).returncode
        except subprocess.TimeoutExpired:
            lf.write(b"\n[tune] TRIAL TIMEOUT - killed\n")
            return 124


def completed_out_ckpts(runs):
    """Journaled out-ckpt paths of COMPLETED runs (the resume done-set; auditor MF-1:
    identity = the driver-minted path, never a precomputed config_id)."""
    done = set()
    for run in runs.values():
        if run["final"] is None:
            continue
        p = ((run["start"] or {}).get("args", {}).get("out_ckpt")
             or (run["final"].get("ckpt") or {}).get("path"))
        if p:
            done.add(str(p))
    return done


def completed_seeds_for_trial(registry, index):
    """Seeds with a COMPLETED journaled run for this trial index (driver-minted paths)."""
    seeds = set()
    for p in completed_out_ckpts(XR.join_runs(XR.read_records(registry))):
        parsed = trial_index_from_path(p)
        if parsed and parsed[0] == index:
            seeds.add(parsed[1])
    return seeds


def config_scores(runs):
    """Seed-averaged score per configuration: {(environment_hash, config_id):
    {run_ids, n, mean_key, worst_key, spread}} over ELIGIBLE runs only. config_id is
    read back from the records (seed-invariant by construction), so seed re-runs of
    one config group together. The caller must refuse a verdict across multiple
    environment hashes."""
    groups = {}
    for rid, run in sorted(runs.items()):
        ok, _ = XR.eligible(run)
        if not ok:
            continue
        key = (run["final"]["environment_hash"], run["final"]["config_id"])
        summ = run["final"]["result"]["route_grade_summary"]
        groups.setdefault(key, []).append((rid, XR.grade_key(summ)))
    out = {}
    for key, rows in groups.items():
        keys = [k for _, k in rows]
        n = len(keys)
        out[key] = {
            "run_ids": [r for r, _ in rows],
            "n": n,
            "mean_key": tuple(sum(k[i] for k in keys) / n for i in range(3)),
            "worst_key": min(keys),
            "spread": tuple(max(k[i] for k in keys) - min(k[i] for k in keys)
                            for i in range(3)),
        }
    return out


def environment_hashes(scores):
    return sorted({env for (env, _cfg) in scores})


def trial_index_of_group(runs, sc):
    """Trial index of a config-score group (parsed from its first run's driver-minted
    out_ckpt path), or None for a foreign path."""
    any_run = runs[sc["run_ids"][0]]
    parsed = trial_index_from_path(
        (any_run["start"] or {}).get("args", {}).get("out_ckpt", ""))
    return parsed[0] if parsed else None


def grade_winner_tertiary(python, eval_script, data, ckpt, *, holdout_offset,
                          grade_segments, horizon, out_json, log_path, timeout_s):
    """Grade ONE checkpoint on the tertiary (never-ranked) holdout chunk via the
    eval CLI. Returns report["route_grade"]["summary"] or None."""
    argv = [python, str(eval_script), "--checkpoint", str(ckpt),
            "--db", str(data["db"]), "--bsp", str(data["bsp"]),
            "--norm-artifact", str(data["norm_artifact"]),
            "--anchors", str(data["anchors"]), "--map", str(data.get("map", "dm3")),
            "--split", str(data.get("split", "val")),
            "--horizon", str(horizon), "--n-segments", str(grade_segments),
            "--aim", "policy", "--grade-route",
            "--select-holdout-offset", str(holdout_offset),
            "--goal-mode", "conditioned", "--out", str(out_json)]
    if data.get("resource_coords"):
        argv += ["--resource-coords", str(data["resource_coords"])]
    rc = run_trial(argv, log_path, timeout_s)
    if rc != 0:
        LOGGER.warning("tertiary grade FAILED rc=%s (see %s)", rc, log_path)
        return None
    try:
        return json.loads(Path(out_json).read_text())["route_grade"]["summary"]
    except (OSError, KeyError, json.JSONDecodeError) as e:
        LOGGER.warning("tertiary grade unreadable: %s", e)
        return None


def keep_winner(ckpt, winners_dir):
    """Copy the winner ckpt read-only into winners/ + record its sha256 (severed-
    lineage guard; the journal `verify` path can re-check it forever). Resume-safe:
    an identical already-kept winner is reused; a CHANGED one is unlocked + replaced."""
    winners_dir = Path(winners_dir)
    winners_dir.mkdir(parents=True, exist_ok=True)
    dst = winners_dir / Path(ckpt).name
    src_sha, src_size = XR.sha256_file(ckpt)
    if dst.exists():
        dst_sha, _ = XR.sha256_file(dst)
        if dst_sha == src_sha:
            return {"path": str(dst), "sha256": dst_sha, "bytes": src_size}
        dst.chmod(dst.stat().st_mode | stat.S_IWUSR)
    shutil.copy2(ckpt, dst)
    dst.chmod(dst.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    sha, size = XR.sha256_file(dst)
    return {"path": str(dst), "sha256": sha, "bytes": size}


def run_sweep(a, runner=run_trial, tertiary=grade_winner_tertiary):
    """The whole sweep. Returns the verdict dict (also written to <sweep>/verdict.json)."""
    sweep = Path(a.sweep_dir).expanduser().resolve()
    registry = sweep / "experiment_registry.jsonl"
    (sweep / "ckpts").mkdir(parents=True, exist_ok=True)
    data = {"init_ckpt": a.init_ckpt, "db": a.db, "bsp": a.bsp,
            "norm_artifact": a.norm_artifact, "anchors": a.anchors,
            "map": a.map, "split": a.split,
            "resource_coords": getattr(a, "resource_coords", None)}

    # Provenance fail-fast: without a code version every run journals
    # provenance-incomplete = ineligible, and the whole sweep would be un-rankable.
    git_sha, cv_source = XR.resolve_code_version(a.git_sha)
    if git_sha is None:
        raise SystemExit("[tune] NO code version (no --git-sha, no CODE_VERSION file, not a "
                         "git checkout) — every run would be ineligible. Stamp the sync "
                         "(git rev-parse HEAD > CODE_VERSION) or pass --git-sha.")
    print(f"[tune] code_version={git_sha[:12]} ({cv_source})  sweep={sweep}", flush=True)
    print(f"[tune] space={SPACE_VERSION} sweep_seed={a.sweep_seed} trials={a.trials} "
          f"steps/trial={a.trial_steps} (NO reduced-step screening — PPO curves cross)",
          flush=True)

    t0 = time.time()
    counts = {"completed": 0, "skipped": 0, "crashed": 0}
    planned = [(i, trial_config(a.sweep_seed, i), a.base_seed) for i in range(a.trials)]

    def launch(index, cfg, seed):
        out = trial_ckpt_path(sweep, index, seed)
        done = completed_out_ckpts(XR.join_runs(XR.read_records(registry)))
        if str(out) in done:
            counts["skipped"] += 1
            print(f"[tune] t{index:03d}_s{seed} already completed — skip (resume)", flush=True)
            return
        if a.max_hours and (time.time() - t0) > a.max_hours * 3600:
            raise TimeoutError
        argv = trial_argv(a.python, a.trainer, data, cfg, seed=seed, steps=a.trial_steps,
                          out_ckpt=out, registry=registry, git_sha=git_sha,
                          grade_segments=a.grade_segments,
                          n_reset_segments=a.n_reset_segments,
                          reset_split=getattr(a, "reset_split", None))
        print(f"[tune] t{index:03d}_s{seed} cfg={json.dumps(cfg, sort_keys=True)}", flush=True)
        rc = runner(argv, sweep / "logs" / f"t{index:03d}_s{seed}.log", a.trial_timeout)
        counts["completed" if rc == 0 else "crashed"] += 1
        if rc != 0:
            print(f"[tune] t{index:03d}_s{seed} FAILED rc={rc} (journal keeps the start "
                  f"record; log in logs/)", flush=True)

    stopped_early = False
    finalist_keys = set()
    try:
        for index, cfg, seed in planned:
            launch(index, cfg, seed)

        # ---- finalists: top-K configs by (so-far single-seed) mean, then verify-seeds
        runs = XR.join_runs(XR.read_records(registry))
        scores = config_scores(runs)
        ranked = sorted(scores.items(), key=lambda kv: kv[1]["mean_key"], reverse=True)
        finalists = ranked[:a.top_k]
        crownable = {key for key, _sc in finalists}
        # D7 (plans/d7-sustain-shaping.md §4.1): the trial-0 CONTROL is ALWAYS seed-
        # verified to the full quota — the promotion margin must never compare a 5-seed
        # winner mean to a 1-seed control point. Verification does NOT make the control
        # crownable unless it ranked top-K on its own (else an under-verified best
        # candidate could be silently displaced by a verified weak control).
        verify_worklist = list(finalists)
        if not any(trial_index_of_group(runs, sc) == 0 for _k, sc in finalists):
            ctrl_entry = next(((k, sc) for k, sc in ranked
                               if trial_index_of_group(runs, sc) == 0), None)
            if ctrl_entry is not None:
                verify_worklist.append(ctrl_entry)
        for (env, cfgid), sc in verify_worklist:
            index = trial_index_of_group(runs, sc)
            if index is None:
                print(f"[tune] finalist {cfgid}: foreign out_ckpt, cannot re-derive its "
                      f"config — skipping verify (NOT crownable without verification)",
                      flush=True)
                continue
            cfg = trial_config(a.sweep_seed, index)
            # Seed-verify to the FULL quota (Codex #474 P2): iterate candidate seeds
            # until this config has --verify-seeds COMPLETED runs — an already-complete
            # candidate never consumes the quota, a crashed one is replaced by the next
            # candidate (bounded at 4x to terminate on persistent crashers).
            candidates = [a.base_seed] + [a.base_seed + 1001 + j
                                          for j in range(a.verify_seeds * 4)]
            for seed in candidates:
                seeds_done = completed_seeds_for_trial(registry, index)
                if len(seeds_done) >= a.verify_seeds:
                    break
                if seed in seeds_done:
                    continue
                launch(index, cfg, seed)
            # Crownable ONLY at the full quota (Codex #474 round-2 P1): if replacement
            # verification seeds keep crashing, the bounded loop exits with the config
            # UNDER-verified — it must refuse/resume, never crown a one-seed finalist.
            # (The always-verified control stays NON-crownable unless it ranked top-K.)
            n_done = len(completed_seeds_for_trial(registry, index))
            if n_done >= a.verify_seeds:
                if (env, cfgid) in crownable:
                    finalist_keys.add((env, cfgid))
            else:
                print(f"[tune] finalist {cfgid}: only {n_done}/{a.verify_seeds} completed "
                      f"verification runs — NOT crownable (resume the sweep to retry)",
                      flush=True)
    except TimeoutError:
        stopped_early = True
        print(f"[tune] --max-hours budget reached — stopping (resume re-enters via the "
              f"done-set)", flush=True)
    except KeyboardInterrupt:
        stopped_early = True
        print("[tune] interrupted — sweep is resumable (done-set)", flush=True)

    # ---- verdict (journal-backed; refuses cross-environment comparison)
    runs = XR.join_runs(XR.read_records(registry))
    scores = config_scores(runs)
    envs = environment_hashes(scores)
    verdict = {
        "verdict_schema": "komodobots.tune_verdict.v2",
        "space_version": SPACE_VERSION, "space_bounds": {k: str(v) for k, v in SPACE_BOUNDS.items()},
        "sweep_seed": a.sweep_seed, "trials_planned": a.trials,
        "trial_steps": a.trial_steps, "verify_seeds": a.verify_seeds,
        "counts": dict(counts), "stopped_early": stopped_early,
        "code_version": git_sha,
        "registry": str(registry),
        # HARD-CODED honesty: the grade is RELATIVE (faster than the sim-human control
        # on held-out routes in the offline sim). The absolute claim needs the live
        # engine + a recording + pov_fuse — never this driver.
        "superhuman_claim": False,
        "caveat": ("relative offline route-grade (sim-fidelity-cancelled vs the recorded-"
                   "human control); NOT a live/absolute superhuman result"),
    }
    if not scores:
        verdict["winner"] = None
        verdict["refusal"] = "no eligible (completed + provenance-complete + graded) runs"
    elif len(envs) > 1:
        verdict["winner"] = None
        verdict["refusal"] = (f"{len(envs)} environment groups in the journal — grades are "
                              f"not comparable across code/data/norm/route pins: {envs}")
    elif not (verified := {k: v for k, v in scores.items()
                           if k in finalist_keys and v["n"] >= a.verify_seeds}):
        # Belt-and-braces on the loop-side quota gate: crownable requires the full
        # --verify-seeds count of completed AND STILL-ELIGIBLE runs at verdict time.
        verdict["winner"] = None
        verdict["refusal"] = ("no finalist reached --verify-seeds completed eligible runs "
                              "(sweep stopped early, verification crashes, or grades lost "
                              "eligibility) — resume the sweep; an under-verified config is "
                              "never crowned")
    else:
        # The crown is restricted to the SEED-VERIFIED finalist set (Codex #474 P1):
        # after the finalists' extra seeds land, a previously rank-(K+1) single-seed
        # config can outrank a verified finalist's honest mean — it must trigger
        # verification in a future sweep pass, never be crowned unverified.
        ranked_all = sorted(scores.items(), key=lambda kv: kv[1]["mean_key"], reverse=True)
        ranked = sorted(verified.items(), key=lambda kv: kv[1]["mean_key"], reverse=True)
        if ranked_all[0][0] not in finalist_keys:
            # NOTE this also fires when the ALWAYS-VERIFIED CONTROL outranks every crownable
            # finalist (verified-but-non-crownable by design): the sweep still crowns the best
            # finalist, and the readout that "nothing improved on the control" is carried by
            # beats_control_margin <= 0 -> promotion_eligible: False, never by the crown.
            verdict["note"] = (f"config {ranked_all[0][0][1]} outranks the verified winner "
                               f"on mean grade (n={ranked_all[0][1]['n']}) but is not a "
                               f"crownable finalist (unverified, or the control outside "
                               f"top-K) — a candidate must earn the crown via top-K + full "
                               f"seed verification in a sweep pass")
        (env, cfgid), sc = ranked[0]
        # deployable artifact = the best single run's ckpt among the winner's seeds
        best_rid = max(sc["run_ids"],
                       key=lambda r: XR.grade_key(runs[r]["final"]["result"]["route_grade_summary"]))
        best_ckpt = (runs[best_rid]["final"].get("ckpt") or {}).get("path")
        winner = {
            "environment_hash": env, "config_id": cfgid, "n_runs": sc["n"],
            "mean_key": sc["mean_key"], "worst_key": sc["worst_key"], "spread": sc["spread"],
            "fragile": bool(sc["n"] >= 2 and sc["worst_key"][0] <= 0.0),
            "run_ids": sc["run_ids"], "best_run": best_rid, "best_ckpt": best_ckpt,
            "config": (runs[best_rid]["start"] or {}).get("args", {}),
            "finalists": [{"config_id": c, "mean_key": s["mean_key"], "n": s["n"],
                           "worst_key": s["worst_key"]} for (_e, c), s in ranked[:a.top_k]],
        }
        # D7 promotion fields (plans/d7-sustain-shaping.md §4.2) — the pre-registered
        # rule EXECUTES here, never decoration: margin vs the always-verified control in
        # ranked-segment quanta. Fail closed: a missing or under-verified control means
        # promotion-INELIGIBLE (never assumed), while the sweep crown itself stands.
        ctrl_sc = next((s for k, s in scores.items()
                        if trial_index_of_group(runs, s) == 0), None)
        n_seg = (runs[best_rid]["final"]["result"]["route_grade_summary"]
                 or {}).get("n_segments") or 0
        quantum = (1.0 / n_seg) if n_seg else None
        winner["promotion_quantum"] = quantum
        if ctrl_sc is not None and ctrl_sc["n"] >= a.verify_seeds and quantum:
            margin = sc["mean_key"][0] - ctrl_sc["mean_key"][0]
            winner["control"] = {"n_runs": ctrl_sc["n"], "mean_key": ctrl_sc["mean_key"],
                                 "worst_key": ctrl_sc["worst_key"]}
            winner["beats_control_margin"] = margin
            promo_margin_ok = margin >= quantum
        else:
            winner["control"] = None
            winner["beats_control_margin"] = None
            promo_margin_ok = False
        tert = None
        if best_ckpt and Path(best_ckpt).is_file():
            tert = tertiary(a.python, a.eval_script, data, best_ckpt,
                            holdout_offset=XR.grade_holdout_offset(
                                getattr(a, "reset_split", None), a.split,
                                a.n_reset_segments) + a.grade_segments,
                            grade_segments=a.grade_segments, horizon=a.horizon,
                            out_json=sweep / "winner_tertiary.json",
                            log_path=sweep / "logs" / "winner_tertiary.log",
                            timeout_s=a.trial_timeout)
        winner["tertiary_grade"] = tert   # never-ranked route set (overfit guard)
        winner["tertiary_report"] = str(sweep / "winner_tertiary.json")
        winner["tertiary_log"] = str(sweep / "logs" / "winner_tertiary.log")
        # The pre-registered off-ramp is EXECUTABLE, not decoration (Codex #474 P1):
        # tertiary missing -> fail closed; tertiary collapse vs the ranked value ->
        # overfit to the ranking routes. Either way: NO crowned winner — the refused
        # candidate stays in the verdict, fully audited, and is NOT blessed into
        # winners/.
        ranked_frac = sc["mean_key"][0]
        tert_frac = (tert or {}).get("seg_faster_frac")
        mech_frac = (tert or {}).get("seg_clean_mechanism_frac")
        if tert_frac is None:
            verdict["winner"] = None
            verdict["refusal"] = ("tertiary grade unavailable — cannot verify the top "
                                  "config on never-ranked routes (fail closed)")
            verdict["refused_candidate"] = winner
        elif tert_frac < TERTIARY_OFFRAMP_FRACTION * ranked_frac:
            verdict["winner"] = None
            verdict["refusal"] = (f"overfit_to_ranking_routes: tertiary seg_faster_frac "
                                  f"{tert_frac} < {TERTIARY_OFFRAMP_FRACTION} x ranked "
                                  f"{ranked_frac}")
            verdict["refused_candidate"] = winner
        elif mech_frac is None or mech_frac < MECH_GUARD_MIN_CLEAN_FRAC:
            # D7 pre-registered mechanism guard (plans/d7-sustain-shaping.md §4.3), fail
            # closed on a missing field: anchor-off geometry optimization must never
            # crown a physics/bulldoze artifact, however fast it grades.
            verdict["winner"] = None
            verdict["refusal"] = (f"mechanism_guard: tertiary seg_clean_mechanism_frac "
                                  f"{mech_frac} < {MECH_GUARD_MIN_CLEAN_FRAC}")
            verdict["refused_candidate"] = winner
        else:
            winner["promotion_eligible"] = bool(promo_margin_ok)
            winner["kept"] = keep_winner(best_ckpt, sweep / "winners")
            verdict["winner"] = winner

    (sweep / "verdict.json").write_text(json.dumps(verdict, indent=2, default=str),
                                        encoding="utf-8")
    print(f"[tune] verdict -> {sweep / 'verdict.json'}", flush=True)
    print(f"[tune] {verdict['caveat']}", flush=True)
    if verdict.get("winner"):
        w = verdict["winner"]
        print(f"[tune] winner config_id={w['config_id']} n={w['n_runs']} "
              f"mean={w['mean_key']} worst={w['worst_key']}"
              f"{' FRAGILE' if w['fragile'] else ''}", flush=True)
    return verdict


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sweep-dir", required=True, help="all sweep artifacts land here")
    ap.add_argument("--init-ckpt", required=True)
    ap.add_argument("--db", required=True)
    ap.add_argument("--bsp", required=True)
    ap.add_argument("--norm-artifact", required=True)
    ap.add_argument("--anchors", required=True)
    ap.add_argument("--resource-coords", default=None,
                    help="goal-conditioning resource coords json (5th data arg on pinnacle)")
    ap.add_argument("--map", default="dm3")
    ap.add_argument("--split", default="val")
    ap.add_argument("--reset-split", default=None,
                    help="split trial RESETS draw from (default: --split). Disjoint from "
                         "--split -> the whole --split pool serves grade + tertiary "
                         "(budget 2 x grade_segments <= pool)")
    ap.add_argument("--trials", type=int, default=30,
                    help="sampled configs incl. trial 0 = the incumbent-default control")
    ap.add_argument("--trial-steps", type=int, default=200000,
                    help="env steps per trial — ONE budget for every trial (no screening tier)")
    ap.add_argument("--sweep-seed", type=int, default=429, help="sampler RNG seed (journaled)")
    ap.add_argument("--base-seed", type=int, default=0, help="trainer --seed for first runs")
    ap.add_argument("--top-k", type=int, default=3, help="finalist configs to seed-verify")
    ap.add_argument("--verify-seeds", type=int, default=5,
                    help="total runs per finalist config (nblm: 3 is the bare minimum for PPO)")
    ap.add_argument("--grade-segments", type=int, default=12)
    ap.add_argument("--n-reset-segments", type=int, default=64,
                    help="FORWARDED to every trial as the trainer's --n-reset-segments AND used as "
                         "the tertiary offset base. BUDGET THE POOL: this + 2 x --grade-segments must "
                         "not exceed the split's qualifying episode pool (val dm3 slice measured at 54 "
                         "for horizon 385 -> use 30 there), or the holdout/tertiary sets come up EMPTY "
                         "and every run is refused as ungradable.")
    ap.add_argument("--horizon", type=int, default=385)
    ap.add_argument("--max-hours", type=float, default=0, help="0 = unbounded")
    ap.add_argument("--trial-timeout", type=int, default=7200, help="seconds per subprocess")
    ap.add_argument("--git-sha", default=None,
                    help="code version override (else CODE_VERSION file > git rev-parse)")
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--trainer", default=str(Path(__file__).resolve().parent / "rl_onspeed.py"))
    ap.add_argument("--eval-script",
                    default=str(Path(__file__).resolve().parent / "eval_broad_closedloop.py"))
    a = ap.parse_args(argv)
    run_sweep(a)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    sys.exit(main())
