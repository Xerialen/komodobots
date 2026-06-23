#!/usr/bin/env python3
"""Data-contract gate (issue #374).

Makes Git the memory for the training-data format and refuses to let the code and
the contract drift apart. Three checks, all stdlib-only so they run inside the
repo's `unittest discover` CI floor (no jsonschema / pyyaml dependency):

  1. The golden example rows (examples/expected_training_frame.jsonl) validate
     against the JSON Schema (schemas/training_example.schema.json).
  2. The field set the dataset builder actually emits
     (the `row = {...}` literal in scripts/build_training_dataset.py) is exactly
     the schema's required field set -- so adding/removing/renaming a field in the
     builder without updating the schema FAILS the build (the same-PR coupling).
  3. (soft, skipped if PyYAML is absent) configs/extraction_spec.yaml lists the
     same per-frame field set as the schema.

See docs/25_DATA_CONTRACT.md for the contract and its change-control rule.
Run locally:  python3 -m unittest tests.test_data_contract -v
"""
from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "training_example.schema.json"
EXAMPLE_PATH = ROOT / "examples" / "expected_training_frame.jsonl"
SPEC_PATH = ROOT / "configs" / "extraction_spec.yaml"
BUILDER_PATH = ROOT / "scripts" / "build_training_dataset.py"


def _load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


# --- minimal stdlib JSON-Schema check (only the constructs our schema uses) ----

_PY_TYPE = {
    "string": str,
    "integer": int,
    "number": (int, float),  # JSON has no int/float distinction; bool excluded below
    "boolean": bool,
    "array": list,
    "object": dict,
    "null": type(None),
}


def _type_ok(value, type_decl) -> bool:
    types = type_decl if isinstance(type_decl, list) else [type_decl]
    for t in types:
        py = _PY_TYPE[t]
        # bool is a subclass of int -- keep them distinct
        if t == "integer" and isinstance(value, bool):
            continue
        if t == "number" and isinstance(value, bool):
            continue
        if t == "boolean":
            if isinstance(value, bool):
                return True
            continue
        if isinstance(value, py):
            return True
    return False


def _validate_row(row: dict, schema: dict) -> list[str]:
    errors: list[str] = []
    props = schema["properties"]
    for key in schema.get("required", []):
        if key not in row:
            errors.append(f"missing required field {key!r}")
    if not schema.get("additionalProperties", True):
        for key in row:
            if key not in props:
                errors.append(f"unexpected field {key!r}")
    for key, value in row.items():
        spec = props.get(key)
        if spec is None:
            continue
        if "type" in spec and not _type_ok(value, spec["type"]):
            errors.append(f"field {key!r}={value!r} not of type {spec['type']}")
            continue
        if spec.get("type") == "array" or (isinstance(spec.get("type"), list) and "array" in spec["type"]):
            if isinstance(value, list):
                if "minItems" in spec and len(value) < spec["minItems"]:
                    errors.append(f"field {key!r} shorter than minItems {spec['minItems']}")
                if "maxItems" in spec and len(value) > spec["maxItems"]:
                    errors.append(f"field {key!r} longer than maxItems {spec['maxItems']}")
                item_spec = spec.get("items")
                if item_spec and "type" in item_spec:
                    for i, item in enumerate(value):
                        if not _type_ok(item, item_spec["type"]):
                            errors.append(f"field {key!r}[{i}]={item!r} not of type {item_spec['type']}")
    return errors


def _builder_row_keys() -> set[str]:
    """AST-extract the keys of the `row = {...}` dict literal emitted by the builder."""
    tree = ast.parse(BUILDER_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = [t for t in node.targets if isinstance(t, ast.Name) and t.id == "row"]
            if targets and isinstance(node.value, ast.Dict):
                keys = set()
                for k in node.value.keys:
                    if isinstance(k, ast.Constant) and isinstance(k.value, str):
                        keys.add(k.value)
                return keys
    raise AssertionError("could not find `row = {...}` dict literal in build_training_dataset.py")


class TestDataContract(unittest.TestCase):
    def test_golden_example_validates_against_schema(self):
        schema = _load_schema()
        lines = [ln for ln in EXAMPLE_PATH.read_text(encoding="utf-8").splitlines() if ln.strip()]
        self.assertGreater(len(lines), 0, "golden example file is empty")
        for n, line in enumerate(lines, 1):
            row = json.loads(line)
            errors = _validate_row(row, schema)
            self.assertEqual(errors, [], f"row {n} violates schema: {errors}")

    def test_builder_emits_exactly_the_contracted_fields(self):
        schema = _load_schema()
        required = set(schema["required"])
        emitted = _builder_row_keys()
        self.assertEqual(
            emitted,
            required,
            "scripts/build_training_dataset.py emits a different field set than "
            "schemas/training_example.schema.json requires. If you changed the row, "
            "update the schema, configs/extraction_spec.yaml, the golden example, and "
            "docs/25_DATA_CONTRACT.md IN THE SAME PR.\n"
            f"  builder only: {sorted(emitted - required)}\n"
            f"  schema only:  {sorted(required - emitted)}",
        )

    def test_extraction_spec_matches_schema(self):
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("PyYAML not installed; spec/schema cross-check is a soft gate")
        import yaml
        spec = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))
        spec_fields = {f["key"] for f in spec["per_frame_row"]["fields"]}
        schema_required = set(_load_schema()["required"])
        self.assertEqual(
            spec_fields,
            schema_required,
            "configs/extraction_spec.yaml per_frame_row.fields disagree with the schema.",
        )


if __name__ == "__main__":
    unittest.main()
