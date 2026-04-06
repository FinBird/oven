"""
Robustness matrix for ABC parsing:
- truncation matrix
- out-of-range index matrix
"""

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import pytest
from oven.avm2 import ABCReader, ConstantPool, parse_abc
from oven.avm2.enums import Index, MultinameKind
from oven.avm2.constant_pool import Multiname, NamespaceInfo
from oven.avm2.exceptions import InvalidABCCodeError
from oven.avm2.methods import MethodFlags
from oven.avm2.enums import (
    ConstantKind,
    MultinameKind,
    NamespaceKind,
    Opcode,
    TraitKind,
)


def _minimal_abc(method_body_method_indexes: list[int], method_count: int = 1) -> bytes:
    blob = bytearray()
    blob.extend((16).to_bytes(2, "little"))
    blob.extend((46).to_bytes(2, "little"))
    blob.extend([1, 1, 1, 1, 1, 1, 1])
    blob.append(method_count)
    for _ in range(method_count):
        blob.extend([0, 0, 0, 0])
    blob.append(0)
    blob.append(0)
    blob.append(0)
    blob.append(len(method_body_method_indexes))
    for method_index in method_body_method_indexes:
        blob.extend([method_index, 1, 1, 0, 1])
        blob.extend([1, Opcode.ReturnVoid.value])
        blob.extend([0, 0])
    return bytes(blob)


def _minimal_abc_with_script_init(method_count: int, script_init_method: int) -> bytes:
    blob = bytearray()
    blob.extend((16).to_bytes(2, "little"))
    blob.extend((46).to_bytes(2, "little"))
    blob.extend([1, 1, 1, 1, 1, 1, 1])
    blob.append(method_count)
    for _ in range(method_count):
        blob.extend([0, 0, 0, 0])
    blob.append(0)
    blob.append(0)
    blob.append(1)
    blob.append(script_init_method)
    blob.append(0)
    blob.append(0)
    return bytes(blob)


def _minimal_abc_with_invalid_script_method_trait() -> bytes:
    blob = bytearray()
    blob.extend((16).to_bytes(2, "little"))
    blob.extend((46).to_bytes(2, "little"))
    blob.extend([1, 1, 1, 1, 1, 1])
    blob.append(2)
    blob.append(15)
    blob.append(0)
    blob.append(1)
    blob.extend([0, 0, 0, 0])
    blob.append(0)
    blob.append(0)
    blob.append(1)
    blob.append(0)
    blob.append(1)
    blob.append(1)
    blob.append(TraitKind.METHOD.value)
    blob.append(0)
    blob.append(2)
    blob.append(0)
    return bytes(blob)


def _minimal_abc_with_exception_offsets(
    from_offset: int,
    to_offset: int,
    target_offset: int,
    exc_type_idx: int = 0,
    var_name_idx: int = 0,
    init_scope_depth: int = 0,
    max_scope_depth: int = 1,
    code: bytes = bytes([Opcode.ReturnVoid.value]),
) -> bytes:
    blob = bytearray()
    blob.extend((16).to_bytes(2, "little"))
    blob.extend((46).to_bytes(2, "little"))
    blob.extend([1, 1, 1, 1, 1, 1, 1])
    blob.append(1)
    blob.extend([0, 0, 0, 0])
    blob.append(0)
    blob.append(0)
    blob.append(0)
    blob.append(1)
    blob.extend([0, 1, 1, init_scope_depth, max_scope_depth])
    blob.append(len(code))
    blob.extend(code)
    blob.append(1)
    blob.append(from_offset)
    blob.append(to_offset)
    blob.append(target_offset)
    blob.extend([exc_type_idx, var_name_idx])
    blob.append(0)
    return bytes(blob)


def _abc_with_script_trait_metadata_index(
    metadata_index: int, metadata_count: int
) -> bytes:
    blob = bytearray()
    blob.extend((16).to_bytes(2, "little"))
    blob.extend((46).to_bytes(2, "little"))
    blob.extend([1, 1, 1])
    blob.append(3)
    blob.extend([4])
    blob.extend(b"Meta")
    blob.extend([4])
    blob.extend(b"Tag0")
    blob.append(2)
    blob.append(NamespaceKind.NAMESPACE.value)
    blob.append(1)
    blob.append(1)
    blob.append(2)
    blob.append(7)
    blob.append(1)
    blob.append(1)
    blob.append(1)
    blob.extend([0, 0, 0, 0])
    blob.append(metadata_count)
    for _ in range(metadata_count):
        blob.extend([1, 0])
    blob.append(0)
    blob.append(1)
    blob.append(0)
    blob.append(1)
    blob.append(1)
    blob.append(TraitKind.METHOD.value | 64)
    blob.append(0)
    blob.append(0)
    blob.append(1)
    blob.append(metadata_index)
    blob.append(0)
    return bytes(blob)


def _abc_with_instance_class_trait(
    class_index: int, class_trait_in_class_section: bool = False
) -> bytes:
    blob = bytearray()
    blob.extend((16).to_bytes(2, "little"))
    blob.extend((46).to_bytes(2, "little"))
    blob.extend([1, 1, 1])
    blob.append(2)
    blob.extend([4])
    blob.extend(b"Name")
    blob.append(2)
    blob.append(NamespaceKind.NAMESPACE.value)
    blob.append(1)
    blob.append(1)
    blob.append(2)
    blob.append(7)
    blob.append(1)
    blob.append(1)
    blob.append(1)
    blob.extend([0, 0, 0, 0])
    blob.append(0)
    blob.append(1)
    blob.append(1)
    blob.append(1)
    blob.append(0)
    blob.append(0)
    blob.append(0)
    blob.append(0 if class_trait_in_class_section else 1)
    if not class_trait_in_class_section:
        blob.append(1)
        blob.append(TraitKind.CLASS.value)
        blob.append(1)
        blob.append(class_index)
    blob.append(0)
    blob.append(1 if class_trait_in_class_section else 0)
    if class_trait_in_class_section:
        blob.append(1)
        blob.append(TraitKind.CLASS.value)
        blob.append(1)
        blob.append(class_index)
    blob.append(0)
    blob.append(0)
    return bytes(blob)


def _abc_with_instance_headers(
    flags: int, protected_ns_index: int | None, interface_indices: list[int]
) -> bytes:
    blob = bytearray()
    blob.extend((16).to_bytes(2, "little"))
    blob.extend((46).to_bytes(2, "little"))
    blob.extend([1, 1, 1])
    blob.append(2)
    blob.extend([4])
    blob.extend(b"Name")
    blob.append(2)
    blob.append(NamespaceKind.NAMESPACE.value)
    blob.append(1)
    blob.append(1)
    blob.append(2)
    blob.append(7)
    blob.append(1)
    blob.append(1)
    blob.append(1)
    blob.extend([0, 0, 0, 0])
    blob.append(0)
    blob.append(1)
    blob.append(1)
    blob.append(1)
    blob.append(flags)
    if flags & 8:
        blob.append(0 if protected_ns_index is None else protected_ns_index)
    blob.append(len(interface_indices))
    for idx in interface_indices:
        blob.append(idx)
    blob.append(0)
    blob.append(0)
    blob.append(0)
    blob.append(0)
    blob.append(0)
    blob.append(0)
    return bytes(blob)


def _abc_with_single_method_and_body(
    param_count: int,
    method_flags: int,
    num_locals: int,
    max_stack: int = 1,
    init_scope_depth: int = 0,
    max_scope_depth: int = 1,
    code: bytes = bytes([Opcode.ReturnVoid.value]),
    exception_entries: list[tuple[int, int, int, int, int]] | None = None,
) -> bytes:
    blob = bytearray()
    blob.extend((16).to_bytes(2, "little"))
    blob.extend((46).to_bytes(2, "little"))
    blob.extend([1, 1, 1, 1, 1, 1, 1])
    blob.append(1)
    blob.append(param_count)
    blob.append(0)
    for _ in range(param_count):
        blob.append(0)
    blob.append(0)
    blob.append(method_flags)
    blob.append(0)
    blob.append(0)
    blob.append(0)
    blob.append(1)
    blob.append(0)
    blob.append(max_stack)
    blob.append(num_locals)
    blob.append(init_scope_depth)
    blob.append(max_scope_depth)
    blob.append(len(code))
    blob.extend(code)
    entries = exception_entries or []
    blob.append(len(entries))
    for from_offset, to_offset, target_offset, exc_type_idx, var_name_idx in entries:
        blob.append(from_offset)
        blob.append(to_offset)
        blob.append(target_offset)
        blob.append(exc_type_idx)
        blob.append(var_name_idx)
    blob.append(0)
    return bytes(blob)


def _abc_with_rtqname_multiname_and_body(
    *, code: bytes, max_stack: int = 1, num_locals: int = 0, param_count: int = 0
) -> bytes:
    """
    Minimal ABC with exactly one multiname entry:
      multiname[1] = RTQNAME(name=0, i.e. '*')
    Useful for verifier tests that need runtime multiname arity.
    """
    blob = bytearray()
    blob.extend((16).to_bytes(2, "little"))
    blob.extend((46).to_bytes(2, "little"))
    blob.append(1)
    blob.append(1)
    blob.append(1)
    blob.append(1)
    blob.append(1)
    blob.append(1)
    blob.append(2)
    blob.append(15)
    blob.append(0)
    blob.append(1)
    blob.append(param_count)
    blob.append(0)
    for _ in range(param_count):
        blob.append(0)
    blob.append(0)
    blob.append(0)
    blob.append(0)
    blob.append(0)
    blob.append(0)
    blob.append(1)
    blob.append(0)
    blob.append(max_stack)
    blob.append(num_locals)
    blob.append(0)
    blob.append(1)
    blob.append(len(code))
    blob.extend(code)
    blob.append(0)
    blob.append(0)
    return bytes(blob)


def _abc_with_qname_multiname_and_body(
    *,
    name: str,
    code: bytes,
    max_stack: int = 1,
    num_locals: int = 0,
    param_count: int = 0,
) -> bytes:
    """
    Minimal ABC with exactly one multiname entry:
      multiname[1] = QNAME(namespace[1], string[1]=name)
    Useful for verifier tests that require static multiname names.
    """
    name_bytes = name.encode("utf-8")
    blob = bytearray()
    blob.extend((16).to_bytes(2, "little"))
    blob.extend((46).to_bytes(2, "little"))
    blob.append(1)
    blob.append(1)
    blob.append(1)
    blob.append(2)
    blob.append(len(name_bytes))
    blob.extend(name_bytes)
    blob.append(2)
    blob.append(NamespaceKind.NAMESPACE.value)
    blob.append(1)
    blob.append(1)
    blob.append(2)
    blob.append(MultinameKind.QNAME.value)
    blob.append(1)
    blob.append(1)
    blob.append(1)
    blob.append(param_count)
    blob.append(0)
    for _ in range(param_count):
        blob.append(0)
    blob.append(0)
    blob.append(0)
    blob.append(0)
    blob.append(0)
    blob.append(0)
    blob.append(1)
    blob.append(0)
    blob.append(max_stack)
    blob.append(num_locals)
    blob.append(0)
    blob.append(1)
    blob.append(len(code))
    blob.extend(code)
    blob.append(0)
    blob.append(0)
    return bytes(blob)


