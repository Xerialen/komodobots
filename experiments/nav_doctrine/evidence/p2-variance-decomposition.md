# P2 variance decomposition — why directed mode-23 runs diverge

**Protocol:** mode-23 v8 bot, dm3, spawn snapped to (385.5, 614.25, 56) (lifts-below), goal pinned to live marker 191 at (-473, 514, 120) (SNG platform). Arrival = 3D dist ≤ 80 qu, 45 s budget. 10 runs `20260609T225417Z .. 230323Z`.
All times below are **t+ = seconds after first movement** (bot starts moving ~7.3 s into each trace).

Companion files: `raw_report.md` (full tables: marker positions, per-run sequences, divergence, stuck windows, ASCII overlay), `gates_report.md` (gate tables, 225518Z timeline, climb mechanism), `summary.json` (machine-readable), produced by `analyze_variance.py` / `analyze_gates.py`.

## 0. Sanity checks

- Goal pinning held: `route_state.goal_marker = 191`, `goal_ed = 280` on **every** record of **every** run, including all wrong-way phases. Failures are route-following failures, not goal drift.
- `blocked` never set; `bot_state` constant 128 while routing. `path_state` is 0 except 262144 exactly while `linked_marker == 191`.

## 1. The route and the divergence point

The arriving corridor (overlay in `raw_report.md`) is:

> spawn → west along the lifts corridor floor (y≈600–700, z≈56–88, markers 214→208) → **jump up onto the north ledge** at ≈(-90, 700): z 88→130 (marker 210 "lip", confirmed airborne jump in 230021Z trace) → west along the ledge y≈810–830, z≈130–160 (209→211→206) → **hard left (≈90°) south turn** at 206 (-574, 816) → 207 (-528, 615, 145) → goal platform 191 (-473, 514).

There is **not one bifurcation — there are exactly two**, and neither is the first marker choice after spawn (all 10 runs open identically 214→208 and never differ there):

| Gate | Place | What happens | Effect |
|---|---|---|---|
| **Gate 1 — ledge lip (210)** | (-90, 700, z 88→130) | jump up onto north ledge; weaving approach misses the jump line and falls back to the lifts floor cluster (215/217/218/219/213/212) | **time sink**: per-entry fall-back rate 50–80 % (66 lip entries across 10 runs, 41 fell back). Terminal for 1 run (225719Z, first success at t+41.4 — out of time). Cost 225518Z ~40 s. |
| **Gate 2 — the 206/207 corner** | (-530..-575, 615..820, z≈145) | bot arrives along the ledge at vh≈480–505 heading west, must turn ~90° left; overshoot throws it off the ledge (west past 204, or down to the floor at 225) | **outcome decider**: 5 of 6 failures are downstream of exactly this miss |

Failing runs first leave the arriving corridor (>100 qu sustained) at t+3.0–8.1 — but so do arriving runs (lifts-cluster flapping is universal). The *outcome-determining* divergence is Gate 2; first corner-miss times for the failures: 225820Z t+4.2, 230323Z t+3.4, 230222Z t+19.4, 225417Z t+29.2, 230122Z t+30.8 (225719Z never reached the corner).

## 2. Marker sequences

Full deduped `linked_marker` sequences in `raw_report.md` §"Marker sequences". Summary:

- **Shared skeleton of all 4 arrivals:** `214 → 208 → 210 → 209 → 211 → 206 → 207 → 191`, heavily interleaved with flap noise (208↔210, 208↔217 back-links while weaving). Strict longest common prefix of arrivals is only `[214]` because the flapping differs, but all four contain the skeleton in order, and arrival follows first ledge commit by only 1.7–3.5 s.
- **Failing runs split from the skeleton at two points, not at the start:**
  - 225719Z never converts 210→209 (13 lip entries, 9 fall-backs, plus 102↔5 south-floor detours ×4).
  - The other 5 reach 206/207 and split there.

**Next-hop fractions at the split markers** (all pre-arrival first-class transitions, 10 runs pooled — `gates_report.md` §Gate 2):

| from | to | n | share |
|---|---|---|---|
| 206 | 207 (toward goal) | 14 | 78 % |
| 206 | 204 (wrong-way, NW perimeter) | 3 | 17 % |
| 206 | 202 (drop to floor) | 1 | 6 % |
| 207 | **191 (goal)** | **5** | **36 %** |
| 207 | 206 (bounced back) | 7 | 50 % |
| 207 | 225 (fell to floor below) | 2 | 14 % |

So at the split marker 207 only ~1/3 of attempts convert. All 4 arrivals converted on their 1st or 2nd 207-visit; no failure ever converted (225820Z linked 191 once at t+25.1 at z=162, 183 qu out, then fell off the platform before closing within 80).

**On g_random:** the data does not support random *scoring* as the variance source. `goal_marker` stays 191 throughout, and every "wrong" next-hop is physically explained: `linked_marker` follows the bot's body. 206→204 events occur ≤0.4 s after a 207-bounce with the bot still carrying 240–280 vh westward — it is momentum carrying it past the turn, not a path re-roll. The coin being flipped is the **weave phase / speed at the corner**, and at the lip.

## 3. Per-run verdicts

Failure classes: (a) wrong-direction never recovers, (b) marker loop/oscillation, (c) physically stuck (>3 s, <40 qu displacement), (d) goal-area orbiting (near but never ≤80 qu).

