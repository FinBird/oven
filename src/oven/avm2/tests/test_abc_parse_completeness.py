"""
ABC parsing completeness and structural integrity tests.
"""

from __future__ import annotations
from pathlib import Path
import pytest
from oven.avm2 import load_abc, parse_abc
from oven.avm2.exceptions import InvalidABCCodeError
from oven.avm2.enums import Opcode


def _minimal_abc(method_body_method_indexes: list[int], method_count: int = 1) -> bytes:
    """
    Build a tiny but structurally valid ABC binary for parser boundary tests.
    The constant pool is empty (all count=1).
    """
    blob = bytearray()
    blob.extend((16).to_bytes(2, "little"))
    blob.extend((46).to_bytes(2, "little"))
    blob.extend([1, 1, 1, 1, 1, 1, 1])
    blob.append(method_count)
    for _ in range(method_count):
        blob.extend([0, 0, 0, 0])
    blob.append(0)
    blob.append(0)
    blob.append(0)
    blob.append(len(method_body_method_indexes))
    for method_index in method_body_method_indexes:
        blob.extend([method_index, 1, 1, 0, 1])
        blob.extend([1, Opcode.ReturnVoid.value])
        blob.extend([0, 0])
    return bytes(blob)


def _fixture_path(name: str) -> Path:
    # The fixtures directory is at the project root, not under src
    return Path(__file__).resolve().parents[4] / "fixtures" / "abc" / name


def test_parse_abc_and_load_abc_match_on_fixture_file() -> None:
    fixture = _fixture_path("Test.abc")
    by_parse = parse_abc(fixture.read_bytes())
    by_load = load_abc(str(fixture))
    assert by_parse.major_version == by_load.major_version
    assert by_parse.minor_version == by_load.minor_version
    assert len(by_parse.methods) == len(by_load.methods)
    assert len(by_parse.method_bodies) == len(by_load.method_bodies)
    assert len(by_parse.scripts) == len(by_load.scripts)


def test_parse_abc_method_body_links_are_structurally_consistent() -> None:
    abc = parse_abc(_fixture_path("Test.abc").read_bytes())
    for body in abc.method_bodies:
        assert 0 <= body.method < len(abc.methods)
        assert abc.methods[body.method].body is body
        assert abc.method_body_at(body.method) is body


def test_parse_abc_rejects_duplicate_method_body_entries() -> None:
    data = _minimal_abc([0, 0], method_count=1)
    with pytest.raises(InvalidABCCodeError, match="Duplicate method body"):
        parse_abc(data)


def test_parse_abc_rejects_out_of_range_method_body_method_index() -> None:
    data = _minimal_abc([1], method_count=1)
    with pytest.raises(InvalidABCCodeError, match="invalid method index"):
        parse_abc(data)


def test_parse_abc_rejects_trailing_bytes_after_valid_payload() -> None:
    valid = _minimal_abc([0], method_count=1)
    with pytest.raises(InvalidABCCodeError, match="trailing"):
        parse_abc(valid + b"\x00")
