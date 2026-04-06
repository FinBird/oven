from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest

from oven.avm2 import (
    ABCFile,
    ParseMode,
    VerifyProfile,
    decompile,
    parse,
    parse_abc,
    parse_file,
)
from oven.avm2.enums import Opcode
from oven.avm2.exceptions import InvalidABCCodeError


def _join_type_conflict_abc() -> bytes:
    code = bytes(
        [
            Opcode.PushTrue.value,
            Opcode.IfTrue.value,
            6,
            0,
            0,
            Opcode.PushByte.value,
            1,
            Opcode.Jump.value,
            1,
            0,
            0,
            Opcode.PushTrue.value,
            Opcode.Pop.value,
            Opcode.ReturnVoid.value,
        ]
    )
    blob = bytearray()
    blob.extend((16).to_bytes(2, "little"))
    blob.extend((46).to_bytes(2, "little"))
    blob.extend([1, 1, 1, 1, 1, 1, 1])
    blob.append(1)
    blob.extend([0, 0, 0, 0])
    blob.append(0)
    blob.append(0)
    blob.append(0)
    blob.append(1)
    blob.extend([0, 1, 0, 0, 1])
    blob.append(len(code))
    blob.extend(code)
    blob.extend([0, 0])
    return bytes(blob)


def _qname_method_body_abc(
    *, name: str, code: bytes, max_stack: int = 1, num_locals: int = 0
) -> bytes:
    name_bytes = name.encode("utf-8")
    blob = bytearray()
    blob.extend((16).to_bytes(2, "little"))
    blob.extend((46).to_bytes(2, "little"))
    blob.append(1)
    blob.append(1)
    blob.append(1)
    blob.append(2)
    blob.append(len(name_bytes))
    blob.extend(name_bytes)
    blob.append(2)
    blob.append(8)
    blob.append(1)
    blob.append(1)
    blob.append(2)
    blob.append(7)
    blob.append(1)
    blob.append(1)
    blob.append(1)
    blob.extend([0, 0, 0, 0])
    blob.append(0)
    blob.append(0)
    blob.append(0)
    blob.append(1)
    blob.extend([0, max_stack, num_locals, 0, 1])
    blob.append(len(code))
    blob.extend(code)
    blob.extend([0, 0])
    return bytes(blob)


def test_parse_and_parse_file_default_entrypoints_remain_usable(
    fixture_bytes: Callable[[str], bytes],
) -> None:
    data = fixture_bytes("Test.abc")
    abc_from_bytes = parse(data)
    abc_from_file = parse_file(
        Path(__file__).resolve().parents[4] / "fixtures" / "abc" / "Test.abc"
    )
    assert isinstance(abc_from_bytes, ABCFile)
    assert isinstance(abc_from_file, ABCFile)
    assert len(abc_from_bytes.methods) > 0
    assert len(abc_from_file.methods) > 0


def test_parse_and_parse_abc_default_behavior_align_on_unknown_opcode(
    build_single_method_abc: Callable[[bytes, int, int], bytes],
) -> None:
    data = build_single_method_abc(bytes([255, Opcode.ReturnVoid.value]), 1, 0)
    with pytest.raises(InvalidABCCodeError, match="Unknown opcode"):
        parse_abc(data)
    with pytest.raises(InvalidABCCodeError, match="Unknown opcode"):
        parse(data)


def test_parse_mode_strict_rejects_invalid_branch_target_fixture(
    fixture_bytes: Callable[[str], bytes],
) -> None:
    data = fixture_bytes("Test.abc")
    with pytest.raises(InvalidABCCodeError, match="Invalid branch target offset"):
        parse(data, mode=ParseMode.STRICT)


@pytest.mark.parametrize(
    ("profile", "should_succeed"),
    [
        (VerifyProfile.STRICT, False),
        (VerifyProfile.STACK_ONLY, True),
        (VerifyProfile.BRANCH_ONLY, False),
        (VerifyProfile.RELAXED_FULL, True),
    ],
)
def test_parse_profile_matrix_on_invalid_branch_target_fixture(
    fixture_bytes: Callable[[str], bytes], profile: VerifyProfile, should_succeed: bool
) -> None:
    data = fixture_bytes("Test.abc")
    if should_succeed:
        abc = parse(data, profile=profile)
        assert len(abc.methods) > 0
    else:
        with pytest.raises(InvalidABCCodeError, match="Invalid branch target offset"):
            parse(data, profile=profile)


def test_parse_abc_compat_entry_accepts_verify_profile(
    fixture_bytes: Callable[[str], bytes],
) -> None:
    data = fixture_bytes("Test.abc")
    abc = parse_abc(data, verify_profile=VerifyProfile.STACK_ONLY)
    assert len(abc.methods) > 0


