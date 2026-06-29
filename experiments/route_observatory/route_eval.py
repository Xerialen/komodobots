#!/usr/bin/env python3
"""route_eval.py — T5.2 (#428) the route-isolated EVAL harness (PR1 vertical slice).

Turn a recorded prewar-movecheck run into one objective, re-runnable score: GEOMETRICALLY pin the
base Route-Canon highway the bot drove (within the engine-logged ENGAGED window), extract the bot
trajectory, grade route ADHERENCE (MSE/RMSE vs the #420 seed line) AND record a VELOCITY/duration
scalar, write a `komodobots.route_eval.v1` artifact into the run dir, and merge the score into that
run's attempt-ledger row so the number and the watchable MVD travel together. This replaces "validate
by 4v4 / by eye" with automated, repeatable scoring (docs/28 Phase-2; #428 Verification).

WHAT THIS METRIC IS / ISN'T (read before trusting a number — eval-integrity):
  * adherence MSE/RMSE = a route-SHAPE / route-ADHERENCE proxy vs the ONE #420 seed line ("did the
    bot run THIS highway"). It is SPEED-BLIND (arc-fraction grid renormalises to [0,1]) and is NOT the
    optimization target — matching the human centerline would CAP the bot at human; we want it FASTER.
    It is NOT a #421-band believability judgment.
  * The Phase-2 objective is VELOCITY (epic #415). `velocity.mean_speed_qu_s` is the explicit,
    duration-aware scalar; #427's reward sources speed from THAT term, NEVER from the MSE.
  * A LARGE MSE is a PASS for the PLUMBING (the frozen 6-feat live mover won't track a highway;
    quality is the RL job, #427). #428 proves the MEASUREMENT is automated, objective + velocity-aware.

THE GEOMETRIC PIN (the keystone — replaces a broken log-index parse). The engine's
`[moveprobe-handoff] slot N ENGAGED|DISENGAGED` log carries the engaged WINDOW but NO highway id and
NO coordinates (verified: frogbot-moveprobe-handoff.patch:101-102). So the driven highway is pinned
PURELY from geometry: over the `route_class=='base'` highways, the nearest by mean point-to-polyline
distance (xy) to the bot's path — the offline mirror of the live C primitive
`mhw_nearest_base_highway` (experiments/ktx_moveprobe/live/move_highway.{c,h}). No engine change, no
log id.

Pure stdlib + the in-repo reuse modules (no numpy/torch/PyYAML), so the pure core runs in the
merge-gating `python -m unittest discover -s tests` floor. The only impure parts (the `qw-analyze`
subprocess + run-dir/ledger file I/O) are thin wrappers, exercised on-box, not in CI.

Reuses (do NOT reinvent):
  * score_route_mse.load_highway_seed / build_artifact  — the #423 MSE scorer core.
  * route_legs.player_ticks + pov_fuse_extract._find_player — the SAME qw-analyze-JSON decode that
    built the #420 seed lines (unit symmetry: the attempt is decoded into qu exactly like the seed).

Usage (standalone, on a recorded run dir):
  route_eval.py <run_dir> [--slot 1] [--player <botname>] [--grid arclen|time] \
      [--canon data/catalog/route_canon.dm3.json] [--ledger <bot-attempts.json>] [--no-write]
"""
from __future__ import annotations

import argparse
import bisect
import json
import logging
import math
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = Path(HERE).resolve().parents[1]
if HERE not in sys.path:                 # score_route_mse / route_legs / pov_fuse_extract live here
    sys.path.insert(0, HERE)

import score_route_mse                          # noqa: E402  (the #423 MSE scorer core)
from route_legs import player_ticks             # noqa: E402  (seed-symmetric per-tick decode)
from pov_fuse_extract import _find_player        # noqa: E402

LOGGER = logging.getLogger(__name__)

SCHEMA = "komodobots.route_eval.v1"

# progress_fraction = attempt 3-D arclen / seed 3-D arclen. Below this the bot barely moved ->
# the run is degenerate (stalled) and the adherence MSE is not meaningful (it scores a near-point).
MIN_PROGRESS = 0.10

# Geometric-pin thresholds, mirrored from move_highway.h (qu) so the offline pin uses the same
# tolerances the live gate engaged on. AMBIGUOUS = the two nearest base highways are within R_ON of
# each other in mean distance (the bot hugged neither cleanly). OFF_ALL = even the nearest base
# highway is beyond R_OFF on average (the bot likely drove no base highway -> low confidence).
PIN_AMBIGUOUS_MARGIN_QU = 48.0          # == MHW_R_ON
PIN_OFF_ALL_QU = 96.0                   # == MHW_R_OFF

# Cross-bot isolation (#428 shape-A: N bots in ONE server). Two bots whose QW player HULLS overlap
# DURING the overlap of their engaged windows bumped -- a physics block that perturbs the scored path
# WITHOUT disengaging the highway gate (which would silently corrupt the MSE) -> fail-closed
# `player_contact` (invalidate both). Collision is HULL-based, NOT a centre-sphere distance (two bots
# block on a ramp/stairs with vertically-separated origins): the QW player hull is +-16 qu in x,y and
# spans z in [-24, +32], so two equal hulls' AABBs overlap iff |dx| < 32 AND |dy| < 32 AND |dz| < 56.
PLAYER_HULL_HALF = (32.0, 32.0, 56.0)   # per-axis (|dx|,|dy|,|dz|) hull-overlap bounds (progs hull sums)

DEFAULT_CANON = REPO_ROOT / "data" / "catalog" / "route_canon.dm3.json"
DEFAULT_LEDGER = REPO_ROOT / "lab" / "dashboard" / "public" / "data" / "bot-attempts.json"
DEFAULT_DEMOS_DIR = Path("/home/ubuntu/nquakesv/ktx/demos")
DEFAULT_QW_ANALYZE = os.environ.get("QW_ANALYZE_BIN", "/home/ubuntu/qw-sim/bin/qw-analyze-v20")

_NOTE = (
    "adherence MSE = route-SHAPE proxy vs the ONE #420 seed (speed-blind); NOT the velocity "
    "objective (use velocity.*) and NOT a #421-band believability judgment. highway.id is pinned "
    "GEOMETRICALLY (nearest base polyline in xy), NEVER by (from,to) and NOT from the engine log "
    "(which carries no id). #427 reward sources speed from velocity.mean_speed_qu_s. "
    "A VALID run has exactly ONE engaged span: engaged_window_s = a single contiguous [t0,t1] mapped "
    "from the [moveprobe-live] total-frame counter onto the trajectory clock (each handoff anchored to "
    "the FOLLOWING live counter, the engage/disengage frame; anchored fraction; PR1 approximation). "
    "Rigorous sub-frame/variable-dt alignment is the deferred #428 item. A LARGE MSE is a PASS for the "
    "automation (quality is the RL job, #427). "
    "valid=false (+ invalid_reasons) means the run was NOT route-isolated -- no_engaged_spans / "
    "multi_span_engagement (the bot engaged >1x: a disengaged off-route gap would bridge "
    "velocity/arclen across spans, so PR1 fail-closes; per-span scoring is a deferred follow-up) / "
    "engaged_window_too_narrow / window_extraction_failed / player_contact (a cross-bot bump within "
    "the engaged window physics-contaminated the scored path -- multi-bot only) / no_player_bound. "
    "On invalid the consumable "
    "adherence/velocity/degenerate are NULL and ONLY non_isolated_debug carries (non-consumable) "
    "full-trajectory numbers -- never read those as a score."
)

