# #440 (WS-1) — komodobots side: flip the ledger + scope the ETL-wiring

**Status:** PLANNED, awaiting auditor review then owner go. Decoder PR-1 is DONE.
**Grounded against** `origin/main` @ `6f3d943` (the primary checkout `/home/ubuntu/projects/komodobots`
is 3 commits behind — missing #437/#444/#445 — so every line-ref below was re-confirmed in a
`/tmp/komodo-ws1-ledger` worktree off fresh `origin/main`, NOT the drifted checkout).

## What is already done (do not redo)

- **PR-1 = `Xerialen/mvd_analyzer#1` — MERGED** (`mergeCommit 4146b10`, PR-head `95426df`,
  merged 2026-06-27). Surfaced `STAT_ACTIVEWEAPON` as `PlayerStream.w` (`[]ChangeI16`), mirroring the
  `Armor` path, **schema bump 35 → v37** (NOT v36 — the Xerialen fork already carried a v36). Encoding =
  **raw `IT_` weapon bits** `{axe=4096, sg=1, ssg=2, ng=4, sng=8, gl=16, rl=32, lg=64}`, no clamp.
  Unit test + regenerated goldens (only `schemaVersion` + `w` changed; player counts unchanged).

This plan covers ONLY the **komodobots** side of #440, which has two parts.

## Decomposition — and the recommendation

| | PR-2 — **ledger-flip** (THE NEXT STEP) | PR-3 — **ETL-wiring** (follow-on, blocked) |
|---|---|---|
| Job | Record that the decoder gap is closed; reclassify the two `*.weapon` GAPs from *decoder-gap* → *ETL-wiring-gap* | Actually populate the `weapon` column from `w`; flip labels GAP→OK |
| Touches | `audit_extraction_coverage.py` + its generated report + `docs/27` + ledger tests | `catalog_etl_mvd.py` + data-contract surfaces (docs/25 + schema + golden + tests) + a re-extraction |
| Labels | **stay `GAP`** (column still NULL → gate green) | flip **GAP → OK** |
| External dependency | **none** — true the moment PR-1 merged | **heavy**: a v37-built `qw-analyze` binary + a re-decode of the corpus |

**Recommendation: split them; do PR-2 now, defer PR-3.** Reason: the standing fitness ledger's whole
purpose is to be continuously true. The decoder-side reality ("active-weapon is now surfaced") became
true the instant PR-1 merged — PR-2 records that with **zero external dependency**. PR-3, by contrast, is
blocked on rebuilding the decoder binary the ETL actually runs (see the binary-version finding below) and
re-decoding the corpus. Bundling would hold the honest ledger-flip hostage to a slow, binary-gated
re-extraction. This is the same discipline WS-0 used (flip *reasons*, keep *labels*).
*Alternative if you'd rather not have an interim state: do nothing until PR-3 — but then the ledger lies
("surfacing it = WS-1") for however long the binary rebuild takes. Not recommended.*

## ★ Strategic timing (NotebookLM review grounded in docs/28 — verified)

A NotebookLM review grounded in the program docs surfaced a **stronger reason to defer PR-3 than the binary
block: the program of record does not consume `weapon_onehot` until Phase 2.** docs/28's hierarchical
architecture mandates bottom-up training **Movement → Combat → Strategy** with a weight-freeze between
stages; the project is in **Phase 1 (the movement Motor Cortex)**, and under the P1.3 modular split the
Frogbot "Commander" owns weapon choice while the ML model is *only* the movement controller — combat-blind,
reading no weapon feature. Active-weapon is **observation (State), so it survives the reinforcement-learning
pivot's action-pruning** (unlike the QWD action data WS-2 chased) — but it is a **Phase-2 (Aiming & Combat
Controller) feature**, not a Phase-1 one. Re-decoding the whole corpus now to populate a column no current
model consumes is wasted effort. **So PR-2 is the correct stopping point for this phase; PR-3 is a Phase-2
item** — a program-level reason on top of the binary block. (PR-2 stays correct regardless of phase: the
fitness ledger must reflect the decoder reality whenever it changes.)

## ★ Binary-version finding (sharpens PR-3; load-bearing)

`catalog_etl_mvd.py` does NOT consume the mvd_analyzer Go Result directly. It shells out to a **frozen
binary**: `~/qw-sim/bin/qw-analyze-v20`, **sha256 `6954ffb6…`**, which emits **`schemaVersion: 33`** JSON
(`catalog_etl_mvd.py:52-76,155,600-620`). `_validate_analysis` hard-requires `schemaVersion >= 33`. That
binary is a **v33-era build** of mvd_analyzer's `cmd/qw-analyze` — it predates the v37 active-weapon field,
so its JSON has **no `players[].w`**. Therefore:

