from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Final, Literal, TypeAlias

from ..enums import Opcode

PoolKind: TypeAlias = Literal[
    "int", "uint", "double", "string", "namespace", "multiname"
]

FORM_NONE: Final[int] = 0
FORM_RELATIVE_I24: Final[int] = 1
FORM_LOOKUPSWITCH: Final[int] = 2
FORM_U8: Final[int] = 3
FORM_S8: Final[int] = 4
FORM_U30_PLAIN: Final[int] = 5
FORM_U30_STRING: Final[int] = 6
FORM_POOL_INDEX: Final[int] = 7
FORM_MULTINAME_INDEX: Final[int] = 8
FORM_TWO_U30_PLAIN: Final[int] = 9
FORM_TWO_U30_MULTINAME_COUNT: Final[int] = 10
FORM_DEBUG: Final[int] = 11
FORM_DEBUGLINE: Final[int] = 12

DYNAMIC_STACK: Final[int] = -1


@dataclass(slots=True, frozen=True)
class OpcodeInfo:
    opcode: int
    name: str
    operand_form: int
    pool_kind: PoolKind | None
    stack_pops: int
    stack_pushes: int
    is_branch: bool
    is_conditional_branch: bool
    is_terminator: bool
    allow_relaxed_underflow: bool

    @property
    def has_dynamic_stack(self) -> bool:
        return self.stack_pops == DYNAMIC_STACK or self.stack_pushes == DYNAMIC_STACK


_opcode_enum_by_byte: list[Opcode | None] = [None] * 256
for _op in Opcode:
    _opcode_enum_by_byte[_op.value] = _op
OPCODE_ENUM_BY_BYTE: Final[tuple[Opcode | None, ...]] = tuple(_opcode_enum_by_byte)


def _default_info(opcode: int) -> OpcodeInfo:
    op_enum = OPCODE_ENUM_BY_BYTE[opcode]
    if op_enum is not None:
        name = op_enum.name
    else:
        name = f"UNKNOWN_{opcode:02X}"
    return OpcodeInfo(
        opcode=opcode,
        name=name,
        operand_form=FORM_NONE,
        pool_kind=None,
        stack_pops=0,
        stack_pushes=0,
        is_branch=False,
        is_conditional_branch=False,
        is_terminator=False,
        allow_relaxed_underflow=False,
    )


_registry: list[OpcodeInfo] = [_default_info(i) for i in range(256)]


def _set_info(opcode: Opcode, **changes: Any) -> None:
    _registry[opcode.value] = replace(_registry[opcode.value], **changes)


def _set_group(opcodes: frozenset[Opcode], **changes: Any) -> None:
    for opcode in opcodes:
        _set_info(opcode, **changes)


