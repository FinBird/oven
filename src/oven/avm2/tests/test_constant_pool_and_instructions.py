import pytest
from oven.avm2 import ABCReader, ConstantPool, Instruction, MethodBody
from oven.avm2.constant_pool import Multiname, MultinameRef, NamespaceInfo, NamespaceSet
from oven.avm2.enums import (
    ConstantKind,
    Index,
    MultinameKind,
    NamespaceKind,
    Opcode,
    TraitKind,
)
from oven.avm2.exceptions import InvalidABCCodeError
from oven.avm2.methods import DefaultValue, MethodFlags, MethodInfo, MethodParam


def test_constant_pool_resolve_indices_and_multinames() -> None:
    pool = ConstantPool(
        ints=[-10, 0, 10],
        uints=[10, 20, 30],
        doubles=[0.1, 0.2, 0.3],
        strings=["hello", "world", "flash.display", "ÄãºÃÊÀ½ç"],
        namespaces=[
            NamespaceInfo(NamespaceKind.PRIVATE_NS, 1),
            NamespaceInfo(NamespaceKind.PACKAGE_NAMESPACE, 3),
        ],
        namespace_sets=[
            NamespaceSet([NamespaceInfo(NamespaceKind.PRIVATE_NS, 1)]),
            NamespaceSet(
                [
                    NamespaceInfo(NamespaceKind.PRIVATE_NS, 1),
                    NamespaceInfo(NamespaceKind.PACKAGE_NAMESPACE, 3),
                ]
            ),
        ],
        multinames=[
            Multiname(MultinameKind.QNAME, {"namespace": Index(2), "name": Index(1)}),
            Multiname(MultinameKind.QNAME, {"namespace": Index(1), "name": Index(2)}),
        ],
    )
    assert pool.resolve_index(1, "string") == "hello"
    assert pool.resolve_index(4, "string") == "ÄãºÃÊÀ½ç"
    assert pool.resolve_index(1, "int") == -10
    assert pool.resolve_index(3, "uint") == 30
    assert pool.resolve_index(2, "double") == pytest.approx(0.2)
    assert pool.multinames[0].kind == MultinameKind.QNAME


def test_method_info_supports_optional_and_named_parameters() -> None:
    params = [
        MethodParam(kind=1, name="paramA", default_value=None),
        MethodParam(
            kind=2,
            name="paramB",
            default_value=DefaultValue(ConstantKind.INT, Index(1)),
        ),
    ]
    info = MethodInfo(
        name="myFunc",
        params=params,
        return_type="void",
        flags=MethodFlags.HAS_OPTIONAL | MethodFlags.HAS_PARAM_NAMES,
    )
    assert info.name == "myFunc"
    assert info.return_type == "void"
    assert info.flags & MethodFlags.HAS_OPTIONAL
    assert info.flags & MethodFlags.HAS_PARAM_NAMES
    assert info.params[1].default_value is not None

    dv = info.params[1].default_value
    if isinstance(dv, DefaultValue) and dv.kind == ConstantKind.INT:
        if isinstance(dv.value, Index):
            assert dv.value.value == 1


def test_parse_lookupswitch_operands_preserves_offsets() -> None:
    reader = ABCReader(b"")
    data = bytes(
        [Opcode.LookupSwitch.value, 100, 0, 0, 2, 10, 0, 0, 20, 0, 0, 251, 255, 255]
    )
    instructions = reader.parse_instructions(
        data, ConstantPool([], [], [], [], [], [], [])
    )
    assert len(instructions) == 1
    inst = instructions[0]
    assert inst.opcode == Opcode.LookupSwitch
    assert inst.operands == [100, 2, [10, 20, -5]]


def test_parse_multiname_operands_keep_kind_metadata() -> None:
    reader = ABCReader(b"")
    namespace = NamespaceInfo(NamespaceKind.NAMESPACE, 1)
    namespace_set = NamespaceSet([namespace])
    pool = ConstantPool(
        ints=[],
        uints=[],
        doubles=[],
        strings=["name"],
        namespaces=[namespace],
        namespace_sets=[namespace_set],
        multinames=[
            Multiname(MultinameKind.RTQNAME, {"name": Index(1)}),
            Multiname(MultinameKind.RTQNAMEL, {}),
            Multiname(
                MultinameKind.MULTINAME,
                {"name": Index(1), "namespace_set": namespace_set},
            ),
            Multiname(MultinameKind.MULTINAMEL, {"namespace_set": namespace_set}),
        ],
    )
    data = bytes(
        [
            Opcode.GetProperty.value,
            1,
            Opcode.GetProperty.value,
            2,
            Opcode.GetProperty.value,
            3,
            Opcode.GetProperty.value,
            4,
            Opcode.ReturnVoid.value,
        ]
    )
    instructions = reader.parse_instructions(data, pool)
    names = [i.operands[0] for i in instructions if i.opcode == Opcode.GetProperty]
    assert all((isinstance(name, MultinameRef) for name in names))
    from oven.avm2.constant_pool import MultinameRef as MultinameRefType

    multiname_refs = [n for n in names if isinstance(n, MultinameRefType)]
    assert len(multiname_refs) >= 4
    assert multiname_refs[0].kind == MultinameKind.RTQNAME
    assert multiname_refs[1].kind == MultinameKind.RTQNAMEL
    assert multiname_refs[2].kind == MultinameKind.MULTINAME
    assert multiname_refs[3].kind == MultinameKind.MULTINAMEL


