# Phase 4 — Human 4on4 dm3 state-distribution corpus: extraction findings

Status: **extraction COMPLETE** · **verification GREEN** · **provenance JSON committed**
(`data/catalog/dm3_4on4_human1537.summary.json`).

**What this does NOT prove:** the green verification below proves referential integrity, that the
geometric on-ground populated both states, and that every recovered action is held out of training.
It does **not** prove the inverse-dynamics-recovered labels are *correct*, that the corpus yields
useful movement behaviour, or that any bot improved — no model is trained here. This is a
data-extraction step; baselines and kill criteria attach to the training runs that consume the corpus.

This note records the Phase-4 extraction against the [ML Evidence Chain Gate](21_ML_EVIDENCE_CHAIN_GATE.md).
The committed `data/catalog/dm3_4on4_human1537.summary.json` is the durable provenance record (the
~125 GB database itself stays on servexeri — not in git, not on the build box).

## What ran

`scripts/catalog_etl_mvd.py` over the 1537-demo TRAIN manifest
(`data/corpus/human_4on4_dm3_mvd_manifest.json`) on **servexeri** (demos are servexeri-local; the run
is pinned there). Parser pinned to the **schema-33** `qw-analyze` binary (sha `6954ffb6`), which emits
per-tick view-yaw (`vya`), pitch, and velocity; geometric on-ground via `dm3.bsp` floor-trace
(`-view full -include positions,view,velocity`).

The run used a scratch **streaming patch** (PHASE4-STREAM) of the ETL; the reviewed, tested port is
now merged as **PR #383** (commit `c7c09e6`) — see the reproducibility note below.

## Results (provenance tag: ETL summary + verify.json, host=servexeri, parser sha `6954ffb6`)

| Field | Value |
|---|---|
| `demos_attempted` | 1537 |
| `demos_loaded` | **1536** |
| `demos_failed` | **1** |
| `episodes` | 949,814 |
| `player_ticks` | 534,627,531 |
| `actions` | 534,627,531 |
| `onground_distinct` | `[0, 1]` |
| split counts (sha-bucket) | train **1088** / val **222** / test **226** |
| extract wall-clock | 22,257.6 s |

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

## Verification (post-extraction gate — GREEN)

A live `PRAGMA foreign_key_check` + DB-side on-ground / hold-out recount over the 125 GB / 534M-row
database (`run_verify.py` on servexeri, ~1h55m) returned all green — the meaningful test that the
streaming-insert patch did not orphan any rows:

| `verify.json` | Value |
|---|---|
| `foreign_key_violations` | **0** |
| `onground_distinct` | `[0, 1]` |
| `actions_total` | 534,627,531 |
| `actions_held_out` | 534,627,531 (== total) |
| `actions_idm_trainable_BAD` | **0** |
| `elapsed_s` | 6923.8 |

## Evidence-chain gate mapping (`docs/21_ML_EVIDENCE_CHAIN_GATE.md`)

- **Item 1 (data used / ignored):** human 4on4 dm3 multi-view demos (MVD), 1537 TRAIN from the
  servexeri archive; bot games and non-dm3 excluded; single-player QuakeWorld demos (QWD) and the
  Milton believability anchor are out of scope here.
- **Item 2 (provenance):** `demos.sha256` (unique), parser binary sha `6954ffb6` (schema-33 —
  **required**; the schema-21 selection binary sha `3bc388bb` silently drops view-yaw and would
  corrupt strafe-sign recovery), manifest content-locked by sha256 + size. The committed summary JSON
  carries all of this plus the split policy and the verify output.
- **Item 3 (is the label a label):** MVDs record server-frame **state**, not the usercmd input
  stream. Movement is **recovered by inverse dynamics** (`label_source='idm'`, not `qwd_usercmd`);
  air-strafe sign trusted only in the ≥400 u/s bunnyhop regime; `forwardmove` is unrecoverable and
  never used; all recovered rows held out (`is_interp=1`).
- **Item 4 (measurement planes):** on-ground is a geometric `pmove_sim` floor-trace **proxy**
  (`player_ticks.onground_is_proxy`), a distinct plane from a live KTX on-ground flag.
- **Item 6 (leakage):** whole-demo splits (sha-bucket `group_by_demo_sha256_bucket`, no demo
  straddles a split); believability anchors kept out of training evidence.
- **Items 7 / 10 (baseline / kill criteria):** not applicable — this data-extraction step trains no
  model; baselines and kill criteria attach to the training runs that consume the corpus.

## Reproducibility & the PHASE4-STREAM → #383 relationship

The corpus was produced by the **scratch PHASE4-STREAM patch** (per-demo streaming insert + bounded
worker window — the merged `build()` accumulated all frames in RAM and would have run the box out of
memory on the full corpus). That fix is now merged, reviewed, and tested as **PR #383** (`c7c09e6`).

- **State + action values and the train/val/test split are reproducible from #383:** the scratch
  patch and #383 use the **identical sha-bucket split** (train `u<0.70`, val `u<0.85`) and identical
  per-tick values, so the committed split counts (1088/222/226) are what #383 produces.
- **The one difference is `demo_id` numbering:** this corpus carries autoincrement-by-completion-order
  ids (scratch); #383 assigns content-stable **sha-rank** ids. A re-extraction under #383 yields
  identical values + splits but renumbered `demo_id`s — immaterial for the held-out-action state-prior
  use. A fully #383-reproducible re-extraction is **deferred until RL is greenlit**.

## Use of the corpus

Reinforcement-learning **state prior** + reward / cadence anchor (`plans/rl-plan.md`, STEP 0). Action
labels stay held out until per-head weights unlock the trustworthy heads (aim / yaw, jump, in-regime
strafe-sign); `forwardmove` is never used. The canonical ~125 GB database stays on servexeri (not in
git, not on the build box); the pinnacle copy is deferred until reinforcement-learning is greenlit.
