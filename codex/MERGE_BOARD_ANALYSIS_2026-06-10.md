# Merge Board Analysis and Claude Help Request

Date: 2026-06-10

Repository: `Xerialen/komodobots`

Local workspace: `C:\Users\benya\projects\quakeworld\komodobots`

Prepared by: Codex, in reviewer / merge-board maintenance mode

## Why this file exists

The current merge board has reached a point where there are no remaining safe
mechanical merges or branch deletions for Codex to perform without crossing a
project role boundary or accepting unresolved technical risk.

This document records:

- what is open
- what is blocked
- what evidence already exists
- why each item is risky to merge or delete as-is
- my recommendation for each item
- a direct request for Claude to help move the board forward

The project rule that matters most here is the autonomous loop in `AGENTS.md`:

```text
Coder = Claude implements
Reviewer = Codex reviews and applies gate labels
```

That means Codex should not implement feature work to unblock Claude's PRs, and
Codex should not silently self-approve work that Codex created as branch
maintenance. Where the safe next step is implementation, live lab execution, or
ownership clarification, this file asks Claude for help.

## Current board snapshot

Snapshot gathered from `gh pr list`, `gh api repos/Xerialen/komodobots/branches`,
`git status`, and `git worktree list` on 2026-06-10.

Local state:

- current branch: `main`
- local branch list: `main`
- working tree: clean
- worktrees: only the main workspace

Remote branches:

- `main`
- `ld-f1-perslot-moveprobe-95`
- `a5-carve-release-118`
- `codex/qtv-lab-spectating-refresh`
- `qwd/dm3-sng-to-rl-route-map`

Open PRs:

| PR | Branch | State | Gate | Checks | Mergeability | Summary |
| --- | --- | --- | --- | --- | --- | --- |
| #124 | `ld-f1-perslot-moveprobe-95` | open, non-draft | `gate: blocked` | PR Tests pass | clean / mergeable | KTX per-slot moveprobe cvars |
| #125 | `a5-carve-release-118` | open, non-draft | `gate: blocked` | PR Tests pass | clean / mergeable | A5 terminal carve release |
| #126 | `codex/qtv-lab-spectating-refresh` | open, draft | `gate: reviewing` | PR Tests pass | clean / mergeable | refreshed QTV lab spectating branch |

Closed but still-existing branch:

| Branch | Associated PR | State | Reason it remains |
| --- | --- | --- | --- |
| `qwd/dm3-sng-to-rl-route-map` | #45 | closed unmerged | PR #45 comment says: "Branch kept for reference." |

## Executive recommendation

Do not merge anything immediately.

Recommended order of operations:

1. Claude fixes PR #125 first. It is the smallest concrete code blocker.
2. Claude helps convert PR #126 from a Codex-created draft into a normal reviewable item, or explicitly asks Benjamin for permission for Codex to gate it.
3. Claude produces the live lab evidence required for PR #124, or rescope #124 so it no longer claims completion of issue #95.
4. Claude or Benjamin decides whether `qwd/dm3-sng-to-rl-route-map` is still needed as a reference branch.
5. A separate CI hygiene PR should fix the review-gate merge workflow bug where a failed `gh pr merge` can still produce a misleading "Merged" comment.

The first two items are the most likely to reduce board pressure quickly.

## PR #125: A5 terminal carve release

URL: https://github.com/Xerialen/komodobots/pull/125

Branch: `a5-carve-release-118`

Head SHA reviewed: `b7e11f4d397a237de7e85d98e636d25a0e60f68d`

Current gate: `gate: blocked`

### What the PR is trying to do

PR #125 is stage A5, round 2 of the Distance jump work. It adds the terminal
carve release experiment, records a scored sweep, updates the off-ramp
decomposition, and documents the result that first landings exist but the
pre-registered bar was not reached.

The PR body says the important result is:

- round 1 had `0/4860` landings
- the carve sweep found `9` one-hit configurations
- top-3 extension yielded `8/100`, `9/100`, and `6/100`
- best result missed the pre-registered live bar of `>=10/100`
- next wall is speed-at-arm / release speed floor

This is evidence-bearing experiment work and should be mergeable once the CLI
runtime blocker is fixed.

### Evidence already gathered

Codex local review on the PR branch:

- `python -m unittest discover -s tests -p "test_*.py"` ran `310` tests OK
- the blocker reproduced locally with the explicit-source CLI path

GitHub checks:

- `PR Tests / unittest`: success
- branch is clean / mergeable against `main`

### Blocking finding

Changed file:

- `experiments/a5_distance_standstill/a5_offramp_decomposition.py`

Problem:

The new `--src` path treats any existing input file as plain-text JSON. Passing
the committed sweep artifact as an explicit source crashes because the committed
file is gzip-compressed:

```powershell
python experiments/a5_distance_standstill/a5_offramp_decomposition.py `
  --src experiments/a5_distance_standstill/carve-sweep-results.json.gz `
  --out $env:TEMP\carve-test-out.json
```

Observed failure:

```text
UnicodeDecodeError
```

Why this blocks merge:

- the PR advertises an explicit `--src` path
- the branch commits the carve sweep as `.json.gz`
- the most natural explicit-source invocation is therefore broken
- this is a runtime error in changed behavior

### Recommendation

Fix this in #125, not in a separate PR.

Likely implementation:

- centralize JSON loading behind a helper
- if `Path.suffix == ".gz"`, read with `gzip.open(path, "rt", encoding="utf-8")`
- otherwise use normal UTF-8 text JSON loading
- add a regression test that invokes `--src carve-sweep-results.json.gz`
- re-run the relevant focused test plus the full unit suite

### Request to Claude

Claude, please take #125 back and make the smallest scoped fix:

1. Patch `a5_offramp_decomposition.py` so explicit `--src` supports both `.json`
   and `.json.gz`.
2. Add or extend a test/selfcheck that exercises the committed
   `carve-sweep-results.json.gz` path.
3. Re-run:

   ```powershell
   python -m unittest discover -s tests -p "test_*.py"
   python experiments/a5_distance_standstill/a5_offramp_decomposition.py `
     --src experiments/a5_distance_standstill/carve-sweep-results.json.gz `
     --out $env:TEMP\carve-test-out.json
   ```

4. Push the fix to `a5-carve-release-118`.
5. Leave the PR in `gate: reviewing` after the reset workflow runs; Codex can
   then re-review the new head.

## PR #124: LD-F1 per-slot moveprobe cvars

URL: https://github.com/Xerialen/komodobots/pull/124

Issue: https://github.com/Xerialen/komodobots/issues/95

Branch: `ld-f1-perslot-moveprobe-95`

Current head SHA: `f1252aca83aa0f86fcf065257a023b0afc240df1`

Current gate: `gate: blocked`

### What the PR is trying to do

PR #124 implements issue #95:

- per-slot cvar convention `k_fb_moveprobe_<param>_s<N>`
- four params: `mode`, `replay_file`, `fixed_goal`, `spawn_origin`
- per-slot replay-file cache
- loud-fail behavior for malformed per-slot values
- `FBMOVEPROBE_ASSIGN` instrumentation
- parser / runner updates for assignment and per-slot error rows

This is high-value lab infrastructure because it enables two bots on the same
map to run different routes at the same time.

### Evidence already gathered

The original code-side blocker was fixed.

Earlier Codex finding:

- malformed per-slot `spawn_origin` was skipped after the one-shot snap latch
- this violated the loud-fail contract after mid-session reassignment

Claude's follow-up commit `f1252aca` addressed it:

- re-arms the spawn snap latch when per-slot source/value changes
- adds a structural guard in `tests/test_perslot_moveprobe_patch.py`
- documents the behavior in `experiments/ktx_moveprobe/README.md`

Codex re-review evidence on `f1252aca`:

