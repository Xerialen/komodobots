#!/usr/bin/env python3
"""A3 #75 pre-flight probe (sim-only, NO lab attempts): what does
deleg_vh_max 320 ALONE (no spin-up loop) produce on rung B?

The screen-set amendment names screen 2 "deleg_vh_max 320 family (512-median
in sim, cvar-only)". The design grids show every 512.3-median config was
spinup76@220/4s + deleg_vh_max 320 — the spin-up knob needs goal-seam cvars
NOT in the 3-cvar KTX change. This probe measures the deleg-only config so
the screen-2 ambiguity can be resolved (or escalated) BEFORE any lab run.

Anchor: spiker_base on training seeds must reproduce the recorded
edge_median 446.5 / n526 1 / max 554.5 exactly (proves the probe wiring is
the design-grid harness).
"""
import logging
import json
import multiprocessing
import statistics
import sys
from pathlib import Path


LOGGER = logging.getLogger(__name__)
SCRIPTS = Path(__file__).resolve().parents[4] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from mode23_sim import LawParams                       # noqa: E402
from mode23_sweep import EDGE_TARGET                   # noqa: E402
import tail_autopsy as ta                              # noqa: E402

SPIKER = dict(pass_r=130.0, numerator=5.0, swing=12.0, turn_thresh=35.0,
              corner_thresh=45.0, corner_aim=85.0)
LAUNCHC = dict(pass_r=100.0, numerator=5.0, swing=12.0, turn_thresh=35.0,
               corner_thresh=45.0, corner_aim=85.0)

CONFIGS = {
    "spiker_base": LawParams(**SPIKER),
    "spiker_d320_only": LawParams(**SPIKER, deleg_vh_max=320.0),
    "launchbase_d320_only": LawParams(**LAUNCHC, deleg_vh_max=320.0),
}


def agg(vals):
    present = sorted(v for v in vals if v is not None)
    return {
        "edge_values": vals,
        "edge_n": len(present),
        "edge_median": round(statistics.median(present), 1) if present else None,
        "edge_max": present[-1] if present else None,
        "n_526": sum(1 for v in present if v >= EDGE_TARGET),
    }


def main():
    workers = 12
    bsp, dump = r"C:\nQuake\qw\maps\dm3.bsp", None
    out = {}
    with multiprocessing.Pool(workers, initializer=ta._init_worker,
                              initargs=(bsp, dump)) as pool:
        for name, p in CONFIGS.items():
            for label, seeds in (("train", tuple(range(1, 31))),
                                 ("fresh", tuple(range(31, 61)))):
                jobs = [(name, p.__dict__, s) for s in seeds]
                res = pool.map(ta.eval_rung_b_seed, jobs)
                vals = [v for (_n, _s, v) in res]
                out[f"{name}/{label}"] = agg(vals)
                print(name, label, json.dumps(
                    {k: v for k, v in out[f'{name}/{label}'].items()
                     if k != 'edge_values'}), flush=True)

    # anchor assert: spiker_base on training seeds = the recorded r1 row
    a = out["spiker_base/train"]
    assert a["edge_median"] == 446.5 and a["n_526"] == 1 \
        and a["edge_max"] == 554.5 and a["edge_n"] == 16, a
    print("ANCHOR OK (spiker_base/train == design-grid r1 record)")
    Path(__file__).with_suffix(".json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
