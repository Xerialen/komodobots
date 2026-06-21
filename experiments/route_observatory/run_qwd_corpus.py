#!/usr/bin/env python3
"""run_qwd_corpus.py — memory-safe batched .qwd corpus extraction (the full SmackDown3 set).

The t3.small dev box (2 GB) OOMs running catalog_etl_qwd on >~12 demos at once (it holds all
extracted demos in RAM before the serial insert). So process the corpus in small batches: per
batch, ETL → a throwaway DB → position-segment the legs (append) → DELETE the DB. Memory stays
bounded by BATCH, not by corpus size. Legs accumulate to legs_qwd_full.jsonl, atomically
swapped over legs_qwd.jsonl on success (so the prior corpus stays valid during the run).

Usage: run_qwd_corpus.py <demo_list.tsv> [out_dir=/tmp/route_qwd] [batch=6]
"""
import sys, os, json, math, sqlite3, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import route_legs_qwd as RLQ
from route_legs import resource_visits, compute_signature

REPO = os.path.abspath(os.path.join(HERE, '..', '..'))   # repo root (experiments/route_observatory -> ../..)
ENV = os.path.join(HERE, 'signatures', 'envelopes_mvd_4on4.json')   # dm3 resource coords (map-static)


def segment_db(db, coords, out):
    con = sqlite3.connect(db)
    epmeta = {}
    try:
        for eid, dl, pl in con.execute(
                "SELECT e.episode_id, d.path, p.handle FROM episodes e "
                "LEFT JOIN demos d ON e.demo_id=d.demo_id "
                "LEFT JOIN players p ON e.player_id=p.player_id"):
            epmeta[eid] = (os.path.basename(dl or '?'), pl or '?')
    except sqlite3.OperationalError:
        pass
    n = 0
    eids = [r[0] for r in con.execute("SELECT DISTINCT episode_id FROM player_ticks")]
    for eid in eids:
        ticks = RLQ.episode_ticks(con, eid)
        if len(ticks) < 3:
            continue
        visits = resource_visits(ticks, coords)
        demo, player = epmeta.get(eid, ('?', '?'))
        for (i0, t0, a), (i1, t1, b) in zip(visits, visits[1:]):
            if a == b:
                continue
            seg = ticks[i0:i1 + 1]
            if len(seg) < 3:
                continue
            sig = compute_signature(seg)
            gx, gy = coords[b]
            ed = round(math.hypot(seg[-1]['x'] - gx, seg[-1]['y'] - gy), 1)
            out.write(json.dumps({"demo": demo, "player": player, "episode": eid,
                                  "from": a, "to": b, "end_dist_qu": ed, **sig}) + "\n")
            n += 1
    con.close()
    return n, len(eids)


def main(tsv, out_dir, batch=6):
    os.makedirs(out_dir, exist_ok=True)
    full = os.path.join(out_dir, 'legs_qwd_full.jsonl')
    final = os.path.join(out_dir, 'legs_qwd.jsonl')
    demos = [l.rstrip('\n').split('\t') for l in open(tsv) if l.strip()]
    coords = RLQ.load_coords(ENV)
    total_legs = total_demos = total_eps = 0
    with open(full, 'w') as out:
        for bi in range(0, len(demos), batch):
            chunk = demos[bi:bi + batch]
            btsv, bdb = f'/tmp/qb_{bi}.tsv', f'/tmp/qb_{bi}.sqlite'
            with open(btsv, 'w') as f:
                for row in chunk:
                    f.write('\t'.join(row) + '\n')
            if os.path.exists(bdb):
                os.remove(bdb)
            r = subprocess.run(
                ['python3', 'scripts/catalog_etl_qwd.py', '--catalog-dir', 'data/catalog',
                 '--demo-list', btsv, '--db', bdb, '--workers', '2', '--allow-empty'],
                cwd=REPO, capture_output=True, text=True)
            if not os.path.exists(bdb):
                print(f'batch {bi//batch+1}: NO DB (rc={r.returncode}) {r.stderr[-160:]}', flush=True)
                os.path.exists(btsv) and os.remove(btsv)
                continue
            try:
                nlegs, neps = segment_db(bdb, coords, out)
            except Exception as e:
                print(f'batch {bi//batch+1}: segment error {e}', flush=True)
                nlegs = neps = 0
            total_legs += nlegs; total_eps += neps; total_demos += len(chunk)
            for p in (bdb, btsv):
                os.path.exists(p) and os.remove(p)
            print(f'batch {bi//batch+1}/{(len(demos)+batch-1)//batch}: {len(chunk)} demos '
                  f'-> {nlegs} legs (corpus {total_demos}d {total_legs}legs)', flush=True)
    os.replace(full, final)
    print(f'DONE: {total_legs} legs from {total_demos} demos / {total_eps} episodes -> {final}')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    out_dir = sys.argv[2] if len(sys.argv) > 2 else '/tmp/route_qwd'
    main(sys.argv[1], out_dir, int(sys.argv[3]) if len(sys.argv) > 3 else 6)
