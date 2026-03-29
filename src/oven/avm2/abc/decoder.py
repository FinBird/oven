from __future__ import annotations

from typing import Callable, TypeAlias

from ..constant_pool import ConstantPool, MultinameRef
from ..enums import Instruction, Opcode
from ..exceptions import InvalidABCCodeError
from .opcode_registry import (
    FORM_DEBUG,
    FORM_DEBUGLINE,
    FORM_LOOKUPSWITCH,
    FORM_MULTINAME_INDEX,
    FORM_NONE,
    FORM_POOL_INDEX,
    FORM_RELATIVE_I24,
    FORM_S8,
    FORM_TWO_U30_MULTINAME_COUNT,
    FORM_TWO_U30_PLAIN,
    FORM_U8,
    FORM_U30_PLAIN,
    FORM_U30_STRING,
    MULTINAME_INDEX_OPERAND_OPCODES,
    NO_OPERAND_OPCODES,
    OPCODE_ENUM_BY_BYTE,
    OPERAND_FORM_BY_OPCODE,
    POOL_KIND_BY_OPCODE,
    POOL_INDEX_OPERAND_KINDS,
    PoolKind,
    RELATIVE_I24_OPERAND_OPCODES,
    S8_OPERAND_OPCODES,
    TWO_U30_MULTINAME_COUNT_OPERAND_OPCODES,
    TWO_U30_PLAIN_OPERAND_OPCODES,
    U8_OPERAND_OPCODES,
    U30_PLAIN_OPERAND_OPCODES,
)

OperandValue: TypeAlias = object

_CACHE_MISS: object = object()

ResolveIndexFn = Callable[[int, PoolKind], OperandValue]
ResolveCache = dict[PoolKind, dict[int, OperandValue]]
PreloadedTables = dict[PoolKind, list[OperandValue]]


