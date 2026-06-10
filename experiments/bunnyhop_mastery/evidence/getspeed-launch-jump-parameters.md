# The getspeed.qwd launch, parameter by parameter (engine + KTX, source-grounded)

**Demo:** `C:\nQuake\qw\matchinfo\demos\getspeed.qwd` (sha256 `dfb893a3…`), map *"Zaqwer's Trick Map | No Rocketjumping!"* = **`ztricks.bsp`** *(A5 correction — this doc originally said `trick.bsp`; see changelog 7)*, 2145 cmd-frames @ 76.999 fps, 27.86 s, playernum 0.

> **⚠ A5 CORRECTIONS (2026-06-10, `experiments/a5_distance_standstill/`).** Two data errors found while building on this doc:
> 1. **The map is `ztricks.bsp`, not `trick.bsp`** (the demo's own modellist says `maps/ztricks.bsp`; the Distance room sits OUTSIDE trick.bsp's world bounds). Every §B entity-census claim was made against the wrong file. Re-done on ztricks.bsp: **light ×37, trigger_teleport ×26, info_teleport_destination ×8, info_player_deathmatch ×1, worldspawn — still no `trigger_push`, no velocity-imparting entity**, so the no-pad conclusion survives. The miss-reset is a catcher-slab teleporter under the gap (x −3392..−3000, y 3552..3872, z −576..−568) → destination `t5` `(-3520, 3712, -480)` angle 0; the demo deposits at **`(-3516.125, 3712, -453.125)` yaw 0** — that deposit is the per-attempt start.
> 2. **This doc's input-stream claims were computed on a MISALIGNED .cmds.** The builder zip-pairs cmds (2145, complete) with states (2104 — the server dropped 41), so every drop shifts all later inputs; by the winning attempt the printed inputs are ~0.5 s stale. The time-aligned rebuild (`a5_rebuild_cmds.py`, pipeline lag L=2, anchored replay p95 0.147 qu) shows **the jump bit pressed exactly at the last grounded frame of EVERY launch, including the winner** — the takeoff is a plain self-jump (+270; the “+249” is that jump sampled 2 frames into gravity across the drop). §0A/§0C and the SUPERSEDED banner's "no jump bit" forensics are data artifacts of the misalignment; the player's account is data-confirmed. **[O0] fully closed.** The §0D table (state-stream-derived) survives: the aligned re-derivation reproduces every lip speed and heading, winner −11.7° uniquely negative. One nuance: one of the 11 attempts (att 6 in the aligned numbering) launched no jump at all — a walk-off-the-edge botch.
**Source read** (owner's tree):
- Engine physics: `engine/ezquake-source/src/pmove.c`, `pmove.h`, `pmovetst.c`; input filter `cl_input.c`; movevars wiring `cl_parse.c`, `sv_phys.c`, `sv_user.c`.
- Bot→engine seam: `engine/ktx/src/bot_movement.c`, `g_syscalls.c`, `triggers.c`, `bot_client.c`.
- Map: `C:\nQuake\qw\maps\trick.bsp` entity lump.

Runtime values tagged **[live]** (verified vs the running server), **[default]** (code default), **[verify]** (not yet confirmed live). *This doc was self-reviewed and then adversarially reviewed by a second agent; §0 and §5 reflect corrections to two wrong first-pass conclusions — see the changelog at the end.*

> **⚠ SUPERSEDED (2026-06-08, player ground truth).** There is **no external launcher, no map feature, no "spot."** The takeoff is **the player's own movement** — a jump + air-strafe, i.e. the canonical *"fastest way to move in one direction in Quake,"* already documented in **§4**. My "external +vz impulse / ramp-refuted / **[O0]** mystery" conclusion (§0C, and everywhere it recurs below) is **WRONG and retired**, for two reasons: (1) **a jump adds +vz, which by itself raises `|v|²` exactly as observed** — the +33% is what a jump *does*, not evidence of injected energy; I wrongly treated "ramp ruled out" as "therefore external." (2) The takeoff frame (1880) sits on a **dropped `svc_playerinfo` state**, so the single-frame "no jump bit / +249 vz" reconstruction is unreliable; **+249 ≈ a standard +270 jump sampled ~2 frames into gravity** (`270 − 800·(1/77)·2 ≈ 249`). **For the bot: model a self-generated jump + air-strafe (§4), not a phantom impulse. [O0] is CLOSED — there was nothing to find.** The §0D *aim-vs-speed* finding still stands (it's about which heading the self-launched arc needs); only the *source-of-vz* conclusion is retired.

