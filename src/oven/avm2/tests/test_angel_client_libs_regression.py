from __future__ import annotations

from pathlib import Path

from oven.avm2 import decompile, decompile_to_files, parse
from oven.avm2.config import ParseMode


def _fixture_path() -> Path:
    return (
        Path(__file__).resolve().parents[4] / "fixtures" / "abc" / "AngelClientLibs.abc"
    )


def test_angel_client_libs_parse_smoke() -> None:
    fixture = _fixture_path()
    abc = parse(fixture.read_bytes(), mode=ParseMode.RELAXED)
    assert abc.major_version > 0
    assert len(abc.methods) > 0
    assert len(abc.method_bodies) > 0
    assert len(abc.instances) > 0


import pytest


def test_angel_client_libs_decompile_smoke() -> None:
    import time

    fixture = _fixture_path()
    start = time.time()
    text = decompile(fixture.read_bytes(), layout="classes")
    duration = time.time() - start
    print(f"Decompile took {duration:.2f}s")
    # Allow up to 30s for large ABC files after optimizations
    assert duration < 30, f"Decompile took too long: {duration:.2f}s"
    assert text
    assert "class " in text or "interface " in text


def test_angel_client_libs_decompile_to_files_smoke(tmp_path: Path) -> None:
    fixture = _fixture_path()
    written = decompile_to_files(
        fixture.read_bytes(),
        tmp_path,
        style="semantic",
        int_format="dec",
        clean_output=True,
    )
    assert written
    assert all(path.suffix == ".as" for path in written)