def test_decompile_accepts_bytes_path_and_abcfile(
    fixture_bytes: Callable[[str], bytes],
) -> None:
    fixture = Path(__file__).resolve().parents[4] / "fixtures" / "abc" / "Avm2Dummy.abc"
    data = fixture_bytes("Avm2Dummy.abc")
    abc = parse(data)
    by_bytes = decompile(data, method_idx=0)
    by_path = decompile(fixture, method_idx=0)
    by_abc = decompile(abc, method_idx=0)
    assert "// method 0" in by_bytes
    assert "// method 0" in by_path
    assert "// method 0" in by_abc


def test_relaxed_profile_accepts_invalid_lookupswitch_target_by_default(
    build_invalid_lookupswitch_abc: Callable[[], bytes],
) -> None:
    data = build_invalid_lookupswitch_abc()
    abc = parse_abc(data, verify_profile=VerifyProfile.RELAXED_FULL)
    assert len(abc.methods) == 1


def test_relaxed_profile_can_enable_strict_lookupswitch(
    build_invalid_lookupswitch_abc: Callable[[], bytes],
) -> None:
    data = build_invalid_lookupswitch_abc()
    with pytest.raises(InvalidABCCodeError, match="Invalid branch target offset"):
        parse_abc(
            data, verify_profile=VerifyProfile.RELAXED_FULL, strict_lookupswitch=True
        )


def test_strict_relaxed_joins_profile_accepts_join_type_conflict_fixture() -> None:
    data = _join_type_conflict_abc()
    with pytest.raises(InvalidABCCodeError, match="stack type mismatch"):
        parse_abc(data, verify_profile=VerifyProfile.STRICT)
    abc = parse_abc(data, verify_profile="strict_relaxed_joins")
    assert len(abc.methods) == 1


def test_strict_precise_joins_profile_is_exposed_in_public_api() -> None:
    data = _join_type_conflict_abc()
    with pytest.raises(InvalidABCCodeError, match="stack type mismatch"):
        parse_abc(data, verify_profile="strict_precise_joins")


def test_precision_enhanced_mode_tightens_findproperty_join_typing() -> None:
    code = bytes(
        [
            Opcode.PushTrue.value,
            Opcode.IfTrue.value,
            6,
            0,
            0,
            Opcode.FindProperty.value,
            1,
            Opcode.Jump.value,
            2,
            0,
            0,
            Opcode.PushByte.value,
            1,
            Opcode.Pop.value,
            Opcode.ReturnVoid.value,
        ]
    )
    data = _qname_method_body_abc(name="x", code=code, max_stack=1, num_locals=0)
    abc = parse_abc(data, verify_stack=True)
    assert len(abc.methods) == 1
    with pytest.raises(InvalidABCCodeError, match="stack type mismatch"):
        parse_abc(data, verify_stack=True, precision_enhanced=True)


def test_precision_enhanced_mode_tightens_astype_join_typing() -> None:
    code = bytes(
        [
            Opcode.PushTrue.value,
            Opcode.IfTrue.value,
            7,
            0,
            0,
            Opcode.PushNull.value,
            Opcode.AsType.value,
            1,
            Opcode.Jump.value,
            2,
            0,
            0,
            Opcode.PushByte.value,
            1,
            Opcode.Pop.value,
            Opcode.ReturnVoid.value,
        ]
    )
    data = _qname_method_body_abc(name="String", code=code, max_stack=1, num_locals=0)
    abc = parse_abc(data, verify_stack=True)
    assert len(abc.methods) == 1
    with pytest.raises(InvalidABCCodeError, match="stack type mismatch"):
        parse_abc(data, verify_stack=True, precision_enhanced=True)


def test_parse_entrypoint_accepts_precision_enhanced_flag() -> None:
    code = bytes(
        [
            Opcode.PushTrue.value,
            Opcode.IfTrue.value,
            6,
            0,
            0,
            Opcode.FindProperty.value,
            1,
            Opcode.Jump.value,
            2,
            0,
            0,
            Opcode.PushByte.value,
            1,
            Opcode.Pop.value,
            Opcode.ReturnVoid.value,
        ]
    )
    data = _qname_method_body_abc(name="x", code=code, max_stack=1, num_locals=0)
    abc = parse(data, profile=VerifyProfile.STRICT)
    assert len(abc.methods) == 1
    with pytest.raises(InvalidABCCodeError, match="stack type mismatch"):
        parse(data, profile=VerifyProfile.STRICT, precision_enhanced=True)
