#!/usr/bin/env python3
"""gmv_believability.py — the G-MV believability battery (T5.3 / #283).

Pure standard library only (``math``, ``json``, ``sqlite3``, ``statistics``,
``argparse``, ``pathlib``). NO third-party imports — this module obeys the same
stdlib-only merge gate as the rest of ``scripts/`` (the gate runs it on bare
Python 3.12). Heavy deps live only under ``ml/``.

WHAT THIS IS FOR
----------------
A BROAD dm3 4on4 bot must be **believable**, not just competent. The competence
gates (docs/12 M/E/A/P/T, the ``dm3_4on4_anchors.json`` bands) are
necessary-but-not-sufficient: a bot can hit every band and still move like a
robot. This module is the offline **believability** gate the trained policy is
judged by, scoring a sequence of ``(player_state, usercmd)`` ticks against the
per-player anchor bands (defs: docs/16 G-MV; cross-referenced docs/13 §3,
docs/18 "human-look gate").

THE GATES (docs/16 G-MV)
------------------------
* **G-MV1 (HARD) — no face-and-run collapse.** The FrikBotNex failure: the bot's
  view yaw is locked to its velocity direction, so it always *faces where it is
  going* and never strafes / looks-off-axis like a human. We quantify the
  distribution of ``|wrap180(yaw - atan2(vy, vx))|`` over **airborne, moving**
  ticks (the strafe-jump domain) and FAIL if it has collapsed toward zero
  (median below a small floor AND too large a fraction of ticks near-aligned).
  Humans hold a large, spread yaw-vs-velocity angle while air-strafing; a
  face-and-run bot pins it at ~0.
* **G-MV3 — strafe cadence.** Left/right strafe alternation (``usercmd.sidemove``
  sign flips) per minute must sit inside a human band. Too few flips = not
  strafe-jumping; absurdly many = per-tick jitter, not human rhythm.
* **G-MV4 — speed within anchor min/max.** The sequence's horizontal-speed
  summary (avg + p95) must sit inside the per-player anchor band
  (``avg_horizontal_speed_qu_per_s`` / ``p95_horizontal_speed_qu_per_s``).

BANDS come from ``references/dm3_4on4_anchors.json`` (the Stage-0 Spike-4 elite
anchor). G-MV4 reads the per-player movement band (or the pool envelope when no
player is named). G-MV1 / G-MV3 thresholds are derived from the SAME real elite
corpus (see ``DEFAULT_THRESHOLDS`` provenance) — measured, not hand-tuned.

MEASUREMENT PLANE (important; G-ALIGN / M3-plane rule)
------------------------------------------------------
The anchor speed band is on the ``mvd_event_rate_finite_difference`` plane (a
forward difference of MVD ``pos`` at ~13 ms). The ``.qwd``/catalog ``hspeed`` is
``hypot(vx, vy)`` from the dense ``.qwd`` input path — the same ~13 ms cadence,
very close to the anchor plane but reconstructed per-frame rather than from
position deltas. G-MV4 therefore reports the plane it measured and treats the
anchor band as the comparison envelope; it is a band-membership check on the same
metric family, not a cross-plane comparison of speed vs item-share.

INPUT (the (state, usercmd) sequence)
-------------------------------------
A ``Tick`` is one frame: ``vx, vy`` (velocity qu/s), ``yaw`` (view angle deg),
``onground`` (bool/int), ``hspeed`` (optional; recomputed from vx/vy if absent),
``sidemove`` (usercmd short), and ``msec`` (frame ms, default ~13). Sequences are
read from:

* a real self-POV ``.qwd`` demo (``--qwd``), decoded by the on-``dev`` extractor
  ``build_replay_command_file.build_replay_frames`` — the SAME extraction the
  Strategy-A catalog ETL uses; this is the **POSITIVE-control** real-human source;
* the Strategy-A relational catalog SQLite (``--catalog``; ``player_ticks`` joined
  to ``actions``), optionally narrowed to one ``--player`` handle or ``--episode``
  (works once the catalog populator P1 has run);
* a plain JSON list of tick dicts (``--sequence-json``) — the test/fixture path
  and the format a bot-rollout exporter can emit;
* the built-in synthetic face-and-run generator (``synth_face_and_run``) — the
  NEGATIVE control proving the gate discriminates.

USAGE
-----
    # POSITIVE control: real human dm3 4on4 POV must PASS G-MV1
    python scripts/gmv_believability.py \
        --qwd /path/to/dm3_4on4_pov.qwd \
        --anchors references/dm3_4on4_anchors.json [--player-band Milton]

    # or from the populated Strategy-A catalog (after P1):
    python scripts/gmv_believability.py \
        --catalog data/catalog/dm3_4on4.sqlite \
        --anchors references/dm3_4on4_anchors.json [--player "qwd:...#p3"]

    # NEGATIVE control: synthesize a face-and-run sequence -> FAILS G-MV1
    python scripts/gmv_believability.py --synthetic face_and_run \
        --anchors references/dm3_4on4_anchors.json

Repo destination: scripts/gmv_believability.py
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import statistics
import sys
from pathlib import Path

SCHEMA = "komodobots.gmv_believability.v1"

# ----------------------------------------------------------------------------- #
# Tuning constants (the G-MV1/G-MV3 thresholds). Values are read off the SAME
# elite dm3 4on4 corpus the anchor file is built from (real self-POV .qwd dm3
# 4on4 demos, ~258k airborne-moving ticks measured during this unit's build),
# per the program §6 discipline of measuring the real objective. They are
# deliberately *loose* envelopes (necessary-not-sufficient), not tuned cuts:
# G-MV1 fails only a clear collapse toward zero, not a merely low-but-human
# spread.
# ----------------------------------------------------------------------------- #
DEFAULT_THRESHOLDS = {
    # G-MV1 domain: a tick counts toward the yaw-vs-velocity distribution only if
    # it is AIRBORNE and moving (the air-strafe regime where face-and-run shows).
    "mv1_airborne_only": True,
    "mv1_min_hspeed_qu_per_s": 150.0,  # below this, velocity angle is noise
    "mv1_min_ticks": 200,              # need enough airborne-moving ticks to judge
    # "near-aligned" = yaw within this many degrees of velocity direction.
    "mv1_aligned_deg": 5.0,
    # FAIL G-MV1 iff the distribution has collapsed toward zero: BOTH the median
    # |yaw-vel| angle is below the floor AND too large a share of ticks are
    # near-aligned. (Elite humans: median ~36 deg, ~13% aligned -> both far from
    # these cuts. A face-and-run bot: median ~0 deg, ~100% aligned.)
    "mv1_collapse_median_deg": 8.0,    # human median ~36 deg >> 8
    "mv1_collapse_aligned_frac": 0.60,  # human aligned-frac ~0.13 << 0.60
    # G-MV3 strafe cadence band, L/R sidemove sign-flips per minute. Human
    # air-strafing runs ~120-260 flips/min on active segments; allow a generous
    # band so non-strafe lulls (low cadence) and frantic fights still pass, and
    # only per-tick jitter (>~360/min, i.e. flipping every other 13 ms frame)
    # or a dead stick (no alternation at all over a long active window) fail.
    "mv3_min_flips_per_min": 8.0,
    "mv3_max_flips_per_min": 360.0,
    "mv3_min_strafe_ticks": 50,        # need enough nonzero-strafe ticks to judge
    # G-MV4: which anchor fields define the speed band, and a small relative
    # tolerance on the band edges (the anchor plane and the hspeed plane are
    # close but not byte-identical; see module docstring).
    "mv4_avg_field": "avg_horizontal_speed_qu_per_s",
    "mv4_p95_field": "p95_horizontal_speed_qu_per_s",
    "mv4_band_tol_frac": 0.05,         # widen [min,max] by +-5% before testing
    "mv4_min_ticks": 100,
}


# ----------------------------------------------------------------------------- #
# angle math                                                                    #
# ----------------------------------------------------------------------------- #
def wrap180(deg: float) -> float:
    """Wrap an angle in degrees to (-180, 180]."""
    d = (float(deg) + 180.0) % 360.0 - 180.0
    # the modulo can yield -180 for inputs at the wrap point; map it to +180 so
    # the range is the half-open (-180, 180].
    return 180.0 if d == -180.0 else d


def velocity_angle_deg(vx: float, vy: float) -> float:
    """Direction of the horizontal velocity in degrees (atan2(vy, vx))."""
    return math.degrees(math.atan2(float(vy), float(vx)))


def yaw_minus_velocity_deg(yaw: float, vx: float, vy: float) -> float:
    """Signed wrapped angle between view yaw and velocity direction (deg)."""
    return wrap180(float(yaw) - velocity_angle_deg(vx, vy))


def hspeed_of(vx: float, vy: float) -> float:
    return math.hypot(float(vx), float(vy))


def _percentile(sorted_vals, q: float) -> float:
    """Linear-interpolated percentile of an already-sorted list (q in [0,1])."""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    pos = q * (len(sorted_vals) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return float(sorted_vals[lo])
    frac = pos - lo
    return float(sorted_vals[lo]) * (1.0 - frac) + float(sorted_vals[hi]) * frac


# ----------------------------------------------------------------------------- #
# Tick model + normalization                                                    #
# ----------------------------------------------------------------------------- #
def normalize_tick(t: dict) -> dict:
    """Coerce one raw tick dict into the fields the gates use. Tolerant of the
    catalog column names and the JSON fixture names; recomputes hspeed from
    vx/vy when not supplied. ``onground`` accepts bool / 0-1 int / None."""
    vx = t.get("vx")
    vy = t.get("vy")
    yaw = t.get("yaw", t.get("cmd_yaw"))
    hspeed = t.get("hspeed")
    if hspeed is None and vx is not None and vy is not None:
        hspeed = hspeed_of(vx, vy)
    og = t.get("onground")
    if og is not None:
        og = bool(og)
    side = t.get("sidemove", t.get("side"))
    msec = t.get("msec")
    return {
        "vx": None if vx is None else float(vx),
        "vy": None if vy is None else float(vy),
        "yaw": None if yaw is None else float(yaw),
        "hspeed": None if hspeed is None else float(hspeed),
        "onground": og,
        "sidemove": None if side is None else float(side),
        "msec": float(msec) if msec is not None else 13.0,
    }


def normalize_sequence(ticks) -> list:
    return [normalize_tick(t) for t in ticks]


# ----------------------------------------------------------------------------- #
# G-MV1 — no face-and-run collapse (HARD)                                        #
# ----------------------------------------------------------------------------- #
def gate_mv1(ticks, thr=None) -> dict:
    """G-MV1: the yaw-vs-velocity-direction distribution must be human-shaped
    (large, spread), not collapsed toward zero (the face-and-run failure).

    Returns a per-gate result dict: pass/fail + the measured statistics + the
    margin to the collapse cuts. INSUFFICIENT (not enough airborne-moving ticks)
    is reported as ``passed=None`` with ``status='insufficient'`` so a caller can
    distinguish "no data to judge" from "judged and failed".
    """
    thr = thr or DEFAULT_THRESHOLDS
    angles = []
    for t in ticks:
        if t["vx"] is None or t["vy"] is None or t["yaw"] is None:
            continue
        if thr["mv1_airborne_only"] and t["onground"]:
            continue
        if (t["hspeed"] or 0.0) < thr["mv1_min_hspeed_qu_per_s"]:
            continue
        angles.append(abs(yaw_minus_velocity_deg(t["yaw"], t["vx"], t["vy"])))

    n = len(angles)
    if n < thr["mv1_min_ticks"]:
        return {
            "gate": "G-MV1", "hard": True, "passed": None, "status": "insufficient",
            "reason": "only %d airborne-moving ticks (< %d required)" % (n, thr["mv1_min_ticks"]),
            "n_ticks": n, "statistic": None, "margin": None, "thresholds": _mv1_thr(thr),
        }
    angles.sort()
    median = statistics.median(angles)
    mean = statistics.fmean(angles)
    aligned_frac = sum(1 for a in angles if a < thr["mv1_aligned_deg"]) / n
    p10 = _percentile(angles, 0.10)
    p90 = _percentile(angles, 0.90)

    # collapse iff BOTH conditions hold (median pinned low AND mostly aligned).
    collapsed = (median < thr["mv1_collapse_median_deg"]
                 and aligned_frac > thr["mv1_collapse_aligned_frac"])
    passed = not collapsed
    # margins: how far each indicator sits from its collapse cut (positive ==
    # comfortably human). We report both indicators.
    margin_median = median - thr["mv1_collapse_median_deg"]
    margin_aligned = thr["mv1_collapse_aligned_frac"] - aligned_frac
    return {
        "gate": "G-MV1", "hard": True, "passed": passed,
        "status": "pass" if passed else "fail",
        "n_ticks": n,
        "statistic": {
            "median_yaw_vs_vel_deg": round(median, 3),
            "mean_yaw_vs_vel_deg": round(mean, 3),
            "p10_deg": round(p10, 3),
            "p90_deg": round(p90, 3),
            "aligned_frac_within_%g_deg" % thr["mv1_aligned_deg"]: round(aligned_frac, 4),
        },
        "margin": {
            "median_minus_collapse_cut_deg": round(margin_median, 3),
            "collapse_cut_minus_aligned_frac": round(margin_aligned, 4),
        },
        "thresholds": _mv1_thr(thr),
    }


def _mv1_thr(thr) -> dict:
    return {
        "collapse_median_deg": thr["mv1_collapse_median_deg"],
        "collapse_aligned_frac": thr["mv1_collapse_aligned_frac"],
        "aligned_deg": thr["mv1_aligned_deg"],
        "min_hspeed_qu_per_s": thr["mv1_min_hspeed_qu_per_s"],
        "airborne_only": thr["mv1_airborne_only"],
    }


# ----------------------------------------------------------------------------- #
# G-MV3 — strafe cadence                                                         #
# ----------------------------------------------------------------------------- #
def _strafe_sign(side) -> int:
    if side is None:
        return 0
    if side > 0:
        return 1
    if side < 0:
        return -1
    return 0


def gate_mv3(ticks, thr=None) -> dict:
    """G-MV3: left/right strafe alternation cadence (sidemove sign flips per
    minute) must sit inside the human band. A flip is a transition between
    nonzero +side and nonzero -side; zero-strafe runs between them do not reset
    the comparison (so hold-left -> coast -> hold-right counts as one flip)."""
    thr = thr or DEFAULT_THRESHOLDS
    # active-time denominator = wall time spanned by the ticks that carry a
    # usercmd sidemove (the .qwd POV frames); MVD frames with no sidemove are
    # excluded both from flips and from the time base.
    have_side = [t for t in ticks if t["sidemove"] is not None]
    nonzero = [t for t in have_side if _strafe_sign(t["sidemove"]) != 0]
    n_strafe = len(nonzero)
    if n_strafe < thr["mv3_min_strafe_ticks"]:
        return {
            "gate": "G-MV3", "hard": False, "passed": None, "status": "insufficient",
            "reason": "only %d nonzero-strafe ticks (< %d required)" % (n_strafe, thr["mv3_min_strafe_ticks"]),
            "n_strafe_ticks": n_strafe, "statistic": None, "margin": None,
            "thresholds": {"min_flips_per_min": thr["mv3_min_flips_per_min"],
                           "max_flips_per_min": thr["mv3_max_flips_per_min"]},
        }
    flips = 0
    prev = 0
    for t in have_side:
        s = _strafe_sign(t["sidemove"])
        if s == 0:
            continue
        if prev != 0 and s != prev:
            flips += 1
        prev = s
    active_s = sum(t["msec"] for t in have_side) / 1000.0
    flips_per_min = (flips / active_s * 60.0) if active_s > 0 else 0.0
    in_band = thr["mv3_min_flips_per_min"] <= flips_per_min <= thr["mv3_max_flips_per_min"]
    # margin to the nearer band edge (positive == inside, with room).
    margin = min(flips_per_min - thr["mv3_min_flips_per_min"],
                 thr["mv3_max_flips_per_min"] - flips_per_min)
    return {
        "gate": "G-MV3", "hard": False, "passed": in_band,
        "status": "pass" if in_band else "fail",
        "n_strafe_ticks": n_strafe,
        "statistic": {
            "flips": flips,
            "active_s": round(active_s, 3),
            "flips_per_min": round(flips_per_min, 3),
        },
        "margin": {"flips_per_min_to_nearer_edge": round(margin, 3)},
        "thresholds": {"min_flips_per_min": thr["mv3_min_flips_per_min"],
                       "max_flips_per_min": thr["mv3_max_flips_per_min"]},
    }


# ----------------------------------------------------------------------------- #
# G-MV4 — horizontal speed within the per-player anchor band                     #
# ----------------------------------------------------------------------------- #
def _band_for(anchors: dict, field: str, player_band):
    """Return (lo, hi, source) for one movement metric. ``player_band`` names an
    anchor player to use that player's per-player min/max; otherwise the pool
    envelope (across all anchor players) is used."""
    fld = anchors["metrics"]["movement"]["fields"][field]
    if player_band:
        pp = fld["per_player"]
        if player_band not in pp:
            raise KeyError("anchor player %r not in band (have: %s)"
                           % (player_band, ", ".join(sorted(pp))))
        st = pp[player_band]["stats"]
        return float(st["min"]), float(st["max"]), "per_player:%s" % player_band
    st = fld["pool"]
    return float(st["min"]), float(st["max"]), "pool"


def gate_mv4(ticks, anchors: dict, player_band=None, thr=None) -> dict:
    """G-MV4: the sequence's horizontal-speed summary (avg + p95) must fall
    inside the anchor speed band (per-player if named, else pool), each band
    widened by ``mv4_band_tol_frac`` to absorb the small plane difference."""
    thr = thr or DEFAULT_THRESHOLDS
    speeds = [t["hspeed"] for t in ticks if t["hspeed"] is not None]
    n = len(speeds)
    if n < thr["mv4_min_ticks"]:
        return {
            "gate": "G-MV4", "hard": False, "passed": None, "status": "insufficient",
            "reason": "only %d ticks with hspeed (< %d required)" % (n, thr["mv4_min_ticks"]),
            "n_ticks": n, "statistic": None, "margin": None,
            "plane": "hspeed=hypot(vx,vy) (~13ms); anchor plane=mvd_event_rate_finite_difference",
        }
    speeds.sort()
    avg = statistics.fmean(speeds)
    p95 = _percentile(speeds, 0.95)

    checks = {}
    all_in = True
    for label, value, field in (("avg", avg, thr["mv4_avg_field"]),
                                ("p95", p95, thr["mv4_p95_field"])):
        lo, hi, src = _band_for(anchors, field, player_band)
        tol = (hi - lo) * thr["mv4_band_tol_frac"]
        lo_t, hi_t = lo - tol, hi + tol
        inside = lo_t <= value <= hi_t
        all_in = all_in and inside
        # signed distance to the band: >=0 inside (room to the nearer edge),
        # negative outside (how far past the violated edge, either side).
        if value < lo_t:
            dist = value - lo_t          # negative (below the band)
        elif value > hi_t:
            dist = hi_t - value          # negative (above the band)
        else:
            dist = min(value - lo_t, hi_t - value)  # >=0 inside
        checks[label] = {
            "value": round(value, 3), "band_field": field, "band_source": src,
            "band_min": round(lo, 3), "band_max": round(hi, 3),
            "band_min_tol": round(lo_t, 3), "band_max_tol": round(hi_t, 3),
            "inside": inside, "dist_to_band_qu_per_s": round(dist, 3),
        }
    return {
        "gate": "G-MV4", "hard": False, "passed": all_in,
        "status": "pass" if all_in else "fail",
        "n_ticks": n,
        "statistic": {"avg_hspeed_qu_per_s": round(avg, 3),
                      "p95_hspeed_qu_per_s": round(p95, 3),
                      "checks": checks},
        "margin": {k: v["dist_to_band_qu_per_s"] for k, v in checks.items()},
        "plane": "hspeed=hypot(vx,vy) (~13ms); anchor plane=mvd_event_rate_finite_difference",
        "band_player": player_band or "pool",
    }


# ----------------------------------------------------------------------------- #
# Battery                                                                        #
# ----------------------------------------------------------------------------- #
def run_battery(ticks, anchors=None, player_band=None, thr=None) -> dict:
    """Run all three gates over one normalized (state, usercmd) sequence.

    Overall ``believable`` is gated on G-MV1 (the HARD gate) PASSING; G-MV3/G-MV4
    are reported and contribute to ``all_gates_passed`` but, per docs/16,
    band-pass is necessary-not-sufficient while G-MV1 is the hard fail.
    ``all_gates_passed`` is True only when EVERY included gate affirmatively
    passed (``passed is True``): an included-but-unscored gate (``passed is
    None`` / insufficient) makes it False (fail-closed), it is not dropped.
    ``believable`` likewise requires G-MV1 to have actually passed (not be
    insufficient)."""
    thr = thr or DEFAULT_THRESHOLDS
    ticks = normalize_sequence(ticks)
    mv1 = gate_mv1(ticks, thr)
    mv3 = gate_mv3(ticks, thr)
    gates = {"G-MV1": mv1, "G-MV3": mv3}
    if anchors is not None:
        gates["G-MV4"] = gate_mv4(ticks, anchors, player_band, thr)

    # Every INCLUDED gate counts toward "all passed" only when it affirmatively
    # passed. An included-but-unscored gate (passed is None / insufficient) is NOT
    # dropped: it makes all_gates_passed False (fail-closed), so an unscored soft
    # gate can never be reported as all-passed.
    all_passed = bool(gates) and all(g["passed"] is True for g in gates.values())
    believable = (mv1["passed"] is True)  # HARD gate must affirmatively pass
    return {
        "schema": SCHEMA,
        "n_ticks": len(ticks),
        "player_band": player_band or "pool",
        "believable": believable,            # G-MV1 hard gate
        "all_gates_passed": all_passed,      # incl. necessary-not-sufficient band gates
        "hard_gate": "G-MV1",
        "gates": gates,
    }


# ----------------------------------------------------------------------------- #
# Sequence sources                                                              #
# ----------------------------------------------------------------------------- #
def load_anchors(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_sequence_json(path) -> list:
    """Load a sequence from JSON: either a bare list of tick dicts, or
    ``{"ticks": [...]}`` / ``{"frames": [...]}``."""
    obj = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(obj, dict):
        obj = obj.get("ticks", obj.get("frames", []))
    return list(obj)


def load_sequence_from_qwd(qwd_path, limit=0) -> list:
    """Decode a real self-POV ``.qwd`` demo into a (state, usercmd) sequence via
    the on-``dev`` extractor ``build_replay_command_file.build_replay_frames``
    (the same path the Strategy-A catalog ETL uses). Each replay frame carries
    the ego state (origin/velocity/angles/onground) AND the recovered usercmd
    (move = [fwd, side, up], buttons), so one frame == one (state, usercmd) tick.

    This is the POSITIVE-control real-human source and needs no populated
    catalog; it imports the extractor lazily so the rest of the module stays
    importable on a bare interpreter without a demo on hand."""
    here = Path(__file__).resolve().parent
    for p in (str(here.parent), str(here)):
        if p not in sys.path:
            sys.path.insert(0, p)
    import build_replay_command_file as brc  # noqa: E402 (stdlib-only sibling)

    frames, _meta = brc.build_replay_frames(Path(qwd_path), alignment="time")
    if limit:
        frames = frames[:limit]
    out = []
    for f in frames:
        v = f["velocity"]
        a = f["angles"]
        mv = f["move"]
        out.append({
            "vx": v[0], "vy": v[1],
            "yaw": a[1],                       # angles = [pitch, yaw, roll]
            "hspeed": hspeed_of(v[0], v[1]),
            "onground": bool(f["onground"]),
            "sidemove": mv[1],                 # move = [forward, side, up]
            "msec": f.get("msec", 13),
        })
    return out


def load_sequence_from_catalog(db_path, player=None, episode=None, limit=0) -> list:
    """Read a (state, usercmd) sequence from the Strategy-A catalog SQLite by
    joining ``player_ticks`` to ``actions`` (so each row carries both the state
    and the recovered usercmd). Optionally narrow to one player handle or one
    episode. Rows are ordered by (episode, tick) so cadence/flip counting sees
    frames in time order.

    Only ``.qwd`` (source='qwd') demos carry real usercmds; the ``.mvd`` fixture
    zeroes movement-intent. We restrict to qwd demos by default so G-MV3 (needs
    sidemove) and G-MV1 (airborne, needs ground-truth onground) are scored on the
    action-fidelity tier."""
    con = sqlite3.connect(db_path)
    try:
        where = ["d.source = 'qwd'"]
        params = []
        if player:
            where.append("pl.handle = ?")
            params.append(player)
        if episode is not None:
            where.append("pt.episode_id = ?")
            params.append(int(episode))
        sql = (
            "SELECT pt.episode_id, pt.tick, pt.vx, pt.vy, pt.yaw, pt.hspeed, "
            "       pt.onground, pt.msec, a.sidemove "
            "FROM player_ticks pt "
            "JOIN actions a ON a.episode_id = pt.episode_id AND a.tick = pt.tick "
            "JOIN episodes e ON e.episode_id = pt.episode_id "
            "JOIN demos d ON d.demo_id = e.demo_id "
            "JOIN players pl ON pl.player_id = e.player_id "
            "WHERE " + " AND ".join(where) + " "
            "ORDER BY pt.episode_id, pt.tick"
        )
        if limit:
            sql += " LIMIT %d" % int(limit)
        rows = con.execute(sql, params).fetchall()
    finally:
        con.close()
    return [
        {"vx": r[2], "vy": r[3], "yaw": r[4], "hspeed": r[5],
         "onground": r[6], "msec": r[7], "sidemove": r[8]}
        for r in rows
    ]


def list_catalog_players(db_path) -> list:
    """Return [(handle, n_ticks)] for qwd POV players in the catalog, busiest
    first (useful to pick a --player for the positive control)."""
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute(
            "SELECT pl.handle, COUNT(*) n "
            "FROM player_ticks pt "
            "JOIN episodes e ON e.episode_id = pt.episode_id "
            "JOIN demos d ON d.demo_id = e.demo_id "
            "JOIN players pl ON pl.player_id = e.player_id "
            "WHERE d.source = 'qwd' "
            "GROUP BY pl.handle ORDER BY n DESC"
        ).fetchall()
    finally:
        con.close()
    return [(r[0], r[1]) for r in rows]


# ----------------------------------------------------------------------------- #
# Synthetic NEGATIVE control: face-and-run (yaw == velocity angle every tick)    #
# ----------------------------------------------------------------------------- #
def _lcg(seed):
    """A tiny deterministic LCG (Numerical Recipes constants) returning a
    closure yielding floats in [0,1). Used so the synthetic controls are
    reproducible without seeding any external RNG (stdlib-free determinism)."""
    state = seed & 0xFFFFFFFF

    def rnd():
        nonlocal state
        state = (1664525 * state + 1013904223) & 0xFFFFFFFF
        return state / 4294967296.0

    return rnd


def _bimodal_speed(rnd, burst_frac=0.22, low=225.0, high=520.0, jit=0.12) -> float:
    """A bursty, bimodal horizontal speed (low cruise vs bunny-burst) tuned so a
    long synthetic run's avg+p95 land inside the dm3 4on4 pool speed band — real
    movement is bursty, not uniform, so a uniform draw cannot reproduce the
    band's wide avg<->p95 gap. Used to make the negative control sit INSIDE the
    speed band so G-MV1 is provably the SOLE discriminator."""
    base = high if rnd() < burst_frac else low
    return max(base * (1.0 + (rnd() - 0.5) * jit), 0.0)


def synth_face_and_run(n=2000, seed=1234) -> list:
    """Synthesize a FACE-AND-RUN airborne sequence: the view yaw is locked to the
    instantaneous velocity direction every tick (the FrikBotNex collapse). The
    heading wanders (a smooth pseudo-random walk), the speed is bursty so it sits
    inside the anchor speed band, and the bot strafes in a human-band cadence —
    but because yaw == atan2(vy, vx) exactly, G-MV1's distribution collapses to
    ~0. Deterministic so the control is reproducible.

    This is the discrimination proof's negative pole: a sequence that PASSES the
    soft band gates (G-MV3 cadence, G-MV4 speed) yet must FAIL the hard G-MV1 —
    proving G-MV1 alone catches face-and-run."""
    rnd = _lcg(seed)
    ticks = []
    heading = 0.0  # degrees, wanders
    for i in range(n):
        heading += (rnd() - 0.5) * 6.0  # gentle drift
        spd = _bimodal_speed(rnd)
        rad = math.radians(heading)
        vx = spd * math.cos(rad)
        vy = spd * math.sin(rad)
        # FACE-AND-RUN: yaw is exactly the velocity direction (the collapse).
        yaw = velocity_angle_deg(vx, vy)
        # ~150 L/R flips/min: hold each strafe direction ~30 ticks (~0.4 s).
        side_sign = 1 if (i // 30) % 2 == 0 else -1
        ticks.append({
            "vx": vx, "vy": vy, "yaw": yaw, "hspeed": spd,
            "onground": False, "msec": 13.0, "sidemove": 400 * side_sign,
        })
    return ticks


def synth_human_like(n=2000, yaw_offset_deg=40.0, seed=99) -> list:
    """Synthesize a HUMAN-LIKE airborne strafe sequence for tests: yaw is held a
    large, oscillating offset OFF the velocity direction (as when air-strafing),
    so G-MV1 passes. Deterministic. Not a control of record (the real human .qwd
    is the positive control); a self-contained fixture for unit tests."""
    rnd = _lcg(seed)
    ticks = []
    heading = 0.0
    for i in range(n):
        heading += (rnd() - 0.5) * 6.0
        spd = _bimodal_speed(rnd)
        rad = math.radians(heading)
        vx = spd * math.cos(rad)
        vy = spd * math.sin(rad)
        # large yaw offset off the velocity direction, oscillating L/R like a
        # human air-strafe (sign flips ~ every 0.4 s -> ~150 flips/min).
        phase = 1.0 if (i // 30) % 2 == 0 else -1.0
        yaw = velocity_angle_deg(vx, vy) + yaw_offset_deg * phase
        side_sign = 1 if phase > 0 else -1
        ticks.append({
            "vx": vx, "vy": vy, "yaw": yaw, "hspeed": spd,
            "onground": False, "msec": 13.0, "sidemove": 400 * side_sign,
        })
    return ticks


# ----------------------------------------------------------------------------- #
# CLI                                                                           #
# ----------------------------------------------------------------------------- #
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="G-MV believability battery (G-MV1 hard / G-MV3 / G-MV4)")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--qwd", help="real self-POV .qwd demo (positive-control source)")
    src.add_argument("--catalog", help="Strategy-A catalog .sqlite (player_ticks+actions)")
    src.add_argument("--sequence-json", help="JSON sequence: list of tick dicts or {ticks:[...]}")
    src.add_argument("--synthetic", choices=["face_and_run", "human_like"],
                     help="use a built-in synthetic sequence (controls/demo)")
    ap.add_argument("--anchors", help="references/dm3_4on4_anchors.json (enables G-MV4)")
    ap.add_argument("--player", help="catalog POV handle to score (default: all qwd POVs)")
    ap.add_argument("--player-band", help="anchor player name for the G-MV4 band (else pool)")
    ap.add_argument("--episode", type=int, help="restrict catalog read to one episode_id")
    ap.add_argument("--limit", type=int, default=0, help="cap rows/frames read (debug)")
    ap.add_argument("--list-players", action="store_true",
                    help="with --catalog: list qwd POV handles + tick counts, then exit")
    ap.add_argument("--n", type=int, default=2000, help="synthetic sequence length")
    args = ap.parse_args(argv)

    if args.list_players:
        if not args.catalog:
            ap.error("--list-players requires --catalog")
        for handle, n in list_catalog_players(args.catalog):
            print("%8d  %s" % (n, handle))
        return 0

    if args.qwd:
        ticks = load_sequence_from_qwd(args.qwd, limit=args.limit)
        source = "qwd:%s" % args.qwd
    elif args.catalog:
        ticks = load_sequence_from_catalog(
            args.catalog, player=args.player, episode=args.episode, limit=args.limit)
        source = "catalog:%s%s" % (args.catalog, (" player=%s" % args.player) if args.player else "")
    elif args.sequence_json:
        ticks = load_sequence_json(args.sequence_json)
        source = "json:%s" % args.sequence_json
    else:
        ticks = (synth_face_and_run(n=args.n) if args.synthetic == "face_and_run"
                 else synth_human_like(n=args.n))
        source = "synthetic:%s" % args.synthetic

    anchors = load_anchors(args.anchors) if args.anchors else None
    if anchors is None:
        print("# note: no --anchors given; G-MV4 (speed band) skipped", file=sys.stderr)

    result = run_battery(ticks, anchors=anchors, player_band=args.player_band)
    result["source"] = source
    print(json.dumps(result, indent=2))
    # CLI success (exit 0) requires the HARD gate (G-MV1) to AFFIRMATIVELY pass.
    # Fail closed for CI/batch consumers: an outright G-MV1 fail -> exit 2; an
    # insufficient/unscored G-MV1 (passed is None) -> exit 3 (distinct from a
    # clear fail, but still non-zero so an unscored rollout is never "passing").
    mv1_passed = result["gates"]["G-MV1"]["passed"]
    if mv1_passed is True:
        return 0
    return 2 if mv1_passed is False else 3


if __name__ == "__main__":
    raise SystemExit(main())
