"""Tests for debug comment output through the class-only API."""

from __future__ import annotations

from pathlib import Path

from oven.api import Decompiler, ExportOptions
from oven.avm2.config import ParseMode


def _export_first_file(tmp_path: Path, fixture_dir: Path, *, debug: bool) -> str:
    decompiler = Decompiler.from_file(
        fixture_dir / "Test.abc",
        options=ExportOptions(
            debug=debug,
            mode=ParseMode.RELAXED,
            int_format="hex",
        ),
    )
    result = decompiler.export_to_disk(tmp_path / ("debug" if debug else "clean"))
    assert result.output_files
    return result.output_files[0].read_text(encoding="utf-8")


def test_debug_comments_enabled_include_offset_opcode_and_operands(
    tmp_path: Path,
    fixture_dir: Path,
) -> None:
    source = _export_first_file(tmp_path, fixture_dir, debug=True)
    assert "// method " in source
    debug_lines = [
        line.strip() for line in source.splitlines() if line.strip().startswith("// 0x")
    ]
    assert debug_lines
    for line in debug_lines[:20]:
        assert line.startswith("// 0x")
        assert ": " in line
        assert line.split(": ", 1)[1].strip()


def test_debug_comments_disabled_omits_bytecode_comments(
    tmp_path: Path,
    fixture_dir: Path,
) -> None:
    source = _export_first_file(tmp_path, fixture_dir, debug=False)
    assert "// 0x" not in source
    assert "// method " not in source