def _abc_with_two_methods_and_declared_return_type(
    *, return_type_name: str, code: bytes, max_stack: int = 1, num_locals: int = 0
) -> bytes:
    """
    Minimal ABC with two methods and one declared return-type multiname:
      method[0]: body owner (return_type="*")
      method[1]: declared return type = QNAME(namespace[1], string[1])
    """
    return_name_bytes = return_type_name.encode("utf-8")
    blob = bytearray()
    blob.extend((16).to_bytes(2, "little"))
    blob.extend((46).to_bytes(2, "little"))
    blob.append(1)
    blob.append(1)
    blob.append(1)
    blob.append(2)
    blob.append(len(return_name_bytes))
    blob.extend(return_name_bytes)
    blob.append(2)
    blob.append(NamespaceKind.NAMESPACE.value)
    blob.append(1)
    blob.append(1)
    blob.append(2)
    blob.append(MultinameKind.QNAME.value)
    blob.append(1)
    blob.append(1)
    blob.append(2)
    blob.append(0)
    blob.append(0)
    blob.append(0)
    blob.append(0)
    blob.append(0)
    blob.append(1)
    blob.append(0)
    blob.append(0)
    blob.append(0)
    blob.append(0)
    blob.append(0)
    blob.append(1)
    blob.append(0)
    blob.append(max_stack)
    blob.append(num_locals)
    blob.append(0)
    blob.append(1)
    blob.append(len(code))
    blob.extend(code)
    blob.append(0)
    blob.append(0)
    return bytes(blob)


def _i24(value: int) -> bytes:
    return int(value & 16777215).to_bytes(3, "little", signed=False)


@dataclass(frozen=True)
class _LookupswitchProfileScenario:
    id: str
    profile: str
    strict_lookupswitch: bool | None
    lattice_any_policy: str | None
    expected_error: str | None


_LOOKUPSWITCH_PROFILE_SCENARIOS = [
    _LookupswitchProfileScenario(
        id="strict_precise_joins_default_lookupswitch_validation",
        profile="strict_precise_joins",
        strict_lookupswitch=None,
        lattice_any_policy=None,
        expected_error="Invalid branch target offset",
    ),
    _LookupswitchProfileScenario(
        id="strict_precise_joins_relaxed_lookupswitch_still_rejects_join_type",
        profile="strict_precise_joins",
        strict_lookupswitch=False,
        lattice_any_policy=None,
        expected_error="stack type mismatch",
    ),
    _LookupswitchProfileScenario(
        id="strict_relaxed_joins_relaxed_lookupswitch_accepts_payload",
        profile="strict_relaxed_joins",
        strict_lookupswitch=False,
        lattice_any_policy=None,
        expected_error=None,
    ),
    _LookupswitchProfileScenario(
        id="strict_profile_prefers_precise_any_and_rejects_join",
        profile="strict",
        strict_lookupswitch=False,
        lattice_any_policy="prefer_precise",
        expected_error="stack type mismatch",
    ),
    _LookupswitchProfileScenario(
        id="strict_profile_with_any_widen_accepts_payload",
        profile="strict",
        strict_lookupswitch=False,
        lattice_any_policy="widen",
        expected_error=None,
    ),
]


def _abc_with_exception_lookupswitch_cross_matrix_payload() -> bytes:
    code = bytes(
        [
            Opcode.PushByte.value,
            0,
            Opcode.LookupSwitch.value,
            *_i24(7),
            1,
            *_i24(20),
            *_i24(120),
            Opcode.Nop.value,
            Opcode.Nop.value,
            Opcode.Nop.value,
            Opcode.Nop.value,
            Opcode.Nop.value,
            Opcode.Nop.value,
            Opcode.Nop.value,
            Opcode.PushByte.value,
            1,
            Opcode.Jump.value,
            *_i24(14),
            Opcode.Pop.value,
            Opcode.GetLocal.value,
            1,
            Opcode.Jump.value,
            *_i24(7),
            Opcode.PushTrue.value,
            Opcode.Jump.value,
            *_i24(2),
            Opcode.Nop.value,
            Opcode.Nop.value,
            Opcode.Pop.value,
            Opcode.ReturnVoid.value,
        ]
    )
    return _abc_with_single_method_and_body(
        param_count=0,
        method_flags=0,
        num_locals=2,
        max_stack=1,
        code=code,
        exception_entries=[(0, 40, 26, 0, 0)],
    )


@pytest.mark.parametrize("cut", range(0, len(_minimal_abc([0]))))
def test_parse_abc_truncation_matrix_rejects_all_prefixes(cut: int) -> None:
    data = _minimal_abc([0])
    truncated = data[:cut]
    with pytest.raises(InvalidABCCodeError):
        parse_abc(truncated)


def _pool_for_kind(kind: ConstantKind) -> ConstantPool:
    ints = [7] if kind == ConstantKind.INT else []
    uints = [8] if kind == ConstantKind.UINT else []
    doubles = [3.5] if kind == ConstantKind.DOUBLE else []
    strings = ["s"] if kind == ConstantKind.UTF8 else []
    namespaces = (
        [NamespaceInfo(NamespaceKind.NAMESPACE, 0)]
        if kind
        in {
            ConstantKind.NAMESPACE,
            ConstantKind.PRIVATE_NS,
            ConstantKind.PACKAGE_NAMESPACE,
            ConstantKind.PACKAGE_INTERNAL_NS,
            ConstantKind.PROTECTED_NAMESPACE,
            ConstantKind.EXPLICIT_NAMESPACE,
            ConstantKind.STATIC_PROTECTED_NS,
        }
        else []
    )
    return ConstantPool(
        ints=ints,
        uints=uints,
        doubles=doubles,
        strings=strings,
        namespaces=namespaces,
        namespace_sets=[],
        multinames=[],
    )


def _method_with_optional(val_index: int, kind: ConstantKind) -> bytes:
    return bytes([1, 0, 0, 0, MethodFlags.HAS_OPTIONAL.value, 1, val_index, kind.value])


@pytest.mark.parametrize(
    "kind",
    [
        ConstantKind.INT,
        ConstantKind.UINT,
        ConstantKind.DOUBLE,
        ConstantKind.UTF8,
        ConstantKind.NAMESPACE,
        ConstantKind.PRIVATE_NS,
    ],
)
def test_method_optional_default_index_out_of_range_is_rejected(
    kind: ConstantKind,
) -> None:
    reader = ABCReader(_method_with_optional(2, kind))
    pool = _pool_for_kind(kind)
    with pytest.raises(InvalidABCCodeError, match="out of range"):
        reader.read_method(pool)


def test_method_optional_default_index_in_range_remains_accepted() -> None:
    reader = ABCReader(_method_with_optional(1, ConstantKind.INT))
    pool = _pool_for_kind(ConstantKind.INT)
    method = reader.read_method(pool)
    assert len(method.params) == 1
    assert method.params[0].default_value is not None


def test_read_method_rejects_param_type_index_out_of_range() -> None:
    pool = ConstantPool(
        ints=[],
        uints=[],
        doubles=[],
        strings=["", "OnlyOneType"],
        namespaces=[],
        namespace_sets=[],
        multinames=[
            Multiname(MultinameKind.QNAME, {"namespace": Index(0), "name": Index(2)})
        ],
    )
    data = bytes([1, 0, 2, 0, 0])
    reader = ABCReader(data)
    with pytest.raises(InvalidABCCodeError, match="param type index"):
        reader.read_method(pool)


def test_read_constant_pool_rejects_qname_name_index_out_of_range() -> None:
    data = bytes([1, 1, 1, 1, 2, NamespaceKind.NAMESPACE.value, 0, 1, 2, 7, 1, 1])
    with pytest.raises(InvalidABCCodeError, match="multiname name index"):
        ABCReader(data).read_constant_pool()


def test_read_constant_pool_rejects_typename_base_index_out_of_range() -> None:
    data = bytes([1, 1, 1, 1, 1, 1, 2, 29, 2, 1, 1])
    with pytest.raises(InvalidABCCodeError, match="typename base index"):
        ABCReader(data).read_constant_pool()


def test_parse_abc_rejects_out_of_range_script_init_method() -> None:
    data = _minimal_abc_with_script_init(method_count=1, script_init_method=2)
    with pytest.raises(InvalidABCCodeError, match="script init method"):
        parse_abc(data)


def test_read_trait_rejects_slot_type_name_index_out_of_range() -> None:
    pool = ConstantPool(
        ints=[],
        uints=[],
        doubles=[],
        strings=["", "traitName"],
        namespaces=[],
        namespace_sets=[],
        multinames=[
            Multiname(MultinameKind.QNAME, {"namespace": Index(0), "name": Index(2)})
        ],
    )
    data = bytes([1, TraitKind.SLOT.value, 1, 2, 0])
    with pytest.raises(InvalidABCCodeError, match="type_name index"):
        ABCReader(data).read_trait(pool)


def test_parse_abc_rejects_trait_method_reference_out_of_range() -> None:
    data = _minimal_abc_with_invalid_script_method_trait()
    with pytest.raises(InvalidABCCodeError, match="trait method index"):
        parse_abc(data)


def test_parse_abc_rejects_exception_range_with_descending_offsets() -> None:
    data = _minimal_abc_with_exception_offsets(
        from_offset=1, to_offset=0, target_offset=0
    )
    with pytest.raises(InvalidABCCodeError, match="exception range"):
        parse_abc(data)


def test_parse_abc_rejects_exception_range_with_to_out_of_code_bounds() -> None:
    data = _minimal_abc_with_exception_offsets(
        from_offset=0, to_offset=2, target_offset=0
    )
    with pytest.raises(InvalidABCCodeError, match="exception range"):
        parse_abc(data)


def test_parse_abc_rejects_exception_target_out_of_code_bounds() -> None:
    data = _minimal_abc_with_exception_offsets(
        from_offset=0, to_offset=1, target_offset=1
    )
    with pytest.raises(InvalidABCCodeError, match="exception target"):
        parse_abc(data)


def test_parse_abc_accepts_valid_exception_range() -> None:
    data = _minimal_abc_with_exception_offsets(
        from_offset=0, to_offset=1, target_offset=0
    )
    abc = parse_abc(data)
    assert len(abc.method_bodies) == 1
    assert len(abc.method_bodies[0].exceptions) == 1


def test_parse_abc_rejects_script_trait_metadata_index_out_of_metadata_range() -> None:
    data = _abc_with_script_trait_metadata_index(metadata_index=2, metadata_count=1)
    with pytest.raises(InvalidABCCodeError, match="trait metadata index"):
        parse_abc(data)


