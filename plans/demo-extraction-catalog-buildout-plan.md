# Plan: Demo Extraction Spec v1 — catalog build-out (accept + populate + fill genuine gaps)

**Status:** authored 2026-06-24. Anchors the implementation of `docs/27_DEMO_EXTRACTION_SPEC.md`
(`komodobots.demo-extraction.v1`). Tickets labelled **`extraction-impl`** on GitHub.

## Governing principle (why this plan is *reconcile*, not *greenfield*)

A repo audit (2026-06-24, three parallel passes) found that **most of the contextual + structural
design already exists** as binding artifacts — it is overwhelmingly **defined-but-unpopulated**, not
missing. The owner directive for this plan: *"anchored in what the repo already has, and not just add
new things while not accepting anything that is in the repo on this topic. Remember the audit and the
importance of these files."* Every ticket therefore **extends an existing artifact in place** and
none duplicates one. The keystone is the coverage **audit** the spec promises but the repo lacks.

## What the audit found (the ground truth the tickets build on)

**Binding artifacts that already exist:**
- **`scripts/catalog_schema.sql`** (`komodobots.catalog.v1`) — the schema `scripts/catalog_load.py`
  actually loads (operative). 18 tables incl. `player_ticks`, `actor_ticks` (omniscient all-players,
  with `health/armor/armor_type/weapon`), `actions`, `item_events`, `items`, `item_value`, `markers`,
  `nav_edges`, `episodes`, `teams`, `actor_visibility` (full PVS/FOV/LOS + belief block),
  `audio_cues`, `frag_events`, `region_control_timeline`, `feature_partitions`.
- **`data/catalog/feature_registry.yaml`** (`registry_version: 5`) — 12 feature groups: position,
  velocity, orientation (incl. yaw_rate/face-vel/goal-conditioning), player_resource (incl.
  `ammo_per_weapon_norm`, `powerup_remaining`), item (incl. `item_eta_norm`, `item_up_on_arrival`,
  `item_value_prior`), timing (incl. `time_to_reach_navgraph_norm`), player_style, entity_observation
  (15 feat), audio, team, action (targets), rtg.
- **`docs/ml-data-architecture/00-DATA-ARCHITECTURE.md`** — already specifies §2 geometry/nav,
  §2.5 over_void/height-above-floor, §2.8 POMDP (PVS→FOV→LOS raycast + belief), §2.9 entity rep,
  §3 items + §3.3 respawn + §3.4 ETA/contest + §3.5 value model + §3.6 audio + §3.7 team, §6
  normalization, §7 splits/leakage/versioning.
- **Derivation primitives:** `scripts/pmove_sim.py` (`player_trace`, `hull_point_contents`,
  `derive_onground`, `WorldModel.load`), `experiments/route_observatory/route_legs.py` (#334
  segmenter — legs by resource-visit, NO phase labels yet), `scripts/features/agent_observation.py`
  + `egocentric.py` (yaw_rate, face-vel, rel_distance/bearing/pitch, nearest-enemy in
  `ml/pipeline/build_features.py`), `data/catalog/item_catalog.dm3.json` (verified respawn times),
  `nav_edges.dm3.json`, `references/dm3_4on4_anchors.json`, `scripts/gmv_believability.py`.

**What the ETL actually populates today (the "we extract only movement" gap, code-confirmed):**
- `catalog_etl_mvd.py` requests only `-include positions,view,velocity` → fills `player_ticks` STATE +
  `actions` (IDM-recovered, all `is_interp=1`). Leaves NULL: `health/armor/armor_type/weapon`,
  `waterlevel`. **Populates none of** `actor_ticks`, `item_events`, `frag_events`, `teams`,
  `actor_visibility`, `audio_cues`.
- `catalog_etl_qwd.py` fills `player_ticks` + `actions` (ground-truth) + `actor_ticks` (self +
  observed-others, PVS-gated). Leaves `weapon=NULL`. Populates `item_events`/`frag_events`/`teams`
  only via test fixture.

**Genuine gaps (truly absent — these are the only *new* things):**
1. **No coverage audit** — no script diffs decoder Result inventory vs catalog vs registry → report.
2. **Schema-file drift** — `scripts/catalog_schema.sql` (operative) vs `data/catalog/catalog.sql`
   (near-dup, 7 lines drifted) vs registry's `schema/catalog.sql` (third path). No single canonical.
3. **`damage_events` table** — absent (only `frag_events` exists); per-hit KTX damage is decoded but
   has no destination → PENDING per spec §3.4.
4. **Ammo + powerup-remaining source columns** — `feature_registry` v5 *defines the features*
   (`ammo_per_weapon_norm` sh/nl/rk/cl; `powerup_remaining` quad/pent/ring, self + entity) but the
   source columns don't exist in the schema.
5. **Stored [G]/[R]/leg-phase columns** — geometry/regime are computed ad-hoc (trace.csv), not stored;
   **leg-phase (launch/cruise/approach/land) is genuinely absent** (route_legs has legs, no phases).
