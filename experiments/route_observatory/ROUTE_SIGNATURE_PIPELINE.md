# Route data → train-ready movement targets (offline extraction)

**Goal:** fix the dm3 routes as much as possible and structure the result so the broad-BC
model can train on it — *offline only* (no GPU run, no live server). Movement first.

This is the HOW layer on top of the route canon: the canon says *where* humans go (resource→
resource); this extracts *how they move* along each route as a per-route **signature envelope**
(the believability rubric + the route-conditioned BC target), plus a per-tick **route-
conditioning** feature that plugs straight into the existing shard contract.

```
parsed demo (MVD: all players | .qwd: elite POV + ground-truth usercmds)
  └─ route_legs.py ──────────► resource→resource LEGS  (position-based, flicker-immune)
        ├─ per-leg movement SIGNATURE   (speed / jump-cadence / look-vs-move / straightness)
        ├─ per-route ENVELOPE (envelopes.json)   = believability rubric + BC target
        └─ route_condition.py ──► per-tick GOAL VECTOR  = the v4 route-conditioning feature
                                   (joins catalog actor_ticks → broad-BC obs)
```

## Tools (`experiments/route_observatory/`)

- **`route_legs.py`** `<analysis.json> <out_dir> [rho=200]` → `legs.jsonl` + `envelopes.json`.
  Loads the whole game once (42 MB / ~280 MB RAM), segments every player into resource→
  resource legs, computes each leg's signature (reuses the committed
  `pov_fuse_extract.compute_signature`), aggregates per route into a distribution.
- **`route_condition.py`** `<analysis.json> <out_dir>` → `route_conditioning_sample.jsonl`.
  Per-tick goal vector toward the next resource; the reference implementation of the proposed
  v4 SELF feature, with a built-in validation gate.
- **`route_legs_qwd.py`** `<catalog.sqlite> <mvd_envelopes.json> <out_dir>` → the same
  position-based legs + `envelopes_qwd.json`, but from a `.qwd`-derived catalog (per episode,
  so legs never straddle a respawn/teleport).
- **`run_qwd_corpus.py`** `<demo_list.tsv> [out_dir] [batch]` → memory-safe batched driver that
  runs `catalog_etl_qwd.py` + the segmenter over the whole corpus on a 2 GB box (OOM-safe).
- **`merge_envelopes.py`** `<mvd_legs.jsonl> <qwd_legs.jsonl> <out.json>` → pools both corpora
  into one `envelopes_merged.json` with per-source counts.

The committed `signatures/*.json` are the produced envelopes (`envelopes_mvd_4on4.json`, the
97-demo `envelopes_qwd.json`, and the pooled `envelopes_merged.json`). The raw `legs.jsonl`
are regenerable and kept out of git (the 97-demo corpus is ~9 MB / 16k legs).

## The five "route" artifacts — which is canonical for what

`dm3` has five route-related artifacts with deliberately distinct jobs; do not conflate them:

