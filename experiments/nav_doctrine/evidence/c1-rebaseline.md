# C1 (#65) — v8 free-roam re-baseline at n=12: floor 173, canary settled (no regression)

**Date:** 2026-06-10 (12:10–12:27 UTC) · **Lab:** servexeri komodobots-lab :28599 · **Issue:** #65

## What was measured

The **deployed** config — mode-23 **v8** (vanilla-delegation stairs doctrine + 3 s livelock
guard) **+ carrot config-5** (edge-triggered handover + delegation-exact climb guard) — exactly
as it runs live: servexeri `~/nquakesv/ktx/qwprogs-mode21.so` (the `qwprogs.so` symlink target),
**md5 `654149794d3106ea4c4604cb172917e3`**, mtime 2026-06-10 01:38 (the P3 c5 deploy).
**No rebuild, no redeploy** — the module was the measurement target.

Protocol (pre-registered in `artifacts/loop-state.md` BEFORE run 1):

```
python scripts/run_dm3.py --moveprobe-mode 23 --duration 50 --bot-count 1 \
    --lab-mvdsv mvdsv-lab --ktx-extra-cvars "k_fb_moveprobe_fixed_goal -1"
```

Free-roam: no `k_fb_moveprobe_fixed_goal` pin (explicit `-1` clear), no
`k_fb_moveprobe_spawn_origin` — verified absent in every run's generated `lab.cfg`.
Budget: **n=12 × 50 s** (so n≥10 survives up to 2 infrastructure failures) **+ 1 discarded
cold-start attempt 0** (standing rule) = 13 runs, serial.

## Metric (convention validated before run 1)

One number per run: **free-roam tws** = `route_metrics.time_weighted_speed(rows, tele_entrances)`
(imported, never reimplemented) with `tele_entrances` = the run's own observed teleport
entrances, once per use — in free-roam every dm3 teleporter is legitimate navigation (there is
no route to stray from), and each teleport throw's displacement is excluded by the metric's own
convention. Equivalently: whole-trace xy distance (teleport steps excluded) / duration.
Tool: `scripts/freeroam_tws.py` (committed with this evidence; route gates must NOT use its
trace-derived sanctioning — see its docstring).

The convention reproduces both pre-existing ledger blocks **exactly** from their stored traces:

| Block | Recomputed | Ledger says |
|---|---|---|
| v4 free-roam (n=6) | mean 209.3, sd 33.5, range 172.8–254.7 | "209±34, range 173-255" |
| v8-bare free-roam (n=5) | mean 194.2, sd 34.9 | "194±35" |

## Per-run results (block of 12; 0 infrastructure failures)

| # | run_id | tws (qu/s) | teleports | %onground | max vh | note |
|---|--------|-----------:|----------:|----------:|-------:|------|
| 0 | 20260610T121023Z | (177.7) | 0 | 11.2 | 371.5 | DISCARDED cold-start |
| 1 | 20260610T121217Z | 174.5 | 0 | 66.6 | 439.1 | |
| 2 | 20260610T121339Z | 261.3 | 1 | 12.3 | 506.4 | |
| 3 | 20260610T121614Z | 163.0 | 0 | 5.3 | 473.9 | |
| 4 | 20260610T121721Z | 219.3 | 2 | 12.9 | 541.6 | |
| 5 | 20260610T121826Z | 199.9 | 0 | 7.5 | 541.7 | |
| 6 | 20260610T121944Z | 212.0 | 1 | 24.2 | 530.1 | |
| 7 | 20260610T122050Z | 243.5 | 1 | 13.8 | 533.5 | |
| 8 | 20260610T122156Z | 234.9 | 1 | 6.9 | 521.1 | |
| 9 | 20260610T122314Z | 216.6 | 1 | 8.0 | 435.0 | |
| 10 | 20260610T122420Z | 168.9 | 0 | 3.5 | 480.8 | |
| 11 | 20260610T122526Z | 171.8 | 1 | 3.8 | 429.0 | |
| 12 | 20260610T122645Z | 196.4 | 0 | 23.9 | 546.3 | |

