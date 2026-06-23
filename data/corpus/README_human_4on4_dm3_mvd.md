# Human 4on4 dm3 MOVE corpus (#358 / F-DATA-1)

The real human 4on4 dm3 movement corpus that replaces the ~1-MVD catalog. This is the
**selection manifest** (which demos are the training set); the per-tick feature extraction
that turns these demos into the learnable catalog is the next ticket.

## Files
- `human_4on4_dm3_mvd_manifest.json` — per-demo classification of the curated 4on4 archive
  (schema `…v3`). Each entry: `demo` (basename), `path` (locator on the archive host),
  `map`, `active_players`, `teams`, `class` (TRAIN/EXCLUDED), `reason`, `ok`, and the
  **content lock** `sha256` + `size_bytes`.
- `milton_div0_benchmark.json` — the Milton div0 reference, isolated as a SEPARATE held-out
  benchmark (never in TRAIN).
- `../../scripts/classify_4on4_mvd.py` — the tool that produced the manifest (reproducible).

## Counts
- scanned **1806** (the `[dm3]`-named demos in the curated `4on4-corpus`), 100% parsed clean.
- **TRAIN = 1537** real human 4on4 dm3 (clan-named, 2 teams, ≥6 active on dm3).
- EXCLUDED = 269: `bot_lab_default_teams` **223**, `not 2 teams` 25, `too few active players`
  14, `not_dm3` 7 (e.g. Blood Run / ztndm3 named "dm3" but a different map — caught by the
  map check, not the filename).

## Provenance — why `.mvd`, not `.qwd`
The original #358 plan read `~/ctv_decomp` `.qwd`. That path was **dropped** (owner-steered):
`qw-analyze` parses `.mvd` but not `.qwd`, and the `.qwd` set was ~77% SmackDown **duels** that
an old spectator-inflated client-slot count mislabeled 4on4. The corpus here is the owner's
curated `.mvd` archive on **servexeri** (`/mnt/usb-ssd/4on4-corpus/`, ~6.4k 4on4 mvds, ~1.8k
`[dm3]`-named). `path` fields are servexeri-local **locators** — identity is the basename + the
recorded parse; the feature-extraction ticket runs where the demos live.

## Content lock (provenance contract)
`path` is only a locator — the **identity** of each demo is its `sha256` + `size_bytes`.
Every row carries them and **every TRAIN row is hard-gated** to have a valid 64-hex sha256 +
positive size (`validate_provenance` → exit 3 otherwise), so a later extraction run cannot
silently trust a replaced/truncated/repaired file at the same path. The committed manifest is
built with `--demo-dir`, which hashes **each file's own bytes during the parse** (`analyze_one`)
— so every lock is computed independently and is self-consistent with that file's parse. The
downstream MVD ETL re-hashes each file before extraction and fails loud on any mismatch.

A safety net guards the foundational invariant that **no two TRAIN rows share bytes**
(`dedupe_train_by_sha` demotes any duplicate-content alias to EXCLUDED; a CI test asserts TRAIN
shas are unique). On the current corpus it fires 0× — all 1537 TRAIN demos are distinct content.
(NB: an earlier draft attached hashes by basename from a separate TSV and mis-paired two
*different* demos under similar names — `…free_vs_sr` exists as two distinct recordings, sha
`3b77719a…`/4881765 and `fa148b56…`/5091202; hashing each file's own bytes is what fixes that.)

**Parser provenance** (gate item 2): `provenance.parser` records the qw-analyze binary that
produced the selection fields (servexeri `qw-analyze-v20`, sha `3bc388bb…`). The map/teams/
active-player reads are parser-version-robust; the **per-tick MOVE extraction (ETL) separately
REQUIRES the schema-33 binary** (sha `6954ffb6…`, per-tick view-yaw/velocity) — a distinct,
load-bearing concern, not this manifest's.

## Discriminator (authoritative — `mvd_analyzer` / `qw-analyze`)
A demo is **TRAIN** iff, by qw-analyze's `match` read:
1. `map == "The Abandoned Base"` (true dm3 — filename is NOT trusted), AND
2. exactly **2 teams**, AND
3. teams are **not** the default `{red, blue}` (see bot exclusion), AND
4. `active_players ≥ 6` (`--team-min`, allows in-match churn from a true 8).

Active players are spectator-filtered (the `*spectator` userinfo flag + a real team +
non-zero frags), which is what fixes the duel-with-spectators ↔ real-4on4 confusion.

## Bot-lab exclusion (the contamination this corpus had to remove)
The active-player read separates 4on4 from duels/spectators but **cannot tell a human 4on4
from a bot 4on4** — both are 8 active players, 2 teams, dm3. KTX lab/bot matches use the
**default team names red/blue** (`docs/20_ML_DATA_ARCHITECTURE`: `4on4_red_vs_blue` /
`4on4_frog_vs_leap` = bot lab output). 223 such `{red, blue}`-team demos were present
(`red_vs_blue` + the reversed `blue_vs_red` lab naming) and are **EXCLUDED** — BC must not
learn bot movement. A few genuine human pugs on default teams are dropped with them; an
accepted trade given **1537 cleanly clan-named** human demos remain. They are recorded (not
deleted) and recoverable via a player-nick re-parse if ever needed.

## Threshold is re-derivable (no re-run)
`--team-min 6` → TRAIN 1537. The manifest records every demo's `active_players`, so other
thresholds re-derive instantly via `--reclassify` (no qw-analyze): strict-8 ≈ 1549−223 default
-team overlap, or any floor. `active_player_hist` is in `counts`.

## Milton — the div0 benchmark, kept SEPARATE
Milton (`/mnt/c/nQuake/qw/demos/milton_src.mvd`, the div0 reference) is **held out** — never in
TRAIN. The corpus contains **0** milton-named demos (verified). See `milton_div0_benchmark.json`.

## QWD is scoped, not retired
This is the **MVD MOVE corpus**. MVD is sufficient for movement (aim direct from the view
track; jump/getspeed from onground+velocity-z; strafe-sign from yaw-rate at ~88–94% = the v5
air-accel rule; only fwd/side analog magnitude is lost, minor for bhop). QWD is **kept** as a
validation anchor and reserved for what it uniquely provides — float-angle AIM supervision,
POV-internal opponent decode (the `docs/13` collision-ceiling fix), and the route-transfer
line (`docs/09` S7). See `docs/13_QWD_MVD_FUSION_PLAN.md`.

## Reproduce
```bash
# parse the archive in place (on the host that holds the demos):
python scripts/classify_4on4_mvd.py --demo-dir <4on4-corpus>/demos \
    --qwa ~/qw-sim/bin/qw-analyze-v20 --workers 4 \
    --out data/corpus/human_4on4_dm3_mvd_manifest.json
# or re-apply the rule to the recorded parse (no qw-analyze), merging the content lock from
# the archive's authoritative manifest.tsv (repeat --manifest-tsv for extra hashes):
python scripts/classify_4on4_mvd.py --reclassify <prev_manifest>.json \
    --manifest-tsv <4on4-corpus>/manifest.tsv --team-min 6 \
    --out data/corpus/human_4on4_dm3_mvd_manifest.json
```
`--demo-dir` hashes on disk; `--reclassify` merges `sha256`/`size_bytes` by basename from one or
more `--manifest-tsv` files. Either way a TRAIN row without a lock fails the run.
