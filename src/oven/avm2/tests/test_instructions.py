import pytest
from pathlib import Path
from oven.avm2 import ABCReader, ConstantPool, Instruction, MethodBody, Opcode
from oven.avm2.constant_pool import Multiname
from oven.avm2.enums import Index, MultinameKind


def test_parse_basic_instruction_sequence() -> None:
    code = bytes(
        [
            Opcode.GetLocal0.value,
            Opcode.PushScope.value,
            Opcode.PushString.value,
            1,
            Opcode.PushByte.value,
            5,
            Opcode.Add.value,
            Opcode.ReturnValue.value,
        ]
    )
    pool = ConstantPool([], [], [], ["", "Hello"], [], [], [])
    instructions = ABCReader(b"").parse_instructions(code, pool)
    assert [ins.opcode for ins in instructions] == [
        Opcode.GetLocal0,
        Opcode.PushScope,
        Opcode.PushString,
        Opcode.PushByte,
        Opcode.Add,
        Opcode.ReturnValue,
    ]
    assert instructions[2].operands == [""]
    assert instructions[3].operands == [5]


def test_read_real_avm2_dummy_file_parses_core_sections() -> None:
    abc_path = (
        Path(__file__).resolve().parents[4] / "fixtures" / "abc" / "Avm2Dummy.abc"
    )
    if not abc_path.exists():
        pytest.skip("Avm2Dummy.abc is not available in this environment")
    abc_file = ABCReader(abc_path.read_bytes()).read_abc_file()
    assert abc_file.major_version == 46
    assert abc_file.minor_version == 16
    assert len(abc_file.methods) == 2
    assert len(abc_file.method_bodies) == 2
    assert len(abc_file.scripts) == 1
    for body in abc_file.method_bodies:
        assert body.instructions
        assert body.max_stack > 0
        assert body.to_string(abc_file.constant_pool, show_offsets=True)
        assert body.to_function_calls(abc_file.constant_pool)


def test_opcode_metadata_sets_are_available() -> None:
    reader = ABCReader(b"")
    assert len(Opcode) > 0
    assert len(reader._NO_OPERAND_OPCODES) > 0
    assert Opcode.Add in Opcode
    assert isinstance(Opcode.Add in reader._NO_OPERAND_OPCODES, bool)
    assert reader._STACK_EFFECT_STATIC_TABLE[Opcode.Add.value] == (2, 1)


def test_parse_lookupswitch_instruction_operands() -> None:
    data = bytes(
        [Opcode.LookupSwitch.value, 100, 0, 0, 2, 10, 0, 0, 20, 0, 0, 251, 255, 255]
    )
    instructions = ABCReader(b"").parse_instructions(
        data, ConstantPool([], [], [], [], [], [], [])
    )
    assert len(instructions) == 1
    assert instructions[0].opcode == Opcode.LookupSwitch
    assert instructions[0].operands == [100, 2, [10, 20, -5]]


def test_parse_push_int_resolves_constant_pool_values() -> None:
    data = bytes([Opcode.PushInt.value, 1, Opcode.PushInt.value, 2])
    pool = ConstantPool(
        ints=[42, -100],
        uints=[],
        doubles=[],
        strings=[],
        namespaces=[],
        namespace_sets=[],
        multinames=[],
    )
    instructions = ABCReader(b"").parse_instructions(data, pool)
    assert len(instructions) == 2
    assert instructions[0].operands == [42]
    assert instructions[1].operands == [-100]


def test_method_body_string_and_function_call_serialization() -> None:
    instructions = [
        Instruction(Opcode.GetLocal0, [], 0),
        Instruction(Opcode.PushScope, [], 1),
        Instruction(Opcode.PushString, [1], 2),
        Instruction(Opcode.PushInt, [1], 4),
        Instruction(Opcode.Add, [], 6),
        Instruction(Opcode.ReturnValue, [], 7),
    ]
    body = MethodBody(
        method=0,
        max_stack=2,
        num_locals=1,
        init_scope_depth=1,
        max_scope_depth=2,
        code=b"",
        exceptions=[],
        traits=[],
        instructions=instructions,
    )
    pool = ConstantPool(
        ints=[42],
        uints=[],
        doubles=[],
        strings=["Hello", "World"],
        namespaces=[],
        namespace_sets=[],
        multinames=[
            Multiname(MultinameKind.QNAME, {"namespace": Index(0), "name": Index(0)}),
            Multiname(MultinameKind.QNAME, {"namespace": Index(0), "name": Index(1)}),
        ],
    )
    standard = body.to_string(pool, show_offsets=True)
    calls = body.to_function_calls(pool)
    assert "GetLocal0" in standard
    assert "PushScope" in standard
    assert "ReturnValue" in standard
    assert "GetLocal0()" in calls
    assert "ReturnValue()" in calls


def test_parse_invalid_and_truncated_code_raises() -> None:
    reader = ABCReader(b"")
    with pytest.raises(Exception):
        reader.parse_instructions(b"\xff", None)
    with pytest.raises(Exception):
        reader.parse_instructions(bytes([Opcode.CallProperty.value, 1]), None)
    with pytest.raises(ValueError):
        ABCReader(b"\x81\x81\x81\x81\x81").read_u30()


def test_parse_unknown_opcode_relaxed_mode_emits_nop_placeholder() -> None:
    reader = ABCReader(b"", verify_relaxed=True)
    instructions = reader.parse_instructions(b"\xff", None)
    assert len(instructions) == 1
    assert instructions[0].opcode == Opcode.Nop
    assert instructions[0].operands == []
    assert instructions[0].offset == 0
