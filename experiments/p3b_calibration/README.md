# P3b calibration — mode-23 control law over pmove_sim (issue #69)

The calibration gate between the live P3 carrot phase and the A2 offline parameter
sweep (#74): the deployed mode-23 config-5 control law, ported over the validated
`scripts/pmove_sim.py` physics with a seeded frogbot-nav stub, must reproduce the
LIVE c5 block's behavior (recorded lesson: replay-faithful != policy-faithful)
before any sweep result is trusted.

**Verdict: FAITHFUL** — see `evidence/calibration-report.md` (comparator
recomputation, pre-registered tolerances, per-config results, three-layer port
validation, seam audit vs the deployed KTX source, and the trust bounds the A2
sweep inherits).

Code: `scripts/mode23_sim.py` (simulator + `calibrate` / `run` /
`audit-selection` CLIs). Tests: `tests/test_mode23_sim.py`.

Evidence:
- `evidence/calibration-report.md` — the report + seam audit
- `evidence/fbmarker-dm3.txt` — committed live marker-graph dump (sim input)
- `evidence/calibration-c{1,4,5}.json` — per-seed results, 30 seeds per config
