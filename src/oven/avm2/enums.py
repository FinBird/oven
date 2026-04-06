"""AVM2 domain enums and shared type declarations."""

from dataclasses import dataclass
from enum import Enum, IntEnum
from typing import (
    TypeVar,
    Generic,
    TypedDict,
    Literal,
    TypeAlias,
)
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .constant_pool import ConstantPool

T = TypeVar("T")


class Index(Generic[T]):
    """Type-safe constant-pool index wrapper (simplified)."""

    def __init__(self, value: int):
        self.value = value

    def resolve(self, pool: "ConstantPool", kind_hint: str | None = None) -> Any:
        """Resolve the wrapped index into an actual pool value."""
        if pool is None or self.value == 0:
            return self.value
        return pool.resolve_index(self.value, kind_hint)

    def to_dict(
        self, pool: "ConstantPool | None" = None, kind_hint: str | None = None
    ) -> Any:
        """Return serializable value or resolved value when pool is provided."""
        if pool:
            return self.resolve(pool, kind_hint)
        return self.value

    def __repr__(self) -> str:
        return f"Index({self.value})"


class NamespaceKind(IntEnum):
    """Namespace-kind enum."""

    NAMESPACE = 0x08
    PACKAGE_NAMESPACE = 0x16
    PACKAGE_INTERNAL_NS = 0x17
    PROTECTED_NAMESPACE = 0x18
    EXPLICIT_NAMESPACE = 0x19
    STATIC_PROTECTED_NS = 0x1A
    PRIVATE_NS = 0x05


class MultinameKind(IntEnum):
    """Multiname-kind enum."""

    QNAME = 0x07
    QNAMEA = 0x0D
    RTQNAME = 0x0F
    RTQNAMEA = 0x10
    RTQNAMEL = 0x11
    RTQNAMELA = 0x12
    MULTINAME = 0x09
    MULTINAMEA = 0x0E
    MULTINAMEL = 0x1B
    MULTINAMELA = 0x1C
    TYPENAME = 0x1D


class ConstantKind(IntEnum):
    """Constant-kind enum."""

    UNDEFINED = 0x00
    UTF8 = 0x01
    INT = 0x03
    UINT = 0x04
    PRIVATE_NS = 0x05
    DOUBLE = 0x06
    NAMESPACE = 0x08
    FALSE = 0x0A
    TRUE = 0x0B
    NULL = 0x0C
    PACKAGE_NAMESPACE = 0x16
    PACKAGE_INTERNAL_NS = 0x17
    PROTECTED_NAMESPACE = 0x18
    EXPLICIT_NAMESPACE = 0x19
    STATIC_PROTECTED_NS = 0x1A


class TraitKind(IntEnum):
    """Trait-kind enum."""

    SLOT = 0
    METHOD = 1
    GETTER = 2
    SETTER = 3
    CLASS = 4
    FUNCTION = 5
    CONST = 6


