---
name: demo-eyecheck
description: Use when you need to VISUALLY confirm a specific event in a QuakeWorld demo — a flagged rocket/explosive jump, a teleport, a contact, a suspect route segment, "did this really happen at match-time T?" — by rendering that player's first-person POV (1 screenshot per second, full HUD) on the real GPU and reading the frames yourself. The closest-to-truth check for any detector decision (e.g. route_observatory's suspect_trick verifier). aws-dev orchestrates the GPU box (winnacle) which owns demoshots; you pull the frames and read them. Pairs with route-signature / eval-integrity (same validate-by-eye-then-read-the-render philosophy).
---

# demo-eyecheck — confirm a demo event by eye (POV render → read it yourself)

A detector decision (self-damage + vertical launch = rocket jump; a velocity discontinuity =
teleport; a damage spike = contact) is always a *derived* signal. This skill lets you check it
against the **actual game view**: render the player's POV one frame per demo-second with a full HUD,
pull the frames, and **read them yourself**. Born from validating the route-canon rocket-jump
trick-verifier — where the velocity stream said "launch" and the POV frames confirmed the player was
airborne with the armor dropping by the self-damage amount.

## Where this sits

```
analytics event (match-time T, player P, demo D)         a CLAIM
        ↓  demo-eyecheck (this skill)
P's POV at T ± a few seconds, full HUD, read by you       GROUND TRUTH
```

It does **not** replace the data — it adjudicates it. Use it to confirm a `suspect_trick` flag
before deciding whether an owner-marked half-route must be re-cut, or any time "the numbers say X,
but is X real?".

## Architecture (why it's cross-machine)

The render needs a real GPU + a Windows ezQuake — that lives on **winnacle** (the pinnacle box,
Windows side), which already has the **`demoshots`** skill (the raw 1-fps capture engine,
`C:\Users\benya\.claude\skills\demoshots`). **aws-dev** drives it over ssh and reads the frames.

- `winnacle` — ssh host, **PowerShell** shell. nQuake at `C:\nQuake`, demoshots + Python 3.12 (Pillow).
- `linnacle` — ssh host, WSL2 on the same box; sees the Windows FS at `/mnt/c` (use it for `scp`).
- aws-dev has **no** image library → build the contact sheet on the GPU box's Python, pull the JPG.

## The clock — the one thing that bites (calibrate per demo)

demoshots names frames `t<sec>.jpg` by **demo-file second**. Analytics events (pos.t, damage.time)
are **match second** — and the demo leads match-time by the **warmup/prewar**:

```
demo_sec = match_sec + OFFSET          # OFFSET = warmup length, per-demo
```

Calibrate OFFSET **once per demo** from a known anchor: pick a known self-damage event (match-time
known), capture a strip, and find the frame where the HUD **health/armor drops by that damage** —
its `t<sec>` minus the match-second is OFFSET. (Or read the prewar→"GO" transition near t0.) For
`book_vs_mix[dm3].mvd` the measured OFFSET is **≈ +11 s**. Guess wrong and you eyecheck the wrong
moment — always anchor first.

## Read protocol — what the event looks like

Read a **±2–3 s strip** (1 fps catches the launch within ±1 frame, not the apex), and confirm by the
*conjunction* of cues, not one frame:

| event | HUD | view / motion |
|---|---|---|
| **rocket / explosive jump** | health/armor **drops ≈ self-damage** | grounded → **airborne, view pitched up** → vertical relocation |
| **combat splash** (NOT a jump) | health/armor drops too | view stays **level / grounded**, enemies nearby |
| **teleport** | — | instant scene cut, unrelated geometry between adjacent seconds |

The discriminator between a rocket *jump* and combat splash is the **launch** (airborne/upward view)
— which is exactly the velocity-conjunction the verifier keys on. Validated on `zero`/book_vs_mix:
match-118 (dmg 50) → armor 131→124→84 + airborne = jump; match-64 (dmg 22) → armor 57→34 + level =
splash. Both drop armor; only the jump launches.

## Usage

**One command** (from aws-dev) — capture, sheet, pull:

```
.claude/skills/demo-eyecheck/scripts/eyecheck.sh <demo> <player> <match_sec> [offset=0] [context=3]
#   <demo>  : a local demo path (auto-staged to the GPU box) OR a name already under C:\nQuake\qw\demos
#   <player>: exact in-demo name or a userid (color-byte names like "\x1c zero" -> pass "zero" or the userid)
# prints:  READ: /tmp/eyecheck/<player>/sheet_<lo>-<hi>.jpg   (then zoom to t<sec>.jpg)
```

Then **Read** the printed sheet, and zoom to the full-res `t<sec>.jpg` frames for the HUD digits.

**Manual** (when you need control), the proven steps the driver wraps:

1. roster (exact names / userids): `python C:\Users\benya\.claude\skills\demoshots\scripts\get_roster.py <demo>`
2. capture: `pwsh …\demoshots\scripts\capture-pov.ps1 -Demo <winpath> -Player <name> -MaxSec <demo_sec+pad> -OutRoot <out>`
3. sheet (GPU-box Python): `python contact_sheet.py <out>\<player> <lo> <hi>` → `sheet_<lo>-<hi>.jpg`
4. `scp` the sheet + in-range `t<sec>.jpg` via the `linnacle:/mnt/c/...` mount → Read.

## Gotchas (hard-won)

- **winnacle shell is PowerShell** — chain with `;`, not `&`; quote Windows paths.
- **`capture-pov.ps1` SetForegroundWindows ezQuake** — a window flashes up per chunk; it is **not**
  fully headless. Don't run it while a match is live on that box.
- **MaxSec sizes the capture from 0** (no start-second param) → set it just past your event; one full
  POV ≈ 1200 frames ≈ 45 s, so a targeted event is seconds of wall-clock.
- **A HIGH `match_sec` makes a long 0..MaxSec capture that trips demoshots' runaway-loop guard**
  (`chunk 0-N TIMEOUT … lower -Chunk`, ~140+ shots/launch). The driver passes **`-Chunk 80`** so it
  auto-relaunches per chunk and never trips (override `EYECHECK_CHUNK`); proven on a 531-frame capture.
- **`linnacle` (WSL2) scp is flaky** ("Connection closed"). All pulls fall back to **winnacle
  PowerShell base64** (`pull()` helper) — winnacle is the Windows side of the same `/mnt/c`, so it
  always works when linnacle is down; the small `contact_sheet.py` upload has the same fallback.
- **OFFSET is per-demo** — recalibrate for every new demo (don't reuse book_vs_mix's +11).
- Demo names with a leading color byte (`\x1c zero`) may fail `track` by plain name → use the userid
  (capture-pov logs `no such player` when this happens).

## Pairs with

- **route-signature / eval-integrity** — same "validate by eye, then read the render back yourself".
- **route_observatory** (`build_route_canon.py`) — this is how you adjudicate a `suspect_trick` flag.
