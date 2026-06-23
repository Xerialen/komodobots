"""broad_bc — BROAD (enemy/team-aware) behavioral-cloning trainer for the dm3 4on4
stand-in bot.

This package is the TRAINER unit (P4 scaffold). Unlike the move-only Stage-2
template (`experiments/stage2/move-bc-train/`, which clones a 6-dim self-movement
vector -> fwd/side/jump only), the model here is trained on the FULL POMDP
`agent_observation` from `data/catalog/dataset_spec.yaml`:

    self features (obs)  +  N observed-other egocentric vectors (entities)
    +  audio cues  +  team context   ->   the broad human usercmd action

so the policy is enemy- and team-aware, not movement-only.

Layout (everything here is DEPS-FREE except the torch trainer next door):
  shard_contract.py  — the documented SHARD CONTRACT the loader binds to
                       (feature column order, action labels, window) + a tolerant
                       resolver that rebinds to FEAT's actual emitted schema.
  synth_shard.py     — synthetic-shard generator (tiny) for the offline CPU smoke.
  core.py            — deps-free split-by-demo, action label encoding, metrics,
                       model-card assembly, AND a pure-Python reference MLP+SGD
                       trainer used by the offline smoke (no torch/numpy needed).

The heavy production trainer is `ml/train_broad_bc.py` (torch+numpy). It reuses
this package's contract / split / label-encoding / metrics / model-card so the
offline CPU smoke exercises the SAME contract the GPU run does.
"""

from . import shard_contract  # noqa: F401
from . import core            # noqa: F401
from . import synth_shard     # noqa: F401