def test_parse_abc_rejects_script_trait_metadata_when_metadata_table_empty() -> None:
    data = _abc_with_script_trait_metadata_index(metadata_index=1, metadata_count=0)
    with pytest.raises(InvalidABCCodeError, match="trait metadata index"):
        parse_abc(data)


def test_parse_abc_accepts_script_trait_metadata_in_range() -> None:
    data = _abc_with_script_trait_metadata_index(metadata_index=1, metadata_count=1)
    abc = parse_abc(data)
    assert len(abc.scripts) == 1
    assert len(abc.scripts[0].traits) == 1


def test_parse_abc_accepts_script_trait_metadata_index_valid_against_metadata_table_not_string_pool() -> (
    None
):
    data = _abc_with_script_trait_metadata_index(metadata_index=3, metadata_count=3)
    abc = parse_abc(data)
    assert len(abc.scripts) == 1
    assert len(abc.scripts[0].traits) == 1
    trait_data = abc.scripts[0].traits[0].data
    assert trait_data is not None
    assert trait_data["metadata_indices"] == [3]
    assert abc.scripts[0].traits[0].metadata == ["Meta"]


def test_parse_abc_rejects_one_based_trait_metadata_in_strict_mode() -> None:
    data = _abc_with_script_trait_metadata_index(metadata_index=1, metadata_count=1)
    with pytest.raises(InvalidABCCodeError, match="trait metadata index"):
        parse_abc(data, strict_metadata_indices=True)


def test_parse_abc_accepts_zero_based_trait_metadata_in_strict_mode() -> None:
    data = _abc_with_script_trait_metadata_index(metadata_index=0, metadata_count=1)
    abc = parse_abc(data, strict_metadata_indices=True)
    assert len(abc.scripts) == 1
    assert len(abc.scripts[0].traits) == 1


def test_parse_abc_rejects_instance_trait_class_reference_out_of_range() -> None:
    data = _abc_with_instance_class_trait(
        class_index=1, class_trait_in_class_section=False
    )
    with pytest.raises(InvalidABCCodeError, match="instance trait class index"):
        parse_abc(data)


def test_parse_abc_rejects_class_trait_class_reference_out_of_range() -> None:
    data = _abc_with_instance_class_trait(
        class_index=1, class_trait_in_class_section=True
    )
    with pytest.raises(InvalidABCCodeError, match="class trait class index"):
        parse_abc(data)


def test_parse_abc_accepts_class_trait_class_reference_in_range() -> None:
    data = _abc_with_instance_class_trait(
        class_index=0, class_trait_in_class_section=True
    )
    abc = parse_abc(data)
    assert len(abc.classes) == 1


def test_read_metadata_item_rejects_key_index_out_of_range() -> None:
    pool = ConstantPool(
        ints=[],
        uints=[],
        doubles=[],
        strings=["Meta", "Value"],
        namespaces=[],
        namespace_sets=[],
        multinames=[],
    )
    with pytest.raises(InvalidABCCodeError, match="metadata key index"):
        ABCReader(bytes([1, 1, 3, 2])).read_metadata_item(pool)


def test_read_metadata_item_rejects_value_index_out_of_range() -> None:
    pool = ConstantPool(
        ints=[],
        uints=[],
        doubles=[],
        strings=["Meta", "Key"],
        namespaces=[],
        namespace_sets=[],
        multinames=[],
    )
    with pytest.raises(InvalidABCCodeError, match="metadata value index"):
        ABCReader(bytes([1, 1, 2, 3])).read_metadata_item(pool)


def test_read_method_rejects_method_name_index_out_of_range() -> None:
    pool = ConstantPool(
        ints=[],
        uints=[],
        doubles=[],
        strings=["only"],
        namespaces=[],
        namespace_sets=[],
        multinames=[],
    )
    with pytest.raises(InvalidABCCodeError, match="method name index"):
        ABCReader(bytes([0, 0, 2, 0])).read_method(pool)


def test_read_constant_pool_rejects_namespace_name_index_out_of_range() -> None:
    data = bytes([1, 1, 1, 1, 2, NamespaceKind.NAMESPACE.value, 1, 1, 1])
    with pytest.raises(InvalidABCCodeError, match="namespace name index"):
        ABCReader(data).read_constant_pool()


def test_parse_abc_rejects_instance_protected_namespace_zero_index() -> None:
    data = _abc_with_instance_headers(
        flags=8, protected_ns_index=0, interface_indices=[]
    )
    with pytest.raises(InvalidABCCodeError, match="protected namespace index"):
        parse_abc(data)


def test_parse_abc_rejects_instance_interface_index_out_of_range() -> None:
    data = _abc_with_instance_headers(
        flags=0, protected_ns_index=None, interface_indices=[2]
    )
    with pytest.raises(InvalidABCCodeError, match="instance interface index"):
        parse_abc(data)


def test_parse_abc_rejects_exception_type_index_out_of_range() -> None:
    data = _minimal_abc_with_exception_offsets(
        from_offset=0, to_offset=1, target_offset=0, exc_type_idx=1, var_name_idx=0
    )
    with pytest.raises(InvalidABCCodeError, match="exception type index"):
        parse_abc(data)


def test_parse_abc_rejects_exception_var_name_index_out_of_range() -> None:
    data = _minimal_abc_with_exception_offsets(
        from_offset=0, to_offset=1, target_offset=0, exc_type_idx=0, var_name_idx=1
    )
    with pytest.raises(InvalidABCCodeError, match="exception var_name index"):
        parse_abc(data)


def test_parse_abc_rejects_method_body_scope_depth_order() -> None:
    data = _minimal_abc_with_exception_offsets(
        from_offset=0,
        to_offset=1,
        target_offset=0,
        init_scope_depth=2,
        max_scope_depth=1,
    )
    with pytest.raises(InvalidABCCodeError, match="scope depth"):
        parse_abc(data)


def test_parse_abc_rejects_scope_stack_underflow_in_verifier_mode() -> None:
    data = _abc_with_single_method_and_body(
        param_count=0,
        method_flags=0,
        num_locals=0,
        max_scope_depth=1,
        code=bytes([Opcode.PopScope.value, Opcode.ReturnVoid.value]),
    )
    with pytest.raises(InvalidABCCodeError, match="scope stack underflow"):
        parse_abc(data, verify_stack=True)


def test_parse_abc_rejects_scope_stack_exceeding_max_scope_depth_in_verifier_mode() -> (
    None
):
    data = _abc_with_single_method_and_body(
        param_count=0,
        method_flags=0,
        num_locals=0,
        max_stack=1,
        max_scope_depth=0,
        code=bytes(
            [Opcode.PushNull.value, Opcode.PushScope.value, Opcode.ReturnVoid.value]
        ),
    )
    with pytest.raises(InvalidABCCodeError, match="max_scope_depth"):
        parse_abc(data, verify_stack=True)


def test_parse_abc_rejects_scope_depth_mismatch_on_control_flow_join_in_verifier_mode() -> (
    None
):
    code = bytes(
        [
            Opcode.PushByte.value,
            1,
            Opcode.IfTrue.value,
            *_i24(2),
            Opcode.PushNull.value,
            Opcode.PushScope.value,
            Opcode.ReturnVoid.value,
        ]
    )
    data = _abc_with_single_method_and_body(
        param_count=0,
        method_flags=0,
        num_locals=0,
        max_stack=1,
        max_scope_depth=1,
        code=code,
    )
    with pytest.raises(InvalidABCCodeError, match="scope depth mismatch"):
        parse_abc(data, verify_stack=True)


def test_parse_abc_accepts_balanced_scope_stack_flow_in_verifier_mode() -> None:
    data = _abc_with_single_method_and_body(
        param_count=0,
        method_flags=0,
        num_locals=0,
        max_stack=1,
        max_scope_depth=1,
        code=bytes(
            [
                Opcode.PushNull.value,
                Opcode.PushScope.value,
                Opcode.PopScope.value,
                Opcode.ReturnVoid.value,
            ]
        ),
    )
    abc = parse_abc(data, verify_stack=True)
    assert len(abc.methods) == 1
    assert abc.methods[0].body is not None


def test_parse_abc_rejects_getscopeobject_when_scope_stack_is_empty_in_verifier_mode() -> (
    None
):
    data = _abc_with_single_method_and_body(
        param_count=0,
        method_flags=0,
        num_locals=0,
        max_stack=1,
        init_scope_depth=0,
        max_scope_depth=1,
        code=bytes(
            [Opcode.GetScopeObject.value, 0, Opcode.Pop.value, Opcode.ReturnVoid.value]
        ),
    )
    with pytest.raises(InvalidABCCodeError, match="scope object index out of range"):
        parse_abc(data, verify_stack=True)


def test_parse_abc_accepts_getscopeobject_within_current_scope_depth_in_verifier_mode() -> (
    None
):
    data = _abc_with_single_method_and_body(
        param_count=0,
        method_flags=0,
        num_locals=0,
        max_stack=1,
        init_scope_depth=1,
        max_scope_depth=1,
        code=bytes(
            [Opcode.GetScopeObject.value, 0, Opcode.Pop.value, Opcode.ReturnVoid.value]
        ),
    )
    abc = parse_abc(data, verify_stack=True)
    assert len(abc.methods) == 1
    assert abc.methods[0].body is not None


def test_parse_abc_rejects_method_body_num_locals_less_than_param_count() -> None:
    data = _abc_with_single_method_and_body(param_count=2, method_flags=0, num_locals=1)
    with pytest.raises(InvalidABCCodeError, match="num_locals"):
        parse_abc(data)


def test_parse_abc_accepts_method_body_num_locals_equal_param_count() -> None:
    data = _abc_with_single_method_and_body(param_count=2, method_flags=0, num_locals=2)
    abc = parse_abc(data)
    assert len(abc.methods) == 1
    assert abc.methods[0].body is not None


def test_parse_abc_rejects_getlocal_index_out_of_range_in_verifier_mode() -> None:
    data = _abc_with_single_method_and_body(
        param_count=0,
        method_flags=0,
        num_locals=1,
        max_stack=1,
        code=bytes(
            [Opcode.GetLocal.value, 1, Opcode.Pop.value, Opcode.ReturnVoid.value]
        ),
    )
    with pytest.raises(InvalidABCCodeError, match="local register index out of range"):
        parse_abc(data, verify_stack=True)


def test_parse_abc_accepts_getlocal_index_in_range_in_verifier_mode() -> None:
    data = _abc_with_single_method_and_body(
        param_count=0,
        method_flags=0,
        num_locals=1,
        max_stack=1,
        code=bytes(
            [Opcode.GetLocal.value, 0, Opcode.Pop.value, Opcode.ReturnVoid.value]
        ),
    )
    abc = parse_abc(data, verify_stack=True)
    assert len(abc.methods) == 1
    assert abc.methods[0].body is not None


