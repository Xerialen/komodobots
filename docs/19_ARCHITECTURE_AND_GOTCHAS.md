# 19 — Architecture and gotchas (the trap map)

**Status:** living reference. Companion to `docs/18_BENCH_ITERATED_BOT_PROGRAM.md` (the
program of record). This doc is *not* the plan; it is the map of how the Komodobots live
pipeline fits together and — more importantly — the **hard-won particularities and the
mistakes that already cost real time**, so the next session (any agent, any model) does not
repeat them.

**Read me before you touch the live loop, the bench, the merge gate, or the box.**

Every concrete claim below (file path, cvar, constant, flag) was verified against the
repository at the time of writing. The repo moves fast: per `AGENTS.md`, **reconcile against
live state before acting**, and decide canonicality by the recency of the actual change, not
by what a doc or a memory asserts. Where this doc and the code disagree, the code wins —
then fix this doc.

---

## 1. The big picture (Phase 0 live loop)

The north star (`AGENTS.md`): *can QuakeWorld bots be believable substitutes for real
players?* The bench is the judge — team **leap** (our bot) vs team **frog** (stock skill-20
Frogbots), 4v4 on dm3, win = total frags, combat guard = **damage-done, never accuracy**
(see `docs/18`).

Phase 0 proves the *live brain pipe* using the already-trained MoveMLP as a seed. The data
path per server tick (~77 Hz):

```
KTX (patched qwprogs.so, mode 30)                 MoveMLP sidecar (python)
  bot_movement.c :: BotApplyMoveProbeLive            scripts/move_policy_sidecar.py
  ─ build 6-feature world-view (move_world_view.c) ─┐
  ─ WRITE VIEW record  ───────────────────────────► │ read VIEW (valid slots)
                          /dev/shm/komodo_move_t06   │ MoveMLP forward → argmax
  ─ READ MOVE record  ◄──────────────────────────── │ WRITE MOVE (fwd/side/jump)
  ─ apply move only; aim+fire stay stock frogbot ───┘
  ─ if stale/torn/absent → SILENT fallback to stock frogbot
```

Component map (all paths from repo root):

| Piece | File | Role |
|-------|------|------|
| World-view (single source of truth) | `scripts/move_world_view.py` | the 6 features, identical offline + live (no train/serve skew) |
| World-view, C side | `experiments/ktx_moveprobe/live/move_world_view.{c,h}` | byte-matched mirror compiled into KTX |
| Transport, python | `scripts/move_policy_sidecar.py` | shm layout owner, seqlock, MoveMLP runner, sidecar serve loop |
| Transport, C side | `experiments/ktx_moveprobe/live/move_shm.{c,h}` | byte-matched mirror compiled into KTX |
| KTX live mode patch | `experiments/ktx_moveprobe/frogbot-moveprobe-live.patch` | adds mode 30 `BotApplyMoveProbeLive` + embeds the live `.c/.h` into KTX src |
| Base per-slot moveprobe patch | `experiments/ktx_moveprobe/frogbot-moveprobe-perslot.patch` | the `_s<N>` per-slot cvar plumbing mode 30 rides on |
| Live launcher (on box) | `experiments/ktx_moveprobe/run_live.sh` | scratch KTX + sidecar bring-up; the canonical recipe |
| Runbook + evidence | `experiments/ktx_moveprobe/T0.3_LIVE_MODE.md` | done-when checks, on-box validation log |
| 4v4 ledger validation runner (frogbot baseline today) | `scripts/run_4v4_validation_lab.py` | spawns a server, plays 8 frogbots, records the MVD |
| Ledger builder + integrity rules | `lab/server/fourvfour_validation_build.py` | validates a match and writes the `komodobots.4v4_validation.v1` ledger |
| Movement metrics (speed) | `scripts/extract_movement_metrics.py` | derives avg/max speed from the MVD analyzer's `events.txt` |
| Dashboard | `lab/dashboard/` + `lab/server/control_bridge.py` + `scripts/telemetry_ws.py` | live view + 4v4 evidence page |
| Cloud hub | `cloud/cloud_hub.py` | landing page + serves the built dashboard + demos on the box |

The 6 world-view features (`scripts/move_world_view.py:57`, `FEATURE_NAMES`):
`hspeed/320, vz/320, lvm_sin, lvm_cos, moving, pitch/90`. The MLP has **three heads only**
— fwd(3)/side(3)/jump(2), **no view head**. View/aim is Stage-3 work; in Phase 0 aim+fire
are stock frogbot. See §8.

---

## 2. KTX bot slot seating — the cvar suffix is the EDICT, not the slot

