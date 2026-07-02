# D7 — potential-based sustain-speed shaping + speed/adherence rebalance (design plan)

Status: REVIEWED (dual pre-flight 2026-07-02: auditor vs origin/main SOUND-WITH-FIXES + NotebookLM
methodology review — all must-fixes folded, see §9). Track: #427 Phase-2 reward. Pre-registered as
**D7** in `plans/phase2-next-step-decisions.md`. Owner authorized the design round 2026-07-02 after
the long-run convergence probe. Code base for all line refs: `origin/main` @ `8d3b3df`.

---

## 1. Trigger — the pre-registered condition, and one formal AMENDMENT

D7's return condition (verbatim, `plans/phase2-next-step-decisions.md`): *"Return to it ONLY if the
honest route-grade (D1) shows the sustain-speed problem persists after D6 (phase-correct forward
penalty) + #429 (`w_press`) + decision B (anchor off)."*

Precondition status: **decision B holds** (the sweep-2 winner runs anchor-off, `kl_coef 0` +
ceiling `1e9`); **#429 ran** (two sweeps, 42 runs, w_press confirmed live, winner w_press 2.516);
**D6 is designed but NOT landed.**

**AMENDMENT (formal, goes into the D7 entry in the same PR):** the D6 precondition is waived on
direct evidence — the failure mode D6 targets (ground `+forward` bulldoze) measured `fwd_press
0.000` in every probe stage's rollouts, i.e. it is not the active failure; requiring D6 first would
gate this round on a fix for a behavior that is not occurring. This is a deviation from the
pre-registered sequence, logged as an amendment (not a footnote); owner ratification = approving
this plan/PR. D6 itself stays parked and is NOT folded in here.

**The evidence (2026-07-02 staged long run, 3 × 2M steps of the sweep-2 winner config
`aa1aaf5477a9` — the program's first convergence datum; no prior run exceeded ~360k steps):**

| ckpt | ranked 27 val routes (offset 0): seg_faster_frac / median ratio / rmse | tertiary 27 never-ranked (offset 27): faster / rmse / on_route |
|---|---|---|
| winner 200k | 0.0741 (=2/27) / 0.0 / 80.9 | — |
| stage 1, 2M | 0.1111 (=3/27) / 0.0 / 57.6 | 0.1481 (=4/27) / 59.9 / 0.926 |
| stage 2, 4M | 0.1111 / +0.0633 / 42.3 | **0.0370 (=1/27)** / 29.7 / **1.000** |
| stage 3, 6M | 0.1111 / +0.1235 / 50.8 | 0.0741 / 42.0 / **1.000** |

- `seg_faster_frac` EXACTLY flat across 2M/4M/6M (the same 3-of-27 value); stage-3's best
  candidate came EARLY (it247; later snapshots had worse medians).
- Tertiary = the **route-hugger signal**: adherence climbs to perfect (on_route 1.000, rmse
  halves) while faster-than-sim-human DECLINES from the 2M point — the D5-documented failure mode
  ("hug the route at half speed") as the dominant gradient direction at scale.
- Rollout behavior stayed clean all stages (fwd_press 0.000, ap_rate 0.01–0.08, in-env hspeed
  320–330): the policy HAS the air-strafe mechanism; the gap is sustained along-route speed on
  held-out routes.
- 30× compute moved the speed axis zero quanta ⇒ compute ruled out; **reward geometry is the
  binding constraint.**

**Instrument resolution (corrected by audit):** `seg_faster_frac`'s denominator is ALL graded
segments (`route_grade.py aggregate`), so the 1-segment quantum is **1/27 ≈ 0.037**. The
10–14-of-27 invalid control references per chunk set the metric's **CEILING** (e.g. 13/27 ≈ 0.481
ranked), not its quantum — headroom above today's 0.1111 exists but is capped well below 1.0.

