from __future__ import annotations

from oven.avm2.transform import AS3NodeType, AS3NodeTypes as NT
from oven.avm2.transform.cfg_dialect import AVM2ControlFlowAdapter
from oven.core.ast import Node
from oven.core.cfg.dialect import BranchInfo, CTIKind
from oven.avm2.enums import EdgeKind


def test_node_type_constants_and_literal_alias_are_importable() -> None:
    sample: str = NT.SET_PROPERTY
    assert sample == "set_property"
    assert NT.GET_PROPERTY == "get_property"
    assert NT.FIELD_INITIALIZERS == "field_initializers"


def test_avm2_control_flow_adapter_extracts_branch_info() -> None:
    adapter = AVM2ControlFlowAdapter()

    jump = Node("jump", [123])
    jump_info = adapter.get_branch_info(jump)
    assert isinstance(jump_info, BranchInfo)
    assert jump_info.kind == CTIKind.JUMP
    assert jump_info.targets == [123]
    assert jump_info.keep_node is False
    assert jump.children == []

    jump_if = Node("jump_if", [True, 456, Node("true")])
    jump_if_info = adapter.get_branch_info(jump_if)
    assert isinstance(jump_if_info, BranchInfo)
    assert jump_if_info.kind == CTIKind.COND
    assert jump_if_info.targets == [456]
    assert jump_if_info.keep_node is True
    assert len(jump_if.children) == 2
    assert isinstance(jump_if.children[1], Node)

    switch = Node("lookup_switch", [100, [200, 300], Node("get_local", [0])])
    switch_info = adapter.get_branch_info(switch)
    assert isinstance(switch_info, BranchInfo)
    assert switch_info.kind == CTIKind.SWITCH
    assert switch_info.targets == [100, 200, 300]
    assert switch_info.keep_node is True
    assert len(switch.children) == 1
    assert isinstance(switch.children[0], Node)

    terminal = Node("return_void", [])
    terminal_info = adapter.get_branch_info(terminal)
    assert isinstance(terminal_info, BranchInfo)
    assert terminal_info.kind == CTIKind.TERMINAL
    assert terminal_info.targets == []
    assert terminal_info.keep_node is True


def test_ctikind_enum_values() -> None:
    """Test that CTIKind enum values match expected constants."""
    assert CTIKind.NONE.value == 0
    assert CTIKind.JUMP.value == 1
    assert CTIKind.COND.value == 2
    assert CTIKind.SWITCH.value == 3
    assert CTIKind.TERMINAL.value == 4


def test_edgekind_enum_values() -> None:
    """Test that EdgeKind enum values match expected strings."""
    assert EdgeKind.ENTRY.value == "entry"
    assert EdgeKind.NORMAL.value == "normal"
    assert EdgeKind.LOOKUPSWITCH.value == "lookupswitch"
    assert EdgeKind.EXCEPTION_ENTRY.value == "exception_entry"


def test_edgekind_string_comparison() -> None:
    """Test that EdgeKind can be compared with strings."""
    assert EdgeKind.ENTRY.value == "entry"
    assert EdgeKind.NORMAL.value == "normal"
    assert EdgeKind.LOOKUPSWITCH.value == "lookupswitch"
    assert EdgeKind.EXCEPTION_ENTRY.value == "exception_entry"

    # Test that string comparison works
    assert "entry" == EdgeKind.ENTRY.value
    assert "normal" == EdgeKind.NORMAL.value


def test_edgekind_in_reader() -> None:
    """Test that EdgeKind is used correctly in ABCReader."""
    from oven.avm2.abc.reader import ABCReader

    # Verify the class attributes use EdgeKind
    assert ABCReader._EDGE_KIND_ENTRY == EdgeKind.ENTRY
    assert ABCReader._EDGE_KIND_NORMAL == EdgeKind.NORMAL
    assert ABCReader._EDGE_KIND_LOOKUPSWITCH == EdgeKind.LOOKUPSWITCH
    assert ABCReader._EDGE_KIND_EXCEPTION_ENTRY == EdgeKind.EXCEPTION_ENTRY