@pytest.mark.parametrize("kind", [MultinameKind.RTQNAMEL, MultinameKind.RTQNAMELA])
def test_read_constant_pool_accepts_runtime_late_multiname_kinds(
    kind: MultinameKind,
) -> None:
    data = bytes([1, 1, 1, 1, 1, 1, 2, kind.value])
    reader = ABCReader(data)
    pool = reader.read_constant_pool()
    assert len(pool.multinames) == 1
    assert pool.multinames[0].kind == kind


def test_read_constant_pool_relaxed_accepts_unknown_namespace_kind() -> None:
    data = bytes([1, 1, 1, 2, 1, ord("x"), 2, 9, 1, 1, 1])
    pool = ABCReader(data, verify_relaxed=True).read_constant_pool()
    assert len(pool.namespaces) == 1
    assert pool.namespaces[0].kind == NamespaceKind.NAMESPACE
    assert pool.namespaces[0].name == 1


def test_read_constant_pool_relaxed_coerces_invalid_namespace_set_index() -> None:
    data = bytes(
        [1, 1, 1, 2, 1, ord("x"), 2, NamespaceKind.NAMESPACE.value, 1, 2, 1, 5, 1]
    )
    pool = ABCReader(data, verify_relaxed=True).read_constant_pool()
    assert len(pool.namespace_sets) == 1
    assert len(pool.namespace_sets[0].namespaces) == 1
    coerced = pool.namespace_sets[0].namespaces[0]
    assert coerced.kind == NamespaceKind.NAMESPACE
    assert coerced.name == 0


def test_read_trait_slot_and_method_with_metadata() -> None:
    pool = ConstantPool(
        ints=[1],
        uints=[],
        doubles=[],
        strings=["", "test", "name", "metadata"],
        namespaces=[NamespaceInfo(NamespaceKind.PRIVATE_NS, 1)],
        namespace_sets=[],
        multinames=[
            Multiname(MultinameKind.QNAME, {"namespace": Index(0), "name": Index(0)}),
            Multiname(MultinameKind.QNAME, {"namespace": Index(1), "name": Index(2)}),
        ],
    )
    reader = ABCReader(b"")
    reader.data = bytes([1, 0, 3, 0, 1, 1])
    reader.pos = 0
    slot = reader.read_trait(pool)
    assert slot.kind == TraitKind.SLOT
    assert slot.data is not None
    assert slot.data["slot_id"] == 3
    assert slot.data["value"] is not None
    reader.data = bytes([1, 65, 5, 2, 1, 4])
    reader.pos = 0
    method = reader.read_trait(pool)
    assert method.kind == TraitKind.METHOD
    assert method.data is not None
    assert method.data["disp_id"] == 5
    method_data = method.data
    if "method" in method_data:
        assert method_data["method"].value == 2
    assert method.metadata == ["metadata"]


def test_parser_raises_for_invalid_opcode_and_truncated_operands() -> None:
    reader = ABCReader(b"")
    with pytest.raises(InvalidABCCodeError):
        reader.parse_instructions(b"\xff", None)
    with pytest.raises(InvalidABCCodeError):
        reader.parse_instructions(bytes([Opcode.CallProperty.value, 1]), None)
    with pytest.raises(ValueError):
        ABCReader(b"\x81\x81\x81\x81\x81").read_u30()


def test_method_body_serialization_contains_expected_tokens() -> None:
    instructions = [
        Instruction(Opcode.GetLocal0, [], 0),
        Instruction(Opcode.PushScope, [], 1),
        Instruction(Opcode.PushString, [1], 2),
        Instruction(Opcode.PushInt, [1], 4),
        Instruction(Opcode.Add, [], 6),
        Instruction(Opcode.ReturnValue, [], 7),
    ]
    body = MethodBody(
        method=0,
        max_stack=2,
        num_locals=1,
        init_scope_depth=1,
        max_scope_depth=2,
        code=b"",
        exceptions=[],
        traits=[],
        instructions=instructions,
    )
    pool = ConstantPool(
        ints=[42],
        uints=[],
        doubles=[],
        strings=["Hello", "World"],
        namespaces=[],
        namespace_sets=[],
        multinames=[
            Multiname(MultinameKind.QNAME, {"namespace": Index(0), "name": Index(0)}),
            Multiname(MultinameKind.QNAME, {"namespace": Index(0), "name": Index(1)}),
        ],
    )
    standard = body.to_string(pool, show_offsets=True)
    as_calls = body.to_function_calls(pool)
    assert "GetLocal0" in standard
    assert "PushScope" in standard
    assert "Add" in standard
    assert "GetLocal0()" in as_calls
    assert "Add()" in as_calls


def test_constant_pool_to_dict_keeps_namespace_set_and_multiname_indices_stable() -> (
    None
):
    ns_private = NamespaceInfo(NamespaceKind.PRIVATE_NS, 1)
    ns_package = NamespaceInfo(NamespaceKind.PACKAGE_NAMESPACE, 2)
    ns_set = NamespaceSet([ns_private, ns_package])
    multiname = Multiname(
        MultinameKind.MULTINAME, {"name": Index(1), "namespace_set": ns_set}
    )
    pool = ConstantPool(
        ints=[],
        uints=[],
        doubles=[],
        strings=["name", "pkg"],
        namespaces=[ns_private, ns_package],
        namespace_sets=[ns_set],
        multinames=[multiname],
    )
    serialized = pool.to_dict(pool)
    assert serialized["namespace_sets"] == [[1, 2]]
    multiname_dict = serialized["multinames"][0]
    assert multiname_dict.get("namespace_set", multiname_dict.get("namespace")) == 1
