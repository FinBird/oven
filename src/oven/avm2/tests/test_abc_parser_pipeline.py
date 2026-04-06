from __future__ import annotations
import pytest
from oven.avm2 import ABCReader, load_abc, parse_abc
from oven.avm2.tests.abc_testkit import ABCFixture, abc_fixtures

_FIXTURES = abc_fixtures()


@pytest.mark.skipif(not _FIXTURES, reason="No ABC fixtures available")
@pytest.mark.parametrize("fixture", _FIXTURES, ids=lambda f: f.name)
def test_parse_entrypoints_produce_consistent_top_level_structure(
    fixture: ABCFixture,
) -> None:
    parsed = parse_abc(fixture.read_bytes())
    loaded = load_abc(fixture.path)
    assert parsed.major_version == loaded.major_version
    assert parsed.minor_version == loaded.minor_version
    assert len(parsed.methods) == len(loaded.methods)
    assert len(parsed.method_bodies) == len(loaded.method_bodies)
    assert len(parsed.instances) == len(loaded.instances)
    assert len(parsed.classes) == len(loaded.classes)
    assert len(parsed.scripts) == len(loaded.scripts)


@pytest.mark.skipif(not _FIXTURES, reason="No ABC fixtures available")
@pytest.mark.parametrize("fixture", _FIXTURES, ids=lambda f: f.name)
def test_method_body_instruction_offsets_are_monotonic_and_in_bounds(
    fixture: ABCFixture,
) -> None:
    abc = parse_abc(fixture.read_bytes())
    for body in abc.method_bodies:
        offsets = [inst.offset for inst in body.instructions]
        assert offsets == sorted(offsets)
        assert len(offsets) == len(set(offsets))
        if offsets:
            assert offsets[0] >= 0
            assert offsets[-1] < len(body.code)


@pytest.mark.skipif(not _FIXTURES, reason="No ABC fixtures available")
@pytest.mark.parametrize("fixture", _FIXTURES, ids=lambda f: f.name)
def test_reparse_method_body_code_matches_stored_instruction_stream(
    fixture: ABCFixture,
) -> None:
    abc = parse_abc(fixture.read_bytes())
    reader = ABCReader(b"")
    for body in abc.method_bodies:
        reparsed = reader.parse_instructions(body.code, abc.constant_pool)
        assert [inst.opcode for inst in reparsed] == [
            inst.opcode for inst in body.instructions
        ]
        assert [inst.offset for inst in reparsed] == [
            inst.offset for inst in body.instructions
        ]
        assert [inst.operands for inst in reparsed] == [
            inst.operands for inst in body.instructions
        ]


@pytest.mark.skipif(not _FIXTURES, reason="No ABC fixtures available")
@pytest.mark.parametrize("fixture", _FIXTURES, ids=lambda f: f.name)
def test_method_body_index_lookup_returns_linked_body_instances(
    fixture: ABCFixture,
) -> None:
    abc = parse_abc(fixture.read_bytes())
    for body in abc.method_bodies:
        assert abc.method_body_at(body.method) is body