class Opcode(IntEnum):
    """AVM2 opcode enum grouped by usage categories."""

    # Control flow
    IfEq = 0x13
    IfFalse = 0x12
    IfGe = 0x18
    IfGt = 0x17
    IfLe = 0x16
    IfLt = 0x15
    IfNe = 0x14
    IfNge = 0x0F
    IfNgt = 0x0E
    IfNle = 0x0D
    IfNlt = 0x0C
    IfStrictEq = 0x19
    IfStrictNe = 0x1A
    IfTrue = 0x11
    Jump = 0x10
    LookupSwitch = 0x1B
    Label = 0x09

    # Arithmetic
    Add = 0xA0
    AddI = 0xC5
    Subtract = 0xA1
    SubtractI = 0xC6
    Multiply = 0xA2
    MultiplyI = 0xC7
    Divide = 0xA3
    Modulo = 0xA4
    Increment = 0x91
    IncrementI = 0xC0
    Decrement = 0x93
    DecrementI = 0xC1
    Negate = 0x90
    NegateI = 0xC4

    # Bitwise
    BitAnd = 0xA8
    BitOr = 0xA9
    BitXor = 0xAA
    BitNot = 0x97
    LShift = 0xA5
    RShift = 0xA6
    URShift = 0xA7

    # Comparisons
    Equals = 0xAB
    StrictEquals = 0xAC
    LessThan = 0xAD
    LessEquals = 0xAE
    GreaterThan = 0xAF
    GreaterEquals = 0xB0
    In = 0xB4

    # Type conversions
    ConvertB = 0x76
    ConvertD = 0x75
    ConvertI = 0x73
    ConvertO = 0x77
    ConvertS = 0x70
    ConvertU = 0x74
    Coerce = 0x80
    CoerceA = 0x82
    CoerceB = 0x81
    CoerceD = 0x84
    CoerceI = 0x83
    CoerceO = 0x89
    CoerceS = 0x85
    CoerceU = 0x88
    AsType = 0x86
    AsTypeLate = 0x87
    IsType = 0xB2
    IsTypeLate = 0xB3
    InstanceOf = 0xB1
    TypeOf = 0x95

    # Stack operations
    Dup = 0x2A
    Swap = 0x2B
    Pop = 0x29
    PushByte = 0x24
    PushShort = 0x25
    PushTrue = 0x26
    PushFalse = 0x27
    PushNaN = 0x28
    PushNull = 0x20
    PushUndefined = 0x21
    PushInt = 0x2D
    PushUint = 0x2E
    PushDouble = 0x2F
    PushString = 0x2C
    PushNamespace = 0x31
    Nop = 0x02
    Not = 0x96

    # Local variables
    GetLocal = 0x62
    GetLocal0 = 0xD0
    GetLocal1 = 0xD1
    GetLocal2 = 0xD2
    GetLocal3 = 0xD3
    SetLocal = 0x63
    SetLocal0 = 0xD4
    SetLocal1 = 0xD5
    SetLocal2 = 0xD6
    SetLocal3 = 0xD7
    Kill = 0x08
    DecLocal = 0x94
    DecLocalI = 0xC3
    IncLocal = 0x92
    IncLocalI = 0xC2

    # Scope operations
    GetGlobalScope = 0x64
    GetScopeObject = 0x65
    GetOuterScope = 0x67
    PushScope = 0x30
    PopScope = 0x1D
    PushWith = 0x1C

    # Property operations
    GetProperty = 0x66
    SetProperty = 0x61
    InitProperty = 0x68
    DeleteProperty = 0x6A
    GetSuper = 0x04
    SetSuper = 0x05
    GetDescendants = 0x59
    FindProperty = 0x5E
    FindPropStrict = 0x5D
    FindDef = 0x5F
    GetLex = 0x60

    # Slot operations
    GetSlot = 0x6C
    SetSlot = 0x6D
    GetGlobalSlot = 0x6E
    SetGlobalSlot = 0x6F

    # Function calls
    Call = 0x41
    CallMethod = 0x43
    CallProperty = 0x46
    CallPropLex = 0x4C
    CallPropVoid = 0x4F
    CallStatic = 0x44
    CallSuper = 0x45
    CallSuperVoid = 0x4E
    Construct = 0x42
    ConstructProp = 0x4A
    ConstructSuper = 0x49

    # Object construction
    NewObject = 0x55
    NewArray = 0x56
    NewActivation = 0x57
    NewClass = 0x58
    NewFunction = 0x40
    NewCatch = 0x5A
    ApplyType = 0x53

    # Iteration
    HasNext = 0x1F
    HasNext2 = 0x32
    NextName = 0x1E
    NextValue = 0x23

    # XML operations
    EscXElem = 0x71
    EscXAttr = 0x72
    CheckFilter = 0x78
    Dxns = 0x06
    DxnsLate = 0x07

    # Debug
    Debug = 0xEF
    DebugFile = 0xF1
    DebugLine = 0xF0

    # Return and exception flow
    ReturnValue = 0x48
    ReturnVoid = 0x47
    Throw = 0x03

    # Sign-extension instructions
    Sxi1 = 0x50
    Sxi8 = 0x51
    Sxi16 = 0x52

    # Load/store instructions
    Li8 = 0x35
    Li16 = 0x36
    Li32 = 0x37
    Lf32 = 0x38
    Lf64 = 0x39
    Si8 = 0x3A
    Si16 = 0x3B
    Si32 = 0x3C
    Sf32 = 0x3D
    Sf64 = 0x3E

    # Miscellaneous instructions
    Timestamp = 0xF3
    Bkpt = 0x01
    BkptLine = 0xF2


class EdgeKind(str, Enum):
    """Control flow edge kind enum for verifier state transfer."""

    ENTRY = "entry"
    NORMAL = "normal"
    LOOKUPSWITCH = "lookupswitch"
    EXCEPTION_ENTRY = "exception_entry"


# TypedDicts used for serialized outputs.
class DefaultValueDict(TypedDict):
    kind: int
    value: int | None | bool | str