| Artifact (schema) | What it holds | Consumed by |
|---|---|---|
| `data/catalog/resource_routes.dm3.json` (`resource_routes.v1`) | observed-traffic counts per resource pair (li-flicker; geometry approximate) | nothing in code today (provenance only) |
| `signatures/envelopes_*.json` (`route_envelopes.v2`) | per-route signature BANDS pooled by `(from,to)` (core = faster-half, all_traffic = full) | believability eval / curriculum. **PRE-PIVOT framing** — the row calls these a "BC target / believability band"; under docs/28 the human is a target to BEAT, not clone, and the `(from,to)` pooling is exactly what `route_canon_bands` avoids |
| `data/catalog/resource_coords.dm3.json` (`resource_coords.v1`) | the 11 resource `{name:[x,y]}` | `ml/pipeline/route_goals` goal-label (train/serve) |
| `data/catalog/route_canon.dm3.json` (`route_canon.v1`, #420) | owner-marked clean half-route SEED LINES (exact trajectory + endpoints + base/shortcut/enabler) | **#428 route-isolated MSE/RMSE centerline**; the seed for `route_canon_bands` |
| `data/catalog/route_canon_bands.dm3.json` (`route_canon_bands.v1`, NEW · #421) | per-highway human-range BAND around the seed: signature band (reuse `route_env`) + per-arc-fraction (x,y) positional corridor, harvested by **seed-trajectory similarity + route_class** (NEVER `(from,to)`) | **Phase-4 drift/believability monitoring + curriculum** (NOT #428 — #428 scores vs the seed centerline) |

**#420 vs #421 scope.** `route_canon.v1` is **#420** — DEFINE the highways + one SEED LINE each (the
initial MSE ground truth). **#421** (POV-fusion) later WIDENS each highway to an empirical band over
many matched corpus traversals, and MUST gate that harvest by seed-trajectory similarity +
`route_class`, **never** by the `(from,to)` resource pair (that re-pools base + shortcut traversals —
the contamination #420 exists to prevent; see the canon's `_match_key`). Built by
`build_route_canon.py` from `route_canon_marks.dm3.json`, whose owner hand-cuts EXCLUDE trick jumps
so movement quality is measured without trick-execution contamination. `route_class` is stored on
ALL highways; Phase-1 base training consumes `route_class=='base'` only (trickjump-separation,
docs/28).

**#421 (T2.2) — IMPLEMENTED.** Two tools link + automate the POV-fusion pipeline and build the band:
- `pov_fuse_pipeline.py <canon> <highway-id> --analysis <alias>=<full.json> --frames <dir> [--offset
  N] [--offset-verified] [--no-shot]` — the linked driver (`pov_fuse_extract` → `pov_fuse_render` →
  `pov_fuse_shot.js`) → the quantified signature + the fused POV+route contact sheet + an L1
  eval-integrity report (`pov_fuse_report.json`: each row PRESENT + NON-DEGENERATE + in-window). The
  frame↔state OFFSET is per-frame-SOURCE, calibrated by-eye once per demo (the in-game HUD match
  clock is the cleanest anchor) and passed as `--offset`; without `--offset-verified` rows are
  `offset-unverified` (fail-loud, never silently aligned). This is the Phase-1 LIVE TEST (docs/28:85).
  Frame variance needs Pillow (integration-only); demo-eyecheck `--render` (winnacle GPU) supplies POV
  frames for non-Milton players (integration-only — the offline/CI proof rests on the Milton frames).
- `route_canon_band.py <canon> --analysis <alias>=<full.json> -o route_canon_bands.dm3.json` — the
  band harvest. Banded **per SEGMENT** (a multi-segment teleport chain → one band per continuous run,
  id `<highway>#segN`, so each band's endpoints + seed-window + signature match the segment actually
  banded, never the whole-highway label/span). Gate A per candidate leg: endpoint==seed (cheap
  prefilter) AND `_suspect_trick`-clean (reuse #420) AND median per-point (x,y) ≤ `SIM_QU`=200 qu AND
  `route_class`==seed AND straightness/jumps within an explicit tolerance width. The seed segment is
  ALWAYS a band member (n≥1).
- **Single-demo finding (book_vs_mix).** Under the principled gate, most owner half-route cuts are
  idiosyncratic paths no other player in ONE demo resembles (Ring→RA: 73 endpoint candidates but the
  closest is 277 qu off the seed; Ring→RL: 1212 qu), so they stay n=1 (seed only). Of the 6
  segment-bands, only `low_bridge_stairs_ya` (water.LG→YA.box) → **n=5** (3 players, hs_mean
  365/394/424) and the shortcut's `…#seg1` Ring→Quad → n=2 gather corpus support. The machinery is
  correct; the candidates are genuinely dissimilar, not a bug. Widening the rest needs the **full
  corpus harvest** over many demos (the gated heavy run, like #420's heavy extraction) — which this
  finding validates deferring.

## The key correction: position-based legs, NOT `pos.li`

The committed canon (PR #332) and the first cut of this tool segmented routes by the loc-index
`pos.li`. **`pos.li` flickers at speed** — a leg's li-endpoint can sit ~1000 qu from the actual
item. Measured consequence: li "mega→RL" legs *started closer to RL than they ended*
(`goal_dist` 0.175→0.264, **decreased in 0/36**). The legs were geometrically wrong even though
their *traffic counts* reproduce the canon 68/68.

Fix: detect a resource visit by **position** — the player entering the `rho=200 qu` radius of an
item entity (`mapEntities`), which is flicker-immune and matches the owner's definition (a route
is the path between two resource *items*). Validation after the fix:

- `end_dist_qu` median **198** / p90 **200** — every leg terminates at its destination item.
- `goal_dist` median falls start→end in **89/89 routes** (it must approach the goal).

Result on the v1 demo (book-vs-mix, 8 players, full game): **2005 legs, 89 routes**. The named
hard pairs (mega→RL, sng→rl) are now correctly *sparse* — the true path is multi-hop through
intermediate items, so it decomposes into clean sub-legs (mega→Ring→RL …). That is the honest
geometry, and goal-conditioned BC chains the sub-legs naturally.

> **Finding to surface:** the committed `resource_routes.dm3.json` canon inherits the li flicker
> at the per-leg level (its traffic counts are fine). A position-based revision is the fix; not
> changing the committed artifact here (owner call) — flagged for review.

## `envelopes.json` — the believability rubric / BC target (`komodobots.route_envelopes.v2`)

Per route, two bands of the signature features (`dur_s`, `hs_mean/max`, `jumps_per_leg`,
`jump_interval_s`, `lookmove_deg`, `straightness`), each as `{n, p10, median, p90, mean, min, max}`:

- **core** (primary) — the *faster-half* traversals = the route actually being **run**; this is
  the route-conditioned BC target a bot should imitate.
- **all_traffic** — the full distribution = the outer believability band (is this plausibly human
  at all). A bot leg is believable iff its signature lands inside the human p10–p90 for that route.

Example (mega→RL core, position-segmented sub-legs): tight ~0.3–0.4 s jump-interval bunnyhop
cadence at sustained speed — a usable, gradeable target instead of one scripted example.

## `route-conditioning` — `feature_registry` v4 (the navigation signal BC lacked) — LANDED

The diagnosed divergence root cause was open-loop BC memorising one trajectory per route and
compounding error on hard geometry. The fix is **goal-conditioned imitation**: tell the policy
where it is headed. Append two SELF features (mirrors exactly how v3 appended turn-direction;
existing-feature normalization unchanged). `SELF_DIM 18 → 21`; `shard_contract.EXPECTS_SELF_DIM`
18→21 at v4.

```yaml
    # --- ROUTE-CONDITIONING SELF features (v4 append; goal-conditioned imitation, GCSL) ---
    - name: goal_heading_sincos
      dtype: float32[2]
      source: derived
      formula: "[sin(atan2(goal_y-oy, goal_x-ox)), cos(atan2(goal_y-oy, goal_x-ox))]"  # map-frame, like vel_heading_sincos
      unit: "[-1,1]x2"
      norm: sincos
      group: none
      version: 4
      leakage_safe: true
      note: "Egocentric heading to the next-resource GOAL on the current route. Goal is set by the tactical/spawn layer at inference; in training it is the hindsight next-item the player reached (GCSL). THE navigation signal open-loop BC lacked."
    - name: goal_dist_norm
      dtype: float32
      source: derived
      formula: "min(dist(origin, goal) / map_diagonal_dm3, 1.0)"   # same family as nearest_marker_dist_norm
      unit: "[0,1]"
      norm: identity
      group: none
      version: 4
      leakage_safe: true
      note: "Normalized distance to the next-resource goal. 1.0 (or a free-roam flag) when no goal is assigned."
```

**Why leakage-safe:** both features depend only on `pos[t]` and the goal coordinates (an INPUT
supplied by the tactical layer), never on future STATE. The action prediction given (state, goal)
is PIT-safe. This is standard hindsight-goal labelling.

## Train-ready integration (where each artifact plugs in)

The broad-BC pipeline is **catalog SQLite → `normalize_fit` → `build_features shard` →
`train_broad_bc`** (shard contract `dataset_spec.v1`). This work adds:

1. **per-tick goal vector** (`route_condition.py`) keyed by `(demo, player, t_ms)` → joins
   `catalog.player_ticks`/`actor_ticks` → becomes the two appended `obs` columns at v4. No new
   table; it is a derived SELF feature like `yaw_rate_z`.
2. **per-route envelope** (`envelopes.json`) → the believability eval target consumed by the
   closed-loop scorer (bot leg vs human p10–p90), and the curriculum signal (difficult routes).

The v4 feature is now LANDED in `feature_registry.json` (registry_version 4): the SELF vector
is appended in the SHARED `scripts/features/agent_observation.goal_vector` (train/serve parity),
`shard_contract` EXPECTS_SELF_DIM 21, and `build_features.py` materialises the goal columns
catalog-wide via `ml/pipeline/route_goals.py` (hindsight next-resource label, GCSL; dm3 coords
in `data/catalog/resource_coords.dm3.json`). `route_condition.py` here remains the validated
reference. Training on the v4 shard is the separate (owner-gated) next step.

## Scaling the corpus — the `.qwd` path (elite human variation)

`qw-analyze` cannot parse `.qwd` (empty output) — but `scripts/catalog_etl_qwd.py` (validated,
stdlib-only) ingests the `ctv_decomp` SmackDown3 corpus into the catalog: `player_ticks`
(pos/vel/angles/hspeed + geometric onground #316 vs `dm3.bsp`) and **`actions` = ground-truth
usercmds** (`label_source=qwd_usercmd`, confidence 1.0 — the real `act` targets). Running the
position-based segmenter over those `player_ticks` widens every route's envelope from one game to
dozens of elite games — "the routes, fixed as much as possible."

> **Caveat:** SmackDown3 is **1v1 duel** POV demos. *Tactics* differ from 4on4, but *movement
> along a route* is the same map + physics, which is exactly the movement focus. The 4on4 MVD
> remains the source for the `entities`/team channel.

## Eval-integrity caveats (every number carries these)

- **Jump cadence = v1 `vz`-proxy** (no onground in MVD); replace with geometric onground (#316)
  once baked into the catalog. The `.qwd` ETL already derives geometric onground.
- **v1 envelope = one 4on4 game** until the `.qwd` corpus folds in; rare routes (RL→YA.box n≈3)
  are thin.
- **MVD positions are 1/8-qu**; this defines route topology + signature, not sub-qu geometry.
- Goal coordinate = item ENTITY origin; legs end at the `rho` radius (~200 qu), not the exact
  pickup point — a directional signal, not a homing controller.