class InstructionDecoder:
    """Decode AVM2 bytecode instructions and resolve operands from constant pool."""

    FORM_NONE = FORM_NONE
    FORM_RELATIVE_I24 = FORM_RELATIVE_I24
    FORM_LOOKUPSWITCH = FORM_LOOKUPSWITCH
    FORM_U8 = FORM_U8
    FORM_S8 = FORM_S8
    FORM_U30_PLAIN = FORM_U30_PLAIN
    FORM_U30_STRING = FORM_U30_STRING
    FORM_POOL_INDEX = FORM_POOL_INDEX
    FORM_MULTINAME_INDEX = FORM_MULTINAME_INDEX
    FORM_TWO_U30_PLAIN = FORM_TWO_U30_PLAIN
    FORM_TWO_U30_MULTINAME_COUNT = FORM_TWO_U30_MULTINAME_COUNT
    FORM_DEBUG = FORM_DEBUG
    FORM_DEBUGLINE = FORM_DEBUGLINE
    _OPERAND_FORM_BY_OPCODE = OPERAND_FORM_BY_OPCODE

    def __init__(self, *, verify_relaxed: bool = False) -> None:
        self._verify_relaxed = verify_relaxed

    def parse_instructions(self, code: bytes, pool: ConstantPool | None) -> list[Instruction]:
        instructions: list[Instruction] = []
        pos = 0
        code_len = len(code)

        opcode_map = OPCODE_ENUM_BY_BYTE
        verify_relaxed = self._verify_relaxed
        append_instruction = instructions.append
        make_instruction = Instruction

        if pool is None:
            read_operands_raw = self._read_operands_raw
            while pos < code_len:
                offset = pos
                opcode_byte = code[pos]
                pos += 1

                opcode = opcode_map[opcode_byte]
                if opcode is None:
                    if verify_relaxed:
                        append_instruction(make_instruction(Opcode.Nop, [], offset))
                        continue
                    raise InvalidABCCodeError(f"Unknown opcode: {opcode_byte:#x} at offset {offset}")

                operands, operand_size = read_operands_raw(opcode, code, pos)
                pos += operand_size
                append_instruction(make_instruction(opcode, operands, offset))
            return instructions

        preloaded_tables = self._build_preloaded_tables(pool)
        read_operands_preloaded = self._read_operands_preloaded

        while pos < code_len:
            offset = pos
            opcode_byte = code[pos]
            pos += 1

            opcode = opcode_map[opcode_byte]
            if opcode is None:
                if verify_relaxed:
                    append_instruction(make_instruction(Opcode.Nop, [], offset))
                    continue
                raise InvalidABCCodeError(f"Unknown opcode: {opcode_byte:#x} at offset {offset}")

            operands, operand_size = read_operands_preloaded(opcode, code, pos, preloaded_tables)
            pos += operand_size
            append_instruction(make_instruction(opcode, operands, offset))

        return instructions

    def _read_operands(
        self,
        opcode: Opcode,
        code: bytes,
        pos: int,
        pool: ConstantPool | None,
        resolve_cache: ResolveCache | None,
    ) -> tuple[list[OperandValue], int]:
        # Compatibility shim for legacy internal call sites.
        if pool is None:
            return self._read_operands_raw(opcode, code, pos)
        preloaded_tables = self._build_preloaded_tables(pool)
        return self._read_operands_preloaded(opcode, code, pos, preloaded_tables)

    def _read_operands_raw(
        self,
        opcode: Opcode,
        code: bytes,
        pos: int,
    ) -> tuple[list[OperandValue], int]:
        operand_form = OPERAND_FORM_BY_OPCODE[opcode.value]
        init_pos = pos

        read_i24 = self._read_i24_fast
        read_u30 = self._read_u30_data_fast

        try:
            match operand_form:
                case 0:
                    return [], 0
                case 1:
                    return [read_i24(code, pos)], 3
                case 2:
                    default_offset = read_i24(code, pos)
                    pos += 3
                    case_count, size = read_u30(code, pos)
                    pos += size
                    case_offsets_count = case_count + 1
                    case_offsets = [0] * case_offsets_count
                    for idx in range(case_offsets_count):
                        case_offsets[idx] = read_i24(code, pos + idx * 3)
                    pos += case_offsets_count * 3
                    return [default_offset, case_count, case_offsets], pos - init_pos
                case 3:
                    return [code[pos]], 1
                case 4:
                    raw = code[pos]
                    return [raw - 0x100 if (raw & 0x80) else raw], 1
                case 5 | 6 | 7 | 8:
                    val, size = read_u30(code, pos)
                    return [val], size
                case 9 | 10:
                    val1, size1 = read_u30(code, pos)
                    pos += size1
                    val2, size2 = read_u30(code, pos)
                    return [val1, val2], size1 + size2
                case 11:
                    debug_type = code[pos]
                    pos += 1
                    name_index, size1 = read_u30(code, pos)
                    pos += size1
                    register = code[pos]
                    pos += 1
                    extra, size2 = read_u30(code, pos)
                    pos += size2
                    return [debug_type, name_index, register, extra], pos - init_pos
                case 12:
                    line, size = read_u30(code, pos)
                    return [line], size
                case _:
                    return [], 0
        except IndexError as exc:
            raise InvalidABCCodeError(
                f"Unexpected end of code block while parsing operands for {opcode.name}"
            ) from exc

    def _read_operands_preloaded(
        self,
        opcode: Opcode,
        code: bytes,
        pos: int,
        preloaded_tables: PreloadedTables,
    ) -> tuple[list[OperandValue], int]:
        operand_form = OPERAND_FORM_BY_OPCODE[opcode.value]
        init_pos = pos

        read_i24 = self._read_i24_fast
        read_u30 = self._read_u30_data_fast
        lookup_preloaded = self._lookup_preloaded

        try:
            match operand_form:
                case 0:
                    return [], 0
                case 1:
                    return [read_i24(code, pos)], 3
                case 2:
                    default_offset = read_i24(code, pos)
                    pos += 3
                    case_count, size = read_u30(code, pos)
                    pos += size
                    case_offsets_count = case_count + 1
                    case_offsets = [0] * case_offsets_count
                    for idx in range(case_offsets_count):
                        case_offsets[idx] = read_i24(code, pos + idx * 3)
                    pos += case_offsets_count * 3
                    return [default_offset, case_count, case_offsets], pos - init_pos
                case 3:
                    return [code[pos]], 1
                case 4:
                    raw = code[pos]
                    return [raw - 0x100 if (raw & 0x80) else raw], 1
                case 5:
                    val, size = read_u30(code, pos)
                    return [val], size
                case 6:
                    val, size = read_u30(code, pos)
                    return [lookup_preloaded(val, "string", preloaded_tables)], size
                case 7:
                    val, size = read_u30(code, pos)
                    kind = POOL_KIND_BY_OPCODE[opcode.value]
                    if kind is None:
                        return [val], size
                    return [lookup_preloaded(val, kind, preloaded_tables)], size
                case 8:
                    val, size = read_u30(code, pos)
                    return [lookup_preloaded(val, "multiname", preloaded_tables)], size
                case 9:
                    val1, size1 = read_u30(code, pos)
                    pos += size1
                    val2, size2 = read_u30(code, pos)
                    return [val1, val2], size1 + size2
                case 10:
                    val1, size1 = read_u30(code, pos)
                    pos += size1
                    val2, size2 = read_u30(code, pos)
                    resolved = lookup_preloaded(val1, "multiname", preloaded_tables)
                    return [resolved, val2], size1 + size2
                case 11:
                    debug_type = code[pos]
                    pos += 1
                    name_index, size1 = read_u30(code, pos)
                    pos += size1
                    register = code[pos]
                    pos += 1
                    extra, size2 = read_u30(code, pos)
                    pos += size2
                    resolved = lookup_preloaded(name_index, "string", preloaded_tables)
                    return [debug_type, resolved, register, extra], pos - init_pos
                case 12:
                    line, size = read_u30(code, pos)
                    return [line], size
                case _:
                    return [], 0
        except IndexError as exc:
            raise InvalidABCCodeError(
                f"Unexpected end of code block while parsing operands for {opcode.name}"
            ) from exc

    @staticmethod
    def _build_preloaded_tables(pool: ConstantPool) -> PreloadedTables:
        return {
            "int": pool.get_preloaded_table("int"),
            "uint": pool.get_preloaded_table("uint"),
            "double": pool.get_preloaded_table("double"),
            "string": pool.get_preloaded_table("string"),
            "namespace": pool.get_preloaded_table("namespace"),
            "multiname": pool.get_preloaded_table("multiname"),
        }

    @staticmethod
    def _lookup_preloaded(index: int, kind: PoolKind, preloaded_tables: PreloadedTables) -> OperandValue:
        if index == 0:
            return "*"
        values = preloaded_tables.get(kind)
        if values is not None and 0 < index < len(values):
            return values[index]
        if kind == "string":
            return f"#string_{index}"
        if kind == "namespace":
            return f"#namespace_{index}"
        if kind == "multiname":
            return MultinameRef(f"#multiname_{index}", None, index)
        if kind in {"int", "uint"}:
            return 0
        if kind == "double":
            return 0.0
        return f"#{index}"

    @staticmethod
    def _resolve_with_cache(
        index: int,
        kind: PoolKind,
        resolve_index: ResolveIndexFn,
        resolve_cache: ResolveCache,
    ) -> OperandValue:
        kind_cache = resolve_cache.get(kind)
        if kind_cache is None:
            kind_cache = {}
            resolve_cache[kind] = kind_cache
        resolved = kind_cache.get(index, _CACHE_MISS)
        if resolved is _CACHE_MISS:
            resolved = resolve_index(index, kind)
            kind_cache[index] = resolved
        return resolved

    @staticmethod
    def _read_i24_fast(data: bytes, pos: int) -> int:
        b0, b1, b2 = data[pos], data[pos + 1], data[pos + 2]
        value = b0 | (b1 << 8) | (b2 << 16)
        if value & 0x800000:
            return value | ~0xFFFFFF
        return value

    @staticmethod
    def _read_u30_data_fast(data: bytes, pos: int) -> tuple[int, int]:
        b = data[pos]
        if not (b & 0x80):
            return b, 1
        b2 = data[pos + 1]
        result = (b & 0x7F) | ((b2 & 0x7F) << 7)
        if not (b2 & 0x80):
            return result, 2
        b3 = data[pos + 2]
        result |= (b3 & 0x7F) << 14
        if not (b3 & 0x80):
            return result, 3
        b4 = data[pos + 3]
        result |= (b4 & 0x7F) << 21
        if not (b4 & 0x80):
            return result, 4
        b5 = data[pos + 4]
        result |= (b5 & 0x7F) << 28
        return result, 5