- The ledger-flip (PR-2) must be **precise**: active-weapon is surfaced in the **decoder-of-record (v37)**,
  but the binary the komodobots ETL currently pins (`qw-analyze-v20`, schema-33, sha `6954ffb6`) does **not
  emit it** → that is exactly the remaining ETL-wiring gap.
- PR-3 is a **binary-version migration** (schema 33 → 37 build of `qw-analyze`), not a one-line read. The
  v34–v37 bumps are additive (loc-medoid / Movers / active-weapon), so a v37 JSON should still satisfy the
  ETL's schema-33 parsing — **but that must be validated**, plus the corpus must be **re-decoded** with the
  v37 binary (the stored catalog was built with the v33 binary and carries no `w`).

---

## PR-2 — ledger-flip (executable spec, anchors @ `6f3d943`)

Gated PR; build in a **`/tmp` worktree off freshly-fetched `origin/main`** (already have
`/tmp/komodo-ws1-ledger`). Claude opens, **never merges / never sets `gate:` labels / never resolves
threads**. Re-confirm every line-ref in the worktree before editing.

### `scripts/audit_extraction_coverage.py`

1. **`state.weapon_active` inventory entry (L94)** — this is a **3-tuple** `(origin, availability, note)`;
   edit all three: **origin** `"STAT_ACTIVEWEAPON — PARSED … but NOT surfaced in the Result (v35)"` →
   `"STAT_ACTIVEWEAPON — surfaced as PlayerStream.w (ChangeI16) in mvd_analyzer schema v37"`; **availability**
   `"MVD — parsed, UNSURFACED"` → `"MVD — surfaced"`; **note** `"… Surfacing it = WS-1 …"` → `"surfaced in
   v37 (Xerialen/mvd_analyzer#1 @ 4146b10); raw IT_ weapon bits; remaining gap is ETL-wiring (#440)"`.
2. **`player_ticks.weapon` GAP reason (L163)** — keep `GAP`; replace the reason with: active-weapon id
   **now surfaced** (mvd v37 `PlayerStream.w`); **remaining gap = ETL-wiring** — the komodobots MVD ETL
   still runs the frozen **v33-era** `qw-analyze-v20` (sha `6954ffb6`), which predates the v37 field and
   emits no `w` — **tracked by #440**. ⚠ **The reason text must NOT contain the literal `schema-33`** — the
   anti-recurrence guard `_report_advertises_stale_schema33` (L631) is a blunt substring check on the
   regenerated report, and CLASSIFY reasons render INTO the report (L490), so a `schema-33` substring fails
   `--check` (L799-804) AND the test (L268). Say "v33-era", never "schema-33".
