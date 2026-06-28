#!/usr/bin/env python3
"""build_route_canon.py — build the dm3 Route Canon DB from owner-marked clean half-routes (#420).

Each owner mark = (demo, player, start_s, end_s, label, route_class). The owner hand-cuts a HALF
route so the CUT itself EXCLUDES the trick jump, isolating pure base movement — avoiding the past
mistake of measuring routes that *require* a trick to complete (which conflates movement quality
with trick execution). This extracts that one clean trajectory (the "seed line"), labels its
endpoints by nearest resource, computes the committed movement signature, runs a trick-anomaly
verifier (flag, never auto-drop), and writes a `komodobots.route_canon.v1` entry.

Scope: this is #420 (define highways + per-highway SEED LINE = the initial MSE/RMSE ground truth).
#421 (POV-fusion) later widens each highway to an empirical BAND over many matched corpus
traversals — and MUST gate that harvest by seed-trajectory similarity + route_class, never by the
(from,to) resource pair (which re-pools base + shortcut traversals = the contamination #420
prevents). See data/catalog/route_canon.dm3.json `_match_key`.

Reuses (anchors — do not reinvent): pov_fuse_extract.compute_signature / _find_player,
route_legs.player_ticks, ml/pipeline/route_goals.load_resource_coords.

Usage:
  build_route_canon.py <marks.json> --analysis <alias>=<analysis.json> [--analysis ...] -o <out.json>
    marks.json: {"map":"dm3","date":"...","marks":[{demo,player,start_s,end_s,label,route_class},...]}
    --analysis maps each mark's `demo` alias -> a qw-analyze full JSON
      (qw-analyze -view full -include positions,view,velocity <demo>).
"""
import logging
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "ml", "pipeline"))
from pov_fuse_extract import compute_signature, _find_player  # noqa: E402
from route_legs import player_ticks  # noqa: E402
from route_goals import load_resource_coords  # noqa: E402

LOGGER = logging.getLogger(__name__)

SCHEMA = "komodobots.route_canon.v1"
COORDS_PATH = os.path.join(REPO, "data", "catalog", "resource_coords.dm3.json")

# A consecutive-tick step is a teleport/respawn discontinuity (not movement) when it exceeds both a
# floor AND a velocity-relative bound — dt-robust, so it stays correct if a future demo uses a lower
# sv_demofps (a fixed qu/tick threshold would not). At book_vs_mix's 15 ms tick the floor dominates.
TELEPORT_FLOOR_QU = 150.0
SPLIT_K = 4.0               # step > K * hspeed * dt  => discontinuity
MIN_RUN = 15               # ticks; a shorter surviving run = dead respawn frames, dropped
RESPAWN_FRACTION = 0.2     # among multiple runs, drop any shorter than this * the longest — kills
                           # pre-respawn gib/death frames (sub-0.5s, survive MIN_RUN) while keeping
                           # comparable teleport-chain legs (seg4). ponytail: a respawn-aware
                           # (health->100) detector is the upgrade if this fraction ever misfires.
GOAL_RHO = 200.0           # endpoint-label "approximate" threshold (matches route_legs visit rho)
# Self-damage (attacker==victim) is the RELIABLE rocket-jump / trick signal. vz alone is NOT: legit
# movement in this corpus (mega hill, lifts/jump-pads) launches vz to ~615, so a low ceiling cries
# wolf on clean bhop. VZ_TRICK_CEILING is a coarse backstop for a genuinely-extreme launch only;
# max_vz is recorded descriptively. Pure-movement "tricks" (hilljump etc.) carry no anomaly — they
# ARE skilled movement, excluded by the owner's cut, not by this verifier.
VZ_TRICK_CEILING = 900.0


def _slug(label):
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")


