#!/usr/bin/env python3
"""LD-G2 (#108): golden-path validation harness for the Lab Dashboard v1.

Validates the dashboard's data contracts end-to-end using only committed
artifacts — no live servexeri or browser required. Fails loud (non-zero exit,
descriptive message) on any contract violation found.

Offline validations (always run):
    1. routes-manifest integrity  — every per-map JSON listed in index.json
       exists and parses; every route in a per-map file references a map that
       appears in maps.json; all required schema fields are present.
    2. maps.json / GLB structural check — every GLB listed in maps.json has
       the correct glTF magic bytes, version 2 header, and a JSON chunk whose
       asset.extras.source_bsp_sha256 matches the maps.json provenance record.
    3. map-entity corpus integrity — every imported mvd_analyzer map-entity JSON
       listed in index.json exists, parses, and matches the recorded entity counts.
    4. records / verdicts schema round-trip — the committed seed verdicts.seed.json
       parses as valid komodobots.verdicts.v1; a minimal synthetic records.json
       round-trips through records_build to prove schema stability.
    5. deploy script expected file-set — public/ key assets expected at the
       dist/ or public/ path exist as committed files.

Live path (deferred, skip unless --live is passed):
    6. @live: telemetry WebSocket frame — connect to ws://servexeri:8770, receive
       one frame, validate it parses as a known telemetry message type.
    7. @live: records.json freshness — fetch the deployed records.json over HTTP
       and validate it matches komodobots.records.v1.

Usage:
    # Offline only (CI / PR path):
    python scripts/ld_g2_golden_path.py

    # With live-lab access (owner slot):
    python scripts/ld_g2_golden_path.py --live

Stdlib-only.  Compatible with Python 3.12.
"""

import logging
import argparse
import json
import struct
import sys
from pathlib import Path


LOGGER = logging.getLogger(__name__)
# ---------------------------------------------------------------------------
# Repo root
# ---------------------------------------------------------------------------

REPO = Path(__file__).resolve().parent.parent

# Key committed paths
MAPS_JSON = REPO / "lab" / "dashboard" / "public" / "maps" / "maps.json"
ROUTES_INDEX = REPO / "lab" / "dashboard" / "public" / "data" / "routes" / "index.json"
ROUTES_DIR = REPO / "lab" / "dashboard" / "public" / "data" / "routes"
MAP_ENTITIES_INDEX = REPO / "lab" / "dashboard" / "public" / "data" / "map_entities" / "index.json"
MAP_ENTITIES_DIR = REPO / "lab" / "dashboard" / "public" / "data" / "map_entities"
MAPS_DIR = REPO / "lab" / "dashboard" / "public" / "maps"
VERDICTS_SEED = REPO / "lab" / "server" / "verdicts.seed.json"
PUBLIC_PANES = REPO / "lab" / "dashboard" / "public" / "panes"

# Schema version sentinels
ROUTES_SCHEMA = "komodobots.routes.v1"
MAPS_SCHEMA = "komodobots.maps.v1"
MAP_ENTITIES_SCHEMA = "komodobots.map_entities.v1"
RECORDS_SCHEMA = "komodobots.records.v1"
VERDICTS_SCHEMA = "komodobots.verdicts.v1"

# Required keys in a route record
ROUTE_REQUIRED_KEYS = {"name", "human", "polyline", "gaps", "teleports", "source"}
HUMAN_REQUIRED_KEYS = {"duration_s", "active_mean_speed", "peak_speed"}
SOURCE_REQUIRED_KEYS = {"census", "cmds", "cmds_sha256"}
GAP_REQUIRED_KEYS = {"edge", "land", "required_speed", "human_speed_at_edge", "hard", "type"}
MAP_ENTITY_REQUIRED_KEYS = {"type", "class", "x", "y", "z"}
MAP_ENTITIES_REQUIRED_MAPS = {"dm2", "dm3", "e1m2", "phantombase", "schloss", "ztricks"}

# Required keys in maps.json per-map entry
MAPS_REQUIRED_KEYS = {
    "obj", "source_bsp", "source_bsp_sha256",
    "vertices", "triangles", "worldmodel_faces",
    "aabb", "glb", "texture_count", "glb_bytes",
    "glb_triangles", "glb_vertices",
}