**Symptom / what bites you:** you set `k_fb_moveprobe_mode_s0..s3 = 30` expecting the four
leap bots to go live, but one (or all) play as stock frogbot, or the wrong bots go live.

**Why:**
- KTX `addbot` is a **client-only `botcmd`**. There is **no console `addbot`** (verified on
  box: console `addbot` → `Unknown command`). Bots are added by a connected client — in the
  lab, a spectator shim (`qw_min_client.py --spectator`).
- The connecting spectator/control client always takes **client slot 0** (the lowest free
  slot), regardless of `maxspectators`. So the four leap bots — added first, as team1 —
  land on **internal slots 1..4**, which are **edicts 2..5**.
- The internal slot is `slot = NUM_FOR_EDICT(self) - 1`
  (`frogbot-moveprobe-perslot.patch:28`, `:319`, `:2758`).
- The per-slot cvar is built as `k_fb_moveprobe_<param>_s<N>` where **`<N>` is the 1-based
  EDICT** (`NUM_FOR_EDICT(self)`), **not** the internal slot
  (`frogbot-moveprobe-perslot.patch:301`: `snprintf(name, ..., "k_fb_moveprobe_%s_s%d",
  param, NUM_FOR_EDICT(self))`).

**What to do / invariant:** to put the four leap bots (edicts 2..5, internal slots 1..4)
live, set **`k_fb_moveprobe_mode_s2..s5 = 30`**. Leave `s6..s9` unset — those are the frog
team and must stay stock. (`run_live.sh` is the *simpler matchless-FFA* case, but it is **not**
an exception to the rule: it also adds its bots through the spectator shim
(`qw_min_client.py --spectator`, `run_live.sh:79-81`), so that spectator still takes client
slot 0 and the bots still land on slots 1..N / edicts 2..N. It sets `k_fb_moveprobe_mode_s0..s3`
(`run_live.sh:62-65`) as a **blanket over-cover** for its handful of bots — that range happens
to key the unused spectator slot 0 *plus* bot slots 1..3, which is harmless because the
spectator is not a frogbot. Setting `s0..s3` is therefore consistent with — not a counterexample
to — the EDICT-suffix rule, and you must **not** copy `s0..s3` into the 4v4 case: there it would
key the spectator + edicts 2..4 and leave edicts 4/5 uncovered, so the 4v4 case needs `s2..s5`.
The rule is mechanical: write the EDICT suffix of the bots you want live.)

**Evidence:** `frogbot-moveprobe-perslot.patch:28,301,319`;
`experiments/ktx_moveprobe/T0.3_LIVE_MODE.md:43`; memory `leap-slot-seating-cap8`.

---

## 3. MSHM_MAX_SLOTS capacity — 4 was a silent 3-vs-4 bug; now 8

**Symptom / what bites you:** with capacity 4, the **fourth** leap bot silently played as a
stock frogbot, producing an unintended **3-leap-vs-4-frog** match that *looked* like a valid
4v4.

**Why:** with `MSHM_MAX_SLOTS = 4`, the live hook guards `if (slot < 0 || slot >=
MSHM_MAX_SLOTS) return;` (`frogbot-moveprobe-live.patch:105`). The fourth leap bot is
internal slot 4, so the guard early-returned **before** it could write a VIEW / read a MOVE
→ stock fallback, no error, no log of why.

**What to do / invariant:** capacity is now **8** in three places that MUST agree:
- `experiments/ktx_moveprobe/live/move_shm.h:45` — `#define MSHM_MAX_SLOTS 8`
- `scripts/move_policy_sidecar.py:93` — `MAX_SLOTS = 8`
- the copy embedded inside `frogbot-moveprobe-live.patch:510`

Region byte layout (8 slots), all from `live/move_shm.h:48-57`:

| Block | Per-slot | Count | Bytes |
|-------|----------|-------|-------|
| VIEW body `<I6fB3x` | 32 | — | — |
| VIEW slot (guard_a + body + guard_b = 4+32+4) | 40 | 8 | 320 |
| MOVE body `<IbbBx3f` | 20 | — | — |
| MOVE slot (4+20+4) | 28 | 8 | 224 |
| **REGION** | | | **544** |

Region = `[ VIEW[0..7] ][ MOVE[0..7] ]`; the MOVE block starts at offset 320.

