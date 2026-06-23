# QWD ⇄ MVD Fusion Plan + Claude/Codex Labor Division

> **Provenance.** Produced by a dynamic multi-agent workflow (2026-06-14): 1 grounding
> scout + 3 independent design lenses (POV-internal / POV×MVD-sync / distributional) →
> adversarial judge per design → synthesis. Scores: POV-internal **34/50**, POV×MVD
> **34/50**, distributional **29/50**. The synthesis agent verified every load-bearing
> claim against the actual code before writing this. Program of record:
> `docs/18_BENCH_ITERATED_BOT_PROGRAM.md`; earlier staged plan kept for background at
> `references/12_DM3_4ON4_STANDIN_PROGRAM.md`.

## Context — why this exists

We have **massive MVDs** (all-player positions/items/damage/economy, server-frame rate,
**no input commands, no true mouse angle**) and **many QWDs** (one player's exact
usercmds + post-mouse view-angle, plus PVS-culled opponent positions), but the two are
**not from the same games** for the bulk of the corpus. Stage-2 MOVE behavioural-cloning
is GO yet **validation-capped at ~1 s**: the recorded-*human* controller itself drifts to
**88.9 qu by 2 s** because `pmove_sim` omits opponent-player collision (78.6 % of dataset
contamination). The question this plan answers: **how do we combine QWD and MVD
information given they are mostly unmatched, and how do Claude and Codex divide the work
most efficiently?**

## 0. Decisive framing — three bounded channels, no fake row-level fusion

The corpora are unmatched **by construction**, and bunnyhop air-accel chaos caps absolute
trajectory-match at ~1–2 s regardless of opponent fidelity. So **there is no row-level
fusion of the bulk, and we do not fabricate one.** Information combines through three
channels, each used at a specific, bounded moment:

| Channel | When used | Mechanism |
|---|---|---|
| **POV-internal re-parse** (PRIMARY) | MOVE closed-loop ceiling fix + AIM target labels | Decode opponent positions from inside the *same* QWD the self-state came from. Zero cross-recording join, zero sync error. Close-range opponents (the only ones that collide) are always in the POV's own PVS, so the demo already contains them. |
| **Contract-level / distributional** (BULK) | All macro/economy + cohort reconciliation | MOVE/AIM train QWD-only; DECIDE trains MVD-only; they meet ONLY at the typed runtime contract `DECIDE→(target_point, intent)→MOVE/AIM`. The classic-vs-modern cohort offset is reconciled as quantile-aligned speed-band *distributions*, never a frame join. |
| **Matched-pair record-level sync** (OPTIONAL, off critical path) | Validation cross-check only | Self-trajectory cross-correlation on the handful of genuine same-game pairs. Cross-checks the POV-internal opponent track + measures cohort offset. Built ONLY if Step 2 proves POV-internal opponents insufficient — never a training dependency. |

**The headline win (lift the 88.9 qu ceiling) needs no MVD join at all.**