def _nearest_resource(coords, x, y):
    """Unbounded nearest resource (name, distance_qu). Half-route cuts end mid-corridor, so the
    label can be >GOAL_RHO from any item — that is surfaced (WARN + persisted dist), not gated."""
    best, bd = None, None
    for name, (rx, ry) in coords.items():
        d = math.hypot(x - rx, y - ry)
        if bd is None or d < bd:
            best, bd = name, d
    return best, bd


def _split_runs(ticks):
    """Split a tick list into continuous runs at teleport/respawn discontinuities."""
    runs, cur = [], []
    for tk in ticks:
        if cur:
            prev = cur[-1]
            dt = max(tk["t"] - prev["t"], 1e-6)
            step = math.hypot(tk["x"] - prev["x"], tk["y"] - prev["y"])
            if step > max(TELEPORT_FLOOR_QU, SPLIT_K * prev["hs"] * dt):
                runs.append(cur)
                cur = []
        cur.append(tk)
    if cur:
        runs.append(cur)
    return runs


def _keep_runs(ticks, label):
    """Drop dead-respawn runs (<MIN_RUN ticks). If ALL are short, fall back to the longest and WARN
    (the fallback must not silently mask an expected multi-segment split)."""
    runs = [r for r in _split_runs(ticks) if len(r) >= MIN_RUN]
    if not runs:
        allr = _split_runs(ticks)
        longest = max(allr, key=len) if allr else []
        LOGGER.warning("mark %r: all runs < MIN_RUN=%d; fell back to longest (%d ticks) — "
                       "n_segments may mask a real split", label, MIN_RUN, len(longest))
        return [longest] if longest else []
    longest = max(len(r) for r in runs)
    kept = [r for r in runs if len(r) >= RESPAWN_FRACTION * longest]
    if len(kept) < len(runs):
        LOGGER.warning("mark %r: dropped %d short pre-respawn/gib run(s) (< %.0f%% of longest)",
                       label, len(runs) - len(kept), RESPAWN_FRACTION * 100)
    return kept


def _self_damage(dmg_events, player, t0_ms, t1_ms):
    """Self-inflicted damage events (attacker == victim == player) inside [t0,t1] ms — the clean
    rocket-jump signal."""
    return [e for e in dmg_events
            if e.get("attacker") == player and e.get("victim") == player
            and t0_ms <= e.get("time", 0) <= t1_ms]


def _suspect_trick(run, self_dmg):
    """Flag (not drop) a run that looks like it contains a trick jump: self-damage (the reliable
    rocket-jump signal) and/or a genuinely-extreme vertical launch. The owner's cut is
    authoritative — this VERIFIES it is trick-free rather than trusting it blindly (#420).
    `self_dmg` is the list of self-damage events, or **None when the damage stream is UNAVAILABLE**
    (missing/malformed) — which fails closed (flagged suspect), since absence is not evidence of
    trick-free. Returns (suspect, reasons, max_vz)."""
    reasons = []
    vz_max = max(tk["vz"] for tk in run)
    if self_dmg is None:
        reasons.append("damage stream unavailable — self-damage (rocket jump) unverifiable; "
                       "fail-closed (absence is not evidence of trick-free)")
    else:
        for e in self_dmg:
            reasons.append(f"self-damage {e.get('damage')} via {e.get('weapon')} @ "
                           f"{e.get('time')}ms (rocket jump)")
    if vz_max > VZ_TRICK_CEILING:
        reasons.append(f"extreme vz launch {round(vz_max)} > {round(VZ_TRICK_CEILING)} (review)")
    return (len(reasons) > 0), reasons, round(vz_max)


