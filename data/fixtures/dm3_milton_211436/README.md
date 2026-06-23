# Fixture: `dm3_milton_211436` — canonical test fixture

The single, canonical demo fixture for the komodobots data architecture. Referenced by
the catalog loader/validator tests (`integration/tests/`), the ml smoke tests
(`integration/ml/tests/`), the worked example (`WORKED-EXAMPLE.md`), and `INTEGRATION.md`.

## Identity

| | |
|---|---|
| Match | `4on4_book_vs_3b[dm3]20260419-2145.mvd` |
| hub gameId | **211436** |
| sha256 | `9e0d4c22438f44dc94346c6d96cb24a5fcc7498b91e3c44dd12886575ac45bc7` |
| Map | dm3 (The Abandoned Base) |
| Result | **Book 294 – 3b 80** (biggest-blowout → strong team-control signal) |
| Headline | Milton 93 frags, 54-kill RL streak, 8 quad-frags |
| Ruleset | 4on4, KTX 1.47-dev / MVDSV 1.20-dev, KT2 respawns, antilag 2, maxfps **77** |
| Duration | 1200 s (20 min) |
| analyzer schemaVersion | 12 (parser-drift key) |

## Provenance

Acquired via **one authorized hub fetch** (`loadDemo(gameId=211436)`); every other
file here was extracted **offline** from the cached demo via mvd-mcp. No bulk download.
The `mvd-api` binary is `~/mvd-mcp-bundle/mvd-api` (mtime 2026-05-30, Go 1.25.10).

## Files

| file | source tool | contents |
|---|---|---|
| `meta.json` | getOverview + getMetadata | identity, teams, ruleset, top streaks/powerups, the t=130 worked-example hint |
| `scoreboard.json` | getDemoInfo | per-player KTX stats (frags/kills/deaths/dmg/accuracy); reconciles 294–80 |
| `items_observed.json` | getItems | observed respawn intervals + world positions (folded into the catalog, B3) |
| `item_events.sample.json` | getWeaponPickups + getBackpacks | weapon pickups + backpack drops, with the spawner/backpack ent join |
| `frag_events.sample.json` | getFrags | aggregates + the Milton-quad-window kill sample |
| `actor_ticks.sample.json` | getStateAt + getStreamSlice | 8-actor world_state at t=130 + Milton velocity derivation |
| `loc.json` / `loc_graph.json` | getLocTable + getLocGraph | 34 named locs (centroids) + 116 adjacency edges |
| `region_control.sample.json` | getRegionControl | 5 regions, control % + per-bucket timelines |
| `events.sample.json` | getEvents | discrete audio-cue/comms events in the quad window |

## Caveats

- **Samples, not full dumps.** `*.sample.json` files keep a representative slice (the
  Milton-quad window) + aggregates; the full streams are re-derivable offline from the
  cached demo. The static catalogs they feed (`schema/`) are complete.
- **Velocity/angles are derived**, never read from MVD (see `actor_ticks.sample.json`).
- **Parser drift:** anything observed (respawns, state) is tied to the `mvd-api` binary
  above (schemaVersion 12). Re-extract if that binary changes.
