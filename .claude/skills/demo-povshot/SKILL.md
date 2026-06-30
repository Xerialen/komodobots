---
name: demo-povshot
description: >
  Grab ONE real ezQuake first-person POV screenshot (full HUD) of a QuakeWorld demo at an exact
  player + demo-second, rendered headless on servexeri (the always-on Linux hub) and pulled to
  aws-dev for Claude to read. The single-moment / Linux-headless sibling of the demo-eyecheck skill
  (which renders a whole 1-fps POV sweep on the Windows GPU box). Use when you need to SEE exactly
  what a player saw at a moment in a demo — validate a route START/END spot, a spawn position, a
  trick frame, "is this the right place?", "show me <player>'s POV at T". Wraps the owner's proven
  clipsmith render.cfg recipe (f_spawn -> demo_jump -> track -> screenshot). Triggers: "screenshot
  this demo at second N", "grab <player>'s POV", "in-game shot of <demo> at T".
---

# demo-povshot — one real ezQuake POV frame from a demo (headless, on servexeri)

```
scripts/grab.sh <demo-rel-to-qw> <player|-|userid> <demo_sec> <local-out.png>
```
…then `Read` the PNG. One real in-engine POV with the full spectator HUD.

## When to use
- Validate a position from a demo by EYE: route START/END, a spawn, a contact, a trick frame.
- "What did <player> see at match-time T?" — the closest-to-truth, real-client check.
- Prefer **demo-eyecheck** instead when you need a whole 1-fps sweep over an event window (it renders
  on the Windows GPU box); use demo-povshot for a SINGLE moment, fully headless on the always-on hub.

## Architecture
- **Renders on servexeri** (192.168.86.33, always-on Ubuntu hub, Intel HD 530): it holds the nQuake
  client (`~/nquake`, paks+maps), the ezQuake AppImage, the demo archive (`/mnt/usb-ssd`), and Xvfb.
- **Reached from aws-dev via pinnacle**: `aws-dev → ssh winnacle (pinnacle Windows) → ssh
  xerial@192.168.86.33`. Do NOT use `winnacle → wsl → ssh servexeri` — that lands on a *pinnacle-local
  WSL* (a different box with a 4090), not the real servexeri hub.
- `scripts/povshot.sh` is the servexeri-side driver (auto-deployed by grab.sh to `~/nquake/`);
  `scripts/grab.sh` is the aws-dev orchestrator (deploy → run → base64-pull the PNG).

## The recipe (owner's clipsmith `~/nquake/qw/render.cfg`, parameterized)
On the demo's first spawn (`f_spawn`): `demo_jump <sec>` → `track <player>` → 8×`wait` (let frames
render) → `screenshot <name>` → `quit`. Output lands in `~/nquake/qw/matchinfo/screenshots/<name>.png`.

## Engine gotchas (encoded in povshot.sh — do not relearn the hard way)
- **Run the AppImage with `APPIMAGE_EXTRACT_AND_RUN=1`, NOT the bare extracted binary.** servexeri's
  system glibc is OLDER than the AppImage's bundled libs, so mixing them dies with
  `GLIBC_ABI_DT_X86_64_PLT not found`. AppRun's "appimage libc" branch loads the bundled glibc
  loader; the owner's logs literally say "executing with appimage libc" — that is the working path.
- **AppRun SIGSEGVs on a post-run qwurl-desktop fixup** AFTER ezQuake quits and the shot is written,
  so the process exit code is junk → gate success on the **PNG existing**, not on rc.
- **Headless render**: `xvfb-run -a -s "-screen 0 WxHx24"` + `LIBGL_ALWAYS_SOFTWARE=1` (llvmpipe;
  Intel HD 530, no GPU accel needed). Default 1280×720; bump via `POV_W`/`POV_H` env.
- **player** must be a single token: a QW name w/o spaces, or a numeric **userid** (color-byte names
  need the userid — get it from a roster), or `-` for the default POV (no track).

## Input safety (validated at both layers)
The args flow through a 2-hop ssh chain and into the ezQuake config, so both scripts reject injection
before acting: **SEC** must be numeric; **outname**/**POV_W/H** are whitelisted (`[A-Za-z0-9._-]` /
digits); **demo**/**player** reject the shell/cfg metachars `" ' ; $ \` \ ` and newlines. `grab.sh`
additionally marshals the remote command with `printf %q` + base64 (no raw user byte ever reaches the
ssh string — the value stays inert data through the Windows middle hop). Real `[dm3]` demo names are
fine (`[`/`]` are allowed and `%q`-escaped for the shell). A rejected value exits non-zero with a clear
`FATAL:` line and renders nothing.

## Clock offset (match-time vs demo-second) — IMPORTANT
`demo_jump <sec>` uses the **demo clock** (includes warmup/prewar), NOT match-time. The in-game HUD
match-clock is burned into the shot, so calibrate by reading it back: `demo_sec = match_sec + warmup`
(book_vs_mix warmup ≈ +11 s; see memory `headless-visual-self-validation` CH4 + `demo-eyecheck`).

## Demos
On servexeri: the live test demo is `matchinfo/demos/4on4_hx_vs_018_dm3.mvd` (relative to qw/); the
full archive is `/mnt/usb-ssd/demo-archive/demos` + `/mnt/usb-ssd/4on4-corpus` (memory
`servexeri-demo-archive`). To shoot an archive demo, stage/symlink it under `~/nquake/qw/` (or pass a
path playdemo can resolve) first.

## Lineage
Built from the owner's `clipsmith` project + `~/nquake/qw/render.cfg`. Sibling skill: demo-eyecheck.
Box facts: vault `infrastructure/machines/servexeri.md`; reachability uses the pinnacle Windows hop
(vault `ssh-keys` / `network-topology`).