# === Operand form metadata ===
NO_OPERAND_OPCODES: Final[frozenset[Opcode]] = frozenset(
    {
        Opcode.Add,
        Opcode.AddI,
        Opcode.Subtract,
        Opcode.SubtractI,
        Opcode.Multiply,
        Opcode.MultiplyI,
        Opcode.Divide,
        Opcode.Modulo,
        Opcode.Increment,
        Opcode.IncrementI,
        Opcode.Decrement,
        Opcode.DecrementI,
        Opcode.Negate,
        Opcode.NegateI,
        Opcode.BitAnd,
        Opcode.BitOr,
        Opcode.BitXor,
        Opcode.BitNot,
        Opcode.LShift,
        Opcode.RShift,
        Opcode.URShift,
        Opcode.Equals,
        Opcode.StrictEquals,
        Opcode.LessThan,
        Opcode.LessEquals,
        Opcode.GreaterThan,
        Opcode.GreaterEquals,
        Opcode.In,
        Opcode.ConvertB,
        Opcode.ConvertD,
        Opcode.ConvertI,
        Opcode.ConvertO,
        Opcode.ConvertS,
        Opcode.ConvertU,
        Opcode.CoerceA,
        Opcode.CoerceB,
        Opcode.CoerceD,
        Opcode.CoerceI,
        Opcode.CoerceO,
        Opcode.CoerceS,
        Opcode.CoerceU,
        Opcode.AsTypeLate,
        Opcode.IsTypeLate,
        Opcode.InstanceOf,
        Opcode.TypeOf,
        Opcode.Dup,
        Opcode.Swap,
        Opcode.Pop,
        Opcode.PushTrue,
        Opcode.PushFalse,
        Opcode.PushNaN,
        Opcode.PushNull,
        Opcode.PushUndefined,
        Opcode.Nop,
        Opcode.Not,
        Opcode.GetLocal0,
        Opcode.GetLocal1,
        Opcode.GetLocal2,
        Opcode.GetLocal3,
        Opcode.SetLocal0,
        Opcode.SetLocal1,
        Opcode.SetLocal2,
        Opcode.SetLocal3,
        Opcode.GetGlobalScope,
        Opcode.PushScope,
        Opcode.PopScope,
        Opcode.PushWith,
        Opcode.HasNext,
        Opcode.NextName,
        Opcode.NextValue,
        Opcode.EscXElem,
        Opcode.EscXAttr,
        Opcode.CheckFilter,
        Opcode.DxnsLate,
        Opcode.ReturnValue,
        Opcode.ReturnVoid,
        Opcode.Throw,
        Opcode.Sxi1,
        Opcode.Sxi8,
        Opcode.Sxi16,
        Opcode.Li8,
        Opcode.Li16,
        Opcode.Li32,
        Opcode.Lf32,
        Opcode.Lf64,
        Opcode.Si8,
        Opcode.Si16,
        Opcode.Si32,
        Opcode.Sf32,
        Opcode.Sf64,
        Opcode.Label,
        Opcode.Timestamp,
    }
)

RELATIVE_I24_OPERAND_OPCODES: Final[frozenset[Opcode]] = frozenset(
    {
        Opcode.IfEq,
        Opcode.IfFalse,
        Opcode.IfGe,
        Opcode.IfGt,
        Opcode.IfLe,
        Opcode.IfLt,
        Opcode.IfNe,
        Opcode.IfNge,
        Opcode.IfNgt,
        Opcode.IfNle,
        Opcode.IfNlt,
        Opcode.IfStrictEq,
        Opcode.IfStrictNe,
        Opcode.IfTrue,
        Opcode.Jump,
    }
)

S8_OPERAND_OPCODES: Final[frozenset[Opcode]] = frozenset({Opcode.PushByte})
U8_OPERAND_OPCODES: Final[frozenset[Opcode]] = frozenset({Opcode.GetScopeObject})

U30_PLAIN_OPERAND_OPCODES: Final[frozenset[Opcode]] = frozenset(
    {
        Opcode.PushShort,
        Opcode.GetLocal,
        Opcode.SetLocal,
        Opcode.Kill,
        Opcode.DecLocal,
        Opcode.DecLocalI,
        Opcode.IncLocal,
        Opcode.IncLocalI,
        Opcode.GetOuterScope,
        Opcode.GetSlot,
        Opcode.SetSlot,
        Opcode.GetGlobalSlot,
        Opcode.SetGlobalSlot,
        Opcode.Call,
        Opcode.Construct,
        Opcode.ConstructSuper,
        Opcode.NewObject,
        Opcode.NewArray,
        Opcode.NewActivation,
        Opcode.NewCatch,
        Opcode.ApplyType,
        Opcode.NewClass,
        Opcode.NewFunction,
        Opcode.Dxns,
        Opcode.Bkpt,
        Opcode.BkptLine,
    }
)

POOL_INDEX_OPERAND_KINDS: Final[dict[Opcode, PoolKind]] = {
    Opcode.PushInt: "int",
    Opcode.PushUint: "uint",
    Opcode.PushDouble: "double",
    Opcode.PushString: "string",
    Opcode.DebugFile: "string",
    Opcode.PushNamespace: "namespace",
}

