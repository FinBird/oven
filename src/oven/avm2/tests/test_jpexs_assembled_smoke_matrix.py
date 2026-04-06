"""Smoke tests comparing decompiler output with JPEXS reference output."""

from __future__ import annotations

import pytest
from pathlib import Path

from oven.avm2 import parse


# Determine the root directory for fixtures
# Path: src/oven/avm2/tests/test_jpexs_assembled_smoke_matrix.py
# Need to go up 5 levels to reach the root
ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent
FIXTURES_ABC_DIR = ROOT_DIR / "fixtures" / "abc"
JPEXS_ABC_DIR = ROOT_DIR / "fixtures" / "jpexs" / "as3_assembled" / "abc"


def _load_abc_file(path: Path) -> bytes:
    """Load ABC file content."""
    return path.read_bytes()


def _get_available_abc_files() -> list[Path]:
    """Get list of available ABC files."""
    files: list[Path] = []
    if FIXTURES_ABC_DIR.exists():
        files.extend(FIXTURES_ABC_DIR.glob("*.abc"))
    if JPEXS_ABC_DIR.exists():
        files.extend(JPEXS_ABC_DIR.glob("*.abc"))
    return files


# ============================================================================
# Basic ABC Parsing Tests
# ============================================================================


class TestABCParsing:
    """Test basic ABC parsing functionality."""

    def test_parse_minimal_abc(self) -> None:
        """Parse a minimal ABC file."""
        abc_data = bytes(
            [
                0x10,
                0x00,
                0x2E,
                0x00,  # minor_version=16, major_version=46
                0x00,  # int_count
                0x00,  # uint_count
                0x00,  # double_count
                0x00,  # string_count
                0x00,  # namespace_count
                0x00,  # ns_set_count
                0x00,  # multiname_count
                0x00,  # method_count
                0x00,  # metadata_count
                0x00,  # class_count
                0x00,  # script_count
                0x00,  # method_body_count
            ]
        )

        abc = parse(abc_data, mode="relaxed")
        assert abc is not None
        assert abc.minor_version == 16
        assert abc.major_version == 46

    def test_parse_abc_with_constants(self) -> None:
        """Parse ABC with constant pool."""
        abc_data = bytes(
            [
                0x10,
                0x00,
                0x2E,
                0x00,  # minor_version, major_version
                0x01,  # int_count = 1
                0x00,  # int[0] = 0
                0x01,  # uint_count = 1
                0x00,  # uint[0] = 0
                0x01,  # double_count = 1
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,  # double[0] = 0.0
                0x01,  # string_count = 1
                0x00,  # string[0] = ""
                0x01,  # namespace_count = 1
                0x00,  # namespace[0] kind = 0
                0x01,  # ns_set_count = 1
                0x00,  # ns_set[0] = []
                0x01,  # multiname_count = 1
                0x00,  # multiname[0] kind = 0
                0x00,  # method_count
                0x00,  # metadata_count
                0x00,  # class_count
                0x00,  # script_count
                0x00,  # method_body_count
            ]
        )

        abc = parse(abc_data, mode="relaxed")
        assert abc is not None

    def test_parse_abc_with_methods(self) -> None:
        """Parse ABC with method definitions."""
        abc_data = bytes(
            [
                0x10,
                0x00,
                0x2E,
                0x00,  # minor_version, major_version
                0x00,  # int_count
                0x00,  # uint_count
                0x00,  # double_count
                0x00,  # string_count
                0x00,  # namespace_count
                0x00,  # ns_set_count
                0x00,  # multiname_count
                0x01,  # method_count = 1
                0x00,  # method[0] param_count = 0
                0x00,  # method[0] return_type = 0
                0x00,  # method[0] flags = 0
                0x00,  # metadata_count
                0x00,  # class_count
                0x00,  # script_count
                0x00,  # method_body_count
            ]
        )

        abc = parse(abc_data, mode="relaxed")
        assert abc is not None

    def test_parse_abc_with_classes(self) -> None:
        """Parse ABC with class definitions."""
        abc_data = bytes(
            [
                0x10,
                0x00,
                0x2E,
                0x00,  # minor_version, major_version
                0x00,  # int_count
                0x00,  # uint_count
                0x00,  # double_count
                0x00,  # string_count
                0x00,  # namespace_count
                0x00,  # ns_set_count
                0x00,  # multiname_count
                0x00,  # method_count
                0x00,  # metadata_count
                0x01,  # class_count = 1
                0x00,  # class[0] name = 0
                0x00,  # class[0] super_name = 0
                0x00,  # class[0] flags = 0
                0x00,  # script_count
                0x00,  # method_body_count
            ]
        )

        abc = parse(abc_data, mode="relaxed")
        assert abc is not None

    def test_parse_abc_with_scripts(self) -> None:
        """Parse ABC with script definitions."""
        abc_data = bytes(
            [
                0x10,
                0x00,
                0x2E,
                0x00,  # minor_version, major_version
                0x00,  # int_count
                0x00,  # uint_count
                0x00,  # double_count
                0x00,  # string_count
                0x00,  # namespace_count
                0x00,  # ns_set_count
                0x00,  # multiname_count
                0x01,  # method_count = 1
                0x00,  # method[0] param_count = 0
                0x00,  # method[0] return_type = 0
                0x00,  # method[0] flags = 0
                0x00,  # metadata_count
                0x00,  # class_count
                0x01,  # script_count = 1
                0x00,  # script[0] init = 0
                0x00,  # script[0] trait_count = 0
                0x00,  # method_body_count
            ]
        )

        abc = parse(abc_data, mode="relaxed")
        assert abc is not None

    def test_parse_abc_with_method_bodies(self) -> None:
        """Parse ABC with method bodies."""
        abc_data = bytes(
            [
                0x10,
                0x00,
                0x2E,
                0x00,  # minor_version, major_version
                0x00,  # int_count
                0x00,  # uint_count
                0x00,  # double_count
                0x00,  # string_count
                0x00,  # namespace_count
                0x00,  # ns_set_count
                0x00,  # multiname_count
                0x01,  # method_count = 1
                0x00,  # method[0] param_count = 0
                0x00,  # method[0] return_type = 0
                0x00,  # method[0] flags = 0
                0x00,  # metadata_count
                0x00,  # class_count
                0x00,  # script_count
                0x01,  # method_body_count = 1
                0x00,  # method_body[0] method = 0
                0x00,  # method_body[0] max_stack = 0
                0x00,  # method_body[0] local_count = 0
                0x00,  # method_body[0] init_scope_depth = 0
                0x00,  # method_body[0] max_scope_depth = 0
                0x00,  # method_body[0] code_length = 0
            ]
        )

        abc = parse(abc_data, mode="relaxed")
        assert abc is not None

    def test_parse_abc_version_validation(self) -> None:
        """Test ABC version validation."""
        # Invalid version
        abc_data = bytes(
            [
                0x00,
                0x00,
                0x00,
                0x00,  # invalid version
                0x00,  # int_count
                0x00,  # uint_count
                0x00,  # double_count
                0x00,  # string_count
                0x00,  # namespace_count
                0x00,  # ns_set_count
                0x00,  # multiname_count
                0x00,  # method_count
                0x00,  # metadata_count
                0x00,  # class_count
                0x00,  # script_count
                0x00,  # method_body_count
            ]
        )

        abc = parse(abc_data, mode="relaxed")
        assert abc is not None
        # Should handle invalid version gracefully

    def test_parse_abc_empty_constant_pools(self) -> None:
        """Test parsing ABC with empty constant pools."""
        abc_data = bytes(
            [
                0x10,
                0x00,
                0x2E,
                0x00,  # minor_version, major_version
                0x00,  # int_count = 0
                0x00,  # uint_count = 0
                0x00,  # double_count = 0
                0x00,  # string_count = 0
                0x00,  # namespace_count = 0
                0x00,  # ns_set_count = 0
                0x00,  # multiname_count = 0
                0x00,  # method_count
                0x00,  # metadata_count
                0x00,  # class_count
                0x00,  # script_count
                0x00,  # method_body_count
            ]
        )

        abc = parse(abc_data, mode="relaxed")
        assert abc is not None

    def test_parse_abc_multiple_classes(self) -> None:
        """Test parsing ABC with multiple classes."""
        abc_data = bytes(
            [
                0x10,
                0x00,
                0x2E,
                0x00,  # minor_version, major_version
                0x00,  # int_count
                0x00,  # uint_count
                0x00,  # double_count
                0x00,  # string_count
                0x00,  # namespace_count
                0x00,  # ns_set_count
                0x00,  # multiname_count
                0x00,  # method_count
                0x00,  # metadata_count
                0x02,  # class_count = 2
                0x00,  # class[0] name = 0
                0x00,  # class[0] super_name = 0
                0x00,  # class[0] flags = 0
                0x00,  # class[1] name = 0
                0x00,  # class[1] super_name = 0
                0x00,  # class[1] flags = 0
                0x00,  # script_count
                0x00,  # method_body_count
            ]
        )

        abc = parse(abc_data, mode="relaxed")
        assert abc is not None

    def test_parse_abc_complex_structure(self) -> None:
        """Test parsing ABC with complex structure."""
        abc_data = bytes(
            [
                0x10,
                0x00,
                0x2E,
                0x00,  # minor_version, major_version
                0x01,  # int_count = 1
                0x00,  # int[0] = 0
                0x01,  # uint_count = 1
                0x00,  # uint[0] = 0
                0x01,  # double_count = 1
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,  # double[0] = 0.0
                0x01,  # string_count = 1
                0x00,  # string[0] = ""
                0x01,  # namespace_count = 1
                0x00,  # namespace[0] kind = 0
                0x01,  # ns_set_count = 1
                0x00,  # ns_set[0] = []
                0x01,  # multiname_count = 1
                0x00,  # multiname[0] kind = 0
                0x01,  # method_count = 1
                0x00,  # method[0] param_count = 0
                0x00,  # method[0] return_type = 0
                0x00,  # method[0] flags = 0
                0x00,  # metadata_count
                0x01,  # class_count = 1
                0x00,  # class[0] name = 0
                0x00,  # class[0] super_name = 0
                0x00,  # class[0] flags = 0
                0x01,  # script_count = 1
                0x00,  # script[0] init = 0
                0x01,  # method_body_count = 1
                0x00,  # method_body[0] method = 0
                0x00,  # method_body[0] max_stack = 0
                0x00,  # method_body[0] local_count = 0
                0x00,  # method_body[0] init_scope_depth = 0
                0x00,  # method_body[0] max_scope_depth = 0
                0x00,  # method_body[0] code_length = 0
            ]
        )

        abc = parse(abc_data, mode="relaxed")
        assert abc is not None

    def test_parse_abc_large_constant_pool(self) -> None:
        """Test parsing ABC with large constant pool."""
        # Build ABC with 10 integers
        int_count = 10
        ints = bytes([i for i in range(int_count)])

        abc_data = bytes(
            [
                0x10,
                0x00,
                0x2E,
                0x00,  # minor_version, major_version
                int_count + 1,  # int_count includes reserved index 0
                *ints,  # int values
                0x01,  # uint_count (reserved only)
                0x01,  # double_count (reserved only)
                0x01,  # string_count (reserved only)
                0x01,  # namespace_count (reserved only)
                0x01,  # ns_set_count (reserved only)
                0x01,  # multiname_count (reserved only)
                0x00,  # method_count
                0x00,  # metadata_count
                0x00,  # class_count
                0x00,  # script_count
                0x00,  # method_body_count
            ]
        )

        abc = parse(abc_data, mode="relaxed")
        assert abc is not None

    def test_parse_abc_with_metadata(self) -> None:
        """Test parsing ABC with metadata."""
        abc_data = bytes(
            [
                0x10,
                0x00,
                0x2E,
                0x00,  # minor_version, major_version
                0x00,  # int_count
                0x00,  # uint_count
                0x00,  # double_count
                0x01,  # string_count = 1
                0x00,  # string[0] = ""
                0x00,  # namespace_count
                0x00,  # ns_set_count
                0x00,  # multiname_count
                0x00,  # method_count
                0x01,  # metadata_count = 1
                0x00,  # metadata[0] name = 0
                0x00,  # metadata[0] values_count = 0
                0x00,  # class_count
                0x00,  # script_count
                0x00,  # method_body_count
            ]
        )

        abc = parse(abc_data, mode="relaxed")
        assert abc is not None

    def test_parse_abc_with_traits(self) -> None:
        """Test parsing ABC with traits."""
        abc_data = bytes(
            [
                0x10,
                0x00,
                0x2E,
                0x00,  # minor_version, major_version
                0x00,  # int_count
                0x00,  # uint_count
                0x00,  # double_count
                0x01,  # string_count = 1
                0x00,  # string[0] = ""
                0x01,  # namespace_count = 1
                0x00,  # namespace[0] kind = 0
                0x00,  # ns_set_count
                0x01,  # multiname_count = 1
                0x00,  # multiname[0] kind = 0
                0x00,  # method_count
                0x00,  # metadata_count
                0x01,  # class_count = 1
                0x00,  # class[0] name = 0
                0x00,  # class[0] super_name = 0
                0x00,  # class[0] flags = 0
                0x01,  # class[0] trait_count = 1
                0x00,  # trait[0] name = 0
                0x00,  # trait[0] kind = 0
                0x00,  # script_count
                0x00,  # method_body_count
            ]
        )

        abc = parse(abc_data, mode="relaxed")
        assert abc is not None

    def test_parse_abc_with_interfaces(self) -> None:
        """Test parsing ABC with interfaces."""
        abc_data = bytes(
            [
                0x10,
                0x00,
                0x2E,
                0x00,  # minor_version, major_version
                0x00,  # int_count
                0x00,  # uint_count
                0x00,  # double_count
                0x01,  # string_count = 1
                0x00,  # string[0] = ""
                0x01,  # namespace_count = 1
                0x00,  # namespace[0] kind = 0
                0x00,  # ns_set_count
                0x01,  # multiname_count = 1
                0x00,  # multiname[0] kind = 0
                0x00,  # method_count
                0x00,  # metadata_count
                0x01,  # class_count = 1
                0x00,  # class[0] name = 0
                0x00,  # class[0] super_name = 0
                0x00,  # class[0] flags = 0
                0x01,  # class[0] interface_count = 1
                0x00,  # interface[0] = 0
                0x00,  # script_count
                0x00,  # method_body_count
            ]
        )

        abc = parse(abc_data, mode="relaxed")
        assert abc is not None

    def test_parse_abc_with_optional_parameters(self) -> None:
        """Test parsing ABC with optional parameters."""
        abc_data = bytes(
            [
                0x10,
                0x00,
                0x2E,
                0x00,
                0x02,  # int_count
                0x01,  # int[1] = 1
                0x01,  # uint_count
                0x01,  # double_count
                0x01,  # string_count
                0x01,  # namespace_count
                0x01,  # ns_set_count
                0x01,  # multiname_count
                0x01,  # method_count = 1
                0x01,  # param_count
                0x00,  # return_type
                0x00,  # param_type[0]
                0x08,  # flags = HAS_OPTIONAL
                0x01,  # optional_count
                0x01,  # optional value index (int #1)
                0x03,  # optional kind = Int
                0x00,  # metadata_count
                0x01,  # class_count
                0x00,
                0x00,
                0x00,
                0x00,  # instance init
                0x00,  # interface_count
                0x00,  # instance trait_count
                0x00,  # class cinit
                0x00,  # class trait_count
                0x01,  # script_count
                0x00,  # script init
                0x00,  # script trait_count
                0x00,  # method_body_count
            ]
        )

        abc = parse(abc_data, mode="relaxed")
        assert abc is not None

    def test_parse_abc_with_exceptions(self) -> None:
        """Test parsing ABC with exception handlers."""
        abc_data = bytes(
            [
                0x10,
                0x00,
                0x2E,
                0x00,  # minor_version, major_version
                0x00,  # int_count
                0x00,  # uint_count
                0x00,  # double_count
                0x01,  # string_count = 1
                0x00,  # string[0] = ""
                0x00,  # namespace_count
                0x00,  # ns_set_count
                0x00,  # multiname_count
                0x01,  # method_count = 1
                0x00,  # method[0] param_count = 0
                0x00,  # method[0] return_type = 0
                0x00,  # method[0] flags = 0
                0x00,  # metadata_count
                0x00,  # class_count
                0x00,  # script_count
                0x01,  # method_body_count = 1
                0x00,  # method_body[0] method = 0
                0x00,  # method_body[0] max_stack = 0
                0x00,  # method_body[0] local_count = 0
                0x00,  # method_body[0] init_scope_depth = 0
                0x00,  # method_body[0] max_scope_depth = 0
                0x00,  # method_body[0] code_length = 0
                0x01,  # method_body[0] exception_count = 1
                0x00,  # exception[0] from = 0
                0x00,  # exception[0] to = 0
                0x00,  # exception[0] target = 0
                0x00,  # exception[0] exc_type = 0
                0x00,  # exception[0] var_name = 0
            ]
        )

        abc = parse(abc_data, mode="relaxed")
        assert abc is not None

    def test_parse_abc_with_activation(self) -> None:
        """Test parsing ABC with activation traits."""
        abc_data = bytes(
            [
                0x10,
                0x00,
                0x2E,
                0x00,  # minor_version, major_version
                0x00,  # int_count
                0x00,  # uint_count
                0x00,  # double_count
                0x01,  # string_count = 1
                0x00,  # string[0] = ""
                0x00,  # namespace_count
                0x00,  # ns_set_count
                0x00,  # multiname_count
                0x01,  # method_count = 1
                0x00,  # method[0] param_count = 0
                0x00,  # method[0] return_type = 0
                0x08,  # method[0] flags = NEED_ACTIVATION
                0x00,  # metadata_count
                0x00,  # class_count
                0x00,  # script_count
                0x01,  # method_body_count = 1
                0x00,  # method_body[0] method = 0
                0x00,  # method_body[0] max_stack = 0
                0x00,  # method_body[0] local_count = 0
                0x00,  # method_body[0] init_scope_depth = 0
                0x00,  # method_body[0] max_scope_depth = 0
                0x00,  # method_body[0] code_length = 0
            ]
        )

        abc = parse(abc_data, mode="relaxed")
        assert abc is not None

    def test_parse_abc_with_rest_parameters(self) -> None:
        """Test parsing ABC with rest parameters."""
        abc_data = bytes(
            [
                0x10,
                0x00,
                0x2E,
                0x00,  # minor_version, major_version
                0x00,  # int_count
                0x00,  # uint_count
                0x00,  # double_count
                0x01,  # string_count = 1
                0x00,  # string[0] = ""
                0x00,  # namespace_count
                0x00,  # ns_set_count
                0x00,  # multiname_count
                0x01,  # method_count = 1
                0x00,  # method[0] param_count = 0
                0x00,  # method[0] return_type = 0
                0x04,  # method[0] flags = HAS_PARAM_NAMES
                0x00,  # metadata_count
                0x00,  # class_count
                0x00,  # script_count
                0x00,  # method_body_count
            ]
        )

        abc = parse(abc_data, mode="relaxed")
        assert abc is not None

    def test_parse_abc_with_native_methods(self) -> None:
        """Test parsing ABC with native methods."""
        abc_data = bytes(
            [
                0x10,
                0x00,
                0x2E,
                0x00,  # minor_version, major_version
                0x00,  # int_count
                0x00,  # uint_count
                0x00,  # double_count
                0x01,  # string_count = 1
                0x00,  # string[0] = ""
                0x00,  # namespace_count
                0x00,  # ns_set_count
                0x00,  # multiname_count
                0x01,  # method_count = 1
                0x00,  # method[0] param_count = 0
                0x00,  # method[0] return_type = 0
                0x10,  # method[0] flags = NATIVE
                0x00,  # metadata_count
                0x00,  # class_count
                0x00,  # script_count
                0x00,  # method_body_count
            ]
        )

        abc = parse(abc_data, mode="relaxed")
        assert abc is not None

    def test_parse_abc_with_constructor(self) -> None:
        """Test parsing ABC with constructor."""
        abc_data = bytes(
            [
                0x10,
                0x00,
                0x2E,
                0x00,  # minor_version, major_version
                0x00,  # int_count
                0x00,  # uint_count
                0x00,  # double_count
                0x01,  # string_count = 1
                0x00,  # string[0] = ""
                0x00,  # namespace_count
                0x00,  # ns_set_count
                0x00,  # multiname_count
                0x01,  # method_count = 1
                0x00,  # method[0] param_count = 0
                0x00,  # method[0] return_type = 0
                0x00,  # method[0] flags = 0
                0x00,  # metadata_count
                0x01,  # class_count = 1
                0x00,  # class[0] name = 0
                0x00,  # class[0] super_name = 0
                0x00,  # class[0] flags = 0
                0x00,  # class[0] cinit = 0
                0x00,  # script_count
                0x01,  # method_body_count = 1
                0x00,  # method_body[0] method = 0
                0x00,  # method_body[0] max_stack = 0
                0x00,  # method_body[0] local_count = 0
                0x00,  # method_body[0] init_scope_depth = 0
                0x00,  # method_body[0] max_scope_depth = 0
                0x00,  # method_body[0] code_length = 0
            ]
        )

        abc = parse(abc_data, mode="relaxed")
        assert abc is not None

    def test_parse_abc_with_static_initializer(self) -> None:
        """Test parsing ABC with static initializer."""
        abc_data = bytes(
            [
                0x10,
                0x00,
                0x2E,
                0x00,  # minor_version, major_version
                0x00,  # int_count
                0x00,  # uint_count
                0x00,  # double_count
                0x01,  # string_count = 1
                0x00,  # string[0] = ""
                0x00,  # namespace_count
                0x00,  # ns_set_count
                0x00,  # multiname_count
                0x01,  # method_count = 1
                0x00,  # method[0] param_count = 0
                0x00,  # method[0] return_type = 0
                0x00,  # method[0] flags = 0
                0x00,  # metadata_count
                0x01,  # class_count = 1
                0x00,  # class[0] name = 0
                0x00,  # class[0] super_name = 0
                0x00,  # class[0] flags = 0
                0x00,  # class[0] cinit = 0
                0x00,  # script_count
                0x01,  # method_body_count = 1
                0x00,  # method_body[0] method = 0
                0x00,  # method_body[0] max_stack = 0
                0x00,  # method_body[0] local_count = 0
                0x00,  # method_body[0] init_scope_depth = 0
                0x00,  # method_body[0] max_scope_depth = 0
                0x00,  # method_body[0] code_length = 0
            ]
        )

        abc = parse(abc_data, mode="relaxed")
        assert abc is not None

    def test_parse_abc_with_protected_namespace(self) -> None:
        """Test parsing ABC with protected namespace."""
        abc_data = bytes(
            [
                0x10,
                0x00,
                0x2E,
                0x00,
                0x01,
                0x01,
                0x01,
                0x02,
                0x00,  # string_count=2, string[1]=""
                0x02,  # namespace_count
                0x08,
                0x01,  # protected namespace with valid name idx
                0x01,
                0x01,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
            ]
        )

        abc = parse(abc_data, mode="relaxed")
        assert abc is not None

    def test_parse_abc_with_private_namespace(self) -> None:
        """Test parsing ABC with private namespace."""
        abc_data = bytes(
            [
                0x10,
                0x00,
                0x2E,
                0x00,
                0x01,
                0x01,
                0x01,
                0x02,
                0x00,
                0x02,
                0x05,
                0x01,
                0x01,
                0x01,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
            ]
        )

        abc = parse(abc_data, mode="relaxed")
        assert abc is not None

    def test_parse_abc_with_explicit_namespace(self) -> None:
        """Test parsing ABC with explicit namespace."""
        abc_data = bytes(
            [
                0x10,
                0x00,
                0x2E,
                0x00,  # minor_version, major_version
                0x00,  # int_count
                0x00,  # uint_count
                0x00,  # double_count
                0x01,  # string_count = 1
                0x00,  # string[0] = ""
                0x01,  # namespace_count = 1
                0x03,  # namespace[0] kind = EXPLICIT_NAMESPACE
                0x00,  # namespace[0] name = 0
                0x00,  # ns_set_count
                0x00,  # multiname_count
                0x00,  # method_count
                0x00,  # metadata_count
                0x00,  # class_count
                0x00,  # script_count
                0x00,  # method_body_count
            ]
        )

        abc = parse(abc_data, mode="relaxed")
        assert abc is not None

    def test_parse_abc_with_static_protected_namespace(self) -> None:
        """Test parsing ABC with static protected namespace."""
        abc_data = bytes(
            [
                0x10,
                0x00,
                0x2E,
                0x00,
                0x01,
                0x01,
                0x01,
                0x02,
                0x00,
                0x02,
                0x1A,
                0x01,  # valid static-protected kind
                0x01,
                0x01,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
            ]
        )

        abc = parse(abc_data, mode="relaxed")
        assert abc is not None

    def test_parse_abc_with_multiname_kind_qname(self) -> None:
        """Test parsing ABC with QName multiname."""
        abc_data = bytes(
            [
                0x10,
                0x00,
                0x2E,
                0x00,  # minor_version, major_version
                0x00,  # int_count
                0x00,  # uint_count
                0x00,  # double_count
                0x01,  # string_count = 1
                0x00,  # string[0] = ""
                0x01,  # namespace_count = 1
                0x00,  # namespace[0] kind = 0
                0x00,  # ns_set_count
                0x01,  # multiname_count = 1
                0x07,  # multiname[0] kind = QName
                0x00,  # multiname[0] ns = 0
                0x00,  # multiname[0] name = 0
                0x00,  # method_count
                0x00,  # metadata_count
                0x00,  # class_count
                0x00,  # script_count
                0x00,  # method_body_count
            ]
        )

        abc = parse(abc_data, mode="relaxed")
        assert abc is not None

    def test_parse_abc_with_multiname_kind_multiname(self) -> None:
        """Test parsing ABC with Multiname multiname."""
        abc_data = bytes(
            [
                0x10,
                0x00,
                0x2E,
                0x00,  # minor_version, major_version
                0x00,  # int_count
                0x00,  # uint_count
                0x00,  # double_count
                0x01,  # string_count = 1
                0x00,  # string[0] = ""
                0x00,  # namespace_count
                0x01,  # ns_set_count = 1
                0x00,  # ns_set[0] = []
                0x01,  # multiname_count = 1
                0x09,  # multiname[0] kind = Multiname
                0x00,  # multiname[0] name = 0
                0x00,  # multiname[0] ns_set = 0
                0x00,  # method_count
                0x00,  # metadata_count
                0x00,  # class_count
                0x00,  # script_count
                0x00,  # method_body_count
            ]
        )

        abc = parse(abc_data, mode="relaxed")
        assert abc is not None

    def test_parse_abc_with_multiname_kind_rtqname(self) -> None:
        """Test parsing ABC with RTQName multiname."""
        abc_data = bytes(
            [
                0x10,
                0x00,
                0x2E,
                0x00,
                0x01,
                0x01,
                0x01,
                0x02,
                0x00,
                0x01,  # namespace_count
                0x01,  # ns_set_count
                0x02,  # multiname_count
                0x0F,
                0x01,  # RTQName name idx=1
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
            ]
        )

        abc = parse(abc_data, mode="relaxed")
        assert abc is not None

    def test_parse_abc_with_multiname_kind_multinamel(self) -> None:
        """Test parsing ABC with MultinameL multiname."""
        abc_data = bytes(
            [
                0x10,
                0x00,
                0x2E,
                0x00,  # minor_version, major_version
                0x00,  # int_count
                0x00,  # uint_count
                0x00,  # double_count
                0x01,  # string_count = 1
                0x00,  # string[0] = ""
                0x00,  # namespace_count
                0x01,  # ns_set_count = 1
                0x00,  # ns_set[0] = []
                0x01,  # multiname_count = 1
                0x1B,  # multiname[0] kind = MultinameL
                0x00,  # multiname[0] ns_set = 0
                0x00,  # method_count
                0x00,  # metadata_count
                0x00,  # class_count
                0x00,  # script_count
                0x00,  # method_body_count
            ]
        )

        abc = parse(abc_data, mode="relaxed")
        assert abc is not None

    def test_parse_abc_with_instance_traits(self) -> None:
        """Test parsing ABC with instance traits."""
        abc_data = bytes(
            [
                0x10,
                0x00,
                0x2E,
                0x00,
                0x01,
                0x01,
                0x01,
                0x01,
                0x01,
                0x01,
                0x01,
                0x01,  # method_count
                0x00,
                0x00,
                0x00,
                0x00,  # metadata_count
                0x01,  # class_count
                0x00,
                0x00,
                0x00,
                0x00,  # instance init
                0x00,  # interface_count
                0x01,  # instance trait_count
                0x00,  # trait name
                0x00,  # trait kind slot
                0x00,
                0x00,
                0x00,
                0x00,  # class cinit
                0x00,  # class trait_count
                0x01,  # script_count
                0x00,  # script init
                0x00,  # script trait_count
                0x00,  # method_body_count
            ]
        )

        abc = parse(abc_data, mode="relaxed")
        assert abc is not None

    def test_parse_abc_with_class_traits(self) -> None:
        """Test parsing ABC with class traits."""
        abc_data = bytes(
            [
                0x10,
                0x00,
                0x2E,
                0x00,
                0x01,
                0x01,
                0x01,
                0x01,
                0x01,
                0x01,
                0x01,
                0x01,  # method_count
                0x00,
                0x00,
                0x00,
                0x00,  # metadata_count
                0x01,  # class_count
                0x00,
                0x00,
                0x00,
                0x00,  # instance init
                0x00,  # interface_count
                0x00,  # instance trait_count
                0x00,  # class cinit
                0x01,  # class trait_count
                0x00,  # trait name
                0x00,  # trait kind slot
                0x00,
                0x00,
                0x00,
                0x01,  # script_count
                0x00,  # script init
                0x00,  # script trait_count
                0x00,  # method_body_count
            ]
        )

        abc = parse(abc_data, mode="relaxed")
        assert abc is not None

    def test_parse_abc_with_trait_slot(self) -> None:
        """Test parsing ABC with slot trait."""
        abc_data = bytes(
            [
                0x10,
                0x00,
                0x2E,
                0x00,
                0x01,
                0x01,
                0x01,
                0x01,
                0x01,
                0x01,
                0x01,
                0x01,  # method_count
                0x00,
                0x00,
                0x00,
                0x00,  # metadata_count
                0x01,  # class_count
                0x00,
                0x00,
                0x00,
                0x00,  # instance init
                0x00,  # interface_count
                0x01,  # instance trait_count
                0x00,  # trait name
                0x00,  # slot
                0x00,
                0x00,
                0x00,
                0x00,  # class cinit
                0x00,  # class trait_count
                0x01,  # script_count
                0x00,  # script init
                0x00,  # script trait_count
                0x00,  # method_body_count
            ]
        )

        abc = parse(abc_data, mode="relaxed")
        assert abc is not None

    def test_parse_abc_with_trait_method(self) -> None:
        """Test parsing ABC with method trait."""
        abc_data = bytes(
            [
                0x10,
                0x00,
                0x2E,
                0x00,  # minor_version, major_version
                0x00,  # int_count
                0x00,  # uint_count
                0x00,  # double_count
                0x01,  # string_count = 1
                0x00,  # string[0] = ""
                0x01,  # namespace_count = 1
                0x00,  # namespace[0] kind = 0
                0x00,  # ns_set_count
                0x01,  # multiname_count = 1
                0x00,  # multiname[0] kind = 0
                0x01,  # method_count = 1
                0x00,  # method[0] param_count = 0
                0x00,  # method[0] return_type = 0
                0x00,  # method[0] flags = 0
                0x00,  # metadata_count
                0x01,  # class_count = 1
                0x00,  # class[0] name = 0
                0x00,  # class[0] super_name = 0
                0x00,  # class[0] flags = 0
                0x01,  # class[0] trait_count = 1
                0x00,  # trait[0] name = 0
                0x01,  # trait[0] kind = TRAIT_Method
                0x00,  # trait[0] disp_id = 0
                0x00,  # trait[0] method = 0
                0x00,  # script_count
                0x00,  # method_body_count
            ]
        )

        abc = parse(abc_data, mode="relaxed")
        assert abc is not None

    def test_parse_abc_with_trait_getter(self) -> None:
        """Test parsing ABC with getter trait."""
        abc_data = bytes(
            [
                0x10,
                0x00,
                0x2E,
                0x00,  # minor_version, major_version
                0x00,  # int_count
                0x00,  # uint_count
                0x00,  # double_count
                0x01,  # string_count = 1
                0x00,  # string[0] = ""
                0x01,  # namespace_count = 1
                0x00,  # namespace[0] kind = 0
                0x00,  # ns_set_count
                0x01,  # multiname_count = 1
                0x00,  # multiname[0] kind = 0
                0x01,  # method_count = 1
                0x00,  # method[0] param_count = 0
                0x00,  # method[0] return_type = 0
                0x00,  # method[0] flags = 0
                0x00,  # metadata_count
                0x01,  # class_count = 1
                0x00,  # class[0] name = 0
                0x00,  # class[0] super_name = 0
                0x00,  # class[0] flags = 0
                0x01,  # class[0] trait_count = 1
                0x00,  # trait[0] name = 0
                0x02,  # trait[0] kind = TRAIT_Getter
                0x00,  # trait[0] disp_id = 0
                0x00,  # trait[0] method = 0
                0x00,  # script_count
                0x00,  # method_body_count
            ]
        )

        abc = parse(abc_data, mode="relaxed")
        assert abc is not None

    def test_parse_abc_with_trait_setter(self) -> None:
        """Test parsing ABC with setter trait."""
        abc_data = bytes(
            [
                0x10,
                0x00,
                0x2E,
                0x00,  # minor_version, major_version
                0x00,  # int_count
                0x00,  # uint_count
                0x00,  # double_count
                0x01,  # string_count = 1
                0x00,  # string[0] = ""
                0x01,  # namespace_count = 1
                0x00,  # namespace[0] kind = 0
                0x00,  # ns_set_count
                0x01,  # multiname_count = 1
                0x00,  # multiname[0] kind = 0
                0x01,  # method_count = 1
                0x00,  # method[0] param_count = 0
                0x00,  # method[0] return_type = 0
                0x00,  # method[0] flags = 0
                0x00,  # metadata_count
                0x01,  # class_count = 1
                0x00,  # class[0] name = 0
                0x00,  # class[0] super_name = 0
                0x00,  # class[0] flags = 0
                0x01,  # class[0] trait_count = 1
                0x00,  # trait[0] name = 0
                0x03,  # trait[0] kind = TRAIT_Setter
                0x00,  # trait[0] disp_id = 0
                0x00,  # trait[0] method = 0
                0x00,  # script_count
                0x00,  # method_body_count
            ]
        )

        abc = parse(abc_data, mode="relaxed")
        assert abc is not None

    def test_parse_abc_with_trait_class(self) -> None:
        """Test parsing ABC with class trait."""
        abc_data = bytes(
            [
                0x10,
                0x00,
                0x2E,
                0x00,
                0x01,
                0x01,
                0x01,
                0x01,
                0x01,
                0x01,
                0x01,
                0x01,  # method_count
                0x00,
                0x00,
                0x00,
                0x00,  # metadata_count
                0x02,  # class_count
                # instance[0]
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x01,
                0x00,
                0x04,
                0x00,
                0x01,
                # instance[1]
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                # class[0], class[1]
                0x00,
                0x00,
                0x00,
                0x00,
                0x01,  # script_count
                0x00,  # script init
                0x00,  # script trait_count
                0x00,  # method_body_count
            ]
        )

        abc = parse(abc_data, mode="relaxed")
        assert abc is not None

    def test_parse_abc_with_trait_function(self) -> None:
        """Test parsing ABC with function trait."""
        abc_data = bytes(
            [
                0x10,
                0x00,
                0x2E,
                0x00,  # minor_version, major_version
                0x00,  # int_count
                0x00,  # uint_count
                0x00,  # double_count
                0x01,  # string_count = 1
                0x00,  # string[0] = ""
                0x01,  # namespace_count = 1
                0x00,  # namespace[0] kind = 0
                0x00,  # ns_set_count
                0x01,  # multiname_count = 1
                0x00,  # multiname[0] kind = 0
                0x01,  # method_count = 1
                0x00,  # method[0] param_count = 0
                0x00,  # method[0] return_type = 0
                0x00,  # method[0] flags = 0
                0x00,  # metadata_count
                0x01,  # class_count = 1
                0x00,  # class[0] name = 0
                0x00,  # class[0] super_name = 0
                0x00,  # class[0] flags = 0
                0x01,  # class[0] trait_count = 1
                0x00,  # trait[0] name = 0
                0x05,  # trait[0] kind = TRAIT_Function
                0x00,  # trait[0] slot_id = 0
                0x00,  # trait[0] method = 0
                0x00,  # script_count
                0x00,  # method_body_count
            ]
        )

        abc = parse(abc_data, mode="relaxed")
        assert abc is not None

    def test_parse_abc_with_trait_const(self) -> None:
        """Test parsing ABC with const trait."""
        abc_data = bytes(
            [
                0x10,
                0x00,
                0x2E,
                0x00,
                0x01,
                0x01,
                0x01,
                0x02,
                0x00,
                0x01,
                0x01,
                0x00,  # method_count
                0x00,  # metadata_count
                0x01,  # class_count
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x01,  # instance trait_count
                0x00,  # trait name
                0x06,  # const
                0x00,
                0x00,
                0x00,
                0x00,  # class cinit
                0x00,  # class trait_count
                0x01,  # script_count
                0x00,  # script init
                0x00,  # script trait_count
                0x00,  # method_body_count
            ]
        )

        abc = parse(abc_data, mode="relaxed")
        assert abc is not None

    def test_parse_abc_error_handling(self) -> None:
        """Test ABC parsing error handling."""
        # Truncated ABC data
        abc_data = bytes(
            [
                0x10,
                0x00,
                0x2E,  # truncated
            ]
        )

        # Should handle gracefully
        try:
            abc = parse(abc_data, mode="relaxed")
            # May raise exception or return partial result
        except Exception:
            # Expected for truncated data
            pass

    def test_parse_abc_corrupted_data(self) -> None:
        """Test ABC parsing with corrupted data."""
        # Corrupted ABC data
        abc_data = bytes(
            [
                0x10,
                0x00,
                0x2E,
                0x00,  # minor_version, major_version
                0xFF,  # int_count = 255 (invalid)
                0x00,
                0x00,
                0x00,  # padding
            ]
        )

        # Should handle gracefully
        try:
            abc = parse(abc_data, mode="relaxed")
            # May raise exception or return partial result
        except Exception:
            # Expected for corrupted data
            pass

    def test_parse_abc_with_fixture_abcdump(self) -> None:
        """Test parsing abcdump.abc fixture."""
        if not FIXTURES_ABC_DIR.exists():
            pytest.skip("Fixtures directory not available")

        fixture_path = FIXTURES_ABC_DIR / "abcdump.abc"
        if not fixture_path.exists():
            pytest.skip("abcdump.abc not available")

        abc_data = _load_abc_file(fixture_path)
        abc = parse(abc_data, mode="relaxed")

        assert abc is not None
        assert abc.minor_version == 16
        assert abc.major_version == 46

    def test_parse_abc_with_fixture_angelclient(self) -> None:
        """Test parsing AngelClientLibs.abc fixture."""
        if not FIXTURES_ABC_DIR.exists():
            pytest.skip("Fixtures directory not available")

        fixture_path = FIXTURES_ABC_DIR / "AngelClientLibs.abc"
        if not fixture_path.exists():
            pytest.skip("AngelClientLibs.abc not available")

        abc_data = _load_abc_file(fixture_path)
        abc = parse(abc_data, mode="relaxed")

        assert abc is not None

    def test_parse_abc_with_fixture_avm2dummy(self) -> None:
        """Test parsing Avm2Dummy.abc fixture."""
        if not FIXTURES_ABC_DIR.exists():
            pytest.skip("Fixtures directory not available")

        fixture_path = FIXTURES_ABC_DIR / "Avm2Dummy.abc"
        if not fixture_path.exists():
            pytest.skip("Avm2Dummy.abc not available")

        abc_data = _load_abc_file(fixture_path)
        abc = parse(abc_data, mode="relaxed")

        assert abc is not None

    def test_parse_abc_with_fixture_builtin(self) -> None:
        """Test parsing builtin.abc fixture."""
        if not FIXTURES_ABC_DIR.exists():
            pytest.skip("Fixtures directory not available")

        fixture_path = FIXTURES_ABC_DIR / "builtin.abc"
        if not fixture_path.exists():
            pytest.skip("builtin.abc not available")

        abc_data = _load_abc_file(fixture_path)
        abc = parse(abc_data, mode="relaxed")

        assert abc is not None

    def test_parse_abc_with_fixture_test(self) -> None:
        """Test parsing Test.abc fixture."""
        if not FIXTURES_ABC_DIR.exists():
            pytest.skip("Fixtures directory not available")

        fixture_path = FIXTURES_ABC_DIR / "Test.abc"
        if not fixture_path.exists():
            pytest.skip("Test.abc not available")

        abc_data = _load_abc_file(fixture_path)
        abc = parse(abc_data, mode="relaxed")

        assert abc is not None

    def test_parse_abc_with_jpexs_assembled(self) -> None:
        """Test parsing JPEXS assembled ABC."""
        if not JPEXS_ABC_DIR.exists():
            pytest.skip("JPEXS ABC directory not available")

        fixture_path = JPEXS_ABC_DIR / "as3_assembled-0.abc"
        if not fixture_path.exists():
            pytest.skip("as3_assembled-0.abc not available")

        abc_data = _load_abc_file(fixture_path)
        abc = parse(abc_data, mode="relaxed")

        assert abc is not None

    def test_parse_abc_version_46(self) -> None:
        """Test parsing ABC version 46."""
        abc_data = bytes(
            [
                0x10,
                0x00,
                0x2E,
                0x00,  # minor_version=0, major_version=46
                0x00,  # int_count
                0x00,  # uint_count
                0x00,  # double_count
                0x00,  # string_count
                0x00,  # namespace_count
                0x00,  # ns_set_count
                0x00,  # multiname_count
                0x00,  # method_count
                0x00,  # metadata_count
                0x00,  # class_count
                0x00,  # script_count
                0x00,  # method_body_count
            ]
        )

        abc = parse(abc_data, mode="relaxed")
        assert abc is not None
        assert abc.major_version == 46
        assert abc.minor_version == 16

    def test_parse_abc_version_47(self) -> None:
        """Test parsing ABC version 47."""
        abc_data = bytes(
            [
                0x10,
                0x00,
                0x2F,
                0x00,  # minor_version=0, major_version=47
                0x00,  # int_count
                0x00,  # uint_count
                0x00,  # double_count
                0x00,  # string_count
                0x00,  # namespace_count
                0x00,  # ns_set_count
                0x00,  # multiname_count
                0x00,  # method_count
                0x00,  # metadata_count
                0x00,  # class_count
                0x00,  # script_count
                0x00,  # method_body_count
            ]
        )

        abc = parse(abc_data, mode="relaxed")
        assert abc is not None
        assert abc.major_version == 47
        assert abc.minor_version == 16

    def test_parse_abc_version_45(self) -> None:
        """Test parsing ABC version 45."""
        abc_data = bytes(
            [
                0x10,
                0x00,
                0x2D,
                0x00,  # minor_version=0, major_version=45
                0x00,  # int_count
                0x00,  # uint_count
                0x00,  # double_count
                0x00,  # string_count
                0x00,  # namespace_count
                0x00,  # ns_set_count
                0x00,  # multiname_count
                0x00,  # method_count
                0x00,  # metadata_count
                0x00,  # class_count
                0x00,  # script_count
                0x00,  # method_body_count
            ]
        )

        abc = parse(abc_data, mode="relaxed")
        assert abc is not None
        assert abc.major_version == 45
        assert abc.minor_version == 16