def build_highway(d, mark, coords, dmg_events):
    """One owner mark -> one route_canon highway entry."""
    player = mark["player"]
    P = _find_player(d["streams"]["players"], player)
    t0, t1 = float(mark["start_s"]), float(mark["end_s"])
    ticks = [tk for tk in player_ticks(P) if t0 <= tk["t"] <= t1]   # zero offset; inclusive
    if len(ticks) < 2:
        raise SystemExit(f"mark {mark.get('label')!r}: <2 ticks in [{t0},{t1}]s for {player!r}")

    runs = _keep_runs(ticks, mark.get("label"))
    if not runs:
        raise SystemExit(f"mark {mark.get('label')!r}: no usable run after split")

    segments, hw_suspect, hw_reasons = [], False, []
    for r in runs:
        sx, sy, sz = r[0]["x"], r[0]["y"], r[0]["z"]
        ex, ey, ez = r[-1]["x"], r[-1]["y"], r[-1]["z"]
        fr, fd = _nearest_resource(coords, sx, sy)
        to, td = _nearest_resource(coords, ex, ey)
        if fd > GOAL_RHO or td > GOAL_RHO:
            LOGGER.warning("mark %r endpoint label approximate: from=%s(%dqu) to=%s(%dqu)",
                           mark.get("label"), fr, round(fd), to, round(td))
        if math.hypot(sx - coords[to][0], sy - coords[to][1]) <= td:
            LOGGER.warning("mark %r run does not approach its to_resource %s (start no farther "
                           "than end)", mark.get("label"), to)
        sdmg = (None if dmg_events is None
                else _self_damage(dmg_events, player, r[0]["t"] * 1000, r[-1]["t"] * 1000))
        susp, reasons, max_vz = _suspect_trick(r, sdmg)
        if susp:
            hw_suspect = True
            hw_reasons += reasons
            LOGGER.warning("mark %r SUSPECT trick: %s", mark.get("label"), "; ".join(reasons))
        segments.append({
            "from_resource": fr, "to_resource": to,
            "from_dist_qu": round(fd), "to_dist_qu": round(td),
            "start_xyz": [round(sx, 1), round(sy, 1), round(sz, 1)],
            "end_xyz": [round(ex, 1), round(ey, 1), round(ez, 1)],
            "suspect_trick": susp, "suspect_reasons": reasons, "max_vz": max_vz,
            "signature": compute_signature(r),
            "trajectory": [[round(tk["t"], 3), round(tk["x"], 1), round(tk["y"], 1),
                            round(tk["z"], 1)] for tk in r],
        })

    return {
        "id": mark.get("id") or _slug(mark["label"]),
        "label": mark["label"], "route_class": mark["route_class"],
        "from_resource": segments[0]["from_resource"], "to_resource": segments[-1]["to_resource"],
        "from_dist_qu": segments[0]["from_dist_qu"], "to_dist_qu": segments[-1]["to_dist_qu"],
        "start_xyz": segments[0]["start_xyz"], "end_xyz": segments[-1]["end_xyz"],
        "seed": {"demo": mark["demo"], "player": player, "start_s": t0, "end_s": t1},
        "n_segments": len(segments),
        "suspect_trick": hw_suspect, "suspect_reasons": hw_reasons,
        "segments": segments,
    }


def _dump(canon):
    """Pretty JSON, but each trajectory point [t,x,y,z] stays on ONE compact line (readable
    metadata + diff-friendly bulk). ponytail: sentinel-splice beats a custom JSONEncoder here."""
    sent, store = "@@TRAJ@@", []
    for hw in canon["highways"]:
        for seg in hw["segments"]:
            store.append(seg["trajectory"])
            seg["trajectory"] = f"{sent}{len(store) - 1}{sent}"
    txt = json.dumps(canon, indent=1, ensure_ascii=False)
    return re.sub(rf'"{sent}(\d+){sent}"',
                  lambda m: json.dumps(store[int(m.group(1))], separators=(",", ":")), txt)