3. **`actor_ticks.weapon` GAP reason (L198)** — same flip (same `schema-33`-literal prohibition).
4. **`build_report()` prose (L539-540)** — the "weapon GAPs are an ANALYZER-FITNESS decoder gap … surfacing
   it = WS-1" sentence: flip the **weapon** half to "now surfaced (v37 `PlayerStream.w`); remaining =
   ETL-wiring (#440)". **Leave the `armor_type` half unchanged** (it is a separate ETL-wiring gap already).
5. **Self-check assert (L704)** — `classify_column("actor_ticks","weapon") == GAP` **stays** (label
   unchanged); update only the assert **message** from "active-weapon parsed but unsurfaced; WS-1" →
   "active-weapon surfaced v37; ETL not yet reading `w`; #440".
6. **`inventory_is_v35` guard var (L799, O3)** — rename to version-agnostic **`inventory_has_active_weapon`**
   (its check `"state.weapon_active" in DECODER_INVENTORY` still holds — the KEY persists, only its reason
   text changes). Do **not** rename to `inventory_is_v37`.
7. **schema-33 anti-recurrence guard `_report_advertises_stale_schema33` (L621-631) — DO NOT BREAK.** In
   this ledger `schema-33` is the *retired Result-schema study* token the guard fails-closed on (substring
   check, L631); keep the guard green, do **not** reintroduce a `schema-33` literal anywhere that renders
   into the report. Its docstring mentions "v35-era entries like `state.weapon_active`" — a light wording
   touch is fine; the logic stays.
8. **Comment `surfacing it = WS-1` (L675-676)** — a comment inside `run_self_checks`; not gate-breaking,
   but the file's own discipline is to chase WS-1 strings, so reword it to "surfaced v37; ETL-wiring (#440)"
   to keep the flipped file internally consistent.

### Generated report `docs/ml-data-architecture/extraction-coverage-audit.md`

- **Do not hand-edit.** Regenerate: `python3 scripts/audit_extraction_coverage.py` (writes the report;
  `--check` writes nothing). The weapon rows (L166, L264), the `state.weapon_active` inventory row (L376),
  and the scoping prose (L431) all flow from `build_report()`.
- **Chase stale strings** in the regenerated output: grep for `"surfacing it = WS-1"`, `"not surfaced"`,
  `"UNSURFACED"`, `"WS-1"` near weapon and confirm each now reads "surfaced v37 / ETL-wiring #440".
- **★ Guard check:** grep the regenerated report for the literal `schema-33` — it MUST return nothing (the
  `_report_advertises_stale_schema33` guard fails-closed on that substring). A weapon reason that leaked
  `schema-33` → reword to `v33-era` and regenerate.

### `docs/27_DEMO_EXTRACTION_SPEC.md`

- **§3 status stub (L124)** — `"weapon stays NULL (no active-weapon source, as §3.4)"` → "surfaced in mvd
  v37 (`PlayerStream.w`); remaining gap = ETL-population (#440)".
- **§3.4 table + prose (L142, L150-151)** — `active_weapon … (unpopulated) … no honest active-weapon source
  without a decoder change (deferred)` → source now exists (v37 `PlayerStream.w`, raw `IT_` bits); remaining
  = ETL-population (#440).
- **§7 (L389-391) — this is an ADD, not a flip.** §7's "Still defined-but-empty" line (L389-391) currently
  names only `audio_cues` — there is NO active-weapon entry to flip. Extend it to name
  `player_ticks.weapon` / `actor_ticks.weapon` (decoder gap closed v37; ETL-population pending #440). AND
  fix the §3.4 **L151** pointer "tracked by §7" — §7 never tracked weapon, so either make §7 track it (the
  ADD above, recommended) or repoint L151 to #440.
- Reference the decoder by **role + schema v37 + merge commit `4146b10`** — never a tool name.

### `tests/test_audit_extraction_coverage.py`

- **GAP roll-up test (L88-97)** — the asserts that `player_ticks.weapon` / `actor_ticks.weapon` classify
  `GAP` **still pass** (labels unchanged); update the **comment** (L88-89) from "not surfaced → WS-1" →
  "surfaced v37; ETL-wiring gap → #440".
- **#437 anti-recurrence test (L256-267)** — `assertIn("state.weapon_active", DECODER_INVENTORY)` (L267)
  **stays valid** (key persists). Light comment touch only.
- **★ GAP-count invariant (L202): `len(audit.PLAN_GAPS) == 6` MUST stay 6.** The flip changes *reasons*,
  not *labels* — confirm `PLAN_GAPS` is unchanged (this is the gate-green guarantee). If it changes, the
  flip touched a label by mistake — stop and fix.
- Before bumping any "v35"→"v37" string, **grep the tests for a literal `"v35"` / `"schema v35"` assertion**
  and update it in lock-step (none seen, but verify — a literal-string assert would otherwise fail the gate).

### Provenance baseline — resolved (do NOT blanket-bump to v37)

*(Auditor MEDIUM-D + MEDIUM-A, folded.)* The inventory is reconciled to a **v35 baseline** (view angles v31,
velocity v32, …); only active-weapon moved to v37. A blanket "v37" bump would contradict the many
still-correct v35 statements (`audit_extraction_coverage.py:24,65,71,83,269,499`; report L292,L361-362). So:
- **Keep the v35 baseline.** At the provenance line (`:497`, report L361) append a SCOPED exception, e.g.
  *"reconciled to schema **v35**; active-weapon surfaced in the **v37** decoder (#440)"*. Do not rewrite the
  other v35 mentions.
- **★ MANDATORY (not optional): correct `docs/ml-data-architecture/_source-schemas.md`** — it is the static
  reference the ledger cites as `SOURCE_SCHEMAS_DOC` (`:52`), and it currently asserts the OPPOSITE of the
  flipped ledger: **L14-15** "WS-1: the mvd-reader parses STAT_ACTIVEWEAPON but does not surface it in the
  Result" and **L356** "no single 'active weapon' int in mvd_analyzer". Both are now FALSE (v37 surfaces it)
  → fix both lines, or the report's own cited provenance source contradicts the report.

---

## PR-3 — ETL-wiring (scope only — Phase-2-gated AND binary-blocked; owner-gated)

**Defer until Phase 2 (the Aiming & Combat Controller).** No Phase-1 model consumes `weapon_onehot` (see
*Strategic timing* above), so this is not a Phase-1 task — it is scoped here only so the deferral is explicit
and the obligations are known when it is taken up. Goal: populate `player_ticks.weapon` +
`actor_ticks.weapon` from `PlayerStream.w`; flip ledger labels GAP→OK. **Dependencies / open questions its
own plan must resolve:**

1. **Build `qw-analyze` from mvd_analyzer v37** (≥ `4146b10`); record the new binary's sha256. (The ETL
   defaults to `qw-analyze-v20` sha `6954ffb6` = v33-era → no `w`; the sha is documentary — the enforced
   runtime guard is `schemaVersion >= 33` + `vya`/`vx` presence, so a v37 JSON passes `_validate_analysis`.)
2. **Validate v37 JSON against the ETL's schema-33 parser** — `_validate_analysis` requires `>= 33`, and
   v34–v37 are additive, so it *should* parse; confirm `pos`/`players` shapes unchanged and `players[].w`
   present.
3. **Map `w` → the registry onehot.** Decoder emits raw `IT_` bits `{axe=4096, sg=1, ssg=2, ng=4, sng=8,
   gl=16, rl=32, lg=64}`; registry `onehot(weapon,[axe,sg,ssg,ng,sng,gl,rl,lg])` → a fixed bit→index map.
   Confirm `w` is a single active-weapon `IT_` bit per tick (PR-1 observed exactly that id set), not a
   held-mask.
4. **Re-decode the corpus** with the v37 binary (the stored catalog has no `w`) — heavy, **servexeri /
   pinnacle only**, owner-gated.
5. **Data-contract anti-drift — the FULL Layer-A set (docs/25 §157-162, verified; NotebookLM caught my
   earlier omission).** If the populated `weapon` column propagates to the Layer-A training row (it does once
   `weapon_onehot` enters the consumed obs space — a Phase-2 event), docs/25 mandates these move in the SAME
   PR: **`configs/extraction_spec.yaml` + `schemas/training_example.schema.json` +
   `examples/expected_training_frame.jsonl` + `tests/test_data_contract.py`** (my first draft said only
   "golden + tests" — it MISSED the YAML mapping + the `.schema.json`). PLUS `catalog_schema.sql` (the
   `weapon INTEGER` column **already exists** — PR-3 *populates*, not adds), **docs/27 §3.3/§3.4/§7**, and
   **`data/catalog/feature_registry.json`** (the `weapon_onehot` source). ⚠ docs/25 §43-47 distinguishes the
   **Layer-A raw-row contract** from the **docs/28 feature-store** — PR-3 must first confirm WHICH surface
   `weapon` actually reaches (catalog-only vs propagated to the NDJSON training shard) and move exactly that
   surface's files.
6. Flip the ledger labels GAP→OK (a further ledger edit, in the PR-3 commit).

---

## Constraints (carry-over)

- **komodobots gate rules:** Claude opens the PR; **never merges, never sets `gate:` labels, never reruns
  the merge workflow, never resolves review threads** — `review-gate-merge.yml` (github-actions[bot]) merges.
- Build in the `/tmp` worktree off fresh `origin/main`; re-confirm refs there (the primary checkout drifts).
- Commit trailers (komodobots): `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>` +
  `Claude-Session: …`. PR body footer: `🤖 Generated with [Claude Code]` + session URL.

## Verification (PR-2)

1. `python3 scripts/audit_extraction_coverage.py --check` passes (self-checks green).
2. `python3 -m pytest tests/test_audit_extraction_coverage.py` green; **`len(PLAN_GAPS) == 6` unchanged**.
3. Regenerated report has **no** stale "surfacing it = WS-1 / not surfaced / UNSURFACED" strings near weapon.
4. The two `*.weapon` columns still classify **`GAP`** (gate green); their *reasons* now cite v37 +
   ETL-wiring (#440).
5. **Net:** `weapon_onehot` is no longer *structurally* unpopulatable — only the (separately tracked, PR-3)
   binary-version ETL migration remains between the v37 decoder and the catalog column.

## Cross-refs

- Decoder spec / PR-1 history: `plans/analyzer-fitness-ws1-active-weapon.md` (the original two-PR WS-1 spec;
  its PR-2 section assumed v36 — this file supersedes it with the v37 reality + the binary-version finding).
- Ticket: #440 — *[analyzer-fitness] WS-1 — Surface MVD active-weapon (STAT_ACTIVEWEAPON)*. Memory:
  `analyzer-fitness-mandate.md`.
</content>
</invoke>
