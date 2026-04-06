"""Tests for DebugCommentGenerator."""

from __future__ import annotations

import pytest
from unittest.mock import Mock

from oven.api.debug import DebugCommentGenerator
from oven.api.models import DecompilerConfig
from oven.core.ast import Node
from oven.avm2.enums import Instruction, Opcode


def test_debug_comment_generator_disabled() -> None:
    """Test generator when debug comments are disabled."""
    config = DecompilerConfig(insert_debug_comments=False)
    generator = DebugCommentGenerator(config)

    node = Node("test", metadata={"instruction": Mock(), "label": 0x1234})
    result = generator.generate(node)

    assert result is None


def test_debug_comment_generator_no_instruction() -> None:
    """Test generator when node has no instruction metadata."""
    config = DecompilerConfig(insert_debug_comments=True)
    generator = DebugCommentGenerator(config)

    node = Node("test", metadata={"label": 0x1234})
    result = generator.generate(node)

    assert result is None


def test_debug_comment_generator_full() -> None:
    """Test generator with all debug options enabled."""
    config = DecompilerConfig(
        insert_debug_comments=True,
        debug_include_offset=True,
        debug_include_opcode=True,
        debug_include_operands=True,
    )
    generator = DebugCommentGenerator(config)

    # Create mock instruction
    instruction = Mock(spec=Instruction)
    instruction.opcode = Mock(name="GETLOCAL")
    instruction.opcode.name = "GETLOCAL"
    instruction.operands = [1]

    node = Node("test", metadata={"instruction": instruction, "label": 0x1234})
    result = generator.generate(node)

    assert result == "// 0x1234: GETLOCAL 1\n"


def test_debug_comment_generator_no_offset() -> None:
    """Test generator without offset."""
    config = DecompilerConfig(
        insert_debug_comments=True,
        debug_include_offset=False,
        debug_include_opcode=True,
        debug_include_operands=True,
    )
    generator = DebugCommentGenerator(config)

    instruction = Mock(spec=Instruction)
    instruction.opcode = Mock(name="PUSHBYTE")
    instruction.opcode.name = "PUSHBYTE"
    instruction.operands = [42]

    node = Node("test", metadata={"instruction": instruction, "label": 0x1234})
    result = generator.generate(node)

    assert result == "// PUSHBYTE 42\n"


def test_debug_comment_generator_no_opcode() -> None:
    """Test generator without opcode."""
    config = DecompilerConfig(
        insert_debug_comments=True,
        debug_include_offset=True,
        debug_include_opcode=False,
        debug_include_operands=True,
    )
    generator = DebugCommentGenerator(config)

    instruction = Mock(spec=Instruction)
    instruction.opcode = Mock(name="PUSHBYTE")
    instruction.opcode.name = "PUSHBYTE"
    instruction.operands = [42]

    node = Node("test", metadata={"instruction": instruction, "label": 0x1234})
    result = generator.generate(node)

    assert result == "// 0x1234: 42\n"


def test_debug_comment_generator_no_operands() -> None:
    """Test generator without operands."""
    config = DecompilerConfig(
        insert_debug_comments=True,
        debug_include_offset=True,
        debug_include_opcode=True,
        debug_include_operands=False,
    )
    generator = DebugCommentGenerator(config)

    instruction = Mock(spec=Instruction)
    instruction.opcode = Mock(name="GETLOCAL")
    instruction.opcode.name = "GETLOCAL"
    instruction.operands = [1]

    node = Node("test", metadata={"instruction": instruction, "label": 0x1234})
    result = generator.generate(node)

    assert result == "// 0x1234: GETLOCAL\n"


def test_debug_comment_generator_no_operands_empty() -> None:
    """Test generator with instruction that has no operands."""
    config = DecompilerConfig(
        insert_debug_comments=True,
        debug_include_offset=True,
        debug_include_opcode=True,
        debug_include_operands=True,
    )
    generator = DebugCommentGenerator(config)

    instruction = Mock(spec=Instruction)
    instruction.opcode = Mock(name="NOP")
    instruction.opcode.name = "NOP"
    instruction.operands = []

    node = Node("test", metadata={"instruction": instruction, "label": 0x1234})
    result = generator.generate(node)

    assert result == "// 0x1234: NOP\n"


def test_debug_comment_generator_from_metadata() -> None:
    """Test static method generate_from_metadata."""
    instruction = Mock(spec=Instruction)
    instruction.opcode = Mock(name="PUSHINT")
    instruction.opcode.name = "PUSHINT"
    instruction.operands = [0x100]

    metadata = {"instruction": instruction, "label": 0x5678}

    result = DebugCommentGenerator.generate_from_metadata(metadata)
    assert result == "// 0x5678: PUSHINT 256\n"

    # Test with custom options
    result = DebugCommentGenerator.generate_from_metadata(
        metadata,
        include_offset=False,
        include_opcode=True,
        include_operands=False,
    )
    assert result == "// PUSHINT\n"

    # Test with no instruction
    result = DebugCommentGenerator.generate_from_metadata({})
    assert result is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
