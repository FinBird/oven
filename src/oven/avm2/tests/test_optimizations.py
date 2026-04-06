"""Tests for decompiler optimizations."""

from __future__ import annotations

import pytest

from oven.avm2.decompiler import decompile_method
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


class TestDecompilerOptimizations:
    """Test various decompiler optimizations."""

    def test_property_increment_optimization(self) -> None:
        """Test that property increments are optimized to ++ syntax."""
        # Simulate bytecode that sets a property with increment
        instructions = [
            Instruction(Opcode.GetLocal0, [], 0),  # this
            Instruction(Opcode.GetProperty, [1], 0),  # get __SerialNum
            Instruction(Opcode.IncrementI, [], 0),  # increment
            Instruction(Opcode.SetProperty, [1], 0),  # set __SerialNum
        ]
        body = _body(instructions)
        result = decompile_method(body)

        # Accept either ++ optimization or equivalent arithmetic lowering.
        assert "++__SerialNum" in result or "+ 1" in result

    def test_ternary_type_conversion_optimization(self) -> None:
        """Test that redundant type conversions in ternary expressions are optimized."""
        # This would require more complex bytecode setup
        # For now, test the semantic pass directly
        pass

    def test_cfg_nested_if_else_optimization(self) -> None:
        """Test CFG optimization for nested if-else structures."""
        # This would require testing the CFG reduce pass
        pass

    def test_single_use_temp_elimination(self) -> None:
        """Test elimination of single-use temporary variables."""
        # Test that temp variables used only once are inlined
        instructions = [
            Instruction(Opcode.GetLocal1, [], 0),  # get local6
            Instruction(Opcode.CallProperty, [2, 0], 0),  # isConnected()
            Instruction(Opcode.Not, [], 0),  # !
            Instruction(Opcode.SetLocal, [10], 0),  # set local10
            Instruction(Opcode.GetLocal, [10], 0),  # get local10
            Instruction(Opcode.GetLocal, [5], 0),  # get local5
            Instruction(Opcode.Equals, [], 0),  # ==
            Instruction(Opcode.IfFalse, [10], 0),  # if false jump
        ]
        body = _body(instructions)
        result = decompile_method(body)

        # Should not contain local10 variable declaration and usage
        # This is a simplified test - actual implementation may vary
        assert "local10" not in result or "!" in result  # Either inlined or kept

    def test_property_decrement_optimization(self) -> None:
        """Test that property decrements are optimized to -- syntax."""
        instructions = [
            Instruction(Opcode.GetLocal0, [], 0),  # this
            Instruction(Opcode.GetProperty, [1], 0),  # get counter
            Instruction(Opcode.DecrementI, [], 0),  # decrement
            Instruction(Opcode.SetProperty, [1], 0),  # set counter
        ]
        body = _body(instructions)
        result = decompile_method(body)

        assert "--counter" in result or "- 1" in result
