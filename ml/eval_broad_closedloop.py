#!/usr/bin/env python3
"""eval_broad_closedloop.py — CLOSED-LOOP G-MV believability gate for the BROAD BC policy.

WHAT THIS IS (and the gap it closes over the open-loop eval)
============================================================
`ml/eval_broad_believability.py` is OPEN-LOOP: it feeds the policy the REAL held-out
human `agent_observation` per tick and scores the predicted ACTION stream against the
human's. It explicitly marks G-MV1 (face-and-run), G-MV4 (speed band) and
route-retention as **N/A** there, because those need the policy to actually MOVE the
player — open-loop never advances position.

THIS harness is the closed-loop counterpart. The trained policy DRIVES the QW player
movement simulator (`scripts/pmove_sim.py`) with the sim's OWN evolving state fed back
each tick (NOT re-anchored to human state):

  1. seed a `pmove_sim.PlayerState` from a recorded clean val start (origin+velocity),
  2. per tick: read the sim's current velocity + the REPLAYED human view yaw/pitch for
     that tick, build the SAME shared `agent_observation` (normalized), argmax the
     policy's 5 heads -> usercmd (fwd/side/up move + jump button),
  3. step `pmove_sim` one frame; the NEW sim velocity/position feeds step 2 next tick.

Because the bot now produces its OWN trajectory, G-MV1 (yaw-vs-velocity face-and-run),
G-MV3 (strafe cadence) and G-MV4 (speed band) are FINALLY scorable on the bot's own
motion, via the pure-stdlib `scripts/gmv_believability.py` battery — plus a route /
anti-stall retention metric computed on the bot's own path.

HONEST CAVEATS (recorded in every report; a reader must never mistake this for more)
------------------------------------------------------------------------------------
* AIM DEFERRED: the BROAD policy clones movement/jump/attack but NOT view. The view
  yaw/pitch is REPLAYED from the recorded human for that tick (so G-MV1 measures the
  bot's yaw-vs-its-own-velocity using the human's facing intent over the bot's motion).
* SOLO-ROAM: there are no enemies in the sim, so `encode_observation` is called with
  `observed_others=[]` -> the entity channel is all-pad + zero mask (the model handles
  it; ~12% of training frames had zero observed others). No combat dynamics.
* MOVE-HEAD -> USERCMD MAGNITUDE = +-400. The trainer scaled the move target /400
  (`agent_observation._MOVE_SCALE = 400`), so the magnitude-consistent inverse of the
  sign3 class is +-400 (NOT the move-only line's 320, which trained against a /320
  scale). The SIGN is what G-MV1 keys on (yaw vs velocity direction); the magnitude
  mainly affects the speed band (G-MV4) and can be swept on pinnacle if speed lands
  off-band.
* ATTACK is not driven (fire stays stock); the predicted attack class is recorded for
  completeness only.
* PLANE: the anchor speed band is on the MVD event-rate finite-difference plane
  (~13 ms); the sim speed here is `hypot(vx,vy)` sampled at the recorded ~13 ms tick
  cadence — close but not byte-identical (gate_mv4 widens the band 5% and states this).

CONTROLS (the proof the judge is valid — these run, in part, on a deps-free box too)
------------------------------------------------------------------------------------
The SAME closed-loop harness is run with two non-policy controllers as discrimination
controls, and a synthetic negative control:
  * controller="recorded" (POSITIVE control): the recorded HUMAN usercmd drives the sim
    -> must PASS G-MV1 (a real human trajectory is believable);
  * synthetic "face_and_run" (NEGATIVE control, `gmv.synth_face_and_run`): yaw locked to
    velocity every tick -> must FAIL G-MV1. gmv is pure stdlib, so THIS control runs for
    real even on a box with no torch (and is asserted in the unit test).
A judge that fails the bot but ALSO fails the human, or passes face-and-run, is not a
valid judge — the report prints all three side by side.

The believability NUMBERS for the POLICY can only come from the pinnacle run (torch +
duckdb); this module's pure-python glue + the gmv controls are unit-tested deps-free.

CLI
===
  python -m ml.eval_broad_closedloop \
      --checkpoint ~/broad_bc_policy.pt \
      --db ~/komodobots/data/catalog/dm3_4on4_slice.sqlite \
      --norm-artifact ~/komodobots/ml/gold/norm/normalization_stats.json \
      --bsp /path/to/dm3.bsp \
      --split val --horizon 385 \
      --anchors references/dm3_4on4_anchors.json \
      --out closedloop_gmv_report.json [--player-band NAME] [--n-segments N] [--cpu]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent          # ml/
REPO_ROOT = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

# DEPS-FREE imports only at module load. torch / numpy / duckdb and the heavy
# encoders/loaders are imported LAZILY inside run_eval(), so this module and its
# pure-python glue import on bare stdlib python (the unit tests verify this).
from broad_bc import shard_contract as SC        # noqa: E402  (deps-free)
import gmv_believability as GMV                   # noqa: E402  (pure stdlib)


# =============================================================================
# Frozen head order (the trainer's heads). head_dims order == HEAD_NAMES order.
# sign3 classes {0: back/left/down, 1: none, 2: fwd/right/up}; bin {0,1}.
# =============================================================================
HEAD_NAMES = SC.head_names()                      # ["fwd","side","up","jump","attack"]

# usercmd move magnitude (qu). The BROAD trainer scaled the move target /400
# (agent_observation._MOVE_SCALE = 400), so the magnitude-consistent inverse of the
# sign3 class is +-400. (The move-ONLY Stage-2 line used 320 because it trained a
# /320-equivalent target; the broad policy did NOT — so 400 here is correct.)
MOVE_MAG = 400.0

# pmove jump button bit (mirrors pmove_sim.BUTTON_JUMP = 2; kept as a module const so
# the decode is exercisable without importing the heavy sim).
BUTTON_JUMP = 2


# =============================================================================
# PURE-PYTHON GLUE  (no torch / numpy / duckdb — unit-tested deps-free)
# The torch CLI (run_eval) calls EXACTLY these after producing per-head argmax.
# =============================================================================
def move_class_to_mag(cls: int, mag: float = MOVE_MAG) -> float:
    """Inverse of shard_contract.encode_sign3 for a usercmd magnitude.

    encode_sign3: value > +dz -> 2, value < -dz -> 0, else 1. So the class->signed
    magnitude inverse is: 2 -> +mag, 0 -> -mag, 1 -> 0. Pure int/float math.
    """
    c = int(cls)
    if c == 2:
        return float(mag)
    if c == 0:
        return float(-mag)
    return 0.0


def decode_move_heads(pred_classes, mag: float = MOVE_MAG):
    """5 per-head argmax classes (fwd/side/up/jump/attack order) -> the usercmd the
    sim consumes: (fwd_mag, side_mag, up_mag, jump_bit).

    fwd/side/up are sign3 -> +-mag/0 via move_class_to_mag. jump is the BUTTON_JUMP
    bit when the jump head argmax == 1. attack is IGNORED for control (fire stays
    stock) — the caller may still log the predicted attack class separately. Pure.
    """
    pc = list(pred_classes)
    fwd_mag = move_class_to_mag(pc[0], mag)
    side_mag = move_class_to_mag(pc[1], mag)
    up_mag = move_class_to_mag(pc[2], mag)
    jump_bit = BUTTON_JUMP if int(pc[3]) == 1 else 0
    return fwd_mag, side_mag, up_mag, jump_bit


def gmv_tick_from_state(origin, vel, onground, yaw, side_mag, msec: float = 13.0) -> dict:
    """Build the one gmv-battery tick dict from a (post-frame) sim state + the
    predicted usercmd. Keys the battery reads: vx, vy, yaw, onground, hspeed,
    sidemove, msec (origin is carried for route metrics, ignored by the gates).

    `vel` = (vx, vy, vz); hspeed = hypot(vx, vy). `side_mag` is the predicted
    sidemove magnitude (so G-MV3 cadence sees the bot's OWN strafe intent). `yaw` is
    the REPLAYED human view yaw. Pure python.
    """
    vx = float(vel[0])
    vy = float(vel[1])
    return {
        "vx": vx,
        "vy": vy,
        "yaw": float(yaw),
        "onground": bool(onground),
        "hspeed": math.hypot(vx, vy),
        "sidemove": float(side_mag),
        "msec": float(msec),
        # origin carried for route_metrics (not used by the gates):
        "_ox": float(origin[0]),
        "_oy": float(origin[1]),
    }


def route_metrics(origins, speeds, msecs, *,
                  stall_window_s: float = 0.5, stall_speed: float = 40.0) -> dict:
    """Route-retention on the bot's OWN path: total 2-D path length + an anti-stall
    check (no contiguous window of ~>= stall_window_s where speed stays near-zero).

    `origins` = list of (x, y) the bot passed through (post-frame), `speeds` =
    per-tick horizontal speed (qu/s), `msecs` = per-tick frame ms. A bot that wedges
    against a wall / stops moving is NOT route-retaining even if its instantaneous
    facing is human; this surfaces it as `stalled=True` + the longest stall length.

    Returns {path_len_qu, n_ticks, mean_speed_qu_per_s, stalled, longest_stall_s,
    longest_stall_ticks, duration_s, displacement_qu}. Pure python (no numpy) — a
    prime deps-free unit-test target.
    """
    n = len(speeds)
    path_len = 0.0
    for i in range(1, len(origins)):
        ax, ay = origins[i - 1]
        bx, by = origins[i]
        path_len += math.hypot(float(bx) - float(ax), float(by) - float(ay))

    # anti-stall: longest contiguous run of near-zero-speed ticks, measured in seconds
    # via the per-tick msec (so it is robust to frame-rate). A run that reaches
    # stall_window_s flips `stalled`.
    longest_stall_s = 0.0
    longest_stall_ticks = 0
    cur_s = 0.0
    cur_ticks = 0
    for i in range(n):
        ms = (float(msecs[i]) if i < len(msecs) and msecs[i] else 13.0) / 1000.0
        if float(speeds[i]) < stall_speed:
            cur_s += ms
            cur_ticks += 1
            if cur_s > longest_stall_s:
                longest_stall_s = cur_s
                longest_stall_ticks = cur_ticks
        else:
            cur_s = 0.0
            cur_ticks = 0

    duration_s = sum((float(m) if m else 13.0) for m in msecs) / 1000.0
    mean_speed = (sum(float(s) for s in speeds) / n) if n else 0.0
    disp = 0.0
    if len(origins) >= 2:
        disp = math.hypot(float(origins[-1][0]) - float(origins[0][0]),
                          float(origins[-1][1]) - float(origins[0][1]))
    return {
        "path_len_qu": round(path_len, 2),
        "n_ticks": n,
        "mean_speed_qu_per_s": round(mean_speed, 3),
        "stalled": bool(longest_stall_s >= stall_window_s),
        "longest_stall_s": round(longest_stall_s, 4),
        "longest_stall_ticks": longest_stall_ticks,
        "duration_s": round(duration_s, 3),
        "displacement_qu": round(disp, 2),
        "stall_window_s": stall_window_s,
        "stall_speed_qu_per_s": stall_speed,
    }


def aggregate_route_metrics(segment_routes, *,
                            stall_window_s: float = 0.5) -> dict:
    """Combine PER-SEGMENT route dicts (each from route_metrics on ONE segment's own
    origins) into a corpus-level route summary WITHOUT re-running route_metrics on a
    concatenation of segment origins.

    Why this exists: route_metrics sums hypot over CONSECUTIVE origins and takes the
    first/last origin for displacement. If segment origins are pooled by concatenation,
    every segment boundary (segment N's last origin -> segment N+1's first origin) is a
    discontinuous JUMP across the map that injects a bogus TELEPORT distance into both
    path_len_qu and displacement_qu. Each segment's own route dict is already correct,
    so we aggregate THOSE instead:

      * path_len_qu, n_ticks, longest_stall_ticks-source, duration_s : SUMMED
      * mean_speed_qu_per_s : DURATION-WEIGHTED mean of per-segment means (so a long
        segment weights proportionally — identical to a pooled per-tick mean when the
        per-tick msec is uniform, which it is here ~13ms)
      * longest_stall_s / longest_stall_ticks : MAX over segments (a stall is a within-
        segment run; the longest single contiguous stall is the meaningful figure — a
        boundary can NOT create or extend a real stall)
      * stalled : ANY segment stalled (longest single-segment stall >= window)
      * displacement_qu : NOT summable across discontinuous segments, and net A->B
        displacement is per-segment by nature -> reported as the SUM of per-segment
        |displacement| (total straight-line ground covered, segment by segment), which
        is the honest cross-segment analog and never crosses a teleport boundary.

    Pure python; deps-free unit-test target. Empty input -> a zeroed route dict.
    """
    routes = list(segment_routes)
    if not routes:
        return {
            "path_len_qu": 0.0, "n_ticks": 0, "mean_speed_qu_per_s": 0.0,
            "stalled": False, "longest_stall_s": 0.0, "longest_stall_ticks": 0,
            "duration_s": 0.0, "displacement_qu": 0.0,
            "stall_window_s": stall_window_s, "stall_speed_qu_per_s": None,
            "n_segments": 0,
        }
    path_len = sum(float(r.get("path_len_qu", 0.0)) for r in routes)
    n_ticks = sum(int(r.get("n_ticks", 0)) for r in routes)
    duration = sum(float(r.get("duration_s", 0.0)) for r in routes)
    disp = sum(float(r.get("displacement_qu", 0.0)) for r in routes)
    # duration-weighted mean speed (fall back to tick-count weight if durations are 0)
    wsum = sum(float(r.get("duration_s", 0.0)) for r in routes)
    if wsum > 0:
        mean_speed = sum(float(r.get("mean_speed_qu_per_s", 0.0)) * float(r.get("duration_s", 0.0))
                         for r in routes) / wsum
    else:
        tw = sum(int(r.get("n_ticks", 0)) for r in routes)
        mean_speed = (sum(float(r.get("mean_speed_qu_per_s", 0.0)) * int(r.get("n_ticks", 0))
                          for r in routes) / tw) if tw else 0.0
    # longest SINGLE-segment stall (max, not sum — a stall never spans a boundary)
    longest_stall_s = max((float(r.get("longest_stall_s", 0.0)) for r in routes), default=0.0)
    longest_stall_ticks = max((int(r.get("longest_stall_ticks", 0)) for r in routes), default=0)
    stalled = any(bool(r.get("stalled")) for r in routes)
    stall_speed = next((r.get("stall_speed_qu_per_s") for r in routes
                        if r.get("stall_speed_qu_per_s") is not None), None)
    return {
        "path_len_qu": round(path_len, 2),
        "n_ticks": n_ticks,
        "mean_speed_qu_per_s": round(mean_speed, 3),
        "stalled": bool(stalled),
        "longest_stall_s": round(longest_stall_s, 4),
        "longest_stall_ticks": longest_stall_ticks,
        "duration_s": round(duration, 3),
        "displacement_qu": round(disp, 2),
        "stall_window_s": stall_window_s,
        "stall_speed_qu_per_s": stall_speed,
        "n_segments": len(routes),
    }


def score_sequence_gmv(ticks, anchors=None, player_band=None) -> dict:
    """Thin wrapper over the pure-stdlib gmv battery on a built tick list. Returns the
    full `run_battery` result (gates G-MV1 HARD / G-MV3 / G-MV4, `believable`,
    `all_gates_passed`). Importable + runnable deps-free (gmv has no heavy deps)."""
    return GMV.run_battery(ticks, anchors=anchors, player_band=player_band)


def summarize_gmv(battery: dict) -> dict:
    """Compact, report-friendly view of a battery result: per-gate pass + the headline
    statistic, so the printed control table stays small. Pure python."""
    gates = battery.get("gates", {})

    def _g(name):
        g = gates.get(name)
        if not g:
            return {"present": False}
        return {"present": True, "passed": g.get("passed"),
                "status": g.get("status"), "statistic": g.get("statistic")}
    return {
        "believable_G_MV1": battery.get("believable"),
        "all_gates_passed": battery.get("all_gates_passed"),
        "n_ticks": battery.get("n_ticks"),
        "G_MV1": _g("G-MV1"),
        "G_MV3": _g("G-MV3"),
        "G_MV4": _g("G-MV4"),
    }


# =============================================================================
# Start-state selection (pure python over the loaded val episodes). Picks segments
# long enough (>= horizon) with enough airborne-moving ticks that gate_mv1 (needs
# >= mv1_min_ticks airborne-moving over the horizon) can actually be scored.
# =============================================================================
def _airborne_moving_count(ticks, *, hspeed_floor: float = None) -> int:
    """How many ticks are airborne (onground falsey) AND moving (hspeed >= floor) in a
    recorded segment — the gate_mv1 domain proxy used to pick startable segments."""
    if hspeed_floor is None:
        hspeed_floor = GMV.DEFAULT_THRESHOLDS["mv1_min_hspeed_qu_per_s"]
    c = 0
    for t in ticks:
        self_state = t.get("self", {})
        og = self_state.get("onground")
        if og:
            continue
        hs = self_state.get("hspeed")
        if hs is None:
            vx = float(self_state.get("vx", 0.0) or 0.0)
            vy = float(self_state.get("vy", 0.0) or 0.0)
            hs = math.hypot(vx, vy)
        if float(hs) >= hspeed_floor:
            c += 1
    return c


def select_start_segments(episodes, *, horizon: int, n_segments: int,
                          min_airborne_moving: int = None) -> list:
    """From {eid: [tick_obs,...]} pick up to `n_segments` (eid, start_index, segment)
    triples, each a horizon-length slice with enough airborne-moving ticks to give
    gate_mv1 a verdict. Deterministic: episodes sorted, first qualifying window per
    episode taken (one segment per episode keeps coverage broad). Pure python."""
    if min_airborne_moving is None:
        # gate_mv1 needs >= mv1_min_ticks airborne-moving ticks; require at least that
        # many in the chosen window so the bot's G-MV1 is scorable, not "insufficient".
        min_airborne_moving = GMV.DEFAULT_THRESHOLDS["mv1_min_ticks"]
    out = []
    for eid in sorted(episodes):
        ticks = episodes[eid]
        if len(ticks) < horizon + 1:
            continue
        # scan stride = horizon (non-overlapping) for the first window that qualifies.
        start = 0
        while start + horizon + 1 <= len(ticks):
            seg = ticks[start:start + horizon + 1]   # +1 so a post-frame end exists
            if _airborne_moving_count(seg) >= min_airborne_moving:
                out.append((eid, start, seg))
                break
            start += horizon
        if len(out) >= n_segments:
            break
    return out


# =============================================================================
# TORCH + NUMPY + DUCKDB PATH — the only part that needs the heavy deps (pinnacle).
# Everything above is pure python and unit-tested without torch/numpy/duckdb.
# =============================================================================
def _self_state_from_sim(st, yaw, pitch) -> dict:
    """agent_observation self_state for the CURRENT sim state + the REPLAYED human
    view. Keys match what agent_observation.self_features reads. health/armor/team
    are unknown in solo-roam -> left out (encoder zero-fills them)."""
    vx, vy, vz = st.velocity[0], st.velocity[1], st.velocity[2]
    return {
        "ox": st.origin[0], "oy": st.origin[1], "oz": st.origin[2],
        "vx": vx, "vy": vy, "vz": vz,
        "yaw": float(yaw), "pitch": float(pitch),
        "hspeed": math.hypot(vx, vy),
        "onground": bool(st.onground),
    }


def _recorded_usercmd(act_state):
    """Recorded HUMAN usercmd magnitudes for the POSITIVE control: read the raw
    forwardmove/sidemove/upmove + jump button from the `actions` row. Returns
    (fwd_mag, side_mag, up_mag, jump_bit). A None action -> idle."""
    if not act_state:
        return 0.0, 0.0, 0.0, 0
    fwd = float(act_state.get("forwardmove", 0.0) or 0.0)
    side = float(act_state.get("sidemove", 0.0) or 0.0)
    up = float(act_state.get("upmove", 0.0) or 0.0)
    buttons = int(act_state.get("buttons", 0) or 0)
    jump_bit = BUTTON_JUMP if (buttons & BUTTON_JUMP) else 0
    return fwd, side, up, jump_bit


def closed_loop_rollout(pm_module, world, segment, controller, *,
                        model=None, dims=None, norm=None, map_name="dm3",
                        n_max=7, device="cpu", torch_mod=None):
    """Drive `pmove_sim` closed-loop over one recorded segment, mirroring the Stage-2
    `eval_closedloop.closed_loop_run` skeleton but with the BROAD obs + heads.

    controller in {"policy","recorded"}. Returns (gmv_ticks, origins, speeds, msecs,
    predicted_attack_classes). The gmv tick is captured from the POST-frame sim state
    so the gates see the bot's own resulting motion.
    """
    pm = pm_module.Pmove(world)
    t0 = segment[0]["self"]
    st = pm_module.PlayerState(
        [float(t0.get("ox", 0.0)), float(t0.get("oy", 0.0)), float(t0.get("oz", 0.0))],
        [float(t0.get("vx", 0.0)), float(t0.get("vy", 0.0)), float(t0.get("vz", 0.0))],
    )

    gmv_ticks = []
    origins = []
    speeds = []
    msecs = []
    attack_classes = []

    # one fewer step than len(segment) so segment[k+1] is never needed (we replay
    # segment[k]'s view onto the bot's own state); the +1 tick in the segment is the
    # post-frame anchor headroom only.
    n = len(segment) - 1
    for k in range(n):
        rec_self = segment[k]["self"]
        yaw = float(rec_self.get("yaw", 0.0) or 0.0)
        pitch = float(rec_self.get("pitch", 0.0) or 0.0)
        angles = [pitch, yaw, 0.0]
        rec_act = segment[k].get("act")
        msec = 13
        if rec_act and rec_act.get("msec"):
            msec = rec_act["msec"]

        if controller == "policy":
            self_state = _self_state_from_sim(st, yaw, pitch)
            enc = norm["_AO"].encode_observation(self_state, [], norm["_stats"], map_name, n_max)
            obs_t = torch_mod.tensor([enc["self"]], dtype=torch_mod.float32, device=device)
            f_ent = dims["f_ent"]
            if f_ent > 0:
                ent_t = torch_mod.tensor([enc["ents"]], dtype=torch_mod.float32, device=device)
                em_t = torch_mod.tensor([enc["mask"]], dtype=torch_mod.float32, device=device)
            else:
                ent_t = torch_mod.zeros((1, n_max, 0), device=device)
                em_t = torch_mod.zeros((1, n_max), device=device)
            aux_t = torch_mod.zeros((1, dims["f_aux"]), device=device)
            with torch_mod.no_grad():
                logits = model(obs_t, ent_t, em_t, aux_t)
            pred_cls = [int(lg.argmax(dim=1).item()) for lg in logits]
            fwd_mag, side_mag, up_mag, jump_bit = decode_move_heads(pred_cls)
            attack_classes.append(pred_cls[4])
        else:  # "recorded" positive control
            fwd_mag, side_mag, up_mag, jump_bit = _recorded_usercmd(rec_act)
            attack_classes.append(None)

        cmd = pm_module.Cmd(msec, angles, [fwd_mag, side_mag, up_mag], jump_bit)
        pm.run_frame(st, cmd)

        # capture the gmv tick from the POST-frame sim state + replayed yaw + the
        # predicted strafe intent (so cadence sees the bot's own side magnitude).
        tick = gmv_tick_from_state(st.origin, st.velocity, st.onground, yaw,
                                   side_mag, msec=msec)
        gmv_ticks.append(tick)
        origins.append((tick["_ox"], tick["_oy"]))
        speeds.append(tick["hspeed"])
        msecs.append(float(msec))

    return gmv_ticks, origins, speeds, msecs, attack_classes


def _controller_report(pooled_ticks, route, anchors, player_band, *,
                       attack_pressed=None) -> dict:
    """Score one controller: gmv battery on the POOLED tick stream + a precomputed
    `route` summary. The gmv gates are per-tick (velocity/yaw/onground/sidemove) and
    pool correctly across segments, but route metrics CANNOT — origins concatenated
    across segments inject a teleport distance at each boundary. So the caller passes
    the route already aggregated from the per-segment route dicts (aggregate_route_metrics);
    this function no longer re-runs route_metrics on pooled origins."""
    battery = score_sequence_gmv(pooled_ticks, anchors=anchors, player_band=player_band)
    rep = {"gmv": battery, "gmv_summary": summarize_gmv(battery), "route": route,
           "n_ticks": len(pooled_ticks)}
    if attack_pressed is not None:
        rep["predicted_attack_rate"] = attack_pressed
    return rep


def run_eval(checkpoint: Path, bsp: Path, db: Path, norm_artifact: Path, *,
             split: str = "val", horizon: int = 385, n_segments: int = 12,
             anchors: Path | None = None, player_band: str | None = None,
             map_name: str = "dm3", n_max: int = 7, cpu: bool = False) -> dict:
    """Closed-loop believability eval. NEEDS torch (policy forward) + numpy (parity) +
    duckdb (catalog start states) + the BSP world. Flow:

      1. load checkpoint -> rebuild BroadBCPolicy (import from eval_broad_believability),
         load norm artifact (json), load the dm3 BSP into pmove_sim.WorldModel.
      2. read val episodes via _load_episode_ticks (the SAME loader the feature build
         uses); pick start segments with enough airborne-moving ticks for gate_mv1.
      3. per segment: closed-loop rollout for controller "policy" and "recorded"
         (positive control); collect each controller's gmv ticks + route data.
      4. score each controller pooled (gmv battery + route metrics); add the synthetic
         face-and-run NEGATIVE control (must FAIL G-MV1). Emit the report + provenance.
    """
    import torch
    import numpy as np  # noqa: F401  (parity w/ the trainer tensor-build path)
    from features import agent_observation as AO
    sys.path.insert(0, str(REPO_ROOT / "ml" / "pipeline"))
    from build_features import _load_episode_ticks
    from eval_broad_believability import _build_policy_from_checkpoint
    import pmove_sim
    from broad_bc import core as _core

    device = "cpu" if cpu else ("cuda" if torch.cuda.is_available() else "cpu")
    ckpt = torch.load(Path(checkpoint).expanduser(), map_location=device)
    model, dims, head_dims = _build_policy_from_checkpoint(ckpt, device)
    stats = json.loads(Path(norm_artifact).expanduser().read_text(encoding="utf-8"))
    world = pmove_sim.WorldModel.load(str(Path(bsp).expanduser()))
    anchors_obj = (json.loads(Path(anchors).expanduser().read_text(encoding="utf-8"))
                   if anchors else None)

    episodes, ep_demo = _load_episode_ticks(Path(db).expanduser(), split=split)
    segments = select_start_segments(episodes, horizon=horizon, n_segments=n_segments)

    # carry the encoder + stats through the rollout without re-importing per tick.
    norm_bundle = {"_AO": AO, "_stats": stats}

    per_segment = []
    # pooled TICK streams per controller (gmv gates pool correctly per-tick). Route
    # data is NOT pooled by concatenation — origins from different segments are
    # discontinuous, so we keep each segment's OWN route dict and aggregate those
    # (aggregate_route_metrics) to avoid a teleport distance at every segment boundary.
    pool = {
        "policy": {"ticks": [], "attack": [], "routes": []},
        "recorded": {"ticks": [], "routes": []},
    }
    for (eid, start, seg) in segments:
        pol = closed_loop_rollout(
            pmove_sim, world, seg, "policy", model=model, dims=dims,
            norm=norm_bundle, map_name=map_name, n_max=n_max, device=device,
            torch_mod=torch)
        rec = closed_loop_rollout(
            pmove_sim, world, seg, "recorded", map_name=map_name, n_max=n_max)

        p_ticks, p_org, p_spd, p_ms, p_atk = pol
        r_ticks, r_org, r_spd, r_ms, _ = rec
        # per-segment route dicts (each on ITS OWN origins -> correct, no boundary jump)
        p_route = route_metrics(p_org, p_spd, p_ms)
        r_route = route_metrics(r_org, r_spd, r_ms)
        pool["policy"]["ticks"].extend(p_ticks)
        pool["policy"]["attack"].extend([a for a in p_atk if a is not None])
        pool["policy"]["routes"].append(p_route)
        pool["recorded"]["ticks"].extend(r_ticks)
        pool["recorded"]["routes"].append(r_route)

        per_segment.append({
            "episode_id": int(eid),
            "demo_id": str(ep_demo.get(eid, eid)),
            "start_index": int(start),
            "n_ticks": len(p_ticks),
            "policy": {
                "gmv_summary": summarize_gmv(
                    score_sequence_gmv(p_ticks, anchors=anchors_obj, player_band=player_band)),
                "route": p_route,
            },
            "recorded": {
                "gmv_summary": summarize_gmv(
                    score_sequence_gmv(r_ticks, anchors=anchors_obj, player_band=player_band)),
                "route": r_route,
            },
        })

    # aggregate controller reports: gmv on pooled ticks, route from per-segment dicts.
    atk = pool["policy"]["attack"]
    atk_rate = round(sum(1 for a in atk if int(a) == 1) / len(atk), 6) if atk else 0.0
    bot_policy = _controller_report(
        pool["policy"]["ticks"], aggregate_route_metrics(pool["policy"]["routes"]),
        anchors_obj, player_band, attack_pressed=atk_rate)
    recorded_human = _controller_report(
        pool["recorded"]["ticks"], aggregate_route_metrics(pool["recorded"]["routes"]),
        anchors_obj, player_band)

    # synthetic NEGATIVE control — gmv is stdlib so this runs for real anywhere.
    face_run = GMV.synth_face_and_run(n=max(2000, horizon * 4))
    face_run_battery = score_sequence_gmv(face_run, anchors=anchors_obj,
                                          player_band=player_band)

    report = {
        "schema": "komodobots.eval_broad_closedloop.v1",
        "eval_mode": "closed_loop",
        "inputs": {
            "checkpoint": str(Path(checkpoint).expanduser()),
            "bsp": str(Path(bsp).expanduser()),
            "db": str(Path(db).expanduser()),
            "norm_artifact": str(Path(norm_artifact).expanduser()),
            "split": split, "horizon_ticks": horizon,
            "approx_horizon_secs": round(horizon * 0.013, 2),
            "n_segments_requested": n_segments,
            "n_segments_used": len(segments),
            "map": map_name, "n_max": n_max,
            "anchors": str(anchors) if anchors else None,
            "player_band": player_band or "pool",
        },
        "checkpoint_meta": {
            "arch": ckpt.get("arch"), "dims": dims, "head_dims": head_dims,
            "head_names": ckpt.get("head_names"),
            "contract_version": ckpt.get("contract_version"),
            "trained_val_action_accuracy": ckpt.get("val_acc"),
        },
        "decode": {
            "move_magnitude_qu": MOVE_MAG,
            "note": ("sign3 class -> usercmd: 2->+MAG, 0->-MAG, 1->0; MAG=400 matches "
                     "the BROAD trainer's /400 move scale (agent_observation._MOVE_SCALE). "
                     "jump head==1 -> BUTTON_JUMP; attack head NOT driven (logged only). "
                     "view yaw/pitch REPLAYED from the recorded human (AIM deferred)."),
            "button_jump_bit": BUTTON_JUMP,
        },
        "anchor_bands": _anchor_band_summary(anchors_obj, player_band),
        # the three-way discrimination view (the proof the judge is valid):
        "bot_policy": bot_policy,
        "recorded_human": recorded_human,          # POSITIVE control (expect G-MV1 pass)
        "face_and_run_synthetic": {                 # NEGATIVE control (expect G-MV1 FAIL)
            "gmv_summary": summarize_gmv(face_run_battery),
            "n_ticks": face_run_battery.get("n_ticks"),
            "expect": "G-MV1 must FAIL (yaw locked to velocity every tick)",
        },
        "per_segment": per_segment,
        "caveats": _build_caveats(),
        "provenance": {
            "git_sha": _core.git_sha(REPO_ROOT),
            "norm_artifact_version": stats.get("artifact_version", "UNSET"),
            "registry_version": stats.get("registry_version"),
            "torch": getattr(torch, "__version__", None),
            "device": device,
        },
    }
    return report


def _anchor_band_summary(anchors_obj, player_band) -> dict:
    """Echo the G-MV4 speed band that will judge the run (pool or per-player)."""
    if not anchors_obj:
        return {"present": False, "reason": "no --anchors provided"}
    try:
        thr = GMV.DEFAULT_THRESHOLDS
        avg_lo, avg_hi, avg_src = GMV._band_for(anchors_obj, thr["mv4_avg_field"], player_band)
        p95_lo, p95_hi, p95_src = GMV._band_for(anchors_obj, thr["mv4_p95_field"], player_band)
    except Exception as e:  # noqa: BLE001
        return {"present": True, "error": str(e)}
    return {
        "present": True,
        "avg_horizontal_speed_qu_per_s": {"min": avg_lo, "max": avg_hi, "source": avg_src},
        "p95_horizontal_speed_qu_per_s": {"min": p95_lo, "max": p95_hi, "source": p95_src},
        "plane": "mvd_event_rate_finite_difference (~13ms); sim sampled at recorded ~13ms tick",
        "schema": anchors_obj.get("schema"),
    }


def _build_caveats() -> dict:
    return {
        "eval_mode": "closed_loop",
        "what_closed_loop_means": (
            "The policy DRIVES pmove_sim with the sim's own evolving state fed back "
            "each tick (not re-anchored to human state), so G-MV1/G-MV3/G-MV4 and route "
            "retention are scored on the BOT's own resulting trajectory."),
        "aim_head": "REPLAYED",
        "aim_head_detail": (
            "The BROAD policy clones movement/jump/attack but NOT view. The view "
            "yaw/pitch each tick is REPLAYED from the recorded human; G-MV1 measures the "
            "bot's yaw-vs-its-own-velocity over the bot's motion under that facing."),
        "solo_roam": (
            "No enemies in the sim -> encode_observation is called with observed_others=[] "
            "(entity channel all-pad + zero mask). Combat dynamics are out of scope here."),
        "move_magnitude": (
            "Move-head -> usercmd magnitude = +-400 (trainer /400 scale). The SIGN drives "
            "G-MV1 (yaw vs velocity); magnitude mainly affects G-MV4 speed band — sweepable "
            "on pinnacle if speed lands off-band."),
        "attack_not_driven": "Predicted attack class is logged but does not fire in the sim.",
        "speed_plane": (
            "anchor speed band is mvd_event_rate_finite_difference (~13ms); sim hspeed is "
            "hypot(vx,vy) at the recorded ~13ms tick — close, not byte-identical (G-MV4 "
            "widens the band 5%)."),
        "controls": (
            "recorded-human (positive, must PASS G-MV1) and synthetic face-and-run "
            "(negative, must FAIL G-MV1) bracket the policy so the judge is shown valid."),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--checkpoint", type=Path, required=True,
                    help="broad_bc_policy.pt (train_broad_bc.py output)")
    ap.add_argument("--bsp", type=Path, required=True,
                    help="dm3.bsp (the map the sim rolls out in)")
    ap.add_argument("--db", type=Path, required=True,
                    help="catalog .sqlite with held-out `val` episodes (start states)")
    ap.add_argument("--norm-artifact", type=Path, required=True,
                    help="normalization_stats.json (SAME artifact training used)")
    ap.add_argument("--split", default="val")
    ap.add_argument("--horizon", type=int, default=385, help="rollout ticks (~5s @ 13ms)")
    ap.add_argument("--n-segments", type=int, default=12,
                    help="max start segments to roll out")
    ap.add_argument("--out", type=Path, required=True, help="report.json path")
    ap.add_argument("--anchors", type=Path, default=None,
                    help="references/dm3_4on4_anchors.json (enables G-MV4 speed band)")
    ap.add_argument("--player-band", default=None,
                    help="anchor player name for the G-MV4 band (else pool envelope)")
    ap.add_argument("--map", default="dm3")
    ap.add_argument("--n-max", type=int, default=7)
    ap.add_argument("--cpu", action="store_true", help="force CPU forward")
    args = ap.parse_args(argv)

    report = run_eval(
        args.checkpoint, args.bsp, args.db, args.norm_artifact,
        split=args.split, horizon=args.horizon, n_segments=args.n_segments,
        anchors=args.anchors, player_band=args.player_band,
        map_name=args.map, n_max=args.n_max, cpu=args.cpu,
    )
    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    bot = report["bot_policy"]["gmv_summary"]
    rec = report["recorded_human"]["gmv_summary"]
    far = report["face_and_run_synthetic"]["gmv_summary"]
    print(f"wrote {out}", flush=True)
    print(f"  segments used = {report['inputs']['n_segments_used']} "
          f"horizon = {report['inputs']['horizon_ticks']} ticks", flush=True)
    print("  G-MV1 (face-and-run, HARD)   bot=%s  recorded=%s  face_and_run=%s"
          % (bot["G_MV1"].get("passed"), rec["G_MV1"].get("passed"),
             far["G_MV1"].get("passed")), flush=True)
    print("  G-MV3 (strafe cadence)       bot=%s  recorded=%s"
          % (bot["G_MV3"].get("passed"), rec["G_MV3"].get("passed")), flush=True)
    print("  G-MV4 (speed band)           bot=%s  recorded=%s"
          % (bot["G_MV4"].get("passed"), rec["G_MV4"].get("passed")), flush=True)
    print("  route(bot): path_len=%s qu  stalled=%s  longest_stall=%ss"
          % (report["bot_policy"]["route"]["path_len_qu"],
             report["bot_policy"]["route"]["stalled"],
             report["bot_policy"]["route"]["longest_stall_s"]), flush=True)
    print("  CONTROLS: recorded-human should PASS G-MV1; face-and-run should FAIL G-MV1.",
          flush=True)
    print("  CAVEATS: closed-loop; AIM replayed; solo-roam; MOVE mag=400; attack not driven.",
          flush=True)
    # exit non-zero if the discrimination controls are wrong (the judge is invalid),
    # so a CI consumer never trusts a run whose controls failed.
    rec_ok = rec["G_MV1"].get("passed") is True
    far_fail = far["G_MV1"].get("passed") is False
    if not (rec_ok and far_fail):
        print("  WARNING: discrimination controls did not bracket as expected "
              "(recorded PASS + face-and-run FAIL) — treat policy verdict with care.",
              flush=True)
        return 4
    return 0


if __name__ == "__main__":
    sys.setrecursionlimit(20000)
    raise SystemExit(main())