---

## 0. The headline (after two rounds of correction)

I made two wrong calls before getting here, both now fixed: (1) the takeoff is **not** a `+jump`; (2) success is **not** decided by run-up speed. What the evidence actually supports:

**A. It is NOT a player `+jump`.**
- The raw, complete `dem_cmd` stream (2145 cmds) has **11 jump rising edges** (frames 167, 353, 530, 701, 885, 1062, 1197, 1390, 1564, 1742, 1918). At the winning launch (frame ~1880) the jump bit is 0; the next press is **frame 1918, mid-air** (`oz=−458`), inert per `PM_CheckJump`'s `if (!onground) return` (`pmove.c:709`). (Jump *is* held on the ground during some **failed** attempts — e.g. frames 1791-1811 — but those launched no one either; so "no jump caused any launch" holds, while the earlier wording "no jump in the entire run-up" was too strong.)

**B. It is NOT a map jump-pad.**
- `trick.bsp` entity lump: **light ×225, trigger_teleport ×13, info_teleport_destination ×7, light_globe ×7, trigger_multiple ×7, info_player_deathmatch ×4, worldspawn, info_player_start.** **No `trigger_push`, no `func_*`, nothing velocity-imparting.** The 7 `trigger_multiple` are message triggers (incl. *"Final Trick: Distance — … try to get to the other side anyway."* — exactly this maneuver). The 13 `trigger_teleport` are the miss→reset mechanism.

**C. The vertical impulse is real, fixed, and external — and the ramp hypothesis is REFUTED.**
- Across all 10 launches the takeoff vz is a **fixed ≈+249** (one 238). Using the reliable **origin** trajectory (position is sent every frame), horizontal speed is **preserved** across the launch (ground 469 → glide 480) while vz is added on top → total `|v|²` rises **+33%** (≈469 → ≈541). A ramp/slope redirect would *conserve* `|v|` and *bleed* horizontal into vertical; the opposite is observed → **energy is injected by an external upward impulse, not a ramp.** Source: not a jump (A), not a pad (B), not a ramp (C) — **genuinely unidentified from inputs+source+BSP.** **[O0] must be settled by watching the demo in ezQuake at t≈24.4 s.** (The dropped `svc_playerinfo` state at frame 1880 makes the *single-frame* numbers noisy, but the clean surrounding frames make the classification — external +vz impulse — solid.)

**D. The success determinant is AIM (heading), NOT run-up speed.** *(This corrects the original headline.)* Per-attempt, measured at the launch lip (last on-ground frame) and the ensuing arc:

| att | lip h-speed | launch vz | **launch heading** | far-point oz | outcome |
|---|---|---|---|---|---|
| 1 | 474 | 249 | +27° | −539 | fail → teleport |
| 2 | **477** | 249 | +35° | −492 | fail → teleport |
| 3 | 461 | 249 | +25° | −499 | fail |
| 4 | 461 | 249 | 0° | −507 | fail |
| 5 | 465 | 249 | −1° | −539 | fail |
| 6 | 468 | 249 | +10° | −511 | fail |
| 7 | 461 | 238 | +9° | −539 | fail |
| 8 | 455 | 249 | −1° | −539 | fail |
| 9 | 468 | 249 | +15° | −495 | fail |
| **10** | 475 | 249 | **−11°** | **−488** | **WIN** |

