# INTEGRATION.md — absorbing the data architecture into the KomodoBots lab

The exact runbook for landing this deliverable into `Xerialen/komodobots`. It respects
the lab's two hard constraints:

1. **Stdlib-only merge gate.** `pr-tests.yml` runs `python -m unittest` on bare Python
   3.12 with **no `pip install`**. Nothing under `scripts/` or `tests/` may import a
   third-party package.
2. **Three-agent loop.** Claude is the **Coder** — it opens/updates the stage PR but
   **must not merge, must not stand in for the Reviewer, and must not self-apply
   `gate: ready`** (AGENTS.md). Independent cross-model review (Codex) is required.

Strategy **A**: small in-tree stdlib catalog + shared feature-math, CI-gated; a
first-class out-of-tree `ml/` subtree with its own deps + a separate, **non-gating** CI.

---

## 0. Staging → repo file map

Everything is built and tested in `research/komodobots-ml-data-architecture/integration/`.
Copy into the repo as follows:

| staging path (`integration/…`) | repo destination | gate |
|---|---|---|
| `scripts/catalog_schema.sql` | `scripts/catalog_schema.sql` | **stdlib CI** |
| `scripts/catalog_load.py` | `scripts/catalog_load.py` | **stdlib CI** |
| `scripts/features/` (pkg) | `scripts/features/` | **stdlib CI** (shared w/ bot) |
| `scripts/validate_catalog.py` | `scripts/validate_catalog.py` | **stdlib CI** |
| `tests/test_catalog_load.py` | `tests/test_catalog_load.py` | **stdlib CI** |
| `tests/test_features.py` | `tests/test_features.py` | **stdlib CI** |
| `tests/test_validate_catalog.py` | `tests/test_validate_catalog.py` | **stdlib CI** |
| `ml/` (requirements, README, pipeline/, tests/) | `ml/` | **non-gating** |
| `.github/workflows/ml-tests.yml` | `.github/workflows/ml-tests.yml` | non-gating CI |
| `../schema/*.json`, `../schema/catalog.sql` | `data/catalog/` | data (see §1) |
| `../fixtures/dm3_milton_211436/` | `data/fixtures/dm3_milton_211436/` | data |

`../schema/feature_registry.json` + `dataset_spec.yaml` stay **reference-only** in
`data/catalog/` — read by `ml/` (PyYAML) or mirrored to JSON for in-tree use. They are
never imported by the unit suite.

## 1. Data placement & the test path constant

The catalogs/fixtures are data, not code. Put them under `data/catalog/` and
`data/fixtures/`. Then update the one path constant at the top of each in-tree test:

```python
# tests/test_catalog_load.py, test_validate_catalog.py
CATALOG_DIR = REPO_ROOT / "data" / "catalog"
FIXTURE_DIR = REPO_ROOT / "data" / "fixtures" / "dm3_milton_211436"
```

(In staging they point at `../../schema` and `../../fixtures`. This is the *only* edit
needed when moving from staging to the repo.) Large fixtures may be DVC-tracked; the
JSON catalogs are small enough to commit directly.

## 2. Command sequence (run from repo root)

```bash
# 2a. in-tree stdlib suite — exactly what the merge gate runs
python -m unittest discover -s tests -p "test_*.py" -v

# 2b. stdlib-safety check (the gate would catch a violation, but verify locally)
! grep -rnE "^\s*(import|from)\s+(duckdb|pyarrow|pandas|pandera|numpy|torch|yaml)" scripts tests

# 2c. build the catalog DB + validate (CLI entry points)
python scripts/catalog_load.py --catalog-dir data/catalog \
    --fixture-dir data/fixtures/dm3_milton_211436 --db data/catalog/dm3.sqlite
python scripts/validate_catalog.py --catalog-dir data/catalog \
    --fixture-dir data/fixtures/dm3_milton_211436 \
    --stats data/catalog/normalization_stats.template.json --expect-items 51

# 2d. out-of-tree ml/ (WSL2 venv; NOT part of the gate)
cd ml && python3 -m venv .venv-ml && source .venv-ml/bin/activate
pip install -r requirements.txt
python -m unittest discover -s tests -p "test_*.py" -v
python pipeline/build_features.py --catalog-dir ../data/catalog \
    --fixture-dir ../data/fixtures/dm3_milton_211436 \
    --stats ../data/catalog/normalization_stats.template.json \
    --out gold/features/dm3_milton_211436.parquet
```

## 3. Per-step acceptance checks

| step | passes when |
|---|---|
| 2a | full unit suite green (existing tests + 24 new in-tree tests) |
| 2b | grep finds **nothing** (stdlib-only holds) |
| 2c load | prints summary: 51 items, 299 markers (234 static), >1000 nav_edges, team_frags `{Book:294, 3b:80}` |
| 2c validate | prints `OK: catalog valid` (exit 0) |
| 2d ml tests | green incl. the DuckDB ASOF + Parquet-emit smoke (skipped only if deps absent) |
| 2d build | writes `gold/features/dm3_milton_211436.parquet` (8 actor rows); PIT join yields 9 frag rows with no future leakage |

## 4. Docs routing (AGENTS.md mandatory)

- **`docs/08_DECISION_LOG.md`** — append the architecture decision: *adopt this data
  layer; Strategy A (in-tree stdlib catalog + shared feature-math; out-of-tree `ml/`
  with non-gating CI)*. (Draft in `docs/decision-entry.md` here — see E2.)
- **`docs/20_ML_DATA_ARCHITECTURE.md`** — new canonical summary linking `data/catalog/`
  and `WORKED-EXAMPLE.md`. The repo's docs are non-sequential (00–19 with gaps/dups); 20 is the next free number on main.
  **AGENTS.md defines no rule for new top-level numbered docs** — flag this in the PR
  description and get the owner's OK before adding it, or fold the summary into an
  existing doc if the owner prefers.
- Any finding that emerges during integration → `docs/07_FINDINGS_LOG.md`.

## 5. PR / CI plan (the part Claude does NOT finish unilaterally)

1. Branch from the lab's default; stage as **one PR** (or split in-tree vs `ml/` if the
   reviewer prefers smaller diffs).
2. The PR adds **two** CI surfaces:
   - the existing `pr-tests.yml` (stdlib gate) keeps passing — verify it does **not** see
     any new third-party import;
   - new `ml-tests.yml` runs as a **separate, informational** workflow. **Do not add it
     to branch-protection required checks.**
3. Coder responsibilities end at: open the PR, update docs/evidence, respond to review.
   **Claude must not merge, must not apply `gate: ready`.** The merge is executed by
   `review-gate-merge.yml` after the Reviewer (Codex / a different-LLM agent) sets
   `gate: ready` — independent cross-model review is mandatory (CLAUDE.md conventions).
4. Any GitHub comment Claude posts must lead with `**Claude** (on behalf of Xerial):`.

## 6. What this does NOT include (tracked separately)

- **`bsp_geom.py`** — the PVS + hull-0 line-of-sight engine that turns the schema's
  `actor_visibility` columns into real masking. The schema, fixtures, and
  `WORKED-EXAMPLE.md` lay the ground for it; the geometry code is its own task.
- Real training (the `ml/` training stage past the feature build).
- A dm2 catalog (dm2.bsp is local; trivial follow-up, out of scope for 4on4-first).
