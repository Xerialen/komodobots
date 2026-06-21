"""synth_shard.py — tiny synthetic BROAD shard generator for the offline CPU smoke.

DEPS-FREE. Produces shards that match the SHARD CONTRACT (shard_contract.py):
obs / entities / ent_mask / audio / team / act / mask / weight + meta. The
SIGNAL is deliberately learnable so a tiny trainer's loss drops (otherwise a
"trains to completion" smoke proves nothing):

  * the action depends on BOTH self obs AND the observed-other entities (so a
    move-only model could NOT fit it — this is what proves the input is broad).
  * fixed RNG seed => byte-identical shards => reproducible loss.

On-disk format is portable so the SAME shard feeds both the stdlib smoke and the
torch trainer:
  * if numpy is importable -> a real `.npz` (np.savez), exactly what FEAT will emit;
  * else -> a stdlib `<name>.shard.json.gz` (gzip+json) with the same arrays as
    nested lists. `ml/broad_bc/dataset.py` reads either transparently.

This stands in for FEAT's gold tensors ONLY for the smoke; the real run reads
FEAT's WebDataset/.npz shards. Real shards are gitignored (large); these synthetic
ones are generated on demand and never committed.
"""
from __future__ import annotations

import gzip
import json
import math
import random
from pathlib import Path

from . import shard_contract as SC


def _logistic(x: float) -> float:
    if x < -60:
        return 0.0
    if x > 60:
        return 1.0
    return 1.0 / (1.0 + math.exp(-x))


def make_synthetic_shard(
    *,
    n_windows: int,
    obs_dim: int = SC.EXPECTS_SELF_DIM,
    ent_dim: int = 10,
    n_max: int = SC.DEFAULT_N_MAX,
    audio_dim: int = 4,
    team_dim: int = 6,
    self_history: int = SC.EXPECTS_SELF_HISTORY,
    demo_id: str = "synthA",
    player_id: str = "synthP",
    map_id: str = "dm3",
    seed: int = 0,
    k: int = 1,
) -> dict:
    """Build one synthetic shard (K=k windows, default single-step BC rows).

    Returns the in-memory shard dict (lists). The action labels are a learnable
    function of self obs AND the entity channel, so fitting it REQUIRES the broad
    input.

    v5: also emits the `self_history` field [self_history*obs_dim] = ONE FLAT history PER
    WINDOW (the last-real-tick history — matching the real build, which stores only that one
    tick the trainer/loader read, not a per-tick [k, HD]). For the default single-step (k=1)
    synth rows there is exactly one tick, so the history is the current SELF tiled
    `self_history` times (the build's left-pad-repeat-first when one tick is available),
    keeping the last obs_dim block == that tick's obs. This is the SELF input the
    trainer/smoke consume; per-window it is [obs_dim*self_history], one vector per row.
    """
    rng = random.Random(seed)
    F_act = len(SC.ACT_COLS)
    hist_dim = self_history * obs_dim

    obs, self_hist, ents, ent_mask, audio, team, act, mask, weight = \
        [], [], [], [], [], [], [], [], []

    for _w in range(n_windows):
        w_obs, w_ent, w_em, w_au, w_tm, w_act, w_mask, w_w = \
            [], [], [], [], [], [], [], []
        last_o = None                      # last real tick's SELF -> the window's history
        for _t in range(k):
            o = [rng.gauss(0.0, 1.0) for _ in range(obs_dim)]
            last_o = o
            # number of visible others this tick (1..n_max), rest padded
            n_vis = rng.randint(1, n_max)
            ent_rows, em_row = [], []
            for j in range(n_max):
                if j < n_vis:
                    e = [rng.gauss(0.0, 1.0) for _ in range(ent_dim)]
                    em_row.append(1.0)
                else:
                    e = [0.0] * ent_dim          # zeroed pad (contract: pad slots zeroed)
                    em_row.append(0.0)
                ent_rows.append(e)
            au = [rng.gauss(0.0, 1.0) for _ in range(audio_dim)]
            tm = [rng.gauss(0.0, 1.0) for _ in range(team_dim)]

            # --- the LEARNABLE target: self + nearest-other interaction ---------
            # pooled mean of the VISIBLE entity vectors (this is exactly the
            # enemy/team-aware signal the broad model must use).
            pooled = [0.0] * ent_dim
            for j in range(n_vis):
                for c in range(ent_dim):
                    pooled[c] += ent_rows[j][c]
            for c in range(ent_dim):
                pooled[c] /= max(n_vis, 1)

            # forward move: chase the nearest other (sign of pooled[0]) but modulated
            # by own speed proxy obs[0]  -> needs both channels.
            fwd_drive = 1.4 * pooled[0] + 0.6 * o[0]
            side_drive = 1.4 * pooled[1] - 0.5 * o[1]
            up_drive = 0.9 * o[2] + 0.7 * pooled[2]
            # jump when closing distance fast: pooled[3] big & moving (obs[3])
            jump_p = _logistic(1.6 * pooled[3] + 0.8 * o[3])
            # attack when an enemy is dead-ahead AND we have LoS proxy: pooled[4]&obs[4]
            attack_p = _logistic(1.8 * pooled[4] + 0.9 * o[4] - 0.3)

            fwd = 1.0 if fwd_drive > 0.25 else (-1.0 if fwd_drive < -0.25 else 0.0)
            side = 1.0 if side_drive > 0.25 else (-1.0 if side_drive < -0.25 else 0.0)
            up = 1.0 if up_drive > 0.4 else (-1.0 if up_drive < -0.4 else 0.0)
            jump = 1.0 if rng.random() < jump_p else 0.0
            attack = 1.0 if rng.random() < attack_p else 0.0

            a = [0.0] * F_act
            a[SC.ACT_COLS.index("forwardmove")] = fwd
            a[SC.ACT_COLS.index("sidemove")] = side
            a[SC.ACT_COLS.index("upmove")] = up
            a[SC.ACT_COLS.index("jump_button")] = jump
            a[SC.ACT_COLS.index("attack_button")] = attack
            # turn columns: continuous, not cloned — fill with a benign value
            a[SC.ACT_COLS.index("cmd_delta_yaw_sin")] = math.sin(o[0])
            a[SC.ACT_COLS.index("cmd_delta_yaw_cos")] = math.cos(o[0])

            w_obs.append(o); w_ent.append(ent_rows); w_em.append(em_row)
            w_au.append(au); w_tm.append(tm); w_act.append(a)
            w_mask.append(1.0); w_w.append(1.0)
        # ONE flat self_history per window: the last real tick's SELF tiled `self_history`
        # times (k=1 synth has a single tick; for k>1 this is the last-real-tick history,
        # matching the real build, which stores only that tick). last block == last obs.
        sh = list(last_o) * self_history
        obs.append(w_obs); self_hist.append(sh)
        ents.append(w_ent); ent_mask.append(w_em)
        audio.append(w_au); team.append(w_tm); act.append(w_act)
        mask.append(w_mask); weight.append(w_w)

    meta = {
        "episode_id": -1,
        "demo_id": demo_id,
        "player_id": player_id,
        "map_id": map_id,
        "start_tick": 0,
        "label_source": "synthetic",
        "registry_version": SC.EXPECTS_REGISTRY_VERSION,
        "norm_artifact_version": "SYNTH-0",
        "k": k,
        "n_windows": n_windows,
        "obs_dim": obs_dim,
        "self_history": self_history,
        "self_history_dim": hist_dim,
        "ent_dim": ent_dim,
        "n_max": n_max,
        "audio_dim": audio_dim,
        "team_dim": team_dim,
        "contract_version": SC.SHARD_CONTRACT_VERSION,
    }
    return {
        SC.KEY_OBS: obs, SC.KEY_SELF_HISTORY: self_hist,
        SC.KEY_ENTITIES: ents, SC.KEY_ENT_MASK: ent_mask,
        SC.KEY_AUDIO: audio, SC.KEY_TEAM: team, SC.KEY_ACT: act,
        SC.KEY_MASK: mask, SC.KEY_WEIGHT: weight, SC.KEY_META: meta,
    }


