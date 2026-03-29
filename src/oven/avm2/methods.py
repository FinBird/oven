from dataclasses import dataclass
from typing import List, Optional, TYPE_CHECKING
from enum import IntFlag

from .enums import (
    DefaultValue,
    MethodDict, MethodParamDict, MethodBodyDict,
    ExceptionDict, Instruction
)

if TYPE_CHECKING:
    from .traits import Trait
    from .constant_pool import ConstantPool


class MethodFlags(IntFlag):
    """Method flag bitmask definitions."""
    NONE = 0x00
    NEED_ARGUMENTS = 0x01  # Requires an arguments object.
    NEED_ACTIVATION = 0x02  # Requires an activation object.
    NEED_REST = 0x04        # Uses a rest parameter.
    HAS_OPTIONAL = 0x08     # Contains optional parameters.
    IGNORE_REST = 0x10      # Ignores rest arguments.
    NATIVE = 0x20           # Native method.
    SET_DXNS = 0x40         # Sets default XML namespace.
    HAS_PARAM_NAMES = 0x80  # Carries parameter names.

    def describe(self) -> List[str]:
        """Return a list of active flag names."""
        flags = []
        if self & MethodFlags.NEED_ARGUMENTS:
            flags.append("NEED_ARGUMENTS")
        if self & MethodFlags.NEED_ACTIVATION:
            flags.append("NEED_ACTIVATION")
        if self & MethodFlags.NEED_REST:
            flags.append("NEED_REST")
        if self & MethodFlags.HAS_OPTIONAL:
            flags.append("HAS_OPTIONAL")
        if self & MethodFlags.IGNORE_REST:
            flags.append("IGNORE_REST")
        if self & MethodFlags.NATIVE:
            flags.append("NATIVE")
        if self & MethodFlags.SET_DXNS:
            flags.append("SET_DXNS")
        if self & MethodFlags.HAS_PARAM_NAMES:
            flags.append("HAS_PARAM_NAMES")
        return flags


@dataclass
class MethodParam:
    """Immutable method parameter model."""
    kind: int  # Parameter type index.
    name: Optional[str] = None  # Resolved parameter name.
    default_value: Optional[DefaultValue] = None  # Optional default value.

    def to_dict(self, pool: Optional['ConstantPool'] = None) -> MethodParamDict:
        """Return a serializable dictionary."""
        dv_dict = None
        if self.default_value:
            dv_dict = self.default_value.to_dict()

        return {
            "kind": self.kind,
            "name": self.name,
            "default_value": dv_dict
        }

    def __repr__(self) -> str:
        base = f"MethodParam(kind={self.kind}"
        if self.name:
            base += f", name={self.name}"
        if self.default_value:
            base += f", default={self.default_value}"
        return base + ")"


@dataclass
class ExceptionInfo:
    """Immutable exception table entry."""
    from_offset: int
    to_offset: int
    target_offset: int
    exc_type: str  # Resolved exception type.
    var_name: str  # Resolved variable name.

    def to_dict(self, pool: Optional['ConstantPool'] = None) -> ExceptionDict:
        return {
            "from_offset": self.from_offset,
            "to_offset": self.to_offset,
            "target_offset": self.target_offset,
            "exc_type": self.exc_type,
            "var_name": self.var_name
        }

    def __repr__(self) -> str:
        return f"ExceptionInfo(from={self.from_offset}, to={self.to_offset}, target={self.target_offset}, type={self.exc_type})"


@dataclass
class MethodInfo:
    """Immutable method metadata."""
    name: str  # Resolved method name.
    params: List[MethodParam]
    return_type: str  # Resolved return type.
    flags: MethodFlags
    body: Optional['MethodBody'] = None  # Linked method body.

    def to_dict(self, pool: Optional['ConstantPool'] = None) -> MethodDict:
        """Return a serializable dictionary."""
        return {
            "name": self.name,
            "params": [param.to_dict(pool) for param in self.params],
            "return_type": self.return_type,
            "flags": int(self.flags),
            "flags_described": self.flags.describe(),
            "body": self.body.method if self.body else None  # Method body index.
        }

    def __repr__(self) -> str:
        params_str = ", ".join(str(p) for p in self.params)
        return f"MethodInfo({self.name}({params_str}) -> {self.return_type})"


@dataclass
class MethodBody:
    """Immutable method-body model."""
    method: int  # Method index.
    max_stack: int
    num_locals: int
    init_scope_depth: int
    max_scope_depth: int
    code: bytes
    exceptions: List[ExceptionInfo]
    traits: List['Trait']
    instructions: List[Instruction]

    def to_dict(self, pool: Optional['ConstantPool'] = None) -> MethodBodyDict:
        """Return a serializable dictionary."""
        return {
            "method": self.method,
            "max_stack": self.max_stack,
            "num_locals": self.num_locals,
            "init_scope_depth": self.init_scope_depth,
            "max_scope_depth": self.max_scope_depth,
            "code": list(self.code),
            "exceptions": [e.to_dict(pool) for e in self.exceptions],
            "traits": [t.to_dict(pool) for t in self.traits],
            "instructions": [inst.to_dict(pool) for inst in self.instructions]
        }

    def to_string(self, pool: Optional['ConstantPool'] = None, show_offsets: bool = True) -> str:
        """Serialize the instruction stream as readable text."""
        from .abc.reader import ABCReader
        # Use a temporary reader for formatting helpers.
        reader = ABCReader(b"")
        return reader.serialize_instructions_to_string(self.instructions, pool, show_offsets)

    def to_function_calls(self, pool: Optional['ConstantPool'] = None) -> str:
        """Serialize instructions as macro-like function calls."""
        from .abc.reader import ABCReader
        # Use a temporary reader for formatting helpers.
        reader = ABCReader(b"")
        return reader.serialize_instructions_as_function_calls(self.instructions, pool)

    def __repr__(self) -> str:
        return (f"MethodBody(method={self.method}, stack={self.max_stack}, "
                f"locals={self.num_locals}, instructions={len(self.instructions)})")

    def __str__(self) -> str:
        """Return a verbose string representation with instruction details."""
        lines = []
        lines.append(f"MethodBody(method={self.method}, stack={self.max_stack}, locals={self.num_locals})")
        lines.append(f"  init_scope_depth={self.init_scope_depth}, max_scope_depth={self.max_scope_depth}")
        lines.append(f"  code_length={len(self.code)}, exceptions={len(self.exceptions)}, traits={len(self.traits)}")
        
        if self.instructions:
            lines.append("  Instructions:")
            for inst in self.instructions:
                # Show detailed instruction information.
                operands_str = ", ".join(str(op) for op in inst.operands) if inst.operands else ""
                lines.append(f"    [{inst.offset:3d}] {inst.opcode.name:20} {operands_str}")
        
        if self.exceptions:
            lines.append("  Exceptions:")
            for exc in self.exceptions:
                lines.append(f"    {exc}")
        
        if self.traits:
            lines.append("  Traits:")
            for trait in self.traits:
                lines.append(f"    {trait}")
        
        return "\n".join(lines)