# Log-line shapes, mirrored from evaluate_live_freshness (run_4v4_validation_lab.py:444-445) so the
# two parsers cannot drift on the same screen.log surface.
_HANDOFF_RE = re.compile(r"\[moveprobe-handoff\] slot (\d+) (ENGAGED|DISENGAGED)\b")
_LIVE_RE = re.compile(r"\[moveprobe-live\] slot (\d+) (LIVE|FALLBACK)\b")
_CUM_RE = re.compile(r"\blive=(\d+)/(\d+)\b")


# =============================================================================
# 1. parse_engaged_window — the ENGAGED span(s) from screen.log (frame-counter space)
# =============================================================================
def parse_engaged_window(screen_log_text: str, slot: int) -> dict:
    """The slot's ENGAGED span(s) from the `[moveprobe-handoff] slot N ENGAGED|DISENGAGED`
    transitions, expressed in the per-slot cumulative total-FRAME counter the interleaved
    `[moveprobe-live] slot N ... live=L/T` lines carry (the handoff line itself has no clock/id).

    ANCHOR (gate P1-a): KTX emits the `[moveprobe-handoff]` line BEFORE the same-frame
    `[moveprobe-live] live=L/T` line, so each transition is anchored to the FOLLOWING (next) live
    counter for the slot, NOT the previous one. Anchoring to the previous counter would grab the prior
    (fallback) frame and shift the span by one live line. Deferred-anchor walk: a handoff line is held
    PENDING and assigned the frame of the next live counter that appears; trailing pending transitions
    (no following live) anchor to the last counter seen (end-of-log). A span opens on ENGAGED and
    closes on the next DISENGAGED (or end-of-log). Raises SystemExit if the slot never ENGAGED (logging
    off, the highway-gate cvar unset, or the bot reached no base highway) -- a clear, actionable error.
    """
    slot = int(slot)
    last_total = None
    overall_total = 0
    transitions: list[tuple[str, int]] = []        # resolved (state, frame), in order
    pending: list[str] = []                         # handoff states awaiting the NEXT live counter
    saw_engaged = False
    for line in screen_log_text.splitlines():
        m_live = _LIVE_RE.search(line)
        if m_live and int(m_live.group(1)) == slot:
            m_cum = _CUM_RE.search(line)
            if m_cum:
                last_total = int(m_cum.group(2))
                overall_total = max(overall_total, last_total)
                for st in pending:                  # the following live counter IS each transition's frame
                    transitions.append((st, last_total))
                pending = []
            continue
        m_h = _HANDOFF_RE.search(line)
        if not (m_h and int(m_h.group(1)) == slot):
            continue
        if m_h.group(2) == "ENGAGED":
            saw_engaged = True
        pending.append(m_h.group(2))
    for st in pending:                              # trailing transitions -> the last counter (end-of-log)
        transitions.append((st, last_total if last_total is not None else 0))
    if not saw_engaged:
        raise SystemExit(
            f"parse_engaged_window: slot {slot} never ENGAGED in screen.log "
            "(was the highway-gate cvar set + k_fb_moveprobe_live_log on, and did the bot reach a "
            "base highway?). See experiments/ktx_moveprobe/T5.2_ROUTE_EVAL.md.")

    spans: list[list[int]] = []
    cur_start = None
    for st, frame in transitions:
        if st == "ENGAGED":
            if cur_start is None:
                cur_start = frame
        elif cur_start is not None:                 # DISENGAGED closes an open span
            spans.append([cur_start, frame])
            cur_start = None
    if cur_start is not None:                        # ran off the end still engaged
        spans.append([cur_start, last_total if last_total is not None else cur_start])
    engaged_frames = sum(max(0, b - a) for a, b in spans)
    return {
        "slot": slot,
        "spans_frames": spans,
        "n_engaged_spans": len(spans),
        "engaged_frames": engaged_frames,
        "total_frames": overall_total,
        "engaged_fraction": round(engaged_frames / overall_total, 4) if overall_total else None,
    }


# =============================================================================
# 2. extract_attempt_trajectory — the bot's per-tick [t,x,y,z] (qu), seed-symmetric decode
# =============================================================================
def _pick_mover(players: list) -> str:
    """The player with the longest (x,y) path -- the bot in a 1-bot prewar run (the spectator shim
    does not move). Used when no --player is given."""
    best, best_len = None, -1.0
    for P in players:
        ticks = player_ticks(P)
        plen = sum(math.hypot(ticks[i]["x"] - ticks[i - 1]["x"], ticks[i]["y"] - ticks[i - 1]["y"])
                   for i in range(1, len(ticks)))
        if plen > best_len:
            best, best_len = P, plen
    if best is None:
        raise SystemExit("extract_attempt_trajectory: no players in streams")
    return best["name"]


def extract_attempt_trajectory(analysis_json: dict, player, window=None) -> list:
    """The bot player's `[[t,x,y,z], ...]` in QUAKE UNITS (t in seconds), window-clipped.

    Reuses route_legs.player_ticks + pov_fuse_extract._find_player -- the SAME decode that built the
    #420 seed lines (build_route_canon.py) -- so the attempt is in qu exactly like the seed (unit
    symmetry). `player=None` auto-picks the most-moving player. `window=(t0,t1)` clips inclusively to
    that single CONTIGUOUS interval (a valid run has exactly one ENGAGED span -- multi-span is rejected
    upstream, so there is no gap to bridge). Raises SystemExit on an unknown player or < 2 ticks."""
    players = (analysis_json.get("streams") or {}).get("players")
    if not players:
        raise SystemExit("extract_attempt_trajectory: analysis JSON has no streams.players")
    name = _pick_mover(players) if player is None else player
    P = _find_player(players, name)                   # raises SystemExit if the name is unknown
    rows = [[round(tk["t"], 3), round(tk["x"], 1), round(tk["y"], 1), round(tk["z"], 1)]
            for tk in player_ticks(P)]
    if window is not None:
        t0, t1 = window
        rows = [r for r in rows if t0 <= r[0] <= t1]
    if len(rows) < 2:
        raise SystemExit(f"extract_attempt_trajectory: < 2 ticks for {name!r}"
                         + (f" in window {window}" if window else ""))
    return rows


