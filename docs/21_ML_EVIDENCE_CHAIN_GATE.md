# ML Evidence Chain Gate

Status: active review gate.

## Purpose

This gate exists to keep machine-learning work tied to the project evidence
chain:

```text
available data -> selected dataset -> model building blocks -> training run -> evaluation result -> next experiment
```

Komodobots must not drift into training because training is available. Every ML
plan must explain which data it uses, which data it ignores, how labels are
grounded, how the model maps onto QuakeWorld physics and live KTX/Frogbots, and
how the result will be judged between training sessions.

## Trigger

Use this gate before proposing, approving, or implementing any work involving:

- dataset construction, filtering, labeling, or corpus selection,
- behavioural cloning, RL, pseudo-labeling, inverse control, or learned policy work,
- model architecture, features, action heads, inference bridges, or training loops,
- evaluation gates for learned movement, aim, economy, decision, or team behaviour.

A plan that cannot answer these questions must be revised before work starts.

## Required Output

The agent must include a short "ML Evidence Chain Gate" section in the plan,
PR body, issue comment, or experiment note. It must answer each checklist item
with concrete artifacts, commands, paths, metrics, or an explicit "not applicable"
with justification.

## Checklist

1. **What exact data is being used, and what available data is being ignored?**
   Name the QWD, MVD, ktxstats, route manifests, human anchors, live bot runs,
   or external corpora in scope. If the DM3 POV corpus or exact-player anchors
   are not used, explain why.

2. **Can every training row be traced back to source?**
   Each row or shard must carry enough provenance to recover demo file, SHA,
   map, player, frame/segment, parser version, seam validation, and inclusion
   reason.

3. **Is the label actually a label?**
   QWD POV demos can provide exact usercmd labels. MVDs generally cannot. The
   plan must prove self-POV status, command/state seam alignment, paired
   coverage, and that spectator/autotrack or misaligned frames are excluded.

4. **Are training and evaluation on compatible measurement planes?**
   Do not mix QWD frame space, `pmove_sim`, MVD kind-5 samples, and live KTX
   output as if they are the same truth. Any pass/fail metric must name its
   plane, and G-ALIGN-style checks must fail closed when planes disagree.

5. **How does each model building block connect to the data?**
   For every input feature and output action, state the raw source, the game or
   physics rule that makes it meaningful, and the evaluation metric expected to
   move if the model learns correctly.

6. **How is data leakage prevented?**
   Splits must be by whole demos, players, sessions, routes, or matches as
   appropriate, not by adjacent frames when that leaks the answer. The same
   route replay, player anchor, or live run must not be both training evidence
   and evaluation evidence unless the plan explicitly marks it diagnostic-only.

7. **Which baseline must the model beat?**
   Name the relevant baseline: stock Frogbot, open-loop replay, hand controller,
   air-law prior, pmove rollout, or previous learned model. If ML does not beat
   the cheaper baseline in the required plane, the plan must say what gets
   killed, deferred, or kept diagnostic-only.

8. **What changed after each training session, and why should the result change?**
   Each session must log dataset hash, filters, model config, seed, loss or
   rollout metric, live/MVD result when available, and the expected causal link
   from data/model change to metric movement.

9. **Which failure class is isolated?**
   Classify the expected or observed failure as data quality, seam/timing,
   start context, closed-loop drift, model capacity, route geometry, live
   bridge, or scoring bug. The next experiment should change one main lever
   unless the plan explains why multiple changes are unavoidable.

10. **What would make the project stop or back up?**
    Define kill criteria before training: too little self-POV data, worse than
    baseline, face-and-run collapse, G-ALIGN failure, live inference too slow,
    metric pass with believability texture failure, or missing evidence.

## Fail-Closed Rules

The plan fails this gate if it:

- treats MVD state as exact usercmd labels,
- lacks source provenance for training rows,
- uses cross-plane pass/fail metrics without alignment evidence,
- has no baseline or kill criterion,
- reports a training improvement without a tied evaluation artifact,
- changes dataset, model, and scorer at once without a failure-isolation reason.

## Session Handoff

Between training sessions, record the evidence in the relevant experiment note,
findings log, PR body, or issue. The next agent must be able to answer:

- what data was trained on,
- what changed in the model or training,
- what metric moved,
- whether the result came from offline simulation, live KTX, MVD analysis, or
  another plane,
- what the next smallest useful experiment is.

## Latest state (2026-06-22)

This anchors the gate to the ML-data work currently in flight so reviewers can
check plans against the real artifacts, not against intentions. It is descriptive
of the current line; the checklist and fail-closed rules above remain the gate.

- **Active data line — human 4on4 dm3 MOVE corpus from `.mvd`.** The dataset
  under construction is per-tick MOVE labels recovered from human 4on4 dm3 MVDs
  on the servexeri archive (TRAIN manifest 1537 demos, bot players excluded).
  Two PRs carry it: the corpus/manifest (F-DATA-1) and the per-tick ETL
  `scripts/catalog_etl_mvd.py` (F-DATA-2). The full data-architecture rationale
  lives in `docs/20_ML_DATA_ARCHITECTURE.md`.

- **Item 3 (is the label actually a label) is the load-bearing one here.** MVDs
  record server-frame STATE, not the usercmd input stream, so MOVE labels are
  *recovered by inverse dynamics*, not observed. The ETL marks this honestly:
  `actions.label_source = 'idm'` (not `'qwd_usercmd'`), `confidence < 1.0`, and
  air-strafe sign is gated to the bhop regime (>= 400 qu/s, ~90% reliable);
  below-gate rows set `is_interp = TRUE` so they are excluded from training.
  Aim (view yaw/pitch) is the one near-lossless MVD signal (`confidence ~0.95`).

- **Item 2 (provenance) is enforced in-schema.** Rows trace to source via
  `demos.sha256` (UNIQUE), `demos.source = 'mvd'`, map/player/episode keys, and
  the qw-analyze parser version. Note the parser-version trap: MVD MOVE recovery
  REQUIRES a schema-33 qw-analyze binary (per-tick `vya`/pitch/velocity); the
  stock schema-21 binary silently drops view-yaw and would corrupt strafe-sign
  recovery. Any extraction run must pin the schema-33 binary and record its sha.

- **Item 4 (measurement planes).** Onground for MVD rows is a geometric proxy
  (`pmove_sim` floor-trace, `player_ticks.onground_is_proxy = TRUE`), not a
  server onground flag — a distinct plane from QWD usercmd onground and from
  live KTX. Plans mixing these must name the plane and fail closed on disagreement.

- **Item 6 (leakage).** Split policy is `group_by_demo_id` (whole-demo splits),
  and the 4on4 human anchors used for believability evaluation are kept distinct
  from training evidence.
