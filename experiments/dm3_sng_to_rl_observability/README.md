# dm3 SNG→RL — observability rebuild and the quantified leap wall

## Finding

The dm3 SNG→RL route ends with a **ballistic jump**, and the bot doesn't make it:

- The route ends with a **launch off a ledge at ~(1477, 53, z≈+5), over a −392 void, across a
  ~340 qu gap** to a landing ledge at ~(1615, 363, −60), then a step down to the RL pit (−88).
- Clearing that gap before falling to the landing requires **≥ 526 qu/s horizontal at the launch
  edge** (`g = 800`, flight ≈ 0.65 s). The human carried **528** — clears by ~2 qu/s. This
  validates the geometry math against ground truth.
- Measured on a **stray-teleport-clean** trajectory, the bot does **not even reach the launch edge
  at speed**: its peak anywhere on the route is ~478–497, but on the legit approach it carries only
  **~327 qu/s** and gets no closer than **~581 qu** from RL (≈86 qu short of the launch edge) before
  wandering off. So the gap is **~199 qu/s of edge speed _plus_ unreliable navigation to the edge** —
  not the ~80 a first pass suggested.

> **Correction (caught by the instrument).** An earlier reading reported "~442 qu/s, ~79 short, the
> bot attempts the leap." That was **contaminated by stray-teleport frames**: dm3 has secondary
> teleporters that dump the bot near RL's xy at the wrong height, inflating closest-approach and
> faking a leap. The first cut of `verify_route.py` had dropped the old scorer's stray-teleport
> guard; it is restored here (`legit_segment()` truncates each attempt at the first non-legit
> teleport). The numbers above are post-fix. This is exactly the masking the goal-true metric
> exists to prevent — and the instrument caught its own contamination.

Next lever: get the bot to the launch edge reliably **and** at ≥526 qu/s (peak is ~497, the legit
approach only ~327 — so both navigation reliability and edge speed must improve). If ≥526 at the
edge is unreachable under KTX's accel model, that is a finding to surface, not tune around.

## Why a rebuild was needed

Prior tuning ran against `events.txt` **origin samples only**, with a metric
`route% = max(nearest-human-path-index)` that **could not distinguish "tracked the path toward the
bridge" from "reached RL."** A run that stalled at the ledge scored ~77% and read as near-success.
That masked the fact that the bot never completes — and never could, at its current speed.

## The instrument (apparatus in this PR)

All dependency-free (stdlib only):

| Script | Role |
|---|---|
| `scripts/bsp_geom.py` | dm3 BSP v29 **collision oracle** — `contents` / `floor_z` / `on_ground`, a stdlib port of demopasha `phase0/hull_check_cpu.py`'s `point_contents` (= Quake `SV_RecursiveHullCheck`, player hull 1). Also `derive_jump_geom()` → the leap geometry. Validated: matches the human resting origin z to **0.0 qu** at SNG and at the RL; map-center→EMPTY, outside→SOLID. |
| `scripts/build_trace.py` | Unified **100 Hz** per-tick `trace.csv`: actual origin + velocity + onground (`flags&512`) + emitted keys + view yaw + BSP floor/void/dist-to-RL — one stream, one clock, **no join**. |
| `scripts/verify_route.py` | **Goal-true** metric. Classifies `REACHED_RL` / `ATTEMPTED_JUMP_FELL_SHORT` / `REACHED_LEDGE_NO_JUMP` / `LEFT_ROUTE` / `NEVER_REACHED_LEDGE`. PASS requires `REACHED_RL` **and** route ≥ 80% **and** speed ≥ 80%. Route % is gated to on-route, on-solid positions so a bot that flies into the void gets no late-arc credit. |
| `scripts/run_dm3.py` | One command: forces every-frame command logging, builds the trace, scores it, mirrors `demo.mvd` → `C:\nQuake\qw\tricks\dm3\<run>.mvd`. A dm3 attempt is never run blind again. |

The one **KTX change** (`evidence/ktx_origin_log.diff`): add `origin=` to the `FBMOVEPROBE_CMD`
log line so the command stream is self-contained. KTX-only; ezQuake unmodified. Deployed on
servexeri `qwprogs-mode21.so`. `scripts/run_frobodm2_lab.py` gains the matching `origin=` parse
token (plus mode-22 harness support). Requires `--moveprobe-log-commands --moveprobe-log-interval 0`
(now the `run_dm3.py` default; prior tuning runs had logging off → 63-byte command logs).

## Evidence (`evidence/`)

- `dm3_jump_geom.json` — the validated leap geometry (req 526 vs human 528, `human_clears: true`).
- `verify_20260609T162916Z.txt`, `verify_20260609T163516Z.txt` — two logged runs scored by the
  stray-teleport-clean metric: best legit attempts are `REACHED_LEDGE_NO_JUMP` (route 85%, closest
  581 qu, **edge speed 327 vs 526 needed**) and `LEFT_ROUTE` (took a stray teleporter). **Zero false
  PASS, zero false leap-attempt.**
- `trace_summary_*.json` — per-run stats (max_vh ~479–497, ~30% onground, frames over void).
- `ktx_origin_log.diff` — the FBMOVEPROBE_CMD origin-field addition.

## Status

The 80/80 criterion (≥80% route **and** ≥80% speed, `REACHED_RL`) is **not met** and is unchanged.
This PR delivers the instrument and the grounded diagnosis; tuning toward the now-measured speed
target resumes on top of it.
