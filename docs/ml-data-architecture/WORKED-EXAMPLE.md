# Worked example — one dm3 tick → world_state → agent_observation → feature vector

A single tick from the canonical fixture (`fixtures/dm3_milton_211436/`,
gameId 211436, `4on4_book_vs_3b[dm3]`), traced end to end with **real numbers**.
The numbers below are produced by the shared `scripts/features` module
(`integration/`) — regenerate them with:

```bash
cd integration
python -c "import sys,json; sys.path.insert(0,'scripts'); \
from features import transforms as T, egocentric as E; ..."   # see commit log
```

The chosen tick is **t = 130.0 s**, mid Milton's quad run (quad picked up at
124.853 s → 8 frags). It is the strongest "Milton wrecks" moment in the demo.

---

## 1. Raw tick (what the demo stores)

MVD stores **state**, not inputs. At t=130 the 8 player entities carry position,
health, armor, weapons, ammo, powerups, and nearest loc (`actor_ticks.sample.json`).
Critically, **velocity and view-angles are NOT in the stream** — velocity is
finite-differenced from the native-rate (~77 Hz) position trail; angles are recovered
via the dense-input (`qwd_usercmd`) path, not from MVD.

Milton (Book): `pos [1499,-176,-78]`, h95 a82(ra), RL+SSG, **quad held**, loc `bridge.high`,
mid-fall (derived velocity ≈ `(-38,-77,-423)` qu/s).

## 2. world_state (omniscient, 8 actors)

The full objective state — every actor's true position/status. This is the
**training target / critic input**, never the policy input (a policy fed world_state
is a wallhack bot). From `actor_ticks.sample.json::world_state_t130`:

| actor | team | pos | h / a | weapons | loc |
|---|---|---|---|---|---|
| Milton | Book | [1499,-176,-78] | 95/82 ra | RL SSG **+quad** | bridge.high |
| wimsuit | Book | [1271,-934,-24] | 44/150 ya | RL | YA.box |
| sae | Book | [101,-681,328] | 36/0 | — | RA |
| stepcop | Book | [-78,-655,-16] | 52/57 ra | LG SNG | RA.low |
| gLAd | 3b | [511,848,153] | 100/0 | — | lifts |
| gor | 3b | [444,-207,74] | 100/0 | — | Ring |
| Zepp | 3b | [1812,431,-88] | 100/0 | — | RL |
| SS | 3b | [-55,765,104] | 76/0 | LG | SNG.ledge |

## 3. agent_observation (Milton's POMDP view)

The policy sees only what Milton could perceive. The visibility gate is
`is_visible = pvs_visible AND in_fov AND los_clear` (`00-DATA-ARCHITECTURE.md` §2.8).

> **Dependency flag:** full PVS + hull-0 line-of-sight needs `bsp_geom.py` (out of
> scope — see the plan). This example therefore shows the **relative geometry** the
> observation layer computes for every candidate target; the real masking AND-gates
> these with `pvs_visible`/`los_clear` once that engine code lands. Until then,
> unseen enemies fall to the **belief/memory** channel (last-seen pos + `time_since_seen`).

Egocentric geometry to each enemy (computed by `scripts/features/egocentric.py`;
observer yaw = 0 placeholder, since Milton's true yaw needs the dense path):

| enemy | dist (qu) | dist_n (÷diag) | bearing° | sin / cos | pitch° | loc |
|---|---|---|---|---|---|---|
| Zepp | 683 | 0.180 | +62.7 | +0.889 / +0.458 | −0.8 | RL |
| gor | 1066 | 0.281 | −178.3 | −0.029 / −1.000 | +8.2 | Ring |
| gLAd | 1442 | 0.380 | +134.0 | +0.720 / −0.694 | +9.2 | lifts |
| SS | 1826 | 0.481 | +148.8 | +0.518 / −0.855 | +5.7 | SNG.ledge |

Nearest enemy = **Zepp (683 qu)** — and indeed Milton frags Zepp three times in the
seconds that follow (`frag_events.sample.json`: 133.0 ssg, 134.6 lg, plus 140.9).

## 4. Feature vector (normalized, model-ready)

Milton's self-block, via the per-feature methods in
`normalization_stats.template.json` (applied by `scripts/features/transforms.py`):

| feature | raw | method | normalized |
|---|---|---|---|
| pos_x | 1499 | minmax[-984,2048] | **0.8189** |
| pos_y | -176 | minmax[-960,1136] | **0.3740** |
| pos_z | -78 | minmax[-416,496] | **0.3706** |
| health | 95 | ÷250 | **0.3800** |
| armor | 82 | ÷200 | **0.4100** |
| has_quad | true | flag | **1** |
| vel_x | -38 | zscore(2.1,310.4) | **-0.1292** |
| vel_y | -77 | zscore(-0.4,305.9) | **-0.2504** |
| vel_z | -423 | zscore(0,180) | **-2.3500** |

(`vel_z = -2.35` correctly flags the steep fall off bridge.high — the z-score makes
the descent a strong signal. Angles would add `yaw`/`pitch` via `sincos`.)

Plus, per visible enemy: `[dist_n, bearing_sin, bearing_cos, rel_pitch, has_rl, has_quad, …]`
and, per unseen enemy: the belief block `[last_seen_x_n, last_seen_y_n, time_since_seen_n]`.

## 5. Why this fixture

The same tick exercises every v2 layer end-to-end: **multi-actor** world_state (§2.7),
**POMDP** masking (§2.8), **team** structure (Book vs 3b, §3.7), **audio** cues
(`events.sample.json`: Milton's quad pickup is a map-wide sound; gLAd calls "enemy quad"
0.6 s later), and **region control** (Book holds RA 54.6% / Quad 27.5%). The 294–80
blowout is the label these features must ultimately predict.