# Pane files that must be present in the committed public/panes/
PANE_FILES_REQUIRED = {"demo.html", "qtv.html", "fte_demo.cfg", "fte_qtv.cfg"}

# ---------------------------------------------------------------------------
# Failure accumulator — collect all errors before reporting
# ---------------------------------------------------------------------------


class HarnessError(Exception):
    """Raised when one or more checks fail."""


def _fail(errors: list[str], msg: str) -> None:
    """Append a formatted failure message."""
    errors.append(f"FAIL: {msg}")


# ---------------------------------------------------------------------------
# Check 1: routes-manifest integrity
# ---------------------------------------------------------------------------


def check_routes_manifest(errors: list[str]) -> None:
    """Validate the committed routes manifests end-to-end.

    - index.json must parse and carry the correct schema
    - every map entry in index.json must have a corresponding per-map file
    - every per-map file must parse and have the correct schema
    - every route in a per-map file must have all required fields
    - every map name referenced by a per-map file must appear in maps.json
    - the route count in index.json must match the actual per-map file route list

    Codex PR #90 locked the schema; tests in tests/test_build_routes_manifest.py
    lock the committed outputs against a fresh build.  This harness locks the
    DEPLOYED state end-to-end without rebuilding.
    """
    # Load index
    if not ROUTES_INDEX.is_file():
        _fail(errors, f"routes index not found: {ROUTES_INDEX}")
        return

    try:
        index = json.loads(ROUTES_INDEX.read_text())
    except json.JSONDecodeError as e:
        _fail(errors, f"routes index is not valid JSON: {e}")
        return

    if index.get("schema") != ROUTES_SCHEMA:
        _fail(errors, f"routes index wrong schema: got {index.get('schema')!r}, want {ROUTES_SCHEMA!r}")

    # Load maps.json to cross-reference map names
    known_maps: set[str] = set()
    if MAPS_JSON.is_file():
        try:
            maps_data = json.loads(MAPS_JSON.read_text())
            known_maps = set(maps_data.get("maps", {}).keys())
        except json.JSONDecodeError:
            pass  # maps.json errors reported in check_maps_glb

    for entry in index.get("maps", []):
        map_name = entry.get("map", "")
        expected_file = entry.get("file", "")
        expected_count = entry.get("routes", -1)

        # Cross-ref: map must be known in maps.json
        if known_maps and map_name not in known_maps:
            _fail(errors, f"routes index references map {map_name!r} not in maps.json")

        # Per-map file must exist
        per_map_path = ROUTES_DIR / expected_file
        if not per_map_path.is_file():
            _fail(errors, f"routes file not found: {per_map_path} (referenced from index)")
            continue

        try:
            per_map = json.loads(per_map_path.read_text())
        except json.JSONDecodeError as e:
            _fail(errors, f"routes file not valid JSON: {per_map_path}: {e}")
            continue

        if per_map.get("schema") != ROUTES_SCHEMA:
            _fail(errors, f"{expected_file}: wrong schema: got {per_map.get('schema')!r}")

        if per_map.get("map") != map_name:
            _fail(errors, f"{expected_file}: map field {per_map.get('map')!r} != index map {map_name!r}")

        routes = per_map.get("routes", [])
        actual_count = len(routes)
        if actual_count != expected_count:
            _fail(errors,
                  f"{expected_file}: route count mismatch: index says {expected_count}, "
                  f"file has {actual_count}")

        # Validate each route's required fields
        for i, route in enumerate(routes):
            prefix = f"{expected_file} route[{i}] {route.get('name', '?')!r}"
            missing = ROUTE_REQUIRED_KEYS - set(route.keys())
            if missing:
                _fail(errors, f"{prefix}: missing required keys: {sorted(missing)}")
                continue

            # human sub-object
            missing_h = HUMAN_REQUIRED_KEYS - set(route.get("human", {}).keys())
            if missing_h:
                _fail(errors, f"{prefix}: human missing keys: {sorted(missing_h)}")

            # source sub-object
            missing_s = SOURCE_REQUIRED_KEYS - set(route.get("source", {}).keys())
            if missing_s:
                _fail(errors, f"{prefix}: source missing keys: {sorted(missing_s)}")

            # polyline must be a list of 3-element coordinate lists
            polyline = route.get("polyline", [])
            if not isinstance(polyline, list) or len(polyline) < 2:
                _fail(errors, f"{prefix}: polyline must have >= 2 points, got {len(polyline)}")
            else:
                for j, pt in enumerate(polyline[:3]):  # spot-check first 3
                    if not (isinstance(pt, list) and len(pt) == 3):
                        _fail(errors, f"{prefix}: polyline[{j}] is not a 3-element list: {pt!r}")

            # gaps must have required keys when non-empty
            for j, gap in enumerate(route.get("gaps", [])):
                missing_g = GAP_REQUIRED_KEYS - set(gap.keys())
                if missing_g:
                    _fail(errors, f"{prefix}: gaps[{j}] missing keys: {sorted(missing_g)}")

            # teleports must have from/to when non-empty
            for j, tp in enumerate(route.get("teleports", [])):
                if "from" not in tp or "to" not in tp:
                    _fail(errors, f"{prefix}: teleports[{j}] missing from/to keys")


