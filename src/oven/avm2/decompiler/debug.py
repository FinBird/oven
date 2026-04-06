"""Debug comment generation."""

from __future__ import annotations

from typing import Any
from oven.core.ast import Node
from oven.avm2.enums import Instruction
from .models import DecompilerConfig


class DebugCommentGenerator:
    """Generate debug comments for AST nodes."""

    def __init__(self, config: DecompilerConfig):
        self.config = config

    def generate(self, node: Node) -> str | None:
        """Generate debug comment for AST node.

        Returns:
            Debug comment string (including newline) or None if no comment should be added.
        """
        if not self.config.insert_debug_comments:
            return None

        instruction = node.metadata.get("instruction")
        if not instruction:
            return None

        offset = (
            node.metadata.get("label", 0) if self.config.debug_include_offset else None
        )
        opcode = instruction.opcode.name if self.config.debug_include_opcode else None
        operands = (
            instruction.operands
            if (self.config.debug_include_operands and instruction.operands)
            else None
        )

        return self._format_comment(offset, opcode, operands)

    @staticmethod
    def _format_comment(
        offset: int | None,
        opcode: str | None,
        operands: list[Any] | None,
    ) -> str | None:
        """Format debug comment from components.

        Format: // 0xOFFSET: OPCODE operands
        """
        parts = []
        if offset is not None:
            parts.append(f"0x{offset:04X}")

        # Build middle part: opcode + operands (space separated)
        middle_parts = []
        if opcode is not None:
            middle_parts.append(opcode)
        if operands:
            # Format operands as decimal integers
            operands_str = " ".join(str(op) for op in operands)
            middle_parts.append(operands_str)

        if not parts and not middle_parts:
            return None

        # Combine offset and middle parts with colon separator
        if parts and middle_parts:
            comment = f"{parts[0]}: {' '.join(middle_parts)}"
        elif parts:
            comment = parts[0]
        else:
            comment = " ".join(middle_parts)

        return f"// {comment}\n"

    @staticmethod
    def generate_from_metadata(
        metadata: dict[str, Any],
        include_offset: bool = True,
        include_opcode: bool = True,
        include_operands: bool = True,
    ) -> str | None:
        """Generate debug comment from metadata dictionary.

        Useful for testing or when node is not available.
        """
        instruction = metadata.get("instruction")
        if not instruction:
            return None

        offset = metadata.get("label", 0) if include_offset else None
        opcode = instruction.opcode.name if include_opcode else None
        operands = (
            instruction.operands
            if (include_operands and instruction.operands)
            else None
        )

        return DebugCommentGenerator._format_comment(offset, opcode, operands)
