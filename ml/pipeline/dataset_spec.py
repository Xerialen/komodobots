"""dataset_spec.py — stdlib reader for data/catalog/dataset_spec.yaml (T9 #397).

`dataset_spec.yaml` (`komodobots.dataset_spec.v1`) is the §2.9 entities / `ent_mask` /
window contract: the windowing geometry (K / stride / N_max), the `record_layout`
(obs / self_history / entities / ent_mask / act / mask / weight), the split policy, and
the normalization-artifact pointer. Until T9 it was referenced only in prose + DUPLICATED
as hardcoded constants in ml/broad_bc/shard_contract.py — nothing actually READ the file,
so the spec and the code could silently drift.

This module is the machine reader that closes that loop. It is **stdlib-only** (no PyYAML —
CI has none; the repo's deterministic floor must import without third-party deps), using the
same targeted line-scan pattern scripts/audit_extraction_coverage.parse_registry_sources and
scripts/features/agent_observation use to read feature_registry.yaml. It does NOT implement a
general YAML parser: it pulls the handful of scalar windowing/record-layout fields the
training connection needs out of the (flat-ish, 2-space-indented) dataset_spec, and is
asserted against shard_contract's pinned constants by the T9 test so any future edit to
either side that breaks the contract fails loudly.

LIMITATION (honest): the reader recognizes the specific keys below (the windowing +
record-layout + split contract). It is not a drop-in YAML loader; a brand-new top-level
section is invisible until a key is added here. That is deliberate — a contract reader
should fail closed on a key it does not understand rather than guess.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path


LOGGER = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SPEC = REPO_ROOT / "data" / "catalog" / "dataset_spec.yaml"

# scalar keys we extract, with the section they live under (None = top level) and a caster.
# Kept explicit (not a generic walk) so an unexpected duplicate key in another section can't
# silently shadow the contract value — we only read the key under its declared parent.
_INT = int
_FLOAT = float


def _coerce(raw: str):
    """Strip an inline `# comment` + quotes, return the bare scalar string."""
    # drop a trailing comment (the YAML values here never contain a literal '#')
    val = raw.split("#", 1)[0].strip()
    return val.strip().strip("\"'")


def _scan(text: str) -> dict:
    """Line-scan the 2-space-indented dataset_spec into {section: {key: value}}.

    Sections are top-level `name:` headers (indent 0, no value or a mapping body);
    keys are `key: value` lines indented under them. record_layout.keys entries are
    `obs: { ... }` inline mappings — we capture only that the key EXISTS (the ext/shape
    detail is prose-y and not part of the scalar contract), recorded under section
    'record_layout.keys'. Good enough for the contract fields T9 needs; deliberately NOT
    a general parser (see module docstring)."""
    sections: dict[str, dict] = {"": {}}
    cur = ""              # current top-level section
    in_keys = False       # inside record_layout.keys:
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        stripped = raw.strip()
        if indent == 0:
            # top-level `section:` (maybe with an inline scalar, maybe a mapping header)
            m = re.match(r"^([A-Za-z_][\w]*)\s*:\s*(.*)$", stripped)
            if not m:
                continue
            cur, rest = m.group(1), m.group(2)
            sections.setdefault(cur, {})
            in_keys = False
            rest_clean = _coerce(rest)
            if rest_clean != "":
                # a top-level scalar (e.g. dataset_spec_version: 5)
                sections[""][cur] = rest_clean
            continue
        # indented line under `cur`
        if cur == "record_layout" and re.match(r"^keys\s*:\s*$", stripped):
            in_keys = True
            sections.setdefault("record_layout.keys", {})
            continue
        if in_keys:
            mk = re.match(r"^([A-Za-z_][\w]*)\s*:\s*\{", stripped)
            if mk:
                sections["record_layout.keys"][mk.group(1)] = True
                continue
            # a non-`{` line under keys ends the keys block (e.g. F_obs_note:)
            if re.match(r"^[A-Za-z_]", stripped) and indent <= 2:
                in_keys = False
        m = re.match(r"^([A-Za-z_][\w]*)\s*:\s*(.*)$", stripped)
        if m and m.group(2).strip() not in ("", "{"):
            sections[cur][m.group(1)] = _coerce(m.group(2))
    return sections


def load(spec_path: Path | None = None) -> dict:
    """Read dataset_spec.yaml -> the typed windowing / record-layout / split contract.

    Returns a dict with the contract fields the training connection binds to:
      schema_version, registry_version,
      window: {lookback_K, stride, bc_window, pad_short_windows},
      entity_max: {N_max},
      record_layout_keys: [obs, self_history, entities, ent_mask, act, mask, weight, ...],
      split: {method, fractions:{train,val,test}, held_out_players:[...]},
      normalization_artifact (relative path string).
    Raises ValueError if a required contract field is missing (fail closed)."""
    path = Path(spec_path) if spec_path is not None else DEFAULT_SPEC
    sec = _scan(path.read_text(encoding="utf-8"))
    top = sec.get("", {})

    def _need(section: str, key: str, cast):
        if section not in sec or key not in sec[section]:
            raise ValueError(f"dataset_spec missing required field {section or '<top>'}.{key}")
        return cast(sec[section][key])

    contract = {
        "schema_version": int(top.get("dataset_spec_version", "0")),
        "registry_version": int(top.get("registry_version", "0")),
        "normalization_artifact": top.get("normalization_artifact", ""),
        "window": {
            "lookback_K": _need("windowing", "lookback_K", _INT),
            "stride": _need("windowing", "stride", _INT),
            "bc_window": _need("windowing", "bc_window", _INT),
            "pad_short_windows": str(sec["windowing"].get("pad_short_windows", "")).lower() == "true",
        },
        "entity_max": {"N_max": _need("entity_max", "N_max", _INT)},
        "record_layout_keys": sorted(sec.get("record_layout.keys", {}).keys()),
        "split": {
            "method": sec.get("split_policy", {}).get("method", ""),
            "fractions": _parse_fractions(sec.get("split_policy", {}).get("fractions", "")),
            "held_out_players": _parse_list(sec.get("split_policy", {}).get("held_out_players", "")),
        },
    }
    return contract


def _parse_fractions(raw: str) -> dict:
    """Parse the inline `{ train: 0.70, val: 0.15, test: 0.15 }` fractions mapping."""
    out: dict[str, float] = {}
    for m in re.finditer(r"(train|val|test)\s*:\s*([0-9.]+)", raw):
        out[m.group(1)] = _FLOAT(m.group(2))
    return out


def _parse_list(raw: str) -> list[str]:
    """Parse an inline `[milton]` / `[a, b]` flow list."""
    inner = raw.strip().strip("[]").strip()
    if not inner:
        return []
    return [tok.strip().strip("\"'") for tok in inner.split(",") if tok.strip()]


if __name__ == "__main__":
    import json
    print(json.dumps(load(), indent=2))
