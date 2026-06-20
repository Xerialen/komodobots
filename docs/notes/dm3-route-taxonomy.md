# dm3 Route Taxonomy (komodobots route-segmented BC program)

Status: owner-approved 2026-06-20. dm3 = "The Abandoned Base". This taxonomy drives the phased program (issues #315-327). Two classes: BASE ROUTES (learn the path + go fast — the priority) and TRICKS (shortcuts/enablers of base routes — a separate class, done later).

## Item control hierarchy (qwiki, traffic-corroborated)
Foundation: **Red Armor (RA)** (the economy — "150 RA worth more than 150 YA") and **Rocket Launcher (RL)** (firepower unit; RL+RA on one player). Swing powerups: **Quad** (run, not held) and **Pentagram** (invuln). Secondary: LG, YA, Mega, cells.
Respawns (QuakeWorld values, drive route timing): RA/YA/Mega **20s**, Quad **60s (pickup-based)**, Pent/Ring **300s**.

## Difficulty convention
Binary, per the owner's real-play call (overrides the ballistic-margin proxy): **hard** = the 6 tricks marked below; **easy** = everything else (all base routes + the unmarked tricks). Curriculum is easy-first.

## Categorization 1 — BASE ROUTES (importance x difficulty) — learn these first
| Tier | Route (leg/rotation) | Importance | Difficulty | Note |
|---|---|---|---|---|
| 1 | Ring<->Quad (hill corridor) | HIGH (quad contest) | easy | wall+pit corridor, runnable |
| 1 | Quad<->mega (hill) | HIGH (central) | easy | bhop sprint (peak ~921 qu/s) |
| 1 | mega<->Ring | HIGH (busiest corridor) | easy | short ~324 qu, fast |
| 1 | Spawn->RA + RA->Quad (RA loop) | HIGHEST (economy) | easy | drops cross the central void |
| 1 | Opening: YA/lifts->Pent ; SNG-tele->Ring->RA | HIGH (opening tempo) | easy | spawn-driven rotations |
| 2 | RL->RA / mega->RL (firepower) | HIGH (RL unit) | easy | RL-area drops/climbs |
| 2 | YA<->YA.box (armor pocket) | MED (secondary armor) | easy | flat, ~598 qu, seen in all demos |
| 3 | RA->YA / RA->SNG (cross-map) | MED | easy* | *geometrically harder: 53-62% straight-line void, long detour |
| 3 | RL->LG / LG<->GL (lower weapons/cells) | LOW-MED (LG cells) | easy | water level, flat |

## Categorization 2 — TRICKS (shortcut vs enabler — a separate class) — later
| Trick | Class | Parent base route | Difficulty | Note |
|---|---|---|---|---|
| sng_shortcut2 | SHORTCUT | Ring->SNG (vs sng_jumps) | hard | owner-marked (was "easiest" by ballistic) |
| sng_shortcut | SHORTCUT | Ring->SNG (post-teleport) | hard | owner-marked |
| sng_to_rl | SHORTCUT | SNG-area->RL (cross-map) | easy | |
| ring_to_mega | SHORTCUT | Ring->mega (east) | easy | (tightest ballistic margin +0.3, but owner: easy) |
| mega_to_rl | SHORTCUT | mega->RL | hard | owner-marked; high speed (~626 req) |
| rl_to_ya | SHORTCUT | RL->YA | easy | (highest ballistic req ~678, but owner: easy) |
| hilljump | ENABLER | Quad<->Ring hill pit | easy | crosses the 256-deep pit |
| ra_jumps | ENABLER | reach RA (climb +344) | easy | lift + short hops |
| rl_to_bridge | ENABLER (rockets) | RL->bridge over chasm | hard | impossible without rocket-jump |
| mega_to_window | ENABLER (rockets) | mega->window slot | hard | impossible without double rocket-jump |
| sng_jumps | ENABLER/grind | the full SNG tour the shortcuts bypass | hard | 9 chained hops, hardest overall |

## Phased program (issues)
- Phase 0 data foundation: #315 ETL all-player kinematics->actor_ticks, #316 real airborne signal (replace all-zero onground), #317 landmark region polygons.
- Phase 1: #318 (this doc), #319 leg segmenter, #320 POV command extractor.
- Phase 2: #321 route-conditioned BC (Tier-1), #322 inverse-pmove non-POV command inference, #323 Tier-2.
- Phase 3 shortcuts: #324 easy, #325 hard. Phase 4 enablers: #326 easy, #327 hard (rockets; needs attack-button head).

## Sources
qwiki Dm3 / Items / Armor / Quad Damage / Teamplay Guide pages (item priority, respawns, named routes, trick purposes); experiments/nav_doctrine/evidence/trick-census/census.json (geometry/required-speed); lab/dashboard/public/data/map_entities/dm3.json (landmark coords); dm3.bsp geometry (BSP floor traces); demo traffic from data/catalog/dm3_4on4.sqlite (ego-only/partial — see #315). DATA CAVEAT: importance leans on qwiki + partial traffic until Phase 0 (#315-317) lands.
