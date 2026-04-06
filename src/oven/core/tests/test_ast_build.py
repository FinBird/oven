"""Test AST building functionality."""

from __future__ import annotations

import pytest
from oven.core.ast import Node
from oven.avm2.transform.ast_build import ASTBuild
from oven.avm2.enums import Opcode, Instruction


class TestASTBuild:
    """Test ASTBuild transformation."""

    def test_ast_build_basic(self) -> None:
        """Test basic AST building."""
        node = Node("test", [1, 2, 3])
        assert node.type == "test"
        assert node.children == [1, 2, 3]

    def test_ast_build_with_metadata(self) -> None:
        """Test AST building with metadata."""
        metadata = {"key": "value"}
        node = Node("test", [1, 2, 3], metadata=metadata)
        assert node.metadata == metadata

    def test_ast_build_nested(self) -> None:
        """Test building nested AST structures."""
        child1 = Node("child1", [1])
        child2 = Node("child2", [2])
        parent = Node("parent", [child1, child2])

        assert len(parent) == 2
        assert parent[0].type == "child1"
        assert parent[1].type == "child2"

    def test_get_local_instructions(self) -> None:
        """Test GetLocal0-3 and GetLocal instructions."""
        instructions = [
            Instruction(offset=0, opcode=Opcode.GetLocal0, operands=[]),
        ]
        builder = ASTBuild()
        ast, _, _ = builder.transform(instructions, None)

        assert len(ast.children) == 1
        assert ast.children[0].type == "get_local"
        assert ast.children[0].children[0] == 0

    def test_set_local_instructions(self) -> None:
        """Test SetLocal0-3 and SetLocal instructions."""
        instructions = [
            Instruction(offset=0, opcode=Opcode.PushByte, operands=[42]),
            Instruction(offset=1, opcode=Opcode.SetLocal0, operands=[]),
        ]
        builder = ASTBuild()
        ast, _, _ = builder.transform(instructions, None)

        assert len(ast.children) == 1
        assert ast.children[0].type == "set_local"
        assert ast.children[0].children[0] == 0

    def test_push_literals(self) -> None:
        """Test various push literal instructions."""
        instructions = [
            Instruction(offset=0, opcode=Opcode.PushByte, operands=[10]),
            Instruction(offset=1, opcode=Opcode.PushShort, operands=[100]),
            Instruction(offset=2, opcode=Opcode.PushInt, operands=[1000]),
            Instruction(offset=3, opcode=Opcode.PushUint, operands=[10000]),
            Instruction(offset=4, opcode=Opcode.PushDouble, operands=[3.14]),
            Instruction(offset=5, opcode=Opcode.PushString, operands=["hello"]),
            Instruction(offset=6, opcode=Opcode.PushTrue, operands=[]),
            Instruction(offset=7, opcode=Opcode.PushFalse, operands=[]),
            Instruction(offset=8, opcode=Opcode.PushNull, operands=[]),
            Instruction(offset=9, opcode=Opcode.PushUndefined, operands=[]),
            Instruction(offset=10, opcode=Opcode.PushNaN, operands=[]),
        ]
        builder = ASTBuild()
        ast, _, _ = builder.transform(instructions, None)

        assert len(ast.children) == 11
        assert ast.children[0].type == "integer"
        assert ast.children[0].children[0] == 10
        assert ast.children[1].type == "integer"
        assert ast.children[1].children[0] == 100
        assert ast.children[2].type == "integer"
        assert ast.children[2].children[0] == 1000
        assert ast.children[3].type == "unsigned"
        assert ast.children[3].children[0] == 10000
        assert ast.children[4].type == "double"
        assert ast.children[4].children[0] == 3.14
        assert ast.children[5].type == "string"
        assert ast.children[5].children[0] == "hello"
        assert ast.children[6].type == "true"
        assert ast.children[7].type == "false"
        assert ast.children[8].type == "null"
        assert ast.children[9].type == "undefined"
        assert ast.children[10].type == "nan"

    def test_binary_operations(self) -> None:
        """Test binary operations."""
        instructions = [
            Instruction(offset=0, opcode=Opcode.PushByte, operands=[5]),
            Instruction(offset=1, opcode=Opcode.PushByte, operands=[3]),
            Instruction(offset=2, opcode=Opcode.Add, operands=[]),
        ]
        builder = ASTBuild()
        ast, _, _ = builder.transform(instructions, None)

        assert len(ast.children) == 1
        assert ast.children[0].type == "add"
        assert len(ast.children[0].children) == 2
        assert ast.children[0].children[0].type == "integer"
        assert ast.children[0].children[1].type == "integer"

    def test_unary_operations(self) -> None:
        """Test unary operations."""
        instructions = [
            Instruction(offset=0, opcode=Opcode.PushByte, operands=[5]),
            Instruction(offset=1, opcode=Opcode.Negate, operands=[]),
        ]
        builder = ASTBuild()
        ast, _, _ = builder.transform(instructions, None)

        assert len(ast.children) == 1
        assert ast.children[0].type == "negate"
        assert len(ast.children[0].children) == 1

    def test_conditional_branch(self) -> None:
        """Test conditional branch instructions."""
        instructions = [
            Instruction(offset=0, opcode=Opcode.PushByte, operands=[1]),
            Instruction(offset=1, opcode=Opcode.PushByte, operands=[2]),
            Instruction(offset=2, opcode=Opcode.IfEq, operands=[10]),
        ]
        builder = ASTBuild()
        ast, _, _ = builder.transform(instructions, None)

        # Should have conditional node
        assert len(ast.children) > 0
        # Check for conditional or jump_if
        has_conditional = any(c.type in {"if_eq", "jump_if"} for c in ast.children)
        assert has_conditional

    def test_jump_instruction(self) -> None:
        """Test jump instruction."""
        instructions = [
            Instruction(offset=0, opcode=Opcode.Jump, operands=[5]),
        ]
        builder = ASTBuild()
        ast, _, _ = builder.transform(instructions, None)

        assert len(ast.children) == 1
        assert ast.children[0].type == "jump"

    def test_return_void(self) -> None:
        """Test return void instruction."""
        instructions = [
            Instruction(offset=0, opcode=Opcode.ReturnVoid, operands=[]),
        ]
        builder = ASTBuild()
        ast, _, _ = builder.transform(instructions, None)

        assert len(ast.children) == 1
        assert ast.children[0].type == "return_void"

    def test_return_value(self) -> None:
        """Test return value instruction."""
        instructions = [
            Instruction(offset=0, opcode=Opcode.PushByte, operands=[42]),
            Instruction(offset=1, opcode=Opcode.ReturnValue, operands=[]),
        ]
        builder = ASTBuild()
        ast, _, _ = builder.transform(instructions, None)

        assert len(ast.children) == 1
        assert ast.children[0].type == "return_value"
        assert ast.children[0].children[0].type == "integer"

    def test_throw_instruction(self) -> None:
        """Test throw instruction."""
        instructions = [
            Instruction(offset=0, opcode=Opcode.PushString, operands=["error"]),
            Instruction(offset=1, opcode=Opcode.Throw, operands=[]),
        ]
        builder = ASTBuild()
        ast, _, _ = builder.transform(instructions, None)

        assert len(ast.children) == 1
        assert ast.children[0].type == "throw"

    def test_dup_instruction(self) -> None:
        """Test dup instruction."""
        instructions = [
            Instruction(offset=0, opcode=Opcode.PushByte, operands=[42]),
            Instruction(offset=1, opcode=Opcode.Dup, operands=[]),
        ]
        builder = ASTBuild()
        ast, _, _ = builder.transform(instructions, None)

        # Dup should produce two values on stack
        # The actual behavior depends on implementation
        assert len(ast.children) > 0

    def test_swap_instruction(self) -> None:
        """Test swap instruction."""
        instructions = [
            Instruction(offset=0, opcode=Opcode.PushByte, operands=[1]),
            Instruction(offset=1, opcode=Opcode.PushByte, operands=[2]),
            Instruction(offset=2, opcode=Opcode.Swap, operands=[]),
        ]
        builder = ASTBuild()
        ast, _, _ = builder.transform(instructions, None)

        # Swap should reorder stack
        assert len(ast.children) > 0

    def test_pop_instruction(self) -> None:
        """Test pop instruction."""
        instructions = [
            Instruction(offset=0, opcode=Opcode.PushByte, operands=[42]),
            Instruction(offset=1, opcode=Opcode.Pop, operands=[]),
        ]
        builder = ASTBuild()
        ast, _, _ = builder.transform(instructions, None)

        assert len(ast.children) == 1
        assert ast.children[0].type == "pop"

    def test_convert_instructions(self) -> None:
        """Test type conversion instructions."""
        instructions = [
            Instruction(offset=0, opcode=Opcode.PushByte, operands=[42]),
            Instruction(offset=1, opcode=Opcode.ConvertI, operands=[]),
        ]
        builder = ASTBuild()
        ast, _, _ = builder.transform(instructions, None)

        assert len(ast.children) == 1
        assert ast.children[0].type == "convert_i"

    def test_coerce_instructions(self) -> None:
        """Test type coercion instructions."""
        instructions = [
            Instruction(offset=0, opcode=Opcode.PushByte, operands=[42]),
            Instruction(offset=1, opcode=Opcode.CoerceI, operands=[]),
        ]
        builder = ASTBuild()
        ast, _, _ = builder.transform(instructions, None)

        assert len(ast.children) == 1
        assert ast.children[0].type == "coerce"
        assert ast.children[0].children[0] == "integer"

    def test_find_property_strict(self) -> None:
        """Test find_property_strict instruction."""
        instructions = [
            Instruction(offset=0, opcode=Opcode.FindPropStrict, operands=["Object"]),
        ]
        builder = ASTBuild()
        ast, _, _ = builder.transform(instructions, None)

        assert len(ast.children) == 1
        assert ast.children[0].type == "find_property_strict"
        assert ast.children[0].children[0] == "Object"

    def test_get_property(self) -> None:
        """Test get_property instruction."""
        instructions = [
            Instruction(offset=0, opcode=Opcode.PushString, operands=["test"]),
            Instruction(offset=1, opcode=Opcode.GetProperty, operands=["prop"]),
        ]
        builder = ASTBuild()
        ast, _, _ = builder.transform(instructions, None)

        assert len(ast.children) == 1
        assert ast.children[0].type == "get_property"

    def test_set_property(self) -> None:
        """Test set_property instruction."""
        instructions = [
            Instruction(offset=0, opcode=Opcode.PushString, operands=["obj"]),
            Instruction(offset=1, opcode=Opcode.PushByte, operands=[42]),
            Instruction(offset=2, opcode=Opcode.SetProperty, operands=["prop"]),
        ]
        builder = ASTBuild()
        ast, _, _ = builder.transform(instructions, None)

        assert len(ast.children) == 1
        assert ast.children[0].type == "set_property"

    def test_call_property(self) -> None:
        """Test call_property instruction."""
        instructions = [
            Instruction(offset=0, opcode=Opcode.PushString, operands=["obj"]),
            Instruction(offset=1, opcode=Opcode.CallProperty, operands=["method", 0]),
        ]
        builder = ASTBuild()
        ast, _, _ = builder.transform(instructions, None)

        assert len(ast.children) == 1
        assert ast.children[0].type == "call_property"

    def test_new_array(self) -> None:
        """Test new_array instruction."""
        instructions = [
            Instruction(offset=0, opcode=Opcode.PushByte, operands=[1]),
            Instruction(offset=1, opcode=Opcode.PushByte, operands=[2]),
            Instruction(offset=2, opcode=Opcode.NewArray, operands=[2]),
        ]
        builder = ASTBuild()
        ast, _, _ = builder.transform(instructions, None)

        assert len(ast.children) == 1
        assert ast.children[0].type == "new_array"

    def test_new_object(self) -> None:
        """Test new_object instruction."""
        instructions = [
            Instruction(offset=0, opcode=Opcode.PushString, operands=["key"]),
            Instruction(offset=1, opcode=Opcode.PushByte, operands=[42]),
            Instruction(offset=2, opcode=Opcode.NewObject, operands=[1]),
        ]
        builder = ASTBuild()
        ast, _, _ = builder.transform(instructions, None)

        assert len(ast.children) == 1
        assert ast.children[0].type == "new_object"

    def test_lookup_switch(self) -> None:
        """Test lookup_switch instruction."""
        instructions = [
            Instruction(offset=0, opcode=Opcode.PushByte, operands=[1]),
            Instruction(offset=1, opcode=Opcode.LookupSwitch, operands=[10, [20, 30]]),
        ]
        builder = ASTBuild()
        ast, _, _ = builder.transform(instructions, None)

        assert len(ast.children) == 1
        assert ast.children[0].type == "lookup_switch"

    def test_complex_expression(self) -> None:
        """Test complex expression building."""
        # (5 + 3) * 2
        instructions = [
            Instruction(offset=0, opcode=Opcode.PushByte, operands=[5]),
            Instruction(offset=1, opcode=Opcode.PushByte, operands=[3]),
            Instruction(offset=2, opcode=Opcode.Add, operands=[]),
            Instruction(offset=3, opcode=Opcode.PushByte, operands=[2]),
            Instruction(offset=4, opcode=Opcode.Multiply, operands=[]),
        ]
        builder = ASTBuild()
        ast, _, _ = builder.transform(instructions, None)

        assert len(ast.children) == 1
        assert ast.children[0].type == "multiply"
        assert ast.children[0].children[0].type == "add"

    def test_stack_underflow_tolerance(self) -> None:
        """Test stack underflow tolerance option."""
        instructions = [
            Instruction(offset=0, opcode=Opcode.Add, operands=[]),
        ]
        builder = ASTBuild(options={"tolerate_stack_underflow": True})
        ast, _, _ = builder.transform(instructions, None)

        # Should handle underflow gracefully
        assert len(ast.children) > 0

    def test_validate_stack_exit(self) -> None:
        """Test stack exit validation."""
        instructions = [
            Instruction(offset=0, opcode=Opcode.PushByte, operands=[42]),
        ]
        builder = ASTBuild(options={"validate_stack_exit": True})

        # Should raise error for non-empty stack on exit
        with pytest.raises(ValueError, match="nonempty stack on exit"):
            builder.transform(instructions, None)

    def test_label_metadata(self) -> None:
        """Test that labels are properly set."""
        instructions = [
            Instruction(offset=100, opcode=Opcode.PushByte, operands=[42]),
            Instruction(offset=101, opcode=Opcode.Pop, operands=[]),
        ]
        builder = ASTBuild()
        ast, _, _ = builder.transform(instructions, None)

        # Pop statement uses its own label and contains pushed value as child.
        assert ast.children[0].metadata.get("label") == 101
        assert ast.children[0].children[0].metadata.get("label") == 100

    def test_nop_instruction(self) -> None:
        """Test NOP instruction handling."""
        instructions = [
            Instruction(
                offset=0, opcode=Opcode.Jump, operands=[0]
            ),  # Jump to self = NOP
        ]
        builder = ASTBuild()
        ast, _, _ = builder.transform(instructions, None)

        assert len(ast.children) == 1
        assert ast.children[0].type == "nop"

    def test_multiple_statements(self) -> None:
        """Test building multiple statements."""
        instructions = [
            Instruction(offset=0, opcode=Opcode.PushByte, operands=[1]),
            Instruction(offset=1, opcode=Opcode.Pop, operands=[]),
            Instruction(offset=2, opcode=Opcode.PushByte, operands=[2]),
            Instruction(offset=3, opcode=Opcode.Pop, operands=[]),
            Instruction(offset=4, opcode=Opcode.ReturnVoid, operands=[]),
        ]
        builder = ASTBuild()
        ast, _, _ = builder.transform(instructions, None)

        assert len(ast.children) == 3
        assert ast.children[0].type == "pop"
        assert ast.children[1].type == "pop"
        assert ast.children[2].type == "return_void"
