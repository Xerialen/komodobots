# DM3 4on4 self-POV data census — Stage-0 Spike 3

**Spike:** `docs/12_DM3_4ON4_STANDIN_PROGRAM.md` §7 spike 3 + §8 risk #1 (the #1-ranked risk:
"Self-POV match-corpus yield for learned MOVE/AIM-of-elites").
**Goal:** measure whether a self-POV elite DM3 4on4 corpus large enough to behaviourally-clone
MOVE+AIM exists, and set an infeasibility floor.
**Date:** 2026-06-14 · **Host:** pinnaclewin11, WSL2 Ubuntu-24.04 · **Machine-readable:** `self-pov-census.json`

---

## TL;DR — RECOMMENDATION: **FEASIBLE**

| Question | Answer |
|---|---|
| Does the elite DM3 4on4 self-POV corpus exist? | **Yes, decisively.** |
| Self-POV 4on4 match demos | **472** |
| Ground-truth usercmd frames (move + view-angle, ~72 Hz) | **37,561,151** (~145 h on one map) |
| Distinct players | **256** |
| Full-match-length demos (≥20k frames ≈ ≥4.5 min) | **443** (median 86,810 frames ≈ 19 min) |
| `.qwz` decompression status | **Resolved** (no gap) — bundled qizmo 2.91 in WSL2 |
| Infeasibility floor (docs/12: "< N self-POV 4on4 → abandon") | **Cleared by ~2 orders of magnitude** |

The feared "no elite DM3 POV corpus" (docs/12 provenance note) is **false**. Learned **MOVE** and
**aim-tracking dynamics** BC are *data-feasible*. The honest residual limits are about *per-player
depth* and *aim target-selection*, not corpus existence — see Caveats.

---

## 1. Full demo inventory on disk (`…/quakeworld/`)

Counted with `find -iname` across the entire quakeworld tree:

| Type | Count | Carries usercmds? | Role |
|---|--:|---|---|
| `.qwd` | 232 | **Yes** (first-person POV) — *if self-POV* | exact MOVE+AIM labels |
| `.qwz` | 1743 | Yes (Qizmo-compressed `.qwd`) | same, after decompression |
| `.mvd` | 691 | **No** (server demo) | all-player positions, no intent → outcome scoring only |
| `.dem` | 0 | — | — |

`.qwz`/`.mvd` span many maps/modes. The **DM3 POV subset** is the staged corpus below; the 99 dm3
`.mvd` (e.g. `komodobots/tricks/dm3/`) are server demos and **cannot** train MOVE/AIM (no usercmd
labels) — they remain the macro/economy (DECIDE) and outcome-scoring source, as docs/12 §5 states.

## 2. The DM3 POV corpus (challenge-tv archive)

Prior work (`data/challenge-tv-archive/`) harvested the challenge-tv.com demostorage archive
(archive.org, 17 GB TAR), classified every dm3 POV demo by filename heuristic, staged them flat into
`stage_dm3/` with a provenance `manifest.tsv`, and decompressed the `.qwz` **on servexeri**. This
spike re-decompressed locally and — crucially — **added the parse-grounded self-POV filter that the
prior filename-only catalog lacked.**

- **548** dm3 POV demos total: **70** raw `.qwd` + **478** `.qwz`.
- `.qwz → .qwd`: **477/478 OK**, 1 corrupt source (`…Lakerman…laker.qwzSC-kth`, damaged
  double-extension). Decompressed total **5,599,710,749 bytes** — **byte-identical to the servexeri
  run**, confirming determinism.
- Filename-heuristic mode split: team/4on4 = 535, duel = 12, ffa = 1.

## 3. Self-POV vs spectator — the classifier (the actual spike-3 work)

A POV `.qwd` carries one player's `dem_cmd` usercmd stream. For a **self-POV** demo that is the
recording player's *real* first-person input; for a **spectator / autotrack / commentary** broadcast
demo it is the *camera operator's idle* input. The catalog that existed was filename-only and never
checked this. `classify_self_pov.py` parses each demo (`tools/qwd_usercmd`) and computes per-demo:

- `move_nonzero_frac` — fraction of usercmds with nonzero forward/side/up move.
- `move_active_frac` — fraction with |forward| or |side| ≥ 200 (a real `cl_forwardspeed` key press).
- view-angle continuity (median |Δyaw|, yaw-jump fraction) — humans aim continuously; autotrack snaps.

**Decision:** `self_pov` if `move_active_frac ≥ 0.45` and `move_nonzero_frac ≥ 0.55`; `spectator` if
`move_nonzero_frac < 0.20`; else `ambiguous`; `too_short` if < 100 frames.

**Calibration (labelled samples) — the separation is binary, not fuzzy:**

| Demo (labelled) | move_nonzero_frac | verdict |
|---|--:|---|
| `…DM3_ParadokS` (player-named POV) | 0.817 | self_pov |
| `paradoks_e_vs_ibh_dm3` | 0.859 | self_pov |
| `…Autotrack_commentary…` ×3 | **0.000** | spectator |
| `…Commentator…` ×2 | **0.000** | spectator |

Self-POV demos sit at 0.82–0.86; broadcast demos at **exactly 0.00**. No overlap.

## 4. Results (547 demos parsed)

| Class | Count |
|---|--:|
| **self_pov** | **479** (472 in 4on4 mode) |
| spectator (autotrack/commentary) | 43 |
| ambiguous | 20 |
| parse_fail | 5 |