- `python -m unittest discover -s tests -p "test_*.py"` ran `331` tests OK
- `git diff --check origin/main...HEAD` was clean
- previous spawn-origin blocker is considered addressed

GitHub checks:

- `PR Tests / unittest`: success
- branch is clean / mergeable against `main`

### Remaining blocker

Issue #95 has explicit Definition of Done items that are still not satisfied.

Issue #95 requires:

- per-slot helper plus four params wired
- additive guarantee demonstrated
- two-bots-two-routes lab evidence with logs and screenshot
- loud-fail evidence pasted
- ASSIGN/exposure rows documented
- patch committed in provenance home
- module deployed plus ledger note

The PR body and follow-up comment both say the live evidence is still pending:

- deploy pending
- additive smoke pending
- two-bots-two-routes proof pending
- loud-fail screen.log capture pending

Why this blocks merge:

- the PR claims `Implements #95`
- #95 explicitly includes live lab measurement in the Definition of Done
- this patch changes KTX lab-control behavior, so offline tests are not enough
- merging without the live proof would close or advance the work without proving
  the central operational claim

### Recommendation

Do not merge #124 until one of two things happens:

Option A, preferred:

- produce and paste the missing live evidence
- keep the PR as the completion vehicle for #95

Option B, acceptable if the live lab slot is intentionally delayed:

- rescope #124 so it is explicitly an offline patch-artifact PR
- stop claiming it implements #95
- update the issue / PR body so the live deployment and proof remain a follow-up
  stage

I prefer Option A if the lab slot is available soon. The whole point of #95 is
not just "the patch applies"; it is "two bots can run different routes in the
real lab without breaking additive behavior."

### Request to Claude

Claude, please help by choosing one path and making the PR consistent with it.

If you keep #124 as the #95 completion PR, please produce these exact evidence
items:

1. Deploy proof:
   - where the module was built
   - which KTX tree / commit / base checksums were used
   - where the module was deployed
   - confirmation that stock/non-test state is recoverable

2. Additive smoke:
   - one no-per-slot-cvars run
   - comparison to pre-change control behavior
   - sampled `FBMOVEPROBE_CMD` rows or equivalent summary showing no unexpected
     behavior change

3. Two-bots-two-routes proof:
   - map: `dm3`
   - slot A: mode 21, `dm3_sng_to_rl.cmds`, correct spawn origin
   - slot B: mode 21, `dm3_hilljump.cmds`, correct spawn origin
   - `FBMOVEPROBE_ASSIGN` rows for both bots
   - logs plus dashboard / 3D trace screenshot showing the routes diverge to the
     intended start pads

4. Loud-fail proof:
   - set a bad per-slot replay file, e.g. `k_fb_moveprobe_replay_file_s2 nonexistent.cmds`
   - capture `FBMOVEPROBE_PERSLOT_ERROR` in `screen.log`
   - show the bot is held rather than silently falling back

5. Ledger/doc update:
   - update `experiments/nav_doctrine/evidence/run-ledger.md`
   - update any relevant lab environment notes if the deploy process changed

If you instead rescope #124, please edit the PR body and issue linkage so Codex
can review it as an offline artifact PR without pretending the live #95 DoD is
complete.

## PR #126: refreshed QTV lab spectating branch

URL: https://github.com/Xerialen/komodobots/pull/126

Branch: `codex/qtv-lab-spectating-refresh`

Head SHA: `6e587ad1e70d48a55437726fa7075e4a6e8aaf08`

Current state: open draft

Current gate: `gate: reviewing`

### What the PR is trying to do

PR #126 refreshes the old stale branch `claude/qtv-lab-spectating-riNiT` onto
current `main` as a clean reviewable PR.

It includes:

- `scripts/run_lab_qtv.py`
- `tests/test_run_lab_qtv.py`
- `docs/02_SOURCE_MAP.md`
- `docs/05_HEADLESS_TEST_ENV.md`
- `docs/08_DECISION_LOG.md`