| run | result | verdict | evidence (t+, positions) |
|---|---|---|---|
| 225417Z | FAIL (closest 268 qu @10.6) | **(b)→(a)** lifts loop, then wrong-way at corner | flap in lifts cluster t+0–28 (4 lip fall-backs); ledge t+28.5; 207-bounce t+29.2; 206→204 t+29.6; falls off west ledge, drifts to mega/tele (-900,-100, z≈20) t+33–45, 184↔197 ×3; dist grows to 750 |
| 225518Z | ARRIVED t+44.1 | slow Gate-1 (see §4) | 40 s captive in lifts cluster, 4th lip attempt sticks t+42.4, clean corner, goal 1.7 s later |
| 225619Z | ARRIVED t+10.4 | clean | ledge t+8.1, 207→191 first try t+8.8 |
| 225719Z | FAIL (closest 225 qu @27.8) | **(b)** pure Gate-1 captivity | 13 lip entries / 9 fall-backs; 102↔5 south-floor detour ×4; first ledge commit t+41.4 — never reaches the corner before 45 s |
| 225820Z | FAIL (closest 97 qu @27.4) | **(d)** orbits *below* the goal platform | ledge t+2.6 but corner misses (207-bounce ×3, drop to 225 floor t+5.4); re-climb ~t+20; links 191 t+25–28 at z=162 (158–183 qu) then **falls off the platform** t+29 (z 162→18); floor orbit 227↔229↔228 directly beneath goal t+30–45 |
| 225920Z | ARRIVED t+12.5 | clean | ledge t+10.6, 207→191 first try t+11.5 |
| 230021Z | ARRIVED t+5.9 | clean (one bounce) | ledge t+2.4, 207-bounce t+3.5, converts on 2nd visit t+4.7 |
| 230122Z | FAIL (closest 114 qu @23.2) | **(b)→(a)** loop, then wrong-way | 213↔212 loop ×6 + near-stuck t+9.4–24 around (-414,590,10) (floor below goal); ledge t+30.0; 207-bounce t+30.8; 206→204 t+31.1; west floor/mega 112/187/184 for the rest |
| 230222Z | FAIL (closest 136 qu @41.0) | **(d)** orbits below the goal | 102↔5 detour early; ledge t+18.7; corner miss t+19.4 drops to 225 (floor); floor orbit 227↔228↔229↔230 beneath goal t+20–45 |
| 230323Z | FAIL (closest 317 qu @29.5) | **(a)+(c)** wrong-way then wall-pinned | fastest ledge t+2.7; 207-bounce t+3.4; 206→204 t+3.8; flies off west ledge (z 148→-1); **physically stuck 13.8 s** at (-832, 336, -16) against the west wall t+9.5–23.2 (linked 187/touch 112, creeping mm/s); then mega area 184↔197 ×5 hopeless re-climb attempts |

Note the orbit-below mode: the goal sits on a raised platform (z≈120–160); the floor beneath is z≈0–28, so horizontal closeness (97–136 qu) never satisfies the 80 qu 3D criterion, and the only ways back up are the same weave-gated climbs.

## 4. 225518Z — what the 44 s arrival did for 40 s

Gate-1 captivity, nothing else (5 s buckets in `gates_report.md`):

- t+0–25: flapping inside the lifts floor cluster (208/215/217/218/219, x −260..+70, z 19–83), three lip (210) entries all falling back; even drifts back to spawn-side 214/220 at t+20–25.
- t+25–35: 213↔212 oscillation ×3 on the low floor north of the goal around (-423, 690, 22) — passes within 124 qu *horizontally* of the goal while 100 qu below it.
- t+35–40: pushed back east into the lifts cluster (217/208/219).
- t+40–44: 4th lip attempt sticks (210→209 t+42.4), then a textbook ledge run 209→211→206→207→191 and arrival at t+44.1 — 1.7 s after the climb finally succeeded.

I.e. the slow arrival is the *same* run as the fast ones, prefixed by 40 s of Gate-1 coin flips.

## 5. Recommendation

The single change with the most evidence behind it: **suppress the weave and cap speed on precision segments of a pinned-goal route — specifically the ledge-lip jump (208→210→209) and the final two hops (206→207→191) — steering directly at the next marker until past the feature.** The mechanism observed is not path-scoring randomness (goal stayed pinned at 191 in every record; every "wrong" hop is the body physically overshooting): runs enter the 206 corner at vh≈480–505 carrying ±45° weave, and only 36 % of 207-exits convert to 191 — the rest bounce or fall off the ledge, after which the bot lands in marker basins (west perimeter → mega/tele dead-end; floor beneath the goal → 227↔229 orbit) from which every return path runs through another weave-gated climb, so a single miss costs 15–40 s or the whole run. The same weave-vs-feature interaction makes the 210 lip a 50–80 % per-attempt fall-back (sole killer of 225719Z, 40 s of 225518Z). Five of six failures had reached 207 with ≥14 s of budget left; converting the corner deterministically (weave off + speed ≤~350 within 2 hops of the pinned goal, as in the successful 207→191 passes at vh 224–415) plausibly turns 9/10 reach-rate, and applying the same governor at the lip removes the remaining time-sink variance.