# =============================================================================
# 2b. seeds + slot->player binding (#428 shape-A multi-bot: N bots in ONE server)
# =============================================================================
def base_highway_seeds(canon: dict, n_bots: int) -> list:
    """The first `n_bots` route_class=='base' highways (in canon file order) as
    `(slot, highway_id, (x, y, z))` seeds: the harness spawn-snaps bot k (slot k, engine edict k+1) to
    base[k-1]'s 3-D `start_xyz`. start_xyz is read from the JSON canon (the generated 2-D
    route_canon_dm3.h is NOT the seed source -- it has no z). Raises if `n_bots` exceeds the base
    count (PR2 assigns one distinct base highway per bot; there are 4)."""
    base = [h for h in canon.get("highways", []) if h.get("route_class") == "base"]
    if n_bots > len(base):
        raise ValueError(f"base_highway_seeds: {n_bots} bots but only {len(base)} base highways")
    out = []
    for k, h in enumerate(base[:n_bots], start=1):
        xyz = h.get("start_xyz") or h["segments"][0]["trajectory"][0][1:4]
        out.append((k, h["id"], (float(xyz[0]), float(xyz[1]), float(xyz[2]))))
    return out


def base_highway_end_markers(canon: dict) -> dict:
    """`{highway_id: end_marker}` for `route_class=='base'` highways carrying an optional
    `end_marker` -- a 1-based live FBMARKER index at the highway END (the Commander goal the
    INTENT-FIRST handoff gate needs to latch the route). READ-ONLY here: absent on every base
    highway today (the index is not derivable offline -- it needs a live MATCHLESS FBMARKER dump),
    so this returns `{}` and a directed `--score` run fail-louds. Populated by the #428 follow-up at
    the generator SOURCE (`data/catalog/route_canon_marks.dm3.json`) + regen -- the generated canon
    is NEVER hand-edited. The map drives live GOAL INTENT only; pin_driven_highway still scores by
    the highway actually driven, so the score stays honest regardless. RAISES ValueError if a present
    `end_marker` is not a POSITIVE 1-based int -- 0 / negative / non-int is rejected, because
    `fixed_goal 0` is an engine no-op (perslot.patch: "0 leaves fixed_goal alone") = un-directed,
    the exact silent-evidence risk this contract guards against."""
    out = {}
    for h in canon.get("highways", []):
        if h.get("route_class") != "base":
            continue
        marker = h.get("end_marker")
        if marker is None:
            continue
        if not isinstance(marker, int) or isinstance(marker, bool) or marker < 1:
            raise ValueError(
                f"base_highway_end_markers: highway {h['id']!r} has invalid end_marker {marker!r} "
                f"-- must be a positive 1-based live FBMARKER index (>= 1); 0/negative/non-int is "
                f"rejected (fixed_goal 0 is a no-op = un-directed)")
        out[h["id"]] = marker
    return out


def _player_min_dist_to_point(P, pt) -> float:
    """Min 3-D distance (qu) from a player's whole trajectory to a point -- the closest approach a bot
    made to a seed coordinate."""
    best = float("inf")
    for tk in player_ticks(P):
        d = math.dist((tk["x"], tk["y"], tk["z"]), pt)
        if d < best:
            best = d
    return best


def bind_players_to_seeds(analysis_json: dict, seeds, *, exclude_players=()) -> dict:
    """Bind each seeded slot to the DISTINCT player whose trajectory passes nearest that slot's
    spawn-snap coordinate. KTX `addbot` names bots randomly (NOT per-slot), so the binding is purely
    geometric: with each bot spawn-snapped to a far-apart base-highway start, closest-approach
    uniquely identifies it (the 4 dm3 base starts are >=270 qu apart). Greedy by smallest distance,
    each player used at most ONCE (uniqueness -- two slots never bind the same player). The non-moving
    spectator shim is excluded by name (`exclude_players`); excluding by movement is impossible because
    the frozen mover stalls too. `seeds = [(slot, (x, y, z)), ...]`. Returns `{slot: player_name|None}`
    (None when fewer players than seeds)."""
    excl = set(exclude_players)
    players = [P for P in ((analysis_json.get("streams") or {}).get("players") or [])
               if P.get("name") not in excl]
    triples = [(_player_min_dist_to_point(P, tuple(pt)), slot, P["name"])
               for slot, pt in seeds for P in players]
    triples.sort(key=lambda t: t[0])
    bound, used_slots, used_names = {}, set(), set()
    for _d, slot, name in triples:
        if slot in used_slots or name in used_names:
            continue
        bound[slot] = name
        used_slots.add(slot)
        used_names.add(name)
    for slot, _pt in seeds:
        bound.setdefault(slot, None)
    return bound


# =============================================================================
# 3. pin_driven_highway — the GEOMETRIC pin (mirror of mhw_nearest_base_highway, in Python)
# =============================================================================
def _seg_dist2(px, py, ax, ay, bx, by) -> float:
    """Squared (x,y) distance from point (px,py) to segment [(ax,ay),(bx,by)] -- mirror of
    move_highway.c:mhw_seg_dist2."""
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    if l2 <= 0.0:                                     # degenerate segment -> point
        return (px - ax) ** 2 + (py - ay) ** 2
    t = ((px - ax) * dx + (py - ay) * dy) / l2
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    cx, cy = ax + t * dx, ay + t * dy
    return (px - cx) ** 2 + (py - cy) ** 2


def _point_to_polyline_qu(px, py, poly) -> float:
    """Min Euclidean (x,y) distance (qu) from a point to a polyline (point-to-segment over every
    segment) -- mirror of move_highway.c:mhw_line_dist2, returned un-squared (qu)."""
    if not poly:
        return float("inf")
    if len(poly) == 1:
        return math.hypot(px - poly[0][0], py - poly[0][1])
    best = float("inf")
    for i in range(len(poly) - 1):
        d2 = _seg_dist2(px, py, poly[i][0], poly[i][1], poly[i + 1][0], poly[i + 1][1])
        if d2 < best:
            best = d2
    return math.sqrt(best)


def _mean_dist_to_polyline(attempt_xy, poly) -> float:
    """Mean over the attempt points of the point-to-polyline distance (qu) -- the whole-trajectory
    extension of the C single-point primitive (the C gate asks per-frame; the pin asks which highway
    the WHOLE path hugged)."""
    if not attempt_xy:
        return float("inf")
    return sum(_point_to_polyline_qu(x, y, poly) for x, y in attempt_xy) / len(attempt_xy)


def _attempt_rows(attempt, window=None) -> list:
    """Normalise an attempt to [[t,x,y,z], ...]; accept bare [x,y,z] (t := index). Clip by a single
    (t0,t1) window (seconds) when the rows carry t."""
    rows = []
    for i, p in enumerate(attempt):
        if len(p) >= 4:
            rows.append([float(p[0]), float(p[1]), float(p[2]), float(p[3])])
        elif len(p) == 3:
            rows.append([float(i), float(p[0]), float(p[1]), float(p[2])])
        else:
            raise SystemExit(f"pin_driven_highway: attempt row must be [t,x,y,z] or [x,y,z], got {p!r}")
    if window is not None:
        t0, t1 = window
        rows = [r for r in rows if t0 <= r[0] <= t1]
    return rows


