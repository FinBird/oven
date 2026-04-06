from __future__ import annotations

from oven.avm2.abc.decoder import InstructionDecoder
from oven.avm2.constant_pool import ConstantPool, NamespaceInfo
from oven.avm2.enums import NamespaceKind, Opcode


def test_decoder_fast_readers_cover_i24_and_u30_edges() -> None:
    assert InstructionDecoder._read_i24_fast(bytes([254, 255, 255]), 0) == -2
    assert InstructionDecoder._read_i24_fast(bytes([5, 0, 0]), 0) == 5
    assert InstructionDecoder._read_u30_data_fast(bytes([127]), 0) == (127, 1)
    assert InstructionDecoder._read_u30_data_fast(bytes([129, 1]), 0) == (129, 2)


def test_decoder_operand_form_tables_cover_expected_opcode_kinds() -> None:
    form_by_opcode = InstructionDecoder._OPERAND_FORM_BY_OPCODE
    assert form_by_opcode[Opcode.ReturnVoid.value] == InstructionDecoder.FORM_NONE
    assert form_by_opcode[Opcode.Jump.value] == InstructionDecoder.FORM_RELATIVE_I24
    assert (
        form_by_opcode[Opcode.LookupSwitch.value]
        == InstructionDecoder.FORM_LOOKUPSWITCH
    )
    assert form_by_opcode[Opcode.PushByte.value] == InstructionDecoder.FORM_S8
    assert form_by_opcode[Opcode.GetScopeObject.value] == InstructionDecoder.FORM_U8
    assert form_by_opcode[Opcode.GetLocal.value] == InstructionDecoder.FORM_U30_PLAIN
    assert form_by_opcode[Opcode.Dxns.value] == InstructionDecoder.FORM_U30_STRING
    assert form_by_opcode[Opcode.PushInt.value] == InstructionDecoder.FORM_POOL_INDEX
    assert (
        form_by_opcode[Opcode.GetProperty.value]
        == InstructionDecoder.FORM_MULTINAME_INDEX
    )
    assert (
        form_by_opcode[Opcode.CallMethod.value] == InstructionDecoder.FORM_TWO_U30_PLAIN
    )
    assert (
        form_by_opcode[Opcode.CallProperty.value]
        == InstructionDecoder.FORM_TWO_U30_MULTINAME_COUNT
    )
    assert form_by_opcode[Opcode.Debug.value] == InstructionDecoder.FORM_DEBUG
    assert form_by_opcode[Opcode.DebugLine.value] == InstructionDecoder.FORM_DEBUGLINE


def test_decoder_relaxed_unknown_opcode_emits_nop() -> None:
    decoder = InstructionDecoder(verify_relaxed=True)
    instructions = decoder.parse_instructions(b"\xff", None)
    assert len(instructions) == 1
    assert instructions[0].opcode == Opcode.Nop
    assert instructions[0].offset == 0


def test_decoder_strict_unknown_opcode_raises() -> None:
    decoder = InstructionDecoder(verify_relaxed=False)
    try:
        decoder.parse_instructions(b"\xff", None)
        assert False, "expected InvalidABCCodeError"
    except Exception as exc:
        assert exc.__class__.__name__ == "InvalidABCCodeError"


def test_decoder_uses_preloaded_tables_without_resolve_index_calls() -> None:
    decoder = InstructionDecoder(verify_relaxed=False)
    pool = ConstantPool(
        ints=[7],
        uints=[],
        doubles=[],
        strings=["hello"],
        namespaces=[NamespaceInfo(NamespaceKind.NAMESPACE, 1)],
        namespace_sets=[],
        multinames=[],
    )

    def _forbidden_resolve_index(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("resolve_index must not be called in decoder hot path")

    from unittest.mock import patch

    with patch.object(pool, "resolve_index", _forbidden_resolve_index):
        data = bytes(
            [
                Opcode.PushInt.value,
                1,
                Opcode.PushString.value,
                1,
                Opcode.PushNamespace.value,
                1,
                Opcode.ReturnVoid.value,
            ]
        )
        instructions = decoder.parse_instructions(data, pool)
        assert [inst.opcode for inst in instructions] == [
            Opcode.PushInt,
            Opcode.PushString,
            Opcode.PushNamespace,
            Opcode.ReturnVoid,
        ]
    assert instructions[0].operands == [7]
    assert instructions[1].operands == ["hello"]
    assert instructions[2].operands == ["NAMESPACE::hello"]
