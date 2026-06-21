#!/usr/bin/env python3
"""rl_onspeed.py — PPO-on-speed RL loop (movement-v5). The matched lever for the
closed-loop bunnyhop-SPEED skill the supervised family (BC/reweight/GRU-seq/DAgger)
could not make: cs10 over-presses fwd ~0.83-0.96 closed-loop (human 0.13-0.36) ->
air-strafe accel dies -> G-MV4 speed band (252-316) fails. RL optimizes downstream
SPEED RETURN with self-yaw (the policy owns its own movement-yaw, the speed mechanism)
+ credit assignment, and an explicit escape from the over-press basin.

REUSE (this loop rebuilds NOTHING that exists):
  * ENV    = the offline pmove sim (scripts/pmove_sim) + the eval's OWN goal-conditioned
             v5 obs path (eval_broad_closedloop._self_state_from_sim + AO.encode_observation
             + _assemble_self_history), so the policy sees the BYTE-PARITY obs it was
             warm-started on. Reset states = the catalog val SEGMENTS (mid-route human
             states AT SPEED) via _load_episode_ticks + select_start_segments -> the
             over-press states are ON-POLICY (rl-plan STEP 1 RF-basin (b)).
  * POLICY = train_broad_bc.BroadBCPolicy(yaw_head=True), warm-started from the
             BC-pretrained believable-aim ckpt (cs10 move/jump heads + believable yaw
             head). A small RLHead adds the VALUE head + a learned yaw log-std off the
             SAME shared trunk feature (_trunk_feat). The KL-ANCHOR reference is a FROZEN
             copy of the warm-start (believable-aim), NOT over-pressing cs10.
  * REWARD = Phi-shaped achievable-speed-gain (sqrt(s^2+900)-s potential, policy-invariant)
             + in-band horizontal speed (soft_band toward 252-316) + route-progress
             (goal-distance decrease) + anti-hack penalties (spin/jitter) + KL-anchor to
             the believable-aim reference. (The fragile hand-set believability THRESHOLD
             term is DROPPED per STEP-0; believability == the KL-anchor.)
  * PPO    = clipped surrogate + value loss + entropy floor + KL-anchor term; conservative
             (small LR, KL/clip guard, mid-route resets, entropy floor) so it ESCAPES the
             over-press basin without leaving the human manifold.

REUSABLE CLI (rounds 2+ just continue from a ckpt + re-eval; no rebuild):
  TRAIN+SAVE:  python -m ml.rl_onspeed --init-ckpt <warmstart_or_prev>.pt --steps 200000 \
                   --out-ckpt <round_k>.pt --db ... --bsp ... --norm-artifact ... \
                   --anchors ... --resource-coords ...
  EVAL-ONLY :  python -m ml.rl_onspeed --eval --init-ckpt <round_k>.pt --db ... --bsp ...
                   (delegates to eval_broad_closedloop.run_eval + eval_broad_dryroute,
                    GOAL-CONDITIONED, on hard routes + controls -> the METRIC VECTOR JSON)

Eval-integrity: training NEVER reads the gate anchors for its band (the reward band is a
DISJOINT player split, reward_dryrun LEAKAGE SPLIT). The metric vector is produced by the
SAME eval harness the judge uses, from raw. Offline only (pinnacle GPU); no live server.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import deque
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

HERE = Path(__file__).resolve().parent          # ml/
REPO_ROOT = HERE.parent
for p in (str(REPO_ROOT / "scripts"), str(HERE), str(HERE / "pipeline")):
    if p not in sys.path:
        sys.path.insert(0, p)

# --- REUSE the eval's goal-conditioned obs path + helpers (byte-parity with warm-start) ---
import pmove_sim as PM                                          # noqa: E402
from features import agent_observation as AO                    # noqa: E402
from broad_bc import shard_contract as SC                       # noqa: E402
from train_broad_bc import BroadBCPolicy, GRU_HIDDEN            # noqa: E402
import eval_broad_closedloop as EV                              # noqa: E402
from eval_broad_believability import _build_policy_from_checkpoint  # noqa: E402
from build_features import _load_episode_ticks                  # noqa: E402
import route_goals as RG                                        # noqa: E402

# ---- reward physics (REUSE reward_dryrun constants verbatim) ---------------------------
WISHSPD_CAP = 30.0
PHI_C = WISHSPD_CAP * WISHSPD_CAP                # 900 (the analytic per-tick achievable gain)
MOVE_MAG = 400.0                                 # usercmd move magnitude (EV.MOVE_MAG)
SELF_HISTORY = SC.EXPECTS_SELF_HISTORY           # 16
SELF_DIM = SC.EXPECTS_SELF_DIM                   # 21


def phi(s: float) -> float:
    """Analytic per-tick achievable horizontal-speed gain at speed s (greedy-perp)."""
    return math.sqrt(s * s + PHI_C) - s


def soft_band(x: float, lo: float, hi: float) -> float:
    """1.0 inside [lo,hi], gaussian-decaying (band-width scale) below/above. The over-press
    failure is BELOW band -> this pulls the policy up toward the band."""
    if lo <= x <= hi:
        return 1.0
    w = max(hi - lo, 1e-6)
    if x < lo:
        return math.exp(-((lo - x) / w) ** 2)
    return math.exp(-((x - hi) / w) ** 2)


def wrap180(d: float) -> float:
    d = (d + 180.0) % 360.0 - 180.0
    return d if d > -180.0 else d + 360.0


# =============================================================================
# Policy wrapper: warm-start BroadBCPolicy(yaw_head=True) + value head + yaw log-std.
# The discrete heads sample from logits (Categorical); the continuous yaw delta is
# Gaussian(mean = yaw_head decoded angle, std = exp(log_std)). Value + log_std are the
# ONLY new params; everything else is the believable-aim warm-start.
# =============================================================================
class RLPolicy(nn.Module):
    def __init__(self, base: BroadBCPolicy, init_log_std: float = math.log(6.0)):
        super().__init__()
        self.base = base
        hidden = base.trunk[-2].out_features  # 256
        self.value_head = nn.Linear(hidden, 1)
        # learned scalar log-std for the per-tick yaw DELTA (degrees). Init ~6 deg so the
        # policy can explore turn angles without leaving the human aim manifold immediately.
        self.yaw_log_std = nn.Parameter(torch.tensor(float(init_log_std)))

    def trunk(self, obs, ent, emask, aux):
        return self.base._trunk_feat(obs, ent, emask, aux)

    def forward(self, obs, ent, emask, aux):
        """Return (logits_list[5], yaw_mean_deg[B], value[B]). yaw_mean is the believable
        per-tick turn DELTA the BC-pretrained head proposes, decoded atan2(sin,cos)."""
        h = self.trunk(obs, ent, emask, aux)
        logits = [head(h) for head in self.base.heads]
        yaw2 = self.base.yaw_head(h)                          # [B,2] raw (sin,cos)
        yaw_mean = torch.atan2(yaw2[:, 0], yaw2[:, 1]) * (180.0 / math.pi)  # deg delta [B]
        value = self.value_head(h).squeeze(-1)               # [B]
        return logits, yaw_mean, value


def load_rl_policy(init_ckpt: Path, device: str):
    """Load init ckpt -> RLPolicy. Accepts BOTH a believable-aim warm-start (no value
    head yet) AND a prior RL round ckpt (has value_head/yaw_log_std). Returns
    (rl, frozen_anchor, ckpt_meta). The frozen_anchor = a believable-aim reference for
    the KL term (a deepcopy of the base policy at THIS init; for round 1 that IS the
    believable-aim warm-start, exactly what rl-plan wants)."""
    import copy
    ckpt = torch.load(Path(init_ckpt).expanduser(), map_location=device, weights_only=False)
    base, dims, head_dims = _build_policy_from_checkpoint(ckpt, device)  # yaw_head auto-detected
    if not getattr(base, "has_yaw_head", False) or base.yaw_head is None:
        raise ValueError("init ckpt has NO yaw head; RL self-yaw needs the BC-pretrained "
                         "believable-aim yaw head (warm-start from rl_warmstart_v5_yaw.pt)")
    rl = RLPolicy(base).to(device)
    # if continuing from a prior RL round, restore value head + yaw log-std
    if ckpt.get("rl_round") is not None and "rl_extra" in ckpt:
        rl.value_head.load_state_dict(ckpt["rl_extra"]["value_head"])
        with torch.no_grad():
            rl.yaw_log_std.copy_(torch.tensor(float(ckpt["rl_extra"]["yaw_log_std"])))
    # frozen believable-aim anchor (NOT cs10): the policy at init, no grad.
    anchor = copy.deepcopy(base).to(device).eval()
    for p in anchor.parameters():
        p.requires_grad = False
    return rl, anchor, ckpt, dims, head_dims


def save_rl_ckpt(out_path: Path, rl: RLPolicy, src_ckpt: dict, dims, head_dims,
                 round_idx: int, meta: dict):
    """Save a ckpt that (a) the EVAL harness can load as a plain BroadBCPolicy (the base
    state_dict, yaw_head=True) AND (b) THIS loop can continue (rl_extra). The eval's
    _build_policy_from_checkpoint reads dims/head_dims/yaw_head/state_dict and ignores the
    extra keys -> the SAME ckpt evals AND continues. Rounds 2+ just --init-ckpt this."""
    out = {
        "state_dict": rl.base.state_dict(),          # the policy the eval loads (yaw_head incl.)
        "dims": dims, "head_dims": list(head_dims), "head_names": SC.head_names(),
        "hidden": int(src_ckpt.get("hidden", 256)), "ent_out": int(src_ckpt.get("ent_out", 64)),
        "self_dim": int(src_ckpt.get("self_dim", SELF_DIM)),
        "gru_hidden": int(src_ckpt.get("gru_hidden", GRU_HIDDEN)),
        "yaw_head": True, "yaw_loss": src_ckpt.get("yaw_loss", "cosine"),
        "arch": "BroadBCPolicy", "contract_version": SC.SHARD_CONTRACT_VERSION,
        "rl_round": round_idx,
        "rl_extra": {  # so THIS loop can continue (value head + yaw std); eval ignores it
            "value_head": rl.value_head.state_dict(),
            "yaw_log_std": float(rl.yaw_log_std.detach().cpu()),
        },
        "warmstart_of": str(src_ckpt.get("warmstart_of", "")),
        "rl_meta": meta,
        "note": "RL-on-speed round ckpt: believable-aim base + PPO-on-speed update. "
                "Loads as a plain BroadBCPolicy for the eval; rl_extra continues training.",
    }
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    torch.save(out, Path(out_path).expanduser())


# =============================================================================
# ENV — a single pmove episode with the goal-conditioned v5 obs + SELF-YAW.
# Reset = a catalog val segment (mid-route human state AT SPEED). The policy owns the
# executed view-yaw (integrates its per-tick turn delta), which drives BOTH the obs
# (yaw_sin/cos, face_vel_angle, yaw_rate) AND the pmove wishdir -> the speed mechanism.
# =============================================================================
class PmoveEnv:
    def __init__(self, world, stats, segments, *, n_max=7, map_name="dm3",
                 horizon=385, band_lo=252.0, band_hi=316.0, seed=0):
        self.world = world
        self.stats = stats
        self.segments = segments                 # list of (eid, start, seg) human segments
        self.n_max = n_max
        self.map_name = map_name
        self.horizon = horizon
        self.band_lo, self.band_hi = band_lo, band_hi
        self.rng = np.random.RandomState(seed)
        self.pm = PM.Pmove(world)
        self._reset_state()

    def _reset_state(self):
        # Reset from a RANDOM catalog val segment (mid-route human state at speed). The
        # segment also carries the per-tick hindsight goal -> goal-conditioned obs in-sim.
        si = self.rng.randint(len(self.segments))
        self.seg = self.segments[si][2]
        t0 = self.seg[0]["self"]
        self.st = PM.PlayerState(
            [float(t0.get("ox", 0.0)), float(t0.get("oy", 0.0)), float(t0.get("oz", 0.0))],
            [float(t0.get("vx", 0.0)), float(t0.get("vy", 0.0)), float(t0.get("vz", 0.0))],
        )
        self.k = 0
        # the executed view yaw is the policy's OWN, integrated from per-tick deltas; seed
        # it at the human's first-tick yaw so the bot starts pointed down the route.
        self.cur_yaw = float(t0.get("yaw", 0.0) or 0.0)
        self.prev_yaw = None
        self.self_hist = deque(maxlen=SELF_HISTORY)
        self.prev_hspeed = math.hypot(self.st.velocity[0], self.st.velocity[1])
        # goal of the FINAL recorded tick of this segment = the route target (for progress).
        self._final_goal = self._segment_goal(min(len(self.seg) - 1, self.horizon))

    def _segment_goal(self, idx):
        g = self.seg[idx]["self"].get("goal") if idx < len(self.seg) else None
        return (float(g[0]), float(g[1])) if g is not None else None

    def _build_obs(self):
        """Build the goal-conditioned v5 obs for the CURRENT sim state + the policy's OWN
        executed yaw (self-yaw), via the eval's SHARED path. Returns (self_in[336],
        ents[n_max,13], mask[n_max]) as python lists (byte-parity with training/eval)."""
        msec = 13
        rec_act = self.seg[self.k].get("act") if self.k < len(self.seg) else None
        if rec_act and rec_act.get("msec"):
            msec = rec_act["msec"]
        yaw_rate = EV._yaw_rate_degps(self.cur_yaw, self.prev_yaw, float(msec) / 1000.0)
        # per-tick hindsight goal (the SAME label the build/eval stamp; goal-conditioned).
        tick_goal = self.seg[self.k]["self"].get("goal") if self.k < len(self.seg) else None
        ss = EV._self_state_from_sim(self.st, self.cur_yaw, 0.0, yaw_rate=yaw_rate,
                                     goal=tick_goal)
        enc = AO.encode_observation(ss, [], self.stats, self.map_name, self.n_max)
        self.self_hist.append(enc["self"])
        self_in = EV._assemble_self_history(self.self_hist, SELF_HISTORY)
        return self_in, enc["ents"], enc["mask"], msec

    def reset(self):
        self._reset_state()
        return self._build_obs()

    def step(self, fwd_cls, side_cls, up_cls, jump_cls, yaw_delta_deg, msec):
        """Apply the sampled discrete heads + the policy's per-tick yaw DELTA (self-yaw).
        Integrate the yaw, step pmove, return (reward, done, info)."""
        fwd_mag, side_mag, up_mag, jump_bit = EV.decode_move_heads(
            [fwd_cls, side_cls, up_cls, jump_cls, 0])
        # SELF-YAW: integrate the policy's per-tick turn delta onto the executed view yaw.
        # This is the mechanism — the yaw drives the air-strafe wishdir in pmove AND was
        # already fed into the obs this tick (cur_yaw). Clamp the delta to a sane per-tick
        # turn so a blown-up sample can't teleport the aim.
        yaw_delta_deg = float(max(-90.0, min(90.0, yaw_delta_deg)))
        self.prev_yaw = self.cur_yaw
        self.cur_yaw = self.cur_yaw + yaw_delta_deg
        angles = [0.0, self.cur_yaw, 0.0]
        cmd = PM.Cmd(int(msec), angles, [fwd_mag, side_mag, up_mag], jump_bit)
        self.pm.run_frame(self.st, cmd)

        vx, vy = self.st.velocity[0], self.st.velocity[1]
        hspeed = math.hypot(vx, vy)
        onground = bool(self.st.onground)

        # ---- REWARD (rl-plan §B; reward_dryrun physics) -------------------------------
        # r_speed: soft in-band horizontal speed (the G-MV4 objective; over-press is below).
        r_speed = soft_band(hspeed, self.band_lo, self.band_hi)
        # r_phi: realized fraction of the analytic per-tick ACHIEVABLE gain (builds speed).
        avail = phi(self.prev_hspeed)
        ds = hspeed - self.prev_hspeed
        r_phi = min(1.0, max(0.0, ds) / avail) if avail > 1e-6 else 0.0
        # r_progress: route-progress = goal-distance DECREASE this tick (keeps it on-route,
        # not orbiting — the greedy-yaw orbit failure). Normalized by a per-tick scale.
        r_prog = 0.0
        if self._final_goal is not None:
            gx, gy = self._final_goal
            d_now = math.hypot(gx - self.st.origin[0], gy - self.st.origin[1])
            d_prev = getattr(self, "_prev_goal_dist", d_now)
            r_prog = max(-1.0, min(1.0, (d_prev - d_now) / 50.0))  # +1 ~ 50qu closer/tick
            self._prev_goal_dist = d_now
        # p_hack: spin-in-place (big yaw_rate, tiny displacement). pogo/jitter handled by
        # r_speed/route. dt for the displacement proxy.
        dt = float(msec) / 1000.0
        yaw_rate = abs(yaw_delta_deg) / dt if dt > 0 else 0.0
        disp = hspeed * dt
        p_hack = 1.0 if (yaw_rate > 600.0 and disp < 1.0) else 0.0

        reward = (1.0 * r_speed + 0.5 * r_phi + 0.5 * r_prog - 1.0 * p_hack)

        self.prev_hspeed = hspeed
        self.k += 1
        # done: route/segment exhausted, time-limit, or fell out of bounds (origin NaN/away).
        done = (self.k >= min(self.horizon, len(self.seg) - 1))
        if not (math.isfinite(self.st.origin[0]) and math.isfinite(self.st.origin[1])):
            done = True
        info = {"hspeed": hspeed, "onground": onground, "fwd_press": int(fwd_cls == 2),
                "r_speed": r_speed, "r_phi": r_phi, "r_prog": r_prog, "p_hack": p_hack}
        if done:
            obs = self._build_obs()  # terminal obs (unused for bootstrap if done)
        else:
            obs = self._build_obs()
        return obs, reward, done, info


# =============================================================================
# Rollout collection (vectorized over N envs) + PPO update.
# =============================================================================
def collect_rollout(envs, rl, device, n_steps, *, deterministic=False):
    """Collect n_steps PER env. Returns flat tensors for the PPO update + diagnostics.
    The discrete heads sample from Categorical(logits); the yaw delta ~ Normal(mean,std).
    Self-yaw is applied IN the env.step (the executed yaw drives obs+pmove)."""
    N = len(envs)
    obs_buf, ent_buf, em_buf = [], [], []
    act_buf = {"fwd": [], "side": [], "up": [], "jump": []}
    logp_buf, yaw_buf, yawlogp_buf = [], [], []
    val_buf, rew_buf, done_buf = [], [], []
    hsp_log, fwdpress_log = [], []

    # current obs per env
    cur = [e._cur_obs if hasattr(e, "_cur_obs") else e.reset() for e in envs]
    for step in range(n_steps):
        self_in = torch.tensor([c[0] for c in cur], dtype=torch.float32, device=device)
        ents = torch.tensor([c[1] for c in cur], dtype=torch.float32, device=device)
        emask = torch.tensor([c[2] for c in cur], dtype=torch.float32, device=device)
        aux = torch.zeros((N, 0), device=device)
        with torch.no_grad():
            logits, yaw_mean, value = rl(self_in, ents, emask, aux)
            dists = [torch.distributions.Categorical(logits=lg) for lg in logits]
            if deterministic:
                acts = [d.probs.argmax(dim=-1) for d in dists]
                yaw = yaw_mean
            else:
                acts = [d.sample() for d in dists]
                yaw_std = rl.yaw_log_std.exp().clamp(min=1e-2)
                yaw = yaw_mean + torch.randn_like(yaw_mean) * yaw_std
            logp = sum(d.log_prob(a) for d, a in zip(dists, acts))  # [N]
            yaw_std = rl.yaw_log_std.exp().clamp(min=1e-2)
            yaw_logp = (-0.5 * ((yaw - yaw_mean) / yaw_std) ** 2
                        - rl.yaw_log_std - 0.5 * math.log(2 * math.pi))  # [N]

        obs_buf.append(self_in); ent_buf.append(ents); em_buf.append(emask)
        for j, nm in enumerate(("fwd", "side", "up", "jump")):
            act_buf[nm].append(acts[j])
        logp_buf.append(logp); yaw_buf.append(yaw); yawlogp_buf.append(yaw_logp)
        val_buf.append(value)

        rews = torch.zeros(N, device=device)
        dones = torch.zeros(N, device=device)
        new_cur = []
        for i, e in enumerate(envs):
            msec = cur[i][3]
            obs, r, d, info = e.step(int(acts[0][i]), int(acts[1][i]), int(acts[2][i]),
                                     int(acts[3][i]), float(yaw[i]), msec)
            rews[i] = r; dones[i] = 1.0 if d else 0.0
            hsp_log.append(info["hspeed"]); fwdpress_log.append(info["fwd_press"])
            if d:
                obs = e.reset()
            new_cur.append(obs)
        cur = new_cur
        rew_buf.append(rews); done_buf.append(dones)
    # stash the carry obs for the next collection (continuation)
    for e, c in zip(envs, cur):
        e._cur_obs = c

    # bootstrap value for the last obs
    self_in = torch.tensor([c[0] for c in cur], dtype=torch.float32, device=device)
    ents = torch.tensor([c[1] for c in cur], dtype=torch.float32, device=device)
    emask = torch.tensor([c[2] for c in cur], dtype=torch.float32, device=device)
    with torch.no_grad():
        _, _, last_val = rl(self_in, ents, emask, torch.zeros((N, 0), device=device))
    return {
        "obs": obs_buf, "ent": ent_buf, "em": em_buf, "act": act_buf,
        "logp": logp_buf, "yaw": yaw_buf, "yawlogp": yawlogp_buf,
        "val": val_buf, "rew": rew_buf, "done": done_buf, "last_val": last_val,
        "hsp_log": hsp_log, "fwdpress_log": fwdpress_log,
    }


def compute_gae(rew, val, done, last_val, gamma=0.99, lam=0.95):
    """GAE-lambda advantages + returns over a [T,N] rollout. T = len(rew)."""
    T = len(rew); N = rew[0].shape[0]
    adv = [torch.zeros(N, device=rew[0].device) for _ in range(T)]
    lastgae = torch.zeros(N, device=rew[0].device)
    for t in reversed(range(T)):
        nextval = last_val if t == T - 1 else val[t + 1]
        nonterm = 1.0 - done[t]
        delta = rew[t] + gamma * nextval * nonterm - val[t]
        lastgae = delta + gamma * lam * nonterm * lastgae
        adv[t] = lastgae
    ret = [adv[t] + val[t] for t in range(T)]
    return adv, ret


def ppo_update(rl, anchor, roll, device, *, epochs=4, minibatch=4096, clip=0.2,
               vf_coef=0.5, ent_coef=0.01, kl_coef=0.05, lr=3e-4, opt=None,
               max_grad_norm=0.5):
    """PPO clipped update + value loss + entropy floor + KL-ANCHOR to the believable-aim
    reference (anchor). The KL term keeps the discrete policy near the believable warm-start
    and the yaw mean near the believable-aim mean (so speed is a CONSTRAINED objective, not
    pure speed-max -> believability holds without the fragile threshold term)."""
    T = len(roll["rew"]); N = roll["rew"][0].shape[0]
    adv, ret = compute_gae(roll["rew"], roll["val"], roll["done"], roll["last_val"])
    # flatten [T,N] -> [T*N]
    def cat(seq): return torch.cat(seq, dim=0)
    obs = cat(roll["obs"]); ent = cat(roll["ent"]); em = cat(roll["em"])
    aux = torch.zeros((obs.shape[0], 0), device=device)
    old_logp = cat(roll["logp"]); old_yaw = cat(roll["yaw"]); old_yawlogp = cat(roll["yawlogp"])
    acts = {nm: cat(roll["act"][nm]) for nm in roll["act"]}
    adv_f = cat(adv); ret_f = cat(ret)
    adv_f = (adv_f - adv_f.mean()) / (adv_f.std() + 1e-8)
    B = obs.shape[0]

    stats = {"pg": 0.0, "vf": 0.0, "ent": 0.0, "kl_anchor": 0.0, "approx_kl": 0.0, "nb": 0}
    # the policy must be in TRAIN mode for the backward pass: cuDNN refuses RNN(GRU) backward
    # in eval mode (the warm-start was loaded via _build_policy_from_checkpoint -> .eval()).
    # The frozen anchor stays in eval (its forward is under no_grad, so that's fine).
    rl.train()
    idx = np.arange(B)
    for _ep in range(epochs):
        np.random.shuffle(idx)
        for s in range(0, B, minibatch):
            mb = torch.tensor(idx[s:s + minibatch], dtype=torch.long, device=device)
            logits, yaw_mean, value = rl(obs[mb], ent[mb], em[mb], aux[mb])
            dists = [torch.distributions.Categorical(logits=lg) for lg in logits]
            head_names = ("fwd", "side", "up", "jump")
            new_logp = sum(d.log_prob(acts[nm][mb]) for d, nm in zip(dists, head_names))
            yaw_std = rl.yaw_log_std.exp().clamp(min=1e-2)
            new_yawlogp = (-0.5 * ((old_yaw[mb] - yaw_mean) / yaw_std) ** 2
                           - rl.yaw_log_std - 0.5 * math.log(2 * math.pi))
            # joint ratio (discrete heads + yaw), PPO-clipped
            ratio = torch.exp((new_logp + new_yawlogp) - (old_logp[mb] + old_yawlogp[mb]))
            a = adv_f[mb]
            pg = -torch.min(ratio * a, torch.clamp(ratio, 1 - clip, 1 + clip) * a).mean()
            vf = F.mse_loss(value, ret_f[mb])
            entropy = sum(d.entropy().mean() for d in dists)
            # KL-ANCHOR to the believable-aim reference (frozen). Discrete: KL(anchor||policy)
            # per head; yaw: squared deviation of the mean from the anchor mean (deg).
            with torch.no_grad():
                a_logits, a_yaw2 = anchor.forward_with_yaw(obs[mb], ent[mb], em[mb], aux[mb])
                a_yawmean = torch.atan2(a_yaw2[:, 0], a_yaw2[:, 1]) * (180.0 / math.pi)
            kl_disc = 0.0
            for lg, alg in zip(logits, a_logits):
                ap = F.softmax(alg, dim=-1)
                kl_disc = kl_disc + (ap * (F.log_softmax(alg, dim=-1)
                                           - F.log_softmax(lg, dim=-1))).sum(-1).mean()
            kl_yaw = ((yaw_mean - a_yawmean) ** 2).mean() / (180.0 ** 2)  # normalized
            kl_anchor = kl_disc + kl_yaw

            loss = pg + vf_coef * vf - ent_coef * entropy + kl_coef * kl_anchor
            opt.zero_grad(); loss.backward()
            nn.utils.clip_grad_norm_(rl.parameters(), max_grad_norm)
            opt.step()
            with torch.no_grad():
                stats["pg"] += float(pg); stats["vf"] += float(vf); stats["ent"] += float(entropy)
                stats["kl_anchor"] += float(kl_anchor)
                stats["approx_kl"] += float(((old_logp[mb] - new_logp)).mean())
                stats["nb"] += 1
    nb = max(stats["nb"], 1)
    return {k: (v / nb if k != "nb" else v) for k, v in stats.items()}


# =============================================================================
# Train driver
# =============================================================================
def build_segments(db, split, resource_coords_path, horizon, n_segments, map_name="dm3"):
    """Load catalog val segments (mid-route human states AT SPEED) WITH the per-tick
    hindsight goal (goal-conditioned) — the SAME loader the eval uses. These are the RL
    reset states (over-press states on-policy)."""
    coords = {}
    if resource_coords_path is not None:
        coords = RG.load_resource_coords(Path(resource_coords_path).expanduser())
    elif map_name == "dm3":
        coords = RG.load_resource_coords(RG.DEFAULT_RESOURCE_COORDS)
    episodes, _ = _load_episode_ticks(Path(db).expanduser(), split=split, resource_coords=coords)
    segs = EV.select_start_segments(episodes, horizon=horizon, n_segments=n_segments)
    return segs


def train(args, device):
    t_start = time.time()
    rl, anchor, src_ckpt, dims, head_dims = load_rl_policy(args.init_ckpt, device)
    stats = json.loads(Path(args.norm_artifact).expanduser().read_text(encoding="utf-8"))
    SC.check_norm_artifact(stats, args.map)
    world = PM.WorldModel.load(str(Path(args.bsp).expanduser()))
    # band from a DISJOINT player split (anti-Goodhart leakage; NOT the gate anchors).
    band_lo, band_hi = reward_band_disjoint(args.anchors)
    print(f"[rl] reward band (disjoint reserve players) = [{band_lo:.1f},{band_hi:.1f}] "
          f"(gate band read separately by the eval)", flush=True)

    segs = build_segments(args.db, args.split, args.resource_coords, args.horizon,
                          args.n_reset_segments, args.map)
    print(f"[rl] {len(segs)} reset segments (mid-route human states at speed, goal-conditioned)",
          flush=True)
    if not segs:
        raise SystemExit("[rl] NO reset segments — check db/split")

    envs = [PmoveEnv(world, stats, segs, n_max=args.n_max, map_name=args.map,
                     horizon=args.ep_horizon, band_lo=band_lo, band_hi=band_hi, seed=1000 + i)
            for i in range(args.n_envs)]
    opt = torch.optim.Adam(rl.parameters(), lr=args.lr)

    steps_per_iter = args.n_envs * args.rollout_steps
    n_iters = max(1, args.steps // steps_per_iter)
    print(f"[rl] {args.n_envs} envs x {args.rollout_steps} steps = {steps_per_iter}/iter; "
          f"{n_iters} iters -> ~{n_iters*steps_per_iter} env steps target", flush=True)

    env_steps = 0
    for it in range(n_iters):
        t0 = time.time()
        roll = collect_rollout(envs, rl, device, args.rollout_steps)
        env_steps += steps_per_iter
        upd = ppo_update(rl, anchor, roll, device, epochs=args.ppo_epochs,
                         minibatch=args.minibatch, clip=args.clip, vf_coef=args.vf_coef,
                         ent_coef=args.ent_coef, kl_coef=args.kl_coef, opt=opt)
        mean_hsp = float(np.mean(roll["hsp_log"])) if roll["hsp_log"] else 0.0
        fwd_press = float(np.mean(roll["fwdpress_log"])) if roll["fwdpress_log"] else 0.0
        dt = time.time() - t0
        sps = steps_per_iter / dt if dt > 0 else 0.0
        print(f"[it {it:03d}] env_steps={env_steps} mean_hspeed={mean_hsp:6.1f} "
              f"fwd_press={fwd_press:.3f} pg={upd['pg']:+.4f} vf={upd['vf']:.4f} "
              f"ent={upd['ent']:.3f} kl_anchor={upd['kl_anchor']:.4f} "
              f"approx_kl={upd['approx_kl']:+.4f} yaw_std={float(rl.yaw_log_std.exp()):.2f} "
              f"({sps:,.0f} env-steps/s, {dt:.1f}s)", flush=True)
        # KL guard: if the policy is drifting hard from the anchor, the run is leaving the
        # human manifold -> report (the orchestrator's guard catches it in eval too).
        if upd["approx_kl"] > args.target_kl * 4:
            print(f"[rl] WARN approx_kl {upd['approx_kl']:.3f} >> target {args.target_kl} "
                  f"(policy moving fast; conservative LR/clip should bound it)", flush=True)

    meta = {
        "init_ckpt": str(Path(args.init_ckpt).resolve()),
        "env_steps": env_steps, "n_iters": n_iters, "n_envs": args.n_envs,
        "rollout_steps": args.rollout_steps, "ppo_epochs": args.ppo_epochs,
        "lr": args.lr, "clip": args.clip, "kl_coef": args.kl_coef,
        "ent_coef": args.ent_coef, "reward_band": [band_lo, band_hi],
        "wall_time_s": round(time.time() - t_start, 1),
        "final_mean_hspeed": mean_hsp, "final_fwd_press": fwd_press,
    }
    save_rl_ckpt(args.out_ckpt, rl, src_ckpt, dims, head_dims, args.round, meta)
    print(json.dumps({"saved": str(Path(args.out_ckpt).resolve()), "rl_meta": meta}, indent=2),
          flush=True)
    return meta


def eval_metric_vector(args, device):
    """Run the GOAL-CONDITIONED hold-guard eval on --init-ckpt with SELF-YAW (aim='policy')
    and return the METRIC VECTOR (M1-M6 + the 2 guards), every number from raw.

      M1 closedloop G-MV4 avg hspeed   (band 252-316)   from eval_broad_closedloop
      M2 closedloop G-MV4 p95 hspeed   (band 462-560)
      M3 over-press relief = max(0, 0.50 - fwd_press_air)  (human band top 0.50)
      M4 hard-route route% mean (mega/sng/ra)            from eval_broad_dryroute
      M5 hard-route speed% mean
      M6 G-MV3 cadence in-band margin
      GUARD launch_11_11 (unseeded dryroute pass count), G-MV1 believable (closedloop)

    The eval uses aim_mode='policy' = the policy's OWN per-tick yaw delta (the RL self-yaw),
    so the gates measure the policy AS IT ACTUALLY BEHAVES. Goal-conditioned (PR #355)."""
    import eval_broad_dryroute as DR
    rc = args.resource_coords
    # --- closed-loop (M1/M2/M3/M6 + G-MV1 guard) — goal-conditioned, self-yaw ----------
    rep = EV.run_eval(
        Path(args.init_ckpt), Path(args.bsp), Path(args.db), Path(args.norm_artifact),
        split=args.split, horizon=args.ep_horizon, n_segments=args.eval_segments,
        anchors=Path(args.anchors), player_band=None, map_name=args.map,  # None = pool envelope
        n_max=args.n_max, cpu=(device == "cpu"),
        goal_mode="conditioned", resource_coords_path=(Path(rc) if rc else None),
        aim_mode="policy",
    )
    bp = rep["bot_policy"]
    g = bp["gmv"]["gates"]
    mv4 = g.get("G-MV4", {}).get("statistic", {})
    mv3 = g.get("G-MV3", {}).get("statistic", {})
    m1 = mv4.get("avg_hspeed_qu_per_s")
    m2 = mv4.get("p95_hspeed_qu_per_s")
    fwd_press = bp.get("fwd_press_frac")
    m3 = (max(0.0, 0.50 - fwd_press) if fwd_press is not None else None)
    cad = mv3.get("flips_per_min")
    # M6 = in-band margin (dist to nearer edge; +inside): use the gate's own margin if present
    cad_margin = g.get("G-MV3", {}).get("margin", {}).get("flips_per_min_to_nearer_edge")
    believable = bp.get("gmv_summary", {}).get("believable_G_MV1")

    # --- dryroute (M4/M5 hard routes + 11/11 launch guard) — goal-conditioned, self-yaw --
    hard = ["mega_to_rl", "sng_to_rl", "ra_jumps"]
    launch_set = args.launch_routes.split(",") if args.launch_routes else hard
    route_pcts, speed_pcts, launch_pass = [], [], 0
    per_route = {}
    for route in launch_set:
        try:
            drep = DR.run_eval(
                Path(args.init_ckpt), Path(args.bsp), route,
                norm_artifact=Path(args.norm_artifact), map_name=args.map, n_max=args.n_max,
                cpu=(device == "cpu"), aim_mode="policy", jump_mode="policy",
                goal_mode="conditioned",
                resource_coords_path=(Path(rc) if rc else None),
            )
            dbp = drep["bot_policy"]
            rp = dbp.get("route_pct"); sp = dbp.get("speed_pct"); pa = dbp.get("passed")
            per_route[route] = {"route_pct": rp, "speed_pct": sp, "passed": pa}
            if route in hard:
                if rp is not None:
                    route_pcts.append(rp)
                if sp is not None:
                    speed_pcts.append(sp)
            if pa:
                launch_pass += 1
        except Exception as e:  # a single route failing must not sink the vector
            per_route[route] = {"error": str(e)[:200]}
    m4 = float(np.mean(route_pcts)) if route_pcts else None
    m5 = float(np.mean(speed_pcts)) if speed_pcts else None

    return {
        "M1_gmv4_avg_hspeed": m1, "M2_gmv4_p95_hspeed": m2,
        "M3_overpress_relief": m3, "M3_fwd_press_air": fwd_press,
        "M4_hard_route_pct_mean": m4, "M5_hard_speed_pct_mean": m5,
        "M6_cadence_flips_per_min": cad, "M6_cadence_inband_margin": cad_margin,
        "GUARD_launch_pass": launch_pass, "GUARD_launch_total": len(launch_set),
        "GUARD_gmv1_believable": believable,
        "aim_mode": "policy", "goal_mode": "conditioned",
        "per_route": per_route,
        "ckpt": str(Path(args.init_ckpt).resolve()),
        "bands": {"gmv4_avg": [252.279, 315.632], "gmv4_p95": [461.538, 560.008],
                  "fwd_press_human_top": 0.50},
    }


def reward_band_disjoint(anchors_path):
    """Reward band = pooled avg-speed envelope of a DISJOINT RESERVE player split (NOT the
    gate's anchors; reward_dryrun LEAKAGE SPLIT, anti-Goodhart). Falls back to the full
    pool if the reserve players aren't present."""
    anchors = json.loads(Path(anchors_path).expanduser().read_text())
    per = anchors["metrics"]["movement"]["fields"]["avg_horizontal_speed_qu_per_s"]["per_player"]
    reserve = ["Milton", "reppie", "yeti", "bps"]
    vals = []
    for p in reserve:
        if p in per:
            vals.extend(per[p]["values"])
    if not vals:  # fallback: full pool
        for p, d in per.items():
            vals.extend(d["values"])
    return float(min(vals)), float(max(vals))


def main(argv=None):
    ap = argparse.ArgumentParser(description="PPO-on-speed RL loop (movement-v5)")
    ap.add_argument("--init-ckpt", required=True,
                    help="warm-start (rl_warmstart_v5_yaw.pt) OR a prior RL round ckpt")
    ap.add_argument("--out-ckpt", help="output ckpt (required unless --eval)")
    ap.add_argument("--steps", type=int, default=200000, help="target env steps to train")
    ap.add_argument("--eval", action="store_true",
                    help="EVAL ONLY: run the goal-conditioned hold-guard eval on --init-ckpt")
    ap.add_argument("--round", type=int, default=1)
    # data
    ap.add_argument("--db", required=True)
    ap.add_argument("--bsp", required=True)
    ap.add_argument("--norm-artifact", required=True)
    ap.add_argument("--anchors", required=True)
    ap.add_argument("--resource-coords", default=None)
    ap.add_argument("--split", default="val")
    ap.add_argument("--map", default="dm3")
    ap.add_argument("--n-max", type=int, default=7)
    # env / rollout
    ap.add_argument("--n-envs", type=int, default=12)
    ap.add_argument("--rollout-steps", type=int, default=256)
    ap.add_argument("--ep-horizon", type=int, default=385)
    ap.add_argument("--horizon", type=int, default=385, help="segment-load horizon")
    ap.add_argument("--n-reset-segments", type=int, default=64,
                    help="how many human val segments to sample resets from")
    # ppo
    ap.add_argument("--ppo-epochs", type=int, default=4)
    ap.add_argument("--minibatch", type=int, default=2048)
    ap.add_argument("--clip", type=float, default=0.2)
    ap.add_argument("--vf-coef", type=float, default=0.5)
    ap.add_argument("--ent-coef", type=float, default=0.01)
    ap.add_argument("--kl-coef", type=float, default=0.05)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--target-kl", type=float, default=0.03)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--cpu", action="store_true")
    # eval
    ap.add_argument("--metric-out", default=None, help="write the metric-vector JSON here")
    ap.add_argument("--eval-segments", type=int, default=12,
                    help="closed-loop eval segments (n_segments)")
    ap.add_argument("--launch-routes", default=None,
                    help="comma routes for the dryroute eval + 11/11 launch guard "
                         "(default = the 3 hard routes)")
    args = ap.parse_args(argv)

    torch.manual_seed(args.seed); np.random.seed(args.seed)
    device = "cpu" if args.cpu else ("cuda" if torch.cuda.is_available() else "cpu")
    print(f"[rl] device={device} torch={torch.__version__}", flush=True)

    if args.eval:
        vec = eval_metric_vector(args, device)
        print("METRIC_VECTOR " + json.dumps(vec), flush=True)
        if args.metric_out:
            Path(args.metric_out).expanduser().write_text(json.dumps(vec, indent=2))
        return 0
    if not args.out_ckpt:
        raise SystemExit("[rl] --out-ckpt required for training")
    train(args, device)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