MULTINAME_INDEX_OPERAND_OPCODES: Final[frozenset[Opcode]] = frozenset(
    {
        Opcode.Coerce,
        Opcode.AsType,
        Opcode.IsType,
        Opcode.InstanceOf,
        Opcode.GetProperty,
        Opcode.SetProperty,
        Opcode.InitProperty,
        Opcode.DeleteProperty,
        Opcode.GetSuper,
        Opcode.SetSuper,
        Opcode.GetDescendants,
        Opcode.FindProperty,
        Opcode.FindPropStrict,
        Opcode.FindDef,
        Opcode.GetLex,
        Opcode.EscXElem,
        Opcode.EscXAttr,
    }
)

TWO_U30_PLAIN_OPERAND_OPCODES: Final[frozenset[Opcode]] = frozenset(
    {
        Opcode.CallStatic,
        Opcode.CallMethod,
        Opcode.HasNext2,
    }
)

TWO_U30_MULTINAME_COUNT_OPERAND_OPCODES: Final[frozenset[Opcode]] = frozenset(
    {
        Opcode.CallProperty,
        Opcode.CallPropLex,
        Opcode.CallPropVoid,
        Opcode.CallSuper,
        Opcode.CallSuperVoid,
        Opcode.ConstructProp,
    }
)

_set_group(RELATIVE_I24_OPERAND_OPCODES, operand_form=FORM_RELATIVE_I24)
_set_info(Opcode.LookupSwitch, operand_form=FORM_LOOKUPSWITCH)
_set_group(S8_OPERAND_OPCODES, operand_form=FORM_S8)
_set_group(U8_OPERAND_OPCODES, operand_form=FORM_U8)
_set_group(U30_PLAIN_OPERAND_OPCODES, operand_form=FORM_U30_PLAIN)
for _opcode, _kind in POOL_INDEX_OPERAND_KINDS.items():
    _set_info(_opcode, operand_form=FORM_POOL_INDEX, pool_kind=_kind)
_set_group(MULTINAME_INDEX_OPERAND_OPCODES, operand_form=FORM_MULTINAME_INDEX)
_set_group(TWO_U30_PLAIN_OPERAND_OPCODES, operand_form=FORM_TWO_U30_PLAIN)
_set_group(
    TWO_U30_MULTINAME_COUNT_OPERAND_OPCODES, operand_form=FORM_TWO_U30_MULTINAME_COUNT
)
_set_info(Opcode.Debug, operand_form=FORM_DEBUG)
_set_info(Opcode.DebugLine, operand_form=FORM_DEBUGLINE)
_set_info(Opcode.Dxns, operand_form=FORM_U30_STRING)

# === Branch/terminator metadata ===
CONDITIONAL_BRANCH_OPCODES: Final[frozenset[Opcode]] = frozenset(
    {
        Opcode.IfEq,
        Opcode.IfFalse,
        Opcode.IfGe,
        Opcode.IfGt,
        Opcode.IfLe,
        Opcode.IfLt,
        Opcode.IfNe,
        Opcode.IfNge,
        Opcode.IfNgt,
        Opcode.IfNle,
        Opcode.IfNlt,
        Opcode.IfStrictEq,
        Opcode.IfStrictNe,
        Opcode.IfTrue,
    }
)

TERMINATOR_OPCODES: Final[frozenset[Opcode]] = frozenset(
    {Opcode.ReturnVoid, Opcode.ReturnValue, Opcode.Throw}
)

_set_group(CONDITIONAL_BRANCH_OPCODES, is_branch=True, is_conditional_branch=True)
_set_info(Opcode.Jump, is_branch=True, is_conditional_branch=False)
_set_info(Opcode.LookupSwitch, is_branch=True, is_conditional_branch=False)
_set_group(TERMINATOR_OPCODES, is_terminator=True)

