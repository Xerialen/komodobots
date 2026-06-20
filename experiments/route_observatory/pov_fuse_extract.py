#!/usr/bin/env python3
"""pov_fuse_extract — extract one route leg's per-tick state + the human MOVEMENT SIGNATURE.

A "leg" = a [t0,t1] window of one player's trajectory along a route (between two resources),
pulled from a parsed MVD demo (`qw-analyze` full JSON). Emits a leg bundle
(`komodobots.route_leg.v1`) consumed by `pov_fuse_render.py` to build the fused POV+route
validation sheet. The signature it computes (speed profile, jump cadence, look-vs-move,
straightness) is the route-conditioned BC TARGET and the believability RUBRIC.

Conventions baked in (these took a session to pin down — see route_observatory/README.md):
  - streams.players[].pos is STRUCT-OF-ARRAYS: t,x,y,z,li,vp,vya,vx,vy,vz
  - pos.t is MILLISECONDS; vya is QUAKE ANGLE UNITS (x 360/65536)
  - pos.li (loc index) FLICKERS at speed -> never trust per-tick loc labels; use x/y + teamsay
  - frame<->match sync: match_ms = (video_t - offset)*1000   (book-vs-mix MVD offset = 1695)

Usage:
  pov_fuse_extract.py <analysis.json> <player> <t0_s> <t1_s> <frames_dir> <out.json>
                      [--offset 1695] [--label "Milton — mega -> RL"]
"""
import sys
import json
import math
import re
import os

# Resources = locs holding a major item; matches route_extract.py (anchor to demo entities).
RES_KINDS = {'ra', 'ya', 'rl', 'sng', 'gl', 'lg', 'quad', 'pent', 'ring', 'mh'}


# ---- pure helpers (unit-tested in tests/test_pov_fuse_extract.py) -------------------------
def hspeed(vx, vy):
    return math.hypot(vx, vy)


def yaw_deg(vya):
    """Quake angle units (0..65535 = 0..360deg) -> degrees normalised to [-180, 180]."""
    return ((vya * 360 / 65536 + 180) % 360) - 180


def move_dir_deg(vx, vy):
    """Horizontal velocity heading in degrees, or None when essentially stationary."""
    return math.degrees(math.atan2(vy, vx)) if math.hypot(vx, vy) > 1 else None


def look_vs_move(yaw, mdir):
    """Smallest angle between where the player LOOKS (yaw) and where they MOVE (mdir)."""
    if yaw is None or mdir is None:
        return None
    return abs(((yaw - mdir + 180) % 360) - 180)


def detect_jumps(ticks, thresh=240.0, ground=60.0, refractory_s=0.22):
    """Takeoffs = vz rising-edge up through +thresh from a recent near-ground state, debounced.

    v1 PROXY: MVD carries no onground flag and raw .qwd onground is unreliable, so jumps are
    inferred from vertical velocity. The refractory + near-ground guard kill the false cluster
    that a bare threshold fires on ramps/stairs (e.g. the dm3 bridge). Replace with geometric
    onground (#316) once it is baked into the catalog.
    """
    jt = []
    last = -9.0
    for k in range(2, len(ticks)):
        vz0, vz1 = ticks[k - 1]['vz'], ticks[k]['vz']
        recent_low = min(ticks[j]['vz'] for j in range(max(0, k - 4), k))
        if vz0 < thresh <= vz1 and recent_low < ground and (ticks[k]['t'] - last) > refractory_s:
            jt.append(round(ticks[k]['t'], 2))
            last = ticks[k]['t']
    return jt


def compute_signature(ticks):
    """The human movement signature for one leg: the BC target + believability rubric."""
    hs = [t['hs'] for t in ticks]
    jt = detect_jumps(ticks)
    ints = [round(jt[i] - jt[i - 1], 3) for i in range(1, len(jt))]
    lmv = [a for a in (look_vs_move(t['yaw'], t['mdir']) for t in ticks) if a is not None]
    path = sum(math.hypot(ticks[k]['x'] - ticks[k - 1]['x'], ticks[k]['y'] - ticks[k - 1]['y'])
               for k in range(1, len(ticks)))
    net = math.hypot(ticks[-1]['x'] - ticks[0]['x'], ticks[-1]['y'] - ticks[0]['y'])
    return {
        "dur_s": round(ticks[-1]['t'] - ticks[0]['t'], 1),
        "hs_min": round(min(hs)), "hs_mean": round(sum(hs) / len(hs)), "hs_max": round(max(hs)),
        "jumps": len(jt), "jump_times_s": jt, "jump_intervals_s": ints,
        "jump_interval_mean_s": (round(sum(ints) / len(ints), 3) if ints else None),
        "lookmove_mean_deg": (round(sum(lmv) / len(lmv)) if lmv else None),
        "lookmove_max_deg": (round(max(lmv)) if lmv else None),
        "path_qu": round(path), "net_qu": round(net),
        "straightness": (round(net / path, 3) if path else None),
        "_jump_method": "vz rising-edge through +240 from near-ground, 0.22s refractory "
                        "(v1 proxy; replace with geometric onground #316 once catalog rebuilt)",
    }