def test_parse_abc_rejects_hasnext2_local_register_out_of_range_in_verifier_mode() -> (
    None
):
    data = _abc_with_single_method_and_body(
        param_count=0,
        method_flags=0,
        num_locals=1,
        max_stack=1,
        code=bytes(
            [Opcode.HasNext2.value, 1, 0, Opcode.Pop.value, Opcode.ReturnVoid.value]
        ),
    )
    with pytest.raises(InvalidABCCodeError, match="local register index out of range"):
        parse_abc(data, verify_stack=True)


def test_parse_abc_rejects_local_type_mismatch_on_control_flow_join_in_verifier_mode() -> (
    None
):
    code = bytes(
        [
            Opcode.PushByte.value,
            1,
            Opcode.IfTrue.value,
            *_i24(8),
            Opcode.PushByte.value,
            7,
            Opcode.SetLocal.value,
            0,
            Opcode.Jump.value,
            *_i24(2),
            Opcode.PushTrue.value,
            Opcode.SetLocal0.value,
            Opcode.GetLocal0.value,
            Opcode.Pop.value,
            Opcode.ReturnVoid.value,
        ]
    )
    data = _abc_with_single_method_and_body(
        param_count=0, method_flags=0, num_locals=1, max_stack=1, code=code
    )
    with pytest.raises(InvalidABCCodeError, match="local type mismatch"):
        parse_abc(data, verify_stack=True)


def test_parse_abc_relaxed_verifier_accepts_local_type_mismatch_on_control_flow_join() -> (
    None
):
    code = bytes(
        [
            Opcode.PushByte.value,
            1,
            Opcode.IfTrue.value,
            *_i24(8),
            Opcode.PushByte.value,
            7,
            Opcode.SetLocal.value,
            0,
            Opcode.Jump.value,
            *_i24(2),
            Opcode.PushTrue.value,
            Opcode.SetLocal0.value,
            Opcode.GetLocal0.value,
            Opcode.Pop.value,
            Opcode.ReturnVoid.value,
        ]
    )
    data = _abc_with_single_method_and_body(
        param_count=0, method_flags=0, num_locals=1, max_stack=1, code=code
    )
    abc = parse_abc(data, verify_stack=True, verify_relaxed=True)
    assert len(abc.methods) == 1
    assert abc.methods[0].body is not None


def test_parse_abc_accepts_local_type_match_on_control_flow_join_in_verifier_mode() -> (
    None
):
    code = bytes(
        [
            Opcode.PushByte.value,
            1,
            Opcode.IfTrue.value,
            *_i24(8),
            Opcode.PushByte.value,
            7,
            Opcode.SetLocal.value,
            0,
            Opcode.Jump.value,
            *_i24(3),
            Opcode.PushByte.value,
            2,
            Opcode.SetLocal0.value,
            Opcode.GetLocal0.value,
            Opcode.Pop.value,
            Opcode.ReturnVoid.value,
        ]
    )
    data = _abc_with_single_method_and_body(
        param_count=0, method_flags=0, num_locals=1, max_stack=1, code=code
    )
    abc = parse_abc(data, verify_stack=True)
    assert len(abc.methods) == 1
    assert abc.methods[0].body is not None


def test_parse_abc_rejects_inclocal_promoted_number_vs_boolean_join_in_verifier_mode() -> (
    None
):
    code = bytes(
        [
            Opcode.PushTrue.value,
            Opcode.IfTrue.value,
            *_i24(9),
            Opcode.PushTrue.value,
            Opcode.SetLocal0.value,
            Opcode.IncLocal.value,
            0,
            Opcode.GetLocal0.value,
            Opcode.Jump.value,
            *_i24(1),
            Opcode.PushTrue.value,
            Opcode.Pop.value,
            Opcode.ReturnVoid.value,
        ]
    )
    data = _abc_with_single_method_and_body(
        param_count=0, method_flags=0, num_locals=1, max_stack=1, code=code
    )
    with pytest.raises(InvalidABCCodeError, match="stack type mismatch"):
        parse_abc(data, verify_stack=True)


def test_parse_abc_rejects_hasnext2_updated_local_object_vs_number_join_in_verifier_mode() -> (
    None
):
    code = bytes(
        [
            Opcode.PushTrue.value,
            Opcode.IfTrue.value,
            *_i24(9),
            Opcode.HasNext2.value,
            0,
            1,
            Opcode.Pop.value,
            Opcode.GetLocal0.value,
            Opcode.Jump.value,
            *_i24(2),
            Opcode.PushByte.value,
            1,
            Opcode.Pop.value,
            Opcode.ReturnVoid.value,
        ]
    )
    data = _abc_with_single_method_and_body(
        param_count=0, method_flags=0, num_locals=2, max_stack=1, code=code
    )
    with pytest.raises(InvalidABCCodeError, match="stack type mismatch"):
        parse_abc(data, verify_stack=True)


def test_parse_abc_rejects_native_method_with_method_body() -> None:
    data = _abc_with_single_method_and_body(
        param_count=0, method_flags=MethodFlags.NATIVE.value, num_locals=1
    )
    with pytest.raises(InvalidABCCodeError, match="native"):
        parse_abc(data)


def test_parse_abc_rejects_stack_underflow_in_verifier_mode() -> None:
    data = _abc_with_single_method_and_body(
        param_count=0,
        method_flags=0,
        num_locals=0,
        max_stack=0,
        code=bytes([Opcode.Pop.value, Opcode.ReturnVoid.value]),
    )
    with pytest.raises(InvalidABCCodeError, match="stack underflow"):
        parse_abc(data, verify_stack=True)


def test_parse_abc_rejects_max_stack_exceeded_in_verifier_mode() -> None:
    data = _abc_with_single_method_and_body(
        param_count=0,
        method_flags=0,
        num_locals=0,
        max_stack=1,
        code=bytes(
            [
                Opcode.PushByte.value,
                1,
                Opcode.PushByte.value,
                2,
                Opcode.ReturnVoid.value,
            ]
        ),
    )
    with pytest.raises(InvalidABCCodeError, match="max_stack"):
        parse_abc(data, verify_stack=True)


def test_parse_abc_rejects_stack_depth_mismatch_on_control_flow_join() -> None:
    code = bytes(
        [
            Opcode.PushByte.value,
            1,
            Opcode.IfTrue.value,
            *_i24(2),
            Opcode.PushByte.value,
            2,
            Opcode.PushByte.value,
            3,
            Opcode.ReturnVoid.value,
        ]
    )
    data = _abc_with_single_method_and_body(
        param_count=0, method_flags=0, num_locals=0, max_stack=3, code=code
    )
    with pytest.raises(InvalidABCCodeError, match="stack depth mismatch"):
        parse_abc(data, verify_stack=True)


def test_parse_abc_accepts_valid_stack_flow_in_verifier_mode() -> None:
    data = _abc_with_single_method_and_body(
        param_count=0,
        method_flags=0,
        num_locals=0,
        max_stack=1,
        code=bytes(
            [Opcode.PushByte.value, 1, Opcode.Pop.value, Opcode.ReturnVoid.value]
        ),
    )
    abc = parse_abc(data, verify_stack=True)
    assert len(abc.methods) == 1
    assert abc.methods[0].body is not None


def test_parse_abc_rejects_exception_handler_join_stack_depth_mismatch_in_verifier_mode() -> (
    None
):
    data = _abc_with_single_method_and_body(
        param_count=0,
        method_flags=0,
        num_locals=0,
        max_stack=1,
        code=bytes([Opcode.Nop.value, Opcode.ReturnVoid.value]),
        exception_entries=[(0, 1, 1, 0, 0)],
    )
    with pytest.raises(InvalidABCCodeError, match="stack depth mismatch"):
        parse_abc(data, verify_stack=True)


def test_parse_abc_rejects_exception_handler_entry_exceeding_max_stack_in_verifier_mode() -> (
    None
):
    code = bytes(
        [Opcode.Jump.value, *_i24(1), Opcode.ReturnVoid.value, Opcode.ReturnVoid.value]
    )
    data = _abc_with_single_method_and_body(
        param_count=0,
        method_flags=0,
        num_locals=0,
        max_stack=0,
        code=code,
        exception_entries=[(0, 5, 4, 0, 0)],
    )
    with pytest.raises(InvalidABCCodeError, match="max_stack"):
        parse_abc(data, verify_stack=True)


def test_parse_abc_accepts_exception_handler_stack_flow_in_verifier_mode() -> None:
    code = bytes(
        [Opcode.Jump.value, *_i24(1), Opcode.Pop.value, Opcode.ReturnVoid.value]
    )
    data = _abc_with_single_method_and_body(
        param_count=0,
        method_flags=0,
        num_locals=0,
        max_stack=1,
        code=code,
        exception_entries=[(0, 5, 4, 0, 0)],
    )
    abc = parse_abc(data, verify_stack=True)
    assert len(abc.methods) == 1
    assert abc.methods[0].body is not None


def test_parse_abc_rejects_stack_type_mismatch_on_control_flow_join_in_verifier_mode() -> (
    None
):
    code = bytes(
        [
            Opcode.PushTrue.value,
            Opcode.IfTrue.value,
            *_i24(5),
            Opcode.PushNull.value,
            Opcode.Jump.value,
            *_i24(2),
            Opcode.PushByte.value,
            1,
            Opcode.Pop.value,
            Opcode.ReturnVoid.value,
        ]
    )
    data = _abc_with_single_method_and_body(
        param_count=0, method_flags=0, num_locals=0, max_stack=1, code=code
    )
    with pytest.raises(InvalidABCCodeError, match="stack type mismatch"):
        parse_abc(data, verify_stack=True)


def test_parse_abc_accepts_matching_stack_type_on_control_flow_join_in_verifier_mode() -> (
    None
):
    code = bytes(
        [
            Opcode.PushTrue.value,
            Opcode.IfTrue.value,
            *_i24(5),
            Opcode.PushNull.value,
            Opcode.Jump.value,
            *_i24(1),
            Opcode.PushNull.value,
            Opcode.Pop.value,
            Opcode.ReturnVoid.value,
        ]
    )
    data = _abc_with_single_method_and_body(
        param_count=0, method_flags=0, num_locals=0, max_stack=1, code=code
    )
    abc = parse_abc(data, verify_stack=True)
    assert len(abc.methods) == 1
    assert abc.methods[0].body is not None


def test_parse_abc_rejects_equals_boolean_vs_number_join_in_verifier_mode() -> None:
    code = bytes(
        [
            Opcode.PushTrue.value,
            Opcode.IfTrue.value,
            *_i24(9),
            Opcode.PushInt.value,
            1,
            Opcode.PushInt.value,
            1,
            Opcode.Equals.value,
            Opcode.Jump.value,
            *_i24(2),
            Opcode.PushInt.value,
            1,
            Opcode.Pop.value,
            Opcode.ReturnVoid.value,
        ]
    )
    data = _abc_with_single_method_and_body(
        param_count=0, method_flags=0, num_locals=0, max_stack=2, code=code
    )
    with pytest.raises(InvalidABCCodeError, match="stack type mismatch"):
        parse_abc(data, verify_stack=True)