RELAXED_UNDERFLOW_OPCODES: Final[frozenset[Opcode]] = frozenset(
    {
        Opcode.GetSlot,
        Opcode.SetSlot,
        Opcode.GetGlobalSlot,
        Opcode.SetGlobalSlot,
        Opcode.GetProperty,
        Opcode.SetProperty,
        Opcode.InitProperty,
        Opcode.GetSuper,
        Opcode.SetSuper,
        Opcode.GetDescendants,
        Opcode.DeleteProperty,
        Opcode.FindProperty,
        Opcode.FindPropStrict,
        Opcode.FindDef,
        Opcode.GetLex,
        Opcode.CallMethod,
        Opcode.CallStatic,
        Opcode.CallProperty,
        Opcode.CallPropLex,
        Opcode.CallPropVoid,
        Opcode.CallSuper,
        Opcode.CallSuperVoid,
        Opcode.ConstructProp,
        Opcode.GetScopeObject,
        Opcode.GetOuterScope,
    }
)
_set_group(RELAXED_UNDERFLOW_OPCODES, allow_relaxed_underflow=True)

# === Stack effect metadata ===
STACK_EFFECT_OVERRIDES: Final[dict[Opcode, tuple[int, int]]] = {
    Opcode.Pop: (1, 0),
    Opcode.Dup: (1, 2),
    Opcode.Swap: (2, 2),
    Opcode.PushByte: (0, 1),
    Opcode.PushShort: (0, 1),
    Opcode.PushTrue: (0, 1),
    Opcode.PushFalse: (0, 1),
    Opcode.PushNaN: (0, 1),
    Opcode.PushNull: (0, 1),
    Opcode.PushUndefined: (0, 1),
    Opcode.PushInt: (0, 1),
    Opcode.PushUint: (0, 1),
    Opcode.PushDouble: (0, 1),
    Opcode.PushString: (0, 1),
    Opcode.PushNamespace: (0, 1),
    Opcode.GetGlobalScope: (0, 1),
    Opcode.GetLocal: (0, 1),
    Opcode.GetLocal0: (0, 1),
    Opcode.GetLocal1: (0, 1),
    Opcode.GetLocal2: (0, 1),
    Opcode.GetLocal3: (0, 1),
    Opcode.SetLocal: (1, 0),
    Opcode.SetLocal0: (1, 0),
    Opcode.SetLocal1: (1, 0),
    Opcode.SetLocal2: (1, 0),
    Opcode.SetLocal3: (1, 0),
    Opcode.IfTrue: (1, 0),
    Opcode.IfFalse: (1, 0),
    Opcode.IfEq: (2, 0),
    Opcode.IfNe: (2, 0),
    Opcode.IfGe: (2, 0),
    Opcode.IfGt: (2, 0),
    Opcode.IfLe: (2, 0),
    Opcode.IfLt: (2, 0),
    Opcode.IfNge: (2, 0),
    Opcode.IfNgt: (2, 0),
    Opcode.IfNle: (2, 0),
    Opcode.IfNlt: (2, 0),
    Opcode.IfStrictEq: (2, 0),
    Opcode.IfStrictNe: (2, 0),
    Opcode.Jump: (0, 0),
    Opcode.LookupSwitch: (1, 0),
    Opcode.ReturnVoid: (0, 0),
    Opcode.ReturnValue: (1, 0),
    Opcode.Throw: (1, 0),
    Opcode.DxnsLate: (1, 0),
    Opcode.Dxns: (0, 0),
    Opcode.Nop: (0, 0),
    Opcode.Label: (0, 0),
    Opcode.Kill: (0, 0),
    Opcode.Debug: (0, 0),
    Opcode.DebugFile: (0, 0),
    Opcode.DebugLine: (0, 0),
    Opcode.IncLocal: (0, 0),
    Opcode.IncLocalI: (0, 0),
    Opcode.DecLocal: (0, 0),
    Opcode.DecLocalI: (0, 0),
}

STACK_EFFECT_BINARY_OPCODES: Final[frozenset[Opcode]] = frozenset(
    {
        Opcode.Add,
        Opcode.AddI,
        Opcode.Subtract,
        Opcode.SubtractI,
        Opcode.Multiply,
        Opcode.MultiplyI,
        Opcode.Divide,
        Opcode.Modulo,
        Opcode.BitAnd,
        Opcode.BitOr,
        Opcode.BitXor,
        Opcode.LShift,
        Opcode.RShift,
        Opcode.URShift,
        Opcode.Equals,
        Opcode.StrictEquals,
        Opcode.LessThan,
        Opcode.LessEquals,
        Opcode.GreaterThan,
        Opcode.GreaterEquals,
        Opcode.In,
        Opcode.InstanceOf,
        Opcode.AsTypeLate,
        Opcode.IsTypeLate,
    }
)

