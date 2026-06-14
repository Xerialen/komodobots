# Specification — ingesting the human-derived bhop formula into the MOVE model

**Status:** OPEN — awaiting the formula from Benjamin.
**Owner of the input:** Benjamin (the cracked speed/velocity bhop rule, derived from
his ztricks + dm3 bot tests).
**Owner of the integration:** Claude (MOVE tier, `experiments/stage2/move-bc-train/`).
**Applies to:** the dm3 MOVE behavioural-cloning policy (Stage 2, docs/12).

This document states **exactly** what is needed and **exactly** how the knowledge must
be structured so it can be applied in the model. It is a contract: a formula delivered
in one of the accepted formats below drops into the existing pipeline with no
interpretation step. Anything outside these formats requires a conversation first.

---

## 0. Confirmed premises (the reason this spec exists)

1. **MVD does not record player input commands.** It records all players' positions,
   items, damage, and economy — but never `forwardmove`/`sidemove`/`upmove`, buttons, or
   the exact mouse view-angle. Confirmed and load-bearing.
2. **QWD (POV demo) records the input commands** (`forwardmove`, `sidemove`, `upmove`,
   buttons, and the exact post-mouse view-angle), via the client's `CL_WriteDemoCmd`.
3. **Therefore bhop speed/velocity can only be *solved* from QWDs.** Speed is the
   *output* of inputs through the physics; MVD sees the output, not the inputs.
   Benjamin's formula is a QWD-derived rule and is the correct and only kind of artifact
   that can carry this knowledge.
4. **There is already a slot for exactly this kind of rule.** The MOVE pipeline measures
   the learned policy against an analytic prior, `airlaw_action(...)`, in
   `eval_openloop.py`. Benjamin's formula is a **better `airlaw_action`** and plugs into
   the same seam. This spec defines that seam precisely.

---

## 1. The interface the formula must become

The formula must reduce to a **pure, deterministic, per-tick function: state → action**,
matching the existing controller signature. The canonical reference implementation is
`airlaw_action` in `experiments/stage2/move-bc-train/eval_openloop.py`:

```python
def bhop_formula(vx, vy, vz, yaw, onground, *, pitch=0.0, msec=13, phase=None) -> (fwd, side, jump):
    ...
```

- **Pure:** no global state, no wall-clock, no randomness. Same inputs → same output,
  every call. (The sim is deterministic; the controller must be too.)
- **Per-tick:** evaluated once per command frame (~13 ms). It receives only quantities
  available at that tick (below). It may NOT look ahead or read future frames.
- **Cheap:** target < ~0.05 ms/call (it will run 8 bot slots × ~77 Hz live, and millions
  of times in offline sweeps). Closed form or a lookup is ideal; heavy per-call work is not.

### 1.1 Inputs (state) — units and conventions are STRICT

