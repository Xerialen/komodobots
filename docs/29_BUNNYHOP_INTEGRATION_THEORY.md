# 29 — Bunnyhop Integration Theory

**Status:** theory / proposal — owner-requested (2026-07-03). No new experiments were run
for this document. Every claim is sourced from engine code, this repo's committed
evidence, or komodobots2's bench ledger, with provenance tags inline. The experiment
ladder in §7 is the validation plan; until it runs, this is a hypothesis document, not
a result.

**The question (owner's framing).** The bunnyjump input code is cracked and bots can
replicate it — but making the bots *know when to use it to gain an advantage* has
failed: whenever the bots are told to use the skill, they play worse. What did
komodobots (gen 1, this repo) and komodobots2 (gen 2) do wrong, and what should be
built instead so the bots move fast on bunnyjumps **without sacrificing combat and
tactical performance**?

**Citation provenance.** komodobots @ `dbe841b` (this repo), komodobots2 @ `4189ec1`,
`Xerialen/ktx` @ `4f34785` (master = stock Frogbot; the gen-2 `feat/kbot-*` brain
branches were **not** read directly — gen-2 behavior is reconstructed from its
committed findings ledger), `ezquake-source` @ `6a2f2f9`. Line numbers are as of those
checkouts and will drift.

## 1. Verdict

Bunnyhopping was cracked as a **trajectory** (a replayed human input timeline, a canned
weave, a view-yaw-sweeping accelerator) when the game only needed it cracked as a
**control law**. It was expressed in the **human input manifold** (view yaw as the
steering variable, 8-way key quantization) when a server-side bot has a strictly larger
action space in which aim and acceleration are *mathematically independent* (§2.2). It
was integrated as a **whole-actuator mode switch** that confiscates dodging and aim
exactly at engagement onsets. It was gated **reactively** (on current enemy visibility)
when the quantity that matters is *predicted contact within the next hop or two*. And it
was trained and graded on **speed** — a currency with no intrinsic value — while the
metric that prices it, match margin, was measured late (gen 2) or never (gen 1).

Each choice independently degrades play. komodobots2's bench measured their combined
cost: the weave is worth **−25 to −30 frags/game**, monotone in exposure
(always-on −76 → combat-gated −30.6 → predator-gated ≈ −8 relative → no-weave ≈ parity;
komodobots2 `docs/findings-log.md`, 4on4 vs skill-20 Frogbots). Nothing in that ladder
says bunnyhop has negative value. It says *these integration choices* have negative
value.

## 2. The physics the integration must respect

Source: the shared player-movement code every QW server/client runs
(`ezquake-source/src/pmove.c`); the offline training sim (`scripts/pmove_sim.py:737-750`)
ports the same law — see §2.5. Stock movevars (`ezquake-source/src/sv_phys.c:46-58`):
maxspeed 320, accelerate 10, air wishspeed cap 30, friction 4, gravity 800; ~13 ms
(≈77 Hz) command frames. Numbers below scale with actual cmd msec.

### 2.1 The air-acceleration law

Per input frame (`pmove.c:395-416`), with `c = velocity · wishdir`:

```
a       = min(accel · wishspeed · dt,  30 − c)      applied along wishdir
        ≈ min(41.6, 30 − c)                          at stock values / 13 ms
⇒ Δ(|v|²) = 900 − c²                                 whenever the 30-cap binds (c ≥ −11.6)
```

The asymmetry that makes bunnyhop exist: the *gate* (`addspeed`) uses wishspeed clamped
to 30 (`pmove.c:395-397`), but the *gain* (`accelspeed`) uses the un-clamped wishspeed,
typically 320 (`pmove.c:413`). Consequences:

1. **Gain lives in a sliver.** You accelerate only while `c < 30`. At 500 qu/s the
   wishdir must sit within ~3.4° of perpendicular to velocity; the window narrows like
   `acos(30/s)` as speed rises.
2. **Straight-line optimum.** `Δ|v|²` is maximized at `c = 0` (exact perpendicular):
   ≈ `450/s` qu/s per frame → ~86 qu/s² at 400, ~69 at 500, ~58 at 600. Alternating the
   perpendicular side every frame cancels net rotation: from 320, ~415 after 1 s, ~492
   after 2 s, ~612 after 4 s, on a straight line. **This exact policy has never been run
   live** (§2.5, experiment E1).
3. **No friction in air** (`pmove.c:342-343`), and a jump on the ground-contact frame
   clears `onground` *before* `PM_Friction` runs (`pmove.c:917/937/939`) — a
   frame-perfect hop is lossless. Each sloppy grounded frame costs `s·4·dt` (~26 qu/s at
   500). Jump must be **released and re-pressed** per hop (`jump_held` anti-pogo,
   `pmove.c:709-713,739`).

### 2.2 The decoupling theorem (aim-free bunnyhop is exact for a bot)

The engine builds `wishvel = forward·fmove + right·smove`, flattens and normalizes it
(`pmove.c:494-504`): **wishdir depends only on view yaw and the fmove:smove ratio**, and
`forwardmove/sidemove` are signed 16-bit shorts on the wire (`com_msg.c:244,713`) —
effectively continuous. Therefore a bot can place wishdir at **any** horizontal angle
while the crosshair points **anywhere**. Aim-free, full-rate air-strafe is not an
approximation for a bot; it is exact, one 2-D rotation per frame.

### 2.3 Why humans sweep the yaw — and why the bots inherited it anyway

A keyboard quantizes fmove/smove to ±400/0, snapping wishdir to 8 view-relative
directions. The only way a *human* keeps a quantized wishdir inside the narrowing 1–3°
gain window as velocity rotates is to rotate the view. The yaw sweep is a prosthetic for
missing analog strafe — nothing more. Every bunnyhop expression in both repos
reproduced the prosthetic instead of exploiting the freedom (§3): the mode-13
accelerator mouses the view ~85° ahead of velocity, mode 25 replays a human mouse
timeline, the RL brain's yaw head is documented as "the speed mechanism", and the
deployed MoveMLP uses human-key ±400 quantization — which is precisely why it cannot
hold the gain window once the view belongs to combat.

### 2.4 The rest of the movement calculus

- **Commitment quantum.** Jump velocity 270 / gravity 800 → ~0.68 s airborne per hop,
  apex +46 qu. Once airborne, the vertical trajectory is deterministic for the whole
  hop.
- **Turning envelope.** The same `a ≤ 30` budget rotates velocity: speed-preserving turn
  rate ≈ `2310/s` rad/s, cornering limit `s_max ≈ √(2310·r)` for corner radius `r`
  (r = 100 qu → ~480 qu/s, 150 → ~590, 200 → ~680). Harder turns are possible only by
  pushing slightly *behind* perpendicular — unlocking the full 41.6/frame at the price
  of shedding speed (a braking turn).
- **Braking is cheap, reversal is not.** Holding back in air decelerates at ~41.6/frame
  (≈3200 qu/s²): 600 → 320 costs ~0.09 s. But *reversing* means stop-then-rebuild, the
  vertical arc is fixed, and every hop broadcasts the jump sound. The true combat cost
  of being airborne is therefore **vertical determinism + reversal poverty + noise** —
  all of which feed enemy prediction — not helplessness.

### 2.5 Two corrections to the existing evidence base (flagged per eval-integrity)

1. **The mode-13 "physics-optimal angle" rationale conflicts with the source.**
   `experiments/ktx_moveprobe/evidence/accel-optimal-angle-trick-20260607.md` derives
   K = 26 from "accelspeed ≈ 4", i.e. it assumes the *capped* wishspeed enters the gain
   term. The source uses the un-capped wishspeed (`pmove.c:413`), giving
   `Δ|v|² = 900 − c²`, maximized at **c = 0**, not 26. The live result (K=26 beat the
   ~90° arm) is real but is almost certainly a **geometry effect**: at c≈0 single-sided
   the turn radius is ~70 qu at 400 and the bot orbits into walls — which that doc
   itself observed ("a map-blind circle's radius grows as v² and … slams into walls").
   The side-alternating c=0 straight-line policy was never tested. Re-measure (E1).
2. **No sim/live physics skew.** `scripts/pmove_sim.py:737-750` matches the source law
   (including the un-capped-wishspeed gain and the mvdsv accelerate-in-air quirk,
   `pmove_sim.py:932-935`), so Phase-2 RL trains against the right physics. The
   train/serve skew is in the **action space**, not the physics (§3.1).

## 3. What was actually built, and each artifact's defect

### 3.1 Gen 1 (this repo): four bunnyhop expressions, four different defects

| Artifact | What it is | Defect |
|---|---|---|
| Moveprobe modes 3–4 | route-yaw steering + jump | points the **view** down the route — "commandeers view yaw … recorded no frags" (`docs/03_MOVEMENT_PROBLEM.md:221,248`). The one mode that kept combat aim (mode 1, jump-only) is the only override run that fragged (`docs/02_SOURCE_MAP.md:305`) |
| Modes 5–7 (S3g) | aim-independent projection of route intent into fmove/smove | right seam, wrong wishdir *policy*: projects the **route chord**, not a velocity-relative strafe angle, so `c ≈ s` in air → zero gain. S7g measured exactly this: ground speed ≈ human (ratio 0.975), airborne collapses (0.283) (`docs/03:453-458`) |
| Mode 13 accelerator | analytic optimal-angle strafe | physics ~right, but implemented by **mousing the view** ~85° ahead of velocity (`accel-optimal-angle-trick-20260607.md:29-39`) — re-couples the channels modes 5–7 had just decoupled |
| Mode 25 — "the cracked code" | replays the human QWD mouse timeline + phase-gated side magnitude (`bunnyjump-code-replication-20260613.md`) | **open-loop**: owns the view outright, anchored to a replay cursor and one map; fragile off-manifold (Distance retries arrive 6 qu from the release point heading 84.6° wrong and don't jump, `docs/03:155-158`). A museum-grade reproduction of one human run, not a skill |
| RL-on-speed (`ml/rl_onspeed.py`) | PPO in the offline sim | the yaw head is explicitly "the speed mechanism — the policy **owns its movement yaw**" (`docs/02:1106`, `rl_onspeed.py:331-339`). But the **deployed** seam (mode 30 + shm sidecar) sends `fb.desired_angle` (combat aim) as the view and lets the policy pick only sign-quantized fwd/side + jump (`experiments/ktx_moveprobe/live/frogbot-moveprobe-live.patch`, `scripts/move_policy_sidecar.py`, `shard_contract.py:84-90`). **The mechanism the policy learned is amputated at deployment**, and ±400 quantization puts it in the human-keyboard trap of §2.3 |

Net effect: gen 1's "use the knowledge" path either gives the policy the yaw (combat
structurally impossible) or keeps combat aim (speed structurally impossible). That
tradeoff is an artifact of the chosen action space — not of the game (§2.2).

### 3.2 Gen 2 (komodobots2): the honest match experiment that priced it

The weave (mode-23-style bunny at the `fb.dir_move_` seam + circle-jump launch) gave a
real **+19% traversal in free-roam**, and then (komodobots2 `docs/findings-log.md`,
bench = 4on4 vs skill-20 Frogbots, n≈8–12 per cell):

```
always-on weave (0.2.0)        −76      "destroys combat"
combat-gated, 1.5 s hyst (0.3.0) −30.6
weave + items (0.4.x)          −32/−36
pure-delegation skeleton, NO weave −5.6  ≈ control parity (null experiment)
predator-weave (0.6.0)         +1.25 vs +9.1 discipline-only  (≈ −8 relative)
discipline champion (0.5.0)    +9.1     zero movement tricks
```

Documented mechanism (`findings-log.md:329-334,185-188`): the weave "overrides frogbot
combat movement (strafe-dodge, engagement micro), producing fast, straight, predictable
flight paths that skill-20 aim punishes, while the kbots' own aim never stabilizes";
"the first moments of every engagement are still weave-mode = no dodging." Weave and
auto-launch are formally parked pending new evidence (`current-stage.md:32-34`). The
champion candidate gates *hunting* by stack — macro expected-value beat micro speed.

### 3.3 The substrate amplifies the cost (stock Frogbot, `Xerialen/ktx` @ 4f34785)

- Dodging runs **only when `FL_ONGROUND`** (`src/bot_botthink.c:153`); combat-jump and
  RJ logic are ground-gated (`src/bot_botjump.c:428`).
- The bot's **own** injected aim error inflates when airborne and when fast
  (`self_midair_volatility`, `ownspeed_volatility`, `src/bot_aim.c:259-292`) — note this
  is a *skill-model dial*, not physics; it can be retuned for Megalodon Milton, but it
  is on today.
- Navigation steers **straight at the next marker** with touch-box arrival
  (`src/bot_botthink.c:217-219`, `src/marker_load.c:254`) and `sv_maxspeed`-calibrated
  travel times feeding route *and enemy* selection (`src/route_lookup.c:13-24`,
  `src/bot_routing.c:70,127`). At 500+ qu/s the bot overshoots markers and its own
  route/target scoring goes stale.

A continuously-airborne bot therefore simultaneously loses dodge micro, loses
combat-jump, suffers doubled injected aim error, overshoots markers, and corrupts its
own tactical scoring. Every one is a *separate* "plays worse" channel; all fire at once
when the weave flips on.

Two buried gems in the same code: the command emitter **already** projects a
world-space `fb.dir_move_` through the current aim yaw into fmove/smove every frame
(`src/bot_movement.c:519-521,561-562`) — the decoupled actuator exists; and Frogbot's
conservative air-steering numerators are **29 and −8.4** (`src/bot_movement.c:191-192`)
— a `c`-target just under the 30-cap and a behind-perpendicular braking turn. The
correct law is already half-encoded there, clamped to marker-seeking, with no jump
chaining.

## 4. The five mistakes, stated as theory

1. **Wrong manifold.** The skill was represented where humans live (view yaw +
   quantized keys) instead of where bots live (continuous world-frame wishdir + jump
   bit, view free). Using the skill therefore *costs the aim channel* — a structural
   mortgage on combat. Explains "commandeers yaw → no frags" (gen 1), "aim never
   stabilizes" (gen 2), and the RL self-yaw → deployed no-yaw amputation.
2. **Wrong control class.** Replay and canned weaves are open-loop; they cannot recover
   from perturbation, start from arbitrary states, or *blend* with other objectives —
   only switch. Bunnyhop is a per-frame feedback law with three inputs (velocity,
   desired course, ground flag) and a closed-form optimum; anything stiffer throws away
   composability.
3. **Wrong arbitration.** Both generations transfer the *whole actuator* between
   movement brain and combat brain. Mode boundaries are dodge-less, aim-less windows —
   and engagements, by definition, *begin at mode boundaries* (the gate flipping is
   what "engagement" means). With time-to-kill at skill-20 aim shorter than gate
   latency + one hop (~0.7 s), the bot loses the opening exchange of every fight —
   compounding to the measured −25/−30. Freezing Brain-1's weights (docs/28) does not
   fix this: **freezing allocates parameters, not actuators.** If Brain 1 owns yaw,
   Brain 2 can never be trained "with movement frozen" — they collide at the usercmd.
4. **Wrong decision variable.** All gates tried are *reactive* functions of current
   visibility. At 500+ qu/s with a 0.68 s hop quantum and `√(2310·r)` cornering, the
   relevant quantity is **predicted contact within the next 1–2 hops** — a function of
   map region, item spawn clocks, and sight/sound memory. Gen 2's same-frame weave drop
   still lost ~8 points because "damage already inbound". A correct gate *tapers speed
   before contested space* (braking is cheap; the decision must precede the last hop)
   and is hysteretic both ways. Building it from sight/sound belief instead of engine
   omniscience is the information-honesty Brain-3 needs anyway (docs/28 trigger (b)).
5. **Wrong objective and blind evals.** The reward (`reward_onspeed.py:311-316`) prices
   route-relative speed, progress, and strafe mechanism — no combat exposure, no
   arrival-time value, no noise; the program of record grades route-isolated speed and
   defers match signal to Phase 4 (`docs/28:60-71`). "Plays worse" was therefore
   *invisible by design* in gen 1's loop and only became measurable when gen 2 built a
   margin bench. Speed is a currency (time-at-objective, angles, escapes); a trainer or
   eval that prices the currency instead of the goods will always buy speed at a loss.

## 5. The architecture to adopt

**A. Channel-ownership contract (non-negotiable core).**
View yaw/pitch: owned by combat/aim, always (stock Frogbot aim today, Brain 2 later);
movement never writes it — out of combat, aim may cosmetically follow the route as a
*consumer* of movement state. fmove/smove: owned by the motor as a **world-frame
wishdir**, projected through whatever yaw aim chose this frame (the projection at
`bot_movement.c:519-521` already does exactly this). Jump bit: owned by the motor with a
combat veto line (suppress the next hop when a ground pivot or silent hold is demanded).
This converts "speed vs combat" into "speed vs agility" — a small, quantifiable cost you
can gate on, instead of a structural one you cannot.

**B. The motor: an analytic carve controller (~50 lines), replacing replay/weave/mode-13.**
Per frame: read velocity, desired course, ground flag; choose the carve parameter `c`
(0 = max gain, up toward ~29 = gentle arc, slightly behind-perpendicular = braking
turn); set world wishdir = velocity rotated to realize `c`, side chosen toward the
course, alternating sides to hold a line; re-press jump on the contact frame. Stateless,
starts from any entry state, no cursor, no activation radius, no map. RL then rides **on
top, in the same yaw-free action space** (c-schedule, corner entries, trick primitives
as residuals against the analytic prior). This simultaneously kills the train/serve
mismatch (trained and deployed action spaces become identical), the over-press attractor
class (forward-press is not an available action), and the strafe-cadence residual
(cadence *is* the side-alternation schedule, now owned by the prior).

**C. Speed-aware navigation.**
Annotate route legs (the Highway canon) with **entry-speed envelopes** from
`s_max ≈ √(2310·r)` + corridor width, computed offline from the marker graph + BSP.
Replace straight-at-marker steering with time-based lookahead (aim `dir_move_` at the
path point ~0.5–0.7 s ahead at current speed — pure pursuit). **Arrival-time control**:
speed's value is realized only when it changes an outcome; plan ETA against item spawn
clocks, taper to grounded dodge-speed over the last 1–2 hops into any contested node.
Fast in the middle, slow at the ends.

**D. The tactical gate ("when") — a risk-priced policy, not a boolean.**
Initiation requires all of: leg envelope-validated; predicted contact over the next 1–2
hops below threshold (belief from sight/sound memory + region priors + spawn clocks —
honest by construction); positive time-value (racing a spawn, converting a frag into the
armor sweep, escaping, quad race, denying when behind). Termination: taper *before*
geometry or risk demands it; instant jump-veto + ground pivot on contact; asymmetric
hysteresis (drop fast, re-arm slow — gen 2's design was right; it had nothing good to
arm). Explicitly negative-value situations stay grounded: approaches to likely-held
positions, peeks, holds, tight-corridor rotations against rocket users, any moment the
jump-sound leak outprices the seconds saved.

**E. Evals that can see the cost.**
Promotion of any movement feature requires *both* the route-isolated grade (existing)
*and* a match-margin A/B on the gen-2 bench (motor on vs off, same seeds/opponents,
n≥12), *plus* decomposed combat forensics from the analyzer stack: deaths-while-airborne,
damage taken in the first second of engagements, opening-exchange win rate, item share,
time-from-frag-to-armor. Adopt the bench in this repo now rather than waiting for
Phase 4's 4v4. The forensics attribute *which* cost term dominates, which selects the
next fix.

## 6. When should the bot bunnyhop (the policy content)

Positive expected value: uncontested rotations; converting a frag into the pack + armor
sweep before respawn pressure; racing a contested spawn when otherwise late; escapes
when weak; quad/pent races; recovering map position after losing an exchange elsewhere.
Negative expected value: approaching probable contact (want ground dodge + quiet
arrival + pre-set aim angle); peeking; holding control (silence + ambush beat speed);
tight corridors vs rockets; protecting a lead late (variance reduction). The gate's
output is not on/off but a **speed budget along the planned leg**, tapering into
contested nodes; with channels decoupled (§5A), the residual cost of bunnying is only
agility + noise + predictability, so the gate's job shrinks from "prevent combat
catastrophe" to "spend speed where it buys something".

## 7. Experiment ladder (falsifiable, smallest first)

- **E1 — Law check (one evening, existing lab).** Straight runway, view pinned to a
  fixed point, per-frame velocity-tracked perpendicular alternating carve (c=0).
  Predict ~86 qu/s² at 400 and 320→~490 in ~2 s, zero yaw motion. Also re-run mode-13's
  arms: predict K=26's advantage disappears on a straight line and reappears only under
  corner constraints. Confirms `Δ|v|² = 900 − c²` live and settles §2.5(1).
- **E2 — S7 redemption.** The carve motor behind the mode-7 projection (combat yaw
  preserved) passes the S7i stop conditions that mode 8 failed: pre-air/air/post-air
  p50s rise without regressing non-airborne (baseline: S7g buckets, `docs/03:453-516`).
- **E3 — The decisive one: gen-2 bench A/B.** Weave replaced by carve motor + channel
  contract (aim and dodge untouched; dodge extended to fire airborne using the same
  lateral budget), reactive gate unchanged. Predict: recovers the ~25–30 frag weave tax
  to ≥ skeleton parity while keeping most of the +19% traversal out of combat.
- **E4 — Predictive taper on top.** Predict ≥ discipline champion (+9.1), because
  rotations get faster without paying engagement-onset tax.
- **E5 — RL retrain in the yaw-free action space with the carve prior.** Predict:
  matches self-yaw checkpoint speed offline and — unlike it — transfers to the live
  seam unmodified.

If E3 fails with channels genuinely decoupled and dodge preserved, the theory is wrong
somewhere interesting: residual costs (noise, ballistic predictability, arrival states)
dominate even outside engagements — measurable via §5E forensics, tightening §5D.

**ML Evidence Chain Gate (applies to E5 only; E1–E4 are deterministic controllers +
bench).** Data: unchanged — same route canon / corpus under `docs/25_DATA_CONTRACT.md`;
no new extraction. What changes: action space (world-wishdir `c` + side + jump; yaw head
removed) and an analytic prior; same `pmove_sim` plane for training, live KTX bench for
transfer (planes named, never mixed as one truth). Labels: none new (RL, not BC).
Baseline to beat: (a) the analytic carve prior itself in `pmove_sim`, (b) the best
self-yaw checkpoint's route-grade, (c) live: E3's carve-only bench margin. Kill
criteria: if yaw-free RL cannot match the analytic prior's speed offline, ship the
analytic law alone and keep RL diagnostic; if offline gains do not transfer at the live
seam, the bridge (not the model) is the failure class to isolate next.

## 8. What this does NOT prove

- No experiment above has been run; §2's straight-line optimum is source-derived but
  live-unverified.
- Gen-2 margins are that repo's own bench ledger (4on4 vs skill-20 Frogbots, versions
  0.2.0/0.3.0/0.5.0/0.6.0, n≈8–12/cell), not re-measured here; gen-1's "no frags when
  yaw is commandeered" comes from short movement-focused runs (weak alone, consistent
  with the powered gen-2 ladder).
- The gen-2 `feat/kbot-*` C code was not read; its behavior is taken from its ledger.
- Line references decay as the checkouts move.

## 9. Where validated results should land

E1/E2 evidence → `docs/07_FINDINGS_LOG.md` + `docs/03_MOVEMENT_PROBLEM.md`; adopting the
channel contract / carve motor / gate → `docs/08_DECISION_LOG.md` and a docs/28 Phase-1/2
amendment (Brain-1 action space, handoff design, promotion gates); bench adoption →
`docs/22_TEST_CASES_AND_EVIDENCE.md`. The komodobots2 twin of this document is
`komodobots2/docs/bunnyhop-integration-theory.md`; its E3/E4 results land in that repo's
findings ledger and decide whether the parked weave is replaced by the carve motor.