6. **docs/27 inaccuracies** — references the wrong schema path, calls `frag_events`/`actor_visibility`/
   `audio_cues`/`teams` "greenfield/reserved" when they are schema-defined-but-empty.

## Tickets (label `extraction-impl`)

Each cites the existing artifact it extends. **Heavy re-extraction across the corpus is the gated RUN
— separate, after these ETL/schema changes land and the analyzer-extension track settles, so the
expensive parse happens ONCE (spec principle).**

- **T1 — Coverage audit (keystone; ABSENT).** Build the runnable audit + committed report the spec
  promises (§3.9/§7): enumerate the decoder Result inventory (MVD qw-analyze schema-33 + in-house
  result: streams/damage/items/frag; QWD usercmd struct) and diff vs `catalog_schema.sql` columns +
  `feature_registry.yaml` + what each ETL populates → classify every field
  **extracted / derived / excluded-with-reason / GAP**. Scopes T2–T9. Extends per-ETL `table_counts`/
  `_observed_summary` + `_source-schemas.md`. No schema change.
- **T2 — Canonicalize the schema file + reconcile docs/27 to the real repo** ("accept what exists").
  Resolve the 3-way schema-path drift → ONE canonical schema + fix all references (loader, registry
  `catalog:`, docs/27). Correct docs/27 §0/§3/§7/§9 (frag_events/actor_visibility/audio_cues/teams =
  defined-not-greenfield; `damage_events` the only absent combat table; correct schema path). Depends
  on T1.
- **T3 — Populate resource state `health/armor/armor_type/weapon` (columns exist, ETL leaves NULL).**
  Extend `catalog_etl_mvd.py` to request the health/armor/weapon/item event streams (decoder already
  emits via `-event-types`) + fill the existing columns; `catalog_etl_qwd.py` weapon currently NULL.
  Mark availability/era per spec. MVD side independent of the qwd-analyzer track.
- **T4 — Populate the omniscient MVD world: `actor_ticks` + `item_events` + `frag_events` + `teams`.**
  MVD ETL populates none today. Consume the decoder's getStateAt (all players) / getItems / getFrags /
  getOverview roster. Tables already exist; streams per Appendix A. The core "extract everything"
  population. MVD-side; independent of qwd-analyzer.
- **T5 — Add + populate `damage_events` (the one genuinely-absent combat table; era-gated).** Promote
  PENDING→binding per §3.4 in one change-controlled PR (docs/27 + schema + registry + tests). Source =
  the decoder's per-hit KTX damage analyzer (`mvdhidden_dmgdone`, ~2024+). Enables the clean-movement
  filter (§6.5). Depends on T2.
- **T6 — Close the registry↔schema gap: ammo + powerup-remaining source columns.** `feature_registry`
  v5 already defines the features; add the missing source columns (additive, change-control) + populate
  from the decoder item/powerup streams. Do NOT add features — add their source columns. Depends on T2.
- **T7 — Contextual derivation pass → stored `[G]` geometry + `[R]` regime + leg-phase columns.**
  One pass reusing `pmove_sim` traces + `route_legs.py`, writing the §5 columns additively
  (wall-dist/ledge/ramp-normal/floor-height; regime label; leg-phase). leg-phase is the genuinely-
  absent derivation. Anchors §2.5. Depends on T2 (+ T3/T4 state).
- **T8 — Derive the POMDP layer: populate `actor_visibility` (PVS→FOV→LOS + belief) + item-urgency
  `[E]`.** Table exists empty; fully spec'd §2.8 (cheapest-first). LOS raycast reuses
  `player_trace` on hull-0; ETA/contest from `item_events` (T4) feed the registry's existing item
  features. Delivers the clean-movement filter (§6.5; needs T5 damage). Depends on T4, T5.
- **T9 — Training-connection template: worked obs-assembly + `dataset_spec.yaml` + norm-stats refit.**
  The "structured & connected to enable training" + "template files" deliverable. Produce the
  `dataset_spec.yaml` referenced in §2.9 + a worked consumer (AMP `(s,s')` and/or the movement obs)
  assembling its vector from the now-populated catalog with the PIT/ASOF leakage guard, and refit
  `normalization_stats` over the richer fields (train-split only, §6.2). Anchors `feature_registry` +
  `ml/pipeline/build_features.py` + `normalization_stats.template.json`. Capstone; depends on T3–T8.

## Sequencing
T1 (audit) first — it produces the map. T2 (canonical schema + doc reconcile) next/parallel (the drift
is already found). Then population T3/T4 (independent, MVD-side free of the qwd-analyzer track) and
schema-additions T5/T6 (need T2). Then derivations T7/T8. T9 is the capstone over a populated catalog.

## Constraints / honesty
- Heavy compute servexeri/pinnacle only; never pull the GB DB to aws-dev. The heavy re-extraction RUN
  is a separate gated step *after* these land (extract once). Claude never merges / never sets gate
  labels. The QWD-side of any ETL ticket may touch code near Codex's qwd-analyzer track — sequence
  those to avoid conflict; the MVD line is free to proceed.