def main(argv):
    marks_path, out, amap = None, None, {}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("-o", "--out"):
            out = argv[i + 1]; i += 2
        elif a == "--analysis":
            key, _, val = argv[i + 1].partition("="); amap[key] = val; i += 2
        elif marks_path is None:
            marks_path = a; i += 1
        else:
            raise SystemExit(f"unexpected arg: {a!r}")
    if not marks_path or not out:
        raise SystemExit("usage: build_route_canon.py <marks.json> "
                         "--analysis <alias>=<analysis.json> [...] -o <out.json>")

    marks = json.loads(open(marks_path, encoding="utf-8").read())
    coords = load_resource_coords(COORDS_PATH)
    if not coords:
        raise SystemExit(f"no resource coords loaded from {COORDS_PATH}")

    cache = {}

    def load(alias):
        if alias not in cache:
            path = amap.get(alias)
            if not path:
                raise SystemExit(f"no --analysis mapping for demo alias {alias!r}")
            cache[alias] = json.loads(open(path, encoding="utf-8").read())
        return cache[alias]

    highways = []
    for m in marks["marks"]:
        d = load(m["demo"])
        # Distinguish an AUTHORITATIVE empty damage stream ([]) from an UNAVAILABLE one (missing /
        # malformed): absence of damage is NOT evidence of zero self-damage, so a missing stream
        # fails closed (the highway is flagged suspect, never silently passed as clean). None here
        # signals unavailable; [] is a real "no self-damage occurred".
        damage = d.get("damage")
        events = damage.get("events") if isinstance(damage, dict) else None
        dmg_events = events if isinstance(events, list) else None
        hw = build_highway(d, m, coords, dmg_events)
        highways.append(hw)
        s0 = hw["segments"][0]["signature"]
        print(f"  {hw['id']:26} [{hw['route_class']:8}] {hw['from_resource']}->{hw['to_resource']} "
              f"({hw['from_dist_qu']}/{hw['to_dist_qu']}qu) nseg={hw['n_segments']} "
              f"{'SUSPECT' if hw['suspect_trick'] else 'clean':7} "
              f"dur={s0['dur_s']}s hs={s0['hs_min']}/{s0['hs_mean']}/{s0['hs_max']} "
              f"jumps={s0['jumps']} straight={s0['straightness']} "
              f"max_vz={hw['segments'][0]['max_vz']} ticks={len(hw['segments'][0]['trajectory'])}")

    canon = {
        "schema": SCHEMA, "map": marks.get("map", "dm3"),
        "_generated_by": "experiments/route_observatory/build_route_canon.py",
        "_regenerate": ("build_route_canon.py data/catalog/route_canon_marks.dm3.json "
                        "--analysis <alias>=<analysis.json> -o data/catalog/route_canon.dm3.json"),
        "_warning": "GENERATED from the marks + demos — regenerate, do NOT hand-edit.",
        "_match_key": ("#421 band-harvest MUST gate by segments[].trajectory similarity + "
                       "route_class — NEVER by (from_resource,to_resource): the pair re-pools "
                       "base+shortcut traversals (the exact contamination #420 prevents)."),
        "_scoring": ("#428 MSE/RMSE is scored on segments[].trajectory (exact MVD 1/8-qu position "
                     "= ground truth). signature.jumps/jump_intervals_s are vz-PROXY (_jump_method) "
                     "— descriptive only, NOT a #428 target, not comparable to geometric-onground "
                     "(#316) cadence. #428 owns trajectory alignment/resampling (native variable-dt)."),
        "_phase1_consumption": ("Canon stores ALL route_class values (tagged). Phase-1 base training "
                                "consumes route_class=='base' ONLY; shortcut/enabler are separate "
                                "frozen units (docs/28 trickjump-separation, #420). Including them "
                                "tagged here is NOT training on them."),
        "_provenance": {"marks_file": os.path.basename(marks_path), "date": marks.get("date"),
                        "n_highways": len(highways)},
        "highways": highways,
    }
    open(out, "w", encoding="utf-8").write(_dump(canon) + "\n")
    print(f"WROTE {out}  ({len(highways)} highways, "
          f"{sum(h['n_segments'] for h in highways)} segments)")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    main(sys.argv[1:])
