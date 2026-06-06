# Komodobots Autonomous Agents

Repo-specific autonomous agent cards for Komodobots.

These files adapt Benjamin's reusable vault templates to this repository. The generic templates live in:

- `C:\Users\benya\Workspace\thevault\agents\phasekeeper.md`
- `C:\Users\benya\Workspace\thevault\agents\code-sentinel.md`
- `C:\Users\benya\Workspace\thevault\agents\merge-steward.md`

`AGENTS.md` remains the source of truth for repository instructions. If an agent card conflicts with `AGENTS.md`, follow `AGENTS.md` and update the card.

## Roster

- `agents/phasekeeper.md` - developer agent. Implements one roadmap stage at a time and prepares a phase PR.
- `agents/code-sentinel.md` - reviewer/hardener agent. Reviews for slop, validation gaps, and roadmap drift. Does not merge.
- `agents/merge-steward.md` - merge gate agent. Merges only reviewed, phase-correct PRs when all gates pass. Does not implement.

## Default Pipeline

```text
Phasekeeper implements phase work -> Code Sentinel reviews/hardens -> Merge Steward merges if gates pass -> Phasekeeper starts the next stage from updated main
```

This split exists to avoid unattended mega-PRs and stacked-PR sprawl. By default, each top-level roadmap stage gets one PR, and the next top-level stage starts from updated `main` only after the previous stage merges.

## Current Live Stack Note

As of 2026-06-06, the repository also has a legacy stack from earlier unattended work:

- PR #3, `[codex] advance movement lab from S2 to S7`, head `codex/auto`, base `main`, legacy cross-stage parent PR.
- PR #5, `[S7] make repeated axes bot-comparable`, head `codex/s7c-bot-cadence`, base `codex/auto`, stacked child PR.

Treat this as a temporary exception, not the pattern for future work. The safe order is parent first, then retarget child PRs to `main`, then recheck all gates.

Refresh this stack note from GitHub at the start of every autonomous run.