def test_parse_abc_rejects_hasnext_boolean_vs_number_join_in_verifier_mode() -> None:
    code = bytes(
        [
            Opcode.PushTrue.value,
            Opcode.IfTrue.value,
            *_i24(7),
            Opcode.PushNull.value,
            Opcode.PushNull.value,
            Opcode.HasNext.value,
            Opcode.Jump.value,
            *_i24(2),
            Opcode.PushInt.value,
            1,
            Opcode.Pop.value,
            Opcode.ReturnVoid.value,
        ]
    )
    data = _abc_with_single_method_and_body(
        param_count=0, method_flags=0, num_locals=0, max_stack=2, code=code
    )
    with pytest.raises(InvalidABCCodeError, match="stack type mismatch"):
        parse_abc(data, verify_stack=True)


def test_parse_abc_accepts_equals_boolean_join_with_pushtrue_in_verifier_mode() -> None:
    code = bytes(
        [
            Opcode.PushTrue.value,
            Opcode.IfTrue.value,
            *_i24(9),
            Opcode.PushInt.value,
            1,
            Opcode.PushInt.value,
            1,
            Opcode.Equals.value,
            Opcode.Jump.value,
            *_i24(1),
            Opcode.PushTrue.value,
            Opcode.Pop.value,
            Opcode.ReturnVoid.value,
        ]
    )
    data = _abc_with_single_method_and_body(
        param_count=0, method_flags=0, num_locals=0, max_stack=2, code=code
    )
    abc = parse_abc(data, verify_stack=True)
    assert len(abc.methods) == 1
    assert abc.methods[0].body is not None


def test_parse_abc_rejects_exception_handler_join_stack_type_mismatch_in_verifier_mode() -> (
    None
):
    code = bytes(
        [
            Opcode.PushNull.value,
            Opcode.Jump.value,
            *_i24(0),
            Opcode.Pop.value,
            Opcode.ReturnVoid.value,
        ]
    )
    data = _abc_with_single_method_and_body(
        param_count=0,
        method_flags=0,
        num_locals=0,
        max_stack=1,
        code=code,
        exception_entries=[(0, 5, 5, 0, 0)],
    )
    with pytest.raises(InvalidABCCodeError, match="stack type mismatch"):
        parse_abc(data, verify_stack=True)


def test_parse_abc_accepts_exception_handler_join_after_convert_b_in_verifier_mode() -> (
    None
):
    code = bytes(
        [
            Opcode.PushTrue.value,
            Opcode.Jump.value,
            *_i24(5),
            Opcode.ConvertB.value,
            Opcode.Jump.value,
            *_i24(0),
            Opcode.Pop.value,
            Opcode.ReturnVoid.value,
        ]
    )
    data = _abc_with_single_method_and_body(
        param_count=0,
        method_flags=0,
        num_locals=0,
        max_stack=1,
        code=code,
        exception_entries=[(0, 10, 5, 0, 0)],
    )
    abc = parse_abc(data, verify_stack=True)
    assert len(abc.methods) == 1
    assert abc.methods[0].body is not None


def test_parse_abc_relaxed_verifier_accepts_exception_handler_join_stack_type_mismatch() -> (
    None
):
    code = bytes(
        [
            Opcode.PushTrue.value,
            Opcode.Jump.value,
            *_i24(5),
            Opcode.Nop.value,
            Opcode.Jump.value,
            *_i24(0),
            Opcode.Pop.value,
            Opcode.ReturnVoid.value,
        ]
    )
    data = _abc_with_single_method_and_body(
        param_count=0,
        method_flags=0,
        num_locals=0,
        max_stack=1,
        code=code,
        exception_entries=[(0, 10, 5, 0, 0)],
    )
    with pytest.raises(InvalidABCCodeError, match="stack type mismatch"):
        parse_abc(data, verify_stack=True)
    abc = parse_abc(data, verify_stack=True, verify_relaxed=True)
    assert len(abc.methods) == 1
    assert abc.methods[0].body is not None


def test_parse_abc_rejects_convert_s_string_vs_number_join_in_verifier_mode() -> None:
    code = bytes(
        [
            Opcode.PushTrue.value,
            Opcode.IfTrue.value,
            *_i24(6),
            Opcode.PushNull.value,
            Opcode.ConvertS.value,
            Opcode.Jump.value,
            *_i24(2),
            Opcode.PushInt.value,
            1,
            Opcode.Pop.value,
            Opcode.ReturnVoid.value,
        ]
    )
    data = _abc_with_single_method_and_body(
        param_count=0, method_flags=0, num_locals=0, max_stack=1, code=code
    )
    with pytest.raises(InvalidABCCodeError, match="stack type mismatch"):
        parse_abc(data, verify_stack=True)


def test_parse_abc_rejects_convert_b_boolean_vs_number_join_in_verifier_mode() -> None:
    code = bytes(
        [
            Opcode.PushTrue.value,
            Opcode.IfTrue.value,
            *_i24(6),
            Opcode.PushNull.value,
            Opcode.ConvertB.value,
            Opcode.Jump.value,
            *_i24(2),
            Opcode.PushInt.value,
            1,
            Opcode.Pop.value,
            Opcode.ReturnVoid.value,
        ]
    )
    data = _abc_with_single_method_and_body(
        param_count=0, method_flags=0, num_locals=0, max_stack=1, code=code
    )
    with pytest.raises(InvalidABCCodeError, match="stack type mismatch"):
        parse_abc(data, verify_stack=True)


def test_parse_abc_rejects_getglobalscope_object_vs_number_join_in_verifier_mode() -> (
    None
):
    code = bytes(
        [
            Opcode.PushTrue.value,
            Opcode.IfTrue.value,
            *_i24(5),
            Opcode.GetGlobalScope.value,
            Opcode.Jump.value,
            *_i24(2),
            Opcode.PushByte.value,
            1,
            Opcode.Pop.value,
            Opcode.ReturnVoid.value,
        ]
    )
    data = _abc_with_single_method_and_body(
        param_count=0, method_flags=0, num_locals=0, max_stack=1, code=code
    )
    with pytest.raises(InvalidABCCodeError, match="stack type mismatch"):
        parse_abc(data, verify_stack=True)


def test_parse_abc_rejects_getscopeobject_object_vs_number_join_in_verifier_mode() -> (
    None
):
    code = bytes(
        [
            Opcode.PushTrue.value,
            Opcode.IfTrue.value,
            *_i24(6),
            Opcode.GetScopeObject.value,
            0,
            Opcode.Jump.value,
            *_i24(2),
            Opcode.PushByte.value,
            1,
            Opcode.Pop.value,
            Opcode.ReturnVoid.value,
        ]
    )
    data = _abc_with_single_method_and_body(
        param_count=0,
        method_flags=0,
        num_locals=0,
        max_stack=1,
        init_scope_depth=1,
        max_scope_depth=1,
        code=code,
    )
    with pytest.raises(InvalidABCCodeError, match="stack type mismatch"):
        parse_abc(data, verify_stack=True)


def test_parse_abc_rejects_convert_o_object_vs_number_join_in_verifier_mode() -> None:
    code = bytes(
        [
            Opcode.PushTrue.value,
            Opcode.IfTrue.value,
            *_i24(6),
            Opcode.PushNull.value,
            Opcode.ConvertO.value,
            Opcode.Jump.value,
            *_i24(2),
            Opcode.PushByte.value,
            1,
            Opcode.Pop.value,
            Opcode.ReturnVoid.value,
        ]
    )
    data = _abc_with_single_method_and_body(
        param_count=0, method_flags=0, num_locals=0, max_stack=1, code=code
    )
    with pytest.raises(InvalidABCCodeError, match="stack type mismatch"):
        parse_abc(data, verify_stack=True)


def test_parse_abc_rejects_scope_slot_string_vs_object_join_in_verifier_mode() -> None:
    code = bytes(
        [
            Opcode.PushTrue.value,
            Opcode.IfTrue.value,
            *_i24(10),
            Opcode.PushNull.value,
            Opcode.ConvertS.value,
            Opcode.PushScope.value,
            Opcode.GetScopeObject.value,
            0,
            Opcode.PopScope.value,
            Opcode.Jump.value,
            *_i24(2),
            Opcode.NewObject.value,
            0,
            Opcode.Pop.value,
            Opcode.ReturnVoid.value,
        ]
    )
    data = _abc_with_single_method_and_body(
        param_count=0,
        method_flags=0,
        num_locals=0,
        max_stack=1,
        init_scope_depth=0,
        max_scope_depth=1,
        code=code,
    )
    with pytest.raises(InvalidABCCodeError, match="stack type mismatch"):
        parse_abc(data, verify_stack=True)


def test_parse_abc_rejects_callproperty_static_boolean_vs_number_join_in_verifier_mode() -> (
    None
):
    code = bytes(
        [
            Opcode.PushTrue.value,
            Opcode.IfTrue.value,
            *_i24(10),
            Opcode.NewObject.value,
            0,
            Opcode.PushNull.value,
            Opcode.CallProperty.value,
            1,
            1,
            Opcode.Jump.value,
            *_i24(2),
            Opcode.PushByte.value,
            1,
            Opcode.Pop.value,
            Opcode.ReturnVoid.value,
        ]
    )
    data = _abc_with_qname_multiname_and_body(
        name="hasOwnProperty", code=code, max_stack=2, num_locals=0
    )
    with pytest.raises(InvalidABCCodeError, match="stack type mismatch"):
        parse_abc(data, verify_stack=True)


def test_parse_abc_accepts_callproperty_runtime_name_vs_number_join_in_verifier_mode() -> (
    None
):
    code = bytes(
        [
            Opcode.PushTrue.value,
            Opcode.IfTrue.value,
            *_i24(9),
            Opcode.PushNull.value,
            Opcode.PushNull.value,
            Opcode.CallProperty.value,
            1,
            0,
            Opcode.Jump.value,
            *_i24(2),
            Opcode.PushByte.value,
            1,
            Opcode.Pop.value,
            Opcode.ReturnVoid.value,
        ]
    )
    data = _abc_with_rtqname_multiname_and_body(code=code, max_stack=2)
    abc = parse_abc(data, verify_stack=True)
    assert len(abc.methods) == 1
    assert abc.methods[0].body is not None


def test_parse_abc_accepts_callproperty_tostring_with_wrong_arity_as_any_join() -> None:
    code = bytes(
        [
            Opcode.PushTrue.value,
            Opcode.IfTrue.value,
            *_i24(11),
            Opcode.PushNull.value,
            Opcode.ConvertS.value,
            Opcode.PushByte.value,
            1,
            Opcode.CallProperty.value,
            1,
            1,
            Opcode.Jump.value,
            *_i24(2),
            Opcode.PushByte.value,
            1,
            Opcode.Pop.value,
            Opcode.ReturnVoid.value,
        ]
    )
    data = _abc_with_qname_multiname_and_body(name="toString", code=code, max_stack=2)
    abc = parse_abc(data, verify_stack=True)
    assert len(abc.methods) == 1
    assert abc.methods[0].body is not None


