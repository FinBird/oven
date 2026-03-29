"""
ABC parsing and decompilation entrypoints.
"""

from pathlib import Path

from oven.avm2.buffer import Buffer, BufferError
from oven.avm2.config import ParseMode, VerifyProfile
from oven.avm2.constant_pool import ConstantPool, Multiname, MultinameRef, NamespaceInfo, NamespaceSet
from oven.avm2.enums import (
    ConstantKind,
    DefaultValue,
    Index,
    Instruction,
    MultinameKind,
    NamespaceKind,
    Opcode,
    TraitKind,
)
from oven.avm2.exceptions import (
    ABCParseError,
    AVM2Error,
    ConstantPoolError,
    InvalidABCCodeError,
    MethodParseError,
    TraitParseError,
)
from oven.avm2.file import ABCFile, MetadataInfo, MetadataItem
from oven.avm2.methods import ExceptionInfo, MethodBody, MethodFlags, MethodInfo, MethodParam
from oven.avm2.abc.reader import ABCReader
from oven.avm2.traits import ClassInfo, InstanceInfo, ScriptInfo, Trait

__all__ = [
    # Minimal public API
    "parse",
    "parse_file",
    "decompile",
    "ParseMode",
    "VerifyProfile",
    # Compatibility entrypoints
    "parse_abc",
    "load_abc",
    "decompile_abc",
    "decompile_abc_to_files",
    "decompile_to_files",
    "decompile_method",
    # Core classes
    "ABCFile",
    "Buffer",
    "BufferError",
    "ABCReader",
    "ConstantPool",
    # Namespace-related types
    "NamespaceInfo",
    "NamespaceSet",
    "Multiname",
    "MultinameRef",
    # Method-related types
    "MethodInfo",
    "MethodBody",
    "MethodParam",
    "ExceptionInfo",
    "MethodFlags",
    # Trait-related types
    "InstanceInfo",
    "ClassInfo",
    "ScriptInfo",
    "Trait",
    # Metadata-related types
    "MetadataItem",
    "MetadataInfo",
    # Shared enums and value objects
    "Index",
    "NamespaceKind",
    "MultinameKind",
    "ConstantKind",
    "TraitKind",
    "Opcode",
    "DefaultValue",
    "Instruction",
    # Exceptions
    "AVM2Error",
    "ABCParseError",
    "InvalidABCCodeError",
    "ConstantPoolError",
    "MethodParseError",
    "TraitParseError",
]


def parse(
    data: bytes,
    *,
    mode: ParseMode | str | None = None,
    profile: VerifyProfile | str | None = None,
    precision_enhanced: bool | None = None,
) -> ABCFile:
    """Parse ABC bytes.

    When `mode`/`profile` are not supplied, this follows compatibility defaults
    (same baseline behavior as `parse_abc`).
    """
    return ABCFile.from_bytes(
        data,
        mode=mode,
        verify_profile=profile,
        precision_enhanced=precision_enhanced,
    )


def parse_file(
    filepath: str | Path,
    *,
    mode: ParseMode | str | None = None,
    profile: VerifyProfile | str | None = None,
    precision_enhanced: bool | None = None,
) -> ABCFile:
    """Parse an ABC file from disk."""
    with open(filepath, "rb") as f:
        return parse(
            f.read(),
            mode=mode,
            profile=profile,
            precision_enhanced=precision_enhanced,
        )


def parse_abc(
    data: bytes,
    *,
    mode: ParseMode | str | None = None,
    verify_profile: VerifyProfile | str | None = None,
    strict_metadata_indices: bool = False,
    verify_stack: bool = False,
    verify_relaxed: bool = False,
    verify_stack_semantics: bool | None = None,
    verify_branch_targets: bool | None = None,
    strict_lookupswitch: bool | None = None,
    relax_join_depth: bool | None = None,
    relax_join_types: bool | None = None,
    prefer_precise_any_join: bool | None = None,
    precision_enhanced: bool | None = None,
    lattice_depth_policy: str | None = None,
    lattice_conflict_policy: str | None = None,
    lattice_any_policy: str | None = None,
) -> ABCFile:
    """Compatibility entrypoint: parse ABC bytes."""
    return ABCFile.from_bytes(
        data,
        mode=mode,
        verify_profile=verify_profile,
        strict_metadata_indices=strict_metadata_indices,
        verify_stack=verify_stack,
        verify_relaxed=verify_relaxed,
        verify_stack_semantics=verify_stack_semantics,
        verify_branch_targets=verify_branch_targets,
        strict_lookupswitch=strict_lookupswitch,
        relax_join_depth=relax_join_depth,
        relax_join_types=relax_join_types,
        prefer_precise_any_join=prefer_precise_any_join,
        precision_enhanced=precision_enhanced,
        lattice_depth_policy=lattice_depth_policy,
        lattice_conflict_policy=lattice_conflict_policy,
        lattice_any_policy=lattice_any_policy,
    )