def write_shard(shard: dict, out_path: Path) -> Path:
    """Write a shard. Prefers real `.npz` (numpy present) else stdlib `.json.gz`.

    `out_path` is the basename (extension is chosen by availability and returned).
    """
    out_path = Path(out_path)
    try:
        import numpy as np  # noqa: WPS433  (optional fast path)
    except Exception:       # noqa: BLE001
        np = None

    meta = shard[SC.KEY_META]
    if np is not None:
        p = out_path.with_suffix(".npz")
        arrays = {
            k: np.asarray(shard[k], dtype=np.float32)
            for k in (SC.KEY_OBS, SC.KEY_SELF_HISTORY, SC.KEY_ENTITIES, SC.KEY_ENT_MASK,
                      SC.KEY_AUDIO,
                      SC.KEY_TEAM, SC.KEY_ACT, SC.KEY_MASK, SC.KEY_WEIGHT)
        }
        np.savez(p, meta=json.dumps(meta), **arrays)
        return p
    p = out_path.with_suffix(".shard.json.gz")
    with gzip.open(p, "wt", encoding="utf-8") as fh:
        json.dump(shard, fh)
    return p


def make_synthetic_corpus(
    out_dir: Path,
    *,
    n_demos: int = 4,
    windows_per_demo: int = 256,
    seed: int = 0,
    **shard_kwargs,
) -> list:
    """Generate a small multi-demo synthetic corpus (one shard per demo) for the
    smoke. Demo ids drive the train/val split-by-demo, so >1 demo is required."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for d in range(n_demos):
        shard = make_synthetic_shard(
            n_windows=windows_per_demo,
            demo_id=f"synthdemo{d:02d}",
            player_id=f"synthplayer{d % 3}",   # players overlap demos (realistic)
            seed=seed * 1000 + d,
            **shard_kwargs,
        )
        p = write_shard(shard, out_dir / f"synth-{d:04d}")
        paths.append(p)
    return paths
