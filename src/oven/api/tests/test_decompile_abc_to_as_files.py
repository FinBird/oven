"""Tests for class-only export API behavior."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import pytest

import oven.api.decompiler as decompiler_api
from oven.api import Decompiler, ExportOptions, ExportResult
from oven.avm2.config import ParseMode, VerifyProfile

PROJECT_ROOT = Path(__file__).resolve().parents[4]
_TEST_ABC = PROJECT_ROOT / "fixtures" / "abc" / "Test.abc"
_ANGEL_ABC = PROJECT_ROOT / "fixtures" / "abc" / "AngelClientLibs.abc"


def _directory_fingerprint(root: Path) -> str:
    digest = hashlib.sha256()
    files = sorted(p for p in root.rglob("*.as") if p.is_file())
    for file_path in files:
        rel = file_path.relative_to(root).as_posix()
        content = file_path.read_bytes()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content)
        digest.update(b"\0")
    return digest.hexdigest()


def test_decompiler_from_file_export_to_disk_smoke(tmp_path: Path) -> None:
    decompiler = Decompiler.from_file(
        _TEST_ABC,
        options=ExportOptions(mode=ParseMode.RELAXED),
    )
    result = decompiler.export_to_disk(tmp_path / "export")
    assert isinstance(result, ExportResult)
    assert result.output_files
    assert all(path.exists() for path in result.output_files)
    assert "exception_range_sanitized" in result.recovery_flags


def test_decompiler_from_bytes_export_to_disk_smoke(tmp_path: Path) -> None:
    decompiler = Decompiler.from_bytes(
        _TEST_ABC.read_bytes(),
        options=ExportOptions(mode=ParseMode.RELAXED),
    )
    result = decompiler.export_to_disk(tmp_path / "export_bytes")
    assert result.output_files
    assert all(path.suffix == ".as" for path in result.output_files)


def test_decompiler_iter_classes_returns_structured_exports() -> None:
    decompiler = Decompiler.from_file(
        _TEST_ABC,
        options=ExportOptions(mode=ParseMode.RELAXED),
    )
    classes = list(decompiler.iter_classes())
    assert classes
    first = classes[0]
    assert first.class_name
    assert isinstance(first.package_parts, tuple)
    assert "class " in first.source or "interface " in first.source


def test_failure_policy_continue_records_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def _fake_decompile_to_files(
        abc: Any,
        output_dir: str | Path,
        *,
        style: str = "semantic",
        int_format: str = "hex",
        clean_output: bool = True,
        inline_vars: bool = True,
        insert_debug_comments: bool = False,
        debug_include_offset: bool = True,
        debug_include_opcode: bool = True,
        debug_include_operands: bool = True,
        owner_map: Any = None,
        failure_policy: str = "continue",
        error_placeholder: str = "/* decompile_error: {error_type}: {error_msg} */",
        method_errors: list[dict[str, object]] | None = None,
    ) -> list[Path]:
        del abc
        del style
        del int_format
        del clean_output
        del inline_vars
        del insert_debug_comments
        del debug_include_offset
        del debug_include_opcode
        del debug_include_operands
        del owner_map
        del error_placeholder
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        if failure_policy == "fail_fast":
            raise RuntimeError("forced fail_fast error")
        if method_errors is not None:
            method_errors.append(
                {
                    "method_index": 0,
                    "owner_name": "MockClass",
                    "owner_kind": "class",
                    "error_type": "RuntimeError",
                    "error_message": "forced continue error",
                }
            )
        out_file = output_path / "MockClass.as"
        out_file.write_text("class MockClass {}", encoding="utf-8")
        return [out_file]

    monkeypatch.setattr(
        decompiler_api,
        "_decompile_abc_parsed_to_files",
        _fake_decompile_to_files,
    )

    decompiler = Decompiler.from_file(
        _TEST_ABC,
        options=ExportOptions(
            mode=ParseMode.RELAXED,
            failure_policy="continue",
        ),
    )
    result = decompiler.export_to_disk(tmp_path / "continue")
    assert result.output_files
    assert result.errors
    assert result.recovery_flags["method_error_recovered"] is True


def test_failure_policy_fail_fast_raises(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def _fake_decompile_to_files(
        abc: Any,
        output_dir: str | Path,
        *,
        failure_policy: str = "continue",
        method_errors: list[dict[str, object]] | None = None,
        **kwargs: Any,
    ) -> list[Path]:
        del abc
        del output_dir
        del method_errors
        del kwargs
        if failure_policy == "fail_fast":
            raise RuntimeError("forced fail_fast error")
        return []

    monkeypatch.setattr(
        decompiler_api,
        "_decompile_abc_parsed_to_files",
        _fake_decompile_to_files,
    )

    decompiler = Decompiler.from_file(
        _TEST_ABC,
        options=ExportOptions(
            mode=ParseMode.RELAXED,
            failure_policy="fail_fast",
        ),
    )
    with pytest.raises(RuntimeError, match="forced fail_fast error"):
        decompiler.export_to_disk(tmp_path / "fail_fast")


@pytest.mark.fixture
@pytest.mark.parametrize("mode", [ParseMode.FAST, ParseMode.STRICT])
def test_angel_client_libs_fast_and_strict_export_with_recovery(
    mode: ParseMode,
    tmp_path: Path,
) -> None:
    decompiler = Decompiler.from_file(
        _ANGEL_ABC,
        options=ExportOptions(
            mode=mode,
            int_format="hex",
            inline_vars=True,
            failure_policy="continue",
        ),
    )
    result = decompiler.export_to_disk(tmp_path / mode.value)
    assert result.output_files
    assert "exception_range_sanitized" in result.recovery_flags


def test_profile_stack_only_produces_stable_output_on_test_fixture(
    tmp_path: Path,
) -> None:
    baseline = Decompiler.from_file(
        _TEST_ABC,
        options=ExportOptions(
            mode=ParseMode.RELAXED,
            profile=None,
            int_format="hex",
            inline_vars=True,
        ),
    ).export_to_disk(tmp_path / "baseline")

    stack_only = Decompiler.from_file(
        _TEST_ABC,
        options=ExportOptions(
            mode=ParseMode.RELAXED,
            profile=VerifyProfile.STACK_ONLY,
            int_format="hex",
            inline_vars=True,
        ),
    ).export_to_disk(tmp_path / "stack_only")

    assert baseline.output_files
    assert stack_only.output_files
    assert len(baseline.output_files) == len(stack_only.output_files)
    assert _directory_fingerprint(tmp_path / "baseline") == _directory_fingerprint(
        tmp_path / "stack_only"
    )


def test_angel_adf_cmds_type_uses_packaged_const_initializers(tmp_path: Path) -> None:
    decompiler = Decompiler.from_file(
        _ANGEL_ABC,
        options=ExportOptions(
            mode=ParseMode.RELAXED,
            int_format="hex",
            inline_vars=True,
            failure_policy="continue",
        ),
    )
    result = decompiler.export_to_disk(tmp_path / "angel")
    assert result.output_files

    target = tmp_path / "angel" / "com" / "QQ" / "angel" / "net" / "ADFCmdsType.as"
    text = target.read_text(encoding="utf-8")

    assert "package com.QQ.angel.net {" in text
    assert "public class ADFCmdsType {" in text
    assert "internal class ADFCmdsType {" not in text
    assert "__static_init__" not in text
    assert "public static const ALL_FREE_TS:Array = [T_SPIRIT_BAG_DATA];" in text
    assert re.search(
        r"public static const T_DIR_RECOMMEND_REQ:(?:int|uint) = 0x70001;",
        text,
    )
    decl_names = re.findall(r"public static const ([A-Za-z0-9_]+):", text)
    assert decl_names[:10] == [
        "ALL_FREE_TS",
        "T_DIR_RECOMMEND_REQ",
        "T_DIR_RECOMMEND_REPLY",
        "T_DIR_RANGE_REQ",
        "T_DIR_RANGE_REPLY",
        "T_LoginRoom",
        "T_GetRoleInfo",
        "T_GetRoleList",
        "T_ChangeScene",
        "T_RoadPosSub",
    ]
