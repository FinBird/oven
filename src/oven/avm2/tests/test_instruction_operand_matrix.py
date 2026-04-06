"""
Instruction operand form matrix tests for less-used AVM2 opcodes.
"""

from __future__ import annotations

from oven.avm2 import ABCReader, ConstantPool, Opcode
from oven.avm2.constant_pool import Multiname, NamespaceInfo
from oven.avm2.enums import Index, MultinameKind, NamespaceKind


def _pool_for_operand_matrix() -> ConstantPool:
    strings = ["name", "dbg"]
    namespaces = [NamespaceInfo(NamespaceKind.NAMESPACE, 1)]
    multinames = [
        Multiname(MultinameKind.QNAME, {"namespace": Index(1), "name": Index(1)})
    ]
    return ConstantPool(
        ints=[],
        uints=[],
        doubles=[],
        strings=strings,
        namespaces=namespaces,
        namespace_sets=[],
        multinames=multinames,
    )


def test_parse_instructions_for_less_used_opcodes_parses_operands() -> None:
    reader = ABCReader(b"")
    pool = _pool_for_operand_matrix()
    code = bytes(
        [
            Opcode.NewFunction.value,
            1,
            Opcode.NewClass.value,
            2,
            Opcode.CallStatic.value,
            3,
            4,
            Opcode.CallMethod.value,
            5,
            6,
            Opcode.ConstructProp.value,
            1,
            2,
            Opcode.HasNext2.value,
            7,
            8,
            Opcode.ApplyType.value,
            2,
            Opcode.NewCatch.value,
            3,
            Opcode.Debug.value,
            1,
            2,
            9,
            10,
            Opcode.Dxns.value,
            2,
            Opcode.DebugFile.value,
            2,
            Opcode.PushNamespace.value,
            1,
            Opcode.BkptLine.value,
            11,
            Opcode.GetOuterScope.value,
            12,
            Opcode.ReturnVoid.value,
        ]
    )
    instructions = reader.parse_instructions(code, pool)
    opcodes = [inst.opcode for inst in instructions]
    assert opcodes == [
        Opcode.NewFunction,
        Opcode.NewClass,
        Opcode.CallStatic,
        Opcode.CallMethod,
        Opcode.ConstructProp,
        Opcode.HasNext2,
        Opcode.ApplyType,
        Opcode.NewCatch,
        Opcode.Debug,
        Opcode.Dxns,
        Opcode.DebugFile,
        Opcode.PushNamespace,
        Opcode.BkptLine,
        Opcode.GetOuterScope,
        Opcode.ReturnVoid,
    ]
    assert instructions[0].operands == [1]
    assert instructions[1].operands == [2]
    assert instructions[2].operands == [3, 4]
    assert instructions[3].operands == [5, 6]
    assert len(instructions[4].operands) == 2
    assert isinstance(instructions[4].operands[0], str)
    assert "name" in instructions[4].operands[0]
    assert instructions[4].operands[1] == 2
    assert instructions[5].operands == [7, 8]
    assert instructions[6].operands == [2]
    assert instructions[7].operands == [3]
    assert instructions[8].operands == [1, "dbg", 9, 10]
    assert instructions[9].operands == ["dbg"]
    assert instructions[10].operands == ["dbg"]
    assert instructions[11].operands == ["NAMESPACE::name"]
    assert instructions[12].operands == [11]
    assert instructions[13].operands == [12]
    assert instructions[14].operands == []


def test_parse_instructions_dxnslate_has_no_operands() -> None:
    reader = ABCReader(b"")
    instructions = reader.parse_instructions(bytes([Opcode.DxnsLate.value]), None)
    assert len(instructions) == 1
    assert instructions[0].opcode == Opcode.DxnsLate
    assert instructions[0].operands == []


def test_parse_instructions_pushbyte_is_signed_i8() -> None:
    reader = ABCReader(b"")
    code = bytes(
        [
            Opcode.PushByte.value,
            255,
            Opcode.PushByte.value,
            127,
            Opcode.ReturnVoid.value,
        ]
    )
    instructions = reader.parse_instructions(code, None)
    assert [inst.opcode for inst in instructions] == [
        Opcode.PushByte,
        Opcode.PushByte,
        Opcode.ReturnVoid,
    ]
    assert instructions[0].operands == [-1]
    assert instructions[1].operands == [127]


def test_parse_instructions_for_plain_u30_constructor_and_call_opcodes() -> None:
    reader = ABCReader(b"")
    code = bytes(
        [
            Opcode.Call.value,
            3,
            Opcode.Construct.value,
            2,
            Opcode.ConstructSuper.value,
            4,
            Opcode.NewClass.value,
            5,
            Opcode.NewFunction.value,
            6,
            Opcode.ReturnVoid.value,
        ]
    )
    instructions = reader.parse_instructions(code, None)
    assert [inst.opcode for inst in instructions] == [
        Opcode.Call,
        Opcode.Construct,
        Opcode.ConstructSuper,
        Opcode.NewClass,
        Opcode.NewFunction,
        Opcode.ReturnVoid,
    ]
    assert instructions[0].operands == [3]
    assert instructions[1].operands == [2]
    assert instructions[2].operands == [4]
    assert instructions[3].operands == [5]
    assert instructions[4].operands == [6]


def test_parse_instructions_branch_operand_shapes_for_jump_and_lookupswitch() -> None:
    reader = ABCReader(b"")
    code = bytes(
        [
            Opcode.Jump.value,
            254,
            255,
            255,
            Opcode.LookupSwitch.value,
            5,
            0,
            0,
            1,
            2,
            0,
            0,
            255,
            255,
            255,
            Opcode.ReturnVoid.value,
        ]
    )
    instructions = reader.parse_instructions(code, None)
    assert instructions[0].opcode == Opcode.Jump
    assert instructions[0].operands == [-2]
    assert instructions[1].opcode == Opcode.LookupSwitch
    assert instructions[1].operands == [5, 1, [2, -1]]