It resolves the stale `docs/08_DECISION_LOG.md` conflict by preserving current
`main` decisions and inserting the QTV decision entries in chronological order.

The old `claude/qtv-lab-spectating-riNiT` branch was deleted after verifying
that the refreshed branch has identical launcher and test files. Only docs differ
because the refreshed branch is based on current `main`.

### Evidence already gathered

Local validation before opening #126:

```powershell
python -m unittest tests.test_run_lab_qtv
```

Result:

```text
Ran 29 tests
OK
```

Full suite:

```powershell
python -m unittest discover -s tests -p "test_*.py"
```

Result:

```text
Ran 353 tests
OK
```

Whitespace / patch hygiene:

```powershell
git diff --check origin/main...HEAD
```

Result:

```text
clean
```

GitHub checks:

- `PR Tests / unittest`: success
- branch is clean / mergeable against `main`

### Risk / role issue

This PR is not blocked because of failing tests. It is blocked by process risk:

- Codex created this branch as maintenance work
- Codex is also the reviewer / gate authority in this repo
- merging or marking this PR ready without another actor reviewing it would be
  self-review
- the PR touches live-lab orchestration and QTV attach/detach behavior, so
  process discipline matters

The draft state is therefore correct.

### Recommendation

Do not merge #126 directly from Codex.

Best path:

1. Claude reviews/adopts #126 as the Coder side.
2. Claude either:
   - makes any needed changes and marks it ready for review, or
   - confirms it is acceptable and asks Codex for normal review.
3. Codex reviews the final non-draft head and applies `gate: ready` or
   `gate: blocked`.

If Benjamin explicitly wants to bypass the role split for this PR, that should be
stated clearly in the PR or issue because the default repo contract says not to
self-review.

### Request to Claude

Claude, please help with #126 by doing one of these:

Option A:

- review the refreshed QTV branch as the Coder-side owner
- check that the conflict resolution in `docs/08_DECISION_LOG.md` preserved the
  intended QTV history
- decide whether the PR body needs more live-verification detail
- mark the PR ready for review if you accept it

Option B:

- take over the branch with a small follow-up commit if anything is missing
- push that commit
- leave it ready for Codex review

Please do not apply `gate: ready`; that remains Codex's reviewer label.

## Remote branch `qwd/dm3-sng-to-rl-route-map`

Associated closed PR: https://github.com/Xerialen/komodobots/pull/45

Branch: `qwd/dm3-sng-to-rl-route-map`

Head SHA: `c472d113379fb373397c1526234802e252602359`

State: closed unmerged, remote branch still exists

### What the branch contains

The branch contains offline route characterization for retargeting the DM3 trick
track from `dm3_sng_shortcut.qwd` to `dm3_sng_to_rl.qwd`.

Files changed relative to its merge base:

- `docs/06_DATA_AND_MVD_PIPELINE.md`
- `docs/07_FINDINGS_LOG.md`
- `docs/09_ROADMAP.md`
- `experiments/qwd_route_probe/evidence/qwd-frogbot-route-map-dm3-sng-to-rl.json`
- `experiments/qwd_route_probe/evidence/qwd-frogbot-route-map-dm3-sng-to-rl.md`

The PR body says:

- command/state coverage `1.0`
- `53` waypoints
- `22` collapsed markers
- within-128-qu marker coverage `0.792`
- direct-edge ratio `0.143`
- verdict: `hybrid_waypoint_controller_probe`

### Why it was not deleted

PR #45 was closed with this owner comment:

```text
Closing per our agreement: this is route-characterization apparatus, not a finding.
The route map + relevant docs will ride inside the first real finding PR for this
track (exact-input replay of dm3_sng_to_rl). Branch kept for reference.
```

That makes deletion a human/owner decision, not a safe mechanical cleanup.

### Current risk

The branch is old and conflicts with current `main` in docs:

- `docs/06_DATA_AND_MVD_PIPELINE.md`
- `docs/07_FINDINGS_LOG.md`

Merging it as-is would be wrong. Deleting it without checking whether the
evidence has been carried forward could lose a deliberate reference.

### Recommendation

Do not merge this branch.

Choose one:

Option A, if the evidence already rode into later finding PRs:

- add a final comment to #45 saying the reference has been superseded
- delete remote branch `qwd/dm3-sng-to-rl-route-map`

Option B, if the evidence is still useful but not integrated:

- cherry-pick only the evidence files and relevant doc excerpts into a fresh
  branch from current `main`
- open a new PR with a narrow "archive route-map evidence" scope
- delete the old branch after the replacement merges

Option C, if Benjamin wants it retained as an archive:

- keep the branch
- record in a current doc that the remote branch is intentionally retained and
  should not be treated as branch debt

### Request to Claude

Claude, please check whether the `dm3_sng_to_rl` route-map evidence from PR #45
has already been carried into a later merged finding PR.

Useful checks:

```powershell
rg -n "qwd-frogbot-route-map-dm3-sng-to-rl|dm3_sng_to_rl trajectory|hybrid_waypoint_controller_probe|within-128" docs experiments
```

Then recommend one of:

- delete the branch as superseded
- preserve it intentionally and document why
- port the evidence into a fresh branch / PR

## Review-gate merge workflow bug

This is not currently attached to one open PR, but it is important merge-board
hygiene.

During the earlier merge pass, PR #117 had a false "Merged" comment from the
review-gate executor even though GitHub still showed the PR open and unmerged.

The action log showed:

- `gh pr merge` failed with a GraphQL error because the base branch was modified
- the workflow still posted a "Merged" comment afterward

Why this matters:

- the deterministic merge executor is the hard authority in this repo
- a false merged comment creates operator confusion
- if humans trust the comment instead of GitHub state, branch/PR cleanup can go
  wrong

Recommendation:

Create a separate CI hygiene PR to make the review-gate merge workflow fail
closed:

- never post "Merged" unless `gh pr merge` exits successfully
- avoid shell constructs where `set -e` is suppressed by a function call inside
  an `||` branch
- after merge, verify the PR state through `gh pr view --json state,mergedAt`
  before commenting
- if the base branch changed, leave an explicit "merge skipped/retry" note or no
  comment at all

Request to Claude:

Please open a small CI-only PR for this after the current board pressure drops.
This should be independent of #124, #125, and #126.

## Claude help request, consolidated

Claude, please help move the board in this order:

1. Fix PR #125.
   - This is the smallest concrete code blocker.
   - Add gzip-aware explicit-source loading and a regression test.

2. Adopt or review PR #126.
   - It is green and mergeable but draft because Codex created it.
   - If you accept it, mark it ready for normal Codex review.

3. Finish or rescope PR #124.
   - Preferred: produce the live #95 evidence.
   - Acceptable: rescope so it no longer claims #95 completion.

4. Decide the fate of `qwd/dm3-sng-to-rl-route-map`.
   - Delete only if superseded.
   - Otherwise preserve intentionally or port the evidence.

5. Create the review-gate merge hygiene fix.
   - The false "Merged" comment should not be allowed to recur.

## What Codex should do next after Claude responds

Once Claude pushes new commits or marks PRs ready:

- re-fetch and inspect current heads
- review changed PRs using the required structured review format
- apply exactly one terminal gate label per reviewed head:
  - `gate: ready`
  - `gate: blocked`
- merge only through the deterministic gate unless an explicit, SHA-pinned manual
  merge is justified and explained
- prune branches only after confirming they are merged, superseded, or explicitly
  abandoned

## Final recommendation to Benjamin

The board is not messy anymore; it is deliberately blocked.

The useful next move is not more branch sweeping. It is one small coder fix
(#125), one role-boundary review/adoption (#126), and one live-lab evidence pass
(#124). After those, the merge executor should be able to drain the board
normally.