Launch speed is **455–477 for everyone** — a **477 attempt failed** and the 475 won, so speed does **not** separate them. vz is fixed (≈249) — the player doesn't control it. The winner's distinguishing feature is its **launch heading: −11°, uniquely negative** (all 9 failures launched at −1° … +35°). The far-point height tells the story: failures drop to `oz` −492…−539 (over the gap edge → into the void → teleported back); the winner stays at `oz` −488 (on solid ground). **"Get to the other side" is a trajectory/aiming problem** — thread the right heading so the (fixed-speed, fixed-vz) ballistic arc lands on the far platform, not in the gap.

**What this means for the bigger goal:** the *general* getting-speed mechanism (ground-strafe acceleration, §4) is still correctly documented and is the right foundation for bunnyhop **speed** broadly — but **this specific "Distance" trick is won by aim, not by getting-speed**, so it is a poor proxy for "getting speed for bunnyhopping." If the objective is raw speed, a continuous-strafe trick (not this gap-cross) is the better teacher; if the objective is *this* jump, the controller must hit a precise launch heading at the lip.

---

## 1. The bot → engine seam (the 4 levers the bot controls)

The bot never calls pmove. Each server frame it hands the engine a `usercmd`; the engine (mvdsv) runs `PM_PlayerMove`. Build site `bot_movement.c:2779`:

```c
trap_SetBotCMD(NUM_FOR_EDICT(self), cmd_msec,
               PASSVEC3(self->fb.desired_angle),   // view angles  -> cmd.angles
               PASSVEC3(direction),                // fwd/side/up  -> cmd.forwardmove/sidemove/upmove
               buttons, impulse);                  // buttons bit2 -> BUTTON_JUMP
```
`g_syscalls.c:424` (header; `syscall(G_SetBotCMD,…)` at 428) → engine. **No smoothing, no rate-limit, same frame**; angles reach pmove verbatim at `pmove.c:905`. **The bot's command is built in KTX and bypasses the client `cl_input.c` path entirely** (relevant to safestrafe, §3a).

| Lever | Set by bot | Becomes | Consumed in pmove |
|---|---|---|---|
| **View angles** | `self->fb.desired_angle[…]`; roll forced 0 (`bot_movement.c:2752`) | `cmd.angles` | `AngleVectors(pmove.angles…)` → `pm_forward,pm_right` (`pmove.c:905-906`). **The wishdir basis.** |
| **forward/side/up** | `direction[0..2]` | `cmd.forwardmove/sidemove/upmove` | `wishvel = pm_forward·fmove + pm_right·smove` (`pmove.c:499-500`) |
| **Jump** | `jumping` → `buttons |= 2` (`bot_movement.c:2777`) | `cmd.buttons & BUTTON_JUMP` | `PM_CheckJump` (header ~672; button test `pmove.c:687`) |
| **Frame time** | `cmd_msec` | `cmd.msec` | `pm_frametime = cmd.msec*0.001` (`pmove.c:896`) |

**Seam quirks (`bot_movement.c:2703-2779`):**
- `direction` = `fb.dir_move_` projected onto the view basis, scaled 800, horizontal-only out of water (`direction[2]=0` when `waterlevel<=1`, `2729-2736`) → **bot can't send upmove on land** (only `+jump` adds vertical, when onground).
- Engine re-clamps `wishspeed` to `maxspeed` (`pmove.c:507-510`); 800 just means full deflection.
- Jump fires meaningfully only onground (`2716-2723`, mirrors the engine gate).
- `cmd_msec = (int)((last_frame_time - last_cmd_sent)*1000)` (`2643-2644`), fallback **12** (`2669`); ≈12–13 ms at 77 fps → `pm_frametime≈0.013`, the human's cadence.
- **Prewar freeze** (`2767-2772`): lab must `--prewar` past it.
- `BotApplyMoveProbe(self,&jumping,direction)` (`2774`): `mode=cvar("k_fb_moveprobe_mode")`, `slot=NUM_FOR_EDICT(self)-1` (`1343-1344`) — the override hook a launch controller uses.
- **Default (non-moveprobe) bot launch gate:** `ApplyPhysics` early-returns `if (onGround && hor_speed² < (0.8·sv_maxspeed)²)` (`bot_movement.c:298`) — the stock bot won't carve below ~256 qu/s. A moveprobe mode bypasses this.

