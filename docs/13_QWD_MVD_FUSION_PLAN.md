# QWD ⇄ MVD Fusion Plan + Claude/Codex Labor Division

> **Provenance.** Produced by a dynamic multi-agent workflow (2026-06-14): 1 grounding
> scout + 3 independent design lenses (POV-internal / POV×MVD-sync / distributional) →
> adversarial judge per design → synthesis. Scores: POV-internal **34/50**, POV×MVD
> **34/50**, distributional **29/50**. The synthesis agent verified every load-bearing
> claim against the actual code before writing this. Companion to
> `docs/12_DM3_4ON4_STANDIN_PROGRAM.md`.

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

## 1. Discarded (adversarially flagged — do not build)

- **The `suspicious_later_playerinfo_markers` byte-count gate** (`probe_qwd_route_applicability.py:333` = `payload.count(bytes([SVC_PLAYERINFO]))`). `0x2A` collides with arbitrary coordinate bytes — it validates **nothing**. Replaced by a real ground-truth gate (Step 1).
- **"Reuse the Rust `parse_playerinfo` for QWD."** False: `engine/demoparser/src/mvd/messages.rs:596` is `DF_*`-only (no msec/velocity/usercmd); QWD uses `PF_*`. Only the *wire primitives* port (`EntityUpdate` struct, the `PacketEntities` delta-from-baseline walker). The QWD `PF_*` record path is **greenfield → moderate stateful work**, not a frame-reader swap.
- **"MVD `vp/vya` gives a usable per-frame AIM signal."** Per docs/12 §6, AIM acceptance is *outcome distributions* (LG%/RL direct-hit via damage), not angle fidelity. MVD angle16 is a coarse distributional anchor only; QWD float angle remains the supervision source.
- **Any claim the POV-internal insight is "verified in code."** No opponent origin has ever been decoded in this repo. It is a **hypothesis the Step-1 kill-switch tests.**

## 2. Roadmap (cheapest-disconfirming-first; every step has a kill-check)

**STEP 1 — Prove opponents are decodable from ONE QWD.** *(Codex local, or Claude — hours)*
Extend the QWD record walk to decode `svc_packetentities`/`svc_deltapacketentities` +
multi-player `svc_playerinfo` (`PF_*`) for ONE demo; dump opponent origin tracks.
- **Acceptance (real gate):** ~7 other-player tracks; origins inside dm3 BSP bounds;
  cadence matches network-update rate; **and** the decoded self-player track agrees with
  the already-validated `probe_qwd_route_applicability.py` self origin within a few qu.
- **Kill:** if positions aren't sane / self-track disagrees → POV-internal premise dead →
  fall back to matched-pair sync (2b) before scaling anything.

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
- `docs/12_DM3_4ON4_STANDIN_PROGRAM.md` — §5 contract, G-M1 distributional gate, §6 AIM-as-outcome-distribution.