> **Provenance / non-gating note (the #466 rule):** the table is decision rationale, NOT merge
> evidence — this PR gates only on its unit-tested code change. Artifacts: pinnacle
> `/home/xerial/rl-onspeed/longrun/20260702/` (experiment_registry.jsonl, ckpts, eval JSONs
> `baseline_winner200k_offset0.json`, `stage{1,2,3}_tertiary_offset27.json`, logs), CODE_VERSION
> `8d3b3df`, runner `run_longrun_stage1.sh`.

## 2. Diagnosis — where the geometry pays adherence and not sustained speed

Code facts (`experiments/route_observatory/reward_onspeed.py`, origin/main):

1. **Speed GAIN is an impulse; speed LOSS has no matching impulse.** `r_phi_raw = min(1,
   max(0, ds)/avail)` (`:160`) pays a concentrated credit on gain ticks and exactly nothing on
   loss ticks. Losing speed does lower `r_vel` (and `r_prog`) the SAME tick — but only as a small
   per-tick stream (~0.5/tick at ratio 0.5), not as the symmetric impulse. At the moment PPO
   chooses between "hold the hard turn" and "ease off", the ease-off's cost is time-smeared by
   GAE(λ=0.95) + an imperfect value net; the gain side is not.
2. **Adherence is paid densely and speed-independently.** `r_strafe = perp_frac` on every
   airborne tick above `band_lo*0.5 ≈ 126 qu/s` (`:166`), weight 0.6. A bot hopping ON the route
   at ratio 0.5 collects ~0.6/tick from this term alone — roughly HALF its per-tick income —
   without ever going faster. This is the hugging subsidy.
3. **The speed axis is carried almost alone by `r_vel`.** Ratio 0.5 → ~0.5/tick vs ratio 1.0 →
   1.0/tick (`velocity_reward` is identity below 1); `r_prog` adds a small speed-scaled stream
   (~+0.03/tick over the same range). The marginal reward for the HARD skill (sustained
   faster-than-human on unfamiliar geometry) is ~0.5/tick; the EASY skill (tight adherence at
   half speed) already collects ~1.1/tick.

The long-run curve is what this mix predicts at scale: rmse falls stage after stage (dense smooth
adherence gradient), faster_frac pinned (weak speed gradient whose local path crosses an
immediate-reward valley: harder turns → collisions/off-route ticks → instant `p_collide`/`r_vel`
loss).

## 3. Design — two levers, separated honestly

- **Hypothesis P (path):** fast-sustain is (near-)optimal under the current mix, but PPO cannot
  TRAVERSE to it — credit for holding speed arrives too late/diffusely. Fix: re-time credit
  without touching the optimum ⇒ potential-based shaping (lever 1).
- **Hypothesis O (optimum):** the mix's optimum itself is the hugger — adherence income dominates.
  No invariant term can fix that by construction. Fix: rebalance the mix (lever 2).

### Lever 1 — the D7 term: `F = γ·Φ(e′) − Φ(e)`, Φ over the speed-EMA ladder

Additive per-tick shaping in `compute_step_reward`, gated by `w_sustain` (**default 0.0 = OFF**;
appended LAST in the mix expression so weight-0 parity is byte-exact):

```
Φ_ladder(h) = ∫₀^min(h, sustain_cap) dx / phi(x)          # phi(x) = √(x²+900) − x  (:57)
            = [ h·√(h²+900)/2 + 450·asinh(h/30) + h²/2 ] / 900   (closed form, stdlib math)
e′ = e + sustain_ema · (hspeed − e)     # hspeed-EMA in the reward carry (self-seeds from
                                        # prev_hspeed on a legacy carry — no reset-code change)
F  = sustain_gamma · Φ_ladder(e′) − Φ_ladder(e)     # per-tick |F| structurally bounded (below)
reward += w_sustain * clamp(F, ±sustain_clip)       # sustain_clip 50 = never-engaging sanity net
```

- **Ladder normalization:** `dΦ/dh = 1/phi(h)`, so one physics-perfect air-gain tick raises Φ by
  ≈1 at any speed (first-order: 1.021 at h=100, 1.002 at h=320 — tests assert the tolerance, not
  exact 1). Φ is denominated in the same "perfect pump-ticks" currency as `r_phi_raw` (literally
  its density, `ds/avail`); losing X qu/s charges what re-climbing it would pay. A linear Φ would
  over-credit low-speed deltas ~3× vs high-speed. Reference: Φ(150)=26.4, Φ(320)=115.6.
  Scope choice (explicit): Φ reads raw horizontal speed (as an EMA) — the same currency as
  `r_phi`/the mechanism credit — NOT along-route speed; the route-relative axis stays `r_vel`'s
  job, and invariance makes the scope choice safe (it re-times, it cannot redirect the optimum).
- **The EMA (implementation-stage REVISION — replaces the reviewed draft's ±3 per-tick clip on
  raw hspeed, which implementation arithmetic exposed as unsound):** bhop's ROUTINE
  ground-contact friction tick bleeds ~16.6 qu/s at 320 (`v·friction·dt`) = **−11.9 Φ in one
  tick**, regained over the next ~12 air ticks at ≈+1 Φ each. A ±3 clip truncates the one-tick
  charge but not the spread-out regain → **≈+8.9 Φ PHANTOM income per hop at CONSTANT speed**
  (≈+0.7/tick — a hidden dense bonus stronger than `w_strafe`, precisely the non-invariant
  prescription the form was chosen to exclude); raising the clip above the sawtooth (≥~30)
  re-admits the loss spikes it existed to bound. The EMA (`sustain_ema` 0.02, ~50-tick/0.65 s
  horizon) dissolves the dilemma: the potential rides a state that barely sees the sawtooth
  (steady bhop nets ~0 beyond the drag, EXACTLY, no clipping anywhere — test-locked), sustained
  decay still charges starting the same tick (spread over ~1/α ticks, total exact), and a
  wall-stop from 320 charges ≈−5.6 on the first tick (−4.5 ΔΦ − 1.1 drag) decaying geometrically
  instead of −115.6 at once (the auditor's loss-spike objection resolved structurally, not by
  truncation). Per-tick |F| is **structurally bounded** by `γ·α·cap/phi(cap) + (1−γ)·Φ(cap) ≈
  55.1` — BOTH parts matter: the delta audit caught that the ΔΦ-only formula (≈44.5) understates
  it and a clip of 50 would engage INSIDE the cap (e=1000, h=0 → |F|=54.7). `sustain_clip` is
  therefore 60: a never-engaging sanity net (an ENGAGING clip would re-open the phantom-income
  hole on climb-crash cycles) — the corrected inequality is test-locked. Invariance: Φ(e) with
  `e` in the reward carry is a potential over the AUGMENTED state (the carry is part of the
  state) — Ng-invariance holds unchanged. Trade-off, owned: a loss's charge spreads over ~0.65 s
  instead of one tick — still orders denser than the diffuse future-`r_vel` signal it
  supplements. (Friction-tick wording per the delta audit: the sim jumps BEFORE friction, so a
  frame-perfect hop skips the friction tick — the sawtooth is the ROUTINE IMPERFECT-timing case,
  training ground-fraction ~0.1–0.2, which is exactly the statistical regime that matters.)
- **Invariance, stated precisely:** within the clip regime the term is potential-based
  (Ng-invariant) — converged advantages unchanged (A′=A); what changes is TD-error timing while
  the value net has not absorbed Φ: decay ticks get an immediate negative burst, holds keep their
  earned potential. That is "denser OUTCOME credit", and ALL it can do — **lever 1 tests
  hypothesis P and can do nothing about hypothesis O.** Residuals, owned: the fixed-horizon
  terminal term `γ^T·Φ(s_T) − Φ(s_0)` (≈ +2.4·w_sustain per 385-tick episode at 320 — mild "end
  fast" pressure, goal-aligned) and the clip attenuation above. Neither can construct a
  prescribed-motion optimum — the r_cad-trap guarantee this form was pre-registered for stands.
- **The invariance price (γ-drag):** holding h costs `−(1−γ)·Φ(h)` per tick (320: −1.156·w_sustain;
  150: −0.264·w_sustain). Before the value net absorbs Φ this reads as "being fast is taxed" —
  NotebookLM's early-training risk. Mitigation (folded): the sampled range is capped at
  log-uniform(0.05, **0.6**) so the drag at 320 stays ≤ ~0.7/tick vs the ~1.6/tick fast-hold
  income; w_sustain=0 arms remain in the space; if ALL w_sustain>0 arms collapse at 200k, the
  named escalation is an ANNEALED-weight variant (rejected now: trainer-schedule complexity +
  anneal-time non-invariance for a risk the sweep itself detects).
- **γ mirrored to the trainer:** `sustain_gamma` defaults to 0.99 == `compute_gae`'s γ
  (`ml/rl_onspeed.py:521`; both call sites `:544`/`:1262` use the default). A stdlib mirror test
  locks the def-site default AND that both call sites pass no explicit gamma (§5).
- **Cap:** Φ flat above `sustain_cap` (default 1000 qu/s); carry already holds `prev_hspeed`
  (`:285-287`, re-seeded at reset) → F never crosses an episode boundary.
- **Diagnostics:** `info["f_sustain"]` always emitted (also at weight 0); rl_onspeed rollout
  logger prints it (`:489-493` pattern, additive).
- **Key validation (audit fold):** unknown `--reward-weight` keys currently pass SILENTLY into
  `_rcfg` (`rl_onspeed.py:649-652` → `:246-247`); a typo'd `w_sustain` would train the control
  silently. New stdlib helper `reward_onspeed.validate_weight_keys(keys)` (raises on unknown),
  called at trainer parse-time; floor-tested.

**Deviation from the pre-registered Φ-argument — explicit.** The parked entry sketched
`Φ(perp_frac)`. The probe shows the MECHANISM is present (clean rollouts, ap_rate ≤0.08, in-env
hspeed 320–330) and perp_frac is already densely paid every airborne tick (`r_strafe`); a
potential over an already-dense mechanism signal re-times nothing of value, and hspeed is the
OUTCOME while perp_frac is mechanical input. Φ(hspeed) keeps every pre-registered constraint —
potential-based, invariant, outcome-not-prescription, reads NOTHING of yaw-rate / hold-length /
cadence (enforced by test). NotebookLM review: deviation "fully justified … a structural
upgrade". Φ(perp_frac) remains the named fallback.

**Considered and excluded:** γ_shape=1 (zero drag but a hidden non-invariant occupancy reward —
the pre-registration demands the γ-form); two-sided `r_phi` (rewrites a KEPT mechanism term's
semantics; the additive term keeps backtrack = weight 0); lowering `w_phi` (mechanism credit is
how bhop is DISCOVERED — round-4 evidence).

### Lever 2 — rebalance the adherence/speed mix (sweep-space v2 — WITH driver changes, named)

`w_strafe`/`w_vel` are already runtime weights, but the audit verified the driver needs real
changes to carry them (NOT "sweep-space only"):

- **`SPACE_BOUNDS`/`sample_config` v2** (`ml/tune_onspeed.py`): `w_strafe` uniform(0.0, 0.6) —
  de-subsidize hugging; `w_vel` uniform(1.0, 3.0) — raise the price of speed; `w_press`
  uniform(2.0, 3.0) — winner-region; `w_sustain` 0.0 with probability 0.3, else
  log-uniform(0.05, 0.6) — explicit only-rebalance arms make P vs O separable.
- **`trial_argv` generalized:** today it special-cases ONLY `w_press` (`:160-164`); v2 maps every
  sampled key present in `reward_onspeed.DEFAULT_WEIGHTS` to `--reward-weight k=v`.
- **`trial_config(seed, 0)` redefined under v2:** today trial 0 = `{}` = incumbent defaults —
  which resolve to anchor ON (`kl_coef 0.05`), lr 3e-4, w_press 1.0 (`rl_onspeed.py:1337-1344`,
  `reward_onspeed.py:69`) — NOT a valid control for this question. v2's trial 0 = the pinned
  sweep-2 winner override dict (w_sustain 0, w_strafe 0.6, w_vel 1.0, w_press 2.516 + the PPO
  values below): the incumbent GOING INTO this sweep IS that winner.
- **PPO dims PINNED to the winner** (lr 1.77e-4, clip 0.237, ent 1.08e-4, minibatch 768,
  anchor-off `kl_coef 0` + ceiling 1e9) — isolates reward geometry, the question D7 asks.
  Provenance for the pinned constants (off-repo facts): sweep-2 verdict
  `sweeps/20260702b/verdict.json` + registry, config_id `aa1aaf5477a9` — cited in the space-v2
  comment + the PR body. Accepted risk: the new mix might prefer other PPO params — a follow-up
  joint sweep only if the geometry levers show signal.
- **`SPACE_VERSION` v1→v2** (journaled with bounds in the verdict). **v1 test locks rewritten in
  the same PR (named):** `test_trial_zero_is_the_incumbent_control` (trial 0 == {} → == the
  pinned control dict), the w_press-bounds lock, `test_argv_shape`, `test_kl_ceiling_pairing` —
  each re-locked to v2 semantics. §5's "existing suite untouched" applies to the REWARD tests,
  not these driver locks.
- **config_id / journal mechanics, pre-explained (audit fold):** `config_id` hashes args + the
  RESOLVED reward config (`experiment_registry.py:100-105`) — 3 new DEFAULT_WEIGHTS keys give the
  v2 control a **different config_id than `aa1aaf5477a9`** even at identical behavior, and
  `environment_hash` includes `code_version` (`:128-132`) so every post-D7 run is a new
  environment group; `rank_runs`/`best` and the tune verdict REFUSE cross-group ranking — by
  design. Within the D7 sweep everything shares one group (per-sweep registry) so ranking,
  seed-verify, off-ramp and control-comparison are journal-legal; comparisons against the OLD
  datums (0.1111 etc.) are MANUAL decision-rationale (same instrument, same routes, different
  code_version) and are labeled exactly that, never journal rankings (#466 rule).

## 4. Verification protocol (the proven instrument, unchanged — rules ENFORCED in driver code)

Instrument = the honest relative route-grade + journal + tuning loop as-is — NO grade/eval changes
in this PR; every number is same-instrument/same-routes comparable with the probe (manually, per
§3 above).

1. **200k sweep** on pinnacle (space v2): 25 trials + top-3 × 5 seeds, `--reset-split train
   --n-reset-segments 1227`, ranking on 27 val routes offset 0, tertiary offset 27 — identical to
   the probe environment. Trial-0 control = the §3 pinned winner config, and (driver change) the
   **control is ALWAYS seed-verified to the full quota** — never a 1-seed control mean vs a
   5-seed winner mean.
2. **Promotion rule — enforced in the verdict, not prose:** the verdict emits
   `beats_control_margin = winner_mean − control_mean` and `promotion_eligible = (margin ≥
   0.037)` (one ranked-segment quantum, the §1 corrected value — NotebookLM's noise-floor fix)
   AND the mechanical guard below. The driver's existing RELATIVE tertiary off-ramp (tertiary <
   0.5 × ranked winner mean ⇒ no winner) stays as coded — the earlier "≥0.075" phrasing was that
   rule instantiated for the old winner, not a fixed bar.
3. **Mechanical guard (NotebookLM fold, enforced):** a winner whose tertiary
   `seg_clean_mechanism_frac` < 0.9 is REFUSED regardless of faster_frac (anchor-off + geometry
   optimization must not promote a physics/bulldoze artifact; the field already exists in the
   grade summary). Rollout diagnostics (fwd_press, ap_rate, hspeed) recorded per stage as
   operator notes, thresholds pre-registered here: fwd_press ≤ 0.1, ap_rate ≤ 0.15.
4. **ONE 2M long-run point** of a promoted winner — same runner template as the probe
   (INIT=`rl_round6_r4init.pt`, 2M steps, seed 1003), graded on the SAME 27+27 routes.
   Read-out against the probe curve (manual, non-gating, labeled): ranked faster_frac vs 0.1111
   and tertiary vs 0.1481/on_route 0.926 — a geometry win = ranked point ≥ 0.1481 (≥ +1 quantum
   over the plateau) AND tertiary NOT declining into the hugger signature.
5. **Kill rule (pre-registered):** no arm promotion-eligible at 200k AND (if a 2M point was run
   anyway) the 2M point ≤ the stage-1 datum on both axes ⇒ D7 track closed; escalate to owner
   with the remaining options (deeper mix redesign; data-line growth #425/corpus wiring;
   instrument-ceiling work — the 13/27 valid-ref CEILING caps how much any reward change can
   show).

superhuman_claim stays `false` throughout (sim-relative instrument); any live/MVD publish remains
owner-gated (docs/28 recording mandate).

## 5. Pre-registered guards → the exact enforcing tests (stdlib, gating floor)

| Guard | Test (`tests/test_reward_onspeed.py`) |
|---|---|
| γ-weighted ΣF telescopes EXACTLY to `γ^T·Φ(e_T) − Φ(e_0)` on an arbitrary trajectory incl. a hard stop (the cannot-manufacture-income property) | `test_sustain_telescoping_exact` |
| THE phantom-income regression (the rejected clip design): steady-bhop friction sawtooth → per-tick F nearly flat (spread < 1 vs raw ~13), net ≤ 0, telescoping exact | `test_sustain_steady_bhop_sawtooth_no_phantom_income` |
| Sustained decay charged as it happens (γ-weighted total ≪ 0, negative from early ticks); climb net-credited; holding pays only the drag (∈ (−1.3, 0)) | `test_sustain_decay_charged_gain_credited` |
| Default OFF: at w_sustain=0 the reward equals the weighted sum of all other info terms exactly; `f_sustain` still emitted; the live lever moves the reward | `test_sustain_default_off_parity` |
| `sustain_gamma` == trainer γ: locks `compute_gae(...)` def-site default AND that every call site passes no explicit gamma; source read with `encoding="utf-8"` (Windows floor, failure-class 6) | `test_sustain_gamma_mirrors_trainer` |
| NEVER keyed to yaw-rate / hold-length / cadence: f_sustain series bit-identical under permutations of `yaw_delta_deg` / `side_am_mag` / strafe-hold carry | `test_sustain_reads_only_speed` |
| Φ monotone non-decreasing, Φ(0)=0, flat above `sustain_cap`; dΦ/dh == 1/phi numerically; perfect-pump ΔΦ ≈ 1 first-order (never exact-1) | `test_sustain_potential_monotone_capped` |
| The clip NEVER engages on honest dynamics within cap: CORRECTED bound γ·α·cap/phi(cap) + (1−γ)·Φ(cap) < sustain_clip (drag term included), worst within-cap tick (e=cap, h=0) under the net; wall-stop first tick ∈ (−8, −3) (immediate, spread, no −115 spike) | `test_sustain_clip_is_sanity_net_only` |
| Unknown `--reward-weight` key REFUSED with valid keys named | `test_validate_weight_keys` |
| Existing REWARD suite untouched-green (the #427/#466 tests) | full floor (1982 OK) |

Driver locks (`tests/test_tune_onspeed.py`): v2 trial-0 == the pinned winner control dict
(provenance-commented); every sampled config's argv carries `--reward-weight` pairs for exactly
the sampled reward keys; PPO dims pinned; `space_version == v2` journaled; control-always-verified
quota; `promotion_eligible`/`beats_control_margin` emitted and the VIOLATING case (margin < 0.037
or `seg_clean_mechanism_frac` < 0.9 ⇒ not eligible / refused) exercised per failure-class 7.

## 6. Files / scope

- `experiments/route_observatory/reward_onspeed.py` — `phi_ladder()`, F term (appended LAST in
  the mix), `DEFAULT_WEIGHTS` += `w_sustain 0.0` / `sustain_gamma 0.99` / `sustain_cap 1000.0` /
  `sustain_ema 0.02` / `sustain_clip 60.0`, carry key `sustain_ema` (self-seeding — no
  reset-code change), `info["f_sustain"]`, `validate_weight_keys()`.
- `tests/test_reward_onspeed.py` — the §5 tests.
- `ml/rl_onspeed.py` — parse-time `validate_weight_keys` call; `f_sustain` collect+print
  (`:489-493` pattern); `--reward-weight` help-string key list updated (`:1412-1415`). No
  training-logic change (torch file: py_compile + the stdlib mirror test are the local net).
- `ml/tune_onspeed.py` + `tests/test_tune_onspeed.py` — space v2 + driver changes per §3 lever 2
  + §4 enforcement (control quota, promotion fields, mechanical guard).
- `plans/d7-sustain-shaping.md` — this plan. `plans/phase2-next-step-decisions.md` — D7 entry:
  PARKED → IN PROGRESS + the §1 AMENDMENT + lever 2's pre-registration home (D7, #429 lineage
  noted). `docs/08_DECISION_LOG.md` — one D7 entry (the #427 convention).

**NOT touched (named):** the route-grade/instrument (`route_grade.py`, eval wiring — verified: it
reads no reward config), the G-MV battery (live ckpt-selection reads it), the data-contract
surfaces (docs/25 Layer-A + feature-store — reward is training code, #427/#465 precedent), D6,
serving path.

**Backtrack (pre-registered in the D7 entry, unchanged):** additive `--reward-weight`-gated term
→ revert = `w_sustain 0` (the default). No data-contract change; no journal-schema change.

## 7. Process

Worktree off freshly-fetched origin/main → stdlib floor green → PR through the Codex gate (coder
role: no merge / no gate labels / no thread-resolution) → after merge, §4 on pinnacle (autonomous
per standing authorization; publishes nothing live).

## 8. What this does NOT prove / honest caveats

- Sim-only, RELATIVE-to-sim-human instrument; nothing here supports a superhuman claim (live
  engine + pov_fuse + recording, owner-gated, is the only path).
- The EMA spreads a loss's charge over ~0.65 s instead of one tick (the price of dissolving the
  sawtooth/clip dilemma, §3) — credit re-timing is therefore dense-but-smoothed, not
  instantaneous; the friction-tick arithmetic behind this trade is in §3 and test-locked.
- Two lever families ride one 25-trial sweep, in tension with the "#429 one-lever-per-round"
  discipline. Justification: they answer ONE pre-registered question (P vs O), the w_sustain=0
  arms (~7-8 expected) + per-arm weights in the journal keep the readout separable, and the real
  datum is the single 2M point either way; a strict split would double GPU rounds for the same
  decision. Instrument noise (seed spread ±0.083 observed in sweep-2) means the 200k readout is
  indicative — the promotion margin + the 2M point carry the decision.
- The valid-ref CEILING (13/27 ranked) caps the observable effect of ANY reward change;
  instrument-ceiling work is a named kill-rule follow-up, deliberately not mixed into this round.

## 9. Review log (dual pre-flight, 2026-07-02)

- **Auditor (code-truth vs origin/main `8d3b3df`): SOUND-WITH-FIXES.** All line refs, the Φ math
  (dΦ/ds=1/phi, Φ(150)=26.404/Φ(320)=115.558, drag, telescoping), plumbing, journal mechanics and
  the D7-entry pre-registration match verified correct. Must-fixes folded: trial-0 semantics +
  named v1 test-lock rewrites (§3), trial_argv generalization (§3), §4 rules now
  driver-enforced + the off-ramp corrected to the coded relative rule, config_id/env-hash
  cross-sweep refusal pre-explained + comparisons labeled manual (§3/§4), quantum arithmetic
  corrected to 1/27 + ceiling stated (§1), D6 waiver promoted to a formal §1 amendment.
  Should-fixes folded: the F loss-spike clip (§3), §2 impulse-vs-stream precision + r_prog,
  first-order ≈1, γ-mirror robustness + utf-8, silent unknown-key validation, invariance wording
  consistency, pinned-constants provenance, one-lever-family justification (§8), help-string.
- **NotebookLM (methodology/honesty): core term sound; Φ(hspeed) deviation "fully justified … a
  structural upgrade".** Folded: γ-drag early-training risk → w_sustain range capped at 0.6 +
  named anneal escalation (§3); promotion margin ≥ 1 quantum (§4.2); D6 skip formalized as an
  amendment (§1); mechanical guard in the kill/promotion rules (§4.3).
- **Implementation-stage revision (post-review, 2026-07-02): raw-hspeed ±3 clip → speed-EMA
  potential (§3).** The reviewed draft's clip (the auditor's loss-spike should-fix, folded as
  ±3) was found unsound during implementation: it converts bhop's routine friction-tick sawtooth
  into ≈+0.7/tick phantom income at constant speed — a hidden dense bonus violating the
  invariance the form exists for. Both reviewers saw the clip variant; neither caught this (it
  needs the engine's per-tick friction arithmetic). The EMA form supersedes it, keeps every
  reviewed property (exact telescoping, immediacy-in-onset, bounded per-tick term, γ-mirror,
  never-keyed-to-cadence), and the failure is pinned as a permanent regression test
  (`test_sustain_steady_bhop_sawtooth_no_phantom_income`).
- **Auditor delta-verdict (scoped follow-up, 2026-07-02): DELTA-SOUND.** Independently
  reproduced the flaw (measured +0.80/tick ≈ +9.6/hop phantom under the ±3 clip; telescoping
  broken by +76.9 over 20 hops) and confirmed the sawtooth regression test FAILS against the
  rejected design; friction arithmetic verified against `pmove_sim.py` (friction 4.0, 13 ms);
  EMA invariance/boundary behavior verified, no new gaming vector found. Its must-fixes folded:
  (1) the "never engages" bound was mis-stated ΔΦ-only (44.5) — corrected to
  γ·α·cap/phi(cap) + (1−γ)·Φ(cap) ≈ 55.1, `sustain_clip` raised 50 → 60, corrected inequality
  test-locked (a 50-clip would engage at e≈955+ full-stops inside the cap); (2) this plan file
  committed in the same PR (every pre-registration pointer targets it). Should-fixes folded:
  wall-stop figure −4.6 → −5.6 (drag term), friction-tick wording softened to the
  imperfect-timing statistical case (the sim jumps before friction), `sustain_ema` added to the
  help-string enumeration, control-outranks-winner verdict note clarified.