def pin_driven_highway(canon: dict, attempt, window=None) -> dict:
    """Pin the base highway the bot drove by GEOMETRY: over the `route_class=='base'` highways (in
    canon file order), the one with the smallest mean point-to-polyline (xy) distance to the attempt
    path. Returns the nearest highway's id + the margin to the runner-up + an `ambiguous` flag +
    `off_all_highways` (the nearest is still beyond R_OFF on average -> low confidence, WARN). Mirrors
    move_highway.c:mhw_nearest_base_highway; reuses score_route_mse.load_highway_seed for each base
    seed (so the pin geometry == the scored seed, in qu). NEVER reads a (from,to) pair or a log id.
    """
    rows = _attempt_rows(attempt, window)
    if not rows:
        raise SystemExit("pin_driven_highway: no attempt points (after window clip)")
    attempt_xy = [(r[1], r[2]) for r in rows]

    base = [h for h in canon.get("highways", []) if h.get("route_class") == "base"]
    if not base:
        raise SystemExit("pin_driven_highway: no route_class=='base' highways in the canon")

    scored = []
    for h in base:
        seed_xyz, _meta = score_route_mse.load_highway_seed(canon, h["id"])
        poly = [(p[0], p[1]) for p in seed_xyz]
        scored.append((h["id"], _mean_dist_to_polyline(attempt_xy, poly)))
    scored.sort(key=lambda kv: kv[1])

    best_id, best_d = scored[0]
    runner_d = scored[1][1] if len(scored) > 1 else float("inf")
    margin = runner_d - best_d
    ambiguous = margin < PIN_AMBIGUOUS_MARGIN_QU
    off_all = best_d > PIN_OFF_ALL_QU
    if off_all:
        LOGGER.warning("pin: nearest base highway %s is %.1f qu off on average (> R_OFF=%.0f) -> "
                       "low confidence; the bot may have driven no base highway", best_id, best_d,
                       PIN_OFF_ALL_QU)
    if ambiguous:
        runner_id = scored[1][0] if len(scored) > 1 else "n/a"
        LOGGER.warning("pin: AMBIGUOUS -- %s (%.1f qu) vs runner-up %s (%.1f qu) within R_ON=%.0f qu",
                       best_id, best_d, runner_id, runner_d, PIN_AMBIGUOUS_MARGIN_QU)
    return {
        "id": best_id,
        "pin": "nearest-base-polyline (geometric)",
        "mean_dist_qu": round(best_d, 1),
        "pin_margin_qu": (round(margin, 1) if margin != float("inf") else None),
        "ambiguous": bool(ambiguous),
        "off_all_highways": bool(off_all),
        "ranked_mean_dist_qu": [[hid, round(d, 1)] for hid, d in scored],
    }


# =============================================================================
# 4. velocity + frame->time helpers
# =============================================================================
def _cum_arclen_3d(rows) -> float:
    """Cumulative 3-D path length over [t,x,y,z] rows (qu)."""
    return sum(math.sqrt((rows[i][1] - rows[i - 1][1]) ** 2 + (rows[i][2] - rows[i - 1][2]) ** 2
                         + (rows[i][3] - rows[i - 1][3]) ** 2) for i in range(1, len(rows)))


def compute_velocity(attempt_rows, seed_xyz) -> dict:
    """The explicit VELOCITY scalar (the Phase-2 signal, #415/#427) + progress fraction. duration =
    last-first t; path_len = 3-D arclen; mean_speed = path_len/duration; progress = attempt arclen /
    seed arclen (the degenerate-progress guard's input)."""
    duration_s = attempt_rows[-1][0] - attempt_rows[0][0]
    path_len = _cum_arclen_3d(attempt_rows)
    seed_len = sum(math.dist(seed_xyz[i - 1], seed_xyz[i]) for i in range(1, len(seed_xyz)))
    return {
        "duration_s": round(duration_s, 3),
        "path_len_qu": round(path_len, 1),
        "mean_speed_qu_s": round(path_len / duration_s, 1) if duration_s > 0 else 0.0,
        "progress_fraction": round(path_len / seed_len, 4) if seed_len > 0 else 0.0,
    }


def _span_to_time_window(span_frames, total_frames, full_rows):
    """Map ONE engaged FRAME-counter span [a,b] onto the trajectory's own SECONDS clock -> (t0,t1).

    Only the single-span case is scored (multi-span runs are rejected upstream as
    `multi_span_engagement`, so there is never a disengaged gap inside a scored window -- no phantom
    arclen/velocity bridge across a gap; gate P1-b). PR1 approximation: the screen.log handoff line has
    no clock, only the interleaved [moveprobe-live] total-frame counter, so [a,b] is anchored by
    FRACTION of total_frames onto the recorded [t_first, t_last] span (no absolute offset / fixed dt
    needed); rigorous sub-frame alignment is the deferred #428 item. Returns (t0,t1), or None when the
    span is degenerate / unmappable (-> the caller marks `engaged_window_too_narrow`).
    """
    if not span_frames or not total_frames or len(full_rows) < 2:
        return None
    t_first, t_last = full_rows[0][0], full_rows[-1][0]
    if t_last <= t_first:
        return None

    def t_of(f):
        frac = max(0.0, min(1.0, f / total_frames))
        return t_first + frac * (t_last - t_first)

    a, b = span_frames
    t0, t1 = t_of(a), t_of(b)
    return (t0, t1) if t1 > t0 else None


def _seed_ts(canon, highway_id):
    """The seed's t column (seconds) for the time grid -- mirrors score_route_mse.main."""
    return [float(p[0]) for h in canon["highways"] if h["id"] == highway_id
            for seg in h["segments"] for p in seg["trajectory"]]


# =============================================================================
# 4b. cross-bot player_contact — the fail-closed multi-bot isolation guard (#428 shape-A)
# =============================================================================
def _interp_xyz(ts, rows, t):
    """Linear-interpolate [x,y,z] at time t over [t,x,y,z] `rows` (`ts` = their t column), clamped to
    the ends. Lets two bots be compared at the SAME demo instant (one recording -> one shared clock)."""
    i = bisect.bisect_left(ts, t)
    if i <= 0:
        return rows[0][1:4]
    if i >= len(rows):
        return rows[-1][1:4]
    t0, t1 = ts[i - 1], ts[i]
    a, b = rows[i - 1], rows[i]
    if t1 <= t0:
        return a[1:4]
    f = (t - t0) / (t1 - t0)
    return [a[1] + f * (b[1] - a[1]), a[2] + f * (b[2] - a[2]), a[3] + f * (b[3] - a[3])]


def _axis_overlap_interval(a0, a1, h):
    """The s-subinterval of [0,1] where the relative coord `a0 + (a1-a0)*s` stays within +-h (one axis
    of the hull-overlap box) as the bots move linearly; None if it never does."""
    da = a1 - a0
    if abs(da) < 1e-9:                                     # no relative motion on this axis
        return (0.0, 1.0) if abs(a0) < h else None
    s0, s1 = (-h - a0) / da, (h - a0) / da
    if s0 > s1:
        s0, s1 = s1, s0
    lo, hi = max(0.0, s0), min(1.0, s1)
    return (lo, hi) if lo <= hi else None