class NamespaceDict(TypedDict):
    kind: str
    name: int


class MultinameQNameDict(TypedDict):
    kind: Literal["QNAME", "QNAMEA"]
    namespace: int
    name: int


class MultinameRTQNameDict(TypedDict):
    kind: Literal["RTQNAME", "RTQNAMEA"]
    name: int


class MultinameMultinameDict(TypedDict):
    kind: Literal["MULTINAME", "MULTINAMEA"]
    name: int
    namespace_set: int


class MultinameMultinameLDict(TypedDict):
    kind: Literal["MULTINAMEL", "MULTINAMELA"]
    namespace_set: int


class MultinameTypeNameDict(TypedDict):
    kind: Literal["TYPENAME"]
    base_type: int
    parameters: list[int]


class MultinameRTQNameLDict(TypedDict):
    kind: Literal["RTQNameL", "RTQNameLA"]


MultinameDict: TypeAlias = (
    MultinameQNameDict
    | MultinameRTQNameDict
    | MultinameMultinameDict
    | MultinameMultinameLDict
    | MultinameRTQNameLDict
    | MultinameTypeNameDict
)


@dataclass
class DefaultValue:
    """Immutable default-value model for method parameters."""

    kind: ConstantKind
    value: int | Index[Any] | None | bool | str

    def to_dict(self) -> DefaultValueDict:
        if isinstance(self.value, Index):
            return {"kind": self.kind.value, "value": self.value.value}
        else:
            return {"kind": self.kind.value, "value": self.value}

    def __repr__(self) -> str:
        return f"DefaultValue({self.kind.name}={self.value})"


class MethodParamDict(TypedDict):
    kind: int
    name: str | None
    default_value: DefaultValueDict | None


class MethodDict(TypedDict):
    name: str
    params: list[MethodParamDict]
    return_type: str
    flags: int
    flags_described: list[str]
    body: int | None


class ExceptionDict(TypedDict):
    from_offset: int
    to_offset: int
    target_offset: int
    exc_type: str
    var_name: str


class TraitDict(TypedDict):
    name: str
    kind: str
    metadata: list[str]
    is_final: bool
    is_override: bool
    data: dict[str, Any] | None


class InstanceInfoDict(TypedDict):
    name: str
    super_name: str
    is_sealed: bool
    is_final: bool
    is_interface: bool
    protected_namespace: str | None
    interfaces: list[str]
    init_method: int
    traits: list[TraitDict]


class ClassInfoDict(TypedDict):
    init_method: int
    traits: list[TraitDict]


class ScriptInfoDict(TypedDict):
    init_method: int
    traits: list[TraitDict]


class MetadataItemDict(TypedDict):
    key: str | None
    value: str


class MetadataInfoDict(TypedDict):
    name: str
    items: list[MetadataItemDict]


OperandType: TypeAlias = int | str | float | bool | list[int] | tuple[int, int] | None


class InstructionDict(TypedDict):
    opcode: str
    operands: list[Any]
    offset: int


@dataclass(slots=True)
class Instruction:
    """Immutable bytecode-instruction model."""

    opcode: Opcode
    operands: list[Any]
    offset: int = 0

    def to_dict(self, pool: "ConstantPool | None" = None) -> InstructionDict:
        return {
            "opcode": self.opcode.name,
            "operands": self.operands,
            "offset": self.offset,
        }

    def __repr__(self) -> str:
        operands_str = ", ".join(str(op) for op in self.operands)
        return (
            f"Instruction({self.opcode.name}, [{operands_str}], offset={self.offset})"
        )


class MethodBodyDict(TypedDict):
    method: int
    max_stack: int
    num_locals: int
    init_scope_depth: int
    max_scope_depth: int
    code: list[int]
    exceptions: list[ExceptionDict]
    traits: list[TraitDict]
    instructions: list[InstructionDict]


class ConstantPoolDict(TypedDict):
    ints: list[int]
    uints: list[int]
    doubles: list[float]
    strings: list[str]
    namespaces: list[NamespaceDict]
    namespace_sets: list[list[int]]
    multinames: list[MultinameDict]


class ABCFileDict(TypedDict):
    minor_version: int
    major_version: int
    constant_pool: ConstantPoolDict
    methods: list[MethodDict]
    metadata: list[MetadataInfoDict]
    instances: list[InstanceInfoDict]
    classes: list[ClassInfoDict]
    scripts: list[ScriptInfoDict]
    method_bodies: list[MethodBodyDict]