def test_parse_abc_rejects_callproperty_string_charcodeat_vs_boolean_join() -> None:
    code = bytes(
        [
            Opcode.PushTrue.value,
            Opcode.IfTrue.value,
            *_i24(11),
            Opcode.PushNull.value,
            Opcode.ConvertS.value,
            Opcode.PushByte.value,
            0,
            Opcode.CallProperty.value,
            1,
            1,
            Opcode.Jump.value,
            *_i24(1),
            Opcode.PushTrue.value,
            Opcode.Pop.value,
            Opcode.ReturnVoid.value,
        ]
    )
    data = _abc_with_qname_multiname_and_body(name="charCodeAt", code=code, max_stack=2)
    with pytest.raises(InvalidABCCodeError, match="stack type mismatch"):
        parse_abc(data, verify_stack=True)


def test_parse_abc_rejects_callmethod_declared_number_vs_boolean_join() -> None:
    code = bytes(
        [
            Opcode.PushTrue.value,
            Opcode.IfTrue.value,
            *_i24(8),
            Opcode.PushNull.value,
            Opcode.CallMethod.value,
            1,
            0,
            Opcode.Jump.value,
            *_i24(1),
            Opcode.PushTrue.value,
            Opcode.Pop.value,
            Opcode.ReturnVoid.value,
        ]
    )
    data = _abc_with_two_methods_and_declared_return_type(
        return_type_name="Number", code=code, max_stack=2
    )
    with pytest.raises(InvalidABCCodeError, match="stack type mismatch"):
        parse_abc(data, verify_stack=True)


def test_parse_abc_rejects_callstatic_declared_string_vs_boolean_join() -> None:
    code = bytes(
        [
            Opcode.PushTrue.value,
            Opcode.IfTrue.value,
            *_i24(8),
            Opcode.PushNull.value,
            Opcode.CallStatic.value,
            1,
            0,
            Opcode.Jump.value,
            *_i24(1),
            Opcode.PushTrue.value,
            Opcode.Pop.value,
            Opcode.ReturnVoid.value,
        ]
    )
    data = _abc_with_two_methods_and_declared_return_type(
        return_type_name="String", code=code, max_stack=2
    )
    with pytest.raises(InvalidABCCodeError, match="stack type mismatch"):
        parse_abc(data, verify_stack=True)


def test_parse_abc_accepts_callmethod_any_result_vs_boolean_join() -> None:
    code = bytes(
        [
            Opcode.PushTrue.value,
            Opcode.IfTrue.value,
            *_i24(8),
            Opcode.PushNull.value,
            Opcode.CallMethod.value,
            0,
            0,
            Opcode.Jump.value,
            *_i24(1),
            Opcode.PushTrue.value,
            Opcode.Pop.value,
            Opcode.ReturnVoid.value,
        ]
    )
    data = _abc_with_two_methods_and_declared_return_type(
        return_type_name="Number", code=code, max_stack=2
    )
    abc = parse_abc(data, verify_stack=True)
    assert len(abc.methods) == 2
    assert abc.methods[0].body is not None


def test_parse_abc_rejects_getproperty_string_length_vs_boolean_join() -> None:
    code = bytes(
        [
            Opcode.PushTrue.value,
            Opcode.IfTrue.value,
            *_i24(8),
            Opcode.PushNull.value,
            Opcode.ConvertS.value,
            Opcode.GetProperty.value,
            1,
            Opcode.Jump.value,
            *_i24(1),
            Opcode.PushTrue.value,
            Opcode.Pop.value,
            Opcode.ReturnVoid.value,
        ]
    )
    data = _abc_with_qname_multiname_and_body(name="length", code=code, max_stack=2)
    with pytest.raises(InvalidABCCodeError, match="stack type mismatch"):
        parse_abc(data, verify_stack=True)


def test_parse_abc_accepts_getproperty_runtime_name_vs_boolean_join() -> None:
    code = bytes(
        [
            Opcode.PushTrue.value,
            Opcode.IfTrue.value,
            *_i24(8),
            Opcode.PushNull.value,
            Opcode.PushNull.value,
            Opcode.GetProperty.value,
            1,
            Opcode.Jump.value,
            *_i24(1),
            Opcode.PushTrue.value,
            Opcode.Pop.value,
            Opcode.ReturnVoid.value,
        ]
    )
    data = _abc_with_rtqname_multiname_and_body(code=code, max_stack=2)
    abc = parse_abc(data, verify_stack=True)
    assert len(abc.methods) == 1
    assert abc.methods[0].body is not None


def test_parse_abc_rejects_exception_join_local_any_pollution_with_precise_merge() -> (
    None
):
    code = bytes(
        [
            Opcode.PushTrue.value,
            Opcode.IfTrue.value,
            *_i24(8),
            Opcode.PushByte.value,
            1,
            Opcode.SetLocal0.value,
            Opcode.GetLocal1.value,
            Opcode.Jump.value,
            *_i24(5),
            Opcode.PushTrue.value,
            Opcode.Jump.value,
            *_i24(6),
            Opcode.Pop.value,
            Opcode.GetLocal0.value,
            Opcode.Jump.value,
            *_i24(0),
            Opcode.Pop.value,
            Opcode.ReturnVoid.value,
        ]
    )
    data = _abc_with_single_method_and_body(
        param_count=0,
        method_flags=0,
        num_locals=2,
        max_stack=1,
        code=code,
        exception_entries=[(0, 18, 18, 0, 0)],
    )
    with pytest.raises(InvalidABCCodeError, match="stack type mismatch"):
        parse_abc(data, verify_profile="strict_precise_joins")


@pytest.mark.parametrize(
    "scenario", _LOOKUPSWITCH_PROFILE_SCENARIOS, ids=lambda scenario: scenario.id
)
def test_parse_abc_exception_lookupswitch_cross_matrix_under_profiles(
    scenario: _LookupswitchProfileScenario,
) -> None:
    data = _abc_with_exception_lookupswitch_cross_matrix_payload()
    kwargs: dict[str, Any] = {"verify_profile": scenario.profile}
    if scenario.strict_lookupswitch is not None:
        kwargs["strict_lookupswitch"] = scenario.strict_lookupswitch
    if scenario.lattice_any_policy is not None:
        kwargs["lattice_any_policy"] = scenario.lattice_any_policy
    if scenario.expected_error is not None:
        with pytest.raises(InvalidABCCodeError, match=scenario.expected_error):
            parse_abc(
                data,
                verify_profile=scenario.profile,
                strict_lookupswitch=scenario.strict_lookupswitch,
                lattice_any_policy=scenario.lattice_any_policy,
            )
    else:
        abc = parse_abc(data, **kwargs)
        assert len(abc.methods) == 1


def test_parse_abc_rejects_add_number_vs_boolean_join_in_verifier_mode() -> None:
    code = bytes(
        [
            Opcode.PushTrue.value,
            Opcode.IfTrue.value,
            *_i24(9),
            Opcode.PushInt.value,
            1,
            Opcode.PushInt.value,
            1,
            Opcode.Add.value,
            Opcode.Jump.value,
            *_i24(1),
            Opcode.PushTrue.value,
            Opcode.Pop.value,
            Opcode.ReturnVoid.value,
        ]
    )
    data = _abc_with_single_method_and_body(
        param_count=0, method_flags=0, num_locals=0, max_stack=2, code=code
    )
    with pytest.raises(InvalidABCCodeError, match="stack type mismatch"):
        parse_abc(data, verify_stack=True)


def test_parse_abc_accepts_add_string_join_with_convert_s_in_verifier_mode() -> None:
    code = bytes(
        [
            Opcode.PushTrue.value,
            Opcode.IfTrue.value,
            *_i24(9),
            Opcode.PushNull.value,
            Opcode.ConvertS.value,
            Opcode.PushNull.value,
            Opcode.ConvertS.value,
            Opcode.Add.value,
            Opcode.Jump.value,
            *_i24(2),
            Opcode.PushNull.value,
            Opcode.ConvertS.value,
            Opcode.Pop.value,
            Opcode.ReturnVoid.value,
        ]
    )
    data = _abc_with_single_method_and_body(
        param_count=0, method_flags=0, num_locals=0, max_stack=2, code=code
    )
    abc = parse_abc(data, verify_stack=True)
    assert len(abc.methods) == 1
    assert abc.methods[0].body is not None


def test_parse_abc_rejects_add_string_vs_number_join_in_verifier_mode() -> None:
    code = bytes(
        [
            Opcode.PushTrue.value,
            Opcode.IfTrue.value,
            *_i24(9),
            Opcode.PushNull.value,
            Opcode.ConvertS.value,
            Opcode.PushNull.value,
            Opcode.ConvertS.value,
            Opcode.Add.value,
            Opcode.Jump.value,
            *_i24(2),
            Opcode.PushInt.value,
            1,
            Opcode.Pop.value,
            Opcode.ReturnVoid.value,
        ]
    )
    data = _abc_with_single_method_and_body(
        param_count=0, method_flags=0, num_locals=0, max_stack=2, code=code
    )
    with pytest.raises(InvalidABCCodeError, match="stack type mismatch"):
        parse_abc(data, verify_stack=True)


def test_parse_abc_rejects_newobject_vs_newarray_join_in_verifier_mode() -> None:
    code = bytes(
        [
            Opcode.PushTrue.value,
            Opcode.IfTrue.value,
            *_i24(6),
            Opcode.NewObject.value,
            0,
            Opcode.Jump.value,
            *_i24(2),
            Opcode.NewArray.value,
            0,
            Opcode.Pop.value,
            Opcode.ReturnVoid.value,
        ]
    )
    data = _abc_with_single_method_and_body(
        param_count=0, method_flags=0, num_locals=0, max_stack=1, code=code
    )
    with pytest.raises(InvalidABCCodeError, match="stack type mismatch"):
        parse_abc(data, verify_stack=True)


def test_parse_abc_accepts_exception_handler_join_after_pop_newarray_in_verifier_mode() -> (
    None
):
    code = bytes(
        [
            Opcode.NewArray.value,
            0,
            Opcode.Jump.value,
            *_i24(7),
            Opcode.Pop.value,
            Opcode.NewArray.value,
            0,
            Opcode.Jump.value,
            *_i24(0),
            Opcode.Pop.value,
            Opcode.ReturnVoid.value,
        ]
    )
    data = _abc_with_single_method_and_body(
        param_count=0,
        method_flags=0,
        num_locals=0,
        max_stack=1,
        code=code,
        exception_entries=[(0, 13, 6, 0, 0)],
    )
    abc = parse_abc(data, verify_stack=True)
    assert len(abc.methods) == 1
    assert abc.methods[0].body is not None