def _segment_hull_overlap(pa0, pa1, pb0, pb1):
    """True iff the two players' HULLS overlap at ANY instant as each moves linearly p*0 -> p*1 over a
    shared s in [0,1] (a continuous swept AABB-vs-AABB test -- a fast pass-through BETWEEN samples
    cannot slip through). Contact iff the three per-axis hull-overlap s-intervals intersect."""
    lo, hi = 0.0, 1.0
    for ax, h in enumerate(PLAYER_HULL_HALF):
        iv = _axis_overlap_interval(pa0[ax] - pb0[ax], pa1[ax] - pb1[ax], h)
        if iv is None:
            return False
        lo, hi = max(lo, iv[0]), min(hi, iv[1])
        if lo > hi:
            return False
    return True


def _segment_min_dist(pa0, pa1, pb0, pb1):
    """(min Euclidean distance, s*) between the two players as each moves linearly over s in [0,1] --
    for the contact-evidence detail only (the DECISION is the hull-overlap test, not this scalar)."""
    r0 = [pa0[k] - pb0[k] for k in range(3)]
    dr = [(pa1[k] - pb1[k]) - r0[k] for k in range(3)]
    a = sum(d * d for d in dr)
    s = 0.0 if a < 1e-12 else max(0.0, min(1.0, -sum(r0[k] * dr[k] for k in range(3)) / a))
    r = [r0[k] + s * dr[k] for k in range(3)]
    return math.sqrt(sum(v * v for v in r)), s


def _pair_hull_contact(rows_a, rows_b, lo, hi):
    """(hit, min_dist_qu, t_s) for two bots over the window [lo,hi]: the swept hull-overlap test over
    the union of their RECORDED tick times within the window (full [[t,x,y,z],...] rows, interpolated).
    `hit` is the hull-overlap decision; `min_dist` is the L2 closest approach (evidence detail only)."""
    ts_a = [r[0] for r in rows_a]
    ts_b = [r[0] for r in rows_b]
    times = sorted({lo, hi} | {t for t in ts_a if lo <= t <= hi} | {t for t in ts_b if lo <= t <= hi})
    hit, min_d, min_t = False, float("inf"), lo
    for k in range(len(times) - 1):
        t0, t1 = times[k], times[k + 1]
        pa0, pa1 = _interp_xyz(ts_a, rows_a, t0), _interp_xyz(ts_a, rows_a, t1)
        pb0, pb1 = _interp_xyz(ts_b, rows_b, t0), _interp_xyz(ts_b, rows_b, t1)
        d, s = _segment_min_dist(pa0, pa1, pb0, pb1)
        if d < min_d:
            min_d, min_t = d, t0 + s * (t1 - t0)
        if _segment_hull_overlap(pa0, pa1, pb0, pb1):
            hit = True
    return hit, min_d, min_t


def detect_player_contact(tracks) -> dict:
    """Cross-bot fail-closed isolation check (#428 shape-A). A VALID bot's scored window is contaminated
    if ANY OTHER bound bot's player HULL overlaps it during that window -- a physics block perturbs the
    scored path without disengaging the gate, silently corrupting the MSE -> the valid bot is demoted
    (`player_contact`, no consumable score).

    Checks every VALID bot against ALL other bound bots -- INCLUDING invalid-but-bound ones (a bot that
    never engaged / multi-span / etc. still has a body that can block a valid bot; an invalid bot has no
    consumable score so it is never itself demoted, but it CAN contaminate a valid one -- gate fix,
    Codex P1 round 2). Contact is HULL-based + CONTINUOUS: the per-axis AABB overlap of the QW player
    hulls (`PLAYER_HULL_HALF` -- NOT a centre-sphere distance; bots block on ramps/stairs with
    vertically-separated origins), swept over each linear sub-interval between the bots' RECORDED tick
    times within the VALID bot's window (a fast pass-through between samples can't slip through).
    `tracks = [{slot, player, valid, window_s, rows(full)}, ...]` for ALL bound bots. Returns
    `{slot: [{slot, min_dist_qu, t_s, partner_valid}, ...]}` for contaminated VALID slots."""
    contacts: dict = {}
    for v in tracks:
        if not v.get("valid") or not v.get("window_s"):
            continue
        lo, hi = v["window_s"]
        if hi <= lo:
            continue
        for o in tracks:
            if o["slot"] == v["slot"]:
                continue
            # clip to O's RECORDED time extent -- O only physically existed where it was recorded;
            # never fabricate a position by clamping outside it (else a bot recorded elsewhere would
            # phantom-block during V's window).
            clo, chi = max(lo, o["rows"][0][0]), min(hi, o["rows"][-1][0])
            if chi <= clo:
                continue
            hit, min_d, min_t = _pair_hull_contact(v["rows"], o["rows"], clo, chi)
            if hit:
                contacts.setdefault(v["slot"], []).append(
                    {"slot": o["slot"], "min_dist_qu": round(min_d, 1), "t_s": round(min_t, 3),
                     "partner_valid": bool(o.get("valid"))})
    return contacts


def _demote_to_player_contact(art: dict, partners: list) -> dict:
    """Demote a VALID artifact to invalid:`player_contact` -- a cross-bot bump within the engaged
    window contaminated the scored trajectory (fail-closed: a physics block is not a movement score).
    The windowed numbers move to `non_isolated_debug` (non-consumable); the consumables go NULL, same
    invariant as every other invalid path."""
    pinned_id = (art.get("highway") or {}).get("id")
    art["valid"] = False
    if "player_contact" not in art["invalid_reasons"]:
        art["invalid_reasons"].append("player_contact")
    art["non_isolated_debug"] = {
        "_warning": ("player_contact: within the player bbox of another bot DURING the engaged window "
                     "-> the scored trajectory is physics-contaminated, NOT a valid route score; do "
                     "NOT consume these numbers."),
        "contact_partners": partners,
        "highway_id": pinned_id,
        "adherence": art.get("adherence"), "velocity": art.get("velocity"),
        "degenerate": art.get("degenerate"),
    }
    art["highway"]["id"] = None
    art["adherence"] = None
    art["velocity"] = None
    art["degenerate"] = None
    return art


# =============================================================================
# 5. evaluate_analysis — the pure assembly (the CI-tested core)
# =============================================================================
def _score_rows(canon, rows, grid, map_name):
    """Geometric pin + adherence-MSE + velocity + degenerate over `rows` ([t,x,y,z]). Shared by the
    VALID (windowed) path and the INVALID `non_isolated_debug` (full-trajectory) path."""
    pin = pin_driven_highway(canon, rows)
    seed_xyz, seed_meta = score_route_mse.load_highway_seed(canon, pin["id"])
    adherence = score_route_mse.build_artifact(
        pin["id"], seed_xyz, seed_meta, [(r[1], r[2], r[3]) for r in rows], "route_eval", grid,
        _seed_ts(canon, pin["id"]), [r[0] for r in rows], map_name=map_name)
    velocity = compute_velocity(rows, seed_xyz)
    return {
        "pin": pin,
        "adherence": {k: adherence[k] for k in
                      ("mse_xyz", "rmse_xyz", "rmse_xy", "rmse_z", "per_axis_mse", "grid")},
        "velocity": velocity,
        "degenerate": bool(velocity["progress_fraction"] < MIN_PROGRESS),
    }


