#!/usr/bin/env python3
"""merge_envelopes.py — unified per-route signature ENVELOPE across corpora.

Merges the per-leg signatures from the 4on4 MVD (book-vs-mix, 8 players) and the elite 1v1
.qwd corpus (SmackDown3) into one believability envelope per route, keeping per-source counts
(movement along a route is a route+skill property — the union widens the human band; tactics
differ by team size but movement does not). The end_dist validation (~198 qu in both corpora)
confirmed the coordinate frames match, so the legs are directly poolable.

Usage: merge_envelopes.py <mvd_legs.jsonl> <qwd_legs.jsonl> <out.json>
"""
import sys, os, json
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from route_legs import route_env, pctl  # noqa: E402


def load(path, source):
    out = []
    for line in open(path):
        L = json.loads(line)
        L['_source'] = source
        out.append(L)
    return out


def main(mvd_legs, qwd_legs, out_json):
    legs = load(mvd_legs, 'mvd_4on4') + load(qwd_legs, 'qwd_1v1')

    byroute = defaultdict(list)
    for L in legs:
        byroute[(L['from'], L['to'])].append(L)

    envs = []
    for (a, b), ls in sorted(byroute.items(), key=lambda kv: -len(kv[1])):
        durs = sorted(L['dur_s'] for L in ls)
        core = [L for L in ls if L['dur_s'] <= durs[len(durs) // 2]] or ls
        src = defaultdict(int)
        for L in ls:
            src[L['_source']] += 1
        e = {'from': a, 'to': b, 'count': len(ls), 'core_count': len(core), 'by_source': dict(src),
             'end_dist_qu_median': pctl([L['end_dist_qu'] for L in ls], .50)}
        e.update(route_env(core))
        e['all_traffic'] = route_env(ls)
        envs.append(e)

    n_mvd = sum(1 for L in legs if L['_source'] == 'mvd_4on4')
    n_qwd = len(legs) - n_mvd
    out = {'schema': 'komodobots.route_envelopes_merged.v1',
           'sources': ['book-vs-mix 4on4 MVD (8 players, 1 game)',
                       'SmackDown3 1v1 .qwd (97 elite POV demos)'],
           'caveat': 'tactics differ 1v1 vs 4on4; MOVEMENT along a route is the same map+physics. '
                     'jump cadence = v1 vz-proxy (MVD) / geometric-onground available (.qwd).',
           'n_legs': len(legs), 'n_legs_mvd_4on4': n_mvd, 'n_legs_qwd_1v1': n_qwd,
           'distinct_routes': len(envs), 'envelopes': envs}
    json.dump(out, open(out_json, 'w'), indent=1)

    print(f"merged {len(legs)} legs ({n_mvd} mvd_4on4 + {n_qwd} qwd_1v1) / {len(envs)} routes -> {out_json}")
    print("\nroute                mvd  qwd  core dur(med) hs(med) straight jumpInt(med)")
    for e in envs[:20]:
        ji = e['jump_interval_s']['median'] if e['jump_interval_s'] else None
        s = e['by_source']
        print(f"  {e['from']:8}->{e['to']:8} {s.get('mvd_4on4',0):4} {s.get('qwd_1v1',0):4}  "
              f"{e['core_count']:3}  {e['dur_s']['median']:4.1f}s  {e['hs_mean']['median']:4.0f}   "
              f"{e['straightness']['median']:.2f}    {ji}")


if __name__ == '__main__':
    if len(sys.argv) < 4:
        raise SystemExit(__doc__)
    main(sys.argv[1], sys.argv[2], sys.argv[3])
