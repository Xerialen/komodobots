# P3b A2 — pre-registered offline sweep: corner conversion + launch-edge speed (issue #74)

The offline parameter sweep over the mode-23 control law, run on the A1-calibrated
simulator (`scripts/mode23_sim.py`, gate FAITHFUL — see
`experiments/p3b_calibration/`). Two rungs per config, seeds 1..30 identical across
configs:

- **Rung A** (floor + tiebreak): the exact A1 sng_shortcut2 protocol — reach
  (floor = sim-c5 baseline 12/30) and the Gate-2 corner conversion rate
  (markers 206/207, P2 decomposition convention).
- **Rung B** (primary): the STEP-0 *surrogate* for the >=526 launch-edge
  objective — the directed walkable route to RL never crosses the census
  launch edge (resolved offline before pre-registering; also answers D1 #77
  pre-check (a) = NO), so edge speed is measured on the directed bridge
  approach: spawn m75, pin marker 148, `route_metrics.edge_speed` (A0 metric,
  constants unchanged) truncated at first pin arrival.

Sweep space, seed set, ranking function, floors, staging rule, and off-ramp were
declared in the loop ledger BEFORE the first sweep run; the full pre-registration
text is reproduced in `evidence/sweep-report.md`.

Code: `scripts/mode23_sweep.py` (grid, runner, ranking, report CLIs).
Tests: `tests/test_mode23_sweep.py` + the governor/carrot-lead/params additions
in `tests/test_mode23_sim.py`.

Evidence:
- `evidence/sweep-report.md` — pre-registration, STEP-0 geometry resolution,
  ranked results, transfer candidates, trust-bound phrasing
- `evidence/ranked.json` / `evidence/ranked.md` — the final ranked table
- `evidence/stage1-aggregates.jsonl` / `evidence/stage2-aggregates.jsonl` —
  per-config aggregates (params + reach/tws/corner/edge stats, per-seed edge
  values), full per-seed rung-A records stripped for size
- `evidence/candidates.json` — the 4 transfer candidates' full records