def evaluate_analysis(canon, analysis_json, *, player, slot, screen_log_text, map_name="dm3",
                      grid="arclen", demo=None, freshness=None, run_id=None, ts_utc=None) -> dict:
    """Assemble the `komodobots.route_eval.v1` artifact from already-decoded inputs (no I/O, no
    subprocess) -- the unit-tested core.

    ROUTE-ISOLATION IS LOAD-BEARING (#428). A run is INVALID (NOT route-isolated) when the engaged
    window is missing (`no_engaged_spans`), the bot engaged MORE THAN ONCE (`multi_span_engagement` --
    a disengaged off-route gap would otherwise bridge the velocity/arclen across spans; fail-closed,
    gate P1-b), the single window is too narrow (`engaged_window_too_narrow`), or extraction fails
    (`window_extraction_failed`). Invalid -> `valid: false` + `invalid_reasons`, the consumable
    `adherence`/`velocity`/`degenerate` are NULL, and the full-trajectory numbers are quarantined in
    `non_isolated_debug` (never consumable). A VALID run has exactly ONE engaged span -> a single
    CONTIGUOUS window -> extract -> geometric-pin -> adherence-MSE -> velocity -> degenerate guard.
    (`degenerate` is movement quality and is orthogonal to `valid`/isolation.)"""
    invalid_reasons: list[str] = []
    try:
        eng = parse_engaged_window(screen_log_text, slot)
    except SystemExit as exc:
        LOGGER.warning("%s", exc)
        eng = {"slot": slot, "spans_frames": [], "n_engaged_spans": 0, "engaged_frames": 0,
               "total_frames": 0, "engaged_fraction": None}
        invalid_reasons.append("no_engaged_spans")

    full_rows = extract_attempt_trajectory(analysis_json, player, window=None)

    window_s = None               # the single CONTIGUOUS (t0,t1) engaged window (valid path only)
    attempt_rows = None
    if not invalid_reasons and eng["n_engaged_spans"] > 1:
        # Fail-closed: per-span scoring is a deferred follow-up; until then a multi-span run is INVALID
        # rather than bridging the disengaged gap in velocity/adherence (gate P1-b).
        LOGGER.warning("route_eval: %d engaged spans %s -> INVALID (multi_span_engagement); per-span "
                       "scoring is deferred", eng["n_engaged_spans"], eng["spans_frames"])
        invalid_reasons.append("multi_span_engagement")
    elif not invalid_reasons:
        window_s = _span_to_time_window(eng["spans_frames"][0], eng["total_frames"], full_rows)
        if not window_s:
            LOGGER.warning("route_eval: engaged span %s maps to no usable window -> INVALID "
                           "(not route-isolated)", eng["spans_frames"])
            invalid_reasons.append("engaged_window_too_narrow")
        else:
            try:
                attempt_rows = extract_attempt_trajectory(analysis_json, player, window=window_s)
            except SystemExit as exc:
                LOGGER.warning("route_eval: %s -> INVALID (engaged window too narrow)", exc)
                invalid_reasons.append("engaged_window_too_narrow")
                window_s = None
            except Exception as exc:  # noqa: BLE001 — any other windowed-extract failure is invalid
                LOGGER.warning("route_eval: windowed extraction failed (%s) -> INVALID", exc)
                invalid_reasons.append("window_extraction_failed")
                window_s = None

    valid = not invalid_reasons
    art = {
        "schema": SCHEMA, "map": map_name, "run_id": run_id, "ts_utc": ts_utc,
        "valid": valid, "invalid_reasons": invalid_reasons,
        "highway": {            # isolation evidence is always present; the geometric PIN only on valid
            "id": None, "pin": "nearest-base-polyline (geometric)",
            "engaged_window_s": ([round(window_s[0], 3), round(window_s[1], 3)] if window_s else None),
            "engaged_fraction": eng["engaged_fraction"],
            "engaged_frames": eng["engaged_frames"], "total_frames": eng["total_frames"],
            "n_engaged_spans": eng["n_engaged_spans"],
            "pin_margin_qu": None, "ambiguous": None, "off_all_highways": None,
            "mean_dist_qu": None, "ranked_mean_dist_qu": None,
        },
        "adherence": None, "velocity": None, "degenerate": None,
        "freshness": freshness, "demo": demo, "_note": _NOTE,
    }

    if valid:
        s = _score_rows(canon, attempt_rows, grid, map_name)
        if s["degenerate"]:
            LOGGER.warning("route_eval: DEGENERATE -- progress_fraction %.3f < MIN_PROGRESS %.2f "
                           "(stalled run; adherence MSE is not meaningful)",
                           s["velocity"]["progress_fraction"], MIN_PROGRESS)
        art["highway"].update({
            "id": s["pin"]["id"], "pin": s["pin"]["pin"],
            "pin_margin_qu": s["pin"]["pin_margin_qu"], "ambiguous": s["pin"]["ambiguous"],
            "off_all_highways": s["pin"]["off_all_highways"], "mean_dist_qu": s["pin"]["mean_dist_qu"],
            "ranked_mean_dist_qu": s["pin"]["ranked_mean_dist_qu"],
        })
        art["adherence"] = s["adherence"]
        art["velocity"] = s["velocity"]
        art["degenerate"] = s["degenerate"]
    else:
        dbg = _score_rows(canon, full_rows, grid, map_name)   # NON-consumable: full-trajectory only
        art["non_isolated_debug"] = {
            "_warning": ("FULL-trajectory numbers, NOT route-isolated -- the engaged window was "
                         "missing/too narrow/unextractable (see invalid_reasons). These are NOT a "
                         "valid route_eval score; do NOT consume them as one."),
            "highway_id": dbg["pin"]["id"], "pin_margin_qu": dbg["pin"]["pin_margin_qu"],
            "ambiguous": dbg["pin"]["ambiguous"], "off_all_highways": dbg["pin"]["off_all_highways"],
            "adherence": dbg["adherence"], "velocity": dbg["velocity"], "degenerate": dbg["degenerate"],
        }

    return art


