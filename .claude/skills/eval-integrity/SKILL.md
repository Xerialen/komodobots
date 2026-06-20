---
name: eval-integrity
description: MANDATORY whenever evaluating, validating, summarizing, or reporting ANY data — eval results, metrics, gates, benchmarks, experiment or test output, training runs, measurements — and before stating ANY conclusion about what the data shows. Counters overstating results. Forces validating a metric's MEANING (not just its value), tagging every number's provenance, inspecting the ground-truth artifact, applying equal skepticism to passes and fails, and keeping claims within the evidence. Apply it on every single data evaluation, positive or negative.
---

# Eval integrity — say only what the data shows

Run this on EVERY data evaluation, before stating any conclusion, headline, or recommendation. It exists because a real failure happened (see "The case"): a passing gate number was reported as "human-level" when the underlying behavior actually failed and fell into the void. Recomputing the metric from raw did NOT catch it — because the metric's value was right; its meaning was not what was claimed.

## The failure mode this counters
Reporting a metric — especially a PASS or any positive result — as a bigger result than the raw evidence supports, by: checking a number's VALUE but not its MEANING; carrying a number from one run into a claim about another; applying less scrutiny to good news than to bad; and using words ("solved", "confirmed", "human-level", "milestone", "cleared") that outrun the evidence.

## Mandatory checks — ALL of them, every eval, before you conclude
1. **What does the metric EXCLUDE?** Open the caveats / `diagnostics_not_gated` / `*_not_gated` / footnote / "what this does not measure" fields — not just the headline score. Write one explicit line: *"This pass does NOT prove ___."* A gate or proxy passing is never the same as the real goal being achieved.
2. **Provenance on every number.** Tag each figure with the run/config/checkpoint/split/seed it came from (seeded vs unseeded, train vs val, which ckpt, which route). NEVER compare, average, or carry a number from one run into a claim about a different run.
3. **Ground truth over proxy.** Inspect the actual artifact the metric summarizes — the trajectory, the raw rows, the produced output, the real behavior — not just the summary statistic. Measuring movement? Look at the path. Measuring text quality? Read the text. If you cannot see the underlying thing, you cannot conclude about it.
4. **Symmetric skepticism.** Interrogate a PASS exactly as hard as you interrogate a FAIL. Ask, in writing, *"What would make this look better than it actually is?"* — then go check that specific thing. Decompose positives the way you decompose negatives.
5. **Words ≤ evidence.** Do not write "solved / confirmed / works / cleared / human-level / milestone / first success / near-human" unless the evidence demonstrates that exact claim. Otherwise state precisely what happened: *"passed metric X, which measures Y and excludes Z."*
6. **Lead with the limitation.** Put the caveat / what-it-doesn't-show BEFORE the headline. No celebratory framing ahead of the evidence.

## Every eval report MUST include
- A one-line **"What this does NOT prove:"**
- **Provenance tags** on the key numbers (run / seed / split / ckpt / config).
- The claim stated at exactly the strength the evidence supports — no stronger.

Litmus test: if the owner/reviewer would have to say *"show me the actual behavior"* to catch an overstatement in your report, you skipped check #3 and you are not done.

## Red flags — stop and recheck
- You're about to call a passing proxy "the goal," "human-level," or "a milestone."
- A number in your conclusion came from a different run than the one you're concluding about.
- You validated the headline metric but never opened the caveats / diagnostics block.
- You feel more excited (or more relieved) than the raw artifact actually justifies.

## The case (why this skill exists)
Reported: *"first full-gate clear — the bot bunnyhops dm3 hilljump at 83% human speed, near-human cadence (.25), human-level."*

Truth: `route% = 89.7` is **arc-length progress to the launch ledge, not route completion**; the bot **fails the ~525 qu/s launch leap and falls into the void** — `cleared_launch: false`, `class: REACHED_LEDGE_NO_JUMP`, both sitting in the very JSON that had been "validated." The `.25` cadence was from the **seeded** trace; the actual unseeded gate run jumps `.068`, far below the human's `.22`.

Three failures, one per broken check above: (1) validated the metric's value, not its meaning [#1]; (2) mixed seeded and unseeded provenance [#2]; (3) words outran the evidence [#5]. It was caught only because the owner said *"show me"* — which forced pulling the x,y,z trajectory, the ground truth that check #3 demands first. Do the checks so the owner never has to.
