from __future__ import annotations

from pathlib import Path


def repo_root() -> Path:
    """Return repository root path (`oven/`)."""
    return Path(__file__).resolve().parents[2]


def reports_root(root: Path | None = None) -> Path:
    """Return unified report root directory."""
    base = repo_root() if root is None else root
    return base / "out" / "reports"


def report_path(*parts: str, root: Path | None = None) -> Path:
    """Build a path under the unified report root."""
    return reports_root(root).joinpath(*parts)


def avm2_reports_root(root: Path | None = None) -> Path:
    """Return AVM2 report directory."""
    return report_path("avm2", root=root)


def jpexs_ast_diff_report_path(root: Path | None = None) -> Path:
    """Canonical path for JPEXS AST diff markdown report."""
    return avm2_reports_root(root) / "JPEXS_AST_DIFF_REPORT.md"


def opcode_family_coverage_report_path(root: Path | None = None) -> Path:
    """Canonical path for opcode family coverage markdown report."""
    return avm2_reports_root(root) / "OPCODE_FAMILY_COVERAGE.md"


def swf_extract_abc_failures_report_path(root: Path | None = None) -> Path:
    """Canonical path for SWF extract + parse failure report."""
    return report_path("swf_extract", "SWF_EXTRACT_ABC_FAILURES.md", root=root)


def parse_abc_profile_report_path(root: Path | None = None) -> Path:
    """Canonical path for parse_abc profiling report."""
    return report_path("parse_abc", "PARSE_ABC_PROFILE_REPORT.md", root=root)


def ensure_parent(path: Path) -> Path:
    """Ensure parent directory exists and return the same path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