# =============================================================================
# 6. impure shell — qw-analyze subprocess, run-dir orchestration, ledger merge (NOT CI-tested)
# =============================================================================
def run_qw_analyze(mvd_path, qw_analyze_bin=DEFAULT_QW_ANALYZE) -> dict:
    """qw-analyze -view full -include positions,view,velocity <mvd> -> the per-tick JSON the seed
    builder consumes. The one impure shell-out; the PARSE/assembly is the tested pure core."""
    cmd = [str(qw_analyze_bin), "-view", "full", "-include", "positions,view,velocity", str(mvd_path)]
    LOGGER.info("qw-analyze: %s", " ".join(cmd))
    out = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def _find_run_mvd(run_dir: Path, demos_dir, run_id: str) -> Path:
    """Locate THIS run's .mvd: the demos dir (name embeds run_id) first, then the run dir."""
    cands = []
    if demos_dir:
        cands += list(Path(demos_dir).glob(f"*{run_id}*.mvd"))
    cands += list(run_dir.glob("*.mvd"))
    cands = [c for c in cands if c.exists() and c.stat().st_size > 0]
    if not cands:
        raise SystemExit(f"_find_run_mvd: no .mvd for run {run_id} (looked in {demos_dir} and {run_dir})")
    return max(cands, key=lambda c: c.stat().st_mtime)


def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _freshness_block(freshness):
    """The glanceable freshness summary for the artifact (ok / live_fraction / min_fraction)."""
    if not isinstance(freshness, dict):
        return None
    return {k: freshness.get(k) for k in ("ok", "min_fraction") if k in freshness} or None


def _ledger_block(artifact: dict, *, slot=None, player=None) -> dict:
    """One per-bot ledger block. ALWAYS carries the isolation-proof fields (`valid`,
    `invalid_reasons`, `n_engaged_spans`, `engaged_frames`, `engaged_fraction`); the consumable
    `highway_id`/`rmse_xyz`/`mean_speed_qu_s`/`degenerate` ONLY when `valid` -- an INVALID (not
    route-isolated / contaminated) eval lands NO consumable score, so a downstream reader can never
    mistake it for a real result (#428). `slot`/`player` identify the bot within a multi-bot
    `route_evals` array (single-bot run -> a 1-element array)."""
    hw = artifact.get("highway") or {}
    block = {
        "slot": slot, "player": player,
        "valid": artifact.get("valid"),
        "invalid_reasons": artifact.get("invalid_reasons", []),
        "n_engaged_spans": hw.get("n_engaged_spans"),
        "engaged_frames": hw.get("engaged_frames"),
        "engaged_fraction": hw.get("engaged_fraction"),
    }
    if artifact.get("valid"):
        block.update({
            "highway_id": hw.get("id"),
            "rmse_xyz": (artifact.get("adherence") or {}).get("rmse_xyz"),
            "mean_speed_qu_s": (artifact.get("velocity") or {}).get("mean_speed_qu_s"),
            "degenerate": artifact.get("degenerate"),
        })
    return block


def merge_route_evals_into_ledger(ledger_path: Path, run_id: str, blocks: list):
    """Merge N per-bot blocks onto that run's `komodobots.bot_attempts.v1` row as the additive nested
    `route_evals` array (the multi-bot shape; a single-bot run is a 1-element array). The row's
    required keys are untouched, so the dashboard gallery still reads it; no live consumer reads
    `route_evals` yet. A missing/unreadable ledger or a missing row WARNs + skips (never crashes the
    run). Returns the merged `blocks`, or None when not merged."""
    ledger_path = Path(ledger_path)
    if not ledger_path.exists():
        LOGGER.warning("ledger %s absent; score not merged", ledger_path)
        return None
    ledger = _load_json(ledger_path)
    attempts = ledger.get("attempts") if isinstance(ledger, dict) else None
    if not isinstance(attempts, list):
        LOGGER.warning("ledger %s has no attempts list; score not merged", ledger_path)
        return None
    for row in attempts:
        if row.get("run_id") == run_id:
            row["route_evals"] = blocks
            ledger_path.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n",
                                   encoding="utf-8")
            return blocks
    LOGGER.warning("no ledger row for run_id %s; route_evals not merged", run_id)
    return None


def merge_score_into_ledger(ledger_path: Path, run_id: str, artifact: dict, *, slot=1, player=None):
    """Single-bot convenience: merge ONE artifact as a 1-element `route_evals` array. Returns the
    per-bot block (back-compat), or None when no matching row. See _ledger_block /
    merge_route_evals_into_ledger."""
    block = _ledger_block(artifact, slot=slot, player=player)
    return block if merge_route_evals_into_ledger(ledger_path, run_id, [block]) is not None else None


def evaluate_run(run_dir, *, slot=1, player=None, canon_path=DEFAULT_CANON, map_name="dm3",
                 grid="arclen", qw_analyze_bin=DEFAULT_QW_ANALYZE, demos_dir=DEFAULT_DEMOS_DIR,
                 ledger_path=DEFAULT_LEDGER, write=True) -> dict:
    """Score a recorded prewar-movecheck run dir end-to-end: locate the .mvd, run qw-analyze, assemble
    the artifact, write route_eval.json into the run dir, and merge the score into the ledger row.
    run_id is the run-dir name (prewar_movecheck derives both from the same id)."""
    run_dir = Path(run_dir)
    screen_log = run_dir / "screen.log"
    if not screen_log.exists():
        raise SystemExit(f"evaluate_run: no screen.log in {run_dir}")
    screen_text = screen_log.read_text(encoding="utf-8", errors="replace")
    canon = json.loads(Path(canon_path).read_text(encoding="utf-8"))
    run_id = run_dir.name

    mvd = _find_run_mvd(run_dir, demos_dir, run_id)
    analysis = run_qw_analyze(mvd, qw_analyze_bin)
    demo_block = {"name": mvd.name, "url": f"/demos/online/{mvd.name}"}
    freshness = _freshness_block(_load_json(run_dir / "freshness.json"))

    artifact = evaluate_analysis(
        canon, analysis, player=player, slot=slot, screen_log_text=screen_text,
        map_name=map_name, grid=grid, demo=demo_block, freshness=freshness,
        run_id=run_id, ts_utc=datetime.now(timezone.utc).isoformat())

    if write:
        (run_dir / "route_eval.json").write_text(json.dumps(artifact, indent=1) + "\n",
                                                 encoding="utf-8")
        if ledger_path:
            merge_score_into_ledger(Path(ledger_path), run_id, artifact, slot=slot, player=player)
    return artifact


def _no_player_artifact(slot, screen_text, *, map_name, run_id, ts_utc, demo, freshness) -> dict:
    """A fail-closed INVALID artifact for a seeded slot that bound to NO player (binding
    under-supplied -- shouldn't happen with proper seeding, but never silently score). Mirrors the
    evaluate_analysis invalid skeleton; isolation evidence kept, consumables NULL."""
    try:
        eng = parse_engaged_window(screen_text, slot)
    except SystemExit:
        eng = {"engaged_fraction": None, "engaged_frames": 0, "total_frames": 0, "n_engaged_spans": 0}
    return {
        "schema": SCHEMA, "map": map_name, "run_id": run_id, "ts_utc": ts_utc,
        "valid": False, "invalid_reasons": ["no_player_bound"],
        "highway": {"id": None, "pin": "nearest-base-polyline (geometric)", "engaged_window_s": None,
                    "engaged_fraction": eng["engaged_fraction"], "engaged_frames": eng["engaged_frames"],
                    "total_frames": eng["total_frames"], "n_engaged_spans": eng["n_engaged_spans"],
                    "pin_margin_qu": None, "ambiguous": None, "off_all_highways": None,
                    "mean_dist_qu": None, "ranked_mean_dist_qu": None},
        "adherence": None, "velocity": None, "degenerate": None,
        "freshness": freshness, "demo": demo, "_note": _NOTE,
    }


