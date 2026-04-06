"""AS3 text emission (AST → source)."""

from oven.avm2.decompiler.render import (
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
