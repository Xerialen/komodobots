# Cadence Evidence Broadening s7e-cadence-evidence-dm3

## Scope

- Map: `dm3`
- Source reference aggregate: `experiments/human_comparison/evidence/human-reference-s7c-bot-comparable-cadence-dm3-aggregate.json`
- Reference rows: `6`
- Bot rows: `6`
- Included bot run IDs: `20260606T003718Z, 20260606T031102Z, 20260606T041805Z`
- S7e broadens bot cadence evidence from existing dm3 mode-7 artifacts only. The default included runs are S3g plus S6b/S6d diagnostic reruns that did not intentionally change movement commands. S6e is excluded because it changed water-edge vertical command behavior.

## Excluded Runs

- `20260606T044000Z`: S6e preserved native water-edge vertical command intent, so it is a mode-7 variant rather than an unchanged diagnostic rerun.

## Cadence Axes

| Axis | Basis | Reference range | Bot range | Bot relation |
|---|---|---:|---:|---|
| Cadence/active min | active movement-metrics rows | 40.4-51.0 | 18.5-138.7 | `mixed_bot_relation` |
| Cadence/non-stationary min | active time excluding stationary_time_ratio | 44.2-55.6 | 18.6-146.6 | `mixed_bot_relation` |
| Cadence/non-low-speed min | active time excluding low_speed_time_ratio | 48.7-61.3 | 20.2-289.5 | `mixed_bot_relation` |
| Cadence/air-proxy min | airborne_proxy_time_ratio | 128.0-143.1 | 164.1-274.1 | `all_bots_above_reference_range` |

## Bot Rows

| Run | Bot | Avg | P95 | Cadence | Air cadence | Air ratio | Avg air ms | Avg air z | Landing delta |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `20260606T003718Z` | `/ bro` | 190.1 | 361.0 | 91.7 | 207.6 | 44.2% | 289.3 | 21.9 | 13.5 |
| `20260606T003718Z` | `/ goldenboy` | 248.2 | 375.3 | 43.3 | 174.4 | 24.8% | 344.5 | 38.1 | -0.6 |
| `20260606T031102Z` | `/ bro` | 136.3 | 359.6 | 138.7 | 274.1 | 50.6% | 219.1 | 9.0 | 2.8 |
| `20260606T031102Z` | `/ goldenboy` | 285.5 | 381.3 | 24.6 | 164.1 | 15.0% | 365.8 | 64.0 | 85.0 |
| `20260606T041805Z` | `/ bro` | 183.9 | 365.5 | 117.6 | 240.5 | 48.9% | 249.4 | 12.5 | 2.8 |
| `20260606T041805Z` | `/ goldenboy` | 286.5 | 386.3 | 18.5 | 203.1 | 9.1% | 295.5 | 36.8 | 20.5 |

## Decision

- Verdict: `cadence_stays_diagnostic_after_broadened_mode7_rows`
- Raw cadence relation: `mixed_bot_relation`
- Movement-time relation: `mixed_bot_relation`
- Airborne-proxy relation: `all_bots_above_reference_range`
- Reason: The broadened unchanged mode-7 dm3 bot set keeps every bot row above the exact-player airborne-proxy-normalized cadence range, while raw and movement-time cadence remain mixed. This strengthens S7d's warning that cadence is entangled with air-rhythm/proxy segmentation and should not become a controller target yet.
- Next goal: S7f should inspect raw airborne-proxy segment distributions, or pivot to the larger land-speed gap, before any cadence controller probe.
