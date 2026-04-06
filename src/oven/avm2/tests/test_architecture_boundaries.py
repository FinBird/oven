from __future__ import annotations

import ast
from pathlib import Path


def test_avm2_runtime_modules_do_not_import_oven_api() -> None:
    package_root = Path(__file__).resolve().parents[1]
    violations: list[str] = []

    for path in package_root.rglob("*.py"):
        if "tests" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("oven.api"):
                        violations.append(f"{path}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                if (node.module or "").startswith("oven.api"):
                    violations.append(f"{path}: from {node.module} import ...")

    assert violations == []
