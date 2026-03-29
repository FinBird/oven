from __future__ import annotations

from typing import Any, List, Optional

from .constant_pool import ConstantPool
from .enums import Instruction, Opcode


class InstructionFormatter:
    """Instruction text rendering extracted from ABCReader."""

    _STRING_OPCODES = frozenset(("pushstring", "debugfile", "dxns"))
    _MULTINAME_MARKERS = ("property", "super", "descendants", "find", "lex", "coerce", "astype", "istype")

    def __init__(self) -> None:
        # Cache operand-resolution kind by opcode to keep hot formatting loops cheap.
        self._opcode_kind_cache: dict[Opcode, str] = {}

    def serialize_instructions_to_string(
        self,
        instructions: List[Instruction],
        pool: Optional[ConstantPool] = None,
        show_offsets: bool = True,
    ) -> str:
        lines: list[str] = []

        for inst in instructions:
            line_parts: list[str] = []

            # Show instruction offset.
            if show_offsets:
                line_parts.append(f"{inst.offset:4d}")

            # Show opcode name.
            line_parts.append(f"{inst.opcode.name:15}")

            # Format operands.
            if inst.operands:
                operand_strs: list[str] = []
                for i, operand in enumerate(inst.operands):
                    # Resolve constant references when possible.
                    resolved_operand = self._resolve_operand_for_display(inst.opcode, i, operand, pool)
                    operand_strs.append(resolved_operand)

                line_parts.append(" ".join(operand_strs))

            lines.append("  ".join(line_parts))

        return "\n".join(lines)

    def serialize_instructions_as_function_calls(
        self,
        instructions: List[Instruction],
        pool: Optional[ConstantPool] = None,
    ) -> str:
        lines: list[str] = []

        for inst in instructions:
            # Convert opcode to function-style name.
            func_name = self._opcode_to_function_name(inst.opcode.name)

            # Format operands.
            if inst.operands:
                operand_strs: list[str] = []
                for operand in inst.operands:
                    resolved_operand = self._resolve_operand_for_function_call(inst.opcode, operand, pool)
                    operand_strs.append(resolved_operand)

                line = f"{func_name}({', '.join(operand_strs)})"
            else:
                line = f"{func_name}()"

            lines.append(line)

        return "; ".join(lines)

    def _opcode_to_function_name(self, opcode_name: str) -> str:
        # Keep original names for compatibility.
        return opcode_name

    def _resolve_operand_for_function_call(
        self,
        opcode: Opcode,
        operand: Any,
        pool: Optional[ConstantPool],
    ) -> str:
        return self._resolve_operand_for_output(opcode, operand, pool)

    def _resolve_operand_for_display(
        self,
        opcode: Opcode,
        operand_index: int,
        operand: Any,
        pool: Optional[ConstantPool],
    ) -> str:
        del operand_index  # Kept for compatibility with existing call sites.
        return self._resolve_operand_for_output(opcode, operand, pool)

    def _resolve_operand_for_output(
        self,
        opcode: Opcode,
        operand: Any,
        pool: Optional[ConstantPool],
    ) -> str:
        if isinstance(operand, str):
            return f'"{operand}"'

        if isinstance(operand, list):
            return f"[{','.join(str(x) for x in operand)}]"

        if not isinstance(operand, int) or pool is None:
            return str(operand)

        kind = self._operand_kind_for_opcode(opcode)
        if kind == "raw":
            return str(operand)

        try:
            resolved = pool.resolve_index(operand, kind)
            if kind == "string":
                return f'"{resolved}"'
            return str(resolved)
        except Exception:
            return str(operand)

    def _operand_kind_for_opcode(self, opcode: Opcode) -> str:
        cached = self._opcode_kind_cache.get(opcode)
        if cached is not None:
            return cached

        opcode_name = opcode.name.lower()
        if opcode_name in self._STRING_OPCODES:
            kind = "string"
        elif opcode_name == "pushint":
            kind = "int"
        elif opcode_name == "pushuint":
            kind = "uint"
        elif opcode_name == "pushdouble":
            kind = "double"
        elif opcode_name == "pushnamespace":
            kind = "namespace"
        elif any(marker in opcode_name for marker in self._MULTINAME_MARKERS):
            kind = "multiname"
        else:
            kind = "raw"

        self._opcode_kind_cache[opcode] = kind
        return kind
