"""Class-only public export API for the oven decompiler."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Literal

from oven.avm2 import ABCFile, InvalidABCCodeError, parse, parse_file
from oven.avm2.config import ParseMode, VerifyProfile
from oven.avm2.decompiler.engine import (
    _build_method_owner_map,
    _decompile_abc_classes_layout_blocks,
    _decompile_abc_parsed_to_files,
)
from oven.avm2.decompiler.models import DecompilerConfig

FailurePolicy = Literal["continue", "fail_fast"]


def _normalize_parse_mode(mode: ParseMode | str | None) -> ParseMode:
    if mode is None:
        return ParseMode.RELAXED
    if isinstance(mode, ParseMode):
        return mode
    return ParseMode(str(mode).strip().lower())


def _normalize_verify_profile(
    profile: VerifyProfile | str | None,
) -> VerifyProfile | None:
    if profile is None:
        return None
    if isinstance(profile, VerifyProfile):
        return profile
    return VerifyProfile(str(profile).strip().lower())


def _normalize_failure_policy(policy: FailurePolicy | str) -> FailurePolicy:
    token = str(policy).strip().lower()
    if token == "continue":
        return "continue"
    if token == "fail_fast":
        return "fail_fast"
    raise ValueError(
        f"failure_policy must be 'continue' or 'fail_fast', got: {policy!r}"
    )


def _is_invalid_exception_range_error(exc: BaseException) -> bool:
    return "Invalid exception range" in str(exc)


def _should_recover_invalid_exception_range(
    exc: InvalidABCCodeError,
    mode: ParseMode,
) -> bool:
    return mode in {
        ParseMode.FAST,
        ParseMode.STRICT,
    } and _is_invalid_exception_range_error(exc)


def _parse_file_relaxed(
    path: Path,
    *,
    profile: VerifyProfile | None,
) -> ABCFile:
    if profile is None:
        return parse_file(path, mode=ParseMode.RELAXED, profile=None)
    try:
        return parse_file(path, mode=ParseMode.RELAXED, profile=profile)
    except InvalidABCCodeError as exc:
        if not _is_invalid_exception_range_error(exc):
            raise
        return parse_file(path, mode=ParseMode.RELAXED, profile=None)


def _parse_bytes_relaxed(
    data: bytes,
    *,
    profile: VerifyProfile | None,
) -> ABCFile:
    if profile is None:
        return parse(data, mode=ParseMode.RELAXED, profile=None)
    try:
        return parse(data, mode=ParseMode.RELAXED, profile=profile)
    except InvalidABCCodeError as exc:
        if not _is_invalid_exception_range_error(exc):
            raise
        return parse(data, mode=ParseMode.RELAXED, profile=None)


def _parse_file_with_recovery(
    path: Path,
    *,
    mode: ParseMode,
    profile: VerifyProfile | None,
) -> tuple[ABCFile, dict[str, bool]]:
    recovery_flags = {"exception_range_sanitized": False}
    try:
        abc = parse_file(path, mode=mode, profile=profile)
    except InvalidABCCodeError as exc:
        if not _should_recover_invalid_exception_range(exc, mode):
            raise
        recovery_flags["exception_range_sanitized"] = True
        abc = _parse_file_relaxed(path, profile=profile)
    return abc, recovery_flags


def _parse_bytes_with_recovery(
    data: bytes,
    *,
    mode: ParseMode,
    profile: VerifyProfile | None,
) -> tuple[ABCFile, dict[str, bool]]:
    recovery_flags = {"exception_range_sanitized": False}
    try:
        abc = parse(data, mode=mode, profile=profile)
    except InvalidABCCodeError as exc:
        if not _should_recover_invalid_exception_range(exc, mode):
            raise
        recovery_flags["exception_range_sanitized"] = True
        abc = _parse_bytes_relaxed(data, profile=profile)
    return abc, recovery_flags


@dataclass(frozen=True, slots=True)
class ExportOptions:
    """Public export controls with moderate configurability."""

    style: str = "semantic"
    int_format: str = "hex"
    inline_vars: bool = True
    debug: bool = False
    mode: ParseMode | str | None = ParseMode.RELAXED
    profile: VerifyProfile | str | None = None
    failure_policy: FailurePolicy | str = "continue"
    enable_static_init_lifting: bool = True
    enable_constructor_field_lifting: bool = True
    enable_auto_imports: bool = True
    enable_namespace_cleanup: bool = True
    enable_switch_optimization: bool = True
    enable_text_cleanup: bool = True

    @property
    def normalized_mode(self) -> ParseMode:
        return _normalize_parse_mode(self.mode)

    @property
    def normalized_profile(self) -> VerifyProfile | None:
        return _normalize_verify_profile(self.profile)

    @property
    def normalized_failure_policy(self) -> FailurePolicy:
        return _normalize_failure_policy(self.failure_policy)

    def to_internal_config(self) -> DecompilerConfig:
        """
        Map public options to internal decompiler config.

        Internal defaults intentionally stay fixed for API simplicity:
        - layout="classes"
        - minify=False
        - debug comments always include offset/opcode/operands when enabled
        """
        return DecompilerConfig(
            style=self.style,
            layout="classes",
            int_format=self.int_format,
            inline_vars=self.inline_vars,
            minify=False,
            insert_debug_comments=self.debug,
            debug_include_offset=True,
            debug_include_opcode=True,
            debug_include_operands=True,
            mode=self.normalized_mode,
            profile=self.normalized_profile,
            enable_static_init_lifting=self.enable_static_init_lifting,
            enable_constructor_field_lifting=self.enable_constructor_field_lifting,
            enable_auto_imports=self.enable_auto_imports,
            enable_namespace_cleanup=self.enable_namespace_cleanup,
            enable_switch_optimization=self.enable_switch_optimization,
            enable_text_cleanup=self.enable_text_cleanup,
        )


@dataclass(frozen=True, slots=True)
class ClassExport:
    class_name: str
    package_parts: tuple[str, ...]
    source: str
    kind: str


@dataclass(slots=True)
class ExportResult:
    output_files: list[Path] = field(default_factory=list)
    errors: list[dict[str, object]] = field(default_factory=list)
    recovery_flags: dict[str, bool] = field(default_factory=dict)


class Decompiler:
    """Single orchestration entrypoint for ABC export."""

    def __init__(
        self,
        abc: ABCFile,
        *,
        options: ExportOptions | None = None,
        recovery_flags: dict[str, bool] | None = None,
    ) -> None:
        self._abc = abc
        self.options = options or ExportOptions()
        self._owner_map = _build_method_owner_map(self._abc)
        self._recovery_flags: dict[str, bool] = {"exception_range_sanitized": False}
        if recovery_flags:
            self._recovery_flags.update(recovery_flags)
        self._last_errors: list[dict[str, object]] = []

    @classmethod
    def from_file(
        cls,
        path: str | Path,
        options: ExportOptions | None = None,
    ) -> Decompiler:
        resolved_options = options or ExportOptions()
        abc, recovery_flags = _parse_file_with_recovery(
            Path(path),
            mode=resolved_options.normalized_mode,
            profile=resolved_options.normalized_profile,
        )
        return cls(abc, options=resolved_options, recovery_flags=recovery_flags)

    @classmethod
    def from_bytes(
        cls,
        data: bytes | bytearray | memoryview,
        options: ExportOptions | None = None,
    ) -> Decompiler:
        resolved_options = options or ExportOptions()
        abc, recovery_flags = _parse_bytes_with_recovery(
            bytes(data),
            mode=resolved_options.normalized_mode,
            profile=resolved_options.normalized_profile,
        )
        return cls(abc, options=resolved_options, recovery_flags=recovery_flags)

    @property
    def internal_config(self) -> DecompilerConfig:
        """Expose internal config mapping for inspection/documentation."""
        return self.options.to_internal_config()

    @property
    def recovery_flags(self) -> dict[str, bool]:
        return dict(self._recovery_flags)

    def iter_classes(self) -> Iterator[ClassExport]:
        config = self.internal_config
        method_errors: list[dict[str, object]] = []
        blocks = _decompile_abc_classes_layout_blocks(
            self._abc,
            style=config.style,
            int_format=config.int_format,
            owner_map=self._owner_map,
            inline_vars=config.inline_vars,
            insert_debug_comments=config.insert_debug_comments,
            debug_include_offset=config.debug_include_offset,
            debug_include_opcode=config.debug_include_opcode,
            debug_include_operands=config.debug_include_operands,
            failure_policy=self.options.normalized_failure_policy,
            method_errors=method_errors,
        )
        self._last_errors = method_errors
        for block in blocks:
            yield ClassExport(
                class_name=block.class_name,
                package_parts=tuple(block.package_parts),
                source=block.source,
                kind=block.kind,
            )

    def export_to_disk(
        self,
        output_dir: str | Path,
        *,
        clean: bool = True,
    ) -> ExportResult:
        config = self.internal_config
        method_errors: list[dict[str, object]] = []
        written = _decompile_abc_parsed_to_files(
            self._abc,
            output_dir=Path(output_dir),
            style=config.style,
            int_format=config.int_format,
            clean_output=clean,
            inline_vars=config.inline_vars,
            insert_debug_comments=config.insert_debug_comments,
            debug_include_offset=config.debug_include_offset,
            debug_include_opcode=config.debug_include_opcode,
            debug_include_operands=config.debug_include_operands,
            owner_map=self._owner_map,
            failure_policy=self.options.normalized_failure_policy,
            method_errors=method_errors,
        )
        self._last_errors = method_errors
        flags = dict(self._recovery_flags)
        flags["method_error_recovered"] = bool(method_errors)
        return ExportResult(
            output_files=list(written),
            errors=list(method_errors),
            recovery_flags=flags,
        )


__all__ = ["Decompiler", "ExportOptions", "ExportResult"]
