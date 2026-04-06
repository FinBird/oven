from __future__ import annotations

from pathlib import Path

import pytest

from oven.avm2 import decompile_abc_to_files, decompile_to_files


def _fixture_bytes(filename: str) -> bytes:
    root = Path(__file__).resolve().parents[4]
    return (root / "fixtures" / "abc" / filename).read_bytes()


def _fixture_path(filename: str) -> Path:
    root = Path(__file__).resolve().parents[4]
    return root / "fixtures" / "abc" / filename


def test_decompile_to_files_from_bytes_writes_class_sources(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    written = decompile_to_files(_fixture_bytes("abcdump.abc"), output_dir, style="semantic", int_format="dec", clean_output=True)
    assert written
    assert all((path.exists() for path in written))
    assert all((path.suffix == ".as" for path in written))
    assert any((path.name == "Abc.as" for path in written))
    assert any(("class Abc {" in path.read_text(encoding="utf-8") for path in written))


def test_decompile_abc_to_files_from_bytes_cleans_output_directory(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    stale_file = output_dir / "stale.txt"
    stale_file.parent.mkdir(parents=True, exist_ok=True)
    stale_file.write_text("stale", encoding="utf-8")
    written = decompile_abc_to_files(_fixture_bytes("Test.abc"), output_dir, style="semantic", int_format="dec", clean_output=True)
    assert written
    assert not stale_file.exists()


def test_decompile_to_files_from_path_target(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    written = decompile_to_files(_fixture_path("Test.abc"), output_dir, style="semantic", int_format="dec", clean_output=True)
    assert written
    assert all((path.exists() for path in written))


def test_decompile_to_files_replaces_file_output_target_when_clean_output_true(tmp_path: Path) -> None:
    output_file = tmp_path / "out"
    output_file.write_text("stale", encoding="utf-8")
    written = decompile_to_files(_fixture_bytes("Test.abc"), output_file, style="semantic", int_format="dec", clean_output=True)
    assert output_file.is_dir()
    assert written
    assert all((path.exists() for path in written))


def test_decompile_to_files_rejects_file_output_target_when_clean_output_false(tmp_path: Path) -> None:
    output_file = tmp_path / "out"
    output_file.write_text("stale", encoding="utf-8")
    with pytest.raises(NotADirectoryError):
        decompile_to_files(_fixture_bytes("Test.abc"), output_file, style="semantic", int_format="dec", clean_output=False)