---

## 2. The per-frame physics pipeline (`PM_PlayerMove`, `pmove.c:886`)

| # | Step | Line | Note |
|---|---|---|---|
| 1 | `pm_frametime = cmd.msec*0.001` | 896 | step Δt (12–13 ms; **not** uniformly 13 — 28 frames are 12) |
| 2 | `AngleVectors(cmd.angles)` → `pm_forward,pm_right` | 905-906 | wishdir basis |
| 3 | `PM_NudgePosition` | 914 | unstick |
| 4 | `PM_CategorizePosition` | 917 | onground / waterlevel / snap-to-ground |
| 5 | `PM_CheckWaterJump` (waterlevel==2) | 920 | map *has* water (Tricks #4/#5); n/a on the −488 run-up platform |
| 6-7 | waterjumptime decay; `jump_msec` (anti-pogo, ≤50 ms) | 922-935 | |
| 8 | **`PM_CheckJump`** | 937 | +270, only if onground |
| 9 | **`PM_Friction`** | 939 | before accel |
| 10 | **`PM_AirMove`** | 946 | accel + gravity + move |
| 11 | `PM_CategorizePosition` (final) | 949 | |
| 12 | landing clip if `onground && vz<-300` | 951-959 | |

---

## 3. Every movement parameter

### 3a. `movevars_t` (`pmove.h:75-93`)

| Field | Server source | cvar | Runtime | Role |
|---|---|---|---|---|
| `gravity` | `sv_phys.c:1123` | `sv_gravity` | **800** [live] | `vz -= entgravity·gravity·Δt` (`pmove.c:517,537`) → −10.4/frame; the ballistic arc. |
| `maxspeed` | `sv_phys.c:1125`; **per-client `sv_user.c:3671`** | `sv_maxspeed` | **320** [live] | caps `wishspeed` (`pmove.c:507`). **The clamp uses the *client's* maxspeed, not necessarily 320** — confirm per-client value. Not the speed ceiling (§4). |
| `accelerate` | `sv_phys.c:1127` | `sv_accelerate` | **10** [live] | accel gain (`pmove.c:367,413`). |
| `airaccelerate` | `sv_phys.c:1128` | `sv_airaccelerate` | **10** [verify] | air accel gain; with the 30-cap it's the air lever. (sim-match used 10; confirm in serverinfo. client fallback 0.7 `cl_parse.c:1616`.) |
| `friction` | `sv_phys.c:1130` | `sv_friction` | **4** [live] | ground friction (`pmove.c:327`). |
| `stopspeed` | `sv_phys.c:1124` | `sv_stopspeed` | **100** [live] | friction floor (`pmove.c:339`). |
| `entgravity` | `sv_phys.c:1132`=1.0 / `sv_user.c:3670` | client | **1.0** [default] | gravity multiplier. |
| `bunnyspeedcap` | `sv_user.c:3672` | `pm_bunnyspeedcap` | **0=off** [live] | post-air-accel clamp (`pmove.c:418-429`). |
| `ktjump` | `sv_user.c:3673` | `pm_ktjump` | **1** [live/dflt] | a **270 floor** after `+=270` (`pmove.c:731-737`). Not exercised (no jump). |
| `slidefix` | (sv) | `pm_slidefix` | **[verify]** | down-ramp gravity (`pmove.c:513-518`). |
| `airstep` | (sv) | `pm_airstep` | **off** [live] | air auto-step + 16% h-loss (`pmove.c:286-293,539-542`). |
| `pground` | (sv) | `pm_pground` | **off** [live] | NQ onground handling (`pmove.c:544-548,627`). |
| `rampjump` | (sv) | `pm_rampjump` | **[verify]** | ramp maxspeed boost + jump-frame vz clip (`pmove.c:602-622,718`). **Relevant to [O0].** |
| `safestrafe` | `sv_safestrafe`→`cl_parse.c:2397` | `sv_safestrafe`/`cl_safestrafe` | **[verify]** | **CLIENT-side input filter** `CL_ApplySafestrafe` (`cl_input.c:991-1045`): on a strafe-direction reversal it forces `sidemove=0` for `required_frames`. **The human's recorded `fwd/side` flips already passed through this filter.** It is *not* referenced in `pmove.c`. Whether it constrains the **bot** (whose cmd is injected server-side via `trap_SetBotCMD`, bypassing `cl_input.c`) depends on whether **mvdsv re-enforces it server-side — [O2], a first-order question for any flip-based controller.** |

### 3b. Hardcoded constants

| Constant | Value | Line | Role |
|---|---|---|---|
| **air-accel cap** | `min(wishspd,30)` | `pmove.c:395` | the bunnyhop lever; air weak, ground strong (§4). |
| **jump impulse** | `velocity[2] += 270` | `pmove.c:729` | what a `+jump` does. **Not the source here** — the measured launch impulse is **≈249, not 270**, and no jump fired. |
| player hull | `{-16,-16,-24}…{16,16,32}` | `pmove.c:38-39` | trace box. |
| `STEPSIZE` 18 / `MIN_STEP_NORMAL` 0.7 | | `41` / `pmove.h:107` | step height; floor-vs-wall (~45°). |
| `MAXGROUNDSPEED` 180/240 | | `554-555` | `vz>180`⇒leave ground (`624`); ramp boost. |
| `STOP_EPSILON` 0.1 / clip planes 5 / bumps 4 / jumpfix −0.1 / water ×0.7 | | `70/87/95/50/454` | slide/clip/water. |

---

## 4. The two acceleration laws — getting-speed is a GROUND mechanism

### Ground `PM_Accelerate` (`pmove.c:354-372`), via onground branch (`pmove.c:515/521`)
```
addspeed   = wishspeed − velocity·wishdir        # wishspeed = min(|wishvel|,320); v·wishdir = |v|cosθ
accelspeed = min(accelerate·Δt·wishspeed, addspeed)  # ≤ 10·0.013·320 = 41.6 /frame
velocity  += accelspeed · wishdir
```
**No 30-cap on the ground.** Strafe so `|v|cosθ` stays below 320 and `addspeed>0` keeps feeding — ground speed climbs **well past 320**. The only QW law that exceeds maxspeed (air has the cap). The gold trace confirms the **outcome** (frames 1837–1879, all on `oz=−488 vz=0`, speed 353→475 on flat ground), but the **mechanism is not a fixed angle**: measured θ is **large and swept (≈70–180°)**, the **view yaw moves only ~17°** over the productive build while the **velocity heading sweeps ~100°** under it — the player rotates wishdir mainly by **flipping `fwd/side`**, not turning the aim. The `max≈320/cosθ` equilibrium is for a *fixed* wishdir and does **not** describe this swept transient; the real schedule must be reproduced in the faithful sim.

### Friction `PM_Friction` (`pmove.c:299-352`), before accel
`control=max(|v|,100); drop=control·4·Δt` (≈24.7/frame at 475); dropoff over a lip doubles friction (`335-337`).

### Air `PM_AirAccelerate` (`pmove.c:382-430`), via air branch (`pmove.c:534`)
`wishspd=min(wishspeed,30)` (the cap), so air only adds while `|v|·cosθ<30` — a few qu/s near θ=90°. **Air maintains, doesn't build** (glide 475→496). Identity `|v|'=√(|v|²sin²θ+wishspd²)`.

**Net:** building ~475 is a ground problem (no cap); holding it across the gap is an air problem (30-cap). The external +vz impulse (§0C) sits between them.

---

## 5. The gold-standard arc (attempt #11), frame-by-frame

| phase | frames | what happens | speed |
|---|---|---|---|
| **Ground-strafe build** | 1837–1879 | on ground (`oz=−488`); `fwd/side` flips; view yaw moves ~17°, velocity heading sweeps ~100° to **−11°**; PM_Accelerate (no cap) climbs vs friction | 353→**475** |
| **Launch (mechanism TBD)** | 1879→1880 | external **+vz≈249** (origin rises ~44 qu, apex ≈frame 1904); horizontal preserved (§0C); **no jump, no pad, ramp refuted**. velocity recon noisy here (dropped state). **[O0]** | ~475 (h) |
| **Air glide** | 1880–1929 | airborne; PM_AirAccelerate (30-cap) nudges 475→**496**; ballistic vz | 475→496 |
| **Land far side** | 1929–1930 | `oz` back to −488, **on solid ground** (failures here fall to `oz` −492…−539, into the gap → `trigger_teleport` back to start) | 496→469, rest at dist ~522 |

**Success determinant (corrected, §0D):** *not* lip speed (455–477 across all, non-separating; a 477 failed). The winner's distinguishing variable is its **launch heading (−11°, uniquely negative)**; vz is fixed (≈249). The 10 failures each launched at +0…+35°, drifted over the gap edge, fell, and were teleported back. The "492/496" figure is the **mid-air glide peak**, not a launch speed — conflating the two was the original error.

**Launch geometry (world coords, Quake units `x y z`):** the run is **east-southeast (~−25°) along a platform at z = −488**; at its **east lip `(-3349, 3775, -488)`** the player goes airborne with **+249 vz** (no jump, no pad — §0):

| point | world coords | note |
|---|---|---|
| run-up begin | `(-3457, 3625, -488)` | building speed, heading ~east |
| **launch lip** | `(-3349, 3775, -488)` | last grounded; next frame airborne with **vz +249** |
| apex | `(-3208, 3767, -444)` | ~44 qu up |
| **land (far side)** | `(-3044, 3760, -488)` | ~305 qu east, back on solid floor |
| gap (where failures fall) | `x≈-3048, z=-539` | ~51 qu *below* the rim → fall in → `trigger_teleport` back |

The entire [O0] mystery lives at that one lip, **`(-3349, 3775, -488)`** — what map feature there supplies the upward kick.

---

## 6. Data quality & client-vs-server (what's verified)

- pmove **algorithm** = ezQuake `pmove.c`; the bot runs **mvdsv** (same shared QW code: same 30-cap, same +270). **[O4]** diff if a sim↔live discrepancy appears.
- **Constants** [live] (maxspeed 320, accel 10, friction 4, gravity 800, stopspeed 100, 30-cap, 1/77, bunnyspeedcap/airstep/pground off) verified vs `mvdsv-lab`. `airaccelerate, slidefix, rampjump, safestrafe, per-client maxspeed` → **[verify]** from serverinfo next live run.
- **Demo data:** reliable on the **ground run-up** (origin-derived ≈ reported velocity) → the lip speeds and headings in §0D are solid. **Unreliable at the single launch frame** (dropped `svc_playerinfo` state, doubled position-step at 1880) → the per-axis launch velocity is reconstructed, but the **origin** (every frame) is reliable and is what proves the +44 qu height gain and the ramp refutation.

---

## 7. What the bot must reproduce (and open items)

**For *this* (Distance/aim) jump, a moveprobe controller must:**
1. **Reach the launch lip carrying ~470+ qu/s horizontal** — necessary but **not** the discriminator. Built by ground-strafe (`PM_Accelerate`, no 30-cap): full `fwd+side` deflection, strafe so wishdir stays offset from the rotating velocity (large swept θ + `fwd/side` flips, *not* a fixed angle). **First confirm `sv_safestrafe` doesn't throttle the bot's flips server-side ([O2]); the bot bypasses the client filter, so it may be unconstrained — or mvdsv may enforce it.**
2. **Hit the precise launch heading (~−11° in this demo) at the lip** — this is the actual determinant. Aim the velocity vector to thread the gap onto the far platform.
3. **The takeoff is a self-generated jump + air-strafe** (§4), *not* a map feature — player ground truth (2026-06-08). The bot launches itself by jumping and air-strafing; there is **no external vz to model** (the earlier "no jump / external impulse" read was a dropped-state artifact — see the SUPERSEDED banner at the top). **[O0] closed.**
4. **Air-glide to hold speed/heading** (`PM_AirAccelerate`, marginal) and land on the far platform.

**Open items:**
- **[O0 — top]** Identify the source of the fixed ≈+249 vertical impulse. **The lip is world `(-3349, 3775, -488)`** — the east edge of the −488 run-up platform; whatever gives the upward kick (a ski-jump curb? a bounce face? a non-entity geometry feature) is *there*. Origin proves it's an external energy-adding impulse (ramp/jump/pad all ruled out by static analysis). Resolve by watching `getspeed.qwd` at t≈24.4 s — or just ask the user (they recorded it).
- **[O1 — done]** `trick.bsp` has no push/jump-pad entity (only teleports + message triggers).
- **[O2]** Live values of `sv_safestrafe` (and whether mvdsv enforces it server-side on bot cmds), `airaccelerate`, `slidefix`, `rampjump`, per-client `maxspeed`.
- **[O3 — coords resolved]** Launch lip `(-3349,3775,-488)`, far platform `(-3044,3760,-488)`, gap floor `z=-539`, run-up from `(-3457,3625,-488)` heading ~−25° (E-SE). Still open: *why a −11° launch heading clears* (the far ledge's exact x/y extent) and the bot's approach corridor.
- **[O4]** Diff mvdsv `pmove.c` vs ezQuake's if any sim↔live discrepancy reappears.

---

### Changelog (corrections found by self-review + adversarial subagent review)
1. **Launch is not a `+jump`** (raw command stream + onground gate). [self-review]
2. **Not a booster pad** (BSP has zero push entities). [self-review]
3. **Ramp refuted** (origin-derived horizontal preserved + `|v|²` +33% = external impulse, not a redirect). [subagent]
4. **Success determinant is heading, not speed** — lip speeds 455–477 don't separate (a 477 failed); vz fixed ≈249; the winner is unique only in heading (−11°). The original "≥490 run-up speed" headline conflated the mid-air glide peak (492/496) with the launch-lip speed (~475). [subagent — the load-bearing fix]
5. **`safestrafe` is a client-side filter (`cl_input.c:991`)**, not "server-side"; the human's inputs already reflect it; bot impact depends on server enforcement. [subagent]
6. Numerics: `msec` is 12–13 (not 13); jump is held onground in *failed* attempts; failures fall to `oz≈−539`; entity list completed; measured impulse ≈249 (not 270). [subagent]
7. **A5 (2026-06-10): map is `ztricks.bsp` (not `trick.bsp`) and the .cmds state↔cmd pairing was shifted by the demo's 41 dropped states** — the launch IS a self-jump with the button at the lip on every attempt; per-attempt start = teleport deposit `(-3516.125, 3712, -453.125)` yaw 0. Full apparatus + time-aligned rebuild + ztricks replay validation (PASS): `experiments/a5_distance_standstill/`. [A5 worker; see the banner at the top]

*Apparatus (preserved in `evidence/getspeed/`): `getspeed.cmds` (rebuildable via `scripts/build_replay_command_file.py --demo C:\nQuake\qw\matchinfo\demos\getspeed.qwd`), `analyze_launch.py` (launch table + per-hop), `attempts.py` (per-attempt segmentation), `launch_geometry.py` (the world-coord table above). Cross-checks — origin-vs-reported velocity, raw `dem_cmd` button dump, `trick.bsp` entity-lump extraction — reproduced inline; the subagent's review scripts were one-off.*