**Sequencing guardrail (Codex #175):** removing *validation-blindness* — the opponent-collision
ceiling (Steps 1–2) plus a distributional gate (Step 3) — is the **prerequisite** for ingesting
the bhop formula/teacher (issue #175). The offline gate must be able to honestly judge a candidate
before one is fed in; formula ingest waits on Steps 1–3, not the reverse.

## 1. Discarded (adversarially flagged — do not build)

- **The `suspicious_later_playerinfo_markers` byte-count gate** (`probe_qwd_route_applicability.py:333` = `payload.count(bytes([SVC_PLAYERINFO]))`). `0x2A` collides with arbitrary coordinate bytes — it validates **nothing**. Replaced by a real ground-truth gate (Step 1).
- **"Reuse the Rust `parse_playerinfo` for QWD."** False: `engine/demoparser/src/mvd/messages.rs:596` is `DF_*`-only (no msec/velocity/usercmd); QWD uses `PF_*`. Only the *wire primitives* port (`EntityUpdate` struct, the `PacketEntities` delta-from-baseline walker). The QWD `PF_*` record path is **greenfield → moderate stateful work**, not a frame-reader swap.
- **"MVD `vp/vya` gives a usable per-frame AIM signal."** Per docs/12 §6, AIM acceptance is *outcome distributions* (LG%/RL direct-hit via damage), not angle fidelity. MVD angle16 is a coarse distributional anchor only; QWD float angle remains the supervision source.
- **Any claim the POV-internal insight is "verified in code."** No opponent origin has ever been decoded in this repo. It is a **hypothesis the Step-1 kill-switch tests.**

## 2. Roadmap (cheapest-disconfirming-first; every step has a kill-check)

**STEP 1 — Prove opponents are decodable from ONE QWD.** *(Codex local, or Claude — hours; READ-ONLY)*
Pick **one named `.qwd`**; extend the QWD record walk to decode
`svc_packetentities`/`svc_deltapacketentities` + multi-player `svc_playerinfo` (`PF_*`), and
**dump entity tracks + a QA report only** — decode-and-dump, no scaling, no mutation. Define
the output schema up front (per entity: `id`, `is_self`, per-tick `[t_ms, origin(x,y,z)]`).
- **Acceptance (executable, not narrative):**
  1. **Known-answer self-track regression (the guardrail):** the decoded *self* entity must
     match the existing `probe_qwd_route_applicability.py` self-state extraction within a small
     tolerance **on the same time samples** — the test against decoding plausible-but-wrong coords.
  2. non-self tracks are **clearly separated** from self;
  3. all origins fall **inside dm3 BSP bounds**;
  4. update **cadence is reported** (not assumed);
  5. **track count is reported and sanity-judged — NOT hardcoded** (PVS + segment timing make
     the live opponent count vary; report it, then judge plausibility — don't pass/fail on "~7").
- **Kill:** self-track regression fails or coords insane → POV-internal premise dead →
  fall back to matched-pair sync (2b) before scaling anything.
- **Do NOT scale to the full corpus until Step 2 passes.**

**STEP 2 — Prove the physics payoff on that one demo.** *(Claude)*
Inject decoded opponent ghosts into `pmove_sim`'s existing `PhysEnt` box-hull path
(Minkowski-expanded boxes; documented hold-last-vs-lerp interpolation + sensitivity
check); re-run the `recorded` controller at 2 s.
- **Acceptance:** 2 s `route_err` drops **materially** from 88.9 qu.
- **Kill:** if not → opponent collision wasn't the binding constraint → stop, re-diagnose,
  do NOT scale extraction to 478 demos.
- **2b (only if Step 1 killed):** Claude builds the self-trajectory cross-correlation
  aligner (velocity-magnitude xcorr + origin-L2 refine + residual-budget fail-closed lock)
  to source opponents from matched MVD. Contingency, not the plan.

**STEP 2.5 — MOVE action-space capacity audit.** *(Claude; runnable NOW — no decode/formula needed)*
Per Codex's #175 review: empirically test whether the discrete **sign+jump ±320** action space
can express elite bhop **before** any formula ingest. On held-out dm3 demos, compare on
**bhop/sustained-speed + route metrics** (not just clean-frame retention): recorded-exact
usercmd vs recorded **sign-quantised** vs air-law prior vs current BC (and later the candidate
formula). Also test **adding yaw-rate / short-history** features to the MOVE state — instantaneous
`dlook` may be insufficient for a trajectory-driven skill.
- **Acceptance:** sign-quantised ≈ recorded-exact on speed/route → the ±320 vocabulary suffices
  and the formula can live inside `state→(fwd,side,jump)`.
- **Kill / escalate:** if sign-quantisation loses material speed/route → **widen the action space**
  (analog magnitude / sub-tick) before ingesting the formula — a model-capacity change surfaced
  now, not discovered late.

**STEP 3 — Scale + migrate the gate.** *(Codex extracts ∥ Claude measures)*
Codex runs the opponent decoder across all 478 demos. In parallel Claude **migrates the
closed-loop gate** from absolute position-error to the distributional metric
(route-segment completion + speed-band retention over many starts, docs/12 G-M1) — chaos
caps absolute-match regardless of collision fidelity, so success must be judged
distributionally.
- **Acceptance:** corpus-wide opponent tracks in the per-tick ghost format; recorded
  controller passes the distributional gate on a held-out set.

**STEP 4 — DECIDE/economy tier (fully parallel, zero QWD dependency).** *(Codex extracts ∥ Claude trains)*
Codex runs Go `mvd_analyzer` (schema v32) over the MVD corpus → damage/items/backpacks/
regionControl JSON. Claude builds the outcome-derived intent labeler (`target_point` =
next loc; intent enum over items/damage/distance + an **abandoned-intent negative class**)
and trains the 2–5 Hz policy.
- **Acceptance:** beats a persistence/blackboard next-macro-transition baseline on held-out MVD.
- **Kill:** if not → keep blackboard-heuristic macro; contract unchanged, MOVE still slots in.

**STEP 5 — Freeze the contract + AIM target dataset.** *(Claude builds, Codex reviews)*
Freeze contract spec v1 (`target_point` vec3, `intent` enum, optional `aim_hint`, dm3 world
coords, 2–5 Hz) as typed doc + Python dataclass + KTX struct shape. Build the AIM
target-selection dataset from QWD: on fire-frames (attack button in usercmd) compute
target-relative aim from self post-mouse view-angle vs decoded opponent positions (reuses
Step-3 tracks).
- **Acceptance:** contract conformance test (MOVE drivable by target_point+intent, no
  leg-level leakage); AIM dataset yields sane target-relative angle distributions at fire frames.

**STEP 6 — Distributional cohort calibration.** *(Claude, lowest urgency)*
QWD speed-band quantiles vs MVD `vx/vy/vz` speed-band quantiles → document the
classic-vs-modern offset + the quantile-alignment anchoring MOVE outputs to the modern
cohort. **Document what it does and does NOT equalize** (a calibration, not a
skill-equalizer; naive application can mask genuine skill differences).

**STEP 7 — Live composite stitch.** *(Claude builds, Codex reviews)*
Run trained DECIDE→contract→trained MOVE/AIM inside `pmove_sim`/KTX on synthetic state
(≥3 clean runs). The ONLY place the two information sources meet at inference.
- **Acceptance:** composite runs; if DECIDE targets are systematically unreachable by MOVE,
  tighten the contract (or invoke matched-pair opponent enrichment).

## 3. Labor table

| Work | Owner | Parallel with | Handoff |
|---|---|---|---|
| Step 1 single-demo opponent decode | **Codex** (local) / Claude fallback | — | tracks → Claude (Step 2) |
| Step 2 physent injection + 2 s remeasure | **Claude** | — | gates Step 3 |
| Step 2.5 MOVE capacity audit (sign-quant vs exact; yaw-rate feats) | **Claude** | runnable now | gates formula ingest (#175) |
| Step 3 corpus-wide opponent decode | **Codex** (local) | Step 3 gate migration | tracks → Claude |
| Step 3 distributional gate migration | **Claude** | Codex Step 3 extraction | — |
| Step 4 `mvd_analyzer` v32 extraction | **Codex** (local) | Steps 1–3 | JSON → Claude |
| Step 4 DECIDE intent labeler + train | **Claude** | Steps 1–3 | — |
| Step 5 contract spec v1 | **Claude** | — | Codex reviews |
| Step 5 AIM dataset | **Claude** | — | Codex reviews |
| Step 6 cohort calibration | **Claude** | — | — |
| `svc_updateuserinfo` roster/name decode + 4on4 verify of the 367 SmackDown* demos | **Codex** (local) | Step 4 | replaces the filename-heuristic `player` column |
| **#170 independent cross-model review** (pmove ghost wiring, contract, DECIDE labels, AIM spec) | **Codex** (different LLM) | each PR | gates merge to `main` |
| Provenance: regenerate `TRAINED_DEMOS.md` after retrains; update docs/12 + ceiling diagnosis | **Claude** | — | — |

Codex owns everything touching the gitignored 9 GB WSL corpus (extraction MUST run local) +
the independent review. Claude owns numerics, sim wiring, metrics, torch tiers, specs.
Steps 3 (extraction) and 4 run fully in parallel.

## 4. Out of scope (and why)

- **Row-level QWD↔MVD fusion of the bulk** — impossible (no matched pairs by construction); we refuse to fabricate it.
- **Learned team coordination** — no source pairs all-four usercmds; stays heuristic. All-player MVD positions are NOT a coordination-training signal.
- **Matched-pair per-tick sync as a training dependency** — demoted to optional validation cross-check; its only concrete payoff (opponent collision) is reachable POV-internally at higher fidelity (QWD self-view vs MVD ~13 ms integer-rounded).
- **Blocking on the bhop formula** — far off; MOVE-BC is GO and the analytic prior exists; the plan does not wait on it.
- **MVD `vp/vya` as per-frame AIM ground truth** — coarse/quantized; distributional anchor only.

## 5. The single first action

**Decode opponent positions from ONE QWD in `~/ctv_decomp/` and dump the opponent origin
tracks**, porting only the wire primitives (`EntityUpdate`, the `PacketEntities`
delta-from-baseline walker) from `engine/demoparser/src/mvd/messages.rs` into a new QWD
`PF_*` record path — NOT the `DF_*` `parse_playerinfo`. Then Claude immediately injects
those ghosts into `pmove_sim` and re-measures 2 s `route_err` on that same demo.

Why first: (a) MOVE is validation-capped at the 88.9 qu opponent-collision ceiling and this
is the only path to lift it; (b) needs zero matched MVD and zero bhop formula, so nothing
blocks it; (c) it is the single highest-leverage extraction (unblocks the collision fix,
AIM target labels, and roster verification at once); (d) it is a kill-switch — if opponents
aren't sanely decodable, the POV-internal spine fails in hours, before any expensive scaling.

**Relevant files** (worktree `…/komodobots-ml`):
- `scripts/probe_qwd_route_applicability.py` — `PF_*` self-decode to extend; **byte-count gate at line 333 must be replaced**.
- `engine/demoparser/src/mvd/messages.rs` — portable `EntityUpdate`/`PacketEntities` primitives (~lines 113-160, 740-790); `parse_playerinfo` at 596 is `DF_*`-only, **NOT** portable.
- `experiments/stage2/move-bc-train/closed-loop-ceiling-diagnosis.md` — the 88.9 qu metric + Step-2 success criterion.
- `references/12_DM3_4ON4_STANDIN_PROGRAM.md` — §5 contract, G-M1 distributional gate, §6 AIM-as-outcome-distribution (background; program of record is `docs/18_BENCH_ITERATED_BOT_PROGRAM.md`).


## 6. Codex review reconciliation (incorporated 2026-06-14)

This plan was produced independently by the design workflow, then reconciled against Codex's two
#175 reviews (the different-LLM check):

- **Initial ML-run review** ([#175 comment](https://github.com/Xerialen/komodobots/issues/175#issuecomment-4701411416)) — verdict **GO for learned MOVE**; sourced the **capacity audit** (now Step 2.5), the **yaw-rate/history coupling** point, and reinforced the **parser-role caution** (§1: prefer `build_replay_command_file`'s time-aligned pairing over the probe's row-order pairing for controller truth).
- **Fusion-plan review** ([#175 comment](https://github.com/Xerialen/komodobots/issues/175#issuecomment-4702015300)) — **endorsed the sequencing**; tightened **Step 1** to executable acceptance (named demo, defined output schema, the **known-answer self-track regression**, read-only, report-don't-hardcode the track count) and added the **validation-before-formula** guardrail (§0).

Where the workflow and Codex independently agreed: POV-internal decode as the primary critical path; matched-pair sync demoted to optional; the `DF_*`-vs-`PF_*` parser trap; opponent-collision (not submodels) as the binding ceiling cause.
