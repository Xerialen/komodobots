# HANDOFF — DM3 4on4 stand-in ML program (temporary, 2026-06-14)

**Temporary hand-off for the next agent.** Read this first, then
`experiments/dm3_4on4_program_status.md` (the longer-lived status doc). Delete this
file once its contents are folded into the status doc / your understanding.

---

## 0. TL;DR — where we are right now

- Branch **`ml/dm3-4on4-standin`** (separate worktree at `C:\Users\benya\projects\quakeworld\komodobots-ml`),
  HEAD **`b45a694`**, **pushed to origin**, 11 commits ahead of `main` (`e73efc8`).
- Stage-2 **MOVE behavioural-cloning policy = GO** (already proven last session).
- This session added: the multi-physent sim foundation, the bhop-formula ingest spec
  (+ issue #175), the maintained trained-demo provenance manifest, and a clean
  "ONLY dm3 4on4" corpus definition.
- **No retrain is pending or needed right now** (see §3). The next *substantive* build
  is the opponent-collision sync OR the DECIDE/economy tier — NOT more MOVE training.

---

## 1. Where everything lives

- **Worktree (do work here):** `C:\Users\benya\projects\quakeworld\komodobots-ml`, branch `ml/dm3-4on4-standin`.
  - NOTE: the *main* checkout `…\komodobots` has unrelated pre-existing dirty files from a
    prior session — leave them; not ours.
- **Program of record:** `docs/18_BENCH_ITERATED_BOT_PROGRAM.md` (greenfield, 2026-06-16);
  earlier staged spec kept for background at `references/12_DM3_4ON4_STANDIN_PROGRAM.md`. Decision:
  `docs/08_DECISION_LOG.md` (Decision Point Alpha → Megalodon Milton).
- **WSL2 Ubuntu-24.04 (heavy compute + data; gitignored):**
  - venv `~/komodobots-ml-venv` (torch 2.6.0+cu124, RTX 4090)
  - `~/move_bc_shards/` (9.1 GB NDJSON state,action shards, 465 demos)
  - `~/move_bc_dataset.npz` (packed clean training set), `~/move_bc_policy.pt` (trained MoveMLP)
  - `~/ctv_decomp/` (478 decompressed self-POV `.qwd`), `~/qizmo_bundle/` (Qizmo .qwz decompressor)
- **Run WSL python via:** `wsl.exe -d Ubuntu-24.04 -e bash -lc '… ~/komodobots-ml-venv/bin/python …'`
  (repo is reachable inside WSL at `/mnt/c/Users/benya/projects/quakeworld/komodobots-ml`).
- **dm3 BSP** (original id content, not committed): `C:\nQuake\qw\maps\dm3.bsp` (Win) /
  `/mnt/c/nQuake/qw/maps/dm3.bsp` (WSL).

---

## 2. What this session did (commits b152aa4 → b45a694)

1. **`b152aa4` — multi-physent trace foundation + closed-loop ceiling diagnosis.**
   - ROOT CAUSE of the "~1 s closed-loop validation ceiling": the *recorded-human*
     controller itself drifts to **88.9 qu by 2 s** while the single-player SNG→RL route
     stays at 0.2 qu over ~9 s. So the cap is the sim **omitting physics**, dominated by
     **opponent-player collision (78.6 % of dataset contamination)**, NOT the physics core
     and NOT brush submodels. Absolute trajectory-match is also chaos-capped long-horizon.
     Doc: `experiments/stage2/move-bc-train/closed-loop-ceiling-diagnosis.md`.
   - `scripts/pmove_sim.py`: `player_trace` now iterates world + a `PhysEnt` list
     (nearest-hit wins); added `build_box_hull` (Quake `SV_InitBoxHull` port),
     `make_player_physent` (Minkowski-expanded opponent box), `Pmove.load_submodels()`
     (6 dm3 brush submodels, at-rest). **Worldmodel-only default is byte-identical to the
     validated baseline** (full `run_pmove_validation.py` regression unchanged:
     human 0.204/0.121/0.178, bot anchored p95 0.004, edge 529.08).
   - Tests: `tests/test_physent_collision.py` — regression + swept box block + submodel
     opt-in, ALL PASS. Run: `python tests/test_physent_collision.py`.
2. **`bf2c181` + `9c9bb09` — strict spec to ingest Benjamin's cracked bhop formula into MOVE.**
   - `experiments/stage2/move-bc-train/bhop-formula-ingest-spec.md`. The formula must become
     a pure per-tick `state → (fwd,side,jump)` function (a better `airlaw_action`), delivered
     as Python fn / lookup table / parametric / reference-trace. Appendix A folds the full
     data-source + bhop-merge discussion so it reads standalone.
   - **GitHub issue #175** frames this as the North-Star critical path; a comment on it lists
     the spec's sources/provenance. (Issue #175 = bhop-ingest spec, NOT the demo manifest.)
   - **Benjamin will not have the formula for a while** — do NOT block on it.
3. **`0bfbc88` — maintained trained-demo provenance manifest.**
   - `experiments/stage2/move-bc-train/TRAINED_DEMOS.md` (+ `trained-demos.tsv`), generated
     by `build_trained_demos_manifest.py` from the npz (ground truth). 462 demos
     (393 train / 69 val), 5.85M clean frames, 251 distinct players; totals match
     `train_metrics.json` exactly. **REGENERATE after every training run** (stamps dataset +
     checkpoint sha256). Standing requirement — see auto-memory `maintain-trained-demos-list`.
4. **`b45a694` — clean "ONLY dm3 4on4" corpus definition (NO retrain).**
   - `make_dm3_4on4_clean_demolist.py` → `dm3_4on4_clean_allowlist.txt` (433 demos) +
     `dm3_4on4_clean_selection.md` (39 excluded: 22 trick, 7 wrong-map, 5 CTF, 2 3v3,
     1 domination, 1 howto, 1 comedy). Content-true map filter caught 7 demos tagged `4v4`
     but actually on e1m2/e3m6/e2m5.

---

## 3. Key DECISIONS made this session (don't relitigate)

- **Source to begin with = QWD** (movement is the North-Star first rung; the contamination is
  in the QWD MOVE corpus; pipeline exists). MVD/DECIDE is the biggest *unblocked* value AFTER,
  since the formula is far off.
- **We did NOT retrain, on purpose.** The 39 contaminant demos are only **0.49 % of trained
  frames** (28,483 / 5,847,254), so a clean retrain would be behaviorally ~identical. The
  durable fix is the corpus *definition* (the allowlist), not a new model. Defer ONE clean
  retrain to the per-player tier, after the two follow-ups below.
- **#170 review deferred** ("too early" — owner call). Branch is pushed but NOT opening a PR to
  `main` yet, so the #170 cross-model-review gate is not tripped. Do the non-Claude review only
  when an ML PR to `main` is actually raised.

---

## 4. OPEN threads / what's next (the forward fork)

Ranked by unblocked value, given the formula is far off and MOVE is validation-capped:

1. **DECIDE / economy tier from MVDs** — biggest *unblocked* value. Trainable today from the
   massive MVD corpus (all-player positions/items/economy); needs neither the formula nor the
   opponent sync. New tier (greenfield: intent-labeling rules, no torch pipeline yet).
2. **Opponent-ghost collision** — unlocks validated MOVE past ~1 s. The physent foundation is
   built; needs per-tick opponent positions. CHEAPEST source = re-parse the SAME `.qwd` (it
   already records other players' positions, PVS-culled) — POV-INTERNAL, no MVD needed. A
   matching-MVD sync is a fidelity upgrade AND the Stage-3 AIM target-selection prereq.
   Success metric: the `recorded`-human closed-loop route_err at 2 s drops from 88.9 qu.
3. **Two corpus follow-ups (prereqs for the per-player Milton tier; NOT for a pooled retrain):**
   - **Roster-verify** the 367 untagged SmackDown* demos are genuinely 4on4 (in-demo
     connected-player count; `engine/demoparser` (Rust) exists at `…/quakeworld/engine/demoparser`).
   - **Re-attribute POV players** from in-demo userinfo — the current `player` column is an
     unreliable filename heuristic (e.g. tokens like `round1`, `sd3`, `trick`).
4. **The bhop formula** — slot into the `airlaw_action` seam per the ingest spec when Benjamin
   delivers it; it's the path to the speed ceiling ("max skill first"), an enhancement, not a gate.
5. **Stage 3 learned AIM** / **moving submodels** — later; both inherit the validation work.

---

## 5. Conventions / guardrails (enforced)

- **Commit/push only when asked.** Co-author trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- **gh comments/issues MUST lead with** `**Claude** (on behalf of Xerial):` (hook-enforced).
- **#170:** any PR authored by one model needs a *different-LLM* review before merge.
- **Role separation:** don't act as both Coder and independent Reviewer for the same PR.
- **Surface assumptions / validate before reporting / don't tune around findings** (this is how
  the ceiling diagnosis and the 0.49 % retrain call were handled — keep that bar).
- **MVD has NO input commands; only QWD has them** → bhop solvable only from QWD. MVD = macro/
  economy + all-player positions. This split forces the 3-tier architecture; the corpora are
  abundant-but-unmatched BY DESIGN (tiers joined by actuator-agnostic contract, not matched games).

---

## 6. Quick verify commands

- Physent tests: `python tests/test_physent_collision.py`
- pmove regression: `python scripts/run_pmove_validation.py --out /tmp/v`
- Regenerate trained-demo manifest (WSL): `~/komodobots-ml-venv/bin/python experiments/stage2/move-bc-train/build_trained_demos_manifest.py`
- Regenerate clean allowlist: `python experiments/stage2/move-bc-dataset/make_dm3_4on4_clean_demolist.py`

---

## 7. Canonical doc pointers

- Program: `docs/18_BENCH_ITERATED_BOT_PROGRAM.md` (spec background: `references/12_DM3_4ON4_STANDIN_PROGRAM.md`) · Decision: `docs/08_DECISION_LOG.md` · North Star: `docs/00_VISION_AND_NORTH_STAR.md`
- Status/resume: `experiments/dm3_4on4_program_status.md`
- Ceiling diagnosis: `experiments/stage2/move-bc-train/closed-loop-ceiling-diagnosis.md`
- Bhop ingest spec: `experiments/stage2/move-bc-train/bhop-formula-ingest-spec.md` (+ issue #175)
- Demo provenance: `experiments/stage2/move-bc-train/TRAINED_DEMOS.md`, `…/trained-demos.tsv`
- Clean corpus: `experiments/stage2/move-bc-dataset/dm3_4on4_clean_allowlist.txt` + `…_selection.md`
