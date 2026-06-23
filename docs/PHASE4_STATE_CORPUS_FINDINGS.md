# Phase 4 — Human 4on4 dm3 state-distribution corpus: extraction findings (interim)

Status: **extraction COMPLETE (clean)** · **verification IN PROGRESS** (foreign-key check running) ·
**summary/provenance JSON HELD** until verification is green.

This note records the findings from the heavy Phase-4 extraction so they can be reviewed against the
[ML Evidence Chain Gate](21_ML_EVIDENCE_CHAIN_GATE.md) before the provenance JSON is committed. It is
*interim* by design: the live `PRAGMA foreign_key_check` over 534M rows is still running, so the
canonical summary file is deliberately not in this commit.

## What ran

`scripts/catalog_etl_mvd.py` over the 1537-demo TRAIN manifest
(`data/corpus/human_4on4_dm3_mvd_manifest.json`) on **servexeri** (demos are servexeri-local; the run
is pinned there). Parser pinned to the **schema-33** `qw-analyze` binary (sha `6954ffb6`), which emits
per-tick view-yaw (`vya`), pitch, and velocity; geometric on-ground via `dm3.bsp` floor-trace.

The run used a scratch **streaming patch** (PHASE4-STREAM) of the ETL — see the caveat below; porting
it to the merged ETL is tracked separately.

## Results (from the run's own summary)

| Field | Value |
|---|---|
| `demos_loaded` | **1536** |
| `demos_failed` | **1** |
| `episodes` | 949,814 |
| `player_ticks` | 534,627,531 |
| `actions` | 534,627,531 |
| `onground_distinct` | `[0, 1]` |
| split counts (sha-hash) | train **1088** / val **222** / test **226** |

The single failure is `blixem__fs__vs_tot_dm3_2.mvd` — its `pos` stream is missing
`vya/vp/vx/vy/vz`, i.e. that source recording is **not** a schema-33 export. It was correctly skipped
and logged as an error, not silently dropped. So `demos_loaded == 1537 − 1`.

### Label hold-out (the whole point of this corpus)

| `strafe_label_stats` | Value | Meaning |
|---|---|---|
| `held_out_action_rows` | **534,627,531** | == total actions — **every** recovered action row is held out |
| `trainable_strafe_sign_rows` | **0** | nothing is trainable yet |
| `above_gate_strafe_sign_rows` | 93,073,575 | recoverable bunnyhop-regime (≥400 u/s) strafe signal, recorded for later |
| `jump_press_rows` / `jump_press_rate` | 6,208,325 / 0.0116 | jump events recorded |

Every `actions` row carries `label_source='idm'` and `is_interp=1` — the corpus is a **state
distribution**, not a label set. Nothing trains on recovered actions until per-head weights (deferred)
unlock the trustworthy heads.

## Verification (post-extraction gate)

- **Green from the run summary:** demos count (1536 = 1537 − 1 expected failure), non-empty tables,
  `onground_distinct == [0,1]`, hold-out intact (`trainable == 0`, `held_out == total`), splits.
- **Running:** a live `PRAGMA foreign_key_check` + DB-side on-ground / hold-out recount over the
  125 GB / 534M-row database (IO-bound, ~1–3 h). This is the meaningful test that the streaming-insert
  patch did not orphan any rows.
- **Held:** the canonical `data/catalog/dm3_4on4_human1537.summary.json` is **not** committed until
  that check returns `foreign_key_violations == 0`.

## Evidence-chain gate mapping (`docs/21_ML_EVIDENCE_CHAIN_GATE.md`)

- **Item 1 (data used / ignored):** human 4on4 dm3 multi-view demos (MVD), 1537 TRAIN from the
  servexeri archive; bot games and non-dm3 excluded; single-player QuakeWorld demos (QWD) and the
  Milton believability anchor are out of scope here.
- **Item 2 (provenance):** `demos.sha256` (unique), parser binary sha `6954ffb6` (schema-33 —
  **required**; the schema-21 selection binary sha `3bc388bb` silently drops view-yaw and would
  corrupt strafe-sign recovery), manifest content-locked by sha256 + size.
- **Item 3 (is the label a label):** MVDs record server-frame **state**, not the usercmd input
  stream. Movement is **recovered by inverse dynamics** (`label_source='idm'`, not `qwd_usercmd`);
  air-strafe sign trusted only in the ≥400 u/s bunnyhop regime; `forwardmove` is unrecoverable and
  never used; all recovered rows held out (`is_interp=1`).
- **Item 4 (measurement planes):** on-ground is a geometric `pmove_sim` floor-trace **proxy**
  (`player_ticks.onground_is_proxy`), a distinct plane from a live KTX on-ground flag.
- **Item 6 (leakage):** whole-demo splits; believability anchors kept out of training evidence.
- **Items 7 / 10 (baseline / kill criteria):** not applicable — this is a data-extraction step that
  trains no model; baselines and kill criteria attach to the training runs that consume the corpus.

## PHASE4-STREAM caveat (must travel with the corpus)

The corpus was produced by a **scratch-patched** ETL: per-demo streaming insert + bounded worker
window (the merged `build()` accumulates all frames in RAM and would run the box out of memory on the
full corpus) + a **deterministic sha-hash split** (~70/15/15). The patch changes:
- **insert timing** — no difference to row values; and
- **split assignment** — deterministic per-demo sha-hash vs. the merged ETL's positional split;
  this affects only the train/val/test label of a demo, not any state or action value.

Porting this fix to the merged ETL (with a bounded-memory test) is tracked as a follow-up.

## Use of the corpus

Reinforcement-learning **state prior** + reward / cadence anchor (`plans/rl-plan.md`, STEP 0). Action
labels stay held out until per-head weights unlock the trustworthy heads (aim / yaw, jump, in-regime
strafe-sign); `forwardmove` is never used. The canonical ~125 GB database stays on servexeri (not in
git, not on the build box); the pinnacle copy is deferred until reinforcement-learning is greenlit.