| Arg | Meaning | Units / convention |
|---|---|---|
| `vx`, `vy` | horizontal velocity components | qu/s, world axes (X east, Y north) |
| `vz` | vertical velocity | qu/s (+ = up) |
| `yaw` | **view** yaw (where the mouse points) | **degrees**, world frame, same as the demo's `angles[1]` |
| `onground` | grounded this tick | bool (derived by the sim's `PM_CategorizePosition`) |
| `pitch` | view pitch (optional; bhop is yaw-driven) | degrees, demo `angles[0]` (+ = down) |
| `msec` | this command's duration | integer ms (variable, ~4–26; usually 13) |
| `phase` | OPTIONAL — see §1.3 | only if your rule is phase-gated |

Derived quantities you will likely use (define them the SAME way the model does, so the
formula and the policy see one world):

- horizontal speed `hsp = hypot(vx, vy)` (qu/s)
- velocity heading `vhead = degrees(atan2(vy, vx))`
- **signed view-relative angle** `dlook = wrap180(yaw - vhead)` — degrees, **positive =
  view is to the LEFT of velocity**. `wrap180(d) = (d + 180) % 360 - 180`.
  This single number is the heart of air-strafe: the existing prior strafes toward its
  sign. Your formula almost certainly refines exactly this.

### 1.2 Output (action) — the discrete MOVE vocabulary

Return a 3-tuple `(fwd, side, jump)`:

| Field | Domain | Meaning |
|---|---|---|
| `fwd`  | `{-1, 0, +1}` | forward key sign (back / none / forward) |
| `side` | `{-1, 0, +1}` | strafe key sign (left / none / right; +1 = +sidemove) |
| `jump` | `{0, 1}` | jump button this tick |

**The magnitude is fixed at ±320 qu** (`MOVE_MAG`) — the model's action space is *sign +
jump*, not analog. `move = [fwd*320, side*320, 0]`, `buttons = 2 (BUTTON_JUMP) if jump`.
If your formula's power lives in **analog** forward/side magnitudes or in **sub-tick
mouse rate**, say so explicitly (§5) — that is a model-capacity change, not a drop-in, and
we will discuss extending the action space before ingesting.

### 1.3 Phase (only if your rule is phase-gated)

Your synchronization principle is "preserve timing, add phase-gated strength." If the
formula needs a phase, it must be **derivable from per-tick state** (the sim has no script
clock). Define it explicitly as one of:

- `time_since_ground` (ms since last `onground` true) — the sim can track this, or
- a jump-cycle phase from `vz` zero-crossings / sign, or
- an explicit function `phase(state, history)` you specify.

If you give a phase definition, I will compute it in the harness and pass it in. **Do not**
assume a phase that depends on anything not listed in §1.1.

---

## 2. Accepted delivery formats (pick ONE)

### Format A — Python function (preferred)
A single self-contained function with the §1 signature, pure Python + `math` only:

```python
def bhop_formula(vx, vy, vz, yaw, onground, *, pitch=0.0, msec=13, phase=None):
    hsp = math.hypot(vx, vy)
    if hsp < 1.0:
        return (1, 0, 1 if onground else 0)
    vhead = math.degrees(math.atan2(vy, vx))
    dlook = (yaw - vhead + 180.0) % 360.0 - 180.0
    # --- YOUR RULE HERE: decide fwd, side, jump from hsp, dlook, vz, onground, phase ---
    ...
    return (fwd, side, jump)
```
Deliver as a `.py` file or a code block. This is the literal drop-in for `airlaw_action`.

### Format B — Lookup table (JSON)
If the rule is a measured table (this is how the mode-19 air-law table was compiled):
discretise the state and map each bucket to an action.

```json
{
  "schema": "komodobots.bhop_formula.table.v1",
  "axes": {
    "hsp":   {"min": 0,    "max": 1000, "step": 50,  "unit": "qu/s"},
    "dlook": {"min": -180, "max": 180,  "step": 5,   "unit": "deg, wrap180(yaw-vhead)"},
    "onground": [false, true]
  },
  "default_action": [1, 0, 0],
  "entries": [
    {"hsp": 500, "dlook": 35, "onground": false, "action": [1, 1, 0]}
  ]
}
```
State out of range → `default_action`; missing bucket → nearest-bucket or default (state
which). `action` is `[fwd, side, jump]` in the §1.2 vocabulary.

### Format C — Parametric closed form (coefficients + the equation)
If the rule is an equation with fitted constants, give **both** the equation (in terms of
the §1.1 names) **and** the coefficients, with units:

```json
{
  "schema": "komodobots.bhop_formula.parametric.v1",
  "equation": "side = sign(dlook); jump = onground; fwd = 1 if hsp < V_HOLD else (0 if |dlook| > D_CUT else 1)",
  "coefficients": {"V_HOLD": 700.0, "D_CUT": 60.0},
  "notes": "thresholds in qu/s and deg; derived from getandmaintainspeed + dm3 SNG->RL"
}
```
I implement the equation verbatim; you own the constants.

### Format D — Reference trace + interpolation rule
If the knowledge is "reproduce THIS state→input curve" (a getandmaintainspeed-style
reference), deliver the per-tick reference (`msec, origin, velocity, angles, move, buttons`
— the `.cmds` format the repo already uses) **plus** the rule for mapping live state to a
point on the curve (projection axis, what to interpolate). This is the
`ztricks_reference_trace`/mode-25 shape and is accepted, but note it is a *replay-relative*
controller, not a state-general rule, so it transfers to a single route, not all of dm3.

---

## 3. Domain the formula must cover

State the regime your formula is valid in, so the harness can fail-closed outside it:

- **Speed range** it was fitted over (qu/s) — e.g. standstill→1000, or only the 500–900
  sustain band.
- **Map(s)/route(s)** it was tested on (ztricks getandmaintainspeed, dm3 SNG→RL, …) and
  whether it is meant to be **route-specific** (Format D) or **state-general** (A/B/C).
- **Ground vs air**: what it does grounded vs airborne (the existing prior: jump whenever
  grounded, strafe-toward-look in air).
- **Failure behavior**: what action to emit when state is outside the fitted domain
  (default to the safe prior, or hold forward).

---

## 4. How each format gets applied in the model (the four roles)

Once delivered, the formula is used in up to four ways (more formats → more roles):

| Role | What it does | Needs format |
|---|---|---|
| **Prior / baseline** | replaces `airlaw_action`; the BC policy must beat it (docs/12 KILL gate) | A, B, C |
| **Teacher (pretrain)** | generate (state→action) targets to pretrain the policy before human fine-tune | A, B, C |
| **Residual base** | policy output = formula(state) + learned correction; bakes your physics in | A, C |
| **Input feature** | feed `formula(state)` to the network as a hint | A, B, C |
| **Synthetic labels** | generate optimal pairs for high-speed states the 4on4 demos never reach | A, C |

Format D (reference trace) serves the **Stage-1 hand-mover baseline** on its specific
route, not the state-general roles.

---

## 5. Out of scope / do NOT send here

- **Analog move magnitudes or sub-tick mouse rate.** The action space is sign ±320 + jump.
  If your formula needs analog control, flag it — it is a model change, discussed first.
- **Anything requiring MVD-only quantities** (opponent positions, items, economy). This
  formula is MOVE-tier and must compute from the §1.1 self-state only.
- **Team/decision logic.** That is the DECIDE/blackboard tier, not this seam.

---

## 6. Acceptance — how the formula is validated once delivered

1. **Plug in** as a drop-in for `airlaw_action` (or as the prior the table/equation
   evaluates to).
2. **Open-loop gate** (`eval_openloop.py`): does the formula's `clean_frame_frac`
   retention beat the current air-law prior, and does the BC policy trained with it as
   prior/teacher beat *that*? Success = higher retention than the 0.074-era air-law prior.
3. **Closed-loop gate** (`eval_closedloop.py`): formula-driven sustained speed vs the
   promoted dm3 4on4 anchor bands, and vs recorded human, over the budgeted horizon.
4. **Report** the deltas honestly (including where the formula does *not* help — e.g. if it
   only lifts the speed ceiling but not route retention). No tuning around a null result.

---

## 7. Minimal checklist for Benjamin

- [ ] Formula expressed in terms of the §1.1 names (hsp, dlook, vz, onground, [phase]).
- [ ] Output is `(fwd, side, jump)` in the §1.2 vocabulary — or analog explicitly flagged.
- [ ] Delivered as Format A, B, C, or D (§2).
- [ ] Domain stated (§3): speed range, map(s), route-specific vs state-general, OOD fallback.
- [ ] If phase-gated: phase defined as a function of per-tick state (§1.3).
