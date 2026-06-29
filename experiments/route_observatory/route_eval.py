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

DEFAULT_CANON = REPO_ROOT / "data" / "catalog" / "route_canon.dm3.json"
DEFAULT_LEDGER = REPO_ROOT / "lab" / "dashboard" / "public" / "data" / "bot-attempts.json"
DEFAULT_DEMOS_DIR = Path("/home/ubuntu/nquakesv/ktx/demos")
DEFAULT_QW_ANALYZE = os.environ.get("QW_ANALYZE_BIN", "/home/ubuntu/qw-sim/bin/qw-analyze-v20")

_NOTE = (
    "adherence MSE = route-SHAPE proxy vs the ONE #420 seed (speed-blind); NOT the velocity "
    "objective (use velocity.*) and NOT a #421-band believability judgment. highway.id is pinned "
    "GEOMETRICALLY (nearest base polyline in xy), NEVER by (from,to) and NOT from the engine log "
    "(which carries no id). #427 reward sources speed from velocity.mean_speed_qu_s. "
    "engaged_window_s is a LIST of [t0,t1] intervals (one per ENGAGED span) mapped from the "
    "[moveprobe-live] total-frame counter onto the trajectory clock (anchored fraction; PR1 "
    "approximation); the score is the UNION of those intervals, so a DISENGAGED gap between spans "
    "(bot off-route, re-engaged later) is EXCLUDED -- never scored as route-isolated. Rigorous "
    "sub-frame/variable-dt alignment is the deferred #428 item. A LARGE MSE is a PASS for the "
    "automation (quality is the RL job, #427). "
    "valid=false (+ invalid_reasons) means the run was NOT route-isolated (no / too-narrow / "
    "unextractable engaged window): its consumable adherence/velocity/degenerate are NULL and ONLY "
    "non_isolated_debug carries (non-consumable) full-trajectory numbers -- never read those as a score."
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

    Walks the log in order; a span opens at the latest total-frame counter seen for the slot when
    ENGAGED appears and closes at the latest counter when DISENGAGED appears (or at end-of-log if the
    run ends still engaged). Returns frame-counter spans + an engaged_fraction; the orchestrator maps
    frames -> the trajectory clock. Raises SystemExit if the slot never ENGAGED (logging off, the
    highway-gate cvar unset, or the bot reached no base highway) -- a clear, actionable error.
    """
    slot = int(slot)
    last_total = None
    overall_total = 0
    spans: list[list[int]] = []
    cur_start = None
    saw_engaged = False
    for line in screen_log_text.splitlines():
        m_live = _LIVE_RE.search(line)
        if m_live and int(m_live.group(1)) == slot:
            m_cum = _CUM_RE.search(line)
            if m_cum:
                last_total = int(m_cum.group(2))
                overall_total = max(overall_total, last_total)
            continue
        m_h = _HANDOFF_RE.search(line)
        if not (m_h and int(m_h.group(1)) == slot):
            continue
        anchor = last_total if last_total is not None else 0
        if m_h.group(2) == "ENGAGED":
            saw_engaged = True
            if cur_start is None:
                cur_start = anchor
        elif cur_start is not None:                        # DISENGAGED closes an open span
            spans.append([cur_start, anchor])
            cur_start = None
    if cur_start is not None:                              # ran off the end still engaged
        spans.append([cur_start, last_total if last_total is not None else cur_start])
    if not saw_engaged:
        raise SystemExit(
            f"parse_engaged_window: slot {slot} never ENGAGED in screen.log "
            "(was the highway-gate cvar set + k_fb_moveprobe_live_log on, and did the bot reach a "
            "base highway?). See experiments/ktx_moveprobe/T5.2_ROUTE_EVAL.md.")
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


def _norm_windows(window):
    """Normalise a window arg to a LIST of (t0,t1) seconds intervals. Accepts None, a single (t0,t1)
    pair, or a list of (t0,t1) pairs (the multi-ENGAGED-span UNION). The list form lets the windowed
    score EXCLUDE the disengaged gaps between ENGAGED spans (P1-1)."""
    if window is None:
        return None
    if len(window) == 2 and all(isinstance(v, (int, float)) for v in window):
        return [(float(window[0]), float(window[1]))]
    return [(float(a), float(b)) for (a, b) in window]


def _in_windows(t, windows):
    """True iff t falls inside ANY (t0,t1) interval (inclusive) -- the union membership test."""
    return any(t0 <= t <= t1 for (t0, t1) in windows)


def extract_attempt_trajectory(analysis_json: dict, player, window=None) -> list:
    """The bot player's `[[t,x,y,z], ...]` in QUAKE UNITS (t in seconds), window-clipped.

    Reuses route_legs.player_ticks + pov_fuse_extract._find_player -- the SAME decode that built the
    #420 seed lines (build_route_canon.py) -- so the attempt is in qu exactly like the seed (unit
    symmetry). `player=None` auto-picks the most-moving player. `window` is a single `(t0,t1)` pair OR
    a LIST of `(t0,t1)` intervals (the engaged-span UNION); a row survives iff its t is inside ANY
    interval, so the DISENGAGED gaps between spans are dropped (P1-1). Raises SystemExit on an unknown
    player or < 2 surviving ticks (a too-narrow union)."""
    players = (analysis_json.get("streams") or {}).get("players")
    if not players:
        raise SystemExit("extract_attempt_trajectory: analysis JSON has no streams.players")
    name = _pick_mover(players) if player is None else player
    P = _find_player(players, name)                   # raises SystemExit if the name is unknown
    rows = [[round(tk["t"], 3), round(tk["x"], 1), round(tk["y"], 1), round(tk["z"], 1)]
            for tk in player_ticks(P)]
    if window is not None:
        windows = _norm_windows(window)
        rows = [r for r in rows if _in_windows(r[0], windows)]
    if len(rows) < 2:
        raise SystemExit(f"extract_attempt_trajectory: < 2 ticks for {name!r}"
                         + (f" in window {window}" if window else ""))
    return rows


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
    """Normalise an attempt to [[t,x,y,z], ...]; accept bare [x,y,z] (t := index). Clip by window (a
    single (t0,t1) pair or a list of intervals -- union membership) when the rows carry t."""
    rows = []
    for i, p in enumerate(attempt):
        if len(p) >= 4:
            rows.append([float(p[0]), float(p[1]), float(p[2]), float(p[3])])
        elif len(p) == 3:
            rows.append([float(i), float(p[0]), float(p[1]), float(p[2])])
        else:
            raise SystemExit(f"pin_driven_highway: attempt row must be [t,x,y,z] or [x,y,z], got {p!r}")
    if window is not None:
        windows = _norm_windows(window)
        rows = [r for r in rows if _in_windows(r[0], windows)]
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


def _frames_to_time_windows(spans_frames, total_frames, full_rows):
    """Map EACH engaged FRAME-counter span onto the trajectory's own SECONDS clock, returning a LIST
    of (t0,t1) intervals -- ONE per ENGAGED span.

    The windowed score is the UNION of these intervals, so a DISENGAGED gap between two ENGAGED spans
    (the bot wandered off-route, re-engaged later) is EXCLUDED -- it can never enter a route-isolated
    score (P1-1). Collapsing spans into one [min,max] would swallow the gap; this does NOT.

    PR1 approximation (documented in _NOTE + the runbook): the screen.log handoff line has no clock,
    only the interleaved [moveprobe-live] total-frame counter. Anchoring each span's [a,b] by FRACTION
    of total_frames onto the recorded [t_first, t_last] span needs neither an absolute offset nor a
    fixed dt; precise sub-frame alignment is the deferred rigorous-dt item (#428). Degenerate (t1<=t0)
    spans are dropped. Returns the list of intervals, or None if none are usable.
    """
    if not spans_frames or not total_frames or len(full_rows) < 2:
        return None
    t_first, t_last = full_rows[0][0], full_rows[-1][0]
    if t_last <= t_first:
        return None

    def t_of(f):
        frac = max(0.0, min(1.0, f / total_frames))
        return t_first + frac * (t_last - t_first)

    intervals = [(t_of(a), t_of(b)) for (a, b) in spans_frames if t_of(b) > t_of(a)]
    return intervals or None


def _seed_ts(canon, highway_id):
    """The seed's t column (seconds) for the time grid -- mirrors score_route_mse.main."""
    return [float(p[0]) for h in canon["highways"] if h["id"] == highway_id
            for seg in h["segments"] for p in seg["trajectory"]]


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

    ROUTE-ISOLATION IS LOAD-BEARING (#428). If the engaged window is missing, too narrow, or
    unextractable, the run was NOT route-isolated -> the artifact is `valid: false` with
    `invalid_reasons`, the consumable `adherence`/`velocity`/`degenerate` are NULL, and the
    full-trajectory numbers are quarantined in `non_isolated_debug` (never consumable). A valid run
    scores the WINDOWED trajectory: window -> extract -> geometric-pin -> adherence-MSE -> velocity ->
    degenerate guard. (`degenerate` is movement quality and is orthogonal to `valid`/isolation.)"""
    invalid_reasons: list[str] = []
    try:
        eng = parse_engaged_window(screen_log_text, slot)
    except SystemExit as exc:
        LOGGER.warning("%s", exc)
        eng = {"slot": slot, "spans_frames": [], "n_engaged_spans": 0, "engaged_frames": 0,
               "total_frames": 0, "engaged_fraction": None}
        invalid_reasons.append("no_engaged_spans")

    full_rows = extract_attempt_trajectory(analysis_json, player, window=None)

    engaged_windows = None        # LIST of (t0,t1) intervals (the engaged-span UNION; gaps excluded)
    attempt_rows = None
    if not invalid_reasons:
        engaged_windows = _frames_to_time_windows(eng["spans_frames"], eng["total_frames"], full_rows)
        if not engaged_windows:
            LOGGER.warning("route_eval: engaged spans %s map to no usable window -> INVALID "
                           "(not route-isolated)", eng["spans_frames"])
            invalid_reasons.append("engaged_window_too_narrow")
        else:
            try:
                # UNION of the engaged intervals -> the disengaged gaps are dropped (P1-1)
                attempt_rows = extract_attempt_trajectory(analysis_json, player, window=engaged_windows)
            except SystemExit as exc:
                LOGGER.warning("route_eval: %s -> INVALID (engaged window too narrow)", exc)
                invalid_reasons.append("engaged_window_too_narrow")
                engaged_windows = None
            except Exception as exc:  # noqa: BLE001 — any other windowed-extract failure is invalid
                LOGGER.warning("route_eval: windowed extraction failed (%s) -> INVALID", exc)
                invalid_reasons.append("window_extraction_failed")
                engaged_windows = None

    valid = not invalid_reasons
    art = {
        "schema": SCHEMA, "map": map_name, "run_id": run_id, "ts_utc": ts_utc,
        "valid": valid, "invalid_reasons": invalid_reasons,
        "highway": {            # isolation evidence is always present; the geometric PIN only on valid
            "id": None, "pin": "nearest-base-polyline (geometric)",
            "engaged_window_s": ([[round(a, 3), round(b, 3)] for (a, b) in engaged_windows]
                                 if engaged_windows else None),
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


def merge_score_into_ledger(ledger_path: Path, run_id: str, artifact: dict):
    """Merge the route-eval result into that run's `komodobots.bot_attempts.v1` row (additive nested
    `route_eval` key -- the row's required keys are untouched, so the dashboard gallery still reads
    it). ALWAYS carries the isolation-proof fields (`valid`, `invalid_reasons`, `n_engaged_spans`,
    `engaged_frames`, `engaged_fraction`); the consumable `highway_id`/`rmse_xyz`/`mean_speed_qu_s`/
    `degenerate` are written ONLY when `valid` -- an INVALID (not route-isolated) eval writes NO
    consumable score, so a downstream reader can never mistake it for a real route_eval result
    (#428). A missing/unreadable ledger or a missing row WARNs and skips (never crashes the run)."""
    if not ledger_path.exists():
        LOGGER.warning("ledger %s absent; score not merged", ledger_path)
        return None
    ledger = _load_json(ledger_path)
    attempts = ledger.get("attempts") if isinstance(ledger, dict) else None
    if not isinstance(attempts, list):
        LOGGER.warning("ledger %s has no attempts list; score not merged", ledger_path)
        return None
    hw = artifact.get("highway") or {}
    route_eval = {
        "valid": artifact.get("valid"),
        "invalid_reasons": artifact.get("invalid_reasons", []),
        "n_engaged_spans": hw.get("n_engaged_spans"),
        "engaged_frames": hw.get("engaged_frames"),
        "engaged_fraction": hw.get("engaged_fraction"),
    }
    if artifact.get("valid"):
        route_eval.update({
            "highway_id": hw.get("id"),
            "rmse_xyz": (artifact.get("adherence") or {}).get("rmse_xyz"),
            "mean_speed_qu_s": (artifact.get("velocity") or {}).get("mean_speed_qu_s"),
            "degenerate": artifact.get("degenerate"),
        })
    for row in attempts:
        if row.get("run_id") == run_id:
            row["route_eval"] = route_eval
            ledger_path.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n",
                                   encoding="utf-8")
            return route_eval
    LOGGER.warning("no ledger row for run_id %s; route_eval not merged", run_id)
    return None


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
            merge_score_into_ledger(Path(ledger_path), run_id, artifact)
    return artifact


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