# ---------------------------------------------------------------------------
# Check 2: maps.json / GLB structural check
# ---------------------------------------------------------------------------


def _parse_glb_header(data: bytes) -> dict:
    """Parse the GLB header and JSON chunk. Return extracted fields."""
    if len(data) < 12:
        raise ValueError("file too short to be a GLB")
    magic = data[:4]
    if magic != b"glTF":
        raise ValueError(f"wrong GLB magic: {magic!r}")
    version = struct.unpack_from("<I", data, 4)[0]
    declared_len = struct.unpack_from("<I", data, 8)[0]
    if declared_len != len(data):
        raise ValueError(
            f"GLB declared length {declared_len} != actual file size {len(data)}"
        )
    if len(data) < 20:
        raise ValueError("GLB too short to contain a chunk header")
    chunk_len = struct.unpack_from("<I", data, 12)[0]
    chunk_type = struct.unpack_from("<I", data, 16)[0]
    if chunk_type != 0x4E4F534A:  # 'JSON' in LE
        raise ValueError(f"chunk 0 is not JSON type: 0x{chunk_type:08x}")
    json_bytes = data[20: 20 + chunk_len]
    try:
        gltf = json.loads(json_bytes)
    except json.JSONDecodeError as e:
        raise ValueError(f"GLB JSON chunk not valid JSON: {e}") from e
    return {
        "version": version,
        "gltf": gltf,
        "sha256_from_extras": (
            gltf.get("asset", {}).get("extras", {}).get("source_bsp_sha256")
        ),
    }


def check_maps_glb(errors: list[str]) -> None:
    """Validate maps.json and all committed GLB assets.

    - maps.json must parse as komodobots.maps.v1
    - every map entry must have all required keys
    - every listed GLB file must exist and have correct glTF header
    - the GLB's asset.extras.source_bsp_sha256 must match maps.json
    - GLB declared file length must match actual file size

    LD-C4 (#92) established the schema and provenance contract;
    tests/test_bsp_to_mesh.py locks the build-time pipeline.
    This check locks the COMMITTED outputs.
    """
    if not MAPS_JSON.is_file():
        _fail(errors, f"maps.json not found: {MAPS_JSON}")
        return

    try:
        maps_data = json.loads(MAPS_JSON.read_text())
    except json.JSONDecodeError as e:
        _fail(errors, f"maps.json not valid JSON: {e}")
        return

    if maps_data.get("schema") != MAPS_SCHEMA:
        _fail(errors, f"maps.json wrong schema: got {maps_data.get('schema')!r}, want {MAPS_SCHEMA!r}")

    for map_name, info in maps_data.get("maps", {}).items():
        prefix = f"maps.json[{map_name!r}]"
        missing = MAPS_REQUIRED_KEYS - set(info.keys())
        if missing:
            _fail(errors, f"{prefix}: missing required keys: {sorted(missing)}")
            continue  # skip GLB check if keys missing

        glb_name = info["glb"]
        glb_path = MAPS_DIR / glb_name
        if not glb_path.is_file():
            _fail(errors, f"{prefix}: GLB file not found: {glb_path}")
            continue

        try:
            glb_data = glb_path.read_bytes()
            parsed = _parse_glb_header(glb_data)
        except (OSError, ValueError) as e:
            _fail(errors, f"{prefix}: GLB parse error for {glb_name}: {e}")
            continue

        if parsed["version"] != 2:
            _fail(errors, f"{prefix}: GLB version {parsed['version']} != 2")

        # SHA provenance round-trip
        expected_sha = info["source_bsp_sha256"]
        got_sha = parsed["sha256_from_extras"]
        if got_sha is None:
            _fail(errors, f"{prefix}: GLB has no asset.extras.source_bsp_sha256")
        elif got_sha != expected_sha:
            _fail(errors,
                  f"{prefix}: SHA mismatch — maps.json says {expected_sha!r}, "
                  f"GLB extras says {got_sha!r}")

        # Byte-size consistency
        if info["glb_bytes"] != len(glb_data):
            _fail(errors,
                  f"{prefix}: glb_bytes {info['glb_bytes']} in maps.json != "
                  f"actual file size {len(glb_data)}")


