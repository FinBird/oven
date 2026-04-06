"""Updated decompiler API tests using current AVM2 entrypoints."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from oven.avm2 import ABCFile, parse, parse_abc
from oven.avm2.config import ParseMode
from oven.avm2.decompiler import (
    AS3Emitter,
    MethodContext,
    _build_method_context,
    _build_method_owner_map,
    _method_to_nf,
    _render_layout_method_signature,
    decompile_abc,
    decompile_method,
)
from oven.avm2.decompiler.engine import _collect_class_method_entries
from oven.avm2.enums import Instruction, Opcode
from oven.avm2.methods import MethodBody
from oven.core.ast import Node


def _body(instructions: list[Instruction], code_size: int = 32) -> MethodBody:
    return MethodBody(
        method=0,
        max_stack=8,
        num_locals=4,
        init_scope_depth=0,
        max_scope_depth=8,
        code=b"\x00" * code_size,
        exceptions=[],
        traits=[],
        instructions=instructions,
    )


def _fixture_bytes(filename: str) -> bytes:
    root = Path(__file__).resolve().parents[4]
    return (root / "fixtures" / "abc" / filename).read_bytes()


def _angel_world_method(
    method_name: str,
) -> tuple[ABCFile, Any, MethodBody, MethodContext]:
    abc = parse(_fixture_bytes("AngelClientLibs.abc"), mode=ParseMode.RELAXED)
    owner_map = _build_method_owner_map(abc)
    for class_index in range(len(abc.instances)):
        _, class_name, entries, _ = _collect_class_method_entries(abc, class_index)
        if class_name != "AngelWorld":
            continue
        entry = next(entry for entry in entries if entry.method_name == method_name)
        body = abc.method_body_at(entry.method_index)
        assert body is not None
        context = _build_method_context(abc, body, owner_map)
        return abc, entry, body, context
    raise AssertionError("AngelWorld not found")


def test_decompile_method_emits_basic_as3_statements() -> None:
    body = _body(
        [
            Instruction(Opcode.PushByte, [1], 0),
            Instruction(Opcode.PushByte, [2], 1),
            Instruction(Opcode.Add, [], 2),
            Instruction(Opcode.SetLocal1, [], 3),
            Instruction(Opcode.ReturnVoid, [], 4),
        ],
        code_size=8,
    )
    text = decompile_method(body)
    assert (
        "local1 = (1 + 2);" in text
        or "local1 = 1 + 2;" in text
        or "local1 = 3;" in text
    )


def test_decompile_method_supports_hex_integer_format() -> None:
    body = _body(
        [
            Instruction(Opcode.PushByte, [15], 0),
            Instruction(Opcode.PushByte, [16], 1),
            Instruction(Opcode.Add, [], 2),
            Instruction(Opcode.SetLocal1, [], 3),
            Instruction(Opcode.ReturnVoid, [], 4),
        ],
        code_size=8,
    )
    text = decompile_method(body, int_format="hex")
    assert "0x" in text


def test_decompile_abc_method_index_returns_single_method() -> None:
    abc_bytes = _fixture_bytes("Test.abc")
    text = decompile_abc(abc_bytes, method_idx=0)
    assert "// method 0" in text
    assert text.count("// method ") == 1


def test_decompile_abc_rejects_invalid_layout() -> None:
    abc_bytes = _fixture_bytes("Test.abc")
    with pytest.raises(ValueError):
        decompile_abc(abc_bytes, layout="invalid")


def test_decompile_abc_rejects_invalid_integer_format() -> None:
    abc_bytes = _fixture_bytes("Test.abc")
    with pytest.raises(ValueError):
        decompile_abc(abc_bytes, int_format="oct")


def test_decompile_abc_classes_layout_smoke() -> None:
    abc_bytes = _fixture_bytes("abcdump.abc")
    text = decompile_abc(abc_bytes, style="semantic", layout="classes")
    assert "class " in text or "interface " in text


def test_angel_world_closure_v1_avoids_empty_method_placeholders() -> None:
    abc, _, body, context = _angel_world_method("changeSceneErrorHandler")
    text = decompile_method(
        body,
        style="semantic",
        abc=abc,
        method_context=context,
        skip_fast_path=True,
    )
    assert "switch (back.code)" in text
    assert "function" in text


def test_as3_emitter_semantic_context_restores_names() -> None:
    ast = Node(
        "begin",
        children=[
            Node("set_local", children=[3, Node("integer", children=[1])]),
            Node("return_value", children=[Node("get_local", children=[0])]),
        ],
    )
    context = MethodContext(
        method_index=1,
        method_name="demo",
        owner_kind="instance",
        owner_name="Demo",
        param_names=("flag",),
        has_param_names=True,
        num_locals=4,
    )
    text = AS3Emitter(style="semantic", method_context=context).emit(ast)
    assert "var local3" in text
    assert "return this;" in text


def test_method_to_nf_preserves_multi_arm_switch_for_abcdump() -> None:
    abc = parse_abc(_fixture_bytes("abcdump.abc"))
    body = abc.method_body_at(26)
    assert body is not None
    nf = _method_to_nf(body)
    stack = [nf]
    switch_label_counts: list[int] = []
    while stack:
        node = stack.pop()
        if not isinstance(node, Node):
            continue
        if (
            node.type == "switch"
            and len(node.children) > 1
            and isinstance(node.children[1], Node)
        ):
            labels = [
                child
                for child in node.children[1].children
                if isinstance(child, Node) and child.type in {"case", "default"}
            ]
            switch_label_counts.append(len(labels))
        for child in node.children:
            if isinstance(child, Node):
                stack.append(child)
    assert switch_label_counts
    assert max(switch_label_counts) >= 10


def test_angel_world_initialize_preserves_rest_parameter_name() -> None:
    abc, entry, body, context = _angel_world_method("initialize")
    signature = _render_layout_method_signature(
        class_name="AngelWorld",
        entry=entry,
        method_info=abc.methods[entry.method_index],
        context=context,
    )
    text = decompile_method(
        body,
        style="semantic",
        abc=abc,
        method_context=context,
        skip_fast_path=True,
    )
    assert signature == "public function initialize(... rest):void"
    assert "rest[0]" in text
    assert "var local1" not in text


def test_angel_world_on_scene_data_init_rewrites_string_switch_selector() -> None:
    abc, _, body, context = _angel_world_method("onSceneDataInit")
    text = decompile_method(
        body,
        style="semantic",
        abc=abc,
        method_context=context,
        skip_fast_path=True,
    )
    assert "switch (" in text
    assert 'case "御风术施法成功。":' in text
    assert 'case "辟水咒施法成功。":' in text
    assert 'case "扫帚飞行施法成功。":' in text
    assert "switch (3)" not in text


def test_angel_world_change_scene_preserves_three_term_short_circuit() -> None:
    _, _, body, _ = _angel_world_method("changeScene")
    nf = _method_to_nf(body)

    def _has_expected_guard(node: object) -> bool:
        if not isinstance(node, Node):
            return False
        if node.type != "and" or len(node.children) < 2:
            return False
        left = node.children[0]
        right = node.children[1]
        if not isinstance(left, Node) or not isinstance(right, Node):
            return False
        if left.type != ">" or right.type != "and" or len(right.children) < 2:
            return False
        inner_left = right.children[0]
        inner_right = right.children[1]
        if not isinstance(inner_left, Node) or not isinstance(inner_right, Node):
            return False
        if inner_left.type != "<" or inner_right.type != "!":
            return False
        return True

    stack = [nf]
    while stack:
        node = stack.pop()
        if _has_expected_guard(node):
            return
        if isinstance(node, Node):
            for child in node.children:
                if isinstance(child, Node):
                    stack.append(child)
    raise AssertionError("expected three-term short-circuit guard not found")