def test_parse_abc_relaxed_verifier_accepts_exception_handler_array_vs_number_join() -> (
    None
):
    code = bytes(
        [
            Opcode.NewArray.value,
            0,
            Opcode.Jump.value,
            *_i24(7),
            Opcode.Pop.value,
            Opcode.PushInt.value,
            1,
            Opcode.Jump.value,
            *_i24(0),
            Opcode.Pop.value,
            Opcode.ReturnVoid.value,
        ]
    )
    data = _abc_with_single_method_and_body(
        param_count=0,
        method_flags=0,
        num_locals=0,
        max_stack=1,
        code=code,
        exception_entries=[(0, 13, 6, 0, 0)],
    )
    with pytest.raises(InvalidABCCodeError, match="stack type mismatch"):
        parse_abc(data, verify_stack=True)
    abc = parse_abc(data, verify_stack=True, verify_relaxed=True)
    assert len(abc.methods) == 1
    assert abc.methods[0].body is not None


def test_parse_abc_rejects_constructprop_object_vs_number_join_in_verifier_mode() -> (
    None
):
    code = bytes(
        [
            Opcode.PushTrue.value,
            Opcode.IfTrue.value,
            *_i24(9),
            Opcode.PushNull.value,
            Opcode.PushNull.value,
            Opcode.ConstructProp.value,
            1,
            0,
            Opcode.Jump.value,
            *_i24(2),
            Opcode.PushByte.value,
            1,
            Opcode.Pop.value,
            Opcode.ReturnVoid.value,
        ]
    )
    data = _abc_with_rtqname_multiname_and_body(code=code, max_stack=2)
    with pytest.raises(InvalidABCCodeError, match="stack type mismatch"):
        parse_abc(data, verify_stack=True)


def test_parse_abc_accepts_constructprop_object_join_with_newobject_in_verifier_mode() -> (
    None
):
    code = bytes(
        [
            Opcode.PushTrue.value,
            Opcode.IfTrue.value,
            *_i24(9),
            Opcode.PushNull.value,
            Opcode.PushNull.value,
            Opcode.ConstructProp.value,
            1,
            0,
            Opcode.Jump.value,
            *_i24(2),
            Opcode.NewObject.value,
            0,
            Opcode.Pop.value,
            Opcode.ReturnVoid.value,
        ]
    )
    data = _abc_with_rtqname_multiname_and_body(code=code, max_stack=2)
    abc = parse_abc(data, verify_stack=True)
    assert len(abc.methods) == 1
    assert abc.methods[0].body is not None


def test_parse_abc_rejects_applytype_object_vs_number_join_in_verifier_mode() -> None:
    code = bytes(
        [
            Opcode.PushTrue.value,
            Opcode.IfTrue.value,
            *_i24(8),
            Opcode.PushNull.value,
            Opcode.PushNull.value,
            Opcode.ApplyType.value,
            1,
            Opcode.Jump.value,
            *_i24(2),
            Opcode.PushByte.value,
            1,
            Opcode.Pop.value,
            Opcode.ReturnVoid.value,
        ]
    )
    data = _abc_with_single_method_and_body(
        param_count=0, method_flags=0, num_locals=0, max_stack=2, code=code
    )
    with pytest.raises(InvalidABCCodeError, match="stack type mismatch"):
        parse_abc(data, verify_stack=True)


def test_parse_abc_accepts_applytype_object_join_with_newobject_in_verifier_mode() -> (
    None
):
    code = bytes(
        [
            Opcode.PushTrue.value,
            Opcode.IfTrue.value,
            *_i24(8),
            Opcode.PushNull.value,
            Opcode.PushNull.value,
            Opcode.ApplyType.value,
            1,
            Opcode.Jump.value,
            *_i24(2),
            Opcode.NewObject.value,
            0,
            Opcode.Pop.value,
            Opcode.ReturnVoid.value,
        ]
    )
    data = _abc_with_single_method_and_body(
        param_count=0, method_flags=0, num_locals=0, max_stack=2, code=code
    )
    abc = parse_abc(data, verify_stack=True)
    assert len(abc.methods) == 1
    assert abc.methods[0].body is not None


def test_parse_abc_rejects_multi_exception_handler_type_fan_in_mismatch_in_verifier_mode() -> (
    None
):
    code = bytes(
        [
            Opcode.PushNull.value,
            Opcode.Jump.value,
            *_i24(10),
            Opcode.ConvertS.value,
            Opcode.Jump.value,
            *_i24(5),
            Opcode.ConvertB.value,
            Opcode.Jump.value,
            *_i24(0),
            Opcode.Pop.value,
            Opcode.ReturnVoid.value,
        ]
    )
    data = _abc_with_single_method_and_body(
        param_count=0,
        method_flags=0,
        num_locals=0,
        max_stack=1,
        code=code,
        exception_entries=[(0, 15, 5, 0, 0), (0, 15, 10, 0, 0)],
    )
    with pytest.raises(InvalidABCCodeError, match="stack type mismatch"):
        parse_abc(data, verify_stack=True)


def test_parse_abc_relaxed_verifier_accepts_multi_exception_handler_type_fan_in_mismatch() -> (
    None
):
    code = bytes(
        [
            Opcode.PushNull.value,
            Opcode.Jump.value,
            *_i24(10),
            Opcode.ConvertS.value,
            Opcode.Jump.value,
            *_i24(5),
            Opcode.ConvertB.value,
            Opcode.Jump.value,
            *_i24(0),
            Opcode.Pop.value,
            Opcode.ReturnVoid.value,
        ]
    )
    data = _abc_with_single_method_and_body(
        param_count=0,
        method_flags=0,
        num_locals=0,
        max_stack=1,
        code=code,
        exception_entries=[(0, 15, 5, 0, 0), (0, 15, 10, 0, 0)],
    )
    with pytest.raises(InvalidABCCodeError, match="stack type mismatch"):
        parse_abc(data, verify_stack=True)
    abc = parse_abc(data, verify_stack=True, verify_relaxed=True)
    assert len(abc.methods) == 1
    assert abc.methods[0].body is not None


def test_parse_abc_accepts_multi_exception_handler_same_type_join_in_verifier_mode() -> (
    None
):
    code = bytes(
        [
            Opcode.PushTrue.value,
            Opcode.Jump.value,
            *_i24(10),
            Opcode.ConvertB.value,
            Opcode.Jump.value,
            *_i24(5),
            Opcode.ConvertB.value,
            Opcode.Jump.value,
            *_i24(0),
            Opcode.Pop.value,
            Opcode.ReturnVoid.value,
        ]
    )
    data = _abc_with_single_method_and_body(
        param_count=0,
        method_flags=0,
        num_locals=0,
        max_stack=1,
        code=code,
        exception_entries=[(0, 15, 5, 0, 0), (0, 15, 10, 0, 0)],
    )
    abc = parse_abc(data, verify_stack=True)
    assert len(abc.methods) == 1
    assert abc.methods[0].body is not None


_RUNTIME_MULTINAME_CALL_OPCODES = [
    pytest.param(Opcode.CallProperty, id="callproperty"),
    pytest.param(Opcode.CallPropLex, id="callproplex"),
    pytest.param(Opcode.CallPropVoid, id="callpropvoid"),
    pytest.param(Opcode.CallSuper, id="callsuper"),
    pytest.param(Opcode.CallSuperVoid, id="callsupervoid"),
    pytest.param(Opcode.ConstructProp, id="constructprop"),
]


@pytest.mark.parametrize("opcode", _RUNTIME_MULTINAME_CALL_OPCODES)
def test_parse_abc_rejects_runtime_multiname_call_underflow_in_verifier_mode(
    opcode: Opcode,
) -> None:
    code = bytes([Opcode.PushNull.value, opcode.value, 1, 0, Opcode.ReturnVoid.value])
    data = _abc_with_rtqname_multiname_and_body(code=code, max_stack=1)
    with pytest.raises(InvalidABCCodeError, match="stack underflow"):
        parse_abc(data, verify_stack=True)


def test_parse_abc_accepts_runtime_multiname_call_when_runtime_name_is_present_in_verifier_mode() -> (
    None
):
    code = bytes(
        [
            Opcode.PushNull.value,
            Opcode.PushNull.value,
            Opcode.CallProperty.value,
            1,
            0,
            Opcode.Pop.value,
            Opcode.ReturnVoid.value,
        ]
    )
    data = _abc_with_rtqname_multiname_and_body(code=code, max_stack=2)
    abc = parse_abc(data, verify_stack=True)
    assert len(abc.methods) == 1
    assert abc.methods[0].body is not None


def test_parse_abc_keeps_runtime_multiname_underflow_unchecked_when_verifier_disabled() -> (
    None
):
    code = bytes(
        [
            Opcode.PushNull.value,
            Opcode.CallProperty.value,
            1,
            0,
            Opcode.ReturnVoid.value,
        ]
    )
    data = _abc_with_rtqname_multiname_and_body(code=code, max_stack=1)
    abc = parse_abc(data, verify_stack=False)
    assert len(abc.methods) == 1
    assert abc.methods[0].body is not None


def test_parse_abc_rejects_istypelate_stack_underflow_in_verifier_mode() -> None:
    data = _abc_with_single_method_and_body(
        param_count=0,
        method_flags=0,
        num_locals=0,
        max_stack=2,
        code=bytes(
            [Opcode.PushNull.value, Opcode.IsTypeLate.value, Opcode.ReturnVoid.value]
        ),
    )
    with pytest.raises(InvalidABCCodeError, match="stack underflow"):
        parse_abc(data, verify_stack=True)


def test_parse_abc_rejects_astypelate_stack_underflow_in_verifier_mode() -> None:
    data = _abc_with_single_method_and_body(
        param_count=0,
        method_flags=0,
        num_locals=0,
        max_stack=2,
        code=bytes(
            [Opcode.PushNull.value, Opcode.AsTypeLate.value, Opcode.ReturnVoid.value]
        ),
    )
    with pytest.raises(InvalidABCCodeError, match="stack underflow"):
        parse_abc(data, verify_stack=True)


def test_parse_abc_accepts_istypelate_with_two_operands_in_verifier_mode() -> None:
    data = _abc_with_single_method_and_body(
        param_count=0,
        method_flags=0,
        num_locals=0,
        max_stack=2,
        code=bytes(
            [
                Opcode.PushNull.value,
                Opcode.PushNull.value,
                Opcode.IsTypeLate.value,
                Opcode.Pop.value,
                Opcode.ReturnVoid.value,
            ]
        ),
    )
    abc = parse_abc(data, verify_stack=True)
    assert len(abc.methods) == 1
    assert abc.methods[0].body is not None


def test_parse_abc_accepts_astypelate_with_two_operands_in_verifier_mode() -> None:
    data = _abc_with_single_method_and_body(
        param_count=0,
        method_flags=0,
        num_locals=0,
        max_stack=2,
        code=bytes(
            [
                Opcode.PushNull.value,
                Opcode.PushNull.value,
                Opcode.AsTypeLate.value,
                Opcode.Pop.value,
                Opcode.ReturnVoid.value,
            ]
        ),
    )
    abc = parse_abc(data, verify_stack=True)
    assert len(abc.methods) == 1
    assert abc.methods[0].body is not None