STACK_EFFECT_UNARY_OPCODES: Final[frozenset[Opcode]] = frozenset(
    {
        Opcode.Increment,
        Opcode.IncrementI,
        Opcode.Decrement,
        Opcode.DecrementI,
        Opcode.Negate,
        Opcode.NegateI,
        Opcode.BitNot,
        Opcode.Not,
        Opcode.ConvertB,
        Opcode.ConvertD,
        Opcode.ConvertI,
        Opcode.ConvertO,
        Opcode.ConvertS,
        Opcode.ConvertU,
        Opcode.Coerce,
        Opcode.CoerceA,
        Opcode.CoerceB,
        Opcode.CoerceD,
        Opcode.CoerceI,
        Opcode.CoerceO,
        Opcode.CoerceS,
        Opcode.CoerceU,
        Opcode.AsType,
        Opcode.IsType,
        Opcode.TypeOf,
        Opcode.EscXElem,
        Opcode.EscXAttr,
        Opcode.CheckFilter,
    }
)

STACK_EFFECT_GET_PROPERTY_OPCODES: Final[frozenset[Opcode]] = frozenset(
    {Opcode.GetProperty, Opcode.GetSuper, Opcode.GetDescendants}
)
STACK_EFFECT_SET_PROPERTY_OPCODES: Final[frozenset[Opcode]] = frozenset(
    {Opcode.SetProperty, Opcode.SetSuper, Opcode.InitProperty}
)
STACK_EFFECT_GET_SCOPE_OPCODES: Final[frozenset[Opcode]] = frozenset(
    {Opcode.GetScopeObject, Opcode.GetOuterScope}
)
STACK_EFFECT_FIND_PROPERTY_OPCODES: Final[frozenset[Opcode]] = frozenset(
    {Opcode.FindProperty, Opcode.FindPropStrict, Opcode.FindDef, Opcode.GetLex}
)
STACK_EFFECT_NEW_EMPTY_CONSTRUCTOR_OPCODES: Final[frozenset[Opcode]] = frozenset(
    {Opcode.NewActivation, Opcode.NewFunction, Opcode.NewCatch}
)
STACK_EFFECT_CALL_PROPERTY_OPCODES: Final[frozenset[Opcode]] = frozenset(
    {Opcode.CallProperty, Opcode.CallPropLex, Opcode.CallSuper, Opcode.ConstructProp}
)
STACK_EFFECT_CALL_PROPVOID_OPCODES: Final[frozenset[Opcode]] = frozenset(
    {Opcode.CallPropVoid, Opcode.CallSuperVoid}
)
STACK_EFFECT_MEMORY_LOAD_OPCODES: Final[frozenset[Opcode]] = frozenset(
    {Opcode.Li8, Opcode.Li16, Opcode.Li32, Opcode.Lf32, Opcode.Lf64}
)
STACK_EFFECT_MEMORY_STORE_OPCODES: Final[frozenset[Opcode]] = frozenset(
    {Opcode.Si8, Opcode.Si16, Opcode.Si32, Opcode.Sf32, Opcode.Sf64}
)
STACK_EFFECT_SIGN_EXTEND_OPCODES: Final[frozenset[Opcode]] = frozenset(
    {Opcode.Sxi1, Opcode.Sxi8, Opcode.Sxi16}
)
STACK_EFFECT_BREAKPOINT_OPCODES: Final[frozenset[Opcode]] = frozenset(
    {Opcode.Bkpt, Opcode.BkptLine}
)
STACK_EFFECT_NEXT_OPCODES: Final[frozenset[Opcode]] = frozenset(
    {Opcode.NextName, Opcode.NextValue}
)
SCOPE_EFFECT_PUSH_OPCODES: Final[frozenset[Opcode]] = frozenset(
    {Opcode.PushScope, Opcode.PushWith}
)

