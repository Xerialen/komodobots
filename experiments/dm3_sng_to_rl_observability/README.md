# dm3 SNG→RL — observability rebuild and the quantified leap wall

## Finding

The dm3 SNG→RL bot does not fail at navigation. It fails at **one ballistic jump**, and
the reason is **speed**, now measured rather than guessed:

- The route ends with a **launch off a ledge at ~(1477, 53, z≈+5), over a −392 void, across a
  ~340 qu gap** to a landing ledge at ~(1615, 363, −60), then a step down to the RL pit (−88).
- Clearing that gap before falling to the landing requires **≥ 526 qu/s horizontal at the launch
  edge** (`g = 800`, flight ≈ 0.65 s). The human carried **528** — clears by ~2 qu/s. This
  validates the geometry math against ground truth.
- The bot **reaches the ledge and even attempts the leap** (goes airborne over the void) but
  carries only **442–448 qu/s into the launch edge**, and its **peak speed anywhere on the route
  is only ~478–497** — itself below 526. So it falls into the void.

The leap is therefore **speed-limited two ways**: the bot loses ~50 qu/s in the final approach/turn,
*and* its ceiling is ~30 below the requirement even at peak. The next lever is raising edge speed
above 526 (audit where ~50 qu/s is lost; determine whether peak can exceed 526 under KTX's accel
model). If 526 is unreachable under the model, that is a finding to surface, not tune around.

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
- `verify_20260609T162916Z.txt`, `verify_20260609T163516Z.txt` — two logged runs scored by the new
  metric: best attempts classify `REACHED_LEDGE_NO_JUMP` / `ATTEMPTED_JUMP_FELL_SHORT`, route ~87%,
  **edge speed 442–448 vs 526 needed, zero false PASS**.
- `trace_summary_*.json` — per-run stats (max_vh ~479–497, ~30% onground, frames over void).
- `ktx_origin_log.diff` — the FBMOVEPROBE_CMD origin-field addition.

## Status

The 80/80 criterion (≥80% route **and** ≥80% speed, `REACHED_RL`) is **not met** and is unchanged.
This PR delivers the instrument and the grounded diagnosis; tuning toward the now-measured speed
target resumes on top of it.
