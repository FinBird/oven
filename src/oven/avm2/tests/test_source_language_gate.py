from __future__ import annotations

import ast
import io
import re
import tokenize
from pathlib import Path

_CJK_RE = re.compile("[\u4e00-\u9fff]")


def _iter_python_sources() -> list[Path]:
    root = Path(__file__).resolve().parents[1]
    return sorted((path for path in root.glob("*.py") if path.name != "__pycache__"))


def _collect_docstring_violations(source: str) -> list[str]:
    violations: list[str] = []
    tree = ast.parse(source)
    module_doc = ast.get_docstring(tree, clean=False)
    if module_doc and _CJK_RE.search(module_doc):
        violations.append("module docstring contains CJK characters")
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc and _CJK_RE.search(doc):
                violations.append(
                    f"{type(node).__name__} {getattr(node, 'name', '<anonymous>')} docstring contains CJK characters"
                )
    return violations


def _collect_comment_violations(source: str) -> list[str]:
    violations: list[str] = []
    stream = io.StringIO(source)
    for tok in tokenize.generate_tokens(stream.readline):
        if tok.type == tokenize.COMMENT and _CJK_RE.search(tok.string):
            violations.append(f"comment line {tok.start[0]} contains CJK characters")
    return violations


def test_avm2_source_comments_and_docstrings_are_english_only() -> None:
    failures: list[str] = []
    for path in _iter_python_sources():
        content = path.read_text(encoding="utf-8")
        doc_issues = _collect_docstring_violations(content)
        comment_issues = _collect_comment_violations(content)
        for issue in doc_issues + comment_issues:
            failures.append(f"{path.name}: {issue}")
    assert not failures, "Found non-English comments/docstrings:\n" + "\n".join(
        failures
    )