def evaluate_run_multi(run_dir, *, seeds, spectator_name="KomodoPrewar", canon_path=DEFAULT_CANON,
                       map_name="dm3", grid="arclen", qw_analyze_bin=DEFAULT_QW_ANALYZE,
                       demos_dir=DEFAULT_DEMOS_DIR, ledger_path=DEFAULT_LEDGER, write=True) -> dict:
    """Score a MULTI-bot run end-to-end (#428 shape-A: N bots seeded onto N base highways in ONE
    server). qw-analyze ONCE; bind each seeded slot to its DISTINCT player by nearest-seed-coordinate
    (KTX names bots randomly); evaluate each slot independently; apply the cross-bot `player_contact`
    fail-closed invalidation; write `route_eval.s<N>.json` per slot and merge a `route_evals:[...]`
    array onto the ledger row. `seeds = [(slot, highway_id, (x, y, z)), ...]` (base_highway_seeds) --
    the spawn-snap starts the harness seeded each bot to. Returns
    `{run_id, route_evals, artifacts:{slot: artifact}}`."""
    run_dir = Path(run_dir)
    screen_log = run_dir / "screen.log"
    if not screen_log.exists():
        raise SystemExit(f"evaluate_run_multi: no screen.log in {run_dir}")
    screen_text = screen_log.read_text(encoding="utf-8", errors="replace")
    canon = json.loads(Path(canon_path).read_text(encoding="utf-8"))
    run_id = run_dir.name
    mvd = _find_run_mvd(run_dir, demos_dir, run_id)
    analysis = run_qw_analyze(mvd, qw_analyze_bin)
    demo_block = {"name": mvd.name, "url": f"/demos/online/{mvd.name}"}
    freshness = _freshness_block(_load_json(run_dir / "freshness.json"))
    ts_utc = datetime.now(timezone.utc).isoformat()

    bound = bind_players_to_seeds(analysis, [(s, xyz) for s, _hid, xyz in seeds],
                                  exclude_players=(spectator_name,))
    arts, tracks = {}, []
    for slot, _hid, _xyz in seeds:
        player = bound.get(slot)
        if player is None:
            LOGGER.warning("route_eval: slot %d bound to no player -> INVALID (no_player_bound)", slot)
            art = _no_player_artifact(slot, screen_text, map_name=map_name, run_id=run_id,
                                      ts_utc=ts_utc, demo=demo_block, freshness=freshness)
        else:
            art = evaluate_analysis(canon, analysis, player=player, slot=slot,
                                    screen_log_text=screen_text, map_name=map_name, grid=grid,
                                    demo=demo_block, freshness=freshness, run_id=run_id, ts_utc=ts_utc)
        arts[slot] = (player, art)
        # the contact check needs EVERY bound bot's FULL trajectory -- an invalid-but-bound bot can
        # still physically block a VALID bot during its scored window (Codex P1 round 2).
        if player is not None:
            try:
                full_rows = extract_attempt_trajectory(analysis, player, window=None)
            except SystemExit:
                full_rows = None
            if full_rows is not None:
                w = art["highway"]["engaged_window_s"] if art["valid"] else None
                tracks.append({"slot": slot, "player": player, "valid": bool(art["valid"]),
                               "window_s": (tuple(w) if w else None), "rows": full_rows})

    for slot, partners in detect_player_contact(tracks).items():
        LOGGER.warning("route_eval: slot %d player_contact %s -> INVALID (physics-contaminated)",
                       slot, partners)
        _demote_to_player_contact(arts[slot][1], partners)

    blocks = []
    for slot, _hid, _xyz in seeds:
        player, art = arts[slot]
        if write:
            (run_dir / f"route_eval.s{slot}.json").write_text(
                json.dumps(art, indent=1) + "\n", encoding="utf-8")
        blocks.append(_ledger_block(art, slot=slot, player=player))
    if write and ledger_path:
        merge_route_evals_into_ledger(Path(ledger_path), run_id, blocks)
    return {"run_id": run_id, "route_evals": blocks,
            "artifacts": {s: a for s, (_p, a) in arts.items()}}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="T5.2 (#428) route-isolated eval: geometric-pin + adherence-MSE + velocity scalar")
    ap.add_argument("run_dir", help="a prewar-movecheck run dir (screen.log + the recorded .mvd)")
    ap.add_argument("--slot", type=int, default=1, help="moveprobe slot to score (default 1)")
    ap.add_argument("--player", default=None,
                    help="bot player name from `status` (default: the most-moving player)")
    ap.add_argument("--canon", default=str(DEFAULT_CANON), help="route_canon.dm3.json")
    ap.add_argument("--grid", choices=("arclen", "time"), default="arclen",
                    help="arclen = path-shape (speed-blind, default); time = timing-sensitive")
    ap.add_argument("--qw-analyze", default=DEFAULT_QW_ANALYZE, help="qw-analyze binary")
    ap.add_argument("--demos-dir", default=str(DEFAULT_DEMOS_DIR), help="where the .mvd is recorded")
    ap.add_argument("--ledger", default=str(DEFAULT_LEDGER),
                    help="bot-attempts.json to merge the score into")
    ap.add_argument("--no-write", action="store_true",
                    help="print the artifact only; write neither route_eval.json nor the ledger")
    args = ap.parse_args(argv)

    artifact = evaluate_run(
        Path(args.run_dir), slot=args.slot, player=args.player, canon_path=args.canon,
        grid=args.grid, qw_analyze_bin=args.qw_analyze, demos_dir=args.demos_dir,
        ledger_path=(None if args.no_write else args.ledger), write=not args.no_write)

    url = (artifact.get("demo") or {}).get("url")
    if artifact["valid"]:
        h, v, a = artifact["highway"], artifact["velocity"], artifact["adherence"]
        summary = (f"{artifact['run_id']} VALID highway={h['id']} rmse_xyz={a['rmse_xyz']:.1f} "
                   f"speed={v['mean_speed_qu_s']:.1f}qu/s prog={v['progress_fraction']:.2f} "
                   f"degenerate={artifact['degenerate']}  watch={url}")
    else:
        summary = (f"{artifact['run_id']} INVALID ({', '.join(artifact['invalid_reasons'])}) -- NOT "
                   f"route-isolated; no consumable score (see non_isolated_debug)  watch={url}")
    LOGGER.info("route-eval: %s", summary)
    print(summary)
    return 0 if artifact["valid"] else 2


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    raise SystemExit(main())