STACK_EFFECT_STATIC_BY_OPCODE: Final[dict[Opcode, tuple[int, int]]] = (
    dict(STACK_EFFECT_OVERRIDES)
    | {opcode: (2, 1) for opcode in STACK_EFFECT_BINARY_OPCODES}
    | {opcode: (1, 1) for opcode in STACK_EFFECT_UNARY_OPCODES}
    | {opcode: (0, 1) for opcode in STACK_EFFECT_GET_SCOPE_OPCODES}
    | {opcode: (0, 1) for opcode in STACK_EFFECT_NEW_EMPTY_CONSTRUCTOR_OPCODES}
    | {opcode: (1, 0) for opcode in SCOPE_EFFECT_PUSH_OPCODES}
    | {opcode: (1, 1) for opcode in STACK_EFFECT_MEMORY_LOAD_OPCODES}
    | {opcode: (2, 0) for opcode in STACK_EFFECT_MEMORY_STORE_OPCODES}
    | {opcode: (1, 1) for opcode in STACK_EFFECT_SIGN_EXTEND_OPCODES}
    | {opcode: (0, 0) for opcode in STACK_EFFECT_BREAKPOINT_OPCODES}
    | {opcode: (2, 1) for opcode in STACK_EFFECT_NEXT_OPCODES}
    | {
        Opcode.GetSlot: (1, 1),
        Opcode.SetSlot: (2, 0),
        Opcode.GetGlobalSlot: (0, 1),
        Opcode.SetGlobalSlot: (1, 0),
        Opcode.PopScope: (0, 0),
        Opcode.Timestamp: (0, 1),
        Opcode.HasNext: (2, 1),
        Opcode.HasNext2: (0, 1),
    }
)

for _opcode, (_pops, _pushes) in STACK_EFFECT_STATIC_BY_OPCODE.items():
    _set_info(_opcode, stack_pops=_pops, stack_pushes=_pushes)

DYNAMIC_STACK_HINTS: Final[dict[Opcode, tuple[int, int]]] = {
    Opcode.GetProperty: (DYNAMIC_STACK, 1),
    Opcode.GetSuper: (DYNAMIC_STACK, 1),
    Opcode.GetDescendants: (DYNAMIC_STACK, 1),
    Opcode.SetProperty: (DYNAMIC_STACK, 0),
    Opcode.SetSuper: (DYNAMIC_STACK, 0),
    Opcode.InitProperty: (DYNAMIC_STACK, 0),
    Opcode.DeleteProperty: (DYNAMIC_STACK, 1),
    Opcode.FindProperty: (DYNAMIC_STACK, 1),
    Opcode.FindPropStrict: (DYNAMIC_STACK, 1),
    Opcode.FindDef: (DYNAMIC_STACK, 1),
    Opcode.GetLex: (DYNAMIC_STACK, 1),
    Opcode.NewArray: (DYNAMIC_STACK, 1),
    Opcode.NewObject: (DYNAMIC_STACK, 1),
    Opcode.ApplyType: (DYNAMIC_STACK, 1),
    Opcode.Call: (DYNAMIC_STACK, 1),
    Opcode.CallMethod: (DYNAMIC_STACK, 1),
    Opcode.CallStatic: (DYNAMIC_STACK, 1),
    Opcode.CallProperty: (DYNAMIC_STACK, 1),
    Opcode.CallPropLex: (DYNAMIC_STACK, 1),
    Opcode.CallSuper: (DYNAMIC_STACK, 1),
    Opcode.ConstructProp: (DYNAMIC_STACK, 1),
    Opcode.CallPropVoid: (DYNAMIC_STACK, 0),
    Opcode.CallSuperVoid: (DYNAMIC_STACK, 0),
    Opcode.Construct: (DYNAMIC_STACK, 1),
    Opcode.ConstructSuper: (DYNAMIC_STACK, 0),
}
for _opcode, (_pops, _pushes) in DYNAMIC_STACK_HINTS.items():
    _set_info(_opcode, stack_pops=_pops, stack_pushes=_pushes)

