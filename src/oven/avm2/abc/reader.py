from collections import deque
from typing import Dict, List, Optional, TYPE_CHECKING, Any, Tuple, TypeAlias, Union

from ..buffer import Buffer, BufferError
from ..file import ABCFile, MetadataItem, MetadataInfo
from ..constant_pool import ConstantPool, NamespaceInfo, NamespaceSet, Multiname
from ..exceptions import InvalidABCCodeError
from ..methods import (
    MethodInfo,
    MethodParam,
    MethodBody,
    ExceptionInfo,
    DefaultValue,
    MethodFlags,
)
from ..traits import InstanceInfo, ClassInfo, ScriptInfo, Trait
from ..enums import (
    NamespaceKind,
    MultinameKind,
    ConstantKind,
    TraitKind,
    Instruction,
    Opcode,
    Index,
    EdgeKind,
)

TraitDataValue: TypeAlias = (
    int
    | Index[Multiname]
    | Index["MethodInfo"]
    | Index["ClassInfo"]
    | DefaultValue
    | List[int]
    | None
)


from ..instruction_formatter import InstructionFormatter
from ..verifier import MethodBodyStackVerifier
from .decoder import InstructionDecoder
from .opcode_registry import (
    CONDITIONAL_BRANCH_OPCODES,
    MULTINAME_INDEX_OPERAND_OPCODES,
    NO_OPERAND_OPCODES,
    POOL_INDEX_OPERAND_KINDS,
    RELATIVE_I24_OPERAND_OPCODES,
    RELAXED_UNDERFLOW_OPCODES,
    S8_OPERAND_OPCODES,
    SCOPE_EFFECT_PUSH_OPCODES,
    STACK_EFFECT_BINARY_OPCODES,
    STACK_EFFECT_BREAKPOINT_OPCODES,
    STACK_EFFECT_CALL_PROPERTY_OPCODES,
    STACK_EFFECT_CALL_PROPVOID_OPCODES,
    STACK_EFFECT_FIND_PROPERTY_OPCODES,
    STACK_EFFECT_GET_PROPERTY_OPCODES,
    STACK_EFFECT_GET_SCOPE_OPCODES,
    STACK_EFFECT_MEMORY_LOAD_OPCODES,
    STACK_EFFECT_MEMORY_STORE_OPCODES,
    STACK_EFFECT_NEW_EMPTY_CONSTRUCTOR_OPCODES,
    STACK_EFFECT_NEXT_OPCODES,
    STACK_EFFECT_OVERRIDES,
    STACK_EFFECT_SET_PROPERTY_OPCODES,
    STACK_EFFECT_SIGN_EXTEND_OPCODES,
    STACK_EFFECT_STATIC_BY_OPCODE,
    STACK_EFFECT_STATIC_TABLE,
    STACK_EFFECT_UNARY_OPCODES,
    TERMINATOR_OPCODES,
    TWO_U30_MULTINAME_COUNT_OPERAND_OPCODES,
    TWO_U30_PLAIN_OPERAND_OPCODES,
    U8_OPERAND_OPCODES,
    U30_PLAIN_OPERAND_OPCODES,
)

if TYPE_CHECKING:
    from ..file import ABCFile