Every run: ~53.1 s trace, demo recorded, `build_trace` clean. (`verify_route` exit 2 — "no
SNG route attempt" — is the expected free-roam outcome, pre-registered as NOT a failure.)

## Findings

### New free-roam speed floor

> **mean 205.2 ± 31.8 (n=12), range 163.0–261.3 → floor = mean − 1 SD = 173 (173.4)**

This replaces the stale v4-derived floor of **176** everywhere a floor is cited (ledger
annotated). It is the no-regression reference for wall-hug (#80) and later gates.
Sanity: 3/12 block runs sit below their own floor (expected ≈ 16% of a roughly normal spread).

### Canary verdict: v8 (deployed) vs v4 — settled, NO regression

Plain words: **the deployed config free-roams at the same speed as v4.** The measured
difference is −4.1 qu/s (205.2 vs 209.3), Welch t = −0.25, df = 9.6, **p = 0.81**;
the **95% CI for the difference is [−41.1, +32.8] qu/s** — any true speed cost larger than
~41 qu/s (~20%) is ruled out at 95% confidence, and the data are fully consistent with zero
cost. The P1-close "v8 194±35 vs v4 209±34, 2/5 under 176" inconclusive reading at n=5 was
sampling noise: those 5 runs (163.3–244.7) sit inside today's n=12 spread (163.0–261.3).
Delegation + livelock-guard (+ carrot c5, which is part of the deployed stack and cannot be
separated out in this block) did **not** cost free-roam speed.

### Qualitative believability (one run trace-walked)

Run 20260610T122314Z (tws 216.6 ≈ block mean): 15 distinct 256-qu cells across three floor
levels (z −366..103), median vh 211, 14% of ticks above run-speed 320, max 435, one teleporter
taken, max non-teleport step 16.4 qu (continuous motion), longest stationary span 0.03 s.
A bunnyhopping roamer that keeps moving and never sticks — believable free-roam.
The agent cannot watch live; the user can (viewer `http://192.168.86.33:8095/botlab/` during
runs; every demo is mirrored to `C:\nQuake\qw\tricks\dm3\<runid>.mvd`, track 2 = bot POV).

### Instrument quirk (note for A3 #75)

Under the c5 module, delegated/grounded frames **double-log** the command stream: run 1
(66.6% grounded) logged ~110 rec/s vs the 77 rec/s norm; the c5-era directed runs show the
same scaling (79–82 rec/s at 16–24% grounded). Harmless for tws — duplicates are
same-t/same-xy (verified: 1537/1558 duplicate pairs identical; the 21 movers are 63 qu of
real, telescoped movement) — but any row-count-based rate would be biased. Time-base metrics
only.

## Archival

**13/13 session MVDs** (12 block + 1 discarded attempt 0) copied server-side to
`servexeri:/mnt/usb-ssd/non-games/lab/Komodobots/dm3/<runid>.mvd` and **sha256-verified**
against the lab-run originals. Lab left clean: no lab mvdsv process running; production
28501–28503 untouched throughout.

## Reproduce

```
python scripts/freeroam_tws.py 20260610T121217Z 20260610T121339Z 20260610T121614Z \
  20260610T121721Z 20260610T121826Z 20260610T121944Z 20260610T122050Z 20260610T122156Z \
  20260610T122314Z 20260610T122420Z 20260610T122526Z 20260610T122645Z
```

(traces under `artifacts/lab-runs/<runid>/`, gitignored; demos on the lab SSD as above).
Stats: Welch two-sample t on the per-run values vs the v4 six
(224.2, 254.7, 172.8, 173.5, 197.3, 233.4); t-CDF implementation cross-checked against
textbook critical values t(9)=2.262, t(10)=2.228, t(20)=2.086 at α/2=0.025.
