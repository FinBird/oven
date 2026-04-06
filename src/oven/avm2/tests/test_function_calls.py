from oven.avm2 import ABCReader, ConstantPool, Instruction, MethodBody, Opcode
from oven.avm2.constant_pool import Multiname, NamespaceInfo
from oven.avm2.enums import Index, MultinameKind, NamespaceKind


def test_serialize_instructions_as_function_calls_contains_opcode_names() -> None:
    instructions = [
        Instruction(Opcode.GetLocal0, [], 0),
        Instruction(Opcode.PushScope, [], 1),
        Instruction(Opcode.PushString, ["Hello World"], 2),
        Instruction(Opcode.PushByte, [5], 4),
        Instruction(Opcode.Add, [], 6),
        Instruction(Opcode.ReturnValue, [], 7),
    ]
    reader = ABCReader(b"")
    function_calls = reader.serialize_instructions_as_function_calls(instructions, None)
    assert "GetLocal0()" in function_calls
    assert "PushScope()" in function_calls
    assert 'PushString("Hello World")' in function_calls
    assert "PushByte(5)" in function_calls
    assert "Add()" in function_calls
    assert "ReturnValue()" in function_calls


def test_serialize_instructions_as_function_calls_resolves_constant_pool_values() -> (
    None
):
    pool = ConstantPool(
        ints=[],
        uints=[],
        doubles=[],
        strings=["", "Message", "Result", "trace"],
        namespaces=[],
        namespace_sets=[],
        multinames=[
            Multiname(MultinameKind.QNAME, {"namespace": Index(0), "name": Index(1)}),
            Multiname(MultinameKind.QNAME, {"namespace": Index(0), "name": Index(4)}),
        ],
    )
    instructions = [
        Instruction(Opcode.GetLocal0, [], 0),
        Instruction(Opcode.PushScope, [], 1),
        Instruction(Opcode.PushString, [2], 2),
        Instruction(Opcode.PushByte, [42], 4),
        Instruction(Opcode.CallProperty, [0, 1], 6),
        Instruction(Opcode.ReturnVoid, [], 8),
    ]
    reader = ABCReader(b"")
    standard = reader.serialize_instructions_to_string(instructions, pool, True)
    function_calls = reader.serialize_instructions_as_function_calls(instructions, pool)
    assert "Message" in standard
    assert "CallProperty" in function_calls
    assert "ReturnVoid()" in function_calls


def test_method_body_to_function_calls_emits_expected_lines() -> None:
    instructions = [
        Instruction(Opcode.GetLocal0, [], 0),
        Instruction(Opcode.PushScope, [], 1),
        Instruction(Opcode.PushString, ["Hello"], 2),
        Instruction(Opcode.PushByte, [5], 4),
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
    output = body.to_function_calls()
    assert "GetLocal0()" in output
    assert 'PushString("Hello")' in output
    assert "Add()" in output
    assert "ReturnValue()" in output


def test_serialization_resolves_string_multiname_namespace_and_lookupswitch() -> None:
    namespace = NamespaceInfo(NamespaceKind.NAMESPACE, 1)
    pool = ConstantPool(
        ints=[7],
        uints=[8],
        doubles=[1.5],
        strings=["name", "dbg"],
        namespaces=[namespace],
        namespace_sets=[],
        multinames=[
            Multiname(MultinameKind.QNAME, {"namespace": Index(1), "name": Index(1)})
        ],
    )
    instructions = [
        Instruction(Opcode.PushString, [2], 0),
        Instruction(Opcode.GetProperty, [1], 2),
        Instruction(Opcode.PushNamespace, [1], 4),
        Instruction(Opcode.LookupSwitch, [10, 1, [20, -3]], 6),
        Instruction(Opcode.DebugFile, [2], 12),
    ]
    reader = ABCReader(b"")
    standard = reader.serialize_instructions_to_string(instructions, pool, True)
    function_calls = reader.serialize_instructions_as_function_calls(instructions, pool)
    assert '"dbg"' in standard
    assert '"dbg"' in function_calls
    assert "NAMESPACE::name" in standard
    assert "NAMESPACE::name" in function_calls
    assert "[20,-3]" in standard
    assert "[20,-3]" in function_calls
