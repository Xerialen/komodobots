# Instrument-pool growth — sharpen the honest route-grade's lens (design plan)

Status: REVIEWED (dual pre-flight 2026-07-03: auditor vs origin/main SOUND-WITH-FIXES +
NotebookLM methodology review — all must-fixes folded, see §8). Owner authorization: "Kör på det"
(2026-07-03) on the recommendation that the data-line/instrument — not another reward round — is
the evidence-backed next move. Code base for line refs: `origin/main` @ `dbe841b`.

---

## 1. Why — three experiments, one binding constraint

Sweep-2, the long-run convergence probe, and the D7 geometry sweep all ended at the same wall:
**the instrument's resolution and pool, not the ideas under test.**

- Qualifying eval pool: **54 val episodes** at horizon 385 (the current `dm3_4on4_slice.sqlite`:
  40 demos, episodes 2,264/873/468 per split — journal state, provenance for the slice itself is
  NOT in the repo; see §3.1) → ranking 27 + tertiary 27, quantum **1/27 ≈ 0.037**.
- Invalid references: **10–14 of 27** per chunk (the recorded-human control replayed in-sim goes
  off-route/incomplete — refused per the Codex #471 P1 guard, `eval_broad_closedloop.py:936-948`)
  → judgeable ceiling ≈ **13/27 ≈ 0.48**.
- Consequences observed: seg_faster_frac moves in 1-segment quanta (the probe's "exactly flat
  0.1111 ×3"); the D7 sweep's decision margin (−0.0074) is a fifth of a quantum.

The un-blocking fact (verified 2026-07-03 on servexeri + the committed build record
`data/catalog/dm3_4on4_human1537.summary.json`): **the Phase-4 catalog already exists** —
`dm3_4on4_human1537.sqlite`, 117 GB, **1,536** demos (1,537 manifest TRAIN-class rows minus one
extraction failure recorded in the summary's `errors[]`), 949,814 episodes, 534,627,531
player-ticks, on servexeri `/mnt/usb-ssd/4on4-corpus/komodo-phase4/`. Growing the pool is a
CARVE + MEASURE + SHIP operation, not a re-extraction.

> Non-gating framing (#466 rule): journal-derived numbers here are decision rationale; this
> round's PR gates only on its unit-tested code + committed provenance artifacts.

## 2. What this round delivers

1. **A bigger slice** — `dm3_4on4_slice.g2.sqlite` ("generation 2"; final demo count chosen by
   the §3.3 probes, NOT baked into names) carved from the Phase-4 catalog, shipped to pinnacle,
   sha256-journaled (the registry pins the db hash into `environment_hash` automatically,
   `experiment_registry.py:197-204`).
2. **Measured instrument gain** (the real deliverable): qualifying pools per split @385, split
   composition, val- AND train-split load RAM/time, and a control-grade over the new pool →
   new quantum, judgeable count, invalid-ref rate, **and a grade-side MDE** (below). Published
   in this doc, non-gating.
3. **A committed provenance chain**: demo-sha subset list (+ header: source db sha, manifest,
   date, count), carve script, run-time verification (source-summary cross-check, FK, counts).

Explicitly NOT this round (named): the Parquet feature store (#425 — training-throughput infra,
owner-triggered, upstream-dep'd on T1.2); any reward/grade-math change; the
`_load_episode_ticks` loader rewrite (§3.4 names when it becomes unavoidable); PR-B (deferred,
trigger + mandatory bias-check below).

## 3. Design

### 3.1 Subset selection (deterministic, committed, split-aware)

Terminology first (a reviewer misread this — it matters): the manifest's **`class=="TRAIN"`**
means *corpus membership* (1,537 of 1,806 scanned demos; the rest EXCLUDED), NOT the db
train/val/test split. The db split is assigned per demo by `split_for_sha` (hash bucket,
`SPLIT_RATIOS=(0.70,0.15,0.15)`, stored per-episode at ETL time — `catalog_etl_mvd.py:1431-1437,
1640-1660`), so a subset copy inherits splits verbatim and new demos distribute ≈70/15/15.

- Candidates = manifest TRAIN-class rows in manifest order **∩ the source db's `demos.sha256`**
  (sha-normalized lowercase; the known extraction failure `blixem__fs__vs_tot_dm3_2.mvd` and any
  other absentee is EXCLUDED and RECORDED in the list header — never silently skipped, never a
  crash on a knowable absence).
- **Split composition is computed BEFORE selection** (pure stdlib `split_for_sha` over the
  candidate shas — no db access needed): the selection takes candidates in manifest order until
  the targets are met, and the list header reports the exact expected train/val/test demo split.
- **No anchors (post-review live-db finding, 2026-07-03):** the current `dm3_4on4_slice.sqlite`
  turns out to be a **QWD catalog** (`demos.source='qwd'`, challenge-tv POV demos; 0 of its 40
  shas exist in the Phase-4 MVD source) — which also fully explains the audit-M3 90-vs-618
  eps/demo discrepancy (different corpus, different ETL, not just different vintage). The
  "keep-the-40-anchors" idea is therefore moot; slice40 stays untouched as the legacy
  instrument db, and g2 is a clean fresh generation from the MVD corpus with the committed
  provenance chain slice40 never had.
- **Named risk — the control's action provenance changes QWD→MVD:** slice40's `actions` are
  ground-truth POV usercmds; the MVD catalog's are IDM-recovered (`label_source='idm'`,
  confidence<1.0, and per docs/27 **forwardmove is unrecoverable from MVD**;
  `_recorded_usercmd` reads a missing forwardmove as 0.0). Expected benign in the graded bhop
  regime (air acceleration is sidemove+aim-driven; humans hold forwardmove ≈0 above ~450 qu/s
  — docs/27 §4.1), but ground re-acceleration inside a segment could weaken the control. **The
  §3.3.3 control-grade IS this risk's gate**: report the control's validity rate + ratio on g2
  next to the slice40-era values; if control quality collapses, STOP and escalate the
  control-provenance decision (options: restrict segments to the air regime, or a QWD-sourced
  control lane) — do not proceed to a re-pose on a broken reference.
- Committed artifact: `data/catalog/slice_g2_demos.txt` — header (source db sha256, manifest
  path+sha, date, counts per split, exclusions) + one sha256 per line. The carve consumes THIS
  file; membership is explicit, never a `--limit`.

### 3.2 The carve (`scripts/carve_catalog_slice.py`, stdlib, gating-tested)

Given `--src`, `--out`, `--demos` (the list file):

- **Table handling derived from the SOURCE `sqlite_master`** — never a hand-declared list (the
  draft's 9-table list was FK-unsatisfiable: the schema has 19 tables and `maps`/`players` are
  hard FK targets of copied rows — audit M1). Policy per table:
  - **whole-copy** the static/spine tables: `maps`, `markers`, `nav_edges`, `items`,
    `item_value`, `players`;
  - **subset by demo** (`demo_id`/`sha256`): `demos`, `teams`, `item_events`, `frag_events`,
    `damage_events`†, `region_control_timeline`;
  - **subset by episode** (`episode_id`, and `(episode_id,tick)` composite where the FK says so
    — `actions` after `player_ticks`): `episodes`, `player_ticks`, `actions`, `actor_ticks`,
    `actor_visibility`, `audio_cues`, `feature_partitions`†;
  - † = copy IF PRESENT in the source (see the vintage waiver below) — a table named in the
    CURRENT schema but absent in the source is skipped WITH a logged notice; a table present in
    the source but unknown to the policy is a hard ERROR (fail closed on surprises, not on
    knowable vintage gaps).
- Schema (tables + indexes + PRAGMAs) copied verbatim from source `sqlite_master`; FK order
  respected; `PRAGMA foreign_keys=ON`; post-carve `PRAGMA foreign_key_check` == empty.
- **Run-time source verification (audit S1):** before carving, cross-check the source against
  the committed `data/catalog/dm3_4on4_human1537.summary.json` (demos=1,536,
  episodes=949,814, player_ticks=534,627,531) — mismatch = stop. Consumers key demos by
  `sha256`, never `demo_id` (Phase-4 ids are completion-order, per the summary's own caveat).
- **Vintage waiver (explicit, owner-visible — audit M2):** the source was built at the #383
  vintage (`c7c09e6`). Post-vintage schema additions (`damage_events`, `demos.damage_available`,
  `episodes.start_t_s`, T6/T7 columns) do not exist there, and the source's
  teams/actor_ticks/item_events/frag_events are EMPTY — a movement-spine-only corpus that the
  repo's `validate_catalog.py:validate_freshness` (the #315 guard) would flag STALE. **This is
  accepted for THIS instrument because the closed-loop grade is a solo-sim measurement**: the
  rollout simulates only the ego through pmove; `_load_episode_ticks` returns `others=[]` for
  empty actor_ticks, which the eval path tolerates (verified: every column the loader SELECTs
  existed at `c7c09e6`). The waiver is stated here, in the PR body, and in the list header;
  "schema byte-identical" means identical TO THE SOURCE, not to current `catalog_schema.sql`.
- Floor test (`tests/test_carve_catalog_slice.py`, stdlib sqlite3 + tempdir, Windows-portable):
  fixture db with the FULL FK web populated (incl. `maps`/`players`, FKs ON — audit M1
  corollary), carve a subset, assert: schema identical to fixture-source, only-subset rows,
  FK check clean, missing-sha REFUSED, absent-optional-table tolerated + logged,
  unknown-table ERROR, reported counts == actual. Connections closed before tempdir cleanup
  (the WinError 32 precedent in `tests/test_catalog_etl_mvd.py:1025`).

### 3.3 Ops + measurement protocol (probe FIRST, ship after — audit M3 reorder)

All probe/guard commands live in a committed runbook block in this doc and **enforce their
thresholds by exit code** (audit S4 — a guard that only exists as prose is not a guard).

1. **Server-side qualifying probe (before any ship):** carve on servexeri (SQL-local; ~78 MiB/
   demo ⇒ ~12 GiB at 160 demos), then run the qualifying-pool probe THERE against the g2 db:
   qualifying episodes per split @385 (`select_start_segments` rule: episode ≥386 ticks, first
   stride-385 window with ≥200 airborne-moving ticks (`mv1_min_ticks=200`, hspeed ≥150,
   onground falsey), ONE segment per episode). **The slice40 qualify-rate does NOT transfer**
   (slice40: 90 eps/demo; Phase-4: 618 eps/demo, mean 563 ticks/ep — different segmentation
   vintage, audit M3), so demo count is chosen HERE: grow the candidate list until
   **qualifying val ≥ 200** or a guard binds. Assert `returned == requested` on every
   segment-selection call (the machinery silently under-fills — audit S4).
2. **RAM guards on pinnacle (BOTH splits — audit M4):** ship the probe-passing db (sha256 before/
   after), then measure peak-RSS of `_load_episode_ticks` for **val** (the grading load; guard
   **≤ 40 GB**) AND **train** (the future sweep-reset load; report-only this round, but its
   result GATES the re-pose: at 70/15 split ratios the train load is ~4.7× val and plausibly
   exceeds the 54 GB box — if it does, the D7 re-pose needs the loader fix or a reset-db
   decision BEFORE any sweep, and this round says so out loud rather than discovering it
   mid-sweep). Val-guard breach ⇒ shrink the demo list from the tail (anchors keep) and re-probe.
3. **Instrument re-measurement (the deliverable):** grade the D7-sweep CONTROL checkpoint
   (t000 best seed, journal-identified, already on pinnacle) on the new pool at
   grade_segments = min(100, ⌊qualifying-val/2⌋), ranking offset 0 + tertiary offset =
   grade_segments (no caps exist on the knobs — verified). Report: new quantum (1/n), judgeable
   count (n − invalid), invalid-ref rate, control faster/median/rmse on the new routes, **and
   the grade-side MDE** (NotebookLM fold): bootstrap the per-segment faster-than booleans →
   SE of seg_faster_frac → MDE ≈ 2·SE·√2; pre-registered target **grade-side MDE ≤ 0.02**.
   Honesty note (two noise sources): this round sharpens the GRADE plane only; the ±0.083
   TRAINING-seed spread is untouched by pool size — with 5 verify-seeds the seed-side floor on
   a sweep comparison stays ≈ 0.083/√5·√2 ≈ 0.05, and the knob for THAT is more verify-seeds
   (cheap, named for the re-pose decision, not this round).
4. Journal what applies; new db ⇒ new `environment_hash` (automatic via the db-sha pin);
   comparisons to 27-route-era numbers are manual decision-rationale, never journal rankings.

### 3.4 Pre-registered decision rules (enforced, not prose)

- **Success:** qualifying val ≥ 200 AND val-load ≤ 40 GB AND judgeable/chunk ≥ 40 AND grade-side
  MDE ≤ 0.02 ⇒ round DONE; the geometry re-pose (D7 arms, more verify-seeds) becomes possible —
  **owner-gated, with the train-side RAM finding attached as its prerequisite sheet**.
- **PR-B trigger (control-validity prefilter at selection):** ONLY if judgeable/chunk < 40 at
  the achieved pool. If triggered, PR-B's own review MUST carry the **geometry-bias check**
  (NotebookLM): compare accepted-vs-rejected segment distributions (z-variance/verticality,
  route length, arc curvature) and state what the instrument goes blind to — refusal moving
  from grade time to selection time is only honest if the purged population is characterized.
- **Kill/park:** if val ≥ 200 is unreachable inside the val RAM guard, surface to the owner
  with the loader-rewrite costed (it converts the guard from a pool cap into a non-issue).

### 3.5 Committed runbook (the §3.3 commands, verbatim — guards are exit codes)

```bash
# on servexeri (bare python3), from /mnt/usb-ssd/4on4-corpus/komodo-g2 with the PR's
# scripts/ + data/catalog/ files shipped in:
python3 scripts/carve_catalog_slice.py \
  --src /mnt/usb-ssd/4on4-corpus/komodo-phase4/dm3_4on4_human1537.sqlite \
  --out dm3_4on4_slice.g2.sqlite \
  --demos data/catalog/slice_g2_demos.txt \
  --summary data/catalog/dm3_4on4_human1537.summary.json          # fail-closed carve
python3 scripts/probe_qualifying_pool.py --db dm3_4on4_slice.g2.sqlite \
  --horizon 385 --require-val 200 --out probe_g2.json              # THE pool guard (exit 1 on miss)
sha256sum dm3_4on4_slice.g2.sqlite                                 # provenance for the journal

# ship to pinnacle, then RAM probes there (venv python has duckdb):
python3 - <<'PY'                                                   # per split: val guard 40 GB
import resource, sys
sys.path.insert(0, "ml"); sys.path.insert(0, "ml/pipeline")
from build_features import _load_episode_ticks
for split, guard_gb in (("val", 40), ("train", None)):             # train = report-only
    eps, _ = _load_episode_ticks("<g2.sqlite>", split=split)
    gb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6
    print(split, len(eps), "episodes, peak", round(gb, 1), "GB")
    if guard_gb and gb > guard_gb:
        raise SystemExit(f"RAM GUARD FAILED: {split} {gb:.1f} > {guard_gb} GB")
    break                                                          # separate processes per split
PY
# control-grade on the new pool (grade_segments = min(100, qualifying_val // 2)):
.../python -u ml/eval_broad_closedloop.py --checkpoint <D7-control-ckpt> \
  --db <g2.sqlite> --split val --horizon 385 --n-segments <N> --aim policy \
  --grade-route --select-holdout-offset 0 --goal-mode conditioned --out grade_g2_control.json
# MDE: bootstrap SE over the report's per-segment faster booleans (script in the PR appendix).
```

## 4. ML Evidence Chain Gate (docs/21 — required section)

1. **Data used / ignored:** used = the Phase-4 MVD catalog (`dm3_4on4_human1537.sqlite`,
   movement spine: demos/episodes/player_ticks/actions + static tables), subset per
   `slice_g2_demos.txt`. Ignored: the QWD POV corpus (this round grades closed-loop movement
   vs an in-sim control — no usercmd labels consumed); ktxstats; live runs; the omniscient
   streams (empty at source vintage — waiver §3.2). No training data changes.
2. **Row provenance:** every carved row keys to `demos.sha256` (manifest-locked, size+sha per
   row); the list header pins source-db sha + manifest sha; the summary.json cross-check runs
   at carve time; the shipped db's sha256 enters every journal record via `environment_hash`.
3. **Label status:** NOT APPLICABLE — no labels are trained on; the `actions` rows carried
   along are IDM-recovered (confidence<1.0, label_source='idm') and serve only the recorded
   usercmd CONTROL replay, which the grade already treats as a reference, not truth.
4. **Measurement planes:** grade plane = pmove_sim closed-loop, both bot and control (the #428
   relative design cancels the common sim factor); no live/MVD plane mixing; plane fields are
   already dynamic in the report (#468). The new pool changes WHICH routes, not the plane.
5. **Building blocks ↔ data:** unchanged — this round adds no features/heads; the instrument
   consumes the same self-state spine the loader already reads.
6. **Leakage:** splits inherited per-demo from hash buckets (whole-demo grouping, stored at ETL
   — verified); training resets (future sweeps) draw from train, grading from val, the #477
   `--reset-split` discipline single-sources the skip; no route is both training evidence and
   eval evidence.
7. **Baseline:** the D7-sweep CONTROL checkpoint re-graded on the new pool IS the baseline
   datum; the round's claim is about instrument resolution (quantum/MDE), no model claim.
8. **What changes and why the result should change:** dataset grows (committed sha list); the
   expected movement is in RESOLUTION metrics (quantum 0.037→~0.01, judgeable 13→≥40, MDE
   ≤0.02), NOT in any policy's score — a policy-score shift on the new routes is a new-
   generation fact, not an improvement claim.

## 5. Files / scope

- `scripts/carve_catalog_slice.py` (new, stdlib, LOGGER per repo rule — `test_logging_coverage`
  scans scripts/).
- `tests/test_carve_catalog_slice.py` (new, floor, Windows-portable).
- `data/catalog/slice_g2_demos.txt` (new — committed subset provenance, header per §3.1).
- `plans/instrument-pool-growth.md` (this doc; measured results appended non-gating).
- NOT touched: reward/grade/eval code, ml/pipeline loader, docs/25 artifacts (pure-subset copy
  — no field added/renamed/transformed; Layer-A and feature-store surfaces byte-untouched,
  stated per the #435 pre-empt), tune driver.

## 6. Honest caveats

- New route set = NEW instrument generation: absolute values incomparable to the 27-route era
  except as manual context; the gain claim is about RESOLUTION (quantum, judgeable, MDE), never
  a policy score.
- Pool growth does not fix the invalid-ref RATE — it grows the judgeable COUNT; the rate fix is
  PR-B, measurement-gated, with the mandatory geometry-bias characterization.
- The carve inherits a movement-spine-only vintage (waiver §3.2) — fine for the solo-sim grade,
  NOT a general-purpose catalog for combat features.
- Two noise sources: this round fixes grade quantization; training-seed spread (±0.083) is
  untouched and floors sweep-level MDE at ~0.05 under 5 seeds — more verify-seeds is that knob.
- The slice40's own build provenance was not in the repo, and the live-db read revealed why the
  numbers never added up: it is a QWD POV catalog, not an MVD-corpus subset (§3.1) — the whole
  current instrument line has been grading on POV-sourced routes. g2's committed provenance
  chain is precisely the repair for that class of gap, and the QWD→MVD control-provenance
  change is measured, not assumed (§3.1 risk + §3.3.3).
- superhuman_claim remains false everywhere; nothing here touches training or claims.

## 7. Process

Plan (this) → dual pre-flight DONE (§8) → PR through the Codex gate (coder role: no
merge/labels) → §3.3 ops on servexeri/pinnacle (autonomous; nothing live-published) →
measured-results report to the owner with the §3.4 verdict + the re-pose prerequisite sheet.

## 7b. Measured results (appended as they land — non-gating operator notes, #466 framing)

**Carve + pool probe (servexeri, 2026-07-03 ~08Z):**
- Carve of 160 demos out of the Phase-4 catalog: **13 GB**, `foreign_key_check` clean, source
  cross-checked against the committed summary (demos 1,536 / episodes 949,814 / player_ticks
  534,627,531 matched). Vintage-gap tables logged absent/empty as the waiver predicts.
  g2 sha256 `3439b9aebde9265c64937fe5e0c9ea7270d39cbe3fcaffd8290911d197b4478b`.
- **Qualifying pools @385 (probe_g2.json, guard ≥200 val PASSED 14× over):**
  | split | episodes | qualifying | rate |
  |---|---|---|---|
  | train | 71,656 | **12,080** | 16.9% |
  | val | 12,802 | **2,804** | 21.9% |
  | test | 17,122 | 3,356 | 19.6% |
  The audit-M3 caution was right in the favorable direction: Phase-4 episodes qualify at ~3×
  the slice40 rate (the 6.2% never transferred). vs the old pool: **54 → 2,804 qualifying val
  episodes (52×)**; grade chunks of 100+100 use <8% of the pool; quantum 0.037 → 0.01.

**RAM probes (pinnacle, 54 GB box, ulimit -v 45 GB, 2026-07-03):**
- **val: 12,802 episodes load at peak 17.6 GB in 62 s — the 40 GB guard PASSES** with headroom
  (the vintage-empty `actor_ticks` keeps `others=[]`, which is most of the saving).
- **train: MemoryError at ~37 GB RSS (address-space cap hit) after 154 s — audit-M4 CONFIRMED:**
  the 71,656-episode train split does NOT load on this box with the current
  `_load_episode_ticks`. Consequence (pre-registered): grading on g2 works TODAY; a sweep
  re-pose with `--reset-split train` on g2 requires the loader follow-up (episode-cap or
  streaming reads) or a different reset source — this goes on the re-pose prerequisite sheet,
  deliberately not scope-crept into this round.

**Control grade on the g2 pool (pinnacle, 100 val segments offset 0, sweep-2 winner ckpt
`t007_s1003.pt` — 2026-07-03, `grade_g2_control.json`):**
- **The §3.1 pre-registered risk FIRED, structurally:** `n_ref_invalid` **97/100**,
  degenerate 2, judgeable **1**; the control's `median_human_ref_ratio` ≈ **0.01**.
- **Mechanism verified, not assumed:** g2's IDM `actions` carry `forwardmove ≡ 0.0` on all
  61,405,080 rows (unrecoverable from MVD — exactly docs/27's stated limitation; `sidemove` is
  sign×400) while the QWD slice40 carries real ±508 usercmds. A usercmd-replay control WITHOUT
  forwardmove cannot ground-start/re-accelerate → it stalls (on_route 0.83 near the spawn,
  progress ~0) → the relative reference is refused nearly everywhere. **This is a corpus-design
  fact, not a bug**: the MVD line is the state/observation oracle; the QWD line is the action
  oracle (docs/27) — and the D8 relative control needs ACTIONS.
- MDE over faster-booleans is undefined at 1 judgeable segment (bootstrap SE 0, degenerate) —
  not reported as a gain.

**§3.4 verdict (per the pre-registered rules):**
- Pool goals: **MET** (qualifying val 2,804 ≥ 200; val RAM 17.6 GB ≤ 40; quantum 0.01
  available). Carve/probe machinery + provenance chain: **DELIVERED** (works on any catalog db).
- Judgeable/chunk ≥ 40: **NOT MET — and not via the PR-B route** (the invalid rate is not a
  selection-time filtering problem; it is the reference's action-provenance). The §3.1 stop
  rule applies: **no re-pose on this pool's relative grade; escalate the control-provenance
  decision to the owner.** Named options, with the evidence this round produced:
  1. **QWD-pool growth (recommended):** the control works on QWD catalogs by construction
     (real usercmds); docs/27 records ~548 dm3 POV demos on servexeri and slice40 uses only
     ~40. This round's carve + probe scripts run unchanged on a QWD catalog; the pool target
     shifts to what the QWD corpus supports (to be probed, not assumed).
  2. Restore a forwardmove for the MVD control (regime-based synthesis) — REJECTED as default:
     fabricating the action the corpus cannot recover is exactly the information-dishonesty
     the program forbids; only worth revisiting with a live-validated synthesis model.
  3. Keep the relative grade on the QWD instrument while g2 serves adherence/mechanism-only
     measures + (post loader-fix) reset diversity — the hybrid, viable but two-instrument.
- Re-pose prerequisite sheet (unchanged by the control finding): train-split resets on g2 need
  the loader follow-up (M4 measurement above); verify-seeds remains the seed-noise knob.

## 8. Review log (dual pre-flight, 2026-07-03)

- **Auditor (code-truth vs `dbe841b`): SOUND-WITH-FIXES — all six must-fixes folded.**
  M1 table-list FK-unsatisfiable → sqlite_master-derived policy + whole-copy of FK-target
  static tables + fixture-with-full-FK-web test (§3.2). M2 source vintage → explicit waiver +
  present-table policy + "identical to SOURCE" wording (§3.2). M3 qualify-rate non-transfer
  (90 vs 618 eps/demo) + val-fraction 15% not 24% → probe-before-ship reorder + split-aware
  pre-selection (§3.1, §3.3.1). M4 train-split RAM → both-split probes; train result gates the
  re-pose prerequisites (§3.3.2). M5 1,536/failed-demo/TRAIN-class ambiguity → candidates =
  manifest ∩ source shas, exclusions recorded, terminology stated (§3.1). M6 missing docs/21
  section → §4. Should-fixes folded: summary.json run-time cross-check + sha256-keying (S1),
  version-named artifacts + list header (S2), WinError-32/ATTACH-path test hygiene (S3),
  committed probe commands + exit-code-enforced guards + returned==requested asserts (S4),
  lowercase sha normalization (S5), citation corrections (#471 P1; #449 = build_route_canon
  SystemExit precedent) (S6).
- **NotebookLM (methodology/honesty): direction endorsed ("cannot bootstrap out of n=13").**
  Folded: MDE-stated success criterion + the two-noise-source honesty note (§3.3.3, §3.4, §6);
  PR-B survivor-bias → mandatory accepted-vs-rejected geometry characterization (§3.4); the
  TRAIN-class/split terminology hazard → §3.1 states it up front (the reviewer's "fatal flaw"
  read was exactly this ambiguity — the mechanism was already split-blind, the wording was not).
