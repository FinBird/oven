"""AS3 text emission (AST → source). Implementation in ``api.decompiler``."""

from oven.api.decompiler import (
    AS3Emitter,
    LocalDeclaration,
    MethodContext,
    SwitchSection,
    _try_fast_emit_method_text,
)

__all__ = [
    "AS3Emitter",
    "LocalDeclaration",
    "MethodContext",
    "SwitchSection",
    "_try_fast_emit_method_text",
]