- **parse_fail (5):** 4 truncated/corrupt + 1 misfiled server demo (named `*_mvd` / `*_CA`).
- **ambiguous (20):** almost all short single-author **trick-drill** demos (`joitrick`,
  `…headbangdoublejump`, `jumpatyaquad`, `dm3-cool`) — *correctly* excluded from the match corpus
  (docs/12 §4 separates trick-drills from match behaviour).
- **spectator (43):** exactly the `Autotrack`/`Commentary`/`Commentator` broadcast demos — the class
  the filter was built to catch, with `move_nonzero_frac == 0.00`.

### Self-POV match yield

- **472** self-POV demos in 4on4 context · **37,561,151** ground-truth usercmd frames.
- Median **86,810** frames/demo (≈ 19 min at 72 Hz); **443** are full-match-length (≥ 20k frames).
- **256** distinct players; **101** with ≥ 2 demos; **47** with ≥ 3.
- Top by demo count: crit (10), exile (9), wart (9), akke (8), spice (8), janus (7), vana (7),
  darkone (6), fs (6) — era-elite Swedish/EU 4on4 names.

## 5. Strength cross-reference (`rate_individual.py`)

`fantasyquake/data/individual_ratings.json` (carry-corrected blended individual+team, openskill
PlackettLuce — the docs/12 clone-selection axis) holds **108** rated players, but its window is
**2024–2026 modern** competitive play. The challenge-tv corpus is **classic-era (2003–2008)**, so
only **7** self-POV players appear in both:

| rating | div | player | self-POV demos |
|--:|--|---|--:|
| 2933.8 | 1 | reppie | 3 |
| 2627.8 | 1 | ParadokS | 4 |
| 2277.4 | 1 | peppe | 2 |
| 2212.3 | 1 | glad | 2 |
| 2182.1 | 1 | scenic | 3 |
| 2066.6 | 2 | blaze | 4 |
| 2014.1 | 2 | hangtime | 2 |

**Interpretation:** this is a **registry-coverage** limit, not a strength limit — most corpus names
predate the modern rating window. The matches that *do* exist are high-strength Div1 (reppie is #3 in
the modern blended list; ParadokS Div1). To rank the classic players by per-skill DM3 signature for
clone-target selection, `rate_individual.py` would need a re-run over the **classic SmackDown MVD
set** — out of spike-3 scope, but a clean follow-up.

## 6. `.qwz` decompression status — RESOLVED (no gap)

Bundled 32-bit **Qizmo 2.91** at `~/qizmo_bundle/` (binary + `compress.dat` + glibc loader/libs) in
pinnacle WSL2 decompresses `.qwz` deterministically, invoked exactly as ezQuake does
(`cl_demo.c:2988`: `qizmo -q -u -3 -D <file.qwz>`, CWD holding `compress.dat`), run via its own
`ld-linux.so.2 --library-path` since the host is x86_64 with no i386 multiarch. **Not a blocker.**

## 7. Infeasibility floor & recommendation

> **docs/12 floor:** *"if < N self-POV 4on4 demos survive → learned MOVE/AIM-of-elites is abandoned;
> fall back to hand controllers + stock combat."*

**Yield 472 self-POV 4on4 demos / 37.56 M frames / 256 players** clears any reasonable floor
(N ≈ 10–25) by ~two orders of magnitude. For scale: **MLMove** (SIGGRAPH SCA 2024) cloned pro CS team
movement from 123 h of play; 37.56 M frames at ~72 Hz ≈ **145 h** of self-POV input — same order of
magnitude, **for a single map**.

### **RECOMMENDATION: learned MOVE / AIM-of-elites is FEASIBLE.**

Caveats that *scope* the claim (none reopen the floor):

1. **Per-player depth is thin for cloning a *single* elite in isolation** (max 10 demos/player; most
   1–2). The realistic shape is **pool-pretrain (472 demos + the ztricks movement prior) → per-player
   fine-tune**, not "clone one player from their demos alone."
2. **AIM target-selection still needs POV × MVD fusion** (per-frame opponent positions), which this
   census does not provide. Only aim-**tracking dynamics** are feasible from POV alone — exactly as
   docs/12 §5 already scopes it ("hand-aim on a learned target is the expected interim outcome").
3. **Classic-era strength ranking** for clone-target selection needs `rate_individual.py` re-run over
   the SmackDown MVDs (the modern registry doesn't cover these names).

---

## Artifacts

| File | Contents |
|---|---|
| `self-pov-census.json` | machine-readable census (all numbers above) |
| `self_pov_per_demo.tsv` | per-demo class + metrics (547 rows) |
| `self_pov_summary.json` | classifier aggregate output |
| `classify_self_pov.py` | the parse-grounded self-POV classifier |
| `decompress_dm3_local.sh` | local WSL2 `.qwz → .qwd` batch decompressor |

**Reproduce (WSL2):**
```bash
MSYS_NO_PATHCONV=1 wsl -d Ubuntu-24.04 -- bash  <worktree>/experiments/stage0/data-census/decompress_dm3_local.sh
MSYS_NO_PATHCONV=1 wsl -d Ubuntu-24.04 -- python3 <worktree>/experiments/stage0/data-census/classify_self_pov.py
```
Every number above is grounded in these two commands (decompress byte-total and classifier JSON).