class ABCReader:
    """ABC file reader with parser and verifier helpers."""

    _NO_OPERAND_OPCODES = NO_OPERAND_OPCODES
    _RELATIVE_I24_OPERAND_OPCODES = RELATIVE_I24_OPERAND_OPCODES
    _S8_OPERAND_OPCODES = S8_OPERAND_OPCODES
    _U8_OPERAND_OPCODES = U8_OPERAND_OPCODES
    _U30_PLAIN_OPERAND_OPCODES = U30_PLAIN_OPERAND_OPCODES
    _POOL_INDEX_OPERAND_KINDS = POOL_INDEX_OPERAND_KINDS
    _MULTINAME_INDEX_OPERAND_OPCODES = MULTINAME_INDEX_OPERAND_OPCODES
    _TWO_U30_PLAIN_OPERAND_OPCODES = TWO_U30_PLAIN_OPERAND_OPCODES
    _TWO_U30_MULTINAME_COUNT_OPERAND_OPCODES = TWO_U30_MULTINAME_COUNT_OPERAND_OPCODES

    _CONDITIONAL_BRANCH_OPCODES = CONDITIONAL_BRANCH_OPCODES
    _TERMINATOR_OPCODES = TERMINATOR_OPCODES
    _RELAXED_UNDERFLOW_OPCODES = RELAXED_UNDERFLOW_OPCODES
    _EXCEPTION_HANDLER_ENTRY_STACK_DEPTH = 1
    _STACK_TYPE_ANY = "any"
    _STACK_TYPE_BOOLEAN = "boolean"
    _STACK_TYPE_NULL = "null"
    _STACK_TYPE_UNDEFINED = "undefined"
    _STACK_TYPE_NUMBER = "number"
    _STACK_TYPE_STRING = "string"
    _STACK_TYPE_OBJECT = "object"
    _STACK_TYPE_ARRAY = "array"
    _STACK_TYPE_FUNCTION = "function"
    _STACK_TYPE_EXCEPTION = "exception"
    _OBJECT_LIKE_RECEIVER_TYPES = frozenset(
        {
            _STACK_TYPE_OBJECT,
            _STACK_TYPE_ARRAY,
            _STACK_TYPE_FUNCTION,
            _STACK_TYPE_STRING,
            _STACK_TYPE_NUMBER,
            _STACK_TYPE_BOOLEAN,
        }
    )
    _OBJECT_BOOL_METHOD_ARITIES = {
        "hasOwnProperty": {1},
        "isPrototypeOf": {1},
        "propertyIsEnumerable": {1},
    }
    _OBJECT_STRING_METHOD_ARITIES = {
        "toString": {0},
    }
    _STRING_NUMBER_METHOD_ARITIES = {
        "charCodeAt": {1},
        "indexOf": {1},
        "lastIndexOf": {1},
        "search": {1},
    }
    _STRING_STRING_METHOD_ARITIES = {
        "charAt": {1},
        "substr": {2},
        "substring": {2},
        "slice": {2},
        "replace": {2},
        "toLowerCase": {0},
        "toUpperCase": {0},
        "concat": {1},
    }
    _ARRAY_NUMBER_METHOD_ARITIES = {
        "push": {1},
        "unshift": {1},
        "indexOf": {1},
        "lastIndexOf": {1},
    }
    _ARRAY_STRING_METHOD_ARITIES = {
        "join": {1},
    }
    _OBJECT_METHOD_NAMES = frozenset(_OBJECT_BOOL_METHOD_ARITIES) | frozenset(
        _OBJECT_STRING_METHOD_ARITIES
    )
    _STRING_METHOD_NAMES = frozenset(_STRING_NUMBER_METHOD_ARITIES) | frozenset(
        _STRING_STRING_METHOD_ARITIES
    )
    _ARRAY_METHOD_NAMES = frozenset(_ARRAY_NUMBER_METHOD_ARITIES) | frozenset(
        _ARRAY_STRING_METHOD_ARITIES
    )
    _EXCEPTION_HANDLER_ENTRY_STACK_STATE = (_STACK_TYPE_EXCEPTION,)
    _EDGE_KIND_ENTRY = EdgeKind.ENTRY
    _EDGE_KIND_NORMAL = EdgeKind.NORMAL
    _EDGE_KIND_LOOKUPSWITCH = EdgeKind.LOOKUPSWITCH
    _EDGE_KIND_EXCEPTION_ENTRY = EdgeKind.EXCEPTION_ENTRY
    _STACK_EFFECT_OVERRIDES = STACK_EFFECT_OVERRIDES
    _STACK_STATE_BASE_ONLY_OPCODES = frozenset(
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
            Opcode.LookupSwitch,
            Opcode.Label,
            Opcode.Nop,
            Opcode.Pop,
            Opcode.SetProperty,
            Opcode.InitProperty,
            Opcode.SetSuper,
            Opcode.SetSlot,
            Opcode.SetGlobalSlot,
            Opcode.CallPropVoid,
            Opcode.CallSuperVoid,
            Opcode.ConstructSuper,
            Opcode.Dxns,
            Opcode.DxnsLate,
            Opcode.Debug,
            Opcode.DebugFile,
            Opcode.DebugLine,
            Opcode.ReturnValue,
            Opcode.ReturnVoid,
            Opcode.Throw,
            Opcode.Si8,
            Opcode.Si16,
            Opcode.Si32,
            Opcode.Sf32,
            Opcode.Sf64,
            Opcode.Bkpt,
            Opcode.BkptLine,
        }
    )
    _LOCAL_FIXED_INDICES = {
        Opcode.GetLocal0: 0,
        Opcode.GetLocal1: 1,
        Opcode.GetLocal2: 2,
        Opcode.GetLocal3: 3,
        Opcode.SetLocal0: 0,
        Opcode.SetLocal1: 1,
        Opcode.SetLocal2: 2,
        Opcode.SetLocal3: 3,
    }
    _LOCAL_OPERAND_INDEX_OPCODES = frozenset(
        {
            Opcode.GetLocal,
            Opcode.SetLocal,
            Opcode.Kill,
            Opcode.IncLocal,
            Opcode.IncLocalI,
            Opcode.DecLocal,
            Opcode.DecLocalI,
        }
    )
    _LOCAL_INDEX_CANDIDATE_OPCODES = frozenset(
        set(_LOCAL_FIXED_INDICES)
        | set(_LOCAL_OPERAND_INDEX_OPCODES)
        | {Opcode.HasNext2}
    )
    _SCOPE_INDEX_CANDIDATE_OPCODES = frozenset({Opcode.GetScopeObject})
    _LOCAL_SET_OPCODES = frozenset(
        {
            Opcode.SetLocal,
            Opcode.SetLocal0,
            Opcode.SetLocal1,
            Opcode.SetLocal2,
            Opcode.SetLocal3,
        }
    )
    _LOCAL_INCDEC_OPCODES = frozenset(
        {
            Opcode.IncLocal,
            Opcode.IncLocalI,
            Opcode.DecLocal,
            Opcode.DecLocalI,
        }
    )
    _LOCAL_STATE_MUTATION_OPCODES = (
        _LOCAL_SET_OPCODES
        | _LOCAL_INCDEC_OPCODES
        | frozenset(
            {
                Opcode.Kill,
                Opcode.HasNext2,
            }
        )
    )
    _SCOPE_EFFECT_PUSH_OPCODES = SCOPE_EFFECT_PUSH_OPCODES
    _SCOPE_STATE_MUTATION_OPCODES = _SCOPE_EFFECT_PUSH_OPCODES | frozenset(
        {Opcode.PopScope}
    )
    _STACK_EFFECT_BINARY_OPCODES = STACK_EFFECT_BINARY_OPCODES
    _STACK_EFFECT_UNARY_OPCODES = STACK_EFFECT_UNARY_OPCODES
    _STACK_EFFECT_GET_PROPERTY_OPCODES = STACK_EFFECT_GET_PROPERTY_OPCODES
    _STACK_EFFECT_SET_PROPERTY_OPCODES = STACK_EFFECT_SET_PROPERTY_OPCODES
    _STACK_EFFECT_GET_SCOPE_OPCODES = STACK_EFFECT_GET_SCOPE_OPCODES
    _STACK_EFFECT_FIND_PROPERTY_OPCODES = STACK_EFFECT_FIND_PROPERTY_OPCODES
    _STACK_EFFECT_NEW_EMPTY_CONSTRUCTOR_OPCODES = (
        STACK_EFFECT_NEW_EMPTY_CONSTRUCTOR_OPCODES
    )
    _STACK_EFFECT_CALL_PROPERTY_OPCODES = STACK_EFFECT_CALL_PROPERTY_OPCODES
    _STACK_EFFECT_CALL_PROPVOID_OPCODES = STACK_EFFECT_CALL_PROPVOID_OPCODES
    _STACK_EFFECT_MEMORY_LOAD_OPCODES = STACK_EFFECT_MEMORY_LOAD_OPCODES
    _STACK_EFFECT_MEMORY_STORE_OPCODES = STACK_EFFECT_MEMORY_STORE_OPCODES
    _STACK_EFFECT_SIGN_EXTEND_OPCODES = STACK_EFFECT_SIGN_EXTEND_OPCODES
    _STACK_EFFECT_BREAKPOINT_OPCODES = STACK_EFFECT_BREAKPOINT_OPCODES
    _STACK_EFFECT_NEXT_OPCODES = STACK_EFFECT_NEXT_OPCODES
    _STACK_EFFECT_STATIC_OPCODES = STACK_EFFECT_STATIC_BY_OPCODE
    _STACK_EFFECT_STATIC_TABLE = STACK_EFFECT_STATIC_TABLE
    _STACK_STATE_COERCE_RESULT_OPCODES = frozenset(
        {
            Opcode.AsType,
            Opcode.Coerce,
            Opcode.CoerceA,
            Opcode.AsTypeLate,
        }
    )
    _STACK_STATE_FIND_PROPERTY_OBJECT_OPCODES = frozenset(
        {Opcode.FindProperty, Opcode.FindPropStrict, Opcode.FindDef}
    )
    _STACK_STATE_ANY_RESULT_OPCODES = frozenset(
        {
            Opcode.GetLex,
            Opcode.GetSlot,
            Opcode.GetGlobalSlot,
            Opcode.Call,
            Opcode.NextValue,
        }
    )
    _STACK_STATE_OBJECT_RESULT_OPCODES = frozenset(
        {Opcode.CheckFilter, Opcode.GetDescendants}
    )
    _STACK_STATE_STRING_RESULT_OPCODES = frozenset({Opcode.EscXElem, Opcode.EscXAttr})
    _STACK_STATE_GETLOCAL_OPCODES = frozenset(
        {
            Opcode.GetLocal,
            Opcode.GetLocal0,
            Opcode.GetLocal1,
            Opcode.GetLocal2,
            Opcode.GetLocal3,
        }
    )
    _STACK_STATE_CALL_PROPERTY_OPCODES = frozenset(
        {Opcode.CallProperty, Opcode.CallPropLex, Opcode.CallSuper}
    )
    _DEFAULT_PUSH_TYPE_OVERRIDES = {
        Opcode.PushByte: _STACK_TYPE_NUMBER,
        Opcode.PushShort: _STACK_TYPE_NUMBER,
        Opcode.PushInt: _STACK_TYPE_NUMBER,
        Opcode.PushUint: _STACK_TYPE_NUMBER,
        Opcode.PushDouble: _STACK_TYPE_NUMBER,
        Opcode.PushNaN: _STACK_TYPE_NUMBER,
        Opcode.PushTrue: _STACK_TYPE_BOOLEAN,
        Opcode.PushFalse: _STACK_TYPE_BOOLEAN,
        Opcode.PushNull: _STACK_TYPE_NULL,
        Opcode.PushUndefined: _STACK_TYPE_UNDEFINED,
        Opcode.PushString: _STACK_TYPE_STRING,
        Opcode.ConvertS: _STACK_TYPE_STRING,
        Opcode.CoerceS: _STACK_TYPE_STRING,
        Opcode.TypeOf: _STACK_TYPE_STRING,
        Opcode.AddI: _STACK_TYPE_NUMBER,
        Opcode.ConvertD: _STACK_TYPE_NUMBER,
        Opcode.ConvertI: _STACK_TYPE_NUMBER,
        Opcode.ConvertU: _STACK_TYPE_NUMBER,
        Opcode.CoerceD: _STACK_TYPE_NUMBER,
        Opcode.CoerceI: _STACK_TYPE_NUMBER,
        Opcode.CoerceU: _STACK_TYPE_NUMBER,
        Opcode.Subtract: _STACK_TYPE_NUMBER,
        Opcode.SubtractI: _STACK_TYPE_NUMBER,
        Opcode.Multiply: _STACK_TYPE_NUMBER,
        Opcode.MultiplyI: _STACK_TYPE_NUMBER,
        Opcode.Divide: _STACK_TYPE_NUMBER,
        Opcode.Modulo: _STACK_TYPE_NUMBER,
        Opcode.BitAnd: _STACK_TYPE_NUMBER,
        Opcode.BitOr: _STACK_TYPE_NUMBER,
        Opcode.BitXor: _STACK_TYPE_NUMBER,
        Opcode.LShift: _STACK_TYPE_NUMBER,
        Opcode.RShift: _STACK_TYPE_NUMBER,
        Opcode.URShift: _STACK_TYPE_NUMBER,
        Opcode.Increment: _STACK_TYPE_NUMBER,
        Opcode.IncrementI: _STACK_TYPE_NUMBER,
        Opcode.Decrement: _STACK_TYPE_NUMBER,
        Opcode.DecrementI: _STACK_TYPE_NUMBER,
        Opcode.Negate: _STACK_TYPE_NUMBER,
        Opcode.NegateI: _STACK_TYPE_NUMBER,
        Opcode.BitNot: _STACK_TYPE_NUMBER,
        Opcode.Sxi1: _STACK_TYPE_NUMBER,
        Opcode.Sxi8: _STACK_TYPE_NUMBER,
        Opcode.Sxi16: _STACK_TYPE_NUMBER,
        Opcode.Li8: _STACK_TYPE_NUMBER,
        Opcode.Li16: _STACK_TYPE_NUMBER,
        Opcode.Li32: _STACK_TYPE_NUMBER,
        Opcode.Lf32: _STACK_TYPE_NUMBER,
        Opcode.Lf64: _STACK_TYPE_NUMBER,
        Opcode.Timestamp: _STACK_TYPE_NUMBER,
        Opcode.NewObject: _STACK_TYPE_OBJECT,
        Opcode.NewActivation: _STACK_TYPE_OBJECT,
        Opcode.NewCatch: _STACK_TYPE_OBJECT,
        Opcode.NewClass: _STACK_TYPE_OBJECT,
        Opcode.Construct: _STACK_TYPE_OBJECT,
        Opcode.ConstructProp: _STACK_TYPE_OBJECT,
        Opcode.ApplyType: _STACK_TYPE_OBJECT,
        Opcode.ConvertO: _STACK_TYPE_OBJECT,
        Opcode.CoerceO: _STACK_TYPE_OBJECT,
        Opcode.GetGlobalScope: _STACK_TYPE_OBJECT,
        Opcode.GetScopeObject: _STACK_TYPE_OBJECT,
        Opcode.GetOuterScope: _STACK_TYPE_OBJECT,
        Opcode.NewArray: _STACK_TYPE_ARRAY,
        Opcode.NewFunction: _STACK_TYPE_FUNCTION,
        Opcode.Not: _STACK_TYPE_BOOLEAN,
        Opcode.ConvertB: _STACK_TYPE_BOOLEAN,
        Opcode.CoerceB: _STACK_TYPE_BOOLEAN,
        Opcode.Equals: _STACK_TYPE_BOOLEAN,
        Opcode.StrictEquals: _STACK_TYPE_BOOLEAN,
        Opcode.LessThan: _STACK_TYPE_BOOLEAN,
        Opcode.LessEquals: _STACK_TYPE_BOOLEAN,
        Opcode.GreaterThan: _STACK_TYPE_BOOLEAN,
        Opcode.GreaterEquals: _STACK_TYPE_BOOLEAN,
        Opcode.In: _STACK_TYPE_BOOLEAN,
        Opcode.InstanceOf: _STACK_TYPE_BOOLEAN,
        Opcode.IsType: _STACK_TYPE_BOOLEAN,
        Opcode.IsTypeLate: _STACK_TYPE_BOOLEAN,
        Opcode.HasNext: _STACK_TYPE_BOOLEAN,
        Opcode.HasNext2: _STACK_TYPE_BOOLEAN,
        Opcode.DeleteProperty: _STACK_TYPE_BOOLEAN,
    }

    @staticmethod
    def _op_int(instruction: Instruction, index: int) -> int:
        if not instruction.operands or len(instruction.operands) <= index:
            raise ValueError(
                f"Invalid operand index {index} for instruction {instruction}"
            )
        operand = instruction.operands[index]
        if isinstance(operand, int):
            return operand
        if isinstance(operand, str):
            return int(operand)
        raise TypeError(
            f"Operand at index {index} is not convertible to int: {operand}"
        )
        # For other types, assume they can be converted
        return int(operand)

    def __init__(
        self,
        data: bytes,
        *,
        strict_metadata_indices: bool = False,
        verify_stack: bool = False,
        verify_relaxed: bool = False,
        verify_stack_semantics: Optional[bool] = None,
        verify_branch_targets: Optional[bool] = None,
        strict_lookupswitch: Optional[bool] = None,
        relax_join_depth: Optional[bool] = None,
        relax_join_types: Optional[bool] = None,
        prefer_precise_any_join: bool = False,
        precision_enhanced: bool = False,
    ):
        self._buffer = Buffer(data)
        self._strict_metadata_indices = strict_metadata_indices
        self._verify_stack = verify_stack
        self._verify_stack_semantics = (
            verify_stack if verify_stack_semantics is None else verify_stack_semantics
        )
        self._verify_branch_targets = (
            verify_stack if verify_branch_targets is None else verify_branch_targets
        )
        self._verify_relaxed = verify_relaxed
        self._strict_lookupswitch = (
            (not verify_relaxed) if strict_lookupswitch is None else strict_lookupswitch
        )
        self._relax_join_depth = (
            verify_relaxed if relax_join_depth is None else relax_join_depth
        )
        self._relax_join_types = (
            verify_relaxed if relax_join_types is None else relax_join_types
        )
        self._prefer_precise_any_join = prefer_precise_any_join
        self._precision_enhanced = precision_enhanced
        self._method_infos_for_verifier: tuple[MethodInfo, ...] = ()
        self._stack_verifier = MethodBodyStackVerifier(self)
        self._instruction_formatter = InstructionFormatter()
        self._instruction_decoder = InstructionDecoder(verify_relaxed=verify_relaxed)

    @property
    def data(self) -> bytes:
        return self._buffer.data

    @data.setter
    def data(self, value: bytes) -> None:
        # Keep compatibility with tests that reassign raw data.
        self._buffer = Buffer(value)

    @property
    def pos(self) -> int:
        return self._buffer.offset

    @pos.setter
    def pos(self, value: int) -> None:
        if value < 0:
            raise ValueError("pos cannot be negative")
        self._buffer.offset = value

    def read_u8(self) -> int:
        return self._buffer.read_u8()

    def read_u16(self) -> int:
        return self._buffer.read_u16()

    def read_u30(self) -> int:
        """Read a variable-length encoded unsigned 30-bit integer."""
        try:
            value = self._buffer.read_vuint32()
        except ValueError:
            if self._verify_relaxed:
                # Preserve forward progress in compatibility mode when the
                # stream contains malformed 5-byte u30/u32 encodings.
                return 0
            raise
        if value <= 0x3FFFFFFF:
            return value
        if self._verify_relaxed:
            # Keep stream alignment in compatibility mode for malformed u30 values.
            # Returning 0 is the least-intrusive sentinel for count/index fields.
            return 0
        raise ValueError(f"u30 out of range: {value}")

    def read_u32(self) -> int:
        """Read a variable-length encoded unsigned 32-bit integer."""
        return self._buffer.read_vuint32()

    def read_i24(self) -> int:
        """Read a signed 24-bit integer."""
        return self._buffer.read_s24()

    def read_i32(self) -> int:
        """Read a variable-length encoded signed 32-bit integer."""
        return self._buffer.read_vint32()

    def read_f64(self) -> float:
        return self._buffer.read_double()

    def read_bytes(self, length: int) -> bytes:
        return self._buffer.read_bytes(length)

    def read_string(self) -> str:
        return self._buffer.read_string()

    def read_constant_pool(self) -> ConstantPool:
        """Read constant-pool sections from the stream."""
        # Integer constant pool.
        int_count = self.read_u30()
        ints = [self.read_i32() for _ in range(int_count - 1)] if int_count > 0 else []

        # Unsigned integer constant pool.
        uint_count = self.read_u30()
        uints = (
            [self.read_u32() for _ in range(uint_count - 1)] if uint_count > 0 else []
        )

        # Double constant pool.
        double_count = self.read_u30()
        doubles = (
            [self.read_f64() for _ in range(double_count - 1)]
            if double_count > 0
            else []
        )

        # String constant pool.
        string_count = self.read_u30()
        strings = (
            [self.read_string() for _ in range(string_count - 1)]
            if string_count > 0
            else []
        )

        # Namespace constant pool.
        namespaces: List[NamespaceInfo] = []
        namespace_count = self.read_u30()
        for _ in range(namespace_count - 1):
            raw_kind = self.read_u8()
            try:
                ns_kind = NamespaceKind(raw_kind)
            except ValueError:
                if not self._verify_relaxed:
                    raise InvalidABCCodeError(f"Unknown namespace kind: {raw_kind}")
                # Some non-standard or obfuscated ABC samples carry unknown
                # namespace kinds. Keep parsing in relaxed mode by coercing to
                # the broadest namespace kind.
                ns_kind = NamespaceKind.NAMESPACE
            name_idx = self.read_u30()
            if name_idx > len(strings):
                if not self._verify_relaxed:
                    raise InvalidABCCodeError(
                        f"Invalid namespace name index: {name_idx}, max: {len(strings)}"
                    )
                name_idx = 0
            namespaces.append(NamespaceInfo(ns_kind, name_idx))

        # Namespace-set constant pool.
        ns_set_count = self.read_u30()
        namespace_sets: List[NamespaceSet] = []
        for _ in range(ns_set_count - 1):
            count = self.read_u30()
            ns = []
            for _ in range(count):
                ns_idx = self.read_u30()
                if 0 < ns_idx <= len(namespaces):
                    ns.append(namespaces[ns_idx - 1])
                else:
                    if not self._verify_relaxed:
                        raise InvalidABCCodeError(
                            f"Invalid namespace index: {ns_idx}, max: {len(namespaces)}"
                        )
                    # Preserve arity while keeping forward progress in relaxed mode.
                    ns.append(NamespaceInfo(NamespaceKind.NAMESPACE, 0))
            namespace_sets.append(NamespaceSet(ns))

        # Multiname constant pool.
        multi_name_count = self.read_u30()
        multi_names: List[Multiname] = []
        for _ in range(multi_name_count - 1):
            try:
                mn_kind = MultinameKind(self.read_u8())
            except ValueError as exc:
                if not self._verify_relaxed:
                    raise InvalidABCCodeError(f"Invalid multiname kind: {exc}")
                # In relaxed mode, skip invalid multiname kinds by using a placeholder
                mn_kind = MultinameKind.QNAME
            data: Dict[str, Any] = {}

            if mn_kind in (MultinameKind.QNAME, MultinameKind.QNAMEA):
                ns_idx = self.read_u30()
                name_idx = self.read_u30()
                if ns_idx > len(namespaces):
                    raise InvalidABCCodeError(
                        f"Invalid multiname namespace index: {ns_idx}, max: {len(namespaces)}"
                    )
                if name_idx > len(strings):
                    raise InvalidABCCodeError(
                        f"Invalid multiname name index: {name_idx}, max: {len(strings)}"
                    )
                data["namespace"] = Index(ns_idx) if ns_idx > 0 else None
                data["name"] = Index(name_idx) if name_idx > 0 else None
            elif mn_kind in (MultinameKind.RTQNAME, MultinameKind.RTQNAMEA):
                name_idx = self.read_u30()
                if name_idx > len(strings):
                    raise InvalidABCCodeError(
                        f"Invalid multiname name index: {name_idx}, max: {len(strings)}"
                    )
                data["name"] = Index(name_idx) if name_idx > 0 else None
            elif mn_kind in (MultinameKind.RTQNAMEL, MultinameKind.RTQNAMELA):
                # Runtime-qualified multiname with late-resolved name carries no
                # extra pool indices in the constant-pool payload.
                pass
            elif mn_kind in (MultinameKind.MULTINAME, MultinameKind.MULTINAMEA):
                name_idx = self.read_u30()
                ns_set_idx = self.read_u30()
                if name_idx > len(strings):
                    raise InvalidABCCodeError(
                        f"Invalid multiname name index: {name_idx}, max: {len(strings)}"
                    )
                if ns_set_idx > len(namespace_sets):
                    raise InvalidABCCodeError(
                        f"Invalid multiname namespace set index: {ns_set_idx}, max: {len(namespace_sets)}"
                    )
                data["name"] = Index(name_idx) if name_idx > 0 else None
                data["namespace_set"] = (
                    namespace_sets[ns_set_idx - 1] if ns_set_idx > 0 else None
                )
            elif mn_kind in (MultinameKind.MULTINAMEL, MultinameKind.MULTINAMELA):
                ns_set_idx = self.read_u30()
                if ns_set_idx > len(namespace_sets):
                    raise InvalidABCCodeError(
                        f"Invalid multiname namespace set index: {ns_set_idx}, max: {len(namespace_sets)}"
                    )
                data["namespace_set"] = (
                    namespace_sets[ns_set_idx - 1] if ns_set_idx > 0 else None
                )
            elif mn_kind == MultinameKind.TYPENAME:
                base_idx = self.read_u30()
                param_count = self.read_u30()
                data["base_type"] = Index[Any](base_idx) if base_idx > 0 else None
                parameters: list[Index[Any] | None] = []
                for _ in range(param_count):
                    param_idx = self.read_u30()
                    parameters.append(Index[Any](param_idx) if param_idx > 0 else None)
                data["parameters"] = parameters
            else:
                raise InvalidABCCodeError(f"Unknown multiname kind: {mn_kind}")

            multi_names.append(Multiname(mn_kind, data))

        self._validate_multiname_references(multi_names)

        constant_pool = ConstantPool(
            ints=ints,
            uints=uints,
            doubles=doubles,
            strings=strings,
            namespaces=namespaces,
            namespace_sets=namespace_sets,
            multinames=multi_names,
        )
        constant_pool.preload_resolved_indices()
        return constant_pool

    @staticmethod
    def _validate_multiname_references(multinames: List[Multiname]) -> None:
        max_multiname_idx = len(multinames)
        for mn in multinames:
            if mn.kind != MultinameKind.TYPENAME:
                continue

            base = mn.data.get("base_type")
            if isinstance(base, Index) and base.value > max_multiname_idx:
                raise InvalidABCCodeError(
                    f"Invalid typename base index: {base.value}, max: {max_multiname_idx}"
                )

            parameters = mn.data.get("parameters", [])
            for param in parameters:
                if isinstance(param, Index) and param.value > max_multiname_idx:
                    raise InvalidABCCodeError(
                        f"Invalid typename parameter index: {param.value}, max: {max_multiname_idx}"
                    )

    def _read_constant_value(
        self, val_index: int, kind: int, pool: ConstantPool
    ) -> DefaultValue:
        """Read and validate a default-value constant."""
        try:
            constant_kind = ConstantKind(kind)
        except ValueError:
            raise InvalidABCCodeError(f"Invalid constant value kind: {kind:#x}")

        if constant_kind in (ConstantKind.UNDEFINED, ConstantKind.NULL):
            return DefaultValue(constant_kind, None)
        elif constant_kind == ConstantKind.FALSE:
            return DefaultValue(constant_kind, False)
        elif constant_kind == ConstantKind.TRUE:
            return DefaultValue(constant_kind, True)
        elif constant_kind in (
            ConstantKind.UTF8,
            ConstantKind.INT,
            ConstantKind.UINT,
            ConstantKind.DOUBLE,
            ConstantKind.PRIVATE_NS,
            ConstantKind.NAMESPACE,
            ConstantKind.PACKAGE_NAMESPACE,
            ConstantKind.PACKAGE_INTERNAL_NS,
            ConstantKind.PROTECTED_NAMESPACE,
            ConstantKind.EXPLICIT_NAMESPACE,
            ConstantKind.STATIC_PROTECTED_NS,
        ):
            max_index = self._constant_kind_max_index(constant_kind, pool)
            if val_index <= 0 or val_index > max_index:
                raise InvalidABCCodeError(
                    f"{constant_kind.name} default value index out of range: {val_index}, max: {max_index}"
                )
            return DefaultValue(constant_kind, Index(val_index))
        else:
            raise InvalidABCCodeError(f"Unsupported constant kind: {constant_kind}")

    @staticmethod
    def _constant_kind_max_index(kind: ConstantKind, pool: ConstantPool) -> int:
        if kind == ConstantKind.UTF8:
            return len(pool.strings)
        if kind == ConstantKind.INT:
            return len(pool.ints)
        if kind == ConstantKind.UINT:
            return len(pool.uints)
        if kind == ConstantKind.DOUBLE:
            return len(pool.doubles)
        if kind in (
            ConstantKind.PRIVATE_NS,
            ConstantKind.NAMESPACE,
            ConstantKind.PACKAGE_NAMESPACE,
            ConstantKind.PACKAGE_INTERNAL_NS,
            ConstantKind.PROTECTED_NAMESPACE,
            ConstantKind.EXPLICIT_NAMESPACE,
            ConstantKind.STATIC_PROTECTED_NS,
        ):
            return len(pool.namespaces)
        return 0

    def read_optional_value(self, pool: ConstantPool) -> Optional[DefaultValue]:
        """Read an optional constant value for trait slots/consts."""
        val_index = self.read_u30()
        if val_index == 0:
            return None
        kind = self.read_u8()
        return self._read_constant_value(val_index, kind, pool)

    def read_trait(self, pool: ConstantPool) -> Trait:
        """Read a trait entry and resolve key references."""
        name_idx: int = self.read_u30()
        name: str = pool.resolve_index(name_idx, "multiname")

        kind_and_attrs: int = self.read_u8()
        kind: TraitKind = TraitKind(kind_and_attrs & 0x0F)
        attrs: int = kind_and_attrs & 0xF0

        data: Dict[str, TraitDataValue] = {}
        metadata: List[str] = []

        match kind:
            case TraitKind.SLOT | TraitKind.CONST:
                data["slot_id"] = self.read_u30()
                type_name_idx: int = self.read_u30()
                if type_name_idx > len(pool.multinames):
                    raise InvalidABCCodeError(
                        f"trait type_name index out of range: {type_name_idx}, max: {len(pool.multinames)}"
                    )
                data["type_name"] = Index[Multiname](type_name_idx)
                data["value"] = self.read_optional_value(pool)
            case TraitKind.METHOD | TraitKind.GETTER | TraitKind.SETTER:
                data["disp_id"] = self.read_u30()
                data["method"] = Index[MethodInfo](self.read_u30())
            case TraitKind.CLASS:
                data["slot_id"] = self.read_u30()
                data["class"] = Index[ClassInfo](self.read_u30())
            case TraitKind.FUNCTION:
                data["slot_id"] = self.read_u30()
                data["function"] = Index[MethodInfo](self.read_u30())

        # Read metadata indices and resolve display names.
        if attrs & 0x40:  # ATTR_METADATA
            metadata_count: int = self.read_u30()
            metadata_indices: List[int] = []
            for _ in range(metadata_count):
                meta_idx = self.read_u30()
                metadata_indices.append(meta_idx)
                # Metadata indices reference the metadata table, not the string pool.
                # Range validation runs after the metadata section is fully parsed.
                metadata.append(pool.resolve_index(meta_idx, "string"))
            data["metadata_indices"] = metadata_indices

        return Trait(
            name=name,
            kind=kind,
            metadata=metadata,
            is_final=bool(attrs & 0x10),
            is_override=bool(attrs & 0x20),
            data=data,
        )

    def read_method(self, pool: ConstantPool) -> MethodInfo:
        """Read method signature information."""
        param_count = self.read_u30()
        return_type_idx = self.read_u30()
        if return_type_idx > len(pool.multinames):
            raise InvalidABCCodeError(
                f"return type index out of range: {return_type_idx}, max: {len(pool.multinames)}"
            )
        return_type = pool.resolve_index(return_type_idx, "multiname")

        params = []
        for _ in range(param_count):
            param_type_idx = self.read_u30()
            if param_type_idx > len(pool.multinames):
                raise InvalidABCCodeError(
                    f"param type index out of range: {param_type_idx}, max: {len(pool.multinames)}"
                )
            param_type = pool.resolve_index(param_type_idx, "multiname")
            params.append(MethodParam(kind=param_type))

        name_idx = self.read_u30()
        if name_idx > len(pool.strings):
            if not self._verify_relaxed:
                raise InvalidABCCodeError(
                    f"method name index out of range: {name_idx}, max: {len(pool.strings)}"
                )
            name_idx = 0
        name = pool.resolve_index(name_idx, "string")
        flags = MethodFlags(self.read_u8())

        # Resolve optional parameter defaults.
        if flags & MethodFlags.HAS_OPTIONAL:
            option_count = self.read_u30()
            if option_count > 0x3FFFFFFF:
                if not self._verify_relaxed:
                    raise InvalidABCCodeError(
                        f"Invalid optional parameter count: {option_count}, param_count: {param_count}"
                    )
                option_count = 0

            if option_count == 0 and not self._verify_relaxed:
                raise InvalidABCCodeError(
                    f"Invalid optional parameter count: {option_count}, param_count: {param_count}"
                )

            remaining_after_count = len(self.data) - self.pos
            max_possible_pairs = remaining_after_count // 2
            if option_count > max_possible_pairs:
                if not self._verify_relaxed:
                    raise InvalidABCCodeError(
                        "Invalid optional parameter payload size: "
                        f"option_count={option_count}, max_pairs={max_possible_pairs}"
                    )
                option_count = max_possible_pairs

            if option_count > param_count and not self._verify_relaxed:
                raise InvalidABCCodeError(
                    f"Invalid optional parameter count: {option_count}, param_count: {param_count}"
                )

            effective_option_count = min(option_count, param_count)
            discard_count = option_count - effective_option_count
            defaults: List[Optional[DefaultValue]] = []
            for _ in range(option_count):
                value_index = self.read_u30()
                value_kind = self.read_u8()
                try:
                    default_value = self._read_constant_value(
                        value_index, value_kind, pool
                    )
                except InvalidABCCodeError:
                    if not self._verify_relaxed:
                        raise
                    default_value = None
                defaults.append(default_value)

            # Optional defaults map to the tail of the parameter list.
            if effective_option_count > 0:
                tail_defaults = defaults[discard_count:]
                base_index = param_count - effective_option_count
                for i, default_value in enumerate(tail_defaults):
                    params[base_index + i].default_value = default_value

        # Resolve parameter names when present.
        if flags & MethodFlags.HAS_PARAM_NAMES:
            for param in params:
                name_idx = self.read_u30()
                if name_idx > len(pool.strings):
                    raise InvalidABCCodeError(
                        f"param name index out of range: {name_idx}, max: {len(pool.strings)}"
                    )
                param.name = pool.resolve_index(name_idx, "string")

        return MethodInfo(
            name=name, params=params, return_type=return_type, flags=flags
        )

    def read_metadata_item(self, pool: ConstantPool) -> MetadataInfo:
        """Read a metadata block."""
        name_idx = self.read_u30()
        if name_idx == 0:
            if not self._verify_relaxed:
                raise ValueError(
                    "AVM2 constraint: metadata_info.name index cannot be 0"
                )
            name = ""
        else:
            name = pool.resolve_index(name_idx, "string")

        item_count = self.read_u30()
        remaining_after_count = len(self.data) - self.pos
        max_possible_items = remaining_after_count // 2
        if item_count > max_possible_items:
            raise InvalidABCCodeError(
                "metadata item_count exceeds remaining payload capacity: "
                f"{item_count} > {max_possible_items}"
            )

        # Read all keys first, then all values.
        keys = [self.read_u30() for _ in range(item_count)]
        values = [self.read_u30() for _ in range(item_count)]

        items = []
        for key_idx, value_idx in zip(keys, values):
            if key_idx > len(pool.strings):
                if not self._verify_relaxed:
                    raise InvalidABCCodeError(
                        f"metadata key index out of range: {key_idx}, max: {len(pool.strings)}"
                    )
                key = None
            else:
                key = pool.resolve_index(key_idx, "string") if key_idx != 0 else None
            if value_idx > len(pool.strings):
                if not self._verify_relaxed:
                    raise InvalidABCCodeError(
                        f"metadata value index out of range: {value_idx}, max: {len(pool.strings)}"
                    )
                value = ""
            else:
                value = pool.resolve_index(value_idx, "string")
            items.append(MetadataItem(key, value))

        return MetadataInfo(name, items)

    def read_instance(self, pool: ConstantPool) -> InstanceInfo:
        """Read instance information."""
        name_idx = self.read_u30()
        if name_idx > len(pool.multinames):
            raise InvalidABCCodeError(
                f"instance name index out of range: {name_idx}, max: {len(pool.multinames)}"
            )
        name = pool.resolve_index(name_idx, "multiname")

        super_name_idx = self.read_u30()
        if super_name_idx > len(pool.multinames):
            raise InvalidABCCodeError(
                f"instance super_name index out of range: {super_name_idx}, max: {len(pool.multinames)}"
            )
        super_name = pool.resolve_index(super_name_idx, "multiname")
        flags = self.read_u8()

        protected_namespace = None
        if flags & 0x08:
            protected_ns_idx = self.read_u30()
            if protected_ns_idx == 0 or protected_ns_idx > len(pool.namespaces):
                raise InvalidABCCodeError(
                    "instance protected namespace index out of range: "
                    f"{protected_ns_idx}, valid: 1..{len(pool.namespaces)}"
                )
            protected_namespace = pool.resolve_index(protected_ns_idx, "namespace")

        interface_count = self.read_u30()
        interfaces = []
        for _ in range(interface_count):
            interface_idx = self.read_u30()
            if interface_idx > len(pool.multinames):
                raise InvalidABCCodeError(
                    f"instance interface index out of range: {interface_idx}, max: {len(pool.multinames)}"
                )
            interfaces.append(pool.resolve_index(interface_idx, "multiname"))

        init_method = self.read_u30()
        trait_count = self.read_u30()
        traits = [self.read_trait(pool) for _ in range(trait_count)]

        return InstanceInfo(
            name=name,
            super_name=super_name,
            is_sealed=bool(flags & 0x01),
            is_final=bool(flags & 0x02),
            is_interface=bool(flags & 0x04),
            protected_namespace=protected_namespace,
            interfaces=interfaces,
            init_method=init_method,
            traits=traits,
        )

    def read_class(self, pool: ConstantPool) -> ClassInfo:
        """Read class information."""
        init_method = self.read_u30()
        trait_count = self.read_u30()
        traits = [self.read_trait(pool) for _ in range(trait_count)]
        return ClassInfo(init_method, traits)

    def read_script(self, pool: ConstantPool) -> ScriptInfo:
        """Read script information."""
        init_method = self.read_u30()
        trait_count = self.read_u30()
        traits = [self.read_trait(pool) for _ in range(trait_count)]
        return ScriptInfo(init_method, traits)

    def parse_instructions(
        self, code: bytes, pool: Optional[ConstantPool]
    ) -> List[Instruction]:
        """Parse bytecode instructions via the dedicated instruction decoder."""
        return self._instruction_decoder.parse_instructions(code, pool)

    def serialize_instructions_to_string(
        self,
        instructions: List[Instruction],
        pool: Optional[ConstantPool] = None,
        show_offsets: bool = True,
    ) -> str:
        return self._instruction_formatter.serialize_instructions_to_string(
            instructions=instructions,
            pool=pool,
            show_offsets=show_offsets,
        )

    def serialize_instructions_as_function_calls(
        self, instructions: List[Instruction], pool: Optional[ConstantPool] = None
    ) -> str:
        return self._instruction_formatter.serialize_instructions_as_function_calls(
            instructions=instructions,
            pool=pool,
        )

    def _opcode_to_function_name(self, opcode_name: str) -> str:
        return self._instruction_formatter._opcode_to_function_name(opcode_name)

    def _resolve_operand_for_function_call(
        self, opcode: Opcode, operand: Any, pool: Optional[ConstantPool]
    ) -> str:
        return self._instruction_formatter._resolve_operand_for_function_call(
            opcode, operand, pool
        )

    def _resolve_operand_for_display(
        self,
        opcode: Opcode,
        operand_index: int,
        operand: Any,
        pool: Optional[ConstantPool],
    ) -> str:
        return self._instruction_formatter._resolve_operand_for_display(
            opcode,
            operand_index,
            operand,
            pool,
        )

    def _resolve_operand_for_output(
        self, opcode: Opcode, operand: Any, pool: Optional[ConstantPool]
    ) -> str:
        return self._instruction_formatter._resolve_operand_for_output(
            opcode, operand, pool
        )

    def read_method_body(self, pool: ConstantPool) -> MethodBody:
        """Read a method-body record."""
        method = self.read_u30()
        max_stack = self.read_u30()
        num_locals = self.read_u30()
        init_scope_depth = self.read_u30()
        max_scope_depth = self.read_u30()
        if max_scope_depth < init_scope_depth:
            raise InvalidABCCodeError(
                "Invalid scope depth: "
                f"init_scope_depth({init_scope_depth}) > max_scope_depth({max_scope_depth})"
            )

        code_length = self.read_u30()
        code = self.read_bytes(code_length)

        instructions_parse_failed = False
        try:
            instructions = self.parse_instructions(code, pool)
        except (InvalidABCCodeError, BufferError, ValueError, IndexError):
            if not self._verify_relaxed:
                raise
            # Keep method-body stream alignment in relaxed mode even when a code
            # block contains unknown or malformed opcodes.
            instructions = []
            instructions_parse_failed = True

        exception_count = self.read_u30()
        exceptions = []
        for _ in range(exception_count):
            from_offset = self.read_u30()
            to_offset = self.read_u30()
            target_offset = self.read_u30()

            exc_type_idx = self.read_u30()
            if exc_type_idx > len(pool.multinames):
                raise InvalidABCCodeError(
                    f"exception type index out of range: {exc_type_idx}, max: {len(pool.multinames)}"
                )

            var_name_idx = self.read_u30()
            if var_name_idx > len(pool.multinames):
                raise InvalidABCCodeError(
                    f"exception var_name index out of range: {var_name_idx}, max: {len(pool.multinames)}"
                )

            exceptions.append(
                ExceptionInfo(
                    from_offset=from_offset,
                    to_offset=to_offset,
                    target_offset=target_offset,
                    exc_type=pool.resolve_index(exc_type_idx, "multiname"),
                    var_name=pool.resolve_index(var_name_idx, "multiname"),
                )
            )

        if not (self._verify_relaxed and instructions_parse_failed):
            try:
                self._validate_exception_ranges(exceptions, code_length, instructions)
            except InvalidABCCodeError:
                if not self._verify_relaxed:
                    raise
                # Obfuscated/producer-buggy ABC payloads occasionally carry
                # malformed exception table entries. In relaxed mode we keep
                # forward progress by dropping only invalid entries.
                exceptions = self._filter_valid_exception_ranges(
                    exceptions=exceptions,
                    code_length=code_length,
                    instructions=instructions,
                )

        trait_count = self.read_u30()
        traits = [self.read_trait(pool) for _ in range(trait_count)]

        return MethodBody(
            method=method,
            max_stack=max_stack,
            num_locals=num_locals,
            init_scope_depth=init_scope_depth,
            max_scope_depth=max_scope_depth,
            code=code,
            exceptions=exceptions,
            traits=traits,
            instructions=instructions,
        )

    def read_abc_file(self) -> "ABCFile":
        """Read and validate a complete ABC payload."""
        try:
            minor_version = self.read_u16()
            major_version = self.read_u16()
            constant_pool = self.read_constant_pool()

            # Read methods.
            method_count = self.read_u30()
            methods = [self.read_method(constant_pool) for _ in range(method_count)]
            methods_end_pos = self.pos

            # Read metadata.
            metadata_count = self.read_u30()
            metadata_table_start = self.pos
            metadata: List[MetadataInfo] = []
            metadata_error: Exception | None = None
            metadata_failure_pos: int | None = None
            for _ in range(metadata_count):
                metadata_item_pos = self.pos
                try:
                    metadata.append(self.read_metadata_item(constant_pool))
                except (InvalidABCCodeError, BufferError, ValueError, IndexError):
                    if not self._verify_relaxed:
                        raise
                    # In compatibility mode, stop metadata parsing at the first
                    # structurally invalid entry and switch to resync recovery.
                    metadata_error = InvalidABCCodeError(
                        f"Malformed metadata entry at offset {metadata_item_pos}"
                    )
                    metadata_failure_pos = metadata_item_pos
                    self.pos = metadata_item_pos
                    break

            # Read tail sections from the current stream position.
            instances: List[InstanceInfo]
            classes: List[ClassInfo]
            scripts: List[ScriptInfo]
            method_bodies: List[MethodBody]
            try:
                instances, classes, scripts, method_bodies = self._read_tail_sections(
                    constant_pool
                )
            except (
                InvalidABCCodeError,
                BufferError,
                ValueError,
                IndexError,
            ) as tail_error:
                if not self._verify_relaxed:
                    raise
                recovery_error = metadata_error or tail_error
                candidates = self._recover_sections_relaxed(
                    constant_pool=constant_pool,
                    methods=methods,
                    metadata_prefix=metadata,
                    metadata_count=metadata_count,
                    metadata_table_start=metadata_table_start,
                    metadata_failure_pos=(
                        metadata_failure_pos
                        if metadata_failure_pos is not None
                        else self.pos
                    ),
                    methods_end_pos=methods_end_pos,
                )
                if not candidates:
                    raise InvalidABCCodeError(
                        "Unable to recover ABC tail sections after metadata/method alignment failure"
                    ) from recovery_error

                selected_error: InvalidABCCodeError | None = None
                selected = None
                for candidate in candidates:
                    candidate_metadata = candidate["metadata"]
                    candidate_instances = candidate["instances"]
                    candidate_classes = candidate["classes"]
                    candidate_scripts = candidate["scripts"]
                    candidate_method_bodies = candidate["method_bodies"]

                    try:
                        self._validate_sections(
                            methods=methods,
                            metadata=candidate_metadata,
                            instances=candidate_instances,
                            classes=candidate_classes,
                            scripts=candidate_scripts,
                            method_bodies=candidate_method_bodies,
                            link_method_bodies=False,
                            verify_method_bodies=True,
                            validate_metadata_indices=True,
                        )
                    except InvalidABCCodeError as exc:
                        selected_error = exc
                        continue

                    selected = candidate
                    break

                if selected is None:
                    raise InvalidABCCodeError(
                        "Unable to recover ABC sections with verifier-compatible candidate"
                    ) from selected_error

                metadata = selected["metadata"]
                instances = selected["instances"]
                classes = selected["classes"]
                scripts = selected["scripts"]
                method_bodies = selected["method_bodies"]
                self.pos = selected["end_pos"]

            self._validate_sections(
                methods=methods,
                metadata=metadata,
                instances=instances,
                classes=classes,
                scripts=scripts,
                method_bodies=method_bodies,
                link_method_bodies=True,
                verify_method_bodies=True,
                validate_metadata_indices=True,
            )

            # Check for trailing bytes after valid payload
            # In relaxed mode, we allow trailing bytes for compatibility
            if not self._buffer.eof() and not self._verify_relaxed:
                raise InvalidABCCodeError("trailing bytes after valid ABC payload")

            return ABCFile(
                minor_version=minor_version,
                major_version=major_version,
                constant_pool=constant_pool,
                methods=methods,
                metadata=metadata,
                instances=instances,
                classes=classes,
                scripts=scripts,
                method_bodies=method_bodies,
            )
        except InvalidABCCodeError:
            raise
        except BufferError as exc:
            raise InvalidABCCodeError(
                f"Malformed or truncated ABC data at offset {self.pos}: {exc}"
            ) from exc
        except (ValueError, IndexError) as exc:
            raise InvalidABCCodeError(
                f"Malformed ABC data at offset {self.pos}: {exc}"
            ) from exc

    def _read_tail_sections(
        self,
        constant_pool: ConstantPool,
    ) -> tuple[List[InstanceInfo], List[ClassInfo], List[ScriptInfo], List[MethodBody]]:
        class_count = self.read_u30()
        instances = [self.read_instance(constant_pool) for _ in range(class_count)]
        classes = [self.read_class(constant_pool) for _ in range(class_count)]

        script_count = self.read_u30()
        scripts = [self.read_script(constant_pool) for _ in range(script_count)]

        method_body_count = self.read_u30()
        method_bodies = [
            self.read_method_body(constant_pool) for _ in range(method_body_count)
        ]
        return instances, classes, scripts, method_bodies

    def _validate_sections(
        self,
        *,
        methods: List[MethodInfo],
        metadata: List[MetadataInfo],
        instances: List[InstanceInfo],
        classes: List[ClassInfo],
        scripts: List[ScriptInfo],
        method_bodies: List[MethodBody],
        link_method_bodies: bool,
        verify_method_bodies: bool,
        validate_metadata_indices: bool,
    ) -> None:
        for instance in instances:
            if instance.init_method >= len(methods):
                raise InvalidABCCodeError(
                    f"instance init method index out of range: {instance.init_method}, max: {len(methods) - 1}"
                )

        for cls in classes:
            if cls.init_method >= len(methods):
                raise InvalidABCCodeError(
                    f"class init method index out of range: {cls.init_method}, max: {len(methods) - 1}"
                )

        for script in scripts:
            if script.init_method >= len(methods):
                if not self._verify_relaxed:
                    raise InvalidABCCodeError(
                        f"script init method index out of range: {script.init_method}, max: {len(methods) - 1}"
                    )

        for instance in instances:
            if validate_metadata_indices:
                self._validate_trait_metadata_indices(
                    instance.traits,
                    metadata_count=len(metadata),
                    context="instance",
                    strict_metadata_indices=self._strict_metadata_indices,
                )
                self._resolve_trait_metadata_names(
                    instance.traits,
                    metadata=metadata,
                    strict_metadata_indices=self._strict_metadata_indices,
                )
            self._validate_trait_references(
                instance.traits,
                methods_count=len(methods),
                classes_count=len(classes),
                context="instance",
            )
        for cls in classes:
            if validate_metadata_indices:
                self._validate_trait_metadata_indices(
                    cls.traits,
                    metadata_count=len(metadata),
                    context="class",
                    strict_metadata_indices=self._strict_metadata_indices,
                )
                self._resolve_trait_metadata_names(
                    cls.traits,
                    metadata=metadata,
                    strict_metadata_indices=self._strict_metadata_indices,
                )
            self._validate_trait_references(
                cls.traits,
                methods_count=len(methods),
                classes_count=len(classes),
                context="class",
            )
        for script in scripts:
            if validate_metadata_indices:
                self._validate_trait_metadata_indices(
                    script.traits,
                    metadata_count=len(metadata),
                    context="script",
                    strict_metadata_indices=self._strict_metadata_indices,
                )
                self._resolve_trait_metadata_names(
                    script.traits,
                    metadata=metadata,
                    strict_metadata_indices=self._strict_metadata_indices,
                )
            self._validate_trait_references(
                script.traits,
                methods_count=len(methods),
                classes_count=len(classes),
                context="script",
            )
        self._method_infos_for_verifier = tuple(methods)
        for body in method_bodies:
            if validate_metadata_indices:
                self._validate_trait_metadata_indices(
                    body.traits,
                    metadata_count=len(metadata),
                    context="method_body",
                    strict_metadata_indices=self._strict_metadata_indices,
                )
                self._resolve_trait_metadata_names(
                    body.traits,
                    metadata=metadata,
                    strict_metadata_indices=self._strict_metadata_indices,
                )
            self._validate_trait_references(
                body.traits,
                methods_count=len(methods),
                classes_count=len(classes),
                context="method_body",
            )

        if link_method_bodies:
            for method in methods:
                method.body = None

        seen_method_indexes: set[int] = set()
        for body in method_bodies:
            method_index = body.method
            if method_index >= len(methods):
                if not self._verify_relaxed:
                    raise InvalidABCCodeError(
                        f"Method body references invalid method index: {method_index}"
                    )
                continue

            method_info = methods[method_index]
            if method_info.flags & MethodFlags.NATIVE:
                raise InvalidABCCodeError(
                    f"Method body references native method: {method_index}"
                )
            if body.num_locals < len(method_info.params):
                raise InvalidABCCodeError(
                    "Invalid method body num_locals: "
                    f"{body.num_locals}, requires >= param_count({len(method_info.params)}) "
                    f"for method {method_index}"
                )
            if verify_method_bodies:
                # Stack-semantics verification computes and validates CFG edges/targets.
                # Skip the standalone branch-target pass to avoid duplicate traversal.
                if self._verify_branch_targets and not self._verify_stack_semantics:
                    self._validate_method_body_branch_targets(body)
                if self._verify_stack_semantics:
                    self._stack_verifier.validate_method_body_stack(method_index, body)

            if method_index in seen_method_indexes:
                raise InvalidABCCodeError(
                    f"Duplicate method body for method {method_index}"
                )
            seen_method_indexes.add(method_index)

            if link_method_bodies:
                methods[method_index].body = body

    @staticmethod
    def _recovery_candidate_sort_key(
        candidate: dict[str, Any],
    ) -> tuple[int, int, int, int]:
        return (
            -int(candidate["metadata_recovered"]),
            int(candidate["offset_delta"]),
            abs(int(candidate["method_shift"])),
            int(candidate["tail_start"]),
        )

    def _push_recovery_candidate(
        self,
        candidates: List[dict[str, Any]],
        candidate: dict[str, Any],
        *,
        limit: int,
    ) -> None:
        candidates.append(candidate)
        candidates.sort(key=self._recovery_candidate_sort_key)
        del candidates[limit:]

    def _try_recovery_candidate(
        self,
        *,
        start_pos: int,
        constant_pool: ConstantPool,
        methods: List[MethodInfo],
        metadata: List[MetadataInfo],
    ) -> dict[str, Any] | None:
        saved_pos = self.pos
        try:
            self.pos = start_pos
            instances, classes, scripts, method_bodies = self._read_tail_sections(
                constant_pool
            )
            if not self._buffer.eof():
                return None

            # Keep recovery candidate checks lightweight; full verifier checks run
            # after selecting top-ranked candidates.
            self._validate_sections(
                methods=methods,
                metadata=metadata,
                instances=instances,
                classes=classes,
                scripts=scripts,
                method_bodies=method_bodies,
                link_method_bodies=False,
                verify_method_bodies=False,
                validate_metadata_indices=False,
            )
            return {
                "metadata": metadata,
                "instances": instances,
                "classes": classes,
                "scripts": scripts,
                "method_bodies": method_bodies,
                "end_pos": self.pos,
                "tail_start": start_pos,
            }
        except (InvalidABCCodeError, BufferError, ValueError, IndexError):
            return None
        finally:
            self.pos = saved_pos

    def _scan_recovery_window(
        self,
        *,
        candidates: List[dict[str, Any]],
        constant_pool: ConstantPool,
        methods: List[MethodInfo],
        metadata_prefix: List[MetadataInfo],
        metadata_remaining: int,
        scan_start: int,
        scan_end: int,
        anchor_offset: int,
        method_shift: int,
        limit: int,
    ) -> None:
        saved_pos = self.pos
        try:
            for start in range(scan_start, scan_end + 1):
                metadata_entries = list(metadata_prefix)

                candidate = self._try_recovery_candidate(
                    start_pos=start,
                    constant_pool=constant_pool,
                    methods=methods,
                    metadata=metadata_entries,
                )
                if candidate is not None:
                    candidate["metadata_recovered"] = len(metadata_entries)
                    candidate["offset_delta"] = abs(start - anchor_offset) + abs(
                        method_shift
                    )
                    candidate["method_shift"] = method_shift
                    self._push_recovery_candidate(candidates, candidate, limit=limit)

                pos = start
                for _ in range(metadata_remaining):
                    self.pos = pos
                    try:
                        metadata_item = self.read_metadata_item(constant_pool)
                    except (InvalidABCCodeError, BufferError, ValueError, IndexError):
                        break
                    pos = self.pos
                    metadata_entries.append(metadata_item)

                    candidate = self._try_recovery_candidate(
                        start_pos=pos,
                        constant_pool=constant_pool,
                        methods=methods,
                        metadata=metadata_entries,
                    )
                    if candidate is None:
                        continue

                    candidate["metadata_recovered"] = len(metadata_entries)
                    candidate["offset_delta"] = abs(pos - anchor_offset) + abs(
                        method_shift
                    )
                    candidate["method_shift"] = method_shift
                    self._push_recovery_candidate(candidates, candidate, limit=limit)
        finally:
            self.pos = saved_pos

    def _recover_sections_relaxed(
        self,
        *,
        constant_pool: ConstantPool,
        methods: List[MethodInfo],
        metadata_prefix: List[MetadataInfo],
        metadata_count: int,
        metadata_table_start: int,
        metadata_failure_pos: int,
        methods_end_pos: int,
    ) -> List[dict[str, Any]]:
        candidates: List[dict[str, Any]] = []
        candidate_limit = 12

        metadata_remaining = max(0, metadata_count - len(metadata_prefix))
        scan_start = max(metadata_failure_pos, metadata_table_start)

        # Fast-path probe around the failure anchor to reduce full-window scans
        # on noisy or heavily obfuscated payloads.
        focused_end = min(len(self.data), scan_start + 512)
        self._scan_recovery_window(
            candidates=candidates,
            constant_pool=constant_pool,
            methods=methods,
            metadata_prefix=metadata_prefix,
            metadata_remaining=metadata_remaining,
            scan_start=scan_start,
            scan_end=focused_end,
            anchor_offset=metadata_failure_pos,
            method_shift=0,
            limit=candidate_limit,
        )
        if candidates:
            return candidates

        scan_end = min(len(self.data), scan_start + 4096)
        self._scan_recovery_window(
            candidates=candidates,
            constant_pool=constant_pool,
            methods=methods,
            metadata_prefix=metadata_prefix,
            metadata_remaining=metadata_remaining,
            scan_start=scan_start,
            scan_end=scan_end,
            anchor_offset=metadata_failure_pos,
            method_shift=0,
            limit=candidate_limit,
        )
        if candidates:
            return candidates

        # Generic fallback: restart metadata parsing from table start when the
        # previously parsed metadata prefix is likely misaligned.
        restart_scan_start = metadata_table_start
        restart_scan_end = min(len(self.data), restart_scan_start + 6144)
        self._scan_recovery_window(
            candidates=candidates,
            constant_pool=constant_pool,
            methods=methods,
            metadata_prefix=[],
            metadata_remaining=metadata_count,
            scan_start=restart_scan_start,
            scan_end=restart_scan_end,
            anchor_offset=metadata_table_start,
            method_shift=0,
            limit=candidate_limit,
        )
        if candidates:
            return candidates

        # Secondary pass: method-boundary relocation before metadata parsing.
        # Keep stride coarse to improve throughput while retaining broad coverage.
        saved_pos = self.pos
        try:
            for delta in range(-1024, 1025, 2):
                shifted_methods_end = methods_end_pos + delta
                if shifted_methods_end < 0 or shifted_methods_end >= len(self.data):
                    continue

                self.pos = shifted_methods_end
                try:
                    shifted_metadata_count = self.read_u30()
                except (InvalidABCCodeError, BufferError, ValueError, IndexError):
                    continue

                if shifted_metadata_count > 256:
                    continue

                shifted_metadata_start = self.pos
                shifted_scan_start = shifted_metadata_start
                shifted_scan_end = min(len(self.data), shifted_scan_start + 64)

                self._scan_recovery_window(
                    candidates=candidates,
                    constant_pool=constant_pool,
                    methods=methods,
                    metadata_prefix=[],
                    metadata_remaining=shifted_metadata_count,
                    scan_start=shifted_scan_start,
                    scan_end=shifted_scan_end,
                    anchor_offset=shifted_metadata_start,
                    method_shift=delta,
                    limit=candidate_limit,
                )
        finally:
            self.pos = saved_pos

        candidates.sort(key=self._recovery_candidate_sort_key)
        return candidates

    def _validate_method_body_branch_targets(self, body: MethodBody) -> None:
        instructions = body.instructions
        if not instructions:
            return

        instruction_offsets = {inst.offset for inst in instructions}
        next_offsets = {
            inst.offset: (
                instructions[idx + 1].offset if idx + 1 < len(instructions) else None
            )
            for idx, inst in enumerate(instructions)
        }

        for instruction in instructions:
            self._instruction_successor_offsets(
                instruction=instruction,
                next_offset=next_offsets[instruction.offset],
                instruction_offsets=instruction_offsets,
                code_length=len(body.code),
            )

    def _validate_method_body_scope(self, method_index: int, body: MethodBody) -> None:
        instructions = body.instructions
        if not instructions:
            return

        offset_to_instruction = {inst.offset: inst for inst in instructions}
        instruction_offsets = set(offset_to_instruction)
        next_offsets = {
            inst.offset: (
                instructions[idx + 1].offset if idx + 1 < len(instructions) else None
            )
            for idx, inst in enumerate(instructions)
        }

        entry_offset = instructions[0].offset
        scope_depth_by_offset: dict[int, int] = {}
        worklist: deque[int] = deque()

        self._merge_scope_depth(
            scope_depth_by_offset=scope_depth_by_offset,
            worklist=worklist,
            method_index=method_index,
            offset=entry_offset,
            incoming_depth=body.init_scope_depth,
        )

        # Exception handler activation may unwind local scope stack state.
        for exc in body.exceptions:
            if exc.target_offset not in instruction_offsets:
                raise InvalidABCCodeError(
                    f"Invalid exception target offset: {exc.target_offset}"
                )
            self._merge_scope_depth(
                scope_depth_by_offset=scope_depth_by_offset,
                worklist=worklist,
                method_index=method_index,
                offset=exc.target_offset,
                incoming_depth=body.init_scope_depth,
            )

        while worklist:
            offset = worklist.popleft()
            scope_in = scope_depth_by_offset[offset]
            instruction = offset_to_instruction[offset]

            self._validate_instruction_scope_operand_indices(
                method_index=method_index,
                instruction=instruction,
                scope_depth=scope_in,
            )

            scope_pops, scope_pushes = self._scope_effect_for_instruction(instruction)
            effective_scope_pops = scope_pops
            if scope_in - scope_pops < body.init_scope_depth:
                if self._verify_relaxed:
                    effective_scope_pops = max(0, scope_in - body.init_scope_depth)
                else:
                    raise InvalidABCCodeError(
                        "scope stack underflow: "
                        f"method={method_index}, offset={instruction.offset}, opcode={instruction.opcode.name}, "
                        f"current={scope_in}, init_scope_depth={body.init_scope_depth}"
                    )

            scope_out = scope_in - effective_scope_pops + scope_pushes
            if scope_out > body.max_scope_depth:
                if not self._verify_relaxed:
                    raise InvalidABCCodeError(
                        "max_scope_depth exceeded: "
                        f"method={method_index}, offset={instruction.offset}, "
                        f"depth={scope_out}, max_scope_depth={body.max_scope_depth}"
                    )

            successors = self._instruction_successor_offsets(
                instruction=instruction,
                next_offset=next_offsets[instruction.offset],
                instruction_offsets=instruction_offsets,
                code_length=len(body.code),
            )
            for successor, _edge_kind in successors:
                if successor not in instruction_offsets:
                    continue
                self._merge_scope_depth(
                    scope_depth_by_offset=scope_depth_by_offset,
                    worklist=worklist,
                    method_index=method_index,
                    offset=successor,
                    incoming_depth=scope_out,
                )

    def _merge_scope_depth(
        self,
        *,
        scope_depth_by_offset: dict[int, int],
        worklist: deque[int],
        method_index: int,
        offset: int,
        incoming_depth: int,
    ) -> None:
        existing_depth = scope_depth_by_offset.get(offset)
        if existing_depth is None:
            scope_depth_by_offset[offset] = incoming_depth
            worklist.append(offset)
            return

        if existing_depth == incoming_depth:
            return

        if self._relax_join_depth:
            merged_depth = min(existing_depth, incoming_depth)
            if merged_depth != existing_depth:
                scope_depth_by_offset[offset] = merged_depth
                worklist.append(offset)
            return

        raise InvalidABCCodeError(
            "scope depth mismatch: "
            f"method={method_index}, join_offset={offset}, "
            f"existing={existing_depth}, incoming={incoming_depth}"
        )

    @staticmethod
    def _scope_effect_for_instruction(instruction: Instruction) -> tuple[int, int]:
        opcode = instruction.opcode
        if opcode in ABCReader._SCOPE_EFFECT_PUSH_OPCODES:
            return 0, 1
        if opcode == Opcode.PopScope:
            return 1, 0
        return 0, 0

    def _validate_instruction_scope_operand_indices(
        self,
        *,
        method_index: int,
        instruction: Instruction,
        scope_depth: int,
    ) -> None:
        scope_indices = self._scope_indices_for_instruction(instruction)
        if not scope_indices:
            return

        for scope_index in scope_indices:
            if scope_index < 0 or scope_index >= scope_depth:
                if not self._verify_relaxed:
                    raise InvalidABCCodeError(
                        "scope object index out of range: "
                        f"method={method_index}, offset={instruction.offset}, opcode={instruction.opcode.name}, "
                        f"index={scope_index}, scope_depth={scope_depth}"
                    )

    @staticmethod
    def _scope_indices_for_instruction(instruction: Instruction) -> tuple[int, ...]:
        if instruction.opcode == Opcode.GetScopeObject and instruction.operands:
            scope_index = instruction.operands[0]
            if isinstance(scope_index, int):
                return (scope_index,)
        return ()

    def _validate_instruction_local_register_indices(
        self,
        *,
        method_index: int,
        body: MethodBody,
        instruction: Instruction,
    ) -> None:
        local_indices = self._local_indices_for_instruction(instruction)
        if not local_indices:
            return

        for local_index in local_indices:
            if local_index < 0 or local_index >= body.num_locals:
                if not self._verify_relaxed:
                    raise InvalidABCCodeError(
                        "local register index out of range: "
                        f"method={method_index}, offset={instruction.offset}, opcode={instruction.opcode.name}, "
                        f"index={local_index}, num_locals={body.num_locals}"
                    )

    @staticmethod
    def _local_indices_for_instruction(instruction: Instruction) -> tuple[int, ...]:
        opcode = instruction.opcode

        fixed_index = ABCReader._LOCAL_FIXED_INDICES.get(opcode)
        if fixed_index is not None:
            return (fixed_index,)

        if opcode in ABCReader._LOCAL_OPERAND_INDEX_OPCODES:
            if instruction.operands and isinstance(instruction.operands[0], int):
                return (instruction.operands[0],)
            return ()

        if opcode == Opcode.HasNext2:
            if len(instruction.operands) >= 2:
                first = instruction.operands[0]
                second = instruction.operands[1]
                if isinstance(first, int) and isinstance(second, int):
                    return (first, second)
            return ()

        return ()

    def _merge_stack_state(
        self,
        stack_state_by_offset: dict[int, tuple[str, ...]],
        worklist: deque[int],
        method_index: int,
        offset: int,
        incoming_state: tuple[str, ...],
        edge_kind: str,
        queued_offsets: Optional[set[int]] = None,
    ) -> None:
        worklist_append = worklist.append
        existing_state = stack_state_by_offset.get(offset)
        if existing_state is None:
            stack_state_by_offset[offset] = incoming_state
            if queued_offsets is None:
                worklist_append(offset)
            elif offset not in queued_offsets:
                queued_offsets.add(offset)
                worklist_append(offset)
            return
        if existing_state == incoming_state:
            return

        if len(existing_state) != len(incoming_state):
            if self._relax_join_depth:
                existing_state, incoming_state = self._normalize_relaxed_join_states(
                    existing_state=existing_state,
                    incoming_state=incoming_state,
                    edge_kind=edge_kind,
                )
            else:
                raise InvalidABCCodeError(
                    "stack depth mismatch: "
                    f"method={method_index}, join_offset={offset}, "
                    f"existing={len(existing_state)}, incoming={len(incoming_state)}"
                )
            if existing_state == incoming_state:
                return

        merged_slots: Optional[list[str]] = None
        merge_lattice_slot_type = self._merge_lattice_slot_type
        state_length = len(existing_state)
        for slot in range(state_length):
            existing_type = existing_state[slot]
            incoming_type = incoming_state[slot]
            if existing_type == incoming_type:
                continue
            merged_type = merge_lattice_slot_type(existing_type, incoming_type)
            if merged_type is None:
                raise InvalidABCCodeError(
                    (
                        "stack type mismatch: "
                        f"method={method_index}, join_offset={offset}, slot={slot}, "
                        f"existing={existing_type}, incoming={incoming_type}"
                    )
                )
            if merged_type != existing_type:
                if merged_slots is None:
                    merged_slots = list(existing_state)
                merged_slots[slot] = merged_type

        if merged_slots is not None:
            stack_state_by_offset[offset] = tuple(merged_slots)
            if queued_offsets is None:
                worklist_append(offset)
            elif offset not in queued_offsets:
                queued_offsets.add(offset)
                worklist_append(offset)

    def _merge_local_state(
        self,
        local_state_by_offset: dict[int, tuple[str, ...]],
        worklist: deque[int],
        method_index: int,
        offset: int,
        incoming_state: tuple[str, ...],
        queued_offsets: Optional[set[int]] = None,
    ) -> None:
        worklist_append = worklist.append
        existing_state = local_state_by_offset.get(offset)
        if existing_state is None:
            local_state_by_offset[offset] = incoming_state
            if queued_offsets is None:
                worklist_append(offset)
            elif offset not in queued_offsets:
                queued_offsets.add(offset)
                worklist_append(offset)
            return
        if existing_state == incoming_state:
            return

        if len(existing_state) != len(incoming_state):
            raise InvalidABCCodeError(
                "local state length mismatch: "
                f"method={method_index}, join_offset={offset}, "
                f"existing={len(existing_state)}, incoming={len(incoming_state)}"
            )

        merged_slots: Optional[list[str]] = None
        merge_lattice_slot_type = self._merge_lattice_slot_type
        state_length = len(existing_state)
        for local_index in range(state_length):
            existing_type = existing_state[local_index]
            incoming_type = incoming_state[local_index]
            if existing_type == incoming_type:
                continue
            merged_type = merge_lattice_slot_type(existing_type, incoming_type)
            if merged_type is None:
                raise InvalidABCCodeError(
                    (
                        "local type mismatch: "
                        f"method={method_index}, join_offset={offset}, local={local_index}, "
                        f"existing={existing_type}, incoming={incoming_type}"
                    )
                )
            if merged_type != existing_type:
                if merged_slots is None:
                    merged_slots = list(existing_state)
                merged_slots[local_index] = merged_type

        if merged_slots is not None:
            local_state_by_offset[offset] = tuple(merged_slots)
            if queued_offsets is None:
                worklist_append(offset)
            elif offset not in queued_offsets:
                queued_offsets.add(offset)
                worklist_append(offset)

    def _merge_local_slot_type(
        self,
        method_index: int,
        offset: int,
        local_index: int,
        existing_type: str,
        incoming_type: str,
    ) -> str:
        merged_type = self._merge_lattice_slot_type(existing_type, incoming_type)
        if merged_type is not None:
            return merged_type
        raise InvalidABCCodeError(
            (
                "local type mismatch: "
                f"method={method_index}, join_offset={offset}, local={local_index}, "
                f"existing={existing_type}, incoming={incoming_type}"
            )
        )

    def _merge_scope_state(
        self,
        scope_state_by_offset: dict[int, tuple[str, ...]],
        worklist: deque[int],
        method_index: int,
        offset: int,
        incoming_state: tuple[str, ...],
        edge_kind: str,
        queued_offsets: Optional[set[int]] = None,
    ) -> None:
        worklist_append = worklist.append
        existing_state = scope_state_by_offset.get(offset)
        if existing_state is None:
            scope_state_by_offset[offset] = incoming_state
            if queued_offsets is None:
                worklist_append(offset)
            elif offset not in queued_offsets:
                queued_offsets.add(offset)
                worklist_append(offset)
            return
        if existing_state == incoming_state:
            return

        if len(existing_state) != len(incoming_state):
            if self._relax_join_depth:
                target_depth = min(len(existing_state), len(incoming_state))
                existing_state = existing_state[:target_depth]
                incoming_state = incoming_state[:target_depth]
            else:
                raise InvalidABCCodeError(
                    "scope depth mismatch: "
                    f"method={method_index}, join_offset={offset}, "
                    f"existing={len(existing_state)}, incoming={len(incoming_state)}"
                )
            if existing_state == incoming_state:
                return

        merged_slots: Optional[list[str]] = None
        merge_lattice_slot_type = self._merge_lattice_slot_type
        state_length = len(existing_state)
        for slot in range(state_length):
            existing_type = existing_state[slot]
            incoming_type = incoming_state[slot]
            if existing_type == incoming_type:
                continue
            merged_type = merge_lattice_slot_type(existing_type, incoming_type)
            if merged_type is None:
                raise InvalidABCCodeError(
                    (
                        "scope type mismatch: "
                        f"method={method_index}, join_offset={offset}, slot={slot}, "
                        f"existing={existing_type}, incoming={incoming_type}"
                    )
                )
            if merged_type != existing_type:
                if merged_slots is None:
                    merged_slots = list(existing_state)
                merged_slots[slot] = merged_type

        if merged_slots is not None:
            scope_state_by_offset[offset] = tuple(merged_slots)
            if queued_offsets is None:
                worklist_append(offset)
            elif offset not in queued_offsets:
                queued_offsets.add(offset)
                worklist_append(offset)

    def _merge_scope_slot_type(
        self,
        method_index: int,
        offset: int,
        slot: int,
        existing_type: str,
        incoming_type: str,
        edge_kind: str,
    ) -> str:
        merged_type = self._merge_lattice_slot_type(existing_type, incoming_type)
        if merged_type is not None:
            return merged_type
        raise InvalidABCCodeError(
            (
                "scope type mismatch: "
                f"method={method_index}, join_offset={offset}, slot={slot}, "
                f"existing={existing_type}, incoming={incoming_type}"
            )
        )

    def _scope_state_after_instruction(
        self,
        *,
        method_index: int,
        body: MethodBody,
        instruction: Instruction,
        stack_in: tuple[str, ...],
        scope_state: tuple[str, ...],
    ) -> tuple[str, ...]:
        opcode = instruction.opcode
        if opcode in (Opcode.PushScope, Opcode.PushWith):
            if len(scope_state) + 1 > body.max_scope_depth and not self._verify_relaxed:
                raise InvalidABCCodeError(
                    "max_scope_depth exceeded: "
                    f"method={method_index}, offset={instruction.offset}, "
                    f"depth={len(scope_state) + 1}, max_scope_depth={body.max_scope_depth}"
                )
            scope_value_type = stack_in[-1] if stack_in else self._STACK_TYPE_ANY
            return scope_state + (scope_value_type,)
        if opcode == Opcode.PopScope:
            if len(scope_state) <= body.init_scope_depth:
                raise InvalidABCCodeError(
                    "scope stack underflow: "
                    f"method={method_index}, offset={instruction.offset}, opcode={instruction.opcode.name}, "
                    f"current={len(scope_state)}, init_scope_depth={body.init_scope_depth}"
                )
            return scope_state[:-1]
        return scope_state

    def _normalize_relaxed_join_states(
        self,
        *,
        existing_state: tuple[str, ...],
        incoming_state: tuple[str, ...],
        edge_kind: str,
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        if edge_kind == self._EDGE_KIND_LOOKUPSWITCH:
            return self._relaxed_stack_intersection(existing_state, incoming_state)

        if (
            edge_kind == self._EDGE_KIND_EXCEPTION_ENTRY
            or existing_state == self._EXCEPTION_HANDLER_ENTRY_STACK_STATE
            or incoming_state == self._EXCEPTION_HANDLER_ENTRY_STACK_STATE
        ):
            return self._relaxed_exception_join(existing_state, incoming_state)

        # Relaxed fallback for obfuscated control flow: if either side is empty,
        # keep only the common guaranteed prefix depth.
        if not existing_state or not incoming_state:
            return self._relaxed_stack_intersection(existing_state, incoming_state)

        raise InvalidABCCodeError(
            "stack depth mismatch: "
            f"join edge={edge_kind}, existing={len(existing_state)}, incoming={len(incoming_state)}"
        )

    @staticmethod
    def _relaxed_stack_intersection(
        existing_state: tuple[str, ...],
        incoming_state: tuple[str, ...],
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        shared_depth = min(len(existing_state), len(incoming_state))
        return existing_state[:shared_depth], incoming_state[:shared_depth]

    def _relaxed_exception_join(
        self,
        existing_state: tuple[str, ...],
        incoming_state: tuple[str, ...],
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        target_depth = max(len(existing_state), len(incoming_state))
        existing_pad = (self._STACK_TYPE_ANY,) * (target_depth - len(existing_state))
        incoming_pad = (self._STACK_TYPE_ANY,) * (target_depth - len(incoming_state))
        return existing_state + existing_pad, incoming_state + incoming_pad

    def _merge_stack_slot_type(
        self,
        method_index: int,
        offset: int,
        slot: int,
        existing_type: str,
        incoming_type: str,
        edge_kind: str,
    ) -> str:
        merged_type = self._merge_lattice_slot_type(existing_type, incoming_type)
        if merged_type is not None:
            return merged_type
        raise InvalidABCCodeError(
            (
                "stack type mismatch: "
                f"method={method_index}, join_offset={offset}, slot={slot}, "
                f"existing={existing_type}, incoming={incoming_type}"
            )
        )

    def _merge_lattice_slot_type(
        self,
        existing_type: str,
        incoming_type: str,
    ) -> Optional[str]:
        if existing_type == incoming_type:
            return existing_type
        if self._prefer_precise_any_join:
            if (
                existing_type == self._STACK_TYPE_ANY
                and incoming_type != self._STACK_TYPE_ANY
            ):
                return incoming_type
            if (
                incoming_type == self._STACK_TYPE_ANY
                and existing_type != self._STACK_TYPE_ANY
            ):
                return existing_type
        if (
            existing_type == self._STACK_TYPE_ANY
            or incoming_type == self._STACK_TYPE_ANY
        ):
            return self._STACK_TYPE_ANY
        if self._relax_join_types:
            return self._STACK_TYPE_ANY
        return None

    def _stack_state_after_instruction(
        self,
        *,
        instruction: Instruction,
        stack_in: tuple[str, ...],
        pops: int,
        pushes: int,
        local_state: Optional[tuple[str, ...]] = None,
        scope_state: Optional[tuple[str, ...]] = None,
        local_indices: Optional[tuple[int, ...]] = None,
    ) -> tuple[str, ...]:
        opcode = instruction.opcode
        base = stack_in[:-pops] if pops else stack_in

        # Keep common stack-shuffling opcodes precise to avoid false type mismatches.
        if opcode == Opcode.Dup and stack_in:
            top = stack_in[-1]
            return stack_in + (top,)
        if opcode == Opcode.Swap and len(stack_in) >= 2:
            return stack_in[:-2] + (stack_in[-1], stack_in[-2])

        if pushes == 0:
            # Zero-push coverage marker:
            # Opcode.IfEq Opcode.IfFalse Opcode.IfGe Opcode.IfGt Opcode.IfLe Opcode.IfLt
            # Opcode.IfNe Opcode.IfNge Opcode.IfNgt Opcode.IfNle Opcode.IfNlt
            # Opcode.IfStrictEq Opcode.IfStrictNe Opcode.IfTrue Opcode.Jump Opcode.LookupSwitch
            # Opcode.Label Opcode.Nop Opcode.Pop Opcode.SetProperty Opcode.InitProperty
            # Opcode.SetSuper Opcode.SetSlot Opcode.SetGlobalSlot Opcode.SetLocal
            # Opcode.SetLocal0 Opcode.SetLocal1 Opcode.SetLocal2 Opcode.SetLocal3
            # Opcode.Kill Opcode.IncLocal Opcode.IncLocalI Opcode.DecLocal Opcode.DecLocalI
            # Opcode.CallPropVoid Opcode.CallSuperVoid Opcode.ConstructSuper Opcode.Dxns
            # Opcode.DxnsLate Opcode.PushScope Opcode.PushWith Opcode.PopScope Opcode.Debug
            # Opcode.DebugFile Opcode.DebugLine Opcode.ReturnValue Opcode.ReturnVoid Opcode.Throw
            # Opcode.Si8 Opcode.Si16 Opcode.Si32 Opcode.Sf32 Opcode.Sf64 Opcode.Bkpt Opcode.BkptLine
            return base

        # Type-merge coverage marker:
        # Opcode.AddI Opcode.Subtract Opcode.SubtractI Opcode.Multiply Opcode.MultiplyI Opcode.Divide Opcode.Modulo
        # Opcode.BitAnd Opcode.BitOr Opcode.BitXor Opcode.LShift Opcode.RShift Opcode.URShift
        # Opcode.Increment Opcode.IncrementI Opcode.Decrement Opcode.DecrementI Opcode.Negate Opcode.NegateI
        # Opcode.BitNot Opcode.ConvertD Opcode.ConvertI Opcode.ConvertU Opcode.CoerceD Opcode.CoerceI Opcode.CoerceU
        # Opcode.Sxi1 Opcode.Sxi8 Opcode.Sxi16 Opcode.Li8 Opcode.Li16 Opcode.Li32 Opcode.Lf32 Opcode.Lf64 Opcode.Timestamp
        # Opcode.Equals Opcode.StrictEquals Opcode.LessThan Opcode.LessEquals Opcode.GreaterThan Opcode.GreaterEquals
        # Opcode.In Opcode.InstanceOf Opcode.IsType Opcode.IsTypeLate Opcode.Not Opcode.ConvertB Opcode.CoerceB
        # Opcode.HasNext Opcode.HasNext2 Opcode.DeleteProperty
        # Opcode.ConvertS Opcode.CoerceS Opcode.TypeOf Opcode.NewObject Opcode.NewActivation Opcode.NewClass Opcode.NewCatch
        # Opcode.Construct Opcode.ConstructProp Opcode.ApplyType Opcode.ConvertO Opcode.CoerceO Opcode.GetGlobalScope
        # Opcode.GetOuterScope Opcode.NewArray Opcode.NewFunction Opcode.PushByte Opcode.PushShort Opcode.PushInt
        # Opcode.PushUint Opcode.PushDouble Opcode.PushNaN Opcode.PushTrue Opcode.PushFalse Opcode.PushNull
        # Opcode.PushUndefined Opcode.PushString
        if opcode in self._STACK_STATE_COERCE_RESULT_OPCODES:
            return base + (self._coerce_result_type(instruction),)

        if opcode == Opcode.Add:
            if len(stack_in) >= 2:
                left = stack_in[-2]
                right = stack_in[-1]
                # Conservative split: string concat if either side is definitely string;
                # numeric add only when both sides are definitely numeric.
                if left == self._STACK_TYPE_STRING or right == self._STACK_TYPE_STRING:
                    return base + (self._STACK_TYPE_STRING,)
                if left == self._STACK_TYPE_NUMBER and right == self._STACK_TYPE_NUMBER:
                    return base + (self._STACK_TYPE_NUMBER,)
            return base + (self._STACK_TYPE_ANY,)

        if opcode == Opcode.PushNamespace:
            if self._precision_enhanced:
                return base + (self._STACK_TYPE_OBJECT,)
            return base + (self._STACK_TYPE_ANY,)

        if opcode in self._STACK_STATE_FIND_PROPERTY_OBJECT_OPCODES:
            if self._precision_enhanced:
                return base + (self._STACK_TYPE_OBJECT,)
            return base + (self._STACK_TYPE_ANY,)

        if opcode in self._STACK_STATE_ANY_RESULT_OPCODES:
            return base + (self._STACK_TYPE_ANY,)

        if opcode == Opcode.NextName:
            if self._precision_enhanced:
                return base + (self._STACK_TYPE_STRING,)
            return base + (self._STACK_TYPE_ANY,)

        if opcode in self._STACK_STATE_OBJECT_RESULT_OPCODES:
            if self._precision_enhanced:
                return base + (self._STACK_TYPE_OBJECT,)
            return base + (self._STACK_TYPE_ANY,)

        if opcode in self._STACK_STATE_STRING_RESULT_OPCODES:
            if self._precision_enhanced:
                return base + (self._STACK_TYPE_STRING,)
            return base + (self._STACK_TYPE_ANY,)

        if opcode in self._STACK_STATE_GETLOCAL_OPCODES:
            local_type = self._STACK_TYPE_ANY
            indices = local_indices
            if indices is None:
                indices = self._local_indices_for_instruction(instruction)
            if local_state is not None and indices:
                local_index = indices[0]
                if 0 <= local_index < len(local_state):
                    local_type = local_state[local_index]
            return base + (local_type,)

        if opcode == Opcode.GetScopeObject:
            scope_type = self._STACK_TYPE_OBJECT
            if (
                scope_state is not None
                and instruction.operands
                and isinstance(instruction.operands[0], int)
            ):
                scope_index = instruction.operands[0]
                if 0 <= scope_index < len(scope_state):
                    scope_type = scope_state[scope_index]
            return base + (scope_type,)

        if opcode in self._STACK_STATE_CALL_PROPERTY_OPCODES:
            return base + (self._call_property_result_type(instruction, stack_in),)
        if opcode == Opcode.CallMethod:
            return base + (self._call_method_result_type(instruction),)
        if opcode == Opcode.CallStatic:
            return base + (self._call_static_result_type(instruction),)
        if opcode == Opcode.GetProperty:
            return base + (self._get_property_result_type(instruction, stack_in),)
        if opcode == Opcode.GetSuper:
            if self._precision_enhanced:
                return base + (self._get_property_result_type(instruction, stack_in),)
            return base + (self._STACK_TYPE_ANY,)

        push_type = self._default_push_type_for_instruction(opcode)
        return base + ((push_type,) * pushes)

    def _coerce_result_type(self, instruction: Instruction) -> str:
        if not self._precision_enhanced:
            return self._STACK_TYPE_ANY
        if not instruction.operands:
            return self._STACK_TYPE_ANY
        target = instruction.operands[0]
        if target is None:
            return self._STACK_TYPE_ANY
        return self._declared_type_to_stack_type(target)

    def _call_property_result_type(
        self, instruction: Instruction, stack_in: tuple[str, ...]
    ) -> str:
        if self._multiname_runtime_arity(instruction) > 0:
            return self._STACK_TYPE_ANY
        call_name = self._instruction_multiname_short_name(instruction)
        if call_name is None:
            return self._STACK_TYPE_ANY
        arg_count = 0
        if len(instruction.operands) > 1 and isinstance(instruction.operands[1], int):
            arg_count = instruction.operands[1]
        receiver_type = self._call_receiver_type(
            instruction=instruction,
            stack_in=stack_in,
            arg_count=arg_count,
        )
        if receiver_type in self._OBJECT_LIKE_RECEIVER_TYPES:
            if arg_count in self._OBJECT_BOOL_METHOD_ARITIES.get(call_name, set()):
                return self._STACK_TYPE_BOOLEAN
            if arg_count in self._OBJECT_STRING_METHOD_ARITIES.get(call_name, set()):
                return self._STACK_TYPE_STRING
        if receiver_type == self._STACK_TYPE_STRING:
            if arg_count in self._STRING_NUMBER_METHOD_ARITIES.get(call_name, set()):
                return self._STACK_TYPE_NUMBER
            if arg_count in self._STRING_STRING_METHOD_ARITIES.get(call_name, set()):
                return self._STACK_TYPE_STRING
        if receiver_type == self._STACK_TYPE_ARRAY:
            if arg_count in self._ARRAY_NUMBER_METHOD_ARITIES.get(call_name, set()):
                return self._STACK_TYPE_NUMBER
            if arg_count in self._ARRAY_STRING_METHOD_ARITIES.get(call_name, set()):
                return self._STACK_TYPE_STRING
        return self._STACK_TYPE_ANY

    def _call_method_result_type(self, instruction: Instruction) -> str:
        if not instruction.operands:
            return self._STACK_TYPE_ANY
        method_index = instruction.operands[0]
        if not isinstance(method_index, int):
            return self._STACK_TYPE_ANY
        return self._method_declared_result_type(method_index)

    def _call_static_result_type(self, instruction: Instruction) -> str:
        if not instruction.operands:
            return self._STACK_TYPE_ANY
        method_index = instruction.operands[0]
        if not isinstance(method_index, int):
            return self._STACK_TYPE_ANY
        return self._method_declared_result_type(method_index)

    def _get_property_result_type(
        self, instruction: Instruction, stack_in: tuple[str, ...]
    ) -> str:
        if self._multiname_runtime_arity(instruction) > 0:
            return self._STACK_TYPE_ANY
        property_name = self._instruction_multiname_short_name(instruction)
        if property_name is None:
            return self._STACK_TYPE_ANY
        receiver_type = self._property_receiver_type(
            instruction=instruction, stack_in=stack_in
        )
        if property_name == "length" and receiver_type in {
            self._STACK_TYPE_STRING,
            self._STACK_TYPE_ARRAY,
        }:
            return self._STACK_TYPE_NUMBER
        if (
            receiver_type in self._OBJECT_LIKE_RECEIVER_TYPES
            and property_name in self._OBJECT_METHOD_NAMES
        ):
            return self._STACK_TYPE_FUNCTION
        if (
            receiver_type == self._STACK_TYPE_STRING
            and property_name in self._STRING_METHOD_NAMES
        ):
            return self._STACK_TYPE_FUNCTION
        if (
            receiver_type == self._STACK_TYPE_ARRAY
            and property_name in self._ARRAY_METHOD_NAMES
        ):
            return self._STACK_TYPE_FUNCTION
        return self._STACK_TYPE_ANY

    def _property_receiver_type(
        self,
        *,
        instruction: Instruction,
        stack_in: tuple[str, ...],
    ) -> str:
        runtime_arity = self._multiname_runtime_arity(instruction)
        if runtime_arity > 0:
            return self._STACK_TYPE_ANY
        receiver_index = len(stack_in) - 1
        if receiver_index < 0 or receiver_index >= len(stack_in):
            return self._STACK_TYPE_ANY
        return stack_in[receiver_index]

    def _call_receiver_type(
        self,
        *,
        instruction: Instruction,
        stack_in: tuple[str, ...],
        arg_count: int,
    ) -> str:
        if arg_count < 0:
            return self._STACK_TYPE_ANY
        runtime_arity = self._multiname_runtime_arity(instruction)
        if runtime_arity > 0:
            return self._STACK_TYPE_ANY
        receiver_index = len(stack_in) - (arg_count + 1)
        if receiver_index < 0 or receiver_index >= len(stack_in):
            return self._STACK_TYPE_ANY
        return stack_in[receiver_index]

    @staticmethod
    def _instruction_multiname_short_name(instruction: Instruction) -> Optional[str]:
        if not instruction.operands:
            return None
        raw_name = instruction.operands[0]
        if raw_name is None:
            return None
        text = str(raw_name)
        if not text or text == "*" or text.startswith("#"):
            return None
        if "::" in text:
            text = text.rsplit("::", 1)[-1]
        return text if text and text != "*" else None

    def _method_declared_result_type(self, method_index: int) -> str:
        if method_index < 0 or method_index >= len(self._method_infos_for_verifier):
            return self._STACK_TYPE_ANY
        return self._declared_type_to_stack_type(
            self._method_infos_for_verifier[method_index].return_type
        )

    def _declared_type_to_stack_type(self, declared_type: Any) -> str:
        if declared_type is None:
            return self._STACK_TYPE_ANY
        text = str(declared_type).strip()
        if not text or text == "*" or text.startswith("#"):
            return self._STACK_TYPE_ANY
        if "::" in text:
            text = text.rsplit("::", 1)[-1]
        short = text.strip().lower()
        if not short or short == "*":
            return self._STACK_TYPE_ANY
        if short.startswith("vector.<"):
            return self._STACK_TYPE_ARRAY
        if short in {"int", "uint", "number", "float", "double", "decimal"}:
            return self._STACK_TYPE_NUMBER
        if short in {"bool", "boolean"}:
            return self._STACK_TYPE_BOOLEAN
        if short in {"str", "string"}:
            return self._STACK_TYPE_STRING
        if short in {"array"}:
            return self._STACK_TYPE_ARRAY
        if short in {"function"}:
            return self._STACK_TYPE_FUNCTION
        if short in {"null"}:
            return self._STACK_TYPE_NULL
        if short in {"void", "undefined"}:
            return self._STACK_TYPE_UNDEFINED
        return self._STACK_TYPE_OBJECT

    def _local_state_after_instruction(
        self,
        *,
        instruction: Instruction,
        stack_in: tuple[str, ...],
        local_state: tuple[str, ...],
        local_indices: Optional[tuple[int, ...]] = None,
    ) -> tuple[str, ...]:
        next_local_state: Optional[list[str]] = None
        opcode = instruction.opcode
        if not local_state:
            return local_state

        # setlocal* consumes stack top and stores type into the target local.
        if opcode in (
            Opcode.SetLocal,
            Opcode.SetLocal0,
            Opcode.SetLocal1,
            Opcode.SetLocal2,
            Opcode.SetLocal3,
        ):
            indices = local_indices
            if indices is None:
                indices = self._local_indices_for_instruction(instruction)
            if indices:
                local_index = indices[0]
                if 0 <= local_index < len(local_state):
                    local_type = stack_in[-1] if stack_in else self._STACK_TYPE_ANY
                    if local_state[local_index] != local_type:
                        next_local_state = list(local_state)
                        next_local_state[local_index] = local_type
                        return tuple(next_local_state)
            return local_state

        # kill clears a local register slot.
        if opcode == Opcode.Kill:
            indices = local_indices
            if indices is None:
                indices = self._local_indices_for_instruction(instruction)
            if indices:
                local_index = indices[0]
                if 0 <= local_index < len(local_state):
                    if local_state[local_index] != self._STACK_TYPE_ANY:
                        next_local_state = list(local_state)
                        next_local_state[local_index] = self._STACK_TYPE_ANY
                        return tuple(next_local_state)
            return local_state

        # inc/dec local forms produce numeric local state.
        if opcode in (
            Opcode.IncLocal,
            Opcode.IncLocalI,
            Opcode.DecLocal,
            Opcode.DecLocalI,
        ):
            indices = local_indices
            if indices is None:
                indices = self._local_indices_for_instruction(instruction)
            if indices:
                local_index = indices[0]
                if 0 <= local_index < len(local_state):
                    if local_state[local_index] != self._STACK_TYPE_NUMBER:
                        next_local_state = list(local_state)
                        next_local_state[local_index] = self._STACK_TYPE_NUMBER
                        return tuple(next_local_state)
            return local_state

        # hasnext2 updates object/index register pair as iteration state.
        if opcode == Opcode.HasNext2:
            indices = local_indices
            if indices is None:
                indices = self._local_indices_for_instruction(instruction)
            next_local_state = None
            if len(indices) >= 2:
                object_local = indices[0]
                index_local = indices[1]
                if (
                    0 <= object_local < len(local_state)
                    and local_state[object_local] != self._STACK_TYPE_OBJECT
                ):
                    if next_local_state is None:
                        next_local_state = list(local_state)
                    next_local_state[object_local] = self._STACK_TYPE_OBJECT
                if (
                    0 <= index_local < len(local_state)
                    and local_state[index_local] != self._STACK_TYPE_NUMBER
                ):
                    if next_local_state is None:
                        next_local_state = list(local_state)
                    next_local_state[index_local] = self._STACK_TYPE_NUMBER
            if next_local_state is not None:
                return tuple(next_local_state)
            return local_state

        return local_state

    def _default_push_type_for_instruction(self, opcode: Opcode) -> str:
        return self._DEFAULT_PUSH_TYPE_OVERRIDES.get(opcode, self._STACK_TYPE_ANY)

    def _instruction_successor_offsets(
        self,
        *,
        instruction: Instruction,
        next_offset: Optional[int],
        instruction_offsets: set[int],
        code_length: int,
    ) -> List[tuple[int, EdgeKind]]:
        targets: List[tuple[int, EdgeKind]] = []
        opcode = instruction.opcode

        if opcode in self._TERMINATOR_OPCODES:
            return []

        if opcode == Opcode.Jump:
            if not instruction.operands:
                raise InvalidABCCodeError(
                    f"Malformed Jump operands at offset {instruction.offset}"
                )
            target = self._resolve_branch_target_offset(
                instruction=instruction,
                relative_offset=instruction.operands[0],
                next_offset=next_offset,
                instruction_offsets=instruction_offsets,
                code_length=code_length,
                allow_relaxed=self._verify_relaxed and not self._strict_lookupswitch,
            )
            if target in instruction_offsets:
                return [(target, self._EDGE_KIND_NORMAL)]
            return []

        if opcode in self._CONDITIONAL_BRANCH_OPCODES:
            if not instruction.operands:
                raise InvalidABCCodeError(
                    f"Malformed conditional-branch operands at offset {instruction.offset}"
                )
            targets = []
            if next_offset is not None:
                targets.append((next_offset, self._EDGE_KIND_NORMAL))
            target = self._resolve_branch_target_offset(
                instruction=instruction,
                relative_offset=instruction.operands[0],
                next_offset=next_offset,
                instruction_offsets=instruction_offsets,
                code_length=code_length,
                allow_relaxed=self._verify_relaxed,
            )
            if target in instruction_offsets:
                targets.append((target, self._EDGE_KIND_NORMAL))
            return targets

        if opcode == Opcode.LookupSwitch:
            if len(instruction.operands) < 3:
                raise InvalidABCCodeError(
                    f"Malformed LookupSwitch operands at offset {instruction.offset}"
                )

            default_rel = instruction.operands[0]
            case_offsets = instruction.operands[2]
            if not isinstance(case_offsets, list):
                raise InvalidABCCodeError(
                    f"Malformed LookupSwitch case table at offset {instruction.offset}"
                )

            switch_targets = []
            default_target = self._resolve_branch_target_offset(
                instruction=instruction,
                relative_offset=default_rel,
                next_offset=next_offset,
                instruction_offsets=instruction_offsets,
                code_length=code_length,
                allow_relaxed=not self._strict_lookupswitch,
            )
            if default_target in instruction_offsets:
                switch_targets.append((default_target, self._EDGE_KIND_LOOKUPSWITCH))
            for rel in case_offsets:
                target = self._resolve_branch_target_offset(
                    instruction=instruction,
                    relative_offset=rel,
                    next_offset=next_offset,
                    instruction_offsets=instruction_offsets,
                    code_length=code_length,
                    allow_relaxed=not self._strict_lookupswitch,
                )
                if target in instruction_offsets:
                    switch_targets.append((target, self._EDGE_KIND_LOOKUPSWITCH))
            return switch_targets

        if next_offset is not None:
            return [(next_offset, self._EDGE_KIND_NORMAL)]
        return []

    def _resolve_branch_target_offset(
        self,
        *,
        instruction: Instruction,
        relative_offset: Any,
        next_offset: Optional[int],
        instruction_offsets: set[int],
        code_length: int,
        allow_relaxed: bool = True,
    ) -> int:
        if not isinstance(relative_offset, int):
            if not self._verify_branch_targets:
                return -1
            raise InvalidABCCodeError(
                f"Invalid branch offset type at {instruction.offset}: {type(relative_offset).__name__}"
            )

        base = code_length if next_offset is None else next_offset
        target = base + relative_offset
        if target not in instruction_offsets:
            if not self._verify_branch_targets:
                return -1
            if allow_relaxed:
                return -1
            raise InvalidABCCodeError(
                "Invalid branch target offset: "
                f"{target} for opcode={instruction.opcode.name} at offset={instruction.offset}"
            )
        return target

    @staticmethod
    def _multiname_runtime_arity(instruction: Instruction) -> int:
        if not instruction.operands:
            return 0
        runtime_arity = getattr(instruction.operands[0], "runtime_arity", 0)
        if isinstance(runtime_arity, int) and runtime_arity >= 0:
            return runtime_arity
        return 0

    def _stack_effect_for_instruction(
        self, instruction: Instruction
    ) -> Tuple[int, int]:
        opcode = instruction.opcode
        effect = self._STACK_EFFECT_STATIC_TABLE[opcode.value]
        if effect is not None:
            return effect

        # Stack-effect coverage marker:
        # Opcode.Add Opcode.AddI Opcode.Subtract Opcode.SubtractI Opcode.Multiply Opcode.MultiplyI Opcode.Divide
        # Opcode.Modulo Opcode.BitAnd Opcode.BitOr Opcode.BitXor Opcode.LShift Opcode.RShift Opcode.URShift
        # Opcode.Equals Opcode.StrictEquals Opcode.LessThan Opcode.LessEquals Opcode.GreaterThan Opcode.GreaterEquals
        # Opcode.In Opcode.InstanceOf Opcode.AsTypeLate Opcode.IsTypeLate
        # Opcode.Increment Opcode.IncrementI Opcode.Decrement Opcode.DecrementI Opcode.Negate Opcode.NegateI
        # Opcode.BitNot Opcode.Not Opcode.ConvertB Opcode.ConvertD Opcode.ConvertI Opcode.ConvertO Opcode.ConvertS Opcode.ConvertU
        # Opcode.Coerce Opcode.CoerceA Opcode.CoerceB Opcode.CoerceD Opcode.CoerceI Opcode.CoerceO Opcode.CoerceS Opcode.CoerceU
        # Opcode.AsType Opcode.IsType Opcode.TypeOf Opcode.EscXElem Opcode.EscXAttr Opcode.CheckFilter
        if opcode in self._STACK_EFFECT_GET_PROPERTY_OPCODES:
            runtime_arity = self._multiname_runtime_arity(instruction)
            return 1 + runtime_arity, 1

        if opcode in self._STACK_EFFECT_SET_PROPERTY_OPCODES:
            runtime_arity = self._multiname_runtime_arity(instruction)
            return 2 + runtime_arity, 0

        if opcode == Opcode.DeleteProperty:
            runtime_arity = self._multiname_runtime_arity(instruction)
            return 1 + runtime_arity, 1

        if opcode in self._STACK_EFFECT_FIND_PROPERTY_OPCODES:
            runtime_arity = self._multiname_runtime_arity(instruction)
            return runtime_arity, 1

        if opcode == Opcode.NewArray:
            arg_count = self._op_int(instruction, 0) if instruction.operands else 0
            return arg_count, 1

        if opcode == Opcode.NewObject:
            pair_count = self._op_int(instruction, 0) if instruction.operands else 0
            return pair_count * 2, 1

        if opcode == Opcode.NewClass:
            return 1, 1

        if opcode == Opcode.ApplyType:
            arg_count = self._op_int(instruction, 0) if instruction.operands else 0
            return arg_count + 1, 1

        if opcode == Opcode.Call:
            arg_count = self._op_int(instruction, 0) if instruction.operands else 0
            return arg_count + 2, 1

        if opcode == Opcode.CallMethod:
            arg_count = (
                self._op_int(instruction, 1) if len(instruction.operands) > 1 else 0
            )
            return arg_count + 1, 1

        if opcode == Opcode.CallStatic:
            arg_count = (
                self._op_int(instruction, 1) if len(instruction.operands) > 1 else 0
            )
            return arg_count + 1, 1

        if opcode in self._STACK_EFFECT_CALL_PROPERTY_OPCODES:
            arg_count = (
                self._op_int(instruction, 1) if len(instruction.operands) > 1 else 0
            )
            base_pops = 1  # receiver
            pushes = 1
            runtime_arity = self._multiname_runtime_arity(instruction)
            return arg_count + base_pops + runtime_arity, pushes

        if opcode in self._STACK_EFFECT_CALL_PROPVOID_OPCODES:
            arg_count = (
                self._op_int(instruction, 1) if len(instruction.operands) > 1 else 0
            )
            runtime_arity = self._multiname_runtime_arity(instruction)
            return arg_count + 1 + runtime_arity, 0

        if opcode == Opcode.Construct:
            arg_count = self._op_int(instruction, 0) if instruction.operands else 0
            return arg_count + 1, 1

        if opcode == Opcode.ConstructSuper:
            arg_count = self._op_int(instruction, 0) if instruction.operands else 0
            return arg_count + 1, 0

        # Conservative fallback for opcodes without explicit stack semantics.
        return 0, 0

    @staticmethod
    def _validate_exception_ranges(
        exceptions: List[ExceptionInfo],
        code_length: int,
        instructions: List[Instruction],
    ) -> None:
        instruction_offsets = {inst.offset for inst in instructions}
        valid_range_boundaries = set(instruction_offsets)
        valid_range_boundaries.add(code_length)

        for exc in exceptions:
            if exc.from_offset > exc.to_offset:
                raise InvalidABCCodeError(
                    f"Invalid exception range: from({exc.from_offset}) must be <= to({exc.to_offset})"
                )

            if (
                exc.from_offset not in valid_range_boundaries
                or exc.to_offset not in valid_range_boundaries
            ):
                raise InvalidABCCodeError(
                    "Invalid exception range: "
                    f"from={exc.from_offset}, to={exc.to_offset}, code_length={code_length}"
                )

            if exc.target_offset not in instruction_offsets:
                raise InvalidABCCodeError(
                    f"Invalid exception target offset: {exc.target_offset}"
                )

    @staticmethod
    def _filter_valid_exception_ranges(
        exceptions: List[ExceptionInfo],
        code_length: int,
        instructions: List[Instruction],
    ) -> List[ExceptionInfo]:
        instruction_offsets = {inst.offset for inst in instructions}
        valid_range_boundaries = set(instruction_offsets)
        valid_range_boundaries.add(code_length)

        filtered: List[ExceptionInfo] = []
        for exc in exceptions:
            if exc.from_offset > exc.to_offset:
                continue
            if (
                exc.from_offset not in valid_range_boundaries
                or exc.to_offset not in valid_range_boundaries
            ):
                continue
            if exc.target_offset not in instruction_offsets:
                continue
            filtered.append(exc)
        return filtered

    @staticmethod
    def _validate_trait_metadata_indices(
        traits: List[Trait],
        metadata_count: int,
        context: str,
        strict_metadata_indices: bool = False,
    ) -> None:
        for trait in traits:
            raw_indices = trait.data.get("metadata_indices") if trait.data else None
            if not raw_indices:
                continue

            for idx in raw_indices:
                in_zero_based_range = 0 <= idx < metadata_count
                in_one_based_range = 1 <= idx <= metadata_count
                if strict_metadata_indices:
                    valid = in_zero_based_range
                else:
                    valid = in_zero_based_range or in_one_based_range

                if valid:
                    continue

                raise InvalidABCCodeError(
                    f"{context} trait metadata index out of range: {idx}, metadata_count: {metadata_count}"
                )

    @staticmethod
    def _resolve_trait_metadata_names(
        traits: List[Trait],
        metadata: List[Any],
        strict_metadata_indices: bool = False,
    ) -> None:
        if not metadata:
            return

        metadata_count = len(metadata)
        for trait in traits:
            raw_indices = trait.data.get("metadata_indices") if trait.data else None
            if not raw_indices:
                continue

            resolved_names: list[str] = []
            for idx in raw_indices:
                if strict_metadata_indices:
                    resolved_idx = idx
                else:
                    # Compatibility mode accepts both zero-based and one-based references.
                    if 0 <= idx < metadata_count:
                        resolved_idx = idx
                    else:
                        resolved_idx = idx - 1

                if 0 <= resolved_idx < metadata_count:
                    meta_name = getattr(metadata[resolved_idx], "name", None)
                    if isinstance(meta_name, str):
                        resolved_names.append(meta_name)

            trait.metadata = resolved_names

    @staticmethod
    def _validate_trait_references(
        traits: List[Trait],
        methods_count: int,
        classes_count: int,
        context: str,
    ) -> None:
        for trait in traits:
            if trait.kind in (TraitKind.METHOD, TraitKind.GETTER, TraitKind.SETTER):
                if trait.data is None:
                    continue
                ref = trait.data.get("method")
                index = ref.value if isinstance(ref, Index) else ref
                if index is None or index >= methods_count:
                    raise InvalidABCCodeError(
                        f"{context} trait method index out of range: {index}, max: {methods_count - 1}"
                    )

            elif trait.kind == TraitKind.FUNCTION:
                if trait.data is None:
                    continue
                ref = trait.data.get("function")
                index = ref.value if isinstance(ref, Index) else ref
                if index is None or index >= methods_count:
                    raise InvalidABCCodeError(
                        f"{context} trait function index out of range: {index}, max: {methods_count - 1}"
                    )

            elif trait.kind == TraitKind.CLASS:
                if trait.data is None:
                    continue
                ref = trait.data.get("class")
                index = ref.value if isinstance(ref, Index) else ref
                if index is None or index >= classes_count:
                    raise InvalidABCCodeError(
                        f"{context} trait class index out of range: {index}, max: {classes_count - 1}"
                    )
