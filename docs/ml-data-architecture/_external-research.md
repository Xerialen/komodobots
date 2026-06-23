# Architecting the Data Substrate for Training an ML Model — Engineering Reference

**Scope.** A concrete, engineering-grade reference for the *data substrate* of a trainable ML model: the files, databases, schemas, dataset formats, feature definitions, and normalization calculations needed to train **reproducibly** and apply the **same transforms at inference**. This is deliberately *not* a survey of ML principles.

**Downstream weighting.** Written with a QuakeWorld FPS **bot** in mind, trained two ways: (a) **imitation / offline learning from recorded match demos** (MVD trajectories of player state over time), and (b) **RL in a fast offline physics simulator**. The features that matter most — agent position on a map, velocity, item positions/availability/respawn-timers/importance, timing, and a specific player's style — drive extra depth on spatial/positional encoding, trajectory/time-series storage, item/event tables, and turning all that into normalized training tensors. The rest is kept as a reusable general reference.

**How to read it.** Eight sections map to the eight requested topics. Section 8 is a worked, copy-pasteable reference layout (DDL, Parquet schema, feature-registry YAML, normalization-stats JSON) that ties everything together. Claims that could not be pinned to a primary source are marked `[unverified]`.

---

## 0. The mental model in one paragraph

You are building a **layered store** (raw → curated → feature → training-ready) where each layer uses the file format that matches its access pattern: append-only logs and demos in **bronze**; cleaned, conformed episode tables in **silver**; **point-in-time feature tables** (Parquet, queried with DuckDB) and **sharded streaming tensors** (TFRecord/WebDataset) in **gold**. A **relational catalog** (SQLite/DuckDB) indexes every demo, episode, map, and feature-table partition for joins and grouped splits. A **feature registry** (YAML/JSON) declares every feature once — `name, dtype, source, transform, version` — so the offline demo-mining path and the live online encoder run the *same* transform. **Normalization statistics are computed from the training split only, frozen into a versioned JSON artifact, and re-applied byte-identically at inference.** Splits are **grouped** (by demo/player/map) to prevent leakage. Everything is **versioned** (git SHA + dataset commit/`.dvc` hash + scaler artifact version) so any run is reproducible.

---

## 1. Storage Layer & File Formats

### 1.1 Apache Parquet — columnar feature tables

**Physical layout (hierarchy):** `File → Row Group → Column Chunk → Page`. Row groups are typically 64–512 MB; each row group holds one column chunk per column; each column chunk splits into pages (smallest encode/compress unit). Per-row-group and per-column **statistics (min, max, null count)** live in the file footer.

**Predicate pushdown + column projection:** engines read footer stats and skip any row group whose min/max can't satisfy a `WHERE`, and read only the column chunks you select. This is *why* columnar wins for analytical/feature workloads — you touch a fraction of the bytes.

