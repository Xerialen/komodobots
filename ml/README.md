# ml/ — out-of-tree feature build & training (WSL2)

This subtree holds the **deps-heavy** half of the data architecture: the Parquet
feature build, the normalization fit, and model training. It is deliberately
**outside the stdlib-only merge gate**.

## Why it's separate

The repo's hard merge gate (`.github/workflows/pr-tests.yml`) runs
`python -m unittest` on **bare Python 3.12 with no `pip install`**. Anything that
imports `duckdb`, `pyarrow`, `pandera`, `numpy`, or `torch` would break it. So:

| | in-tree (`scripts/`, `tests/`) | out-of-tree (`ml/`) |
|---|---|---|
| deps | **stdlib only** | `requirements.txt` (DuckDB/Arrow/torch/…) |
| CI | `pr-tests.yml` — **the merge gate** | `ml-tests.yml` — **separate, non-gating** |
| runs on | every PR, bare Python | on demand / nightly, in a venv |
| imports `scripts/features` | — | **yes** (shared math, see Parity) |

The unit suite never imports anything in `ml/`, so `ml/` can use the full
scientific-Python stack without ever threatening the gate.

## Setup (WSL2, RTX 4090 box)

Per the host policy, model/data work runs in **WSL2 Ubuntu 24.04**, never Windows-native
(so `wsl --shutdown` frees all VRAM/RAM instantly for gaming):

```bash
cd ml
python3 -m venv .venv-ml
source .venv-ml/bin/activate
pip install -r requirements.txt
```

> Installing these deps is a system change — get the owner's OK first (per CLAUDE.md).

## Stages

1. **`pipeline/build_features.py`** — load the SQLite catalog (via the in-tree
   `catalog_load`), join the fixture's `actor_ticks` to the static item/region
   catalogs with a **DuckDB ASOF point-in-time join** (`t <= tick`, no future
   leakage), apply the **shared** `scripts/features` transforms, and emit a Parquet
   feature shard to `gold/features/`.
2. **`pipeline/normalize_fit.py`** — stream the TRAIN split with Welford/Chan to
   produce a frozen `normalization_stats.json` (the artifact `scripts/features`
   reads at train *and* inference).
3. **training** (later) — sequence model over `actor_ticks` windows with the
   `agent_observation` masking from `00-DATA-ARCHITECTURE.md` §2.8.

## Parity guarantee

`ml/` imports the **same** `scripts/features` transforms the live bot uses. The
offline Parquet build and the in-tree path therefore produce **byte-identical**
normalized vectors on a given tick — verified by `ml/tests/test_parity.py`. The
heavy `pandera` dataframe-schema check is the out-of-tree counterpart to the
in-tree stdlib `scripts/validate_catalog.py`.

## Repo destination

`ml/` at the repo root; `ml-tests.yml` under `.github/workflows/`.