def _clean_say(s):
    s = s.replace('\r', '').strip()
    s = re.sub(r'&c[0-9a-fA-F]{3}', '', s)
    s = s.replace('{', '').replace('}', '')
    return re.sub(r'\s+', ' ', s).strip()


def _find_player(players, who):
    if who.isdigit() and int(who) < len(players):
        return players[int(who)]
    for p in players:
        if p.get('name') == who:
            return p
    for p in players:
        if who.lower() in (p.get('name') or '').lower():
            return p
    raise SystemExit(f"player {who!r} not found; have: {[p.get('name') for p in players]}")


# ---- bundle builder ----------------------------------------------------------------------
def build_leg(d, who, t0_s, t1_s, frames_dir, offset=1695, label=None):
    P = _find_player(d['streams']['players'], who)
    p = P['pos']
    locs = d['locGraph']['locs']
    t0_ms, t1_ms = t0_s * 1000, t1_s * 1000
    idx = [i for i in range(len(p['t'])) if t0_ms <= p['t'][i] <= t1_ms]
    if len(idx) < 2:
        raise SystemExit(f"no ticks in [{t0_s},{t1_s}]s for {P.get('name')}")

    ticks = []
    for i in idx:
        mdir = move_dir_deg(p['vx'][i], p['vy'][i])
        ticks.append({"t": round(p['t'][i] / 1000, 3),
                      "x": round(p['x'][i], 1), "y": round(p['y'][i], 1), "z": round(p['z'][i], 1),
                      "hs": round(hspeed(p['vx'][i], p['vy'][i])),
                      "yaw": round(yaw_deg(p['vya'][i]), 1),
                      "mdir": (round(mdir, 1) if mdir is not None else None),
                      "vz": round(p['vz'][i])})

    res_locs = {e['loc'] for e in d['mapEntities']['entities']
                if (e.get('kind') or '').lower() in RES_KINDS and e.get('loc')}
    markers = [{"name": l['name'], "x": round(l['x'], 1), "y": round(l['y'], 1),
                "res": l['name'] in res_locs} for l in locs]

    teamsay = [{"t": round(m['time'] / 1000, 2), "text": _clean_say(m.get('message', ''))}
               for m in d['messages']['events']
               if m.get('player') == P.get('name')
               and t0_ms - 3500 <= m.get('time', 0) <= t1_ms + 500
               and '[' in (m.get('message') or '')]

    frames = []
    for S in range(math.ceil(t0_ms / 1000), math.floor(t1_ms / 1000) + 1):
        vt = S + offset
        f = f"t{vt:06d}.jpg"
        frames.append({"s": S, "video_t": vt, "file": f,
                       "exists": os.path.exists(os.path.join(frames_dir, f))})

    return {
        "schema": "komodobots.route_leg.v1",
        "label": label or f"{P.get('name')} — leg {t0_s}-{t1_s}s",
        "player": P.get('name'), "demo": d.get('filePath'),
        "map": d.get('mapEntities', {}).get('map'),
        "match_t0": t0_s, "match_t1": t1_s, "video_offset": offset,
        "signature": compute_signature(ticks),
        "ticks": ticks, "markers": markers, "teamsay": teamsay, "frames": frames,
    }


def main(argv):
    offset, label, args = 1695, None, []
    i = 0
    while i < len(argv):
        if argv[i] == '--offset':
            offset = int(argv[i + 1]); i += 2
        elif argv[i] == '--label':
            label = argv[i + 1]; i += 2
        else:
            args.append(argv[i]); i += 1
    if len(args) < 6:
        raise SystemExit(__doc__)
    analysis, who, t0, t1, frames_dir, out = args[:6]
    d = json.load(open(analysis))
    leg = build_leg(d, who, float(t0), float(t1), frames_dir, offset, label)
    json.dump(leg, open(out, 'w'))
    s = leg['signature']
    print(f"WROTE {out}: {len(leg['ticks'])} ticks, "
          f"{sum(f['exists'] for f in leg['frames'])} frames, {len(leg['teamsay'])} binds")
    print(f"signature: {s['dur_s']}s  hspeed {s['hs_min']}/{s['hs_mean']}/{s['hs_max']}  "
          f"{s['jumps']} jumps (mean int {s['jump_interval_mean_s']}s)  "
          f"look-vs-move {s['lookmove_mean_deg']}deg  straightness {s['straightness']}")


if __name__ == '__main__':
    main(sys.argv[1:])
