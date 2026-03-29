"""
Public library API: decompilation orchestration, formatting, multi-file export.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from oven.avm2 import ABCFile, parse, parse_file
from oven.avm2.config import ParseMode, VerifyProfile

from oven.api.decompile_to_as_files import decompile_abc_to_as_files
from oven.api.decompiler import (
    AS3Emitter,
    MethodContext,
    SwitchSection,
    _decompile_abc_parsed,
    _decompile_abc_parsed_to_files,
    decompile_abc,
    decompile_abc_to_files,
    decompile_method,
)
from oven.api.formatter import (
    AS3Lexer,
    AS3Processor,
    CommentPolicy,
    ProcessorConfig,
    Token,
    TokenType,
)

__all__ = [
    "decompile",
    "decompile_abc_to_as_files",
    "decompile_method",
    "decompile_abc",
    "decompile_abc_to_files",
    "_decompile_abc_parsed",
    "_decompile_abc_parsed_to_files",
    "AS3Emitter",
    "MethodContext",
    "SwitchSection",
    "AS3Lexer",
    "AS3Processor",
    "CommentPolicy",
    "ProcessorConfig",
    "Token",
    "TokenType",
]


def decompile(
    target: Union[bytes, bytearray, memoryview, str, Path, ABCFile],
    method_idx: Optional[int] = None,
    *,
    style: str = "semantic",
    minify: bool = False,
    layout: str = "methods",
    int_format: str = "dec",
    inline_vars: bool = False,
    mode: ParseMode | str | None = None,
    profile: VerifyProfile | str | None = None,
) -> str:
    """Parse ABC, decompile to AS3, then run the formatter (pretty-print or minify)."""
    if isinstance(target, ABCFile):
        abc = target
    elif isinstance(target, (str, Path)):
        abc = parse_file(target, mode=mode or ParseMode.RELAXED, profile=profile)
    elif isinstance(target, (bytes, bytearray, memoryview)):
        abc = parse(bytes(target), mode=mode or ParseMode.RELAXED, profile=profile)
    else:
        raise TypeError(f"Unsupported decompile target type: {type(target).__name__}")

    raw_code = _decompile_abc_parsed(
        abc,
        method_idx=method_idx,
        style=style,
        layout=layout,
        int_format=int_format,
        inline_vars=inline_vars,
    )
    config = ProcessorConfig(is_minify=minify, comment_policy=CommentPolicy.IMPORTANT)
    tokens = AS3Lexer(config).tokenize(raw_code)
    return AS3Processor(tokens, config).run()