def load_abc(
    filepath: str | Path,
    *,
    mode: ParseMode | str | None = None,
    verify_profile: VerifyProfile | str | None = None,
    strict_metadata_indices: bool = False,
    verify_stack: bool = False,
    verify_relaxed: bool = False,
    verify_stack_semantics: bool | None = None,
    verify_branch_targets: bool | None = None,
    strict_lookupswitch: bool | None = None,
    relax_join_depth: bool | None = None,
    relax_join_types: bool | None = None,
    prefer_precise_any_join: bool | None = None,
    precision_enhanced: bool | None = None,
    lattice_depth_policy: str | None = None,
    lattice_conflict_policy: str | None = None,
    lattice_any_policy: str | None = None,
) -> ABCFile:
    """Compatibility entrypoint: load and parse ABC from a file."""
    with open(filepath, "rb") as f:
        return parse_abc(
            f.read(),
            mode=mode,
            verify_profile=verify_profile,
            strict_metadata_indices=strict_metadata_indices,
            verify_stack=verify_stack,
            verify_relaxed=verify_relaxed,
            verify_stack_semantics=verify_stack_semantics,
            verify_branch_targets=verify_branch_targets,
            strict_lookupswitch=strict_lookupswitch,
            relax_join_depth=relax_join_depth,
            relax_join_types=relax_join_types,
            prefer_precise_any_join=prefer_precise_any_join,
            precision_enhanced=precision_enhanced,
            lattice_depth_policy=lattice_depth_policy,
            lattice_conflict_policy=lattice_conflict_policy,
            lattice_any_policy=lattice_any_policy,
        )


def _decompile_from_abc(
    abc: ABCFile,
    method_idx: int | None = None,
    *,
    style: str = "semantic",
    layout: str = "methods",
    int_format: str = "dec",
    inline_vars: bool = False,
) -> str:
    from oven.api.decompiler import (
        _decompile_abc_parsed as _decompile_abc_parsed,
    )

    return _decompile_abc_parsed(
        abc,
        method_idx=method_idx,
        style=style,
        layout=layout,
        int_format=int_format,
        inline_vars=inline_vars,
    )


def decompile(
    target: bytes | bytearray | memoryview | str | Path | ABCFile,
    method_idx: int | None = None,
    *,
    mode: ParseMode | str = ParseMode.RELAXED,
    profile: VerifyProfile | str | None = None,
    style: str = "semantic",
    layout: str = "methods",
    int_format: str = "dec",
    inline_vars: bool = False,
) -> str:
    """Decompile from bytes, path, or an already parsed ABCFile."""
    if isinstance(target, ABCFile):
        abc = target
    elif isinstance(target, (str, Path)):
        abc = parse_file(target, mode=mode, profile=profile)
    elif isinstance(target, (bytes, bytearray, memoryview)):
        abc = parse(bytes(target), mode=mode, profile=profile)
    else:
        raise TypeError(f"Unsupported decompile target type: {type(target).__name__}")

    return _decompile_from_abc(
        abc,
        method_idx=method_idx,
        style=style,
        layout=layout,
        int_format=int_format,
        inline_vars=inline_vars,
    )


def decompile_method(
    body: MethodBody,
    *,
    style: str = "semantic",
    abc: ABCFile | None = None,
    method_context: object | None = None,
    int_format: str = "dec",
    inline_vars: bool = False,
) -> str:
    """Compatibility entrypoint: decompile a single MethodBody."""
    from oven.api.decompiler import decompile_method as _decompile_method

    return _decompile_method(
        body,
        style=style,
        abc=abc,
        method_context=method_context,
        int_format=int_format,
        inline_vars=inline_vars,
    )


def decompile_abc(
    abc_data: bytes,
    method_idx: int | None = None,
    *,
    style: str = "semantic",
    layout: str = "methods",
    int_format: str = "dec",
    inline_vars: bool = False,
) -> str:
    """Compatibility entrypoint: decompile ABC bytes."""
    return decompile(
        abc_data,
        method_idx=method_idx,
        mode=ParseMode.RELAXED,
        style=style,
        layout=layout,
        int_format=int_format,
        inline_vars=inline_vars,
    )


def decompile_abc_to_files(
    abc_data: bytes,
    output_dir: str | Path,
    *,
    style: str = "semantic",
    int_format: str = "dec",
    clean_output: bool = True,
    inline_vars: bool = False,
) -> list[Path]:
    """Compatibility entrypoint: decompile ABC bytes into .as files."""
    from oven.api.decompiler import decompile_abc_to_files as _decompile_abc_to_files

    return _decompile_abc_to_files(
        abc_data,
        output_dir,
        style=style,
        int_format=int_format,
        clean_output=clean_output,
        inline_vars=inline_vars,
    )


def decompile_to_files(
    target: bytes | bytearray | memoryview | str | Path | ABCFile,
    output_dir: str | Path,
    *,
    mode: ParseMode | str = ParseMode.RELAXED,
    profile: VerifyProfile | str | None = None,
    style: str = "semantic",
    int_format: str = "dec",
    clean_output: bool = True,
    inline_vars: bool = False,
) -> list[Path]:
    """Decompile bytes/path/ABCFile and write class or script outputs to files."""
    from oven.api.decompiler import _decompile_abc_parsed_to_files

    if isinstance(target, ABCFile):
        abc = target
    elif isinstance(target, (str, Path)):
        abc = parse_file(target, mode=mode, profile=profile)
    elif isinstance(target, (bytes, bytearray, memoryview)):
        abc = parse(bytes(target), mode=mode, profile=profile)
    else:
        raise TypeError(f"Unsupported decompile target type: {type(target).__name__}")

    return _decompile_abc_parsed_to_files(
        abc,
        output_dir,
        style=style,
        int_format=int_format,
        clean_output=clean_output,
        inline_vars=inline_vars,
    )
