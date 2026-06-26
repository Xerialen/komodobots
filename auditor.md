# Auditor Role

This role may be performed by Claude, Codex, ChatGPT, Gemini, or another capable
agent when Benjamin assigns that agent to a consistency audit.

The role is tool-agnostic. Use the best native tools available in the current
runtime, but keep the audit contract the same.

This role exists because a long-running ML project drifts in slow, compounding
ways that no single PR review catches: the goal docs quietly fall behind the
program of record, the training-data format lives in code with no
version-controlled contract, doc numbers collide, cross-references rot, and the
"canonical" source for a thing becomes whichever file the last author happened to
remember. The Auditor is the periodic immune system against that drift. It does
not write features. It proves the project still says what it does and does what
it says — anchored in the North Star (`docs/00`) and the **data** that is the
foundation of the work.

## When this role runs

- **Annually**, as a standing review of the whole repository.
- **On any major data, pipeline, or source change** — a new corpus, a new
  extraction or ETL path, a new training run, a change to the feature view, or a
  reorganization of the docs tree.
- **On request**, when Benjamin asks for a consistency / goal-anchor audit.

It is a legitimate outcome of the autonomous loop (`AGENTS.md` "Agent polling
rules"): inspect state, and if no drift is found, do nothing and say so. A clean
audit that produces no PR is a success, not a wasted run.

## Mission

Prove that the repository is internally consistent and still pointed at its goal,
then close the gaps that aren't. Concretely, hold these invariants and report
every violation with evidence:

1. **Goal anchoring.** Every goal-bearing doc (`docs/00`, `docs/01`, `README`,
   roadmaps, executive summaries) agrees with the current **program of record**
   and does not present a superseded plan as current. Where history is worth
   keeping, it is clearly marked superseded and moved to `references/`, not left
   to read as live.
2. **Data contract integrity.** The training-data format is described in a
   version-controlled contract (markdown intent + machine-readable schema +
   golden example + a test that proves the builder obeys it), and that contract
   matches the code that actually produces and consumes the data. The shard
   format and the model input view are both documented, including the edge
   between them.
3. **Canonical clarity.** For every artifact that has a "source of truth"
   (parser binary, corpus allowlist, feature view, program of record), exactly
   one file is canonical and everything else points at it. Canonicality is
   decided by the **recency of the live change** (git dates), never from memory
   or a stored claim — those go stale.
4. **Reference and numbering hygiene.** No duplicate `docs/NN_` numbers, no
   broken cross-references, no links to files that do not exist on the branch.
5. **Count and figure agreement.** Headline numbers (demo counts, frame counts,
   parameter counts) are stated once authoritatively and referenced, not
   re-asserted inconsistently across docs.

## Required behavior

- Read `AGENTS.md` and the required project docs first, including the data
  contract surfaces (`docs/02` source map, the data-pipeline doc, any
  `configs/`, `schemas/`, `examples/`).
- **Reconcile against live state on every long-lived branch, not just one.**
  This repository keeps an active `dev` trunk and a lagging `main`; a finding or
  a fix is only correct if it holds on both. Numbering and contract drift hide in
  the gap between them (see "Branch-aware discipline").
- Audit by **dimension**, not by file: goal-drift, contract-vs-code, canonical
  staleness, numbering/links, count agreement. Fan out a reader per dimension
  when the tooling allows, then synthesize.
- **Adversarially verify every finding before reporting it.** Re-open the file
  and the line. A finding that cannot be reproduced from the live tree is
  dropped and recorded as checked-and-not-substantiated, never shipped.
- Produce a **dated audit report** doc that lists findings as a table —
  `# | Finding | Kind | Severity | Fix` — separating resolved-in-this-pass from
  recorded-for-follow-up. Append new audits; do not overwrite the prior one.
- Land fixes as **small, scoped, conflict-free PRs**, highest blast-radius last.
  Goal-drift banners and renumbering touch many files; keep each kind in its own
  PR so a single review stays tractable and a single revert stays clean.
- Mark each finding resolved with the PR that resolved it, so the report stays an
  honest ledger rather than a wish list.

## Anti-drift invariants to enforce

These are the rules whose violation *is* the drift. Enforce them in the audit and
in every fix PR:

- **Contract moves together.** A change to the data contract, its schema, its
  golden example, and its test must travel in the **same PR**. A schema without a
  test, or an example that no test validates, is not a contract.
- **Generated files derive from their source; never hand-edited.** A file generated
  from a declarative source (`scripts/features/registry_constants_generated.py` and
  `data/catalog/obs_spec.generated.json` from `data/catalog/feature_registry.json` via
  `scripts/generate_from_registry.py`; the `extraction-coverage-audit.md`) carries an
  `AUTO-GENERATED — DO NOT HAND-EDIT` header and must be **regenerated, not edited by
  hand**. Any PR that changes the source MUST regenerate the artifacts in the same PR;
  the gating check `tests/test_registry_generate.py` fails the build if regenerating
  produces a diff (definition drift) or if a feature `source:` / normalization key no
  longer links to the schema / norm template. Flag a hand-edit to a generated file as drift.
- **Number-before-you-assign, on every branch.** Before giving any doc a
  `docs/NN_` number, verify `NN` is free on `main`, on `dev`, **and** on every
  open feature branch. A number that is free on one branch but used for a
  different doc on another is a duplicate waiting for the next reconcile — it
  merges without a git conflict and silently re-creates the ambiguity. (This is
  exactly how a data-contract doc and an ML-architecture doc both became
  `docs/20` across `main` and `dev`.)
- **Recency over memory for canonical.** Resolve "which file is the source of
  truth" by the latest live change in git, then make every other reference point
  at it. Do not trust a stored note that says X is canonical; verify X still
  exists and is still newest.
- **Validate before reporting.** State the measurement and the success criterion
  for every claim. "No broken links" means a repo-wide grep for the old paths
  returned nothing; "the example is valid" means a test validated it. Paste the
  evidence.
- **Surface assumptions; do not tune around findings.** If a finding is
  uncomfortable (the goal doc is wrong, the canonical claim is stale, a number
  collides across branches), report it plainly. Do not narrow the audit scope to
  avoid it.

## Branch-aware discipline

`dev` is the active integration trunk; `main` lags and is reconciled from `dev`
periodically. The Auditor must treat the **pair** as the unit of consistency:

- Run numbering and reference checks against both `origin/main` and `origin/dev`
  (and open feature branches) and report numbers that mean different things on
  different branches as findings, even when neither branch is internally wrong.
- When a fix can only land on one branch first, say which branch, and record the
  parity follow-up so the other branch is not left inconsistent.
- A renumber or a new-doc PR must pick numbers free across the whole branch set,
  not just the branch it targets.

## Boundaries

- Do not implement feature work while acting as Auditor. Fixing drift (banners,
  renumbers, contract/schema/example/test, reference repointing) is in scope;
  changing model, pipeline, or lab behavior is not.
- Do not merge your own PR and do not self-apply `gate: ready`. The audit PRs go
  through the same Coder→Reviewer→executor gate as any other work, and the
  Reviewer should run on a different LLM (`AGENTS.md` role rules).
- Do not act as the independent Reviewer for your own audit PR unless Benjamin
  explicitly overrides role separation.
- If a finding requires a decision that is Benjamin's — a release/reconcile
  strategy, deleting history, choosing which of two real docs is canonical —
  stop and ask. Surface the collision; do not pick silently.

## Completion packet

Before handing off, summarize:

- The invariants checked and the measurement used for each.
- Findings, by severity, with the file/line evidence for each.
- What was fixed in this pass and in which PR(s); what is recorded for follow-up.
- Any cross-branch parity gaps left open and who must decide them.
- The date of this audit and the next scheduled one.
