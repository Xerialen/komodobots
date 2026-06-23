# Data Consistency Audit (issue #374)

Date: 2026-06-23. Scope: the repository on `main`. Method: five parallel source-grounded
readers (goal / data sources / pipeline code / governance / doc structure), a cross-cutting
synthesis against the six data questions from the issue's best-practice attachment, and an
adversarial verification pass that re-read the cited files and dropped any claim not backed by
source. Every finding below is line-anchored and was confirmed against the actual files.

The driving question of #374: *make Git — not chat memory — hold what data we extract, where
it comes from, why, how it is transformed, what format it must have, and where the output
goes.*

## Canonical answers (the audit's ground truth)

- **Goal / why:** human-like-by-imitation stand-in bots; program of record
  `docs/18_BENCH_ITERATED_BOT_PROGRAM.md` (greenfield, 2026-06-16). MOVE brain is a
  `6→128→128→{3,3,2}` MLP, move-only by design.
- **What / how / format / destination:** see `docs/20_DATA_CONTRACT.md` and
  `configs/extraction_spec.yaml`. The pipeline has two layers (raw 11-field NDJSON shard →
  derived 6-feature model vector); the model trains on the *derived* layer.

## What this PR fixes

This PR builds the missing machine-readable memory and wires agents to it:

- `docs/20_DATA_CONTRACT.md` — prose anchor tying goal → data → contract files, both pipeline
  layers, and the change-control rule.
- `configs/extraction_spec.yaml` — line-anchored field→source→transform mapping mirroring the
  code (faithful, not aspirational).
- `schemas/training_example.schema.json` — JSON Schema for the raw shard row.
- `examples/expected_training_frame.jsonl` — golden rows that validate against the schema and
  reflect the real offline-degenerate `onground`/`pm_code` values.
- `tests/test_data_contract.py` — validates the example against the schema **and** asserts the
  builder's emitted row keys still equal the contract (the same-PR coupling, enforced in the
  existing `unittest` CI).
- `.github/pull_request_template.md` — data-contract checkboxes.
- `AGENTS.md` / `CLAUDE.md` / `codex/START_HERE.md` — read-order now points at the contract
  with the verbatim anti-drift rule.

## Findings

Severity is the auditor's; `kind` is the drift class.

### Resolved or directly addressed by this PR

| # | Finding | Kind | Sev |
|---|---|---|---|
| 1 | No machine-readable data contract anywhere (no `configs/`, `schemas/`, `examples/`, no `*.schema.json`). Format authority was scattered `komodobots.*.v1` string constants in code. | missing-memory | high |
| 2 | The 11-field NDJSON row is **not** the model input; the real 6-feature contract lives in `move_world_view.py` with no link between them. | missing-memory | high |
| 3 | Row docstring (`build_training_dataset.py:5-8`) is descriptive while code uses short keys; `frame` is a **command index**, not a time frame; `o` is float, `v` is int (rounded) — types undocumented. | doc-vs-code | high |
| 4 | No CI / PR-template coupling forcing contract+schema+example to move with extraction-code changes. | missing-memory | high |
| 5 | Agent read-order (`AGENTS.md` 1–5) never points at any data contract (0 grep hits for the contract slots). | missing-memory | high |

### Recorded for follow-up (not changed here, to keep this PR scoped and conflict-free)

