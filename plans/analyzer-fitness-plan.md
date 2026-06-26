# Plan: Analyzer fitness — make the QWD + MVD decoders fit-for-purpose for the data line

**Status:** authored 2026-06-26. Owner directive (standing): *"it's part of your job now to make sure
the qwd-analyzer AND the mvd-analyzers are up for the task this project is giving them."* This is the
proper plan for that mandate. Auto-memory: `analyzer-fitness-mandate.md`.

**Method (the mandate's spine):** derive the REQUIRED decoder Result inventory from the consumer
contracts → audit what each decoder ACTUALLY emits → diff → close gaps per repo, sequenced so komodobots
#419 (T1.2) can unblock. The two decoders are referenced by ROLE + schema version, never a tool name
(both are being renamed/extended):
- **MVD decoder** = omniscient server-MVD (all players, full game state). Local `~/mvd_analyzer-src` (Go
  workspace, `go.work`, Go 1.25; `Xerialen/mvd_analyzer`, fork of `galfthan/mvd_analyzer`).
  **Schema v35 @ commit `85ee181` (PR #91)** — *the memory's "v33" was stale; #92 bumps v36 on remote.*
- **QWD decoder** = first-person POV `.qwd` client demo (ground-truth usercmds incl. real forwardmove).
  PRIVATE `Xerialen/qwd-analyzer` (Python pipeline Q0→Q8; schemas `*.v1`; stage-1 prototype, quiescent).

---

## 0. Headline finding — the mandate's founding premise is half-wrong (and it changes the work)

The memory's premise was: *"we extract ~MOVEMENT ONLY because the v5 registry needs entity
health/armor/weapon/visibility/items the decoders may not populate."* The fresh decoder audits
falsify the **decoder-can't-populate** half:

> **The MVD decoder already emits, omnisciently for all players: health, armor, armor-type, weapon
> possession (RL/LG/GL/SSG/SNG), ammo (shells/nails/rockets/cells), powerup presence (quad/pent/ring),
> items + respawn timeline, frags/deaths, and per-hit damage (KTX).** (`mvd-analytics/result/streams.go`
> `PlayerStream` L48-91; `ItemsResult`/`DamageResult` in `RESULT_SCHEMA.md`.) It is **richer than its
> current komodobots consumer.** The "~movement only" reality is a property of the **komodobots ETL**
> (`catalog_etl_mvd.py` leaves those catalog columns NULL), **not** the decoder.

So "make the decoders fit" is, for the load-bearing obs space, **largely already true on the MVD side**.
Every channel in the *current* observation layout (`feature_registry.json` `observation` block —
self health/armor, entity health/armor/alive/is_teammate/is_visible) is **MVD-populated today** (the
entity-visibility channel via the MVD heavy build's BSP LOS). The genuine *decoder* gaps are narrow and
back channels that are **declared-but-not-in-layout** (future use), plus the QWD action-oracle
integration. This plan is therefore **not** a "extend both decoders to emit everything" program; it is:

1. Make the **existing fitness instrument** true to current decoder reality + standing (it's stale).
2. A **small set of high-value additive MVD extensions** (active-weapon first).
3. A **gated research spike** on a potentially transformative MVD capability (true usercmds from KTX
   hidden blocks → forwardmove from MVD, not just QWD POV).
4. **Hand the ETL-wiring gaps back** to the catalog-buildout line (#389-397) — they are not decoder work.
5. The **QWD integration sequencing** that unblocks #419 (owner-paced).

---

## 1. The gap register (diff: required vs emitted), classified

Required inventory derived from `feature_registry.json` (`source:` cols + `observation` layout),
`catalog_schema.sql` (19 tables), `docs/27_DEMO_EXTRACTION_SPEC.md`, `docs/25_DATA_CONTRACT.md`.
Emitted inventory from the two decoder audits (file:line evidence in each repo).

### Class A — ETL-wiring gaps (komodobots side; **NOT analyzer work** — catalog-buildout #389-397)
Decoder emits the raw field; the ETL just doesn't populate the catalog column. Listed here only to draw
the boundary cleanly — these do **not** belong to this mandate.
- `player_ticks.armor_type` — MVD `at` stream IS decoded + already used for `actor_ticks.armor_type`;
  the ego self-fill loop (`catalog_etl_mvd.py`) just skips it. One-line ETL fix. (docs/27 §3.4 names it.)
- `actions.impulse` (QWD) — QWD decoder emits `impulse` (`qwd_usercmd.py:60`); QWD ETL drops it.
- Powerup **remaining-time** (`*_rem` columns) — MVD emits `[start,end)` intervals; "seconds-left" is
  post-hoc derivable downstream from the interval + tick. ETL/feature derivation, not a decoder gap.
- Per-tick **alive** flag for self — derivable from MVD `sp`/`d` spawn/death timestamps. (Entity `alive`
  already populated.)
- `audio_cues`, `region_control_timeline` — derivable from already-decoded item/frag/position streams;
  currently fixture-only. Unfinished derivations, not decoder gaps.
- The whole MVD combat/item/frag richness the ETL leaves NULL = exactly the catalog-buildout backlog.

### Class B — genuine **MVD decoder** gaps (this mandate)
- **B1 · Active/selected weapon.** `STAT_ACTIVEWEAPON` **is parsed** into `stats.ActiveWeapon`
  (`mvd-reader/.../parser/stats.go:224-225`) but **never surfaced** in result/analytics/view (grep
  empty). Blocks `weapon_onehot` + `entity_weapon_onehot` (currently NULL both ETLs). The decoder tracks
  weapon *possession*, not *which gun is out*. **Highest value/effort ratio: it's surfacing an
  already-parsed field — a clean additive schema bump.**
- **B2 · Weapon possession completeness.** Only RL/LG/GL/SSG/SNG possession intervals emitted; **SG/NG/axe
  absent** (`streams.go:69-73`). Lower priority (starting weapons), but needed for an honest
  `weapon_onehot` universe.
- **B3 · KTX true-usercmd hidden blocks (the big one — RESEARCH SPIKE).** The KTX `mvdhidden` usercmd
  blocks exist on the wire as protocol constants — `MVDHiddenUserCmd=0x0001`,
  `MVDHiddenUserCmdWeapons=0x0002`, `…SS=0x0008`, `…WeaponInstruction=0x0009`
  (`mvd-reader/.../mvd/types.go:172-180`) — **but the parser's hidden-message dispatch decodes none of
  them** (`parser/parser.go:496-511` handles only dmgdone/demoinfo/timestamp/paused). Decoding them would
  yield **ground-truth forwardmove/sidemove/buttons for ALL players across the 1537-demo MVD corpus** — not
  just the 548 single-POV QWD demos — dissolving the "MVD actions are IDM-recovered/noisy, forwardmove
  unrecoverable" limitation the entire `MVD=observation-only / QWD=action-oracle` split rests on
  ([[demo-extraction-spec]] §4). **FEASIBILITY IS PROVEN, not hypothetical:** the audit's own anchor doc
  (`docs/ml-data-architecture/_source-schemas.md` §B4) records that a second, independent MVD parser —
  demoparser/`mimer` — **already decodes this exact block** (`src/mvd/hidden.rs:143-179`), recovering
  forward/side/buttons/impulse; the full 23-byte block it reads also carries up + 3 angles + msec
  (currently read-then-discarded). So the data is there and decodable. The **remaining** risk is narrow:
  is the block per-tick *dense* (demoparser only *stored* fire-frame inputs — a storage choice, not proof
  of wire sparsity), and which KTX/mvdsv versions in our corpus wrote it. → a gated spike on density +
  coverage, **not** on feasibility.

### Class C — **QWD decoder** gaps (this mandate; lower priority — the action-oracle role is already MET)
The QWD decoder reliably delivers its raison d'être today: the full ground-truth usercmd channel
(forwardmove/sidemove/upmove/buttons/impulse/msec + both angle triples), 36.6M frames, proven faithful to
0.1-0.4 qu offline (`scripts/qwd_usercmd.py`; `docs/current-stage.md`). So for the action-oracle role it
is **already fit**. Genuine gaps are role-completing, not blocking:
- **C1 · POV self combat-state** (health/armor/armor_type/weapon/ammo/powerups) — the carrying messages
  (`svc_updatestat`/`svc_updatestatlong`/`svc_clientdata`/`svc_damage`) are **sized-and-skipped**
  (`qwd_observed_others.py:379-398`); the POV's *private* state is in the bytes but undecoded. Only needed
  if QWD is used as a standalone training source (it isn't today — MVD is the omniscient state source).
- **C2 · Self `onground`** — **decoded but dropped** at `PairedSample` (`qwd_seam_validator.py:88,324` →
  not carried to `:96-108`); catalog hardcodes proxy-unavailable. One-line carry-through. Marginal (the
  komodobots line uses a geometric proxy anyway).
- **C3 · `use` + other button bits** — only `&1`/`&2` split out; raw `buttons` byte is preserved so
  downstream CAN split more. Class-A-style downstream derivation, not a decoder gap.

### Class D — genuinely unrecoverable / source-limited (record + close, don't chase)
- Other players' health/armor/weapon/name/team **from QWD** — a POV/PVS client demo never receives enemy
  stats. MVD is the only honest source. (Correctly absent; QWD's role stays ego-action oracle.)
- `forwardmove` **from MVD via inverse dynamics** — unrecoverable (server has no usercmd in normal
  snapshots). [B3 is the *exception path* — true usercmds via the side-channel, not IDM.]
- `pvs_visible`, per-player `waterlevel` (MVD), movers/projectile tracks — reserved/PENDING in docs/27 §9;
  perf or not-yet-needed. Not load-bearing.

---

## 2. Workstreams (sequenced)

### WS-0 · Make the fitness instrument true + standing (komodobots; **do first**; unblocks measurement)
**The ledger already exists** — `scripts/audit_extraction_coverage.py` (56 KB, CI-gated by
`tests/test_audit_extraction_coverage.py`) carries a `DECODER RESULT INVENTORY` keyed by decoder *role*,
parses schema (column universe) + ETL inserts (populated) + registry `source:` (required), classifies
every column with a reasoned verdict, and surfaces **UNCLASSIFIED** for any new column (forces an edit).
But its inventory is **sourced from a schema-33-era study + the old `qw-analyze` tool** (header
L64-67) — stale vs the v35 decoder and the new QWD pipeline.
- **Reconcile the inventory to current decoder reality:** MVD schema v35 (not 33); add the
  parsed-but-unsurfaced `ActiveWeapon` (B1) and the un-decoded KTX hidden usercmd blocks (B3) as
  *known-absent-in-output* entries with their gap class; re-key QWD entries to `Xerialen/qwd-analyzer`'s
  `q*.v1` contract (`qwd_usercmd.v1`, `q5_catalog.v1`, `q6_observed_others.v1`).
- **Promote it to the standing fitness ledger:** its gap-class output (this §1 register) becomes the
  durable, CI-checkable "are the decoders fit?" instrument. A new registry `source:` or schema column with
  no decoder backing surfaces as UNCLASSIFIED → the mandate is enforced continuously, not re-audited by
  hand. Update `docs/27` §completeness to point at it as the authority.
- **Verify-check:** `audit_extraction_coverage.py` runs green; deliberately add a fake registry source
  with no decoder → audit flags it. Layer-A surface untouched (docs/25 §2-6). Gated komodobots PR onto
  `main` (stdlib-only floor — the audit is already stdlib).

### WS-1 · MVD active-weapon surfacing (mvd_analyzer; highest value/effort; additive)
Close **B1**. The field is already parsed; the work is exposing it through the strict
reader→analytics→web stack as an additive schema bump (the repo's established discipline — see
`RESULT_SCHEMA.md` version history v4→v35, all additive).
- **Step 1 (verify):** confirm `stats.ActiveWeapon` is populated per-tick for all slots and is genuinely
  absent from `result/streams.go` output (the audit says so — re-confirm before coding, per the
  read-raw-files lesson).
- **Step 2:** add an `active weapon` change-stream to `PlayerStream` (sparse, like `at`), schema-version
  bump, `RESULT_SCHEMA.md` entry, tests. Follow `~/mvd_analyzer-src/CLAUDE.md` (module boundaries; do NOT
  cross the reader→analytics→web layering). Gated PR in **that** repo under **its** rules.
- **Step 3 (komodobots follow-on, separate PR):** once emitted, the catalog-buildout line wires
  `player_ticks.weapon` / `actor_ticks.weapon` from it (Class-A handoff — references this WS).
- **Verify-check:** decoder emits active-weapon on a sample dm3 MVD; `weapon_onehot` is no longer
  structurally unpopulatable. **B2 (SG/NG/axe)** rides along if cheap; else its own small follow-up.

### WS-2 · Forwardmove-from-MVD spike (mvd_analyzer; **gated research**, go/no-go before any build)
De-risk **B3** before committing. This is sequenced *after* WS-0/WS-1 because it is the highest-uncertainty
item and must not block the certain wins.
- **Step 1 (cheap, decides everything — feasibility already proven by demoparser):** port demoparser's
  block decode (`src/mvd/hidden.rs:143-179`) as a throwaway probe and run it across a sample of the
  1537-demo corpus + the live KTX/mvdsv build — measure (a) presence of `0x0001/0x0002` per KTX/mvdsv
  version, and (b) per-tick DENSITY (every frame vs fire-frame-only). Density + coverage decide go/no-go,
  not feasibility.
- **Step 2 (go/no-go, owner-gated):** if present + populated → scope the full usercmd-block decoder (would
  give true actions for the whole MVD corpus — a major data-line upgrade; revisit the
  `MVD=observation-only` framing). If absent → **close B3**, record the negative result in the ledger,
  QWD POV remains the sole action oracle. Either way the spike is bounded and the result is durable.

### WS-3 · QWD action-oracle integration readiness (unblocks komodobots #419; owner-paced)
The QWD decoder is *capability-fit* for its role; the blocker for #419 (T1.2 unify ETLs → shared catalog
writer, QWD adapter plugs the new analyzer in) is **landing + contract-stability**, which the owner drives.
- **Track landing:** `gh pr list --repo Xerialen/qwd-analyzer` — today: 0 open PRs, schemas `*.v1`
  quiescent, but a 2-day stage-1 prototype with no committed data + no downstream consumer. #419 stays
  BLOCKED until the owner declares `q5_catalog.v1`/`q6_observed_others.v1` stable.
- **Pre-stage the adapter mapping (no #419 commit yet):** document how the new analyzer's
  `q5_catalog.v1` SQLite output maps onto the komodobots shared catalog writer, replacing the in-repo
  `catalog_etl_qwd.py` path — so #419 can proceed the moment the owner greenlights. Carry the forwardmove
  asymmetry parameterized (QWD has it, MVD doesn't — unless WS-2 changes that). This is the
  [[data-layer-simplification]] P2 dependency.

### WS-4 · QWD self combat-state (deferred; only if QWD becomes a standalone source)
Close **C1/C2** (decode the skipped `svc_updatestat`/`svc_clientdata`; carry self `onground` through).
Defer until a consumer needs ego health/armor/weapon from the action oracle — today MVD supplies omniscient
state, so this is role-completion, not a blocker.

---

## 3. Per-repo gate compliance (this mandate spans three repos)
- **komodobots** (WS-0, WS-3 adapter doc, Class-A handoffs): gated PR onto `main`; `gate: reviewing` is
  auto-applied; Codex reviews; the deterministic executor merges. **Claude never sets `gate:` labels /
  never merges / never resolves threads.** Build in a `/tmp` worktree off freshly-fetched `origin/main`.
  Data-contract anti-drift binds any schema move (docs/25 + schema + golden + tests same PR).
- **mvd_analyzer** (WS-1, WS-2): follow `~/mvd_analyzer-src/CLAUDE.md` (its OWN rules — strict
  reader→analytics→web; additive schema bumps; do not change module boundaries casually). komodobots gate
  rules do NOT apply here. PRs in that repo under its workflow.
- **qwd-analyzer** (WS-3 tracking, WS-4): private `Xerialen/qwd-analyzer`; its own `AGENTS.md` two-agent
  (Codex codes / Claude reviews) loop. Owner-driven; Claude tracks + specs the contract, does not steer
  its internal churn.

## 4. Sequencing & dependencies
```
WS-0 (ledger true+standing) ──┬─> WS-1 (MVD active-weapon) ──> Class-A wire weapon_onehot (catalog-buildout)
                              ├─> WS-2 (fwdmove spike, gated) ──> [go] full usercmd decoder  /  [no-go] close
                              └─> WS-3 (QWD adapter doc) ──> (owner declares q5 stable) ──> komodobots #419 unblocks
WS-4 deferred (QWD self-state) — only on demand.
```
Do **WS-0 first** (cheap, komodobots-local, makes fitness measurable + the rest legible). WS-1 is the
cleanest certain win. WS-2 is bounded/gated and must not block WS-1. WS-3 is owner-paced and is the
#419 unblock path.

## 5. Open decisions for the owner
1. **WS-2 priority** — run the forwardmove-from-MVD header scan now (cheap, potentially transformative),
   or defer until after WS-0/WS-1 land? (Recommend: WS-0 + WS-1 first, then the WS-2 scan.)
2. **WS-1 vs the catalog-buildout backlog** — surface active-weapon in mvd_analyzer now, or treat
   `weapon_onehot` as out-of-scope until its obs channel is actually pulled into the layout? (It's
   declared-but-not-in-layout today.)
3. **WS-3** — should Claude pre-write the QWD→shared-writer adapter mapping now (so #419 is ready), or
   wait for the owner to declare the analyzer contract stable first?
4. **Memory/ledger correction** — the "MVD extracts ~movement only" framing across memories is being
   corrected to "MVD *decoder* is rich; the *ETL* is thin." (Already actioned in the auto-memory.)

---
Serves [[megalodon-milton-pivot]] (the goal) via [[demo-extraction-spec]] (the data line). The ledger
instrument (WS-0) is the durable form of the standing mandate. Class-A gaps belong to the catalog-buildout
plan (`plans/demo-extraction-catalog-buildout-plan.md`, epic #388 / #389-397), NOT here.
