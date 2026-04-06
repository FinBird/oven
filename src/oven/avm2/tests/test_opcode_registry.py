from __future__ import annotations

from oven.avm2.abc.opcode_registry import (
    DYNAMIC_STACK,
    FORM_MULTINAME_INDEX,
    FORM_NONE,
    FORM_RELATIVE_I24,
    FORM_TWO_U30_MULTINAME_COUNT,
    OPCODE_INFO_TABLE,
    OPERAND_FORM_BY_OPCODE,
    STACK_EFFECT_STATIC_TABLE,
    opcode_info,
)
from oven.avm2.enums import Opcode


def test_opcode_registry_table_shape_and_index_lookup() -> None:
    assert len(OPCODE_INFO_TABLE) == 256
    assert len(OPERAND_FORM_BY_OPCODE) == 256
    assert len(STACK_EFFECT_STATIC_TABLE) == 256
    add_info = opcode_info(Opcode.Add)
    assert add_info.opcode == Opcode.Add.value
    assert add_info.name == "Add"
    assert add_info.operand_form == FORM_NONE
    jump_info = opcode_info(Opcode.Jump)
    assert jump_info.operand_form == FORM_RELATIVE_I24
    assert jump_info.is_branch is True
    assert jump_info.is_conditional_branch is False
    unknown = opcode_info(254)
    assert unknown.opcode == 254
    assert unknown.name.startswith("UNKNOWN_")


def test_opcode_registry_operand_forms_and_dynamic_stack_hints() -> None:
    get_property = opcode_info(Opcode.GetProperty)
    assert get_property.operand_form == FORM_MULTINAME_INDEX
    assert get_property.stack_pops == DYNAMIC_STACK
    assert get_property.has_dynamic_stack is True
    call_property = opcode_info(Opcode.CallProperty)
    assert call_property.operand_form == FORM_TWO_U30_MULTINAME_COUNT
    assert call_property.has_dynamic_stack is True


def test_opcode_registry_static_stack_effect_table_alignment() -> None:
    add_effect = STACK_EFFECT_STATIC_TABLE[Opcode.Add.value]
    assert add_effect == (2, 1)
    return_void_effect = STACK_EFFECT_STATIC_TABLE[Opcode.ReturnVoid.value]
    assert return_void_effect == (0, 0)
    assert STACK_EFFECT_STATIC_TABLE[Opcode.GetProperty.value] is None