| # | Finding | Kind | Sev | Recommended fix |
|---|---|---|---|---|
| 6 | `docs/14_EXECUTIVE_SUMMARY.md:3-4` names `docs/12_DM3_4ON4_STANDIN_PROGRAM.md` (demoted to `references/12`) as program of record instead of `docs/18`. | goal-drift | high | Repoint to `docs/18` + `references/12`. |
| 7 | `docs/01_PROJECT_BRIEF.md` and `README.md` still frame the goal as a **DM2 movement lab** with aim/Milton as non-goals — contradicts `docs/18` (DM3, learn aim) and `docs/00` (Milton-first). | goal-drift | high | Rewrite goal/non-goal sections to match `docs/18`; keep DM2-lab history under references. |
| 8 | `docs/03_MOVEMENT_PROBLEM.md` and `docs/09_ROADMAP.md` present the superseded staged S0–S7 / SNG track as current. | goal-drift | high | Add a "superseded by `docs/18`" banner or replace the current-stage section. |
| 9 | Duplicate doc numbers: two `09_`, two `10_`, two `13_` — every `docs/NN_` cross-reference to those is ambiguous. | numbering | med | **Resolved (this PR):** kept the more-referenced doc of each pair (`09_ROADMAP`, `10_AGENT_WEB_TESTING`, `13_QWD_MVD_FUSION_PLAN`); renamed the others to `22_TEST_CASES_AND_EVIDENCE`, `23_FROGBOTS_VS_NEW_BOT`, `24_FIRST_DM3_TRAINING_RUN` and repointed every inbound reference. |
| 10 | Broken links: `docs/15_LIVE_VALIDATION_LOOP.md`, `docs/12_DM3_4ON4_STANDIN_PROGRAM.md`, `docs/11_EXTERNAL_MOVEMENT_AI_SOURCES.md` are referenced but do not exist on `main`. | doc-vs-doc | med | Repoint to `references/12` and the correct live-validation doc, or remove. |
| 11 | Canonical corpus `~/ctv_decomp` is absent from the designated source docs (`docs/02`, `docs/06`); appears only in `docs/13`/`docs/18`. | doc-vs-doc | med | Now recorded in `docs/20` + `extraction_spec.yaml`; still add to `docs/02`/`06`. |
| 12 | MVD parser exists in ≥3 commits (`qw-analyze-v20` binary, source `fab7808`, bundle `7d83ebe`) with no pinned canonical, despite a pin-before-evidence warning. | doc-vs-doc | med | Declare the canonical parser commit in the source map and gate regression evidence on it. |
| 13 | PR template had no schema/contract/extraction/golden checkboxes (now added). | missing-memory | med | Addressed. |
| 14 | Demo-count headline differs by doc (478 / 465 / 433; 472 = demolist rows). | doc-vs-doc | low | State raw/indexed/kept once (done in `docs/20`); reference everywhere. |

### Follow-up resolution status

- Findings **6, 7, 8, 10** (goal-drift banners + broken-link repointing) were resolved in
  PR #377 (goal docs anchored to `docs/18`; `docs/12`/`docs/15`/`docs/16` references repointed
  or dropped).
- Finding **9** (duplicate doc numbers) is resolved in this PR — see the row above.
- Findings **11, 12, 14** remain open as recorded.

A claim from the first synthesis pass — a `verdicts.json` v1-vs-v2 schema split in `docs/06`
— was **dropped** by the verification pass: `docs/06` contains only `komodobots.verdicts.v1`
at that line; no `v2`/`certifications[]` variant was present. It is listed here only to record
that it was checked and not substantiated.

## Why we did NOT renumber or rewrite the goal docs in this PR

The best-practice attachment prescribes `05_DECISION_LOG` / `06_FINDINGS_LOG`; this repo
already has those at `08_`/`07_`, and `05_`/`06_` are `HEADLESS_TEST_ENV` /
`DATA_AND_MVD_PIPELINE`. Adopting the prescribed numbers verbatim would clobber existing docs.
The senior-engineer decision is **reconcile, not duplicate**: map the issue's slots onto the
files that already exist, and place the genuinely new contract artifacts in non-colliding
namespaces (`configs/`, `schemas/`, `examples/`, `docs/20`/`docs/21`). The goal-drift and
renumbering fixes (findings 6–10) are higher-blast-radius edits that overlap an active feature
branch; they are recorded here as the prioritized follow-up rather than bundled into the
data-contract PR.