def test_parse_abc_rejects_li8_stack_underflow_in_verifier_mode() -> None:
    data = _abc_with_single_method_and_body(
        param_count=0,
        method_flags=0,
        num_locals=0,
        max_stack=1,
        code=bytes([Opcode.Li8.value, Opcode.ReturnVoid.value]),
    )
    with pytest.raises(InvalidABCCodeError, match="stack underflow"):
        parse_abc(data, verify_stack=True)


def test_parse_abc_rejects_si8_stack_underflow_in_verifier_mode() -> None:
    data = _abc_with_single_method_and_body(
        param_count=0,
        method_flags=0,
        num_locals=0,
        max_stack=1,
        code=bytes([Opcode.PushNull.value, Opcode.Si8.value, Opcode.ReturnVoid.value]),
    )
    with pytest.raises(InvalidABCCodeError, match="stack underflow"):
        parse_abc(data, verify_stack=True)


def test_parse_abc_accepts_getouterscope_stack_effect_in_verifier_mode() -> None:
    data = _abc_with_single_method_and_body(
        param_count=0,
        method_flags=0,
        num_locals=0,
        max_stack=1,
        code=bytes(
            [Opcode.GetOuterScope.value, 0, Opcode.Pop.value, Opcode.ReturnVoid.value]
        ),
    )
    abc = parse_abc(data, verify_stack=True)
    assert len(abc.methods) == 1
    assert abc.methods[0].body is not None


def test_parse_abc_rejects_lf32_stack_underflow_in_verifier_mode() -> None:
    data = _abc_with_single_method_and_body(
        param_count=0,
        method_flags=0,
        num_locals=0,
        max_stack=1,
        code=bytes([Opcode.Lf32.value, Opcode.ReturnVoid.value]),
    )
    with pytest.raises(InvalidABCCodeError, match="stack underflow"):
        parse_abc(data, verify_stack=True)


def test_parse_abc_accepts_timestamp_stack_effect_in_verifier_mode() -> None:
    data = _abc_with_single_method_and_body(
        param_count=0,
        method_flags=0,
        num_locals=0,
        max_stack=1,
        code=bytes([Opcode.Timestamp.value, Opcode.Pop.value, Opcode.ReturnVoid.value]),
    )
    abc = parse_abc(data, verify_stack=True)
    assert len(abc.methods) == 1
    assert abc.methods[0].body is not None


def test_parse_abc_accepts_bkpt_no_stack_effect_in_verifier_mode() -> None:
    data = _abc_with_single_method_and_body(
        param_count=0,
        method_flags=0,
        num_locals=0,
        max_stack=0,
        code=bytes([Opcode.Bkpt.value, Opcode.ReturnVoid.value]),
    )
    abc = parse_abc(data, verify_stack=True)
    assert len(abc.methods) == 1
    assert abc.methods[0].body is not None


def test_parse_abc_accepts_bkptline_no_stack_effect_in_verifier_mode() -> None:
    data = _abc_with_single_method_and_body(
        param_count=0,
        method_flags=0,
        num_locals=0,
        max_stack=0,
        code=bytes([Opcode.BkptLine.value, 1, Opcode.ReturnVoid.value]),
    )
    abc = parse_abc(data, verify_stack=True)
    assert len(abc.methods) == 1
    assert abc.methods[0].body is not None


def test_parse_abc_relaxed_verifier_accepts_stack_type_mismatch_on_join() -> None:
    code = bytes(
        [
            Opcode.PushTrue.value,
            Opcode.IfTrue.value,
            *_i24(5),
            Opcode.PushNull.value,
            Opcode.Jump.value,
            *_i24(2),
            Opcode.PushByte.value,
            1,
            Opcode.Pop.value,
            Opcode.ReturnVoid.value,
        ]
    )
    data = _abc_with_single_method_and_body(
        param_count=0, method_flags=0, num_locals=0, max_stack=1, code=code
    )
    abc = parse_abc(data, verify_stack=True, verify_relaxed=True)
    assert len(abc.methods) == 1
    assert abc.methods[0].body is not None


def test_parse_abc_relaxed_verifier_accepts_contextual_underflow() -> None:
    code = bytes([Opcode.GetSlot.value, 1, Opcode.Pop.value, Opcode.ReturnVoid.value])
    data = _abc_with_single_method_and_body(
        param_count=0, method_flags=0, num_locals=0, max_stack=1, code=code
    )
    with pytest.raises(InvalidABCCodeError, match="stack underflow"):
        parse_abc(data, verify_stack=True)
    abc = parse_abc(data, verify_stack=True, verify_relaxed=True)
    assert len(abc.methods) == 1
    assert abc.methods[0].body is not None


def test_parse_abc_relaxed_verifier_does_not_surface_tuple_index_for_dup_underflow() -> (
    None
):
    data = _abc_with_single_method_and_body(
        param_count=0,
        method_flags=0,
        num_locals=0,
        max_stack=2,
        code=bytes([Opcode.Dup.value, Opcode.ReturnVoid.value]),
    )
    with pytest.raises(InvalidABCCodeError, match="stack underflow"):
        parse_abc(data, verify_stack=True)
    try:
        parse_abc(data, verify_stack=True, verify_relaxed=True)
    except InvalidABCCodeError as exc:
        assert "tuple index out of range" not in str(exc)


def test_parse_abc_relaxed_verifier_does_not_surface_tuple_index_for_swap_underflow() -> (
    None
):
    data = _abc_with_single_method_and_body(
        param_count=0,
        method_flags=0,
        num_locals=0,
        max_stack=2,
        code=bytes([Opcode.PushNull.value, Opcode.Swap.value, Opcode.ReturnVoid.value]),
    )
    with pytest.raises(InvalidABCCodeError, match="stack underflow"):
        parse_abc(data, verify_stack=True)
    try:
        parse_abc(data, verify_stack=True, verify_relaxed=True)
    except InvalidABCCodeError as exc:
        assert "tuple index out of range" not in str(exc)


@pytest.mark.parametrize("fixture_name", ["abcdump.abc", "Test.abc"])
def test_parse_abc_relaxed_verifier_does_not_surface_tuple_index_errors_on_samples(
    fixture_name: str,
) -> None:
    fixture = Path(__file__).resolve().parents[4] / "fixtures" / "abc" / fixture_name
    data = fixture.read_bytes()
    try:
        parse_abc(data, verify_stack=True, verify_relaxed=True)
    except InvalidABCCodeError as exc:
        assert "tuple index out of range" not in str(exc)


def test_parse_abc_relaxed_verifier_accepts_stack_depth_mismatch_on_lookupswitch_join() -> (
    None
):
    code = bytes(
        [
            Opcode.PushByte.value,
            0,
            Opcode.LookupSwitch.value,
            *_i24(0),
            0,
            *_i24(6),
            Opcode.PushByte.value,
            1,
            Opcode.Jump.value,
            *_i24(0),
            Opcode.ReturnVoid.value,
        ]
    )
    data = _abc_with_single_method_and_body(
        param_count=0, method_flags=0, num_locals=0, max_stack=2, code=code
    )
    with pytest.raises(InvalidABCCodeError, match="stack depth mismatch"):
        parse_abc(data, verify_stack=True)
    abc = parse_abc(data, verify_stack=True, verify_relaxed=True)
    assert len(abc.methods) == 1
    assert abc.methods[0].body is not None


def test_parse_abc_relaxed_verifier_accepts_exception_handler_join_stack_depth_mismatch() -> (
    None
):
    data = _abc_with_single_method_and_body(
        param_count=0,
        method_flags=0,
        num_locals=0,
        max_stack=1,
        code=bytes([Opcode.Nop.value, Opcode.ReturnVoid.value]),
        exception_entries=[(0, 1, 1, 0, 0)],
    )
    with pytest.raises(InvalidABCCodeError, match="stack depth mismatch"):
        parse_abc(data, verify_stack=True)
    abc = parse_abc(data, verify_stack=True, verify_relaxed=True)
    assert len(abc.methods) == 1
    assert abc.methods[0].body is not None


def test_parse_abc_relaxed_verifier_accepts_abcdump_fixture_stack_join() -> None:
    fixture = Path(__file__).resolve().parents[4] / "fixtures" / "abc" / "abcdump.abc"
    data = fixture.read_bytes()
    abc = parse_abc(data, verify_stack=True, verify_relaxed=True)
    assert len(abc.methods) > 0


def test_parse_abc_rejects_getglobalscope_max_stack_exceeded_in_verifier_mode() -> None:
    data = _abc_with_single_method_and_body(
        param_count=0,
        method_flags=0,
        num_locals=0,
        max_stack=0,
        code=bytes([Opcode.GetGlobalScope.value, Opcode.ReturnVoid.value]),
    )
    with pytest.raises(InvalidABCCodeError, match="max_stack"):
        parse_abc(data, verify_stack=True)


def test_parse_abc_rejects_dxnslate_stack_underflow_in_verifier_mode() -> None:
    data = _abc_with_single_method_and_body(
        param_count=0,
        method_flags=0,
        num_locals=0,
        max_stack=1,
        code=bytes([Opcode.DxnsLate.value, Opcode.ReturnVoid.value]),
    )
    with pytest.raises(InvalidABCCodeError, match="stack underflow"):
        parse_abc(data, verify_stack=True)


def test_parse_abc_strict_stack_only_accepts_test_fixture_with_invalid_branch_target() -> (
    None
):
    fixture = Path(__file__).resolve().parents[4] / "fixtures" / "abc" / "Test.abc"
    data = fixture.read_bytes()
    with pytest.raises(InvalidABCCodeError, match="Invalid branch target offset"):
        parse_abc(data, verify_stack=True)
    abc = parse_abc(
        data,
        verify_stack=True,
        verify_branch_targets=False,
        verify_stack_semantics=True,
    )
    assert len(abc.methods) > 0


@pytest.mark.parametrize("fixture_name", ["abcdump.abc", "builtin.abc"])
def test_parse_abc_strict_branch_only_accepts_samples_with_stack_underflow(
    fixture_name: str,
) -> None:
    fixture = Path(__file__).resolve().parents[4] / "fixtures" / "abc" / fixture_name
    data = fixture.read_bytes()
    with pytest.raises(
        InvalidABCCodeError, match="stack underflow|Invalid branch target offset"
    ):
        parse_abc(data, verify_stack=True)
    abc = parse_abc(
        data,
        verify_stack=False,
        verify_branch_targets=True,
        verify_stack_semantics=False,
        verify_relaxed=True,
    )
    assert len(abc.methods) > 0


def test_parse_abc_branch_only_still_rejects_invalid_branch_target() -> None:
    fixture = Path(__file__).resolve().parents[4] / "fixtures" / "abc" / "Test.abc"
    data = fixture.read_bytes()
    with pytest.raises(InvalidABCCodeError, match="Invalid branch target offset"):
        parse_abc(
            data,
            verify_stack=False,
            verify_branch_targets=True,
            verify_stack_semantics=False,
            verify_relaxed=False,
        )