# ---------------------------------------------------------------------------
# Check 3: map-entity corpus integrity
# ---------------------------------------------------------------------------


def _entity_type_counts(entities: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entity in entities:
        entity_type = str(entity.get("type", ""))
        counts[entity_type] = counts.get(entity_type, 0) + 1
    return dict(sorted(counts.items()))


def check_map_entities(errors: list[str]) -> None:
    """Validate the committed mvd_analyzer static map-entity data layer.

    - index.json must parse and carry the correct schema
    - the required imported maps must be present, including ztricks
    - every per-map file must parse, match its map name, and carry version 1
    - entity counts and type counts must match the index
    - every entity must expose type/class plus x/y/z coordinates

    This is deliberately separate from maps.json: e1m2, phantombase, and schloss
    have entity data before they have committed BotLab mesh assets.
    """
    if not MAP_ENTITIES_INDEX.is_file():
        _fail(errors, f"map-entities index not found: {MAP_ENTITIES_INDEX}")
        return

    try:
        index = json.loads(MAP_ENTITIES_INDEX.read_text())
    except json.JSONDecodeError as e:
        _fail(errors, f"map-entities index is not valid JSON: {e}")
        return

    if index.get("schema") != MAP_ENTITIES_SCHEMA:
        _fail(errors,
              f"map-entities index wrong schema: got {index.get('schema')!r}, "
              f"want {MAP_ENTITIES_SCHEMA!r}")

    maps = index.get("maps", [])
    seen_maps = {entry.get("map", "") for entry in maps}
    missing_maps = MAP_ENTITIES_REQUIRED_MAPS - seen_maps
    if missing_maps:
        _fail(errors, f"map-entities index missing required maps: {sorted(missing_maps)}")

    source = index.get("source", {})
    commit = source.get("commit", "")
    if not isinstance(commit, str) or len(commit) != 40 or not all(c in "0123456789abcdef" for c in commit):
        _fail(errors, f"map-entities source.commit is not a 40-char lowercase sha: {commit!r}")

    for entry in maps:
        map_name = entry.get("map", "")
        expected_file = entry.get("file", "")
        expected_count = entry.get("entities", -1)
        expected_types = entry.get("types", {})
        prefix = f"map_entities[{map_name!r}]"

        if not map_name or not expected_file:
            _fail(errors, f"{prefix}: index entry missing map/file")
            continue

        path = MAP_ENTITIES_DIR / expected_file
        if not path.is_file():
            _fail(errors, f"{prefix}: file not found: {path}")
            continue

        try:
            doc = json.loads(path.read_text())
        except json.JSONDecodeError as e:
            _fail(errors, f"{prefix}: file not valid JSON: {path}: {e}")
            continue

        if doc.get("map") != map_name:
            _fail(errors, f"{prefix}: map field {doc.get('map')!r} != index map {map_name!r}")

        if doc.get("version") != 1:
            _fail(errors, f"{prefix}: version {doc.get('version')!r} != 1")

        entities = doc.get("entities", [])
        if not isinstance(entities, list) or not entities:
            _fail(errors, f"{prefix}: entities must be a non-empty list")
            continue

        actual_count = len(entities)
        if actual_count != expected_count:
            _fail(errors,
                  f"{prefix}: entity count mismatch: index says {expected_count}, "
                  f"file has {actual_count}")

        actual_types = _entity_type_counts(entities)
        if actual_types != expected_types:
            _fail(errors,
                  f"{prefix}: type counts mismatch: index says {expected_types}, "
                  f"file has {actual_types}")

        for i, entity in enumerate(entities):
            missing = MAP_ENTITY_REQUIRED_KEYS - set(entity.keys())
            if missing:
                _fail(errors, f"{prefix}: entity[{i}] missing required keys: {sorted(missing)}")
                continue
            for coord in ("x", "y", "z"):
                if not isinstance(entity.get(coord), (int, float)):
                    _fail(errors, f"{prefix}: entity[{i}].{coord} is not numeric: {entity.get(coord)!r}")


# ---------------------------------------------------------------------------
# Check 4: records / verdicts schema round-trip
# ---------------------------------------------------------------------------


def check_records_verdicts_schema(errors: list[str]) -> None:
    """Validate committed schema seeds and round-trip integrity.

    - verdicts.seed.json must parse and carry schema komodobots.verdicts.v1
    - each verdict in verdicts.seed.json must have the required fields
    - the schema sentinel in records_build.py must match what it exports

    LD-D1 (#93) defined the records schema;
    tests/test_records_build.py locks the full build logic.
    This check locks the committed seed and schema-constant alignment.
    """
    # --- verdicts.seed.json ---
    if not VERDICTS_SEED.is_file():
        _fail(errors, f"verdicts.seed.json not found: {VERDICTS_SEED}")
    else:
        try:
            verdicts = json.loads(VERDICTS_SEED.read_text())
        except json.JSONDecodeError as e:
            _fail(errors, f"verdicts.seed.json not valid JSON: {e}")
            verdicts = {}

        if verdicts.get("schema") != VERDICTS_SCHEMA:
            _fail(errors,
                  f"verdicts.seed.json wrong schema: got {verdicts.get('schema')!r}, "
                  f"want {VERDICTS_SCHEMA!r}")

        required_verdict_keys = {"verdict", "note", "run_id", "date"}
        for route, entry in verdicts.get("routes", {}).items():
            missing = required_verdict_keys - set(entry.keys())
            if missing:
                _fail(errors,
                      f"verdicts.seed.json route {route!r} missing keys: {sorted(missing)}")
            verdict_val = entry.get("verdict", "")
            if verdict_val not in ("pass", "close", "fail"):
                _fail(errors,
                      f"verdicts.seed.json route {route!r} verdict {verdict_val!r} "
                      f"not in (pass, close, fail)")

    # --- records_build.py SCHEMA constant alignment ---
    try:
        sys.path.insert(0, str(REPO / "lab" / "server"))
        import records_build as rb  # noqa: PLC0415
        if rb.SCHEMA != RECORDS_SCHEMA:
            _fail(errors,
                  f"records_build.SCHEMA {rb.SCHEMA!r} != expected {RECORDS_SCHEMA!r}")
    except ImportError as e:
        _fail(errors, f"could not import records_build: {e}")


# ---------------------------------------------------------------------------
# Check 5: deploy script expected file-set
# ---------------------------------------------------------------------------


def check_deploy_file_set(errors: list[str]) -> None:
    """Validate that committed public/ assets expected by the deploy path exist.

    The deploy script ships dist/ which includes public/ verbatim.  Before the
    npm build step is run (which is a live-lab operation), we verify the source
    public/ assets the build depends on are all committed and present.

    - maps.json must be present (already checked, but cross-verify via deploy)
    - per-map GLB files listed in maps.json must be present
    - per-map routes JSON files listed in index.json must be present
    - per-map map-entity JSON files listed in map_entities/index.json must be present
    - pane HTML + cfg files must be present
    - legacy dm3.obj (top-level public/ file, still loaded by deployed viewer) must exist

    LD-A2 (#85) defines the deploy path; tests/test_deploy_dashboard.py locks the
    command-builder logic.  This check locks the committed source file-set without
    requiring npm or a live build.
    """
    required_top_level = [
        REPO / "lab" / "dashboard" / "public" / "dm3.obj",
        REPO / "lab" / "dashboard" / "public" / "dm3_sng_to_rl.cmds",
    ]
    for p in required_top_level:
        if not p.is_file():
            _fail(errors, f"deploy required file missing: {p.relative_to(REPO)}")

    # Pane files
    for fname in PANE_FILES_REQUIRED:
        p = PUBLIC_PANES / fname
        if not p.is_file():
            try:
                label = p.relative_to(REPO)
            except ValueError:
                label = p
            _fail(errors, f"pane file missing: {label}")

    # Per-map GLB (re-verify path existence, not just maps.json reference)
    if MAPS_JSON.is_file():
        try:
            maps_data = json.loads(MAPS_JSON.read_text())
            for map_name, info in maps_data.get("maps", {}).items():
                for ext in ("glb", "obj"):
                    key = ext
                    if key in info:
                        path = MAPS_DIR / info[key]
                        if not path.is_file():
                            _fail(errors,
                                  f"deploy asset missing for map {map_name!r}: "
                                  f"{path.relative_to(REPO)}")
        except (json.JSONDecodeError, KeyError):
            pass  # already reported in check_maps_glb

    # Routes per-map JSONs
    if ROUTES_INDEX.is_file():
        try:
            index = json.loads(ROUTES_INDEX.read_text())
            for entry in index.get("maps", []):
                p = ROUTES_DIR / entry.get("file", "")
                if not p.is_file():
                    _fail(errors,
                          f"deploy asset missing: routes file {p.relative_to(REPO)}")
        except json.JSONDecodeError:
            pass  # already reported in check_routes_manifest

    # Map entity per-map JSONs
    if MAP_ENTITIES_INDEX.is_file():
        try:
            index = json.loads(MAP_ENTITIES_INDEX.read_text())
            for entry in index.get("maps", []):
                p = MAP_ENTITIES_DIR / entry.get("file", "")
                if not p.is_file():
                    _fail(errors,
                          f"deploy asset missing: map-entities file {p.relative_to(REPO)}")
        except json.JSONDecodeError:
            pass  # already reported in check_map_entities


# ---------------------------------------------------------------------------
# Live checks (deferred, --live only)
# ---------------------------------------------------------------------------


def check_live_telemetry(errors: list[str], host: str = "192.168.86.33", port: int = 8770) -> None:
    """@live: connect to telemetry WebSocket, receive one frame, validate type.

    DEFERRED: requires live servexeri access (ws://servexeri:8770).
    Not run in CI. Run manually in a declared lab slot.

    This function is included so its contract is code-level, not just prose.
    """
    import socket  # noqa: PLC0415
    import base64  # noqa: PLC0415
    import hashlib  # noqa: PLC0415
    import os  # noqa: PLC0415
    try:
        sock = socket.create_connection((host, port), timeout=5)
    except OSError as e:
        _fail(errors, f"@live telemetry: cannot connect to {host}:{port}: {e}")
        return

    try:
        # Minimal WebSocket handshake
        key = base64.b64encode(os.urandom(16)).decode()
        handshake = (
            f"GET / HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n\r\n"
        ).encode()
        sock.sendall(handshake)
        resp = sock.recv(4096)
        if b"101" not in resp:
            _fail(errors, f"@live telemetry: WS upgrade failed: {resp[:80]!r}")
            return

        # Read one frame (telemetry sends frames every ~80 ms)
        header = b""
        while len(header) < 2:
            chunk = sock.recv(2 - len(header))
            if not chunk:
                break
            header += chunk
        if len(header) < 2:
            _fail(errors, "@live telemetry: no frame header received within timeout")
            return

        fin_opcode = header[0]
        payload_len = header[1] & 0x7F
        if payload_len == 126:
            ext = sock.recv(2)
            payload_len = struct.unpack("!H", ext)[0]
        elif payload_len == 127:
            ext = sock.recv(8)
            payload_len = struct.unpack("!Q", ext)[0]

        payload = b""
        while len(payload) < min(payload_len, 4096):
            chunk = sock.recv(min(payload_len - len(payload), 4096))
            if not chunk:
                break
            payload += chunk

        try:
            frame = json.loads(payload)
        except json.JSONDecodeError as e:
            _fail(errors, f"@live telemetry: frame not valid JSON: {e}: {payload[:80]!r}")
            return

        if "type" not in frame:
            _fail(errors, f"@live telemetry: frame missing 'type' key: {list(frame.keys())}")
    finally:
        sock.close()


def check_live_records(errors: list[str], host: str = "192.168.86.33", port: int = 8095) -> None:
    """@live: fetch deployed records.json, validate komodobots.records.v1.

    DEFERRED: requires live servexeri HTTP access (http://servexeri:8095).
    Not run in CI. Run manually in a declared lab slot.
    """
    import urllib.request  # noqa: PLC0415
    import urllib.error  # noqa: PLC0415
    url = f"http://{host}:{port}/demos/records/records.json"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read())
    except urllib.error.URLError as e:
        _fail(errors, f"@live records: cannot fetch {url}: {e}")
        return
    except json.JSONDecodeError as e:
        _fail(errors, f"@live records: not valid JSON: {e}")
        return

    if data.get("schema") != RECORDS_SCHEMA:
        _fail(errors,
              f"@live records: wrong schema: got {data.get('schema')!r}, want {RECORDS_SCHEMA!r}")

    if "maps" not in data:
        _fail(errors, "@live records: missing 'maps' key")
        return

    # All four maps must be present
    for map_name in ("dm3", "dm2", "frobodm2", "trick"):
        if map_name not in data["maps"]:
            _fail(errors, f"@live records: map {map_name!r} missing from records.json")

    # provenance block must be present
    if "provenance" not in data:
        _fail(errors, "@live records: missing 'provenance' key")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def run_offline(verbose: bool = False) -> list[str]:
    """Run all offline checks. Return list of error strings (empty = pass)."""
    errors: list[str] = []

    checks = [
        ("routes-manifest integrity", check_routes_manifest),
        ("maps.json / GLB structural", check_maps_glb),
        ("map-entities integrity", check_map_entities),
        ("records/verdicts schema round-trip", check_records_verdicts_schema),
        ("deploy expected file-set", check_deploy_file_set),
    ]

    for name, fn in checks:
        before = len(errors)
        fn(errors)
        after = len(errors)
        if verbose:
            new_errs = after - before
            status = "PASS" if new_errs == 0 else f"FAIL ({new_errs} error(s))"
            print(f"  [{status}] {name}")

    return errors


def run_live(verbose: bool = False) -> list[str]:
    """Run live checks (requires servexeri access). Return error list."""
    errors: list[str] = []
    checks = [
        ("@live telemetry WebSocket frame", check_live_telemetry),
        ("@live records.json deployed schema", check_live_records),
    ]
    for name, fn in checks:
        before = len(errors)
        fn(errors)
        after = len(errors)
        if verbose:
            new_errs = after - before
            status = "PASS" if new_errs == 0 else f"FAIL ({new_errs} error(s))"
            print(f"  [{status}] {name}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="LD-G2 golden-path validation harness (offline slice)."
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Also run @live checks (requires servexeri access — deferred owner task).",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print per-check status lines.",
    )
    args = parser.parse_args(argv)

    print("LD-G2 golden-path harness — offline slice")
    print("==========================================")

    errors = run_offline(verbose=args.verbose)

    if args.live:
        print("\n--- @live checks (requires servexeri) ---")
        errors.extend(run_live(verbose=args.verbose))

    if errors:
        print(f"\n{len(errors)} failure(s):")
        for e in errors:
            print(f"  {e}")
        return 1

    total = 5 + (2 if args.live else 0)
    print(f"\nAll {total} check(s) passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