**Hive-style partitioning** encodes partition keys as `key=value` path segments and lets engines prune whole directories before pushdown runs:
```
features/
  map=dm3/dt=2026-06-01/part-0000.parquet
  map=dm3/dt=2026-06-02/part-0000.parquet
  map=aerowalk/dt=2026-06-01/part-0000.parquet
```
Partition on what you filter on most. For QW feature tables: partition by `map` (you'll do per-map normalization and per-map splits) and by ingest `dt`.

**Typical ML feature-table layout:** one wide table, **one row per entity-timestamp** (here: one row per `(demo_id, tick)` or `(player_id, tick)`), columns = features. Snappy for hot/training-read layers, Zstd for cold/curated archives.

**Compression:**
- **Snappy** — speed-first, ~1.5–2× ratio, decompress >500 MB/s. Default for read-heavy training layers.
- **Zstd** — gzip-class ratio at near-Snappy decompress speed, tunable level (−ve…22). ~30% storage savings at lake scale; use for curated/archival.

### 1.2 Apache Arrow — the in-memory counterpart

Arrow is the in-memory columnar format Parquet decodes into. DuckDB, Polars, and pandas exchange Arrow tables zero-copy — it's the lingua franca between storage and compute. Keep your feature-engineering in Arrow/Polars/DuckDB and you avoid serialization round-trips.

### 1.3 Zarr vs HDF5 — n-dimensional arrays

Both store **chunked, compressed N-D arrays** with composable codec pipelines. Decisive difference = storage substrate:

| | **HDF5** | **Zarr** |
|---|---|---|
| Storage model | One monolithic file, internal B-tree | One file/object **per chunk** |
| Cloud (S3/GCS) | Range-requests into one big object | Each chunk an independent object → native cloud reads |
| Parallel writes | Locking; effectively one writer | Many processes write different chunks lock-free |
| Incremental append | Often a rewrite | Add chunks, no rewrite |
| Tooling | Broad: C/C++/Java/MATLAB/Fortran, HDFView, h5dump | Python-centric, growing |

**When each:** HDF5 for local disk/NFS, mature multi-language tooling, single-writer sequential reads. Zarr for cloud object stores, multi-process parallel writes, incrementally-growing datasets. For both: **larger chunks read faster**; chunk along the axis you slice. For the QW bot, occupancy/voxel-grid tensors (§4.4) or stacked per-tick spatial planes are a natural Zarr/HDF5 fit if you precompute them.

### 1.4 TFRecord & WebDataset — sharded streaming training data

**TFRecord:** a file is a sequence of length-prefixed, CRC-checksummed records, each a serialized **`tf.train.Example`** protobuf. `Example` → `Features` = `{string → Feature}`, each `Feature` one of `BytesList`, `FloatList`, `Int64List`:
```
Example {
  features: Features {
    feature {
      "obs":    FloatList { value: [<flattened obs vector>] }
      "action": Int64List { value: [3] }
      "rtg":    FloatList { value: [42.0] }
      "map_id": Int64List { value: [7] }
    }
  }
}
```

**WebDataset:** an `IterableDataset` over **sharded POSIX tar archives** — data stays as plain files. Within a tar, files sharing a **basename** but differing by **extension** form one sample. Shards named with brace expansion `dataset-{000000..012345}.tar`:
```python
import webdataset as wds
ds = (wds.WebDataset("train-{000000..000511}.tar")
        .shuffle(1000)            # in-memory sample shuffle buffer
        .decode()
        .to_tuple("obs.npy", "act.npy")
        .map(preprocess))
```

**Shard sizing & file-count (both formats):**
- Target **~100 MB–1 GB per shard**.
- **≥10× as many shards as reader hosts** so I/O parallelizes and shuffling has enough shards.
- **Two-level shuffle:** shuffle shard *order* (cheap, on disk), then keep an in-memory **sample shuffle buffer** (commonly 1000+). Near-random ordering with purely sequential reads — the key throughput trick.
- Too many small files → per-file open overhead + back-pressure; too few huge files → poor parallelism + weak shuffling. The 100 MB–1 GB band balances both.

### 1.5 npy / npz — small numpy arrays

`.npy` = one array (dtype/shape/order header + raw buffer); `.npz` = zip of multiple `.npy` (`np.savez` / `np.savez_compressed`). Use for small in-memory-sized arrays, fixtures, quick checkpoints, and the per-feature normalization vectors. No chunking / partial reads / cloud-range-read story, so they don't scale to streaming training. `[unverified — general numpy knowledge]`

### 1.6 Relational catalog — SQLite vs DuckDB

- **SQLite** = row-store OLTP; fast single-record read/write, transactional.
- **DuckDB** = columnar + vectorized OLAP; built for aggregations/joins/scans. On a 10M-row `GROUP BY … SUM`, DuckDB <1 s vs SQLite 20+ s.

**Use DuckDB for analytical queries over Parquet:** it reads Parquet footers for schema, applies predicate pushdown + column projection directly against files — no import step — and can join in-place pandas/Polars/Arrow frames against external Parquet/CSV/SQLite. **Point-in-time joins** (attach feature values *as of* a label's timestamp; §3.4) fit DuckDB's analytical SQL well; it supports `ASOF JOIN` for exactly this. (Exact `ASOF JOIN` syntax not re-verified this session — `[unverified]` on the precise SQL form, verified on the capability.)

**Recommendation for the QW bot:** keep the durable catalog (demos, players, maps, episodes, feature-table manifest) in a small **SQLite** file *or* a DuckDB file you treat as the catalog; run heavy analytical joins/aggregations and PIT joins with **DuckDB over the Parquet feature tables**. DuckDB can `ATTACH` a SQLite DB and query both together.

### 1.7 Medallion layering: raw → curated → feature → training-ready

- **Bronze (raw):** data exactly as ingested — the MVD/demo files, raw parsed per-tick event logs. System-of-record, append-only.
- **Silver (curated):** cleaned, conformed, deduped — per-tick player/item/event tables with consistent schemas and quality checks; episodes delimited.
- **Gold (consumer-ready):** the ML-ready layer — point-in-time **feature Parquet tables** (DuckDB-queried) *and* **training-ready sharded tensors** (TFRecord/WebDataset) windowed into fixed-length sequences.

Map each tier to a distinct path/namespace. Concrete layout (synthesizes the cited medallion + sharding guidance — `[unverified]` as a single canonical template):
```
lake/
  bronze/
    demos/map=dm3/dt=2026-06-01/*.mvd            # raw demos
    events_raw/map=dm3/dt=2026-06-01/*.jsonl     # raw parsed per-tick events
  silver/
    player_ticks/map=dm3/dt=2026-06-01/*.parquet # cleaned per-tick player state
    item_events/map=dm3/dt=2026-06-01/*.parquet  # pickups/respawns
  gold/
    features/                                     # PIT feature tables (DuckDB)
      agent_features/map=dm3/dt=2026-06-01/*.parquet   (zstd)
    training/                                     # sharded streaming tensors
      train/shard-{000000..000511}.tar            (WebDataset)
      val/shard-{000000..000031}.tar
    norm/normalization_stats_v2.json              # frozen stats artifact (§6)
  catalog.duckdb                                  # or catalog.sqlite (§1.6)
```

---

## 2. Trajectory / RL Dataset Standards

This is the substrate for both training modes — imitation from demos and RL rollouts. The unifying abstraction across every standard below: **episode = ordered sequence of steps**, each step carrying `(observation, action, reward, done/terminal flags)`.

### 2.1 RLDS (Reinforcement Learning Datasets)

Episodic store for RL / imitation / offline RL / learning-from-demos, loaded as a `tf.data.Dataset` of episodes, each episode a nested `tf.data.Dataset` of steps. Built on **TFDS**, generated with Apache Beam, serialized to **TFRecord**.

**Step fields & precise semantics:**

| Field | Meaning |
|---|---|
| `is_first` (mandatory bool) | first step of the episode |
| `is_last` (mandatory bool) | last step — **when true, `action`/`reward`/`discount` are invalid** (carries only the final observation) |
| `observation` | current observation |
| `action` | action taken from this observation |
| `reward` | reward after the action |
| `discount` | discount factor |
| `is_terminal` | terminal flag — when true the obs is a final state (so `reward`/`discount`/`action` meaningless); a *truncation* sets `is_terminal=False` but still ends the episode |

Constraint: **all steps in a dataset share identical fields.** Optional episode metadata: `episode_id`, `agent_id`, `environment_config`, `experiment_id`, `invalid`. These boundary flags (`is_first`/`is_last`/`is_terminal`) are exactly what lets you window sequences without crossing episodes (§2.8).

### 2.2 TFDS builder convention for RL

```python
FeaturesDict({
  'episode_return': float32,
  'steps': Dataset({                          # nested Dataset feature
    'action':      Tensor(shape=(A,), dtype=float32),
    'reward':      Tensor(shape=(1,), dtype=float32),
    'discount':    Tensor(shape=(1,), dtype=float32),
    'is_first':    bool, 'is_last': bool, 'is_terminal': bool,
    'observation': FeaturesDict({ ... task-specific ... }),
  }),
})
```
The `steps` field *being itself a `Dataset` feature* is how RLDS's episode-of-steps nesting is encoded.

### 2.3 Minari (Gymnasium / Farama) — HDF5 offline RL

Stored with h5py under `~/.minari/datasets/<id>/data/main_data.hdf5`. Episodes are top-level groups:
```
main_data.hdf5
├── episode_0
│   ├── observations   (num_steps+1, obs_shape)   # +1 includes initial reset obs
│   ├── actions        (num_steps,   act_shape)
│   ├── rewards        (num_steps, 1)
│   ├── terminations   (num_steps, 1)  bool
│   ├── truncations    (num_steps, 1)  bool
│   └── infos          (optional, may be nested)
├── episode_1 ...
```
Note `observations` has **`num_steps+1`** rows. **Dict** spaces → nested subgroups; **Tuple** spaces → indexed keys `_index_0`, `_index_1`. Dataset-level attrs: `total_episodes`, `total_steps`, `env_spec` (JSON), `observation_space`/`action_space` (serialized), `minari_version`, `algorithm_name`, author fields; `rewards` carries `max/min/mean/std/sum`. `EpisodeData` (from `sample_episodes()`): `id, seed, total_timesteps, observations, actions, rewards, terminations, truncations`.

This is the most directly-usable standard for the QW bot's **offline RL** mode — a clean HDF5 episode store with explicit truncation/termination split.

### 2.4 D4RL — classic flat-dict offline RL

`env.get_dataset()` → flat dict: **`observations, actions, rewards, terminals, infos`** (plus `timeouts` in practice, to distinguish horizon cutoff from true terminal). `d4rl.qlearning_dataset(env)` adds **`next_observations`** for Q-learning. Distributed as files fetched on first call. (`timeouts` semantics: `terminals`=MDP terminal, `timeouts`=horizon cutoff — widely-used convention; `[unverified]` from this session's fetched README, which enumerated only the five keys.) Simplest possible schema; good for a quick offline-RL baseline.

### 2.5 Decision Transformer convention

RL as sequence modeling over the trajectory:
```
τ = (R̂₁, s₁, a₁,  R̂₂, s₂, a₂,  …,  R̂_T, s_T, a_T)
```
- **Return-to-go (RTG):** `R̂_t = Σ_{t'=t}^{T} r_{t'}` — sum of *future* rewards from t to episode end. Conditioning on desired future return turns a target return at inference into a goal signal. Precompute RTG per step over the full episode **before** windowing.
- **Context window:** last **K timesteps** → **3K tokens** (RTG, state, action each get a token). Each modality has its own linear embedding + layernorm; a **timestep embedding** is added to all three tokens of a step. GPT backbone predicts actions autoregressively.

For imitation from a *specific player's style* (§ downstream goal), a DT-style return/goal-conditioned sequence model over MVD trajectories is a strong fit: window the player's episodes, precompute RTG (or a style/objective token), feed `(RTG, state, action)` triples.

### 2.6 MineRL — human gameplay demonstrations

>60M `(state, action, reward)` tuples, sampled every game tick (**20 ticks/s**). State = RGB POV + game-state features (inventory, distances, health). Action = keypresses + view pitch/yaw deltas + GUI + agglomerative actions. `sarsd_iter` yields `(state, action, reward, next_state, is_terminal)`, returning up to `max_sequence_len` consecutive samples; **at episode end the returned sequence may be shorter than `max_sequence_len`** (variable length at boundaries).

### 2.7 OpenAI VPT — the IDM pattern for MISSING action labels (critical)

The central technique for the QW bot's imitation track, because raw demos/video often lack clean per-tick action labels.

**Demo storage:** contractor gameplay in **5-minute chunks**: MP4 (720p→360p, 20 Hz) + a **JSONL** action file (one action dict per line) + options JSON + checkpoint zip.

**IDM data flow:**
1. **Small labeled set:** record video **+ ground-truth actions**. VPT used 1,962 h (~$40k), but **~100 h already saturates** IDM quality.
2. **Train the IDM** to predict action-at-each-timestep from video. The IDM is **non-causal** — sees **past *and* future** frames around t. Inverting environment mechanics is far easier than modeling human behavior → **~2 orders of magnitude more data-efficient** than behavioral cloning. Best IDM: **90.6% keypress accuracy, 0.97 R² on mouse movement**.
3. **Pseudo-label at scale:** run the IDM over ~70,000 h of unlabeled video → inferred actions for every frame.
4. **Behavioral cloning** on the pseudo-labeled corpus to train the causal foundation policy.

**For QuakeWorld:** you have a privileged advantage over VPT — MVDs already contain reconstructable player state and many inputs. Where action labels are genuinely missing (e.g. only positions/angles per tick, not the button presses that produced them), train a small **inverse-dynamics model** on the subset where you *can* recover actions (or from sim rollouts where actions are ground-truth), then pseudo-label the rest. The non-causal IDM (sees tick t−k…t+k) is the right tool to infer "what input moved the player from state_t to state_{t+1}."

### 2.8 Windowing episodes into fixed-length sequences

- **Slide a fixed window K** over each episode; use the explicit boundary flags (`is_first`/`is_last`/`is_terminal` in RLDS; `terminations`/`truncations` in Minari) so windows never cross episodes.
- **Trailing window** of an episode is typically shorter than K (MineRL explicitly returns short sequences).
- **Pad + mask:** pad short windows to K and supply an attention/loss mask so padded positions contribute nothing to attention or loss. (Padding+mask mechanics are standard practice consistent with the cited variable-length handling but not quoted verbatim — `[unverified]` as stated.)

---

## 3. Feature Engineering & a Feature Registry

### 3.1 Feast object model (the reference, even if you build lighter)

- **`Entity`** — a logical group of time-series feature data identified by **join keys** (the lookup primary key). For the bot: `player` keyed by `player_id`, or `agent` keyed by `(demo_id)`.
- **`FeatureView`** — a named group of features from a single source, keyed by entities; carries `schema` (`Field`s), `source`, `ttl`, optional `version`.
- **`Field`** — one measurable property: `name` + `dtype`.

```python
from feast import Entity, FeatureView, Field, FileSource
from feast.types import Float32, Int64
from datetime import timedelta

player = Entity(name="player", join_keys=["player_id"])
combat_source = FileSource(
    path="data/player_combat_stats.parquet",
    timestamp_field="event_timestamp",          # required for PIT joins
    created_timestamp_column="created",
)
player_combat_fv = FeatureView(
    name="player_combat", entities=[player], ttl=timedelta(days=1),
    schema=[Field(name="frags_last_30s", dtype=Int64),
            Field(name="accuracy_lg", dtype=Float32),
            Field(name="health", dtype=Int64)],
    source=combat_source, online=True,
)
```
dtypes: `Int32/64`, `Float32/64`, `String`, `Bytes`, `Bool`, `UnixTimestamp`, plus `Array`, `Map`, `Struct`, `Json`.

### 3.2 `feature_store.yaml` registry & store config

```yaml
project: fps_bot
registry: data/registry.db        # catalog of feature DEFINITIONS
provider: local
online_store:                     # low-latency serving (live per-tick cache)
    type: redis
    connection_string: "localhost:6379"
offline_store:                    # historical (demo/replay corpus)
    type: file                    # or duckdb | bigquery | snowflake | ...
entity_key_serialization_version: 2
```
- **Registry** = catalog of definitions (Entities/FeatureViews/Fields), distinct from data. `feast apply` writes Python defs into it.
- **Offline store** = historical features for training (high-volume analytical, PIT joins).
- **Online store** = low-latency single-row lookups for inference.

### 3.3 Materialization

Copy latest feature values offline → online so inference reads them at ms latency (`feast materialize` / `materialize-incremental`). For the bot: offline = historical demo/replay corpus; online = the live per-tick feature cache the bot polls during a match.

### 3.4 Point-in-time correctness / PIT (as-of) joins — the leakage guard

Given an **entity dataframe** of `(entity_key, event_timestamp)` label rows, a PIT join attaches feature values where `feature.event_timestamp <= label.event_timestamp`, selecting the most recent eligible row (within `ttl`). Without the `<=` constraint, future values leak — the documented symptom is offline AUC inflated **5–20%** while online performance collapses.

```python
training_df = store.get_historical_features(
    entity_df=labels_df,            # has event_timestamp column
    features=["player_combat:frags_last_30s", "player_combat:accuracy_lg"],
).to_df()
```

**QW relevance:** when you mine imitation rows from MVDs — e.g. "label = did the player frag in the next 2 s" at tick *t* — **every feature must be computed from game state at tick ≤ t**. A PIT join (Feast `get_historical_features`, or a DuckDB `ASOF JOIN` over the silver per-tick tables) enforces this mechanically instead of by hand. This is the single most important correctness control for the imitation track.

### 3.5 Online/offline parity (training-serving skew)

**Training-serving skew** = any discrepancy between features at training vs serving, usually from two code paths. Cure: define each transform **once** (the registry §3.6), use it for both offline mining and online inference. Careful timestamp management + the as-of join removes leakage as a skew source.

### 3.6 Lightweight feature-registry pattern (when Feast is overkill)

For a single-agent bot, a full feature store is usually overkill. Keep the *idea* — a **versioned declarative registry** pairing each feature with `name, dtype, source, transform, version` — so the same spec drives offline replay-mining and the live online encoder (parity, minus the infra). Example schema (the *shape* is a design recommendation; conventions follow the cited Feast/registry sources):
```yaml
registry_version: 3                  # bump on any breaking schema change
entity: { name: agent, join_keys: [demo_id] }
features:
  - name: health_norm
    dtype: float32
    source: game_state.player.health
    transform: "clip(health, 0, 250) / 250.0"          # online==offline identical
    version: 1
    range: [0.0, 1.0]
  - name: enemy_bearing_sincos
    dtype: float32[2]
    source: derived
    transform: "[sin(atan2(dy, dx)), cos(atan2(dy, dx))]"   # §4.3
    version: 2                          # v1 was raw radians — deprecated
    deprecated_versions: [1]
  - name: nearest_enemy_dist_norm
    dtype: float32
    source: derived
    transform: "min_dist(player, enemies) / map_diagonal"
    version: 1
```

### 3.7 Feature versioning

Two axes: (1) **per-Field/per-FeatureView `version`** — bump when a transform changes so old runs stay reproducible and the online encoder + model agree on layout; (2) **registry-level version** in git — the model artifact records *which registry version + which feature versions* it trained against so serving can refuse a mismatch. (`[unverified]` that Feast auto-enforces model↔feature-version compat — wire this check yourself.)

---

## 4. Spatial / Positional Representation for Agents

The substrate that most affects an FPS bot. Two families: **vector/entity-list** (per-entity feature vectors processed as a set) and **spatial-plane** (multi-channel 2D grids processed like an image). Landmark systems mix them.

### 4.1 Normalized world coordinates

Raw Quake units (thousands) destabilize training. Normalize against known map bounds:
- to **[0,1]**: `x_norm = (x − x_min) / (x_max − x_min)`
- to **[−1,1]**: `x_norm = 2·(x − x_min)/(x_max − x_min) − 1`

But absolute position generalizes poorly across maps — modern systems prefer egocentric relative vectors (§4.2). Keep absolute normalized coords as an *auxiliary* feature, not the primary spatial signal.

### 4.2 Egocentric relative vectors (agent's own frame)

Give each entity's position **relative to the agent, rotated into the agent's facing frame** φ:
```
d_world = p_e − p_a                          # relative offset, world frame
dx_ego =  cos(φ)*d_world.x + sin(φ)*d_world.y
dy_ego = -sin(φ)*d_world.x + cos(φ)*d_world.y
```
This makes the policy translation- and rotation-invariant: "enemy 200u ahead-left" looks identical regardless of map location or facing. OpenAI Five used semantic relative features ("relative positions and velocities", "distance to me") rather than pixels/absolute coords for exactly this generalization + dimensionality win.

### 4.3 Polar encoding & WHY angles must be (sin, cos)

Encode the egocentric offset as distance + bearing, bearing as a `(sin, cos)` pair — never a raw angle:
```
dist    = sqrt(dx_ego^2 + dy_ego^2)
theta   = atan2(dy_ego, dx_ego)
feature = [ dist / map_diagonal,  sin(theta),  cos(theta) ]    # 3 numbers
```
**Why:** an angle is periodic (`α ≡ α + 2kπ`), so a raw scalar has a false discontinuity at the 0/2π wrap — to a plain net, 1° and 359° look maximally far apart though 2° apart. Mapping onto the unit circle via `(cos, sin)` removes it: nearby angles → nearby 2D points. Empirical gap is large — a cube-rotation benchmark: `(cos,sin)` MSE **6.53 / 92% acc@5°** vs raw-angle **1057.69 / 20.5%**. Apply to *any* periodic quantity: heading, view pitch/yaw, projectile direction.

### 4.4 Occupancy / voxel grids & multi-channel spatial planes

Discretize the map (or a window around the agent) into `H×W` and stack **one channel per semantic class** → a `C×H×W` tensor for a CNN, exactly like an image where "colors" are entity types. Real example: a 240×240 map with 6 channels (obstacle, explored, one-hot agent pos, trajectory, one-hot goal, goal-history). Occupancy grids are formally binary presence per cell, optionally split static/dynamic/agent.

**FPS plane stack (egocentric, centered on agent):** `[walls, enemies, teammates, items/weapons, projectiles, last-known-enemy-decay, self]`. Cheap, gives the CNN local spatial structure for free. Precompute and store as Zarr/HDF5 (§1.3) if you go this route.

### 4.5 Distance fields / heat maps

A channel can hold a continuous **distance field** (cell = distance to nearest wall/enemy) or a decaying **heat map** (recent activity, last-known-position confidence that decays over time) — smooth gradients to follow + built-in memory of stale info. Continuous-valued occupancy grids feed CNNs directly. (`[unverified]` that any *published FPS* agent used an explicit signed-distance-field channel — standard technique, no FPS-specific primary citation found.)

### 4.6 Waypoint / navigation-graph embeddings

When the map is naturally a graph (nav-mesh waypoints + traversable edges), represent space topologically: nodes = positions, edges = connectivity, and macro-actions = "go to node N." Node embeddings can be learned with **node2vec** (preserves local proximity + global structure). Well-suited to QW item-control routing (controlling RA/YA/Quad timings is fundamentally a graph-routing problem).

### 4.7 AlphaStar — entity-transformer + spatial-CNN + LSTM (mix both)

- **Entity encoder (set/transformer):** an **entity list** up to ~512 units, each a 1-D attribute vector → **3-layer Transformer, 2-head self-attention, 128-dim heads, 1024-dim FF** → ReLU → 1×1 conv (256 ch) → `entity_embeddings`. Permutation-equivariant → handles a variable-count *set* of units.
- **Spatial encoder (CNN):** minimap as multi-channel planes on a **128×128 grid** → ResNet-style CNN.
- **Scalar encoder:** global state (resources, time, upgrades) as plain vectors.
- **Fusion + core:** concat entity + spatial + scalar → **deep LSTM** for temporal memory.

Takeaway: units/items/enemies → entity-list + transformer; map geometry → spatial planes + CNN; fuse → recurrent core.

### 4.8 OpenAI Five — per-unit vectors, max-pool over a variable set, LSTM

No pixels — purely semantic per-unit vectors. ~**16,000 inputs** per hero/step (up to ~200 friendly units, enemy units in vision, creeps, buildings, projectiles, runes + global scalars). **Variable count:** each unit's vector → shared per-unit MLP ("Process Set", weights shared) → **max-pool across units** → fixed-size vector (permutation-invariant, count-agnostic, no masking). Relative positions/velocities + "distance to me" features. Core = **single-layer 4096-unit LSTM** (~84% of params); **attention over unit embeddings** for target selection.

Takeaway: per-entity MLP + max-pool (or attention) is the cheap, robust way to ingest a variable, unordered set of enemies/pickups.

### 4.9 DeepMind Capture-the-Flag — Quake III Arena (directly relevant)

FTW agents played CTF on procedurally-generated Quake III maps, **directly from raw RGB pixels** (no privileged state). Input = pixel frames → **CNN**. Core = **two LSTMs on fast & slow timescales**, coupled through a **variational** objective (hierarchical RNN for short+long horizons). Each agent learns its **own internal reward** via population-based training; randomized maps prevent layout memorization. Beat 2-human teams by ~16 captures.

**Contrast for the QW bot:** FTW chose *pure pixels* (learn vision from scratch). A QuakeWorld bot with MVD/engine state can use the far cheaper **semantic entity-vector** route (OpenAI Five style) — generalization + sample-efficiency without learning vision. (Granular FTW layer specs live in the Science paper, not the accessible blog — `[unverified]` on exact resolution/CNN depth; architecture *shape* confirmed.)

### 4.10 Entity-list (set/transformer) vs spatial-plane (CNN) — tradeoffs + variable counts

| | Entity-list / set (MLP+pool or transformer) | Spatial planes (CNN grid) |
|---|---|---|
| Input | `N×F`, N variable | `C×H×W` fixed |
| Strength | exact per-entity attributes, precise relative geometry, no resolution loss; permutation-invariant | local spatial structure cheaply; fixed output regardless of count |
| Weakness | must encode geometry explicitly; pooling can lose "where exactly" | resolution caps precision; identity blurred into channels |
| Used by | OpenAI Five (MLP+max-pool), AlphaStar entity encoder (transformer) | AlphaStar minimap, GridNet, exploration agents, FTW (pixels) |

**Variable entity counts — two mechanisms:**
1. **Pooling** (OpenAI Five): per-entity shared MLP → max/mean/sum-pool → fixed vector. Permutation-invariant, count-agnostic, no masking.
2. **Pad + mask** (transformer/AlphaStar): pad to a fixed max length (e.g. 512); supply a **padding mask** adding −∞ to attention logits for padded slots **before softmax** → padded entities get zero weight. Content-based, permuted with the input, preserves set permutation-invariance.

**Recommended substrate for the QW bot (synthesis):**
- Per-entity vectors (enemies, teammates, items, projectiles), each egocentric `[dist/diag, sinθ, cosθ, rel_vel…, type_onehot, health_norm, respawn_remaining_norm, available_now, …]` → shared MLP → max-pool and/or small transformer with pad+mask.
- A small egocentric multi-channel occupancy/distance-field stack for map geometry + last-known positions → tiny CNN.
- Optional nav-graph node2vec embedding for item-control routing.
- Concatenate → recurrent core (LSTM/GRU) — all three landmark systems used recurrence.

---

## 5. Time & Event Features

### 5.1 Countdown timers / cooldowns (item respawn, the FPS staple)

Canonical pattern = **two features per timed entity** — normalized remaining time + binary availability:
```
t_remaining    = max(0, respawn_at − t_now)         # seconds until available
remaining_norm = t_remaining / T                     # [0,1]; 0 = available now
available_now  = 1.0 if t_remaining == 0 else 0.0
```
Notes (standard practice; `[unverified]` as a single-source rule): emit **both** (the flag is a clean step signal; the continuous value gives anticipation/lead-time); clamp to `[0, T]`; if respawn time is unobserved emit a third **"unknown" flag** rather than a sentinel number. For QW this is precisely how you encode RA/YA/Mega-health/Quad timers — the heart of item control.

### 5.2 Time-since-event features

Mirror of the countdown (last damage taken, last frag, last pickup). Raw elapsed is heavy-tailed → `log1p` or cap-and-normalize:
```
elapsed       = t_now − t_last_event
elapsed_norm  = min(elapsed, CAP) / CAP
elapsed_log   = log1p(elapsed)
seen_recently = 1.0 if elapsed < WINDOW else 0.0
```

### 5.3 Cyclic time encoding (sin/cos) — exact formula

```
x_sin = sin(2π · t / period)
x_cos = cos(2π · t / period)
```
e.g. `hour_sin/cos` with period 24, periodic spawn-phase with period T. **Why both:** sine alone is symmetric — two times within a cycle share a sine value (a horizontal line crosses twice); cosine is phase-offset → unique 2D coordinate per phase, and 23:00↔00:00 are correctly *close* on the circle (vs 23 units apart as integers). (NVIDIA notes Radial Basis Functions can beat sin/cos on some benchmarks — MAE 0.37 RBF vs 0.64 sin/cos — but sin/cos is the standard low-dim choice for pure periodic timers.)

### 5.4 Game clock / match time normalization

```
match_progress = t_elapsed / match_duration         # [0,1] fixed-length matches
time_remaining = (match_duration − t_elapsed) / match_duration
```
For overtime/variable-length, prefer min-max against an expected cap + an `overtime` flag rather than dividing by an unknown denominator.

### 5.5 "Time-to-reach" / availability (ETA) — composite features

Fold geometry + kinematics into one decision-relevant scalar (lets the net skip recomputing it):
```
eta      = distance_to_item / max(player_speed, ε)   # seconds to arrive
eta_norm = min(eta, CAP) / CAP

# the high-value timing feature:
will_be_up_on_arrival = 1.0 if eta >= t_remaining else 0.0
slack                 = (eta − t_remaining) / T      # signed; >0 up on arrival
```
`will_be_up_on_arrival` directly encodes the item-contest decision a QW player makes constantly; `slack` carries the magnitude. Always clamp (the `max(speed, ε)` guard prevents blow-up as speed→0). (Building blocks — availability masks, composite features — are sourced; the exact ETA recipe is an engineering recommendation, `[unverified]`.)

---

## 6. Normalization & Standardization — the calculations

### 6.1 Z-score standardization
```
z = (x − μ) / σ          # μ, σ from TRAINING set; sklearn uses biased std (ddof=0)
```
Use for roughly-Gaussian features; default for linear/logistic/SVM/NN. Outlier-sensitive (mean/std not robust).

### 6.2 Min-max scaling
```
x' = (x − min) / (max − min)        # maps training range to [0,1]
```
Use for bounded inputs / known range / no outliers (pixels, capped distances). Highly outlier-sensitive — one extreme compresses everything.

### 6.3 Robust scaling
```
x' = (x − median) / IQR             where IQR = Q3 − Q1 = P75 − P25
```
Use for features with significant outliers (frag counts, damage totals, ping). Median + IQR are far less sensitive to extremes. Quantile range configurable (default 25/75).

### 6.4 Log / sqrt / log1p / Box-Cox (skewed, heavy-tailed)
```
sqrt:    x' = √x            # moderate right-skew; safe on zeros; counts
log:     x' = ln(x)         # strong right-skew; requires x > 0
log1p:   x' = ln(1 + x)     # like log, safe at x = 0
box-cox: x' = (x^λ − 1)/λ (λ≠0); ln(x) (λ=0)    # fitted λ; requires x > 0
```
Box-Cox special cases: λ=0→ln, λ=0.5→√, λ=−0.5→1/√. Pathological tails → rank/quantile transform. **Pipeline order:** transform first (fix shape), *then* z-score / robust-scale.

### 6.5 Angles → (sin, cos)
```
a_sin = sin(θ);  a_cos = cos(θ)     # θ in radians
```
Same rationale as §5.3/§4.3 — wrapping quantities must not be raw scalars (false discontinuity at the wrap). The pair preserves angular distance and is bounded `[−1,1]`.

### 6.6 Per-feature method selection

| Feature type | Method | Why |
|---|---|---|
| Roughly Gaussian continuous | Z-score | Matches estimator assumptions |
| Bounded / known range, no outliers | Min-max | Fixed [0,1], preserves shape |
| Heavy outliers / fat tails | Robust (median/IQR) | Robust to extremes |
| Right-skewed counts / durations | log1p/sqrt → then z-score | Symmetrize before scaling |
| Cyclic (time, periodic timers) | sin/cos pair | Remove wraparound |
| Angles / headings | sin/cos pair | Preserve angular distance |
| Already-normalized timers (§5.1) | divide by period | Already [0,1] |
| Binary flags | leave 0/1 | No scaling needed |

### 6.7 CRITICAL — fit on TRAIN ONLY, freeze, reapply

Compute `μ, σ, min, max, median, IQR` from the **training split only**, freeze, apply identical frozen stats at val/test/inference. scikit-learn is explicit: *"the average should be the average of the train subset, not all the data… Never include test data when using `fit`/`fit_transform`… Using all the data can result in overly optimistic scores."*
```python
X_train, X_test, y_train, y_test = train_test_split(X, y, random_state=42)
scaler = StandardScaler()
X_train_s = scaler.fit_transform(X_train)   # learns μ,σ from TRAIN only
X_test_s  = scaler.transform(X_test)         # reuses frozen μ,σ
```
**Why full-data fit leaks:** the scaler's stats embed the test distribution → test no longer held out → optimistic scores, and a train/inference distribution mismatch in production. Robust fix: a `Pipeline` so the right method runs on the right subset (also correct under cross-validation).

### 6.8 Welford's online algorithm — exact update equations

Single-pass, numerically stable streaming mean/variance:
```
init: count = 0, mean = 0, M2 = 0
for each new x:
    count  += 1
    delta   = x − mean
    mean   += delta / count
    delta2  = x − mean            # uses the UPDATED mean
    M2     += delta * delta2
variance_population = M2 / count
variance_sample     = M2 / (count − 1)
std                 = sqrt(variance)
```
Equation form:
```
x̄ₙ  = x̄ₙ₋₁ + (xₙ − x̄ₙ₋₁) / n
M₂,ₙ = M₂,ₙ₋₁ + (xₙ − x̄ₙ₋₁)·(xₙ − x̄ₙ)
```
Avoids the catastrophic cancellation of the naive `E[x²]−E[x]²`. Essential when feature tables are too large to hold in RAM — stream the training shards once and accumulate.

### 6.9 Chan parallel variant — combining partial stats across shards

Merge two independently-computed partials A and B (per-shard / per-worker):
```
n_AB    = n_A + n_B
δ       = mean_B − mean_A
mean_AB = mean_A + δ * (n_B / n_AB)
M2_AB   = M2_A + M2_B + δ² * (n_A * n_B / n_AB)
variance_AB = M2_AB / n_AB                       # or /(n_AB − 1) for sample
```
Associative → tree-reduce arbitrarily many shards. This is how you compute global training stats over a sharded WebDataset/Parquet corpus in parallel.

### 6.10 Per-group (per-map) vs global normalization

- **Per-group (per-map/player/mode) pro:** removes systematic per-group offsets (a fast map inflates all movement features); features comparable across groups. **Con:** fewer samples → noisier stats; needs an unseen-group fallback; store/route N stat sets.
- **Global pro:** max data per estimate, one artifact, trivial inference. **Con:** entangles group-specific distributions ("should be used cautiously… entangles representations").
- Analogous GroupNorm tradeoff: smaller groups → more diverse features but less stable; larger → stable but lower capacity.
- **Rule:** per-group *only* when groups have genuinely different scales **and** each has enough samples for stable stats; otherwise global + add the group identity as a feature. For the QW bot, **per-map normalization of spatial/positional features is justified** (map bounds and item geometry differ), but normalize behavioral/combat features globally with `map_id` as a feature.

### 6.11 Versioned stats artifact + reapply at inference

**(a) joblib the fitted object** — `joblib.dump(scaler, "scaler.pkl")` / `joblib.load(...).transform(X_new)` (efficient for large NumPy arrays); save the **whole Pipeline** so scaling can't drift from the model.

**(b) Hand-rolled versioned JSON** — language-agnostic, inspectable, diffable; **preferred when inference runs in C/Go/JS** (e.g. a game client / ezQuake-side bot). Example:
```json
{
  "artifact_version": "2.1.0",
  "fitted_on": "train_split_2026-06-01",
  "n_samples": 184320,
  "group": "per_map",
  "features": {
    "health":            {"method": "minmax",        "min": 0.0, "max": 250.0},
    "frags":             {"method": "log1p_zscore",  "mean": 1.83, "std": 0.97},
    "respawn_remaining": {"method": "divide_period", "period": 120.0},
    "yaw":               {"method": "sincos"},
    "ping_ms":           {"method": "robust",        "median": 38.0, "iqr": 22.0}
  }
}
```
Apply the same frozen numbers at inference exactly as at training. **Tie the artifact hash to the model version** so an incompatible scaler/model pair can never deploy together.

---

## 7. Splits, Leakage & Versioning

### 7.1 Grouped / group-aware splits (prevent leakage)

When rows cluster into groups (episode/demo/player/map) the same group must **never** straddle train/test:
- **`GroupKFold`** — "ensures the same group is not represented in both training and testing sets."
- **`GroupShuffleSplit`** — randomized split by a provided group.
```python
from sklearn.model_selection import GroupKFold
gkf = GroupKFold(n_splits=5)
for train_idx, test_idx in gkf.split(X, y, groups=demo_id):
    ...   # no demo_id on both sides of any fold
```
Critical for imitation/time-series: consecutive frames of one episode are near-duplicates — splitting by *frame* leaks the test episode into training and inflates scores. **Split by `demo_id` (and ideally also hold out whole `player_id`s and whole `map`s for generalization tests).**

### 7.2 Temporal splits for time-series

`TimeSeriesSplit` — train on past, test on future; "first k folds train, (k+1)th test… always train on past, test on future." Plain shuffling causes look-ahead bias.

### 7.3 Leakage sources & prevention

| Source | Symptom | Prevention |
|---|---|---|
| Preprocessing fit on full data | Optimistic CV; train/infer mismatch | Fit transformers in a Pipeline inside the split (§6.7) |
| Same group in train + test | Memorization masquerades as generalization | GroupKFold/GroupShuffleSplit (§7.1) |
| Future rows in training | Look-ahead bias | TimeSeriesSplit (§7.2) / PIT joins (§3.4) |
| Target-derived feature | Near-perfect train score | Audit features; exclude post-outcome signals |

### 7.4 Dataset & schema versioning — DVC vs lakeFS

- **DVC** — Git-adjacent; version tiny `.dvc` pointer files in Git, store large artifacts in a remote (S3/GCS/SSH/local). Handles tens of thousands of files well; degrades at hundreds of millions of objects. Use for model-centric teams, reproducible experiments tied to a repo, `dvc repro` pipelines, budget/simplicity.
- **lakeFS** — git-like over object storage; branches/commits are first-class on the storage namespace (branch a 200 TB dataset in seconds), scales to billions of objects. Use for multi-team isolation at scale, governance/audit, big query engines.
- **Hybrid** — DVC for model artifacts/pipelines, lakeFS for raw/curated lake data; pin DVC dataset versions that reference a lakeFS commit hash.

For a single-author QW bot project, **DVC is the right call** (plain S3/local remote, no infra).

### 7.5 Lineage / reproducibility

Pin **code + data + stats** together: `git SHA + dataset commit/.dvc hash + scaler artifact version (§6.11)`. DVC keeps provenance beside the code; the normalization JSON pins the transform. A run is reproducible iff all three are recorded in the model artifact.

### 7.6 Schema validation

**pandera** (schema-as-code; raises on violation):
```python
import pandera.pandas as pa
schema = pa.DataFrameSchema({
    "tick":   pa.Column(int,   checks=pa.Check.greater_than_or_equal_to(0), nullable=False),
    "health": pa.Column(int,   checks=pa.Check.between(0, 250), nullable=False, coerce=True),
    "yaw":    pa.Column(float, checks=pa.Check.between(-3.1416, 3.1416), nullable=False),
    "map":    pa.Column(str,   checks=pa.Check.isin(["dm3","aerowalk","dm2"]), nullable=False),
})
validated = schema.validate(df)     # raises SchemaError on violation
```
**Great Expectations** — expectation *suites* of declarative assertions + human-readable data docs (exact suite API `[unverified]`, not pulled from primary source here).
**TFDV** — production validation in TFX: `infer_schema()` (auto initial schema from train stats), anomaly detection vs schema, **skew** (schema/feature/distribution incl. training-serving), **drift** (L-∞ distance for categorical, approx Jensen-Shannon for numeric).
**Selection:** pandera for in-process pandas pipelines; Great Expectations for cross-team suites + data docs; TFDV for automatic stats + skew/drift monitoring in TFX.

---

## 8. A Concrete Reference Layout (worked example)

Ties everything together for the QW bot. Adapt names freely.

### 8.1 Directory layout
```
qwbot-data/
  bronze/
    demos/map=dm3/dt=2026-06-01/*.mvd
    events_raw/map=dm3/dt=2026-06-01/*.jsonl
  silver/
    player_ticks/map=dm3/dt=2026-06-01/*.parquet   # one row per (demo_id, player_id, tick)
    item_events/map=dm3/dt=2026-06-01/*.parquet    # pickups + respawns
  gold/
    features/agent_features/map=dm3/dt=2026-06-01/*.parquet   # PIT feature table, zstd
    training/
      imitation/train/shard-{000000..000511}.tar    # WebDataset of windowed sequences
      imitation/val/shard-{000000..000031}.tar
      rl/episodes.hdf5                               # Minari-style offline-RL store
    norm/normalization_stats_v2.json                 # frozen stats (§6.11)
    registry/feature_registry_v3.yaml                # feature declarations (§3.6)
  catalog.duckdb                                     # relational catalog (§8.2)
  dvc.yaml + *.dvc                                   # data versioning (§7.4)
  schemas/player_ticks.pandera.py                    # schema validation (§7.6)
```

### 8.2 Relational catalog DDL (DuckDB/SQLite)
```sql
CREATE TABLE maps (
    map_id        INTEGER PRIMARY KEY,
    name          TEXT NOT NULL UNIQUE,        -- 'dm3', 'aerowalk'
    x_min REAL, x_max REAL, y_min REAL, y_max REAL, z_min REAL, z_max REAL,
    diagonal      REAL                          -- precomputed map_diagonal for §4.3
);

CREATE TABLE players (
    player_id     INTEGER PRIMARY KEY,
    handle        TEXT NOT NULL,                -- for per-player style models
    UNIQUE(handle)
);

CREATE TABLE demos (
    demo_id       INTEGER PRIMARY KEY,
    path          TEXT NOT NULL UNIQUE,         -- bronze/demos/...mvd
    map_id        INTEGER REFERENCES maps(map_id),
    recorded_at   TIMESTAMP,
    duration_s    REAL,
    tickrate      INTEGER,                       -- e.g. 77 (QW physics) / sampled rate
    sha256        TEXT NOT NULL
);

CREATE TABLE episodes (                          -- a contiguous trajectory segment
    episode_id    INTEGER PRIMARY KEY,
    demo_id       INTEGER REFERENCES demos(demo_id),
    player_id     INTEGER REFERENCES players(player_id),
    start_tick    INTEGER NOT NULL,
    end_tick      INTEGER NOT NULL,
    n_steps       INTEGER NOT NULL,
    total_reward  REAL,                          -- for offline RL / RTG precompute
    split         TEXT CHECK(split IN ('train','val','test'))   -- grouped split assignment
);

CREATE TABLE feature_partitions (                -- manifest of gold feature files
    partition_id  INTEGER PRIMARY KEY,
    map_id        INTEGER REFERENCES maps(map_id),
    dt            DATE NOT NULL,
    path          TEXT NOT NULL UNIQUE,
    n_rows        INTEGER,
    registry_version INTEGER,                     -- which feature_registry it was built with
    norm_artifact_version TEXT                     -- which normalization_stats it assumes
);
```
Grouped split is assigned at the **episode** level keyed by `demo_id`/`player_id` so no demo straddles splits (§7.1). PIT joins (§3.4) run in DuckDB over `silver/player_ticks` + `silver/item_events`.

### 8.3 Parquet feature-table schema (`gold/features/agent_features`)
One row per `(demo_id, player_id, tick)`. Stored values are **already transformed** per the registry; raw values stay in silver.
```
event_timestamp        TIMESTAMP   # for PIT joins
demo_id                INT64
player_id              INT32
tick                   INT32
map_id                 INT16
# --- self state (egocentric reference) ---
pos_x_norm             FLOAT       # per-map min-max (§4.1), auxiliary
pos_y_norm             FLOAT
pos_z_norm             FLOAT
vel_x_z                FLOAT       # z-scored velocity components
vel_y_z                FLOAT
vel_z_z                FLOAT
speed_norm             FLOAT       # robust-scaled
yaw_sin                FLOAT       # (sin,cos) heading (§4.3/§6.5)
yaw_cos                FLOAT
pitch_sin              FLOAT
pitch_cos              FLOAT
health_norm            FLOAT       # /250 (§3.6)
armor_norm             FLOAT
# --- nearest-enemy egocentric polar (§4.2/4.3) ---
enemy_dist_norm        FLOAT       # /map_diagonal
enemy_bearing_sin      FLOAT
enemy_bearing_cos      FLOAT
enemy_rel_vx           FLOAT
enemy_rel_vy           FLOAT
enemy_visible          FLOAT       # 0/1
# --- item timing (one block per tracked item; §5.1/5.5) ---
ra_remaining_norm      FLOAT       # /T  (RedArmor)
ra_available_now       FLOAT       # 0/1
ra_eta_norm            FLOAT
ra_up_on_arrival       FLOAT       # 0/1  will_be_up_on_arrival
# ... (ya_*, mega_*, quad_* analogous) ...
# --- time ---
match_progress         FLOAT       # [0,1] (§5.4)
# --- label (imitation target; computed from tick<=t only via PIT) ---
action_id              INT32       # discretized action (or separate action vector cols)
rtg                    FLOAT       # return-to-go for DT-style training (§2.5)
```
Partition: `map=<name>/dt=<date>`. Compression: zstd. Variable-count entity lists (all enemies/items, not just nearest) are better stored as a separate per-tick array column or in the Zarr/HDF5 spatial-plane store (§4.4) and joined by `(demo_id, player_id, tick)`.

### 8.4 Feature-registry YAML (`gold/registry/feature_registry_v3.yaml`)
```yaml
registry_version: 3
entity: { name: agent, join_keys: [demo_id, player_id, tick] }
normalization_artifact: norm/normalization_stats_v2.json
defaults: { group: per_map }          # spatial features normalized per-map
features:
  - {name: health_norm, dtype: float32, source: player.health,
     transform: "clip(health,0,250)/250.0", version: 1, group: global, range: [0,1]}
  - {name: speed_norm, dtype: float32, source: derived,
     transform: "robust(norm(vel))", version: 1, group: per_map}
  - {name: yaw_sincos, dtype: float32[2], source: player.yaw,
     transform: "[sin(yaw), cos(yaw)]", version: 1, group: none}
  - {name: enemy_bearing_sincos, dtype: float32[2], source: derived,
     transform: "[sin(atan2(dy,dx)), cos(atan2(dy,dx))]", version: 2,
     deprecated_versions: [1], group: none}
  - {name: enemy_dist_norm, dtype: float32, source: derived,
     transform: "min_dist(player,enemies)/map_diagonal", version: 1, group: none}
  - {name: ra_remaining_norm, dtype: float32, source: items.ra,
     transform: "clip(respawn_at-t_now,0,T)/T", version: 1, group: none, params: {T: 120}}
  - {name: ra_up_on_arrival, dtype: float32, source: derived,
     transform: "1.0 if (dist/max(speed,eps)) >= (respawn_at-t_now) else 0.0",
     version: 1, group: none}
```
The **same `transform` strings** drive offline mining and the live online encoder → online/offline parity (§3.5).

### 8.5 Normalization-stats JSON (`gold/norm/normalization_stats_v2.json`)
```json
{
  "artifact_version": "2.0.0",
  "registry_version": 3,
  "fitted_on": "train_split_2026-06-01",
  "split_def": "grouped_by_demo_id",
  "n_samples": 4821990,
  "global": {
    "health":  {"method": "minmax", "min": 0.0, "max": 250.0},
    "frags":   {"method": "log1p_zscore", "mean": 1.83, "std": 0.97}
  },
  "per_map": {
    "dm3": {
      "vel_x": {"method": "zscore", "mean": 2.1,  "std": 310.4},
      "vel_y": {"method": "zscore", "mean": -0.4, "std": 305.9},
      "speed": {"method": "robust", "median": 320.0, "iqr": 210.0},
      "pos_x": {"method": "minmax", "min": -1024.0, "max": 2880.0}
    },
    "aerowalk": { "...": "..." }
  },
  "sincos": ["yaw", "pitch", "enemy_bearing"],
  "divide_period": {"ra_remaining": 120.0, "ya_remaining": 120.0, "quad_remaining": 60.0}
}
```
Computed from the **train split only** (§6.7), via Welford/Chan over shards (§6.8–6.9), frozen, and re-applied byte-identically at inference (§6.11). A model artifact records `(git_sha, dvc_dataset_hash, artifact_version "2.0.0", registry_version 3)` for full reproducibility (§7.5).

### 8.6 End-to-end flow
1. **Ingest** MVDs → `bronze/demos`; parse per-tick → `bronze/events_raw`. Catalog each in `demos`.
2. **Curate** → `silver/player_ticks` + `silver/item_events`; validate with the pandera schema (§7.6); delimit `episodes`; assign **grouped split** by `demo_id` (§7.1).
3. **Feature-build** per `feature_registry_v3.yaml` using **PIT joins** (DuckDB `ASOF JOIN` over silver tables, tick ≤ t) → `gold/features` Parquet. No future leakage (§3.4).
4. **Fit normalization** on the **train split only**, streaming Welford/Chan over shards → `normalization_stats_v2.json` (§6).
5. **Window** episodes into fixed-K sequences (pad+mask at boundaries; precompute RTG) → `gold/training/imitation/*.tar` (WebDataset) for imitation, and `gold/training/rl/episodes.hdf5` (Minari-style) for offline RL (§2).
6. **Version** the dataset with DVC; pin `(git_sha, dvc_hash, artifact_version, registry_version)` in the model card (§7.4–7.5).
7. **Inference:** the live bot reads the **same** registry transforms + **same** frozen stats JSON, applying identical normalization → zero training-serving skew (§3.5, §6.11).

---

## Sources

**Storage & formats**
- [Parquet File Anatomy (dev.to)](https://dev.to/databro/apache-parquet-file-anatomy-row-groups-column-chunks-pages-and-metadata-explained-4ebg) — row groups/column chunks/pages/footer stats.
- [ClickHouse — Parquet internals](https://clickhouse.com/blog/apache-parquet-clickhouse-local-querying-writing-internals-row-groups) and [Columnar storage formats](https://clickhouse.com/resources/engineering/columnar-storage-formats) — vendor deep-dive; Arrow/Parquet interop.
- [Estuary — Parquet for Data Engineers](https://estuary.dev/blog/apache-parquet-for-data-engineers/) — partitioning + predicate pushdown.
- [Snappy vs Zstd in PyArrow (dev.to)](https://dev.to/ldsands/snappy-vs-zstd-for-parquet-in-pyarrow-9g0) and [e6data Snappy vs Zstd](https://www.e6data.com/blog/fast-writes-apache-iceberg-snappy-vs-zstd) — compression tradeoffs + small-files problem.
- [apxml — Compression algorithms](https://apxml.com/courses/intro-data-lake-architectures/chapter-2-file-formats-and-optimization/compression-algorithms) — Snappy/Zstd speed/ratio.
- [alimanfoo — To HDF5 and beyond](http://alimanfoo.github.io/2016/04/14/to-hdf5-and-beyond.html) and [Earthmover — What is Zarr](https://www.earthmover.io/blog/what-is-zarr/) — foundational Zarr-vs-HDF5.
- [pythonspeed — mmap vs Zarr/HDF5](https://pythonspeed.com/articles/mmap-vs-zarr-hdf5/) — access-pattern guidance.
- [TensorFlow — TFRecord & tf.train.Example](https://www.tensorflow.org/tutorials/load_data/tfrecord) — authoritative TFRecord schema + sharding guidance.
- [webdataset GitHub](https://github.com/webdataset/webdataset) and [NVIDIA DALI webdataset reader](https://docs.nvidia.com/deeplearning/dali/user-guide/docs/operations/nvidia.dali.fn.readers.webdataset.html) — tar sharding, brace expansion, shuffle, shard sizing.
- [DataCamp — DuckDB vs SQLite](https://www.datacamp.com/blog/duckdb-vs-sqlite-complete-database-comparison) and [MotherDuck — DuckDB vs SQLite](https://motherduck.com/learn/duckdb-vs-sqlite-databases/) — OLAP/OLTP split, benchmarks.
- [KDnuggets — Python+Parquet+DuckDB](https://www.kdnuggets.com/building-your-modern-data-analytics-stack-with-python-parquet-and-duckdb) — DuckDB-over-Parquet pushdown/projection.
- [Databricks — Medallion Architecture](https://www.databricks.com/blog/what-is-medallion-architecture) and [Microsoft Learn — Medallion](https://learn.microsoft.com/en-us/azure/databricks/lakehouse/medallion) — bronze/silver/gold.

**Trajectory / RL standards**
- [Google Research — RLDS blog](https://research.google/blog/rlds-an-ecosystem-to-generate-share-and-use-datasets-in-reinforcement-learning/) and [google-research/rlds GitHub](https://github.com/google-research/rlds) — authoritative step/episode field semantics.
- [TFDS rlu_rwrl catalog](https://www.tensorflow.org/datasets/catalog/rlu_rwrl) — concrete nested-`steps` FeaturesDict.
- [Minari — Dataset Standards](https://minari.farama.org/v0.4.1/content/dataset_standards/) and [Minari GitHub](https://github.com/Farama-Foundation/Minari) — HDF5 group hierarchy, shapes, EpisodeData.
- [D4RL — offline_env.py](https://github.com/Farama-Foundation/D4RL/blob/master/d4rl/offline_env.py) and [D4RL GitHub](https://github.com/Farama-Foundation/D4RL) — get_dataset() keys, qlearning_dataset.
- [Decision Transformer — arXiv 2106.01345](https://arxiv.org/pdf/2106.01345) and [HF DT docs](https://huggingface.co/docs/transformers/en/model_doc/decision_transformer) — RTG, 3K-token context, timestep embeddings.
- [OpenAI VPT](https://openai.com/index/vpt/) and [VPT arXiv 2206.11795 (ar5iv)](https://ar5iv.labs.arxiv.org/html/2206.11795) and [openai/Video-Pre-Training GitHub](https://github.com/openai/Video-Pre-Training) — IDM pattern + numbers + demo storage.
- [MineRL — arXiv 1904.10079](https://arxiv.org/pdf/1904.10079) and [MineRL 0.4 data API](https://minerl.readthedocs.io/en/v0.4.4/api/data.html) — SARS tuples, 20 ticks/s, variable-length boundaries.

**Feature stores & spatial**
- [Feast — Feature view concepts](https://docs.feast.dev/getting-started/concepts/feature-view), [feature_store.yaml](https://docs.feast.dev/reference/feature-repository/feature-store-yaml), [Feature repository](https://docs.feast.dev/reference/feature-repository), [Introduction](https://docs.feast.dev) — official object model, PIT joins, stores.
- [apxml — Point-in-Time Correctness](https://apxml.com/courses/feature-stores-for-ml/chapter-3-data-consistency-quality/point-in-time-correctness) — as-of join mechanics + 5–20% leakage figure.
- [System Overflow — PIT & time travel](https://www.systemoverflow.com/learn/ml-feature-stores/feature-store-architecture/point-in-time-correctness-and-time-travel) and [Medium — training-serving skew with Feast](https://medium.com/@scoopnisker/solving-the-training-serving-skew-problem-with-feast-feature-store-3719b47e23a2) — parity + as-of joins.
- [dswok — Training-serving skew](http://dswok.com/General-ML/Training-serving-skew) and [datasops — Feast overview](https://www.datasops.com/blog/feast-feature-store) — skew concept + store internals.
- [Azure ML registry YAML schema](https://learn.microsoft.com/en-us/azure/machine-learning/reference-yaml-registry?view=azureml-api-2) — versioned-YAML-registry pattern.
- [OpenAI Five paper (PDF)](https://cdn.openai.com/dota-2.pdf), [OpenAI Five blog](https://openai.com/index/openai-five/), [appendix digest](https://kiiiiii123.github.io/2020/05/31/post_67.html) — ~16k inputs, Process Set max-pool, 4096 LSTM, attention unit-selection.
- [mini-AlphaStar — arXiv 2104.06890](https://arxiv.org/pdf/2104.06890) and [Decipher AlphaStar](https://ychai.uk/notes/2019/07/21/RL/DRL/Decipher-AlphaStar-on-StarCraft-II/) — entity transformer + 128×128 spatial planes + LSTM core.
- [DeepMind — Capture the Flag blog](https://deepmind.google/blog/capture-the-flag-the-emergence-of-complex-cooperative-agents/) and [Synced summary](https://medium.com/syncedreview/deepmind-ai-reaches-human-level-performance-in-quake-iii-arena-d2e6c1273441) — Quake III CTF: pixels→CNN, fast/slow LSTM, internal reward.
- [leotac — Encoding rotations for learning](https://leotac.github.io/posts/2019/11/12/encoding-rotations-for-learning/) — sin/cos rationale + MSE 6.53 vs 1057.69 benchmark.
- [DD-PPO PointGoal — arXiv 1911.00357](https://arxiv.org/pdf/1911.00357) — `[r, cosθ, sinθ]` egocentric goal encoding.
- [Grid-Wise Control (GridNet) — ICML 2019](https://proceedings.mlr.press/v97/han19a/han19a.pdf) and [Multi-Agent Visual Exploration — arXiv 2110.05734](https://arxiv.org/pdf/2110.05734) — multi-channel spatial planes (C×H×W).
- [Occupancy Grid Map fundamentals](https://www.emergentmind.com/topics/occupancy-grid-map-ogm) — OGM as binary presence per cell.
- [Topological maps + macro actions — arXiv 2504.18300](https://arxiv.org/html/2504.18300) and [node2vec (ResearchGate)](https://www.researchgate.net/publication/373992830_TOPOLOGICAL_NODE2VEC_ENHANCED_GRAPH_EMBEDDING_VIA_PERSISTENT_HOMOLOGY) — nav-graph embeddings.
- [Attention masks explainer](https://blog.lukesalamone.com/posts/what-are-attention-masks/) and [Permutation-Invariant Set Autoencoders — arXiv 2302.12826](https://arxiv.org/pdf/2302.12826) — pad+mask, set encoders.

**Time / normalization / splits / versioning**
- [NVIDIA — Three Approaches to Encoding Time](https://developer.nvidia.com/blog/three-approaches-to-encoding-time-information-as-features-for-ml-models/) — sin/cos formula + RBF comparison.
- [avanwyk — Encoding Cyclical Features](https://www.avanwyk.com/encoding-cyclical-features-for-deep-learning/) and [feature-engine CyclicalFeatures](https://feature-engine.trainindata.com/en/latest/user_guide/creation/CyclicalFeatures.html) — why both sin and cos.
- [TDS — Cyclical Encoding](https://towardsdatascience.com/cyclical-encoding-an-alternative-to-one-hot-encoding-for-time-series-features-4db46248ebba/) — 23:00↔00:00 wraparound.
- [sklearn — StandardScaler](https://scikit-learn.org/stable/modules/generated/sklearn.preprocessing.StandardScaler.html), [RobustScaler](https://scikit-learn.org/stable/modules/generated/sklearn.preprocessing.RobustScaler.html), [Preprocessing](https://scikit-learn.org/stable/modules/preprocessing.html), [Common pitfalls](https://scikit-learn.org/stable/common_pitfalls.html) — official formulas + leakage guidance.
- [apxml — Log Transformation](https://apxml.com/courses/intro-feature-engineering/chapter-4-feature-scaling-transformation/log-transformation) and [marsja — sqrt/log/Box-Cox](https://www.marsja.se/transform-skewed-data-using-square-root-log-box-cox-methods-in-python/) — skew transforms.
- [Wikipedia — Algorithms for calculating variance](https://en.wikipedia.org/wiki/Algorithms_for_calculating_variance) and [nullbuffer — Welford](https://nullbuffer.com/articles/welford_algorithm.html) — Welford + Chan parallel formulas.
- [Wikipedia — Normalization (ML)](https://en.wikipedia.org/wiki/Normalization_(machine_learning)) — global-normalization entanglement caution.
- [Stack Abuse — Save/Load Scalers](https://stackabuse.com/bytes/how-to-save-and-load-fit-scikit-learn-scalers/) and [ML Journey — Saving sklearn models](https://mljourney.com/saving-and-loading-sklearn-models-the-right-way/) — joblib persistence, save whole Pipeline.
- [MachineLearningMastery — Avoid Data Leakage](https://machinelearningmastery.com/data-preparation-without-data-leakage/) and [nb-data — Understanding Data Leakage](https://www.nb-data.com/p/understanding-data-leakage-in-machine) — fit-on-train-only.
- [sklearn — GroupKFold](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.GroupKFold.html), [GroupShuffleSplit](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.GroupShuffleSplit.html), [Cross-validation](https://scikit-learn.org/stable/modules/cross_validation.html) — grouped + temporal splits.
- [CodeCut — TimeSeriesSplit](https://codecut.ai/cross-validation-with-time-series/) — look-ahead bias.
- [lakeFS — DVC vs Git-LFS vs Dolt vs lakeFS](https://lakefs.io/blog/dvc-vs-git-vs-dolt-vs-lakefs/) — DVC vs lakeFS, scaling, hybrid.
- [pandera — DataFrame Schemas](https://pandera.readthedocs.io/en/stable/dataframe_schemas.html) and [Checks](https://pandera.readthedocs.io/en/stable/checks.html) — schema-as-code.
- [TFDV guide](https://www.tensorflow.org/tfx/guide/tfdv) and [TFDV anomalies](https://www.tensorflow.org/tfx/data_validation/anomalies) — schema inference, skew (3 kinds), drift (L-∞ / JS-divergence).

**Verification notes.** Core formulas (§6.1–6.3, §6.8–6.9, sin/cos in §4.3/§5.3/§6.5) are from primary docs (scikit-learn, Wikipedia, NVIDIA) and reliable. Architecture specifics: OpenAI Five quantitative claims come from the official blog + appendix digest (the PDF is binary); AlphaStar layer dims from the mini-AlphaStar reproduction (ultimate primary = Vinyals et al., Nature 2019); DeepMind CTF granular layer specs (resolution/CNN depth) live in Jaderberg et al., Science 2019, not the accessible blog — architecture *shape* is confirmed, exact dims `[unverified]`. Marked `[unverified]` inline: npy/npz details (general numpy knowledge); the single canonical medallion+sharding directory template (a synthesis); DuckDB `ASOF JOIN` exact syntax (capability verified, syntax not re-fetched); D4RL `timeouts` semantics (widely-used convention; fetched README enumerated five keys); padding-mask tensor mechanics for windowing (standard practice, not quoted verbatim); the exact item-respawn two-feature + ETA recipes (building blocks sourced, full recipe is an engineering recommendation); a signed-distance-field channel in a *published FPS* agent; Feast auto-enforcement of model↔feature-version compatibility; and the Great Expectations exact suite API.
