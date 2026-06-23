from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOTS = ("scripts", "lab", "tools", "experiments", "ml", "cloud")
HIGH_RISK_RUNTIME_PATHS = (
    "scripts/run_frobodm2_lab.py",
    "scripts/run_4v4_validation_lab.py",
    "scripts/run_dm3.py",
    "scripts/telemetry_ws.py",
    "lab/deploy_dashboard.py",
    "lab/server/control_bridge.py",
)
DASHBOARD_SRC = REPO_ROOT / "lab" / "dashboard" / "src"


def production_python_files() -> list[Path]:
    files: list[Path] = []
    for root_name in PYTHON_ROOTS:
        root = REPO_ROOT / root_name
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if path.name == "__init__.py" or "tests" in path.parts or "__pycache__" in path.parts:
                continue
            files.append(path)
    return sorted(files)


def has_logging_import(tree: ast.Module) -> bool:
    return any(
        isinstance(node, ast.Import) and any(alias.name == "logging" for alias in node.names)
        or isinstance(node, ast.ImportFrom) and node.module == "logging"
        for node in tree.body
    )


def has_module_logger(tree: ast.Module) -> bool:
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id in {"LOGGER", "logger"} for target in node.targets):
            continue
        value = node.value
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute) and value.func.attr == "getLogger":
            return True
    return False


class PythonLoggingCoverageTests(unittest.TestCase):
    def test_all_production_python_modules_declare_module_logger(self) -> None:
        missing = []
        for path in production_python_files():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            if not (has_logging_import(tree) and has_module_logger(tree)):
                missing.append(str(path.relative_to(REPO_ROOT)))

        self.assertEqual(
            missing,
            [],
            "production Python modules must import logging and declare LOGGER = logging.getLogger(__name__)",
        )

    def test_high_risk_runtime_paths_emit_log_records(self) -> None:
        missing = []
        for rel in HIGH_RISK_RUNTIME_PATHS:
            text = (REPO_ROOT / rel).read_text(encoding="utf-8")
            if re.search(r"\bLOGGER\.(debug|info|warning|error|exception)\(", text) is None:
                missing.append(rel)

        self.assertEqual(missing, [], "high-risk runtime paths need real LOGGER.* calls, not only declarations")


class DashboardLoggingCoverageTests(unittest.TestCase):
    def test_dashboard_catch_blocks_log_errors(self) -> None:
        missing = []
        for path in sorted(DASHBOARD_SRC.rglob("*")):
            if path.suffix not in {".ts", ".tsx"}:
                continue
            text = path.read_text(encoding="utf-8")
            for match in re.finditer(r"\bcatch\b", text):
                snippet = text[match.start() : match.start() + 500]
                if not re.search(r"\blog(?:Debug|Info|Warn|Error)\(", snippet):
                    line = text.count("\n", 0, match.start()) + 1
                    missing.append(f"{path.relative_to(REPO_ROOT)}:{line}")

        self.assertEqual(missing, [], "dashboard catch blocks must log through src/logger.ts")


if __name__ == "__main__":
    unittest.main()
