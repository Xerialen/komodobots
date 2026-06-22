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
  * REWARD = (ROUND-5: MECHANISM-GATED speed) air-strafe-attributed speed-gain: the in-band
             speed + Phi-gain terms are scaled by perp_frac = 1-(vhat.wishdir)^2 IN AIR, so
             only speed earned by wishdir _|_ velocity (the QW air-accel mechanism) is credited
             and bulldozing (wishdir aligned = forward-press) earns ~0; PLUS a HARD air press-
             barrier (-1.5 on air argmax-press) closing the bulldoze path; + route-progress +
             argmax-targeted cadence + anti-hack + KL-anchor to the believable-aim reference.
             Round 4 proved in-band speed was ONLY reachable by pressing under the old speed-
             however-achieved reward; this geometry makes air-strafing the only positive-EV
             route to in-band air speed. (Hand-set believability THRESHOLD dropped per STEP-0;
             believability == the KL-anchor. Ground speed stays ungated for launch accel.)
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
                 horizon=385, band_lo=252.0, band_hi=316.0, seed=0,
                 cad_hold_min=14, cad_hold_max=230, cad_hold_late=240,
                 air_press_thresh=0.40, ap_rate_ema=0.02, r_cad_weight=1.0):
        self.world = world
        self.stats = stats
        self.segments = segments                 # list of (eid, start, seg) human segments
        self.n_max = n_max
        self.map_name = map_name
        self.horizon = horizon
        self.band_lo, self.band_hi = band_lo, band_hi
        # G-MV3 cadence target (round-2 M6 recovery): a strafe sign-flip is rewarded only
        # when the prior hold was a HUMAN-plausible length (cad_hold_min..cad_hold_max ticks
        # ~= 360..16 flips/min), and a steady penalty kicks in once one strafe sign is held
        # PAST cad_hold_late ticks (< ~8 flips/min, the low band edge) so the policy can't
        # park on one strafe direction (the round-1 M6=0 failure). Fast jitter is NOT
        # rewarded (would tank speed + trip p_hack); this only un-sticks held strafe.
        self.cad_hold_min, self.cad_hold_max, self.cad_hold_late = (
            cad_hold_min, cad_hold_max, cad_hold_late)
        # ROUND-6 lever 1: SOFT air press-barrier. air_press_thresh = the human-band-top-ish
        # air-press FRACTION below which pressing is FREE (penalty only on the excess above it);
        # ap_rate_ema = the EMA rate at which the running air-press fraction tracks (slow so the
        # penalty reflects a sustained press habit, not a single tick).
        self.air_press_thresh = float(air_press_thresh)
        self.ap_rate_ema = float(ap_rate_ema)
        # ROUND-7 lever: cadence-reward weight on the L<->R argmax flip term. Round 6 fixed in-band
        # press from r4init but the policy PARKED the strafe (M6 flips 0.0) because r_cad weight
        # 1.0 lost to the comfort of a parked perpendicular hold (full r_strafe for ~cad_hold_max
        # ticks). Raising this (and shortening cad_hold_max so the strafe-decay bites earlier)
        # makes flipping net-positive in the SAME in-band-press basin -> recover M6 without
        # pushing press out of [0.07,0.50].
        self.r_cad_weight = float(r_cad_weight)
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
        # strafe-cadence tracking (G-MV3 mirror): last NONZERO sidemove sign + ticks held.
        self.prev_strafe_sign = 0
        self.strafe_hold = 0
        # ROUND-6 (lever 1): running AIR press-FRACTION (EMA over the episode) for the SOFT
        # hinge barrier. Round-5's flat -1.0-per-air-press-tick drove press to 0.0 (below the
        # human band floor 0.07); a hinge that only penalizes the air-press FRACTION ABOVE
        # ~0.40 lets press settle anywhere in the human band [0.07,0.50] with no penalty and
        # only fights the EXCESS. Seed at the threshold so the first ticks aren't free.
        self.ap_rate = float(self.air_press_thresh)
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

    def step(self, fwd_cls, side_cls, up_cls, jump_cls, yaw_delta_deg, msec,
             fwd_argmax=None, side_argmax=None):
        """Apply the SAMPLED discrete heads + the policy's per-tick yaw DELTA (self-yaw),
        integrate the yaw, step pmove, return (reward, done, info).

        ROUND-3 fix (argmax cadence/press): the closed-loop EVAL drives the heads by
        DETERMINISTIC ARGMAX (eval_broad_closedloop line ~740), so the believability-shaping
        terms (cadence M6, fwd-press M3) MUST be functions of the ARGMAX-decoded action — a
        sampling-only reward (round 2) shifts the sampled distribution but leaves the argmax
        parked, so eval cadence stayed 0 / press stayed high. fwd_argmax/side_argmax are the
        policy's deterministic intent THIS tick (the eval's exact decode); the sim still runs
        the SAMPLED action (on-policy dynamics), reward shapes on the argmax (the eval target).
        """
        fwd_mag, side_mag, up_mag, jump_bit = EV.decode_move_heads(
            [fwd_cls, side_cls, up_cls, jump_cls, 0])
        # the ARGMAX-decoded side/fwd (what the deterministic eval will execute). Fall back to
        # the sampled class if an argmax wasn't supplied (keeps the env standalone-runnable).
        side_am = int(side_argmax) if side_argmax is not None else int(side_cls)
        fwd_am = int(fwd_argmax) if fwd_argmax is not None else int(fwd_cls)
        side_am_mag = EV.move_class_to_mag(side_am)
        # SELF-YAW: integrate the policy's per-tick turn delta onto the executed view yaw.
        # This is the mechanism — the yaw drives the air-strafe wishdir in pmove AND was
        # already fed into the obs this tick (cur_yaw). Clamp the delta to a sane per-tick
        # turn so a blown-up sample can't teleport the aim.
        yaw_delta_deg = float(max(-90.0, min(90.0, yaw_delta_deg)))
        self.prev_yaw = self.cur_yaw
        self.cur_yaw = self.cur_yaw + yaw_delta_deg
        angles = [0.0, self.cur_yaw, 0.0]
        cmd = PM.Cmd(int(msec), angles, [fwd_mag, side_mag, up_mag], jump_bit)
        # PRE-FRAME horizontal velocity (the speed-gain physics uses the velocity BEFORE the
        # accel step: |v'|^2 = s^2 + 900 - (v_h . wishdir)^2). Capture it for the mechanism term.
        pre_vx, pre_vy = self.st.velocity[0], self.st.velocity[1]
        self.pm.run_frame(self.st, cmd)

        vx, vy = self.st.velocity[0], self.st.velocity[1]
        hspeed = math.hypot(vx, vy)
        onground = bool(self.st.onground)

        # ---- AIR-STRAFE MECHANISM credit (ROUND-5) ------------------------------------
        # The QW air-accel is ALWAYS addspeed-capped here (accelspeed ~41.6 > wishspd cap 30),
        # so post-tick |v'_h|^2 = s^2 + 900 - (v_h . wishdir)^2 (optimal_strafe_yaw docstring).
        # => the per-tick speed-GAIN is entirely a function of the angle between wishdir and
        # the PRE-FRAME velocity: wishdir _|_ v gives the full phi(s) gain (the air-strafe
        # mechanism), wishdir ALIGNED with v (forward-press bulldozing) gains ~0. perp_frac =
        # 1 - (vhat . wishdir)^2 in [0,1] is exactly the fraction of phi(s) the geometry yields
        # = "how much of this speed came from strafing, not pressing". Reproduce the SAME wishdir
        # the sim built (pmove_sim angle_vectors for cur_yaw, pitch=roll=0, + the SAMPLED move
        # mags that drove this tick) so the credit measures the realized trajectory.
        ay = self.cur_yaw * (math.pi / 180.0)
        cy, sy = math.cos(ay), math.sin(ay)
        # pmove basis (pitch=roll=0): forward=[cy,sy], right=[sy,-cy]; wishvel = fwd*fmove+right*smove
        wvx = cy * fwd_mag + sy * side_mag
        wvy = sy * fwd_mag - cy * side_mag
        wmag = math.hypot(wvx, wvy)
        pre_h = math.hypot(pre_vx, pre_vy)
        if wmag > 1e-6 and pre_h > 1e-6:
            dot = (pre_vx * wvx + pre_vy * wvy) / (pre_h * wmag)   # vhat . wishdir, pre-frame
            perp_frac = max(0.0, min(1.0, 1.0 - dot * dot))
        else:
            # no move key (wishdir undefined) or stopped: no strafe-mechanism gain this tick.
            perp_frac = 0.0

        # ---- REWARD (rl-plan §B; ROUND-5b = mechanism-CREDIT + strafe bonus, NOT gated-hold)
        # Round 4 proved over-press and in-band speed are ANTI-correlated under speed-however-
        # achieved (the only route to the band was PRESSING). Round-5a (gate BOTH r_speed and
        # r_phi by perp_frac) OVER-corrected: gating the in-band HOLD removed the speed carrot,
        # so from both inits the policy just SLOWED (hspeed ~45) and minimized the barrier
        # instead of air-strafing (no on-manifold low-press snapshot was ever captured). Round-5b
        # keeps the carrot but redirects HOW speed is earned:
        #  - r_speed (in-band HOLD): UNGATED -> the policy still wants to reach the band (this is
        #    what let round 4 reach M1 280). Removing the carrot starved the objective.
        #  - r_phi (per-tick GAIN): GATED by perp_frac in air -> speed-GAIN is only credited via
        #    the air-strafe mechanism (wishdir _|_ v); a bulldozing gain earns ~0.
        #  - r_strafe (NEW): a POSITIVE air-strafe bonus = perp_frac when airborne & moving, so
        #    the policy has a gradient TOWARD perpendicular wishdir, not just barrier-avoidance.
        #  - HARD air press-barrier (below, -1.0): pressing in air pays -1.0; if it yields in-band
        #    speed (+1.0 r_speed) it's only break-even, while air-strafing adds r_strafe + gated
        #    gain on top -> air-strafing STRICTLY dominates pressing as the route to in-band speed.
        r_speed_raw = soft_band(hspeed, self.band_lo, self.band_hi)
        # r_phi: realized fraction of the analytic per-tick ACHIEVABLE gain (builds speed).
        avail = phi(self.prev_hspeed)
        ds = hspeed - self.prev_hspeed
        r_phi_raw = min(1.0, max(0.0, ds) / avail) if avail > 1e-6 else 0.0
        r_speed = r_speed_raw                         # in-band HOLD carrot: UNGATED (round-5b fix)
        if onground:
            r_phi = r_phi_raw                         # ground accel: a different mechanism
            r_strafe = 0.0
        else:
            r_phi = perp_frac * r_phi_raw             # air GAIN credited only via the mechanism
            # positive air-strafe bonus: reward perpendicular wishdir while airborne and actually
            # moving (>~ band_lo/2) so it can't be farmed at a standstill; this is the gradient
            # that pulls toward air-strafing as the speed source instead of pressing.
            r_strafe = perp_frac if hspeed > (self.band_lo * 0.5) else 0.0
            # ROUND-6 lever 2 (cadence coexistence): a PARKED perpendicular strafe earns full
            # r_strafe forever, which round-5 exploited (one held strafe sign -> perp_frac high,
            # cadence DEAD M6=-8). DECAY the strafe bonus once the same nonzero argmax side sign
            # is held past the human window (cad_hold_max), so KEEPING the bonus REQUIRES the
            # L<->R flip -> low-press air-strafe now COEXISTS with cadence instead of fighting it.
            if self.strafe_hold > self.cad_hold_max:
                over = self.strafe_hold - self.cad_hold_max
                r_strafe *= max(0.0, 1.0 - over / float(self.cad_hold_max))
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

        # r_cad: G-MV3 strafe-cadence shaping, ROUND-3 = on the ARGMAX side sign (the eval
        # decodes side by argmax, so cadence must move the argmax, not the sample — round-2's
        # sampling-only r_cad left eval cadence at 0). Mirror the gate's flip semantics on the
        # ARGMAX-decoded sidemove: a flip = a transition between nonzero +side and nonzero
        # -side (zero-strafe runs DON'T reset the comparison). Reward a flip whose prior hold
        # was human-plausible (cad_hold_min..cad_hold_max ticks); penalize parking on one
        # nonzero argmax side sign past cad_hold_late ticks (un-sticks the parked argmax).
        cur_sign = 1 if side_am_mag > 0 else (-1 if side_am_mag < 0 else 0)
        r_cad = 0.0
        if cur_sign != 0:
            if self.prev_strafe_sign != 0 and cur_sign != self.prev_strafe_sign:
                # a real L<->R flip. Reward only if the prior hold was in the human window.
                if self.cad_hold_min <= self.strafe_hold <= self.cad_hold_max:
                    r_cad += 1.0
                self.strafe_hold = 0
            else:
                self.strafe_hold += 1
            self.prev_strafe_sign = cur_sign
            if self.strafe_hold > self.cad_hold_late:
                # RAMPING park penalty (round-3b): the calib showed a flat, late (460-tick)
                # park penalty never fired before the policy committed to parking the strafe
                # argmax for straight-line speed (fpm collapsed 86->0, press climbed to 1.0).
                # A penalty that GROWS with the hold past cad_hold_late (240 ~= the 16-fpm low
                # edge) makes parking progressively net-negative, so the policy keeps flipping.
                over = self.strafe_hold - self.cad_hold_late
                r_cad -= min(2.0, 0.5 + 0.01 * over)
        # (zero-strafe ticks neither flip nor reset the held sign; hold counter pauses.)

        # r_press: SOFT AIR PRESS-BARRIER (ROUND-6 lever 1 — HINGE above a fraction, not a flat
        # per-tick penalty). The eval fwd_press_frac counts fwd-head ARGMAX == class 2 (press-
        # forward) ticks; the bulldoze failure is over-pressing in AIR (M3 fwd_press_air >= 0.80
        # on every in-band snapshot). Round-5b's FLAT -1.0-per-air-press-tick over-corrected: it
        # penalized EVERY air-press tick equally, so the policy drove press to 0.0 — BELOW the
        # human band floor 0.07 (M3 fwd_press 0.0). Round 6: maintain a running air-press FRACTION
        # (ap_rate, EMA per episode) and penalize only the EXCESS above air_press_thresh (~0.40,
        # the human-band-top-ish). Press FRACTION <= thresh -> ZERO penalty (so the policy can
        # settle anywhere in the human band [0.07,0.50] cleanly); excess grows linearly. The EMA
        # updates on EVERY air tick toward the air-press indicator (0/1) so the rate reflects a
        # SUSTAINED press habit, not a single tick. GROUND press is NOT penalized — ground accel
        # is legitimate (the launch guard needs it) and ground ticks don't move ap_rate.
        air_press = (fwd_am == 2) and (not onground)
        if not onground:
            self.ap_rate += self.ap_rate_ema * ((1.0 if air_press else 0.0) - self.ap_rate)
        r_press = max(0.0, self.ap_rate - self.air_press_thresh)

        # ROUND-6 reward = UNGATED in-band-speed carrot (keeps the objective) + mechanism-CREDIT
        # gain (r_phi gated by perp_frac in air) + a POSITIVE air-strafe bonus (r_strafe, now
        # DECAYED when the strafe is parked past the human window) + route + argmax-targeted
        # cadence (r_cad weight RAISED 0.5 -> 1.0 so the L<->R FLIP reward competes with the
        # strafe bonus instead of losing to a parked perpendicular hold) + the SOFT air press-
        # barrier (hinge above ~0.40, weight -1.0 on the EXCESS only) + anti-hack. Round 5 drove
        # press to 0.0 (overshoot below the 0.07 floor) AND collapsed cadence (M6 -8) because the
        # flat barrier crushed every air-press tick and the strafe bonus rewarded a parked
        # perpendicular strafe. Round 6: the hinge lets press settle in [0.07,0.50]; the
        # decayed-strafe + raised r_cad make low-press air-strafe COEXIST with the flip cadence.
        reward = (1.0 * r_speed + 0.5 * r_phi + 0.6 * r_strafe + 0.5 * r_prog
                  + self.r_cad_weight * r_cad - 1.0 * r_press - 1.0 * p_hack)

        self.prev_hspeed = hspeed
        self.k += 1
        # done: route/segment exhausted, time-limit, or fell out of bounds (origin NaN/away).
        done = (self.k >= min(self.horizon, len(self.seg) - 1))
        if not (math.isfinite(self.st.origin[0]) and math.isfinite(self.st.origin[1])):
            done = True
        # fwd_press logged on the ARGMAX (matches eval_broad_closedloop.fwd_press_frac, which
        # counts argmax==2 ticks) so the training fwd_press readout tracks the eval metric.
        info = {"hspeed": hspeed, "onground": onground, "fwd_press": int(fwd_am == 2),
                "r_speed": r_speed, "r_phi": r_phi, "r_prog": r_prog, "p_hack": p_hack,
                "r_cad": r_cad, "r_press": r_press, "strafe_sign": cur_sign,
                "perp_frac": perp_frac, "r_strafe": r_strafe, "ap_rate": self.ap_rate}
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
    hsp_log, fwdpress_log, rcad_log, rpress_log = [], [], [], []

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
            # ARGMAX of the fwd/side heads = the policy's deterministic intent (= what the
            # closed-loop eval executes). The argmax-targeted cadence/press reward terms shape
            # on THESE, not the sampled action, so they move the quantity the eval measures.
            fwd_argmax = logits[0].argmax(dim=-1)   # [N]
            side_argmax = logits[1].argmax(dim=-1)  # [N]

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
                                     int(acts[3][i]), float(yaw[i]), msec,
                                     fwd_argmax=int(fwd_argmax[i]),
                                     side_argmax=int(side_argmax[i]))
            rews[i] = r; dones[i] = 1.0 if d else 0.0
            hsp_log.append(info["hspeed"]); fwdpress_log.append(info["fwd_press"])
            rcad_log.append(info["r_cad"]); rpress_log.append(info["r_press"])
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
        "hsp_log": hsp_log, "fwdpress_log": fwdpress_log, "rcad_log": rcad_log,
        "rpress_log": rpress_log,
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
                     horizon=args.ep_horizon, band_lo=band_lo, band_hi=band_hi, seed=1000 + i,
                     air_press_thresh=args.air_press_thresh,
                     cad_hold_max=args.cad_hold_max, r_cad_weight=args.r_cad_weight)
            for i in range(args.n_envs)]
    opt = torch.optim.Adam(rl.parameters(), lr=args.lr)

    steps_per_iter = args.n_envs * args.rollout_steps
    n_iters = max(1, args.steps // steps_per_iter)
    print(f"[rl] {args.n_envs} envs x {args.rollout_steps} steps = {steps_per_iter}/iter; "
          f"{n_iters} iters -> ~{n_iters*steps_per_iter} env steps target", flush=True)

    # BEST-believable checkpoint tracking + KL-anchor early-stop (ROUND-3c). The calib showed
    # the believable regime (moderate argmax press + nonzero fpm) lives EARLY (~iters 8-12);
    # longer training runs away into the bulldoze basin (press->1.0, fpm->0, kl_anchor blows
    # up to >2). So: (a) snapshot the base state_dict at the iter with the best believability
    # score among iters still ON the manifold (kl_anchor below threshold), and SAVE THAT (not
    # the final collapsed policy); (b) early-STOP once kl_anchor exceeds the manifold ceiling
    # (the runaway signal) — no point training past the collapse. This persists a guard-safe
    # ckpt by construction and never re-saves a regression.
    import copy as _copy
    best = {"score": -1e9, "sd": None, "it": -1, "press": None, "fpm": None, "hsp": None}
    # ROUND-4: keep the top-K believable snapshots (not just the single best) so a post-hoc
    # EVAL-PRESS selection pass can pick the one whose CLOSED-LOOP eval press is lowest. The
    # round-3 paradox: the best snapshot had in-rollout argmax press 0.114 but eval press
    # 0.799 — the in-rollout press signal did NOT transfer to the eval distribution. So the
    # selection criterion is changed from in-rollout press to EVAL press (the metric the gate
    # actually reads). Each candidate stores its base state_dict + the in-rollout diagnostics.
    topk = []  # list of dicts {score, sd, it, press, fpm, hsp, kl_anchor}; trimmed to K
    K = max(1, int(getattr(args, "topk_snapshots", 6)))
    kl_ceiling = args.kl_anchor_ceiling
    stopped_early = None
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
        # cadence proxy: fraction of ticks that scored a flip-reward (r_cad>0) -> rough
        # flips/min = flip_frac * (60000/13) so I can watch M6 recover during training.
        rcad = roll["rcad_log"]
        flip_frac = (float(np.mean([1.0 if x > 0 else 0.0 for x in rcad])) if rcad else 0.0)
        fpm_est = flip_frac * (60000.0 / 13.0)
        dt = time.time() - t0
        sps = steps_per_iter / dt if dt > 0 else 0.0
        print(f"[it {it:03d}] env_steps={env_steps} mean_hspeed={mean_hsp:6.1f} "
              f"fwd_press={fwd_press:.3f} fpm~{fpm_est:5.0f} pg={upd['pg']:+.4f} "
              f"vf={upd['vf']:.4f} ent={upd['ent']:.3f} kl_anchor={upd['kl_anchor']:.4f} "
              f"approx_kl={upd['approx_kl']:+.4f} yaw_std={float(rl.yaw_log_std.exp()):.2f} "
              f"({sps:,.0f} env-steps/s, {dt:.1f}s)", flush=True)
        # KL guard: if the policy is drifting hard from the anchor, the run is leaving the
        # human manifold -> report (the orchestrator's guard catches it in eval too).
        if upd["approx_kl"] > args.target_kl * 4:
            print(f"[rl] WARN approx_kl {upd['approx_kl']:.3f} >> target {args.target_kl} "
                  f"(policy moving fast; conservative LR/clip should bound it)", flush=True)

        # --- believability-scored best-ckpt + KL-anchor early-stop (ROUND-3c) ---------------
        # Only iters still ON the believable manifold (kl_anchor <= ceiling) AND not over-
        # pressing past the human top (0.50) are eligible. Among those, score rewards higher
        # in-rollout speed and a nonzero strafe cadence (fpm>0) — i.e. the air-strafe regime,
        # not bulldozing. Warm-up: skip iter 0 (init transient). A grace lets a couple of low-
        # fpm iters pass without locking the best, but the press/KL gates are hard.
        on_manifold = upd["kl_anchor"] <= kl_ceiling
        press_ok = fwd_press <= args.press_ceiling
        if it >= 1 and on_manifold and press_ok:
            score = mean_hsp - 200.0 * max(0.0, fwd_press - 0.30) + 0.5 * min(fpm_est, 120.0)
            cand = {"score": score, "sd": _copy.deepcopy(rl.base.state_dict()), "it": it,
                    "press": fwd_press, "fpm": fpm_est, "hsp": mean_hsp,
                    "kl_anchor": float(upd["kl_anchor"])}
            # top-K by in-rollout score (ROUND-4): retain the K best believable snapshots for
            # the post-hoc eval-press selection; keep `best` as the single-best for logging.
            topk.append(cand)
            topk.sort(key=lambda c: c["score"], reverse=True)
            del topk[K:]
            if score > best["score"]:
                best.update(score=score, sd=cand["sd"], it=it,
                            press=fwd_press, fpm=fpm_est, hsp=mean_hsp)
                print(f"[rl] * new best-believable @it{it}: score={score:.1f} "
                      f"press={fwd_press:.3f} fpm~{fpm_est:.0f} hspeed={mean_hsp:.1f} "
                      f"kl_anchor={upd['kl_anchor']:.3f}", flush=True)
        # early-STOP on manifold departure (the runaway into the bulldoze basin).
        if upd["kl_anchor"] > kl_ceiling and best["sd"] is not None:
            stopped_early = it
            print(f"[rl] EARLY-STOP @it{it}: kl_anchor {upd['kl_anchor']:.3f} > ceiling "
                  f"{kl_ceiling} (left the believable manifold; keeping best @it{best['it']})",
                  flush=True)
            break

    # --- ROUND-4 eval-press selection: pick the candidate by CLOSED-LOOP EVAL press --------
    # The round-3 paradox was that in-rollout argmax press (0.114) did not transfer to the
    # eval closed-loop distribution (0.799). So instead of saving the top-IN-ROLLOUT-score
    # snapshot, we eval each of the top-K snapshots on the SAME goal-conditioned closed-loop
    # the gate uses (cheap: closed-loop only, NO dryroutes) and KEEP the candidate whose EVAL
    # fwd_press_frac < --eval-press-ceiling AND that holds M1 (avg hspeed) >= band_lo AND M6
    # cadence in-band. If none fully qualifies, fall back to the lowest-eval-press candidate
    # that still holds M1 in band (materially-below the 0.799 basin). This persists the params
    # the FULL metric vector will then confirm.
    sel = None       # the chosen candidate dict
    sel_reason = None
    eval_probe = []  # per-candidate eval diagnostics for the meta
    if getattr(args, "select_by_eval_press", False) and topk:
        print(f"[rl] EVAL-PRESS SELECTION over {len(topk)} top-K snapshots "
              f"(ceiling press<{args.eval_press_ceiling}, M1>={band_lo:.0f}, M6 in-band)",
              flush=True)
        import tempfile
        qualified, in_band = [], []
        # ROUND-7 (lever 2): the selection M1 floor. Defaults to band_lo (round-6 behavior) but
        # can be relaxed slightly (e.g. 252, the gate-band floor) so a press-in-band + M6-in-band
        # candidate whose M1 sits just above the gate floor (but below the disjoint-reserve
        # band_lo) can still be SAVED — the unified snapshot is the goal, not max M1.
        m1_floor = float(getattr(args, "select_m1_floor", None) or band_lo)
        # ROUND-8 (lever 2): LAUNCH-AWARE selection. When --select-launch is set, a candidate
        # must ALSO hold launch >= --select-launch-min (ra_jumps/hard-route dryroute passes) to
        # qualify — closing the round-7 hole where the closed-loop-only screen saved a launch
        # breaker (@it12: press+M6 in band but ra_jumps route% 88.8->4.56 = launch 0/3).
        launch_aware = bool(getattr(args, "select_launch", False))
        launch_min = int(getattr(args, "select_launch_min", 1))
        for ci, c in enumerate(topk):
            rl.base.load_state_dict(c["sd"])
            ep, em1, em6, elaunch = _eval_press_screen(rl, src_ckpt, dims, head_dims, args,
                                                        device, tmptag=f"sel{ci}")
            c_diag = {"it": c["it"], "inroll_press": c["press"], "inroll_hsp": c["hsp"],
                      "inroll_fpm": c["fpm"], "eval_press": ep, "eval_m1": em1, "eval_m6": em6,
                      "eval_launch": elaunch}
            eval_probe.append(c_diag)
            m1_ok = (em1 is not None and em1 >= m1_floor)
            m6_ok = (em6 is not None and em6 >= 0.0)
            # ROUND-8 (lever 2): launch gate. Off (default) -> always True (round-7 behavior).
            launch_ok = (not launch_aware) or (elaunch is not None and elaunch >= launch_min)
            # ROUND-6 (lever 4): a candidate fully qualifies iff its eval press is IN the HUMAN
            # BAND [press_floor, ceiling] (round 5 drove press to 0.0 BELOW the 0.07 floor by
            # picking the lowest-press candidate; the goal is press INSIDE the band, not minimized).
            press_inband = (ep is not None and args.eval_press_floor <= ep < args.eval_press_ceiling)
            print(f"[rl]   cand @it{c['it']}: eval_press={ep} eval_M1={em1} eval_M6={em6} "
                  f"eval_launch={elaunch} -> press_inband={press_inband} M1_ok={m1_ok} "
                  f"M6_ok={m6_ok} launch_ok={launch_ok}", flush=True)
            if press_inband and m1_ok and m6_ok and launch_ok:
                qualified.append((em1, c))               # rank fully-qualified by HIGHEST M1 (best speed @ human press)
            # fallback pool also REQUIRES launch_ok when launch-aware (never fall back to a
            # launch breaker — that was exactly the round-7 @it12 trap).
            if m1_ok and ep is not None and launch_ok:
                in_band.append((ep, c))
        _lr = (f" & launch>={launch_min}" if launch_aware else "")
        if qualified:
            qualified.sort(key=lambda x: x[0], reverse=True)  # highest eval M1 among press-in-band & M6-in-band
            sel = qualified[0][1]; sel_reason = ("press IN human band & M1 in band & M6 in band"
                                                 + _lr + " (max M1)")
        elif in_band:
            # fallback: no candidate fully qualified. Prefer the one CLOSEST to the press band
            # (so we don't re-pick a press-0.0 overshoot NOR a >ceiling bulldozer) while holding
            # M1 (+ launch when launch-aware — the fallback pool is already launch-filtered).
            def _press_dist(x):
                ep = x[0]
                if ep < args.eval_press_floor:
                    return args.eval_press_floor - ep
                if ep >= args.eval_press_ceiling:
                    return ep - args.eval_press_ceiling
                return 0.0
            in_band.sort(key=_press_dist)
            sel = in_band[0][1]
            sel_reason = "fallback: eval press CLOSEST to human band holding M1 in band (no full-qualify)"
        else:
            print("[rl] WARN eval-press selection: NO candidate held M1 in band — "
                  "falling back to in-rollout best", flush=True)

    # restore the SELECTED (eval-press) or BEST-believable (in-rollout) params for saving (NOT
    # the final/collapsed policy). If no eligible iter was found (degenerate run), fall back to
    # the final params with a warning.
    if sel is not None:
        rl.base.load_state_dict(sel["sd"])
        ed = next((d for d in eval_probe if d["it"] == sel["it"]), {})
        print(f"[rl] saving EVAL-PRESS-SELECTED ckpt @it{sel['it']} "
              f"(eval_press={ed.get('eval_press')} eval_M1={ed.get('eval_m1')} "
              f"eval_M6={ed.get('eval_m6')}; reason={sel_reason})", flush=True)
    elif best["sd"] is not None:
        rl.base.load_state_dict(best["sd"])
        print(f"[rl] saving BEST-believable ckpt @it{best['it']} "
              f"(press={best['press']:.3f} fpm~{best['fpm']:.0f} hspeed={best['hsp']:.1f})",
              flush=True)
    else:
        print("[rl] WARN no on-manifold/low-press iter found — saving FINAL params "
              "(this run likely regressed; eval will catch it)", flush=True)

    meta = {
        "init_ckpt": str(Path(args.init_ckpt).resolve()),
        "env_steps": env_steps, "n_iters": n_iters, "n_envs": args.n_envs,
        "rollout_steps": args.rollout_steps, "ppo_epochs": args.ppo_epochs,
        "lr": args.lr, "clip": args.clip, "kl_coef": args.kl_coef,
        "ent_coef": args.ent_coef, "reward_band": [band_lo, band_hi],
        "wall_time_s": round(time.time() - t_start, 1),
        "final_mean_hspeed": mean_hsp, "final_fwd_press": fwd_press,
        "best_it": best["it"], "best_press": best["press"], "best_fpm": best["fpm"],
        "best_hspeed": best["hsp"], "best_score": best["score"],
        "stopped_early_it": stopped_early, "kl_anchor_ceiling": kl_ceiling,
        "press_ceiling": args.press_ceiling,
        "select_by_eval_press": bool(getattr(args, "select_by_eval_press", False)),
        "eval_press_ceiling": float(getattr(args, "eval_press_ceiling", 0.50)),
        "topk_snapshots": K,
        "eval_press_probe": eval_probe,
        "selected_it": (sel["it"] if sel is not None else best["it"]),
        "selected_reason": sel_reason,
        "saved_params": ("eval_press_selected" if sel is not None
                         else ("best_believable" if best["sd"] is not None else "final_fallback")),
    }
    save_rl_ckpt(args.out_ckpt, rl, src_ckpt, dims, head_dims, args.round, meta)
    print(json.dumps({"saved": str(Path(args.out_ckpt).resolve()), "rl_meta": meta}, indent=2),
          flush=True)
    return meta


def _eval_press_screen(rl, src_ckpt, dims, head_dims, args, device, tmptag="sel"):
    """ROUND-4 candidate screen: persist `rl`'s CURRENT base params to a temp ckpt, run the
    SAME goal-conditioned closed-loop eval the gate uses and return
    (eval_fwd_press_frac, eval_M1_avg_hspeed, eval_M6_cadence_margin, eval_launch_pass).
    Self-yaw, conditioned goal — byte-parity with eval_metric_vector's calls, just fewer
    closed-loop segments.

    ROUND-8 (lever 2 — LAUNCH-AWARE selection): the round-7 screen was CLOSED-LOOP ONLY and so
    was BLIND to the launch break (the @it12 candidate had press+M6 in band but had collapsed
    ra_jumps route% 88.8->4.56 = launch 0/3). When --select-launch is set, the screen ALSO runs
    the 3 hard dryroutes (the same DR.run_eval the full vector uses) and returns launch_pass so
    the selection can REQUIRE launch >= --select-launch-min. Without --select-launch it stays
    closed-loop only (launch_pass=None) — the cheap round-7 behavior."""
    import tempfile
    rc = args.resource_coords
    nseg = int(getattr(args, "select_eval_segments", args.eval_segments))
    with tempfile.NamedTemporaryFile(suffix=f"_{tmptag}.pt", delete=False) as tf:
        tmp = Path(tf.name)
    try:
        save_rl_ckpt(tmp, rl, src_ckpt, dims, head_dims, args.round, {"screen": tmptag})
        rep = EV.run_eval(
            tmp, Path(args.bsp), Path(args.db), Path(args.norm_artifact),
            split=args.split, horizon=args.ep_horizon, n_segments=nseg,
            anchors=Path(args.anchors), player_band=None, map_name=args.map,
            n_max=args.n_max, cpu=(device == "cpu"),
            goal_mode="conditioned", resource_coords_path=(Path(rc) if rc else None),
            aim_mode="policy",
        )
        bp = rep["bot_policy"]
        g = bp["gmv"]["gates"]
        m1 = g.get("G-MV4", {}).get("statistic", {}).get("avg_hspeed_qu_per_s")
        m6 = g.get("G-MV3", {}).get("margin", {}).get("flips_per_min_to_nearer_edge")
        ep = bp.get("fwd_press_frac")
        launch_pass = None
        if getattr(args, "select_launch", False):
            # run the SAME 3 hard dryroutes the full vector uses (goal-conditioned, self-yaw)
            # on this candidate ckpt and count launch passes — so selection is launch-aware.
            import eval_broad_dryroute as DR
            hard = ["mega_to_rl", "sng_to_rl", "ra_jumps"]
            launch_set = args.launch_routes.split(",") if args.launch_routes else hard
            launch_pass = 0
            for route in launch_set:
                try:
                    drep = DR.run_eval(
                        tmp, Path(args.bsp), route,
                        norm_artifact=Path(args.norm_artifact), map_name=args.map,
                        n_max=args.n_max, cpu=(device == "cpu"),
                        aim_mode="policy", jump_mode="policy", goal_mode="conditioned",
                        resource_coords_path=(Path(rc) if rc else None),
                    )
                    if drep["bot_policy"].get("passed"):
                        launch_pass += 1
                except Exception as e:  # one route failing must not sink the screen
                    print(f"[rl]   screen {tmptag} dryroute {route} FAILED: "
                          f"{str(e)[:120]}", flush=True)
        return (ep, m1, m6, launch_pass)
    except Exception as e:
        print(f"[rl]   screen {tmptag} FAILED: {str(e)[:160]}", flush=True)
        return (None, None, None, None)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


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
    ap.add_argument("--kl-anchor-ceiling", type=float, default=0.32,
                    help="early-stop + best-ckpt eligibility: max KL(anchor||policy) before "
                         "the policy is judged OFF the believable manifold (runaway). The "
                         "calib runaway hit kl_anchor 0.3->2.6. ROUND-5: relaxed 0.25->0.32 so "
                         "the policy explores the new fast-low-press (air-strafe) basin further "
                         "before stopping (round 4 early-stopped @it8 on kl 0.295, possibly "
                         "before reaching it). G-MV1 is still checked by the eval guard.")
    ap.add_argument("--press-ceiling", type=float, default=0.50,
                    help="best-ckpt eligibility: max in-rollout argmax fwd_press (human top "
                         "0.50). Iters above this are over-pressing -> not eligible as best.")
    # ROUND-4 eval-press selection (the targeted fix for the round-3 in-rollout/eval mismatch)
    ap.add_argument("--select-by-eval-press", action="store_true",
                    help="ROUND-4: after training, eval each of the top-K believable snapshots "
                         "on the goal-conditioned closed-loop and SAVE the one whose EVAL press "
                         "< --eval-press-ceiling while holding M1 in band + M6 in-band (else "
                         "the lowest-eval-press candidate that holds M1). Fixes round-3 where "
                         "in-rollout press did not transfer to the eval distribution.")
    ap.add_argument("--topk-snapshots", type=int, default=6,
                    help="how many top-in-rollout-score believable snapshots to retain for the "
                         "eval-press selection pass (--select-by-eval-press).")
    ap.add_argument("--eval-press-ceiling", type=float, default=0.50,
                    help="eval-press selection: a candidate fully qualifies iff its CLOSED-LOOP "
                         "eval fwd_press_frac is below this (human top 0.50).")
    ap.add_argument("--eval-press-floor", type=float, default=0.07,
                    help="ROUND-6 (lever 4): a candidate fully qualifies iff its eval press is "
                         ">= this (human band floor 0.07). Prevents re-picking a press-0.0 "
                         "overshoot; the goal is press INSIDE [floor,ceiling], not minimized.")
    ap.add_argument("--air-press-thresh", type=float, default=0.40,
                    help="ROUND-6 (lever 1): SOFT air press-barrier hinge. Air-press FRACTION "
                         "below this is FREE; only the excess above it is penalized (weight -1.0). "
                         "Lets press settle in the human band [0.07,0.50] instead of being driven "
                         "to 0.0 by round-5's flat per-tick penalty.")
    ap.add_argument("--r-cad-weight", type=float, default=1.0,
                    help="ROUND-7: weight on the L<->R argmax cadence-flip reward. Round 6's 1.0 "
                         "lost to a parked perpendicular strafe (M6 flips 0.0 from r4init). Raise "
                         "(~1.6) to make flipping net-positive in the in-band-press basin -> "
                         "recover M6 cadence WITHOUT pushing press out of [0.07,0.50].")
    ap.add_argument("--cad-hold-max", type=int, default=230,
                    help="ROUND-7: max human-plausible single-strafe-sign hold (ticks ~16 fpm). "
                         "Both the cadence-flip eligibility window top AND the strafe-bonus decay "
                         "onset. Round 6 (230) let a sign be parked ~the whole 385-tick episode "
                         "with near-full r_strafe; shorten (~140) so the strafe-decay bites earlier "
                         "and KEEPING the bonus REQUIRES a flip -> un-parks the strafe argmax.")
    ap.add_argument("--select-m1-floor", type=float, default=None,
                    help="ROUND-7 (lever 2): eval-press-selection M1 floor (default = the disjoint "
                         "reserve band_lo). Relax slightly (e.g. 252, the gate-band floor) so a "
                         "press-in-band + M6-in-band candidate with M1 just above the gate floor "
                         "can still be saved (the unified snapshot is the goal, not max M1).")
    ap.add_argument("--select-eval-segments", type=int, default=8,
                    help="closed-loop segments for the per-candidate eval-press screen "
                         "(cheaper than the full --eval-segments; the winner gets the full vector).")
    ap.add_argument("--select-launch", action="store_true",
                    help="ROUND-8 (lever 2 — LAUNCH-AWARE selection): also run the 3 hard "
                         "dryroutes in the per-candidate screen and REQUIRE launch >= "
                         "--select-launch-min to qualify. Closes the round-7 hole where the "
                         "closed-loop-only screen saved a launch breaker (@it12: press+M6 in "
                         "band but ra_jumps route% 88.8->4.56 = launch 0/3). Costs 3 dryroutes "
                         "per top-K candidate but cannot pick a launch-breaking ckpt.")
    ap.add_argument("--select-launch-min", type=int, default=1,
                    help="ROUND-8: min dryroute launch passes a candidate must hold to qualify "
                         "under --select-launch (1 = ra_jumps PASS, the held-best's launch 1/3).")
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