**Stale-fact warning:** `T0.3_LIVE_MODE.md:73` still reports the region as **272 B** — that
was the **4-slot era** (`4*(40+28) = 272`). On 8 slots it is **544 B**. The 272 figure in
that runbook predates the capacity bump (PR #251) and should be read as historical. The
authoritative size is `MSHM_REGION_SIZE` in `live/move_shm.h:57` (544).

**Evidence:** `live/move_shm.h:45-57`; `move_policy_sidecar.py:93,103-119`;
`frogbot-moveprobe-live.patch:105,510-521`;
`experiments/ktx_moveprobe/evidence/t0.7_slot_capacity8.json` (all 4 slots 1..4 go LIVE on
box); memory `leap-slot-seating-cap8` (PR #251, `qwprogs-1.48-dev-t07cap8.so` on box,
snapshot `snap-0aa029d704c4bf185`).

### 3a. The embedded patch copy must stay byte-identical (drift guard)

**Symptom / what bites you:** you edit `live/move_shm.c` (or `.h`, or `move_world_view.*`)
but forget the copy inside the `.patch`; the box builds a divergent transport and the
CI byte-match contract silently no longer describes what runs.

**Why:** `frogbot-moveprobe-live.patch` *embeds whole copies* of the four live source files
as new-file hunks (`src/move_world_view.{c,h}`, `src/move_shm.{c,h}`). Those must equal the
canonical `experiments/ktx_moveprobe/live/` files.

**What to do / invariant:** after editing any `live/` file, **regenerate the patch** (copy
`live/` into the KTX `src/` and re-diff). The guard test `tests/test_live_patch_sync.py`
extracts each embedded new-file body and asserts it equals the canonical file (and that the
patch wires CMake + `BotApplyMoveProbeLive` + `mode == 30`). It runs on the stdlib CI floor.
Run locally: `python3 -m unittest tests.test_live_patch_sync -v`.

**Evidence:** `tests/test_live_patch_sync.py:28-97`.

---

## 4. The live loop and the SILENT fallback — the expensive trap

**Symptom / what bites you:** a match runs, frags accrue, it *looks* live — but it was
actually **frog-vs-frog** the whole time because the sidecar never served (dead, never
started, wrong shm name, or torch missing). Nothing crashed. Nothing in the demo says
"this was stock."

**Why (by design):** the loop is built to **never freeze the bot**. KTX (mode 30):
1. owns region creation — `mshm_create()` once per process on the first live frame
   (`frogbot-moveprobe-live.patch:131`); the sidecar **attaches** to the region KTX created
   (`move_policy_sidecar.py:463`, `serve_loop` calls `open_region`, not `create_region`);
2. each tick writes the VIEW, then reads the freshest MOVE;
3. accepts the MOVE only if **untorn AND `ans_seq != 0` AND `ans_seq >= resume_req` AND
   `(req - ans_seq) <= stale_ticks`** (`frogbot-moveprobe-live.patch:186-196`);
4. otherwise **leaves the stock-frogbot direction/jumping untouched** — a clean, silent
   fallback to stock frogbot (`:198-201`).

So a never-served sidecar yields a perfectly playable stock-frogbot bot. The only built-in
signal is the throttled status log gated by `k_fb_moveprobe_live_log 1`:
`[moveprobe-live] slot N LIVE …` vs `[moveprobe-live] slot N FALLBACK (stock frogbot; …)`
(`frogbot-moveprobe-live.patch:18-72`, `:204`). That log is the *only* on-server tell;
without it the run is indistinguishable from stock.

The async pipeline is intentional: the sidecar is a separate process, so a 1-tick answer lag
is normal (`req=4243 ans=4242` in the evidence). `k_fb_moveprobe_live_stale_ticks` (default
3, ~40 ms at 77 Hz) is the freshness window. On a session discontinuity (respawn, map
restart, paused sidecar) the hook re-baselines `resume_req` so a *persisted* MOVE from
before the gap is never accepted as fresh (`frogbot-moveprobe-live.patch:160-176`).

**What to do / invariant:** **never trust "the match ran" as proof it was live.** A live run
must be backed by:
- the `[moveprobe-live] … LIVE` lines in the server log (turn on `k_fb_moveprobe_live_log
  1`), and ideally
- a pause/resume check: `kill -STOP` the sidecar → `FALLBACK` appears, server keeps ticking;
  `kill -CONT` → `LIVE` resumes (`run_live.sh:92-94`).

**Status of an automated integrity gate:** the live runner now has **two machine-checkable
freshness/integrity guards** (added by #252 + #257) — this is no longer manual-only. When
`run_4v4_validation_lab.py` is invoked with `--live-leap`:
1. **`sidecar.started` waiter + liveness gate.** A background waiter touches
   `$rundir/sidecar.started` once it launches the live MoveMLP sidecar, and writes
   `sidecar.failed` / `sidecar.exitcode` on crash. After the match the runner FATAL-aborts if
   `sidecar.started` is missing or the waiter died before match end — *"leap bots fell back to
   stock movement"* (`scripts/run_4v4_validation_lab.py:286-351`).
2. **Per-frame freshness gate.** KTX mode 30 falls back to stock Frogbot **per frame** on a
   stale/torn/absent feed, so a sidecar that is alive but too slow still moves on stock.
   `evaluate_live_freshness()` reads the engine's cumulative per-frame LIVE counters (not the
   throttled LIVE/FALLBACK *line* ratio, which a flapping sidecar would game), writes
   `freshness.json`, and FAILS the run **before scoring** if the live fraction is below
   `--min-live-fraction` (`scripts/run_4v4_validation_lab.py:431-504,789,889-904`). Live
   evidence: healthy ≈ 0.986–0.989 PASS vs a throttled `--hz 1` sidecar ≈ 0.037 FAIL.

The ledger's *leap-vs-frog resolution* gate (§6) still exists as a separate roster guard
(`bench_could_not_resolve_leap_vs_frog_teams`) — it stops a frog-vs-frog *roster* being scored
as a leap-vs-frog verdict — but the per-frame freshness gate above is what catches a leap
roster whose bots silently fell back to stock. **Belt-and-suspenders still applies:** the
`LIVE` log + the pause/resume probe remain the cheap manual tell; the gates above are the
automated backstop. If you change either gate, update this paragraph.

**Evidence:** `scripts/run_4v4_validation_lab.py:286-351` (sidecar.started waiter + liveness),
`:431-504,789,889-904` (per-frame freshness gate + `freshness.json` + `--min-live-fraction`);
`frogbot-moveprobe-live.patch:18-72,131,160-201`; `move_policy_sidecar.py:454-484`;
`T0.3_LIVE_MODE.md:65-93`; `fourvfour_validation_build.py` leap/frog resolution gate (§6).

---

## 5. Remote shell quoting — `shlex.quote` breaks `~` tilde expansion

**Symptom / what bites you:** you "harden" a remote command by `shlex.quote`-ing the box
paths, and the sidecar/launcher silently fails to find `~/...` files — the shell receives a
literal `~` instead of expanding it.

**Why:** these run over `ssh`/`screen` where the *remote* shell does tilde expansion. Quoting
a `~/...` argument (single-quote wrap or `shlex.quote`) turns the leading `~` into a literal
character that the remote shell will not expand. The launcher therefore passes operator-set
box paths **unquoted on purpose**, and runs the python directly under `screen` (no wrapper
shell) so the argv stays clean and a later `pgrep`/`kill -STOP` targets the *real* sidecar
process, not a wrapper (`run_live.sh:84-89,92-94`).

**What to do / invariant:** for the box launcher, **leave operator-controlled `~/...` paths
unquoted**. This is safe *only* because the arguments are operator-set env vars (`SIDECAR`,
`CKPT`, `SHM`, …), not untrusted input. Do not generalize this to untrusted args.
`run_4v4_validation_lab.py` similarly passes its remote test/probe paths unquoted with raw
`~/nquakesv/...` (`scripts/run_4v4_validation_lab.py:329-331`); it does not use `shlex.quote`.

**Evidence:** `experiments/ktx_moveprobe/run_live.sh:84-95`;
`scripts/run_4v4_validation_lab.py:329-331`.

---

## 6. Speed metric source — two different speeds: KTX `speed.avg/max` vs the MVD analyzer

**Symptom / what bites you:** you conflate the two speed numbers, or you assume the validation
ledger computes/consumes speed itself.

**Why:** there are **two independent speed sources**, and they are not the same field:
- **KTX *does* report a coarse per-player speed.** `ktxstats.json` carries `players[*].speed.avg`
  and `players[*].speed.max`, and `lab/server/ktx_match_stats.py` maps them into each player's
  normalized `stats` as `avg_speed` / `max_speed` (select-path `:104-105`, normalize `:194-195`;
  `tests/test_ktx_match_stats.py:177-178` asserts they survive normalization). So speed *is*
  present in KTX stats — do not assume it is absent.
- **The fine-grained movement metric is derived separately** from the MVD analyzer's
  `events.txt`: `scripts/extract_movement_metrics.py` reads `run_dir/events.txt`
(`:684`), parses `kind == 5` events (player-origin samples: `PlayerNum`, `Origin` `[x,y,z]`,
`TimeMs`/`Time`) (`:491-505`), and computes horizontal speed as `hypot(dx,dy) / dt`
(`:312-316`), emitting `avg_horizontal_speed_qu_per_s` / `max_horizontal_speed_qu_per_s` and
percentiles into `movement-metrics.json` (schema `komodobots.movement_metrics.v2`,
`:24,382-387,703`). It skips unnamed slots by default, so the spectator shim at slot 0 is
excluded.

**What to do / invariant:** treat movement-metrics as a **separate artifact** from the
validation ledger; they are produced independently. When an overlay does fold speed in, the
rule is: **only fill speed when present, never clobber a KTX-supplied value.** (Today the
4v4 ledger builder does not consume movement-metrics at all — `VALIDATION_METRICS` in
`fourvfour_validation_build.py:56-74` is frags/deaths/damage-done/efficiency etc., no speed.
KTX stats are the source of truth for those via `normalize_match`.)

**Evidence:** `lab/server/ktx_match_stats.py:104-105,194-195` (KTX `speed.avg/max` →
`avg_speed`/`max_speed`), `tests/test_ktx_match_stats.py:177-178` (preserved through normalize);
`scripts/extract_movement_metrics.py:24,312-316,382-387,491-505,684,703`;
`lab/server/fourvfour_validation_build.py:56-74`.

### 6a. Ledger validity rules (`komodobots.4v4_validation.v1`)

`fourvfour_validation_build.py` validates each match (`validate_match`, `:214-255`) before it
counts:
- map must be `dm3` (`:219`); KTX mode must be `team`/`4on4` (`:221`); `deathmatch=1`,
  `teamplay=2` (`:223-226`); duration ≥ 300 s (`:228`); exactly 8 players, 4 per team
  (`:232-237`); teams must match the roster intent (`komodobots.4v4_roster_intent.v1`,
  two accepted shapes — one komodobot + seven skill-20 controls, or four leap + four skill-20
  controls) (`:241,152-211`).
- **Fail-closed leap/frog gate** (`:251-253`): `_leap_frog_teams()` must resolve exactly one
  leap team and one frog team, else the game is invalid with reason
  `bench_could_not_resolve_leap_vs_frog_teams`. This prevents a frog-vs-frog *roster* from
  being scored as a valid leap-vs-frog comparison (but see §4 — it does not detect a leap
  roster that silently fell back to stock at the move layer).

**Evidence:** `lab/server/fourvfour_validation_build.py:25-28,56-74,152-211,214-255`.

---

## 7. The merge gate — deterministic executor, SHA-bound verdict, no branch protection

The two-layer gate (`AGENTS.md`): a deterministic CI floor is the real authority; the AI
review is an advisory filter on top. The deterministic merge executor
(`.github/workflows/review-gate-merge.yml`) merges **only when ALL** are true:

- PR open, **non-draft**, base `main`, **mergeable** (`review-gate-merge.yml:126-131`);
- label `gate: ready` present, `gate: blocked` absent (`:129-130`);
- a top-level verdict comment for the **current head SHA** containing `DECISION: PASS|READY`
  / `LABEL: gate: ready` / `HEAD_SHA: <full head sha>` (`:137-139,171-173,187`);
- that verdict **post-dates** the latest `ready_for_review` promotion **and is a PASS** — a
  later BLOCK vetoes an earlier PASS even if the `gate: blocked` label write failed
  (`:164-196`);
- `PR Tests` present and passing, and **no** other non-gate check failing (SUCCESS / NEUTRAL
  / SKIPPED only); **fail-closed** if `PR Tests` is absent (`:226-235`);
- the `gate: ready` label has been stable for **READY_COOLDOWN = 300 s** (`:205-210`).

Triggers it reconciles on (`:36-45`): `pull_request:labeled`/`reopened`, `issues:labeled`
(PR labels can arrive via either webhook), `workflow_run` completion of `PR Tests`, and a
cron reconciler. `ready_for_review` is **intentionally not** a merge trigger (Reset owns it,
`:26-34`).

A new commit resets the gate: `review-gate-reset.yml` removes `gate: ready`/`gate: blocked`
and sets `gate: reviewing` on `opened`/`reopened`/`ready_for_review`/`synchronize`
(`review-gate-reset.yml:8-9,33-35`). `gate-draft-guard.yml` strips `gate: ready` from a draft
and restores `gate: reviewing` (`gate-draft-guard.yml:14-17,62-67`).

`pr-tests.yml` is the **stdlib-only** floor: `python -m unittest discover -s tests -p
"test_*.py" -v` on Python 3.12, ubuntu-latest, **no torch / no external deps**
(`pr-tests.yml:3,22,28,30`). torch-dependent tests skip cleanly when torch is absent.

**Gotchas:**
- **STALE FACT:** `AGENTS.md` says a "10-minute reconciler"; the workflow cron is
  **`*/5 * * * *`** — every 5 minutes (`review-gate-merge.yml:45`). The code is authority.
  (Operationally the cron reconciler has been observed wedged — see memory; the reliable
  trigger in practice is the `PR Tests` `workflow_run` completion event, i.e. re-run "PR
  Tests" to force re-evaluation. Combined with the 300 s cooldown, expect a few minutes of
  latency before a ready PR merges.)
- **NEVER set `gate: ready` on a draft** — the draft guard will strip it, and the executor
  skips drafts anyway. Open PRs **non-draft** when you want them reviewed-and-merged.
- **`main` is unprotected** (free private plan; `gh api .../branches/main/protection` → 404).
  The executor *substitutes* for branch protection but does **not** check authorship — see §8.

**Evidence:** `.github/workflows/review-gate-merge.yml`, `review-gate-reset.yml`,
`gate-draft-guard.yml`, `pr-tests.yml`; `AGENTS.md:55-79,108-168`; memories
`review-gate-self-review-gap`, `draft-pr-never-gate-ready`, `pr-review-protocol`.

---

## 8. Review roles + Codex semantics — the self-review / auto-merge gap

**Symptom / what bites you:** a Claude-authored PR gets merged on a Claude review-loop's
`gate: ready` **before** the independent (Codex) reviewer ever looked at it — a
role-separation breach, and on a race the gate can merge a head whose real finding lands
seconds too late (this orphaned a fix on #239).

**Why:**
- `main` is unprotected and the merge executor does **not** check PR authorship; it merges on
  `gate: ready` + SHA-bound PASS + green tests. The role separation in `AGENTS.md` (Coder ≠
  independent Reviewer; prefer a *different LLM*) is a **convention**, not a runtime block.
- The review-open-PRs Claude loop reviews *all* open base-main PRs, including Claude-authored
  ones, and can set `gate: ready` itself — that is a Claude grading Claude (self-review).
- The merge executor then auto-merges. Observed on #205 and #226; on #239 the gate merged
  `591d265` two minutes before Codex's real P2 finding landed → the fix commit was orphaned.

**Codex (`chatgpt-codex-connector`) semantics — verified:**
- A **clean** pass is an **issue comment** "Didn't find any major issues … Reviewed commit:
  `<sha>`". Suggestions come as a **COMMENTED review** with inline P1/P2 comments (fetch via
  `pulls/<n>/comments`). A clean pass is *not* a review object.
- Codex auto-reviews on **PR open / mark-ready / explicit `@codex review` comment** — **not**
  on a plain push to an already-open PR. **The explicit `@codex review` ping is
  load-bearing**; re-ping after every blocking-fix push.
- **Codex CANNOT set labels or mutate the PR** — it runs in a network-isolated sandbox (no
  `gh`, no git remote, no GitHub API egress; a `curl POST .../labels` returns 403). Its only
  write path is the review text the connector posts.

**What to do / invariant (owner protocol, 2026-06-17):**
1. `@codex review` is posted **only on a PR**, on open and after each blocking-fix push.
2. **Max 2 Codex rounds for non-blocking** feedback; blocking findings have no cap (they
   block merge). Don't pingpong on nits.
3. Leftover non-blocking nits after 2 rounds → file a repo issue labelled **`optional`**
   (color `c5def5`).
4. Set `gate: ready` **only after** confirming a Codex clean signal exists on the **current
   head SHA** (its "Didn't find any major issues … Reviewed commit `<sha>`", **not** the
   Claude loop's gate label) **and** the PR is non-draft.

Do **not** treat the review-open-PRs loop's `gate: ready` as the independent review. To
guarantee a non-Claude pass before a Claude-authored PR merges, either keep it a draft until
Codex reviews (the executor ignores drafts) then mark ready, or get the loop to skip
same-author PRs.

**Evidence:** `AGENTS.md:35-79`; memories `review-gate-self-review-gap`,
`pr-review-protocol`, `draft-pr-never-gate-ready`, `loop-merge-authority`.

---

## 9. The box (komodo-aws) — reachability before "blocked"

The whole lab runs on a pinnacle-independent AWS box.

- **Instance** `i-0a47bfde4edd12455`, t3.medium, Ubuntu 24.04, **eu-north-1**. Public IP
  **changes on stop/start**. On-demand: stop when idle.
- **Access:** `ssh komodo-aws` (key `~/.ssh/komodo-claude.pem`); SG allows SSH from the
  owner's IP only. Cloudflare-tunnelled browser terminal at **https://komodo.xerious.org**
  (Gmail-gated ttyd+tmux); dashboard at **https://komodolab.xerious.org**.
- **AWS CLI:** profile `komodo` (`~/.aws-cli-venv/bin/aws`, eu-north-1), scoped IAM user
  `claude` — **EC2-only, not admin** (can't touch IAM/SSM); CAN start/stop/resize, create
  EBS snapshots, modify the SG.

**Sandbox / reachability gotchas:**
- **SSH/scp/rsync (port 22) need the sandbox DISABLED** (`dangerouslyDisableSandbox: true`);
  port 22 is filtered in-sandbox. `gh`/HTTPS/`aws` work in-sandbox.
- Direct SSH is **blippy** (intermittent timeouts) — retry 2-3×; the CF tunnel is steadier.
- **Reachability rule (binding):** never call work "box-gated" / "needs the live box" /
  "can't be done in this sandbox" **without first running the reachability check**: AWS CLI
  `describe-instances` state (in-sandbox) → start if stopped (`cloud/manage.sh start`) →
  `ssh -o ConnectTimeout=12 komodo-aws hostname` (sandbox off). The `komodo-box` skill encodes
  the full runbook. *Needing* the box ≠ being *unable to reach* it.

**Do-not-harm guardrails:**
- **NEVER touch the 4 standing game servers / ports 28501–28504, QTV 28000**, or the live
  `ktx` gamedir / its `qwprogs.so`. The standing servers run under the `quakelab` systemd
  unit; the validation runner spawns its **own** server on its own port + screen, so it does
  not collide — just don't aim it at 28501–28504.
- Lab **scratch ports** are **28599–28609** only (`ALLOWED_LAB_PORTS = range(28599, 28610)`;
  `DENIED_PORTS = (28501, 28502, 28503)` in `lab/server/control_bridge.py:74-75`).
  `run_live.sh` defaults to scratch port 28599 and **refuses** 28000/28501-28504
  (`run_live.sh:38-40`).
- **Never print secrets** (box `~/.config/api-keys.env`; pinnacle `~/.config/api-keys.env`).

**Evidence:** `lab/server/control_bridge.py:74-75`; `experiments/ktx_moveprobe/run_live.sh:24-40`;
memories `cloud-box-migration-state`, `reachability-before-blocked`,
`komodobots-rt-teammode-and-dashboard`; the `komodo-box` skill.

### 9a. 4on4 team mode — the `k_matchless`/`k_allowed_free_modes` trap

**Symptom / what bites you:** you set `teamplay 2` for a 4on4 match and the server logs
`WARNING: teamplay changed to: 0` — it ran FFA, no teams, the demo is canceled
("No non-empty MVD", exit 8).

**Why:** `k_matchless 1` **hard-forces the `ffa` usermode**, which zeroes teamplay
(KTX `commands.c`: `um_idx_byname(k_matchLess ? "ffa" : k_defmode)`). And even with
`k_matchless 0` + `k_defmode 4on4`, KTX discards the 4on4 usermode unless
**`k_allowed_free_modes 4095`** (a bitmask) is set, falling back to ffa.

**What to do / invariant (proven on box):** `k_matchless 0` + `k_defmode 4on4` +
**`k_allowed_free_modes 4095`** + a **ready client-player on a team** to anchor match start
(a connected client that does `setinfo team red` + `ready`; it then adds frogbots via
`botcmd addbot`, which auto-balance). `addbot` takes only `[skill] [team]` — no name/color
via addbot. The named, policy-driven leap komodobots require the real policy client, not the
minimal `qw_min_client.py` skeleton.

**Note:** `run_live.sh` is the *simpler* matchless-FFA live-loop bring-up (`k_matchless 1` +
`k_defmode ffa`), used to observe the live brain end-to-end; the **4on4 verdict** path needs
the team-mode recipe above.

**Evidence:** memories `komodobots-rt-teammode-and-dashboard`,
`cloud-box-migration-state`; `run_live.sh:51-69`.

---

## 10. WSL `/tmp` worktree volatility

**Symptom / what bites you:** a worktree you created under `/tmp` (e.g. `/tmp/komodo-...`)
disappears between sessions and your in-progress edits seem gone.

**Why:** `/tmp` on WSL is volatile and can be reaped. The **branch** persists in git; the
working directory does not.

**What to do / invariant:** the branch is durable — re-create the worktree
(`git worktree add <path> <branch>`) or check out the branch elsewhere. Commit and push
early so nothing important lives only in a `/tmp` working tree. `git worktree prune` cleans
stale registrations.

---

## 11. The MoveMLP policy — move-only, and the standstill fixpoint baseline

**Symptom / what bites you:** the first leap-vs-frog verdict shows a **negative** frag margin
(leap loses), and the bots barely move at standstill. This looks like a broken loop.

**Why (expected, not a defect):**
- The MoveMLP is **move-only by design**: heads fwd(3)/side(3)/jump(2), no view head
  (`komodobots-ml/.../train.py`); view-yaw/pitch are *input features*, not targets. Learned
  aim is **Stage-3**; Phase 0 uses **stock frogbot aim+fire** (`docs/18`; memory
  `move-policy-move-only-coupling-stage3`). So a Phase-0 leap bot is "learned move + stock
  aim" — it cannot out-aim frog, only out-move.
- The behavioral-cloning policy has a **standstill fixpoint** (*stillastående*): at zero
  velocity it outputs a near-zero move (a BC fixpoint), so it can fail to self-start moving.
  This is the **known unsolved movement wall**, a *policy* property to be fixed by richer
  training (Phase 1+), not a loop bug (`T0.3_LIVE_MODE.md:100-102`).

**What to do / invariant:**
- The first verdict's number is the **baseline to beat**, not a pass/fail. A negative
  Phase-0 margin is an **accepted baseline** (`docs/18` Phase-0 PASS bar: "loop runs honest
  end-to-end; the number is the baseline to beat — not a win yet").
- Score by **frags** (win) with **damage-done** as the combat guard. **Never gate on
  accuracy** — a bot can fake high LG% by barely shooting; damage-done can't be faked that
  way (`docs/18:13`).
- Coupling (DeepFrag's air-strafe view-vs-heading metric) is a **Stage-3** human-likeness
  gate; do not wire it as a Phase-0/1 training signal — for a move-only policy on replayed
  view it passes trivially/circularly (memory `move-policy-move-only-coupling-stage3`).

**Evidence:** `docs/18_BENCH_ITERATED_BOT_PROGRAM.md:9-13,73`;
`experiments/ktx_moveprobe/T0.3_LIVE_MODE.md:100-102`; memory
`move-policy-move-only-coupling-stage3`.

---

## 12. Subagent dispatch hazard

**Symptom / what bites you:** two agents editing the same worktree concurrently collide —
one's edits clobber the other's, or a stale read causes an Edit to fail.

**Why:** a fresh `Agent` call starts an isolated context; two of them on the same working
tree have no coordination.

**What to do / invariant:** run *read-only* exploration agents in parallel freely, but
**serialize writes** to one worktree. To continue work an agent already has context for, use
**SendMessage to the running agent**, not a fresh `Agent` call. For genuinely parallel write
work, give each agent its own worktree (`isolation: "worktree"`).

---

## 13. Other sharp edges

- **CRLF noise on the dashboard tree.** The box's dashboard `dist` was once built from a stale
  branch and `App.tsx` showed a phantom diff that was pure CRLF, not real edits. For dashboard
  PRs, branch from a **fresh worktree off `origin/main`** (clean LF). (memory
  `cloud-box-migration-state`.)
- **No docs/markdown/link-check CI exists.** The only PR gate that runs on a docs-only change
  is `PR Tests` (the stdlib unit suite). There is no markdown linter or link checker workflow
  in `.github/workflows/`. Validate doc links by reading; don't expect CI to catch a broken
  one. (`grep` of `.github/workflows/` — no docs/markdown job.)
- **`pgrep -f` self-matches.** Polling for a process with `pgrep -f run_bot_lab` /
  `pgrep -f move_policy_sidecar` will match the *poller's own* command line. Run long jobs
  detached and poll a logfile, or filter `pgrep` output to the real interpreter
  (`run_live.sh:93` filters to `comm=python*`). (memory `komodobots-rt-teammode-and-dashboard`.)
- **Canonical parser = mvdanalyzer (`qw-analyze-v20`).** Trust it for decisions/economy/combat
  + bench scoring. **demopasha/`mimer`** is complementary/tentative — use it **only** for raw
  x/y/z positions, cross-checked against the canonical numbers (`docs/18:38-45`).
- **MoveMLP checkpoint is a gitignored 4090/WSL artifact** (`~/move_bc_policy.pt`); the sidecar
  loads it lazily and raises a clear `FileNotFoundError` if absent (`move_policy_sidecar.py:355,393-396`).
  The transport + argmax are pure stdlib so they test on the CI floor without torch.

---

## Maintenance

When any fact here changes, update this doc in the same PR per `AGENTS.md` documentation
rules, and route the underlying discovery to its home doc (movement → `docs/03`, pipeline →
`docs/06`, decisions → `docs/08`, etc.). If you find a *new* trap, add a §-entry in the
**Symptom → Why → What to do / invariant → Evidence** micro-format. Re-verify any recalled
"canonical / latest" claim against live git state before writing it as current.