OPCODE_INFO_TABLE: Final[tuple[OpcodeInfo, ...]] = tuple(_registry)
OPERAND_FORM_BY_OPCODE: Final[tuple[int, ...]] = tuple(
    info.operand_form for info in OPCODE_INFO_TABLE
)
POOL_KIND_BY_OPCODE: Final[tuple[PoolKind | None, ...]] = tuple(
    info.pool_kind for info in OPCODE_INFO_TABLE
)

_stack_effect_static_table: list[tuple[int, int] | None] = [None] * 256
for _opcode, _effect in STACK_EFFECT_STATIC_BY_OPCODE.items():
    _stack_effect_static_table[_opcode.value] = _effect
STACK_EFFECT_STATIC_TABLE: Final[tuple[tuple[int, int] | None, ...]] = tuple(
    _stack_effect_static_table
)


def opcode_info(opcode: Opcode | int) -> OpcodeInfo:
    opcode_value = int(opcode)
    if opcode_value < 0 or opcode_value > 0xFF:
        raise ValueError(f"opcode out of range: {opcode_value}")
    return OPCODE_INFO_TABLE[opcode_value]


__all__ = [
    "PoolKind",
    "OpcodeInfo",
    "DYNAMIC_STACK",
    "FORM_NONE",
    "FORM_RELATIVE_I24",
    "FORM_LOOKUPSWITCH",
    "FORM_U8",
    "FORM_S8",
    "FORM_U30_PLAIN",
    "FORM_U30_STRING",
    "FORM_POOL_INDEX",
    "FORM_MULTINAME_INDEX",
    "FORM_TWO_U30_PLAIN",
    "FORM_TWO_U30_MULTINAME_COUNT",
    "FORM_DEBUG",
    "FORM_DEBUGLINE",
    "NO_OPERAND_OPCODES",
    "RELATIVE_I24_OPERAND_OPCODES",
    "S8_OPERAND_OPCODES",
    "U8_OPERAND_OPCODES",
    "U30_PLAIN_OPERAND_OPCODES",
    "POOL_INDEX_OPERAND_KINDS",
    "MULTINAME_INDEX_OPERAND_OPCODES",
    "TWO_U30_PLAIN_OPERAND_OPCODES",
    "TWO_U30_MULTINAME_COUNT_OPERAND_OPCODES",
    "CONDITIONAL_BRANCH_OPCODES",
    "TERMINATOR_OPCODES",
    "RELAXED_UNDERFLOW_OPCODES",
    "STACK_EFFECT_OVERRIDES",
    "STACK_EFFECT_BINARY_OPCODES",
    "STACK_EFFECT_UNARY_OPCODES",
    "STACK_EFFECT_GET_PROPERTY_OPCODES",
    "STACK_EFFECT_SET_PROPERTY_OPCODES",
    "STACK_EFFECT_GET_SCOPE_OPCODES",
    "STACK_EFFECT_FIND_PROPERTY_OPCODES",
    "STACK_EFFECT_NEW_EMPTY_CONSTRUCTOR_OPCODES",
    "STACK_EFFECT_CALL_PROPERTY_OPCODES",
    "STACK_EFFECT_CALL_PROPVOID_OPCODES",
    "STACK_EFFECT_MEMORY_LOAD_OPCODES",
    "STACK_EFFECT_MEMORY_STORE_OPCODES",
    "STACK_EFFECT_SIGN_EXTEND_OPCODES",
    "STACK_EFFECT_BREAKPOINT_OPCODES",
    "STACK_EFFECT_NEXT_OPCODES",
    "SCOPE_EFFECT_PUSH_OPCODES",
    "STACK_EFFECT_STATIC_BY_OPCODE",
    "DYNAMIC_STACK_HINTS",
    "OPCODE_ENUM_BY_BYTE",
    "OPCODE_INFO_TABLE",
    "OPERAND_FORM_BY_OPCODE",
    "POOL_KIND_BY_OPCODE",
    "STACK_EFFECT_STATIC_TABLE",
    "opcode_info",
]
