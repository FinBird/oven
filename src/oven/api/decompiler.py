from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import ClassVar, Iterable

from oven.avm2.enums import ConstantKind, DefaultValue, Instruction, TraitKind
from oven.avm2.file import ABCFile
from oven.avm2.methods import MethodBody, MethodFlags, MethodInfo
from oven.avm2.transform.ast_build import ASTBuild
from oven.avm2.transform.ast_normalize import ASTNormalize
from oven.avm2.transform.cfg_dialect import AVM2ControlFlowAdapter
from oven.avm2.transform.nf_transform import NFNormalize
from oven.avm2.transform.semantic_passes import AstConstructorCleanupPass, AstSemanticNormalizePass
from oven.core.ast import Node
from oven.core.pipeline import Pipeline
from oven.core.transform.cfg_build import CFGBuild
from oven.core.transform.cfg_reduce import CFGReduce
from oven.core.transform.propagate_constants import PropagateConstants
from oven.core.transform.propagate_labels import PropagateLabels


_AVM2_CFG_ADAPTER = AVM2ControlFlowAdapter()


def _method_to_nf(body: MethodBody) -> Node:
    pipeline = Pipeline(
        [
            ASTBuild({"tolerate_stack_underflow": True}),
            ASTNormalize(),
            PropagateConstants(),
            PropagateLabels(),
            CFGBuild(adapter=_AVM2_CFG_ADAPTER),
            CFGReduce(),
            NFNormalize(),
        ]
    )
    try:
        return pipeline.transform(body.instructions, body)
    except (KeyError, ValueError):
        # Keep decompilation output available for malformed/obfuscated control
        # flow by falling back to the low-level AST when CFG structuring fails.
        ast, _, _ = ASTBuild({"tolerate_stack_underflow": True}).transform(body.instructions, body)
        fallback = Node("begin")
        fallback.children = [child for child in ast.children if isinstance(child, Node)]
        if not fallback.children:
            fallback.children = [Node("stack_hole", ["decompile_fallback"], {"synthetic": 1})]
        # Ensure parent/index invariants for downstream passes on fallback path.
        fallback.normalize_hierarchy()
        return fallback


@dataclass(slots=True)
class SwitchSection:
    label: Node
    body: list[object]
    terminal: str | None
    fallthrough_to: int | None
    origin_order: int
    synthetic_break: bool = False


@dataclass(slots=True)
class MethodContext:
    method_index: int
    method_name: str
    owner_kind: str
    owner_name: str
    param_names: tuple[str, ...]
    has_param_names: bool
    num_locals: int
    owner_index: int | None = None
    slot_name_map: dict[int, str] = field(default_factory=dict)
    global_slot_name_map: dict[int, str] = field(default_factory=dict)
    avm2_constant_value_map: dict[str, int] = field(default_factory=dict)

    @property
    def param_register_start(self) -> int:
        return 1 if self.owner_kind == "instance" else 0


@dataclass(slots=True, frozen=True)
class LocalDeclaration:
    index: int
    name: str
    type_name: str


@dataclass(slots=True)
class _MethodOwnerRef:
    owner_kind: str
    owner_name: str
    method_name: str
    owner_index: int | None = None


_IDENTIFIER_SANITIZE_RE = re.compile(r"[^0-9A-Za-z_$]+")
_FIELD_IDENTIFIER_RE = re.compile(r"^[A-Za-z_$][0-9A-Za-z_$]*$")
_OWNER_PRIORITY = {"unknown": 0, "script": 1, "class": 2, "instance": 3}
_CONVERT_MULTINAME_ALIASES = {
    "i": "int",
    "u": "uint",
    "d": "Number",
    "s": "String",
    "o": "Object",
}
_NAMESPACE_KIND_PREFIXES: tuple[str, ...] = (
    "PACKAGE_NAMESPACE",
    "PACKAGE_INTERNAL_NS",
    "PRIVATE_NS",
    "PROTECTED_NAMESPACE",
    "EXPLICIT_NAMESPACE",
    "STATIC_PROTECTED_NS",
    "NAMESPACE",
)
_OWNER_SLOT_NAME_CACHE_ATTR = "_cached_owner_slot_name_maps"
_SCRIPT_SLOT_NAME_CACHE_ATTR = "_cached_script_slot_name_map"
_SCRIPT_CONSTANT_VALUE_CACHE_ATTR = "_cached_script_constant_value_map"
_METHOD_OWNER_MAP_CACHE_ATTR = "_cached_method_owner_map"


def _normalize_int_format(int_format: str) -> str:
    token = str(int_format).strip().lower()
    if token in {"dec", "decimal"}:
        return "dec"
    if token in {"hex", "hexadecimal"}:
        return "hex"
    raise ValueError(f"unsupported integer format: {int_format!r} (expected 'dec' or 'hex')")


@dataclass(slots=True)
class _ClassMethodEntry:
    method_index: int
    method_name: str
    trait_kind: object | None
    static: bool
    is_constructor: bool = False


@dataclass(slots=True, frozen=True)
class _ClassLayoutBlock:
    class_name: str
    source: str
    package_parts: tuple[str, ...] = ()
    kind: str = "class"


def _index_value(value: object) -> int | None:
    if isinstance(value, int):
        return value
    index = getattr(value, "value", None)
    if isinstance(index, int):
        return index
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed


def _namespace_kind_from_qualified_name(raw_name: object) -> str | None:
    text = str(raw_name).strip()
    if not text:
        return None
    if text.startswith("[NsSet]::"):
        text = text.split("::", 1)[1]
    if "::" not in text:
        return None
    prefix = text.split("::", 1)[0].strip()
    if prefix in _NAMESPACE_KIND_PREFIXES:
        return prefix
    return None


def _strip_known_namespace_prefix(text: str) -> str:
    token = text.strip()
    if token.startswith("[NsSet]::"):
        token = token.split("::", 1)[1]

    namespace_kind = _namespace_kind_from_qualified_name(token)
    if namespace_kind is not None and "::" in token:
        token = token.split("::", 1)[1]

    while token.startswith("::"):
        token = token[2:]
    while "::::" in token:
        token = token.replace("::::", "::")
    return token


def _visibility_from_namespace_kind(namespace_kind: str | None, *, for_class: bool = False) -> str:
    if namespace_kind == "PRIVATE_NS":
        return "internal" if for_class else "private"
    if namespace_kind in {"PROTECTED_NAMESPACE", "STATIC_PROTECTED_NS"}:
        return "internal" if for_class else "protected"
    if namespace_kind == "PACKAGE_INTERNAL_NS":
        return "internal"
    return "public"


@lru_cache(maxsize=8192)
def _short_multiname_text(text: str) -> str:
    token = _strip_known_namespace_prefix(text)
    if "::" in token:
        token = token.rsplit("::", 1)[1]

    if token.startswith("convert_"):
        alias = _CONVERT_MULTINAME_ALIASES.get(token.removeprefix("convert_"))
        if alias is not None:
            return alias

    if token.startswith("void_i"):
        suffix = token[6:]
        if suffix and suffix.isdigit():
            return "void"

    return token


def _short_multiname(raw_name: object) -> str:
    text = str(raw_name).strip()
    if not text:
        return ""
    return _short_multiname_text(text)


def _sanitize_identifier(raw: object, fallback: str, used: set[str]) -> str:
    token = str(raw).strip()
    if not token or token == "*":
        token = fallback
    token = token.replace("::", "_").replace(".", "_")
    token = _IDENTIFIER_SANITIZE_RE.sub("_", token)
    token = token.strip("_")
    if not token:
        token = fallback
    if token[0].isdigit():
        token = f"_{token}"
    if token in ABCFile.AS3_KEYWORDS or token == "this":
        token = f"{token}_"

    candidate = token
    suffix = 1
    while candidate in used:
        candidate = f"{token}_{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def _trait_method_index(trait: object) -> int | None:
    data = getattr(trait, "data", None)
    if not isinstance(data, dict):
        return None

    kind = getattr(trait, "kind", None)
    if kind in (TraitKind.METHOD, TraitKind.GETTER, TraitKind.SETTER):
        return _index_value(data.get("method"))
    if kind == TraitKind.FUNCTION:
        return _index_value(data.get("function"))

    for key in ("method", "function"):
        if key in data:
            idx = _index_value(data[key])
            if idx is not None:
                return idx
    return None


def _append_slot_names_from_traits(slot_name_map: dict[int, str], traits: object) -> None:
    if not isinstance(traits, list):
        return
    for trait in traits:
        kind = getattr(trait, "kind", None)
        if kind not in (TraitKind.SLOT, TraitKind.CONST):
            continue
        data = getattr(trait, "data", None)
        if not isinstance(data, dict):
            continue
        slot_id = _index_value(data.get("slot_id"))
        if slot_id is None or slot_id <= 0:
            continue
        slot_name = _short_multiname(getattr(trait, "name", ""))
        if not slot_name:
            continue
        slot_name_map.setdefault(slot_id, slot_name)


def _build_owner_slot_name_map(abc: ABCFile, owner_kind: str, owner_index: int | None) -> dict[int, str]:
    if owner_index is None or owner_index < 0:
        return {}

    cache = getattr(abc, _OWNER_SLOT_NAME_CACHE_ATTR, None)
    if not isinstance(cache, dict):
        cache = {}
        setattr(abc, _OWNER_SLOT_NAME_CACHE_ATTR, cache)
    cache_key = (owner_kind, owner_index)
    cached = cache.get(cache_key)
    if isinstance(cached, dict):
        return cached

    slot_name_map: dict[int, str] = {}
    if owner_kind == "instance":
        if owner_index < len(abc.instances):
            _append_slot_names_from_traits(slot_name_map, getattr(abc.instances[owner_index], "traits", None))
        if owner_index < len(abc.classes):
            _append_slot_names_from_traits(slot_name_map, getattr(abc.classes[owner_index], "traits", None))
        cache[cache_key] = slot_name_map
        return slot_name_map
    if owner_kind == "class":
        if owner_index < len(abc.classes):
            _append_slot_names_from_traits(slot_name_map, getattr(abc.classes[owner_index], "traits", None))
        if owner_index < len(abc.instances):
            _append_slot_names_from_traits(slot_name_map, getattr(abc.instances[owner_index], "traits", None))
        cache[cache_key] = slot_name_map
        return slot_name_map
    if owner_kind == "script" and owner_index < len(abc.scripts):
        _append_slot_names_from_traits(slot_name_map, getattr(abc.scripts[owner_index], "traits", None))
        cache[cache_key] = slot_name_map
        return slot_name_map
    cache[cache_key] = slot_name_map
    return slot_name_map


def _build_script_slot_name_map(abc: ABCFile) -> dict[int, str]:
    cached = getattr(abc, _SCRIPT_SLOT_NAME_CACHE_ATTR, None)
    if isinstance(cached, dict):
        return cached

    slot_name_map: dict[int, str] = {}
    for script in abc.scripts:
        _append_slot_names_from_traits(slot_name_map, getattr(script, "traits", None))
    setattr(abc, _SCRIPT_SLOT_NAME_CACHE_ATTR, slot_name_map)
    return slot_name_map


def _resolve_default_int_constant(abc: ABCFile, raw_value: object) -> int | None:
    if not isinstance(raw_value, DefaultValue):
        return None
    if raw_value.kind not in {ConstantKind.INT, ConstantKind.UINT}:
        return None

    direct = _index_value(raw_value.value)
    if direct is None:
        return None

    # Trait default constants are stored as pool references in practice.
    kind_hint = "uint" if raw_value.kind == ConstantKind.UINT else "int"
    resolved = abc.constant_pool.resolve_index(direct, kind_hint)
    resolved_int = _index_value(resolved)
    if resolved_int is None:
        # Fallback for corpora that already store raw immediate values.
        return direct
    return resolved_int


def _build_script_constant_value_map(abc: ABCFile) -> dict[str, int]:
    cached = getattr(abc, _SCRIPT_CONSTANT_VALUE_CACHE_ATTR, None)
    if isinstance(cached, dict):
        return cached

    values: dict[str, int] = {}
    for script in abc.scripts:
        traits = getattr(script, "traits", None)
        if not isinstance(traits, list):
            continue
        for trait in traits:
            name = _short_multiname(getattr(trait, "name", ""))
            if not name.startswith("CONSTANT_"):
                continue
            data = getattr(trait, "data", None)
            if not isinstance(data, dict):
                continue
            resolved = _resolve_default_int_constant(abc, data.get("value"))
            if resolved is None:
                continue
            values.setdefault(name, resolved)
    setattr(abc, _SCRIPT_CONSTANT_VALUE_CACHE_ATTR, values)
    return values


def _register_owner(
    mapping: dict[int, _MethodOwnerRef],
    method_index: int | None,
    owner_kind: str,
    owner_name: str,
    method_name: str,
    owner_index: int | None = None,
) -> None:
    if method_index is None or method_index < 0:
        return
    current = mapping.get(method_index)
    if current is None or _OWNER_PRIORITY.get(owner_kind, 0) > _OWNER_PRIORITY.get(current.owner_kind, 0):
        mapping[method_index] = _MethodOwnerRef(
            owner_kind=owner_kind,
            owner_name=owner_name,
            method_name=method_name,
            owner_index=owner_index,
        )


def _build_method_owner_map(abc: ABCFile) -> dict[int, _MethodOwnerRef]:
    cached = getattr(abc, _METHOD_OWNER_MAP_CACHE_ATTR, None)
    if isinstance(cached, dict):
        return cached

    owners: dict[int, _MethodOwnerRef] = {}

    for idx, instance in enumerate(abc.instances):
        owner_name = str(getattr(instance, "name", f"instance_{idx}"))
        _register_owner(
            owners,
            _index_value(getattr(instance, "init_method", None)),
            "instance",
            owner_name,
            owner_name,
            owner_index=idx,
        )

        for trait in getattr(instance, "traits", []):
            method_index = _trait_method_index(trait)
            if method_index is None:
                continue
            method_name = _short_multiname(getattr(trait, "name", f"method_{method_index}")) or f"method_{method_index}"
            _register_owner(
                owners,
                method_index,
                "instance",
                owner_name,
                method_name,
                owner_index=idx,
            )

        cls = abc.classes[idx] if idx < len(abc.classes) else None
        if cls is not None:
            _register_owner(
                owners,
                _index_value(getattr(cls, "init_method", None)),
                "class",
                owner_name,
                "__static_init__",
                owner_index=idx,
            )
            for trait in getattr(cls, "traits", []):
                method_index = _trait_method_index(trait)
                if method_index is None:
                    continue
                method_name = _short_multiname(getattr(trait, "name", f"method_{method_index}")) or f"method_{method_index}"
                _register_owner(
                    owners,
                    method_index,
                    "class",
                    owner_name,
                    method_name,
                    owner_index=idx,
                )

    for idx, script in enumerate(abc.scripts):
        owner_name = f"script_{idx}"
        _register_owner(
            owners,
            _index_value(getattr(script, "init_method", None)),
            "script",
            owner_name,
            "__script_init__",
            owner_index=idx,
        )
        for trait in getattr(script, "traits", []):
            method_index = _trait_method_index(trait)
            if method_index is None:
                continue
            method_name = _short_multiname(getattr(trait, "name", f"method_{method_index}")) or f"method_{method_index}"
            _register_owner(
                owners,
                method_index,
                "script",
                owner_name,
                method_name,
                owner_index=idx,
            )

    setattr(abc, _METHOD_OWNER_MAP_CACHE_ATTR, owners)
    return owners


def _build_param_names(method_info: MethodInfo, owner_kind: str) -> tuple[tuple[str, ...], bool]:
    has_param_names = bool(method_info.flags & MethodFlags.HAS_PARAM_NAMES)
    used: set[str] = set()
    if owner_kind == "instance":
        used.add("this")

    names: list[str] = []
    for position, param in enumerate(method_info.params, start=1):
        raw_name = param.name if has_param_names else None
        base_name = raw_name if isinstance(raw_name, str) and raw_name.strip() else f"param{position}"
        names.append(_sanitize_identifier(base_name, f"param{position}", used))
    return tuple(names), has_param_names


def _build_method_context(
    abc: ABCFile,
    method_body: MethodBody,
    owner_map: dict[int, _MethodOwnerRef] | None = None,
) -> MethodContext:
    if owner_map is None:
        owner_map = _build_method_owner_map(abc)
    method_index = method_body.method
    method_info = abc.methods[method_index]
    owner = owner_map.get(method_index)
    owner_kind = owner.owner_kind if owner else "unknown"
    owner_name = owner.owner_name if owner else ""
    owner_index = owner.owner_index if owner else None
    default_method_name = method_info.name or f"method_{method_index}"
    method_name = owner.method_name if owner and owner.method_name else default_method_name
    param_names, has_param_names = _build_param_names(method_info, owner_kind)
    slot_name_map = _build_owner_slot_name_map(abc, owner_kind, owner_index)
    global_slot_name_map = _build_script_slot_name_map(abc)
    avm2_constant_value_map = _build_script_constant_value_map(abc)
    return MethodContext(
        method_index=method_index,
        method_name=method_name,
        owner_kind=owner_kind,
        owner_name=owner_name,
        param_names=param_names,
        has_param_names=has_param_names,
        num_locals=method_body.num_locals,
        owner_index=owner_index,
        slot_name_map=slot_name_map,
        global_slot_name_map=global_slot_name_map,
        avm2_constant_value_map=avm2_constant_value_map,
    )


def _split_qualified_name(raw_name: object, fallback: str) -> tuple[tuple[str, ...], str]:
    text = _strip_known_namespace_prefix(str(raw_name).strip())
    if not text or text == "*":
        return (), _sanitize_identifier(fallback, fallback, set())

    package_parts: list[str] = []
    class_token = text

    if "::" in text:
        namespace, class_token = text.rsplit("::", 1)
        package_parts = [segment for segment in namespace.split(".") if segment]
    elif "." in text:
        dotted_parts = [segment for segment in text.split(".") if segment]
        if len(dotted_parts) > 1:
            *package_parts, class_token = dotted_parts

    sanitized_parts: list[str] = []
    for index, segment in enumerate(package_parts, start=1):
        sanitized_parts.append(_sanitize_identifier(segment, f"pkg{index}", set()))

    class_name = _sanitize_identifier(_short_multiname(class_token) or fallback, fallback, set())
    return tuple(sanitized_parts), class_name


def _class_display_name(raw_name: object, fallback: str) -> str:
    _, class_name = _split_qualified_name(raw_name, fallback)
    return class_name


def _collect_class_method_entries(
    abc: ABCFile,
    class_index: int,
) -> tuple[tuple[str, ...], str, list[_ClassMethodEntry]]:
    instance = abc.instances[class_index]
    package_parts, class_name = _split_qualified_name(
        getattr(instance, "name", f"Class_{class_index}"),
        f"Class_{class_index}",
    )
    cls = abc.classes[class_index] if class_index < len(abc.classes) else None

    entries: list[_ClassMethodEntry] = []
    seen_method_indexes: set[int] = set()

    def _append(
        method_index: int | None,
        method_name: str,
        *,
        trait_kind: object | None,
        static: bool,
        is_constructor: bool = False,
    ) -> None:
        if method_index is None or method_index < 0:
            return
        if method_index in seen_method_indexes:
            return
        seen_method_indexes.add(method_index)
        entries.append(
            _ClassMethodEntry(
                method_index=method_index,
                method_name=method_name,
                trait_kind=trait_kind,
                static=static,
                is_constructor=is_constructor,
            )
        )

    _append(
        _index_value(getattr(instance, "init_method", None)),
        class_name,
        trait_kind=TraitKind.METHOD,
        static=False,
        is_constructor=True,
    )

    for trait in getattr(instance, "traits", []):
        method_index = _trait_method_index(trait)
        if method_index is None:
            continue
        method_name = _short_multiname(getattr(trait, "name", f"method_{method_index}")) or f"method_{method_index}"
        _append(
            method_index,
            method_name,
            trait_kind=getattr(trait, "kind", None),
            static=False,
            is_constructor=False,
        )

    if cls is not None:
        _append(
            _index_value(getattr(cls, "init_method", None)),
            "__static_init__",
            trait_kind=TraitKind.METHOD,
            static=True,
            is_constructor=False,
        )
        for trait in getattr(cls, "traits", []):
            method_index = _trait_method_index(trait)
            if method_index is None:
                continue
            method_name = _short_multiname(getattr(trait, "name", f"method_{method_index}")) or f"method_{method_index}"
            _append(
                method_index,
                method_name,
                trait_kind=getattr(trait, "kind", None),
                static=True,
                is_constructor=False,
            )

    return package_parts, class_name, entries


def _build_method_ir(
    body: MethodBody,
    *,
    style: str,
    abc: ABCFile | None = None,
    owner_map: dict[int, _MethodOwnerRef] | None = None,
    method_context: MethodContext | None = None,
) -> tuple[Node, MethodContext | None]:
    nf = _method_to_nf(body)
    context = method_context
    if context is None and abc is not None:
        context = _build_method_context(abc, body, owner_map)
    if style == "semantic":
        slot_name_map = context.slot_name_map if context is not None else None
        global_slot_name_map = context.global_slot_name_map if context is not None else None
        nf = AstSemanticNormalizePass(
            slot_name_map=slot_name_map,
            global_slot_name_map=global_slot_name_map,
            assume_normalized=True,
        ).transform(nf)
        if (
            context is not None
            and context.owner_kind == "instance"
            and context.method_name == context.owner_name
        ):
            nf = AstConstructorCleanupPass(
                owner_kind=context.owner_kind,
                owner_name=context.owner_name,
                method_name=context.method_name,
        ).transform(nf)
    return nf, context


def _instruction_get_local_index(instruction: Instruction) -> int | None:
    opcode_name = instruction.opcode.name
    if opcode_name == "GetLocal0":
        return 0
    if opcode_name == "GetLocal1":
        return 1
    if opcode_name == "GetLocal2":
        return 2
    if opcode_name == "GetLocal3":
        return 3
    if opcode_name == "GetLocal" and instruction.operands:
        operand = instruction.operands[0]
        if isinstance(operand, int):
            return operand
        parsed = _index_value(operand)
        if parsed is not None:
            return parsed
    return None


def _param_name_for_local(context: MethodContext | None, local_index: int) -> str:
    if context is not None:
        if context.owner_kind == "instance" and local_index == 0:
            return "this"
        offset = local_index - context.param_register_start
        if 0 <= offset < len(context.param_names):
            return context.param_names[offset]
    return f"local{local_index}"


def _format_fast_int_literal(value: int, int_format: str) -> str:
    if int_format == "hex":
        if value < 0:
            return f"-0x{abs(value):X}"
        return f"0x{value:X}"
    return str(value)


def _try_fast_emit_method_text(
    body: MethodBody,
    context: MethodContext | None,
    *,
    int_format: str = "dec",
) -> str | None:
    instructions = body.instructions
    if not instructions:
        return ""

    opcodes = tuple(inst.opcode.name for inst in instructions)
    if opcodes in {("ReturnVoid",), ("GetLocal0", "PushScope", "ReturnVoid")}:
        return ""

    if len(opcodes) >= 5 and opcodes[0:2] == ("GetLocal0", "PushScope") and opcodes[-2:] == ("ConstructSuper", "ReturnVoid"):
        get_local_indexes: list[int] = []
        for inst in instructions[2:-2]:
            index = _instruction_get_local_index(inst)
            if index is None:
                get_local_indexes = []
                break
            get_local_indexes.append(index)

        if get_local_indexes and get_local_indexes[0] == 0:
            arg_names = [_param_name_for_local(context, idx) for idx in get_local_indexes[1:]]
            if arg_names:
                return f"super({', '.join(arg_names)});"
            return "super();"

    if opcodes == ("GetLocal0", "PushScope", "PushFalse", "ReturnValue"):
        return "return false;"
    if opcodes == ("GetLocal0", "PushScope", "PushTrue", "ReturnValue"):
        return "return true;"
    if opcodes == ("GetLocal0", "PushScope", "PushNull", "ReturnValue"):
        return "return null;"
    if opcodes == ("GetLocal0", "PushScope", "GetLocal0", "ReturnValue"):
        return f"return {_param_name_for_local(context, 0)};"
    if opcodes == ("GetLocal0", "PushScope", "PushByte", "ReturnValue"):
        if len(instructions[2].operands) == 1 and isinstance(instructions[2].operands[0], int):
            return f"return {_format_fast_int_literal(instructions[2].operands[0], int_format)};"

    return None


def _resolve_trait_type_name(abc: ABCFile, trait: object) -> str:
    data = getattr(trait, "data", None)
    if not isinstance(data, dict):
        return "*"
    raw_type = data.get("type_name")
    if raw_type is None:
        return "*"

    type_idx = _index_value(raw_type)
    if type_idx == 0:
        return "*"

    resolved: object = raw_type
    if hasattr(raw_type, "resolve"):
        try:
            resolved = raw_type.resolve(abc.constant_pool, "multiname")
        except Exception:
            resolved = raw_type

    short = _short_multiname(resolved).strip()
    if not short:
        return "*"
    if short == "void":
        return "*"
    return short


def _resolve_default_value_expr(abc: ABCFile, default_value: DefaultValue) -> str | None:
    kind = default_value.kind
    value = default_value.value

    if kind == ConstantKind.NULL:
        return "null"
    if kind == ConstantKind.UNDEFINED:
        return "undefined"
    if kind == ConstantKind.TRUE:
        return "true"
    if kind == ConstantKind.FALSE:
        return "false"

    if kind in {ConstantKind.INT, ConstantKind.UINT, ConstantKind.DOUBLE, ConstantKind.UTF8}:
        index = _index_value(value)
        if index is None:
            if kind == ConstantKind.UTF8 and isinstance(value, str):
                return json.dumps(value, ensure_ascii=False)
            return str(value)

        if kind == ConstantKind.INT:
            return str(abc.constant_pool.resolve_index(index, "int"))
        if kind == ConstantKind.UINT:
            return str(abc.constant_pool.resolve_index(index, "uint"))
        if kind == ConstantKind.DOUBLE:
            return str(abc.constant_pool.resolve_index(index, "double"))
        text = abc.constant_pool.resolve_index(index, "string")
        return json.dumps(str(text), ensure_ascii=False)

    if kind in {
        ConstantKind.NAMESPACE,
        ConstantKind.PRIVATE_NS,
        ConstantKind.PACKAGE_NAMESPACE,
        ConstantKind.PACKAGE_INTERNAL_NS,
        ConstantKind.PROTECTED_NAMESPACE,
        ConstantKind.EXPLICIT_NAMESPACE,
        ConstantKind.STATIC_PROTECTED_NS,
    }:
        ns_index = _index_value(value)
        if ns_index is None:
            return None
        return _short_multiname(abc.constant_pool.resolve_index(ns_index, "namespace"))

    return None


def _trait_default_initializer_expr(abc: ABCFile, trait: object) -> str | None:
    data = getattr(trait, "data", None)
    if not isinstance(data, dict):
        return None

    value = data.get("value")
    if value is None:
        return None

    if isinstance(value, DefaultValue):
        return _resolve_default_value_expr(abc, value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (int, float)):
        return str(value)

    return None


def _build_class_member_lines(
    abc: ABCFile,
    *,
    instance_traits: list[object],
    class_traits: list[object],
    constructor_initializers: dict[str, str],
) -> tuple[list[str], set[str]]:
    lines: list[str] = []
    declared_names: set[str] = set()
    used_identifiers: set[str] = set()

    def _append_trait_member(trait: object, *, is_static: bool) -> None:
        kind = getattr(trait, "kind", None)
        if kind not in (TraitKind.SLOT, TraitKind.CONST):
            return

        raw_name = _short_multiname(getattr(trait, "name", "")).strip()
        if not raw_name:
            raw_name = "field"

        fallback = raw_name if raw_name else "field"
        name = _sanitize_identifier(raw_name, fallback, used_identifiers)
        if name in {"prototype", "__static_init__"}:
            return

        # 避免重复声明：如果名称已经声明过，跳过
        if name in declared_names:
            return

        type_name = _resolve_trait_type_name(abc, trait)
        init_expr = _trait_default_initializer_expr(abc, trait)
        if not is_static and init_expr is None:
            ctor_init = constructor_initializers.get(name)
            if ctor_init:
                init_expr = ctor_init

        static_kw = " static" if is_static else ""
        kind_kw = "const" if kind == TraitKind.CONST else "var"
        visibility = _visibility_from_namespace_kind(
            _namespace_kind_from_qualified_name(getattr(trait, "name", "")),
            for_class=False,
        )
        line = f"    {visibility}{static_kw} {kind_kw} {name}:{type_name}"
        if init_expr is not None:
            line += f" = {init_expr}"
        line += ";"

        lines.append(line)
        declared_names.add(name)

    for trait in instance_traits:
        _append_trait_member(trait, is_static=False)
    for trait in class_traits:
        _append_trait_member(trait, is_static=True)

    for name in sorted(constructor_initializers):
        if name in declared_names:
            continue
        value = constructor_initializers[name]
        lines.append(f"    private var {name}:* = {value};")
        declared_names.add(name)

    return lines, declared_names


def _build_class_signature(class_name: str, instance: object | None) -> str:
    implements: list[str] = []
    seen: set[str] = set()
    visibility = "public"
    extends_class = None

    if instance is not None:
        visibility = _visibility_from_namespace_kind(
            _namespace_kind_from_qualified_name(getattr(instance, "name", "")),
            for_class=True,
        )
        
        # 处理继承关系
        super_name = getattr(instance, "super_name", None)
        if super_name:
            super_token = _short_multiname(super_name).strip()
            if super_token and super_token != "*":
                # 过滤掉 Object 基类，因为它是默认继承
                if super_token != "Object":
                    extends_class = super_token
        
        # 处理接口
        interfaces = getattr(instance, "interfaces", None)
        if isinstance(interfaces, list):
            for iface in interfaces:
                token = _short_multiname(iface).strip()
                if not token or token == "*" or token in seen:
                    continue
                seen.add(token)
                implements.append(token)

    # 构建类签名
    signature_parts = [visibility, "class", class_name]
    
    if extends_class:
        signature_parts.extend(["extends", extends_class])
    
    if implements:
        signature_parts.extend(["implements", ", ".join(implements)])
    
    return " ".join(signature_parts)


def _field_initializer_name(value: object) -> str | None:
    token: object = value
    if isinstance(token, Node):
        if token.type == "string" and token.children:
            token = token.children[0]
        elif token.type in {"get_lex", "find_property", "find_property_strict"} and token.children:
            token = token.children[0]
        else:
            return None

    text = _short_multiname(token).strip()
    if not text:
        return None
    if not _FIELD_IDENTIFIER_RE.match(text):
        return None
    if text in ABCFile.AS3_KEYWORDS:
        return None
    return text


def _extract_method_field_initializers(
    nf: Node,
    *,
    style: str,
    method_context: MethodContext | None,
    int_format: str = "dec",
) -> tuple[Node, dict[str, str]]:
    if nf.type != "begin":
        return nf, {}

    emitter = AS3Emitter(style=style, method_context=method_context, int_format=int_format)
    emitter._local_name_map = emitter._build_local_name_map()

    extracted: dict[str, str] = {}
    remaining_children: list[object] = []
    had_initializer_block = False

    for child in nf.children:
        if not (isinstance(child, Node) and child.type == "field_initializers"):
            remaining_children.append(child)
            continue

        had_initializer_block = True
        for entry in child.children:
            if not isinstance(entry, Node) or entry.type != "field_initializer" or len(entry.children) < 2:
                continue
            field_name = _field_initializer_name(entry.children[0])
            if field_name is None:
                continue
            value_expr = emitter._expr(entry.children[1]).strip()
            if not value_expr:
                continue
            extracted.setdefault(field_name, value_expr)

    if not had_initializer_block:
        return nf, extracted

    cleaned = Node("begin", remaining_children, dict(nf.metadata))
    return cleaned, extracted


def _render_layout_method_signature(
    *,
    class_name: str,
    entry: _ClassMethodEntry,
    method_info: MethodInfo,
    context: MethodContext | None,
) -> str:
    if entry.is_constructor:
        return f"public function {class_name}()"
    if entry.method_name == "__static_init__":
        return "private static function __static_init__()"

    static_kw = " static" if entry.static else ""
    param_specs: list[str] = []
    for idx, param in enumerate(method_info.params, start=1):
        if context is not None and idx - 1 < len(context.param_names):
            param_name = context.param_names[idx - 1]
        else:
            param_name = f"arg{idx}"
        param_type = _short_multiname(getattr(param, "kind", "*")) or "*"
        param_specs.append(f"{param_name}:{param_type}")

    params_text = ", ".join(param_specs)
    return_type = _short_multiname(getattr(method_info, "return_type", "*")) or "*"

    if entry.trait_kind == TraitKind.GETTER:
        return f"public{static_kw} function get {entry.method_name}():{return_type}".strip()
    if entry.trait_kind == TraitKind.SETTER:
        setter_param = param_specs[0] if param_specs else "value:*"
        return f"public{static_kw} function set {entry.method_name}({setter_param}):void".strip()
    return f"public{static_kw} function {entry.method_name}({params_text}):{return_type}".strip()


@dataclass(slots=True)
class AS3Emitter:
    indent: str = "    "
    style: str = "semantic"
    method_context: MethodContext | None = None
    int_format: str = "dec"
    inline_vars: bool = False
    _TERMINAL_STMTS: tuple[str, ...] = ("break", "continue", "return_void", "return_value", "throw")
    _LOCAL_OPS: tuple[str, ...] = (
        "get_local",
        "set_local",
        "inc_local",
        "inc_local_i",
        "dec_local",
        "dec_local_i",
        "pre_increment_local",
        "post_increment_local",
        "pre_decrement_local",
        "post_decrement_local",
        "kill",
    )
    _TYPE_INFERENCE_NODE_BUDGET: int = 400
    _CALL_RESULT_TYPE_HINTS: ClassVar[dict[str, str]] = {
        "readboolean": "Boolean",
        "readbyte": "int",
        "readshort": "int",
        "readint": "int",
        "readu8": "uint",
        "readu16": "uint",
        "readu30": "uint",
        "readu32": "uint",
        "readunsignedbyte": "uint",
        "readunsignedshort": "uint",
        "readunsignedint": "uint",
        "readdouble": "Number",
        "readfloat": "Number",
        "readnumber": "Number",
        "readutf": "String",
        "readutfbytes": "String",
        "tostring": "String",
    }
    _CONVERT_RESULT_TYPES: ClassVar[dict[str, str]] = {
        "coerce_b": "Boolean",
        "convert_i": "int",
        "convert_u": "uint",
        "convert_d": "Number",
        "convert_s": "String",
        "convert_o": "Object",
    }
    _SYMBOLIC_BINARY_OPS: ClassVar[dict[str, str]] = {
        "==": "==",
        "===": "===",
        "!=": "!=",
        "!==": "!==",
        "<": "<",
        "<=": "<=",
        ">": ">",
        ">=": ">=",
    }
    _EXPR_HANDLER_MISSING: ClassVar[object] = object()
    _BINARY_META_BY_TYPE: ClassVar[dict[str, tuple[str, int]]] = {
        "||": ("||", 1),
        "logical_or": ("||", 1),
        "&&": ("&&", 2),
        "logical_and": ("&&", 2),
        "|": ("|", 3),
        "bit_or": ("|", 3),
        "^": ("^", 4),
        "bit_xor": ("^", 4),
        "&": ("&", 5),
        "bit_and": ("&", 5),
        "==": ("==", 6),
        "!=": ("!=", 6),
        "===": ("===", 6),
        "!==": ("!==", 6),
        "<": ("<", 7),
        "<=": ("<=", 7),
        ">": (">", 7),
        ">=": (">=", 7),
        "in": ("in", 7),
        "<<": ("<<", 8),
        ">>": (">>", 8),
        ">>>": (">>>", 8),
        "left_shift": ("<<", 8),
        "right_shift": (">>", 8),
        "unsigned_right_shift": (">>>", 8),
        "+": ("+", 9),
        "add": ("+", 9),
        "-": ("-", 9),
        "subtract": ("-", 9),
        "*": ("*", 10),
        "multiply": ("*", 10),
        "/": ("/", 10),
        "divide": ("/", 10),
        "%": ("%", 10),
        "modulo": ("%", 10),
    }
    _ASSOCIATIVE_BINARY_OPS: ClassVar[set[str]] = {"&&", "||", "&", "|", "^", "+", "*"}
    _AVM2_SWITCH_CASE_CONSTANTS: ClassVar[dict[str, int]] = {
        "CONSTANT_Utf8": 0x01,
        "CONSTANT_Int": 0x03,
        "CONSTANT_UInt": 0x04,
        "CONSTANT_PrivateNs": 0x05,
        "CONSTANT_Double": 0x06,
        "CONSTANT_Qname": 0x07,
        "CONSTANT_Namespace": 0x08,
        "CONSTANT_Multiname": 0x09,
        "CONSTANT_False": 0x0A,
        "CONSTANT_True": 0x0B,
        "CONSTANT_Null": 0x0C,
        "CONSTANT_QnameA": 0x0D,
        "CONSTANT_MultinameA": 0x0E,
        "CONSTANT_RTQname": 0x0F,
        "CONSTANT_RTQnameA": 0x10,
        "CONSTANT_RTQnameL": 0x11,
        "CONSTANT_RTQnameLA": 0x12,
        "CONSTANT_NameL": 0x13,
        "CONSTANT_NameLA": 0x14,
        "CONSTANT_NamespaceSet": 0x15,
        "CONSTANT_PackageNs": 0x16,
        "CONSTANT_PackageInternalNs": 0x17,
        "CONSTANT_ProtectedNs": 0x18,
        "CONSTANT_ExplicitNamespace": 0x19,
        "CONSTANT_StaticProtectedNs": 0x1A,
        # Non-standard alias observed in some ABC corpora.
        "CONSTANT_StaticProtectedNs2": 0x1B,
        "CONSTANT_MultinameL": 0x1B,
        "CONSTANT_MultinameLA": 0x1C,
        "CONSTANT_TypeName": 0x1D,
    }
    _local_name_map: dict[int, str] = field(default_factory=dict, init=False, repr=False)
    _declared_locals: list[LocalDeclaration] = field(default_factory=list, init=False, repr=False)
    _declared_local_indexes: set[int] = field(default_factory=set, init=False, repr=False)
    _expr_handler_cache: dict[str, object] = field(default_factory=dict, init=False, repr=False)
    _declared_local_types: dict[int, str] = field(default_factory=dict, init=False, repr=False)
    _inline_candidate_locals: set[int] = field(default_factory=set, init=False, repr=False)
    _inline_declared_locals: set[int] = field(default_factory=set, init=False, repr=False)

    def emit(self, node: Node) -> str:
        self._local_name_map = self._build_local_name_map()
        self._declared_locals = []
        self._declared_local_indexes = set()
        self._declared_local_types = {}
        self._inline_candidate_locals = set()
        self._inline_declared_locals = set()

        lines: list[str] = []
        if self._is_semantic_style() and node.type == "begin":
            self._declared_locals = self._build_local_declarations(node)
            self._declared_local_types = {decl.index: decl.type_name for decl in self._declared_locals}
            if self.inline_vars:
                self._inline_candidate_locals = self._plan_inline_var_indexes(node)
                hoisted = [decl for decl in self._declared_locals if decl.index not in self._inline_candidate_locals]
                self._declared_local_indexes = {decl.index for decl in hoisted}
                for decl in hoisted:
                    lines.append(f"{self._pad(0)}var {decl.name}:{decl.type_name};")
            else:
                self._declared_local_indexes = {decl.index for decl in self._declared_locals}
                for decl in self._declared_locals:
                    lines.append(f"{self._pad(0)}var {decl.name}:{decl.type_name};")

        body_lines = self._emit_block(node, 0, inline=False)
        if lines and body_lines:
            lines.append("")
        lines.extend(body_lines)
        return "\n".join(lines).strip()

    def _is_semantic_style(self) -> bool:
        return self.style == "semantic" and self.method_context is not None

    def _is_semantic_output_style(self) -> bool:
        return self.style == "semantic"

    def _build_local_name_map(self) -> dict[int, str]:
        if not self._is_semantic_style():
            return {}
        context = self.method_context
        assert context is not None

        mapping: dict[int, str] = {}
        if context.owner_kind == "instance":
            mapping[0] = "this"

        start = context.param_register_start
        for offset, name in enumerate(context.param_names):
            mapping[start + offset] = name
        return mapping

    def _is_this_register(self, index: int) -> bool:
        context = self.method_context
        return bool(context and context.owner_kind == "instance" and index == 0)

    def _is_param_register(self, index: int) -> bool:
        context = self.method_context
        if not self._is_semantic_style() or context is None:
            return False
        start = context.param_register_start
        end = start + len(context.param_names)
        return start <= index < end

    def _iter_nodes(self, root: Node) -> Iterable[Node]:
        stack: list[Node] = [root]
        while stack:
            node = stack.pop()
            yield node
            for child in reversed(node.children):
                if isinstance(child, Node):
                    stack.append(child)

    def _iter_nodes_budgeted(self, root: Node, *, budget: int) -> Iterable[Node]:
        if budget <= 0:
            return
        stack: list[Node] = [root]
        remaining = budget
        while stack and remaining > 0:
            node = stack.pop()
            yield node
            remaining -= 1
            if remaining <= 0:
                break
            for child in reversed(node.children):
                if isinstance(child, Node):
                    stack.append(child)

    def _iter_local_indexes(self, root: Node) -> Iterable[int]:
        unary_local_ops = {
            "get_local",
            "set_local",
            "inc_local",
            "inc_local_i",
            "dec_local",
            "dec_local_i",
            "pre_increment_local",
            "post_increment_local",
            "pre_decrement_local",
            "post_decrement_local",
            "kill",
        }

        for node in self._iter_nodes(root):
            if node.type in unary_local_ops and node.children:
                index = _index_value(node.children[0])
                if index is not None:
                    yield index
                continue

            if node.type in {"for_in", "for_each_in"}:
                if len(node.children) > 0:
                    value_index = _index_value(node.children[0])
                    if value_index is not None:
                        yield value_index
                if len(node.children) > 2:
                    object_index = _index_value(node.children[2])
                    if object_index is not None:
                        yield object_index
                continue

            if node.type == "has_next2" and len(node.children) >= 2:
                obj_index = _index_value(node.children[0])
                idx_index = _index_value(node.children[1])
                if obj_index is not None:
                    yield obj_index
                if idx_index is not None:
                    yield idx_index

    def _build_local_declarations(self, root: Node) -> list[LocalDeclaration]:
        if self._exceeds_type_inference_budget(root):
            local_indexes = sorted(set(self._iter_local_indexes(root)))
            # Keep performance bounded on very large methods while still
            # recovering useful type hints from the early/linear portion.
            _, inferred_types = self._analyze_locals(root, node_budget=self._TYPE_INFERENCE_NODE_BUDGET)
        else:
            local_indexes, inferred_types = self._analyze_locals(root)
        if not local_indexes:
            return []

        declarations: list[LocalDeclaration] = []
        for index in local_indexes:
            if self._is_this_register(index) or self._is_param_register(index):
                continue
            type_name = inferred_types.get(index, "*")
            declarations.append(
                LocalDeclaration(
                    index=index,
                    name=self._var_name(index),
                    type_name=type_name,
                )
            )
        return declarations

    def _plan_inline_var_indexes(self, root: Node) -> set[int]:
        if not self._is_semantic_style() or not self.inline_vars:
            return set()

        tracked = {decl.index for decl in self._declared_locals}
        if not tracked:
            return set()

        events: dict[int, dict[str, list[tuple[int, int, str, tuple[int, ...]]]]] = {
            idx: {"reads": [], "writes": []}
            for idx in tracked
        }
        first_setlocal_sources: dict[int, set[int]] = {}
        event_seq = 0
        scope_seq = 0

        def _next_seq() -> int:
            nonlocal event_seq
            event_seq += 1
            return event_seq

        def _next_scope_path(parent: tuple[int, ...]) -> tuple[int, ...]:
            nonlocal scope_seq
            scope_seq += 1
            return parent + (scope_seq,)

        def _is_descendant_scope(scope_path: tuple[int, ...], ancestor_path: tuple[int, ...]) -> bool:
            return (
                len(scope_path) >= len(ancestor_path)
                and scope_path[: len(ancestor_path)] == ancestor_path
            )

        def _record_read(local_index: int, depth: int, scope_path: tuple[int, ...]) -> int:
            bucket = events.get(local_index)
            if bucket is None:
                return -1
            seq = _next_seq()
            bucket["reads"].append((seq, depth, "read", scope_path))
            return seq

        def _record_write(local_index: int, depth: int, kind: str, scope_path: tuple[int, ...]) -> int:
            bucket = events.get(local_index)
            if bucket is None:
                return -1
            seq = _next_seq()
            bucket["writes"].append((seq, depth, kind, scope_path))
            return seq

        def _collect_expr_local_reads(value: object) -> set[int]:
            reads: set[int] = set()

            def _walk(current: object) -> None:
                if not isinstance(current, Node):
                    return
                if current.type == "get_local" and current.children:
                    local_index = _index_value(current.children[0])
                    if local_index is not None:
                        reads.add(local_index)
                for child in current.children:
                    if isinstance(child, Node):
                        _walk(child)

            _walk(value)
            return reads

        def _scan_expr(value: object, depth: int, scope_path: tuple[int, ...]) -> None:
            if not isinstance(value, Node):
                return

            if value.type == "get_local" and value.children:
                local_index = _index_value(value.children[0])
                if local_index is not None:
                    _record_read(local_index, depth, scope_path)

            elif value.type in {
                "inc_local",
                "inc_local_i",
                "dec_local",
                "dec_local_i",
                "pre_increment_local",
                "post_increment_local",
                "pre_decrement_local",
                "post_decrement_local",
                "kill",
            } and value.children:
                local_index = _index_value(value.children[0])
                if local_index is not None:
                    _record_read(local_index, depth, scope_path)
                    _record_write(local_index, depth, "other", scope_path)

            elif value.type in {"for_in", "for_each_in"}:
                loop_scope = _next_scope_path(scope_path)
                value_reg = _index_value(value.children[0]) if len(value.children) > 0 else None
                if value_reg is not None:
                    _record_write(value_reg, depth + 1, "other", loop_scope)
                object_reg = _index_value(value.children[2]) if len(value.children) > 2 else None
                if object_reg is not None:
                    _record_read(object_reg, depth + 1, loop_scope)
                if len(value.children) > 1:
                    _scan_expr(value.children[1], depth + 1, loop_scope)
                if len(value.children) > 3:
                    _scan_stmt(value.children[3], depth + 1, loop_scope)
                return

            elif value.type == "has_next2" and len(value.children) >= 2:
                obj_index = _index_value(value.children[0])
                idx_index = _index_value(value.children[1])
                if obj_index is not None:
                    _record_read(obj_index, depth, scope_path)
                    _record_write(obj_index, depth, "other", scope_path)
                if idx_index is not None:
                    _record_read(idx_index, depth, scope_path)
                    _record_write(idx_index, depth, "other", scope_path)

            for child in value.children:
                if isinstance(child, Node):
                    _scan_expr(child, depth, scope_path)

        def _scan_stmt(value: object, depth: int, scope_path: tuple[int, ...]) -> None:
            if not isinstance(value, Node):
                return

            if value.type == "begin":
                for child in value.children:
                    if isinstance(child, Node):
                        _scan_stmt(child, depth, scope_path)
                return

            if value.type == "set_local" and len(value.children) >= 2:
                local_index = _index_value(value.children[0])
                rhs = value.children[1]
                read_dependencies = _collect_expr_local_reads(rhs)
                _scan_expr(rhs, depth, scope_path)
                if local_index is not None:
                    _record_write(local_index, depth, "set_local", scope_path)
                    first_setlocal_sources.setdefault(local_index, read_dependencies)
                return

            if value.type == "if":
                if value.children:
                    _scan_expr(value.children[0], depth, scope_path)
                if len(value.children) > 1:
                    _scan_stmt(value.children[1], depth + 1, _next_scope_path(scope_path))
                if len(value.children) > 2:
                    _scan_stmt(value.children[2], depth + 1, _next_scope_path(scope_path))
                return

            if value.type == "while":
                if value.children:
                    _scan_expr(value.children[0], depth, scope_path)
                if len(value.children) > 1:
                    _scan_stmt(value.children[1], depth + 1, _next_scope_path(scope_path))
                return

            if value.type in {"for_in", "for_each_in"}:
                loop_scope = _next_scope_path(scope_path)
                value_reg = _index_value(value.children[0]) if len(value.children) > 0 else None
                if value_reg is not None:
                    _record_write(value_reg, depth + 1, "other", loop_scope)
                if len(value.children) > 1:
                    _scan_expr(value.children[1], depth + 1, loop_scope)
                object_reg = _index_value(value.children[2]) if len(value.children) > 2 else None
                if object_reg is not None:
                    _record_read(object_reg, depth + 1, loop_scope)
                if len(value.children) > 3:
                    _scan_stmt(value.children[3], depth + 1, loop_scope)
                return

            if value.type == "switch":
                if value.children:
                    _scan_expr(value.children[0], depth, scope_path)
                if len(value.children) > 1:
                    _scan_stmt(value.children[1], depth + 1, _next_scope_path(scope_path))
                return

            if value.type == "with":
                if value.children:
                    _scan_expr(value.children[0], depth, scope_path)
                if len(value.children) > 1:
                    _scan_stmt(value.children[1], depth + 1, _next_scope_path(scope_path))
                return

            for child in value.children:
                if isinstance(child, Node):
                    _scan_expr(child, depth, scope_path)

        _scan_stmt(root, depth=0, scope_path=())

        inline_candidates: set[int] = set()
        for local_index, bucket in events.items():
            writes = bucket["writes"]
            if not writes:
                continue

            first_write_seq, first_write_depth, first_write_kind, first_write_scope = min(
                writes,
                key=lambda item: item[0],
            )
            if first_write_kind != "set_local":
                continue

            reads = bucket["reads"]
            if any(read_seq < first_write_seq for read_seq, _depth, _kind, _scope in reads):
                continue

            # Avoid inline declarations that read tracked locals whose first
            # assignment only happens later (read-before-write dependency).
            read_dependencies = first_setlocal_sources.get(local_index, set())
            unsafe_dependency = False
            for source_index in read_dependencies:
                if source_index not in tracked:
                    continue
                source_writes = events[source_index]["writes"]
                if not source_writes:
                    unsafe_dependency = True
                    break
                source_first_write_seq = min(source_writes, key=lambda item: item[0])[0]
                if source_first_write_seq > first_write_seq:
                    unsafe_dependency = True
                    break
            if unsafe_dependency:
                continue

            # AS3 `var` is function-scoped: when the first write is inside a
            # nested block, force hoist if the variable can be read outside
            # that lexical subtree.
            if first_write_depth > 0 and any(
                read_seq > first_write_seq
                and not _is_descendant_scope(read_scope, first_write_scope)
                for read_seq, _depth, _kind, read_scope in reads
            ):
                continue

            inline_candidates.add(local_index)

        return inline_candidates

    def _exceeds_type_inference_budget(self, root: Node) -> bool:
        budget = self._TYPE_INFERENCE_NODE_BUDGET
        if budget <= 0:
            return True
        count = 0
        for _ in self._iter_nodes(root):
            count += 1
            if count > budget:
                return True
        return False

    def _analyze_locals(self, root: Node, node_budget: int | None = None) -> tuple[list[int], dict[int, str]]:
        local_indexes: set[int] = set()
        candidates: dict[int, set[str]] = {}
        local_type_cache: dict[int, str] = {}
        copy_edges: list[tuple[int, int, int]] = []
        first_setlocal_seq: dict[int, int] = {}
        visit_seq = 0

        def _record_type(index: int, type_name: str | None) -> None:
            if not type_name:
                return
            candidates.setdefault(index, set()).add(type_name)
            if type_name != "*":
                local_type_cache[index] = type_name

        node_iter: Iterable[Node]
        if node_budget is not None:
            node_iter = self._iter_nodes_budgeted(root, budget=node_budget)
        else:
            node_iter = self._iter_nodes(root)

        for node in node_iter:
            visit_seq += 1
            if node.type in self._LOCAL_OPS and node.children:
                index = _index_value(node.children[0])
                if index is not None:
                    local_indexes.add(index)
                    if node.type in {"inc_local_i", "dec_local_i"}:
                        _record_type(index, "int")
                    elif node.type in {
                        "inc_local",
                        "dec_local",
                        "pre_increment_local",
                        "post_increment_local",
                        "pre_decrement_local",
                        "post_decrement_local",
                    }:
                        current = local_type_cache.get(index)
                        if current in {"int", "uint", "Number"}:
                            _record_type(index, current)
                        else:
                            _record_type(index, "int")

            elif node.type in {"for_in", "for_each_in"}:
                value_index = _index_value(node.children[0]) if len(node.children) > 0 else None
                object_index = _index_value(node.children[2]) if len(node.children) > 2 else None
                if value_index is not None:
                    local_indexes.add(value_index)
                    hinted = self._normalize_type_hint(node.children[1]) if len(node.children) > 1 else None
                    if node.type == "for_in" and (hinted is None or hinted == "*"):
                        hinted = "String"
                    _record_type(value_index, hinted or "*")
                if object_index is not None:
                    local_indexes.add(object_index)

            elif node.type == "has_next2" and len(node.children) >= 2:
                obj_index = _index_value(node.children[0])
                idx_index = _index_value(node.children[1])
                if obj_index is not None:
                    local_indexes.add(obj_index)
                if idx_index is not None:
                    local_indexes.add(idx_index)

            if node.type == "set_local" and len(node.children) >= 2:
                target = _index_value(node.children[0])
                if target is None:
                    continue
                local_indexes.add(target)
                first_setlocal_seq.setdefault(target, visit_seq)
                source = self._extract_source_local_index(node.children[1])
                if source is not None:
                    copy_edges.append((target, source, visit_seq))
                inferred = self._infer_expr_type(node.children[1], local_type_cache)
                _record_type(target, inferred)

        if copy_edges:
            changed = True
            while changed:
                changed = False
                for target, source, edge_seq in copy_edges:
                    source_first_write_seq = first_setlocal_seq.get(source)
                    if source_first_write_seq is None or source_first_write_seq > edge_seq:
                        # Defensive mode for obfuscated bytecode: avoid
                        # propagating types from source locals that are only
                        # assigned after this copy site.
                        continue
                    source_types = candidates.get(source, set())
                    source_concrete = {value for value in source_types if value != "*"}
                    if len(source_concrete) != 1:
                        continue
                    propagated = next(iter(source_concrete))
                    if propagated in candidates.get(target, set()):
                        continue
                    candidates.setdefault(target, set()).add(propagated)
                    local_type_cache[target] = propagated
                    changed = True

        inferred_types: dict[int, str] = {}
        for index, types in candidates.items():
            if not types:
                continue
            concrete_types = {value for value in types if value != "*"}
            if concrete_types and concrete_types.issubset({"int", "uint", "Number"}):
                if "Number" in concrete_types:
                    inferred_types[index] = "Number"
                elif "int" in concrete_types:
                    inferred_types[index] = "int"
                else:
                    inferred_types[index] = "uint"
                continue
            if len(concrete_types) == 1:
                inferred_types[index] = next(iter(concrete_types))
                continue
            inferred_types[index] = "*" if len(concrete_types) != 1 else next(iter(concrete_types))

        return sorted(local_indexes), inferred_types

    def _extract_source_local_index(self, value: object) -> int | None:
        current = value
        while isinstance(current, Node) and current.type in {
            "coerce",
            "convert",
            "coerce_b",
            "convert_i",
            "convert_u",
            "convert_d",
            "convert_s",
            "convert_o",
        } and current.children:
            current = current.children[-1]
        if isinstance(current, Node) and current.type == "get_local" and current.children:
            return _index_value(current.children[0])
        return None

    def _normalize_type_hint(self, hint: object) -> str | None:
        if isinstance(hint, Node):
            if hint.type == "string" and hint.children:
                return self._normalize_type_hint(hint.children[0])
            if hint.type in {"get_lex", "find_property", "find_property_strict"} and hint.children:
                return self._normalize_type_hint(hint.children[0])
            return None

        text = str(hint).strip()
        if not text:
            return None
        text = _short_multiname(text)
        lowered = text.lower()
        if lowered in {"*", "any", "coercea"}:
            return "*"
        if lowered in {"int", "integer"}:
            return "int"
        if lowered == "uint":
            return "uint"
        if lowered in {"number", "double", "float"}:
            return "Number"
        if lowered in {"string"}:
            return "String"
        if lowered in {"boolean", "bool"}:
            return "Boolean"
        if lowered == "array":
            return "Array"
        if lowered == "object":
            return "Object"
        normalized = self._property_name(text)
        return normalized if normalized and normalized != "*" else "*"

    def _infer_expr_type(self, value: object, local_type_cache: dict[int, str]) -> str | None:
        if isinstance(value, bool):
            return "Boolean"
        if isinstance(value, int):
            return "int"
        if isinstance(value, float):
            return "Number"
        if isinstance(value, str):
            return "String"
        if value is None:
            return None
        if not isinstance(value, Node):
            return None

        if value.type == "integer":
            return "int"
        if value.type == "unsigned":
            return "uint"
        if value.type == "double":
            return "Number"
        if value.type == "string":
            return "String"
        if value.type in {"true", "false", "coerce_b"}:
            return "Boolean"
        mapped_convert = self._CONVERT_RESULT_TYPES.get(value.type)
        if mapped_convert:
            return mapped_convert
        if value.type == "new_array":
            return "Array"
        if value.type in {"new_object", "new_activation", "new_catch"}:
            return "Object"
        if value.type in {"get_lex", "find_property", "find_property_strict"} and value.children:
            return self._normalize_type_hint(value.children[0])
        if value.type == "get_local" and value.children:
            source_index = _index_value(value.children[0])
            if source_index is not None:
                return local_type_cache.get(source_index)
            return None
        if value.type in {"coerce", "convert"} and value.children:
            hinted = self._normalize_type_hint(value.children[0])
            if hinted and hinted != "*":
                return hinted
            return self._infer_expr_type(value.children[-1], local_type_cache)
        if value.type in {"call_property", "call_property_lex", "call_super"} and len(value.children) >= 2:
            call_name = self._property_name(value.children[1]).strip().lower()
            if call_name in self._CALL_RESULT_TYPE_HINTS:
                return self._CALL_RESULT_TYPE_HINTS[call_name]
            callee_hint = self._infer_expr_type(value.children[0], local_type_cache)
            if callee_hint and call_name == callee_hint.lower():
                return callee_hint
        if value.type == "construct" and value.children:
            return self._infer_expr_type(value.children[0], local_type_cache) or "Object"
        if value.type == "construct_property" and len(value.children) >= 2:
            hinted = self._normalize_type_hint(value.children[1])
            return hinted or "Object"
        if value.type in {"ternary", "ternary_if", "ternary_if_boolean"} and len(value.children) >= 3:
            left = self._infer_expr_type(value.children[1], local_type_cache)
            right = self._infer_expr_type(value.children[2], local_type_cache)
            if left and right and left == right:
                return left
            return left or right
        return None

    def _loop_binding(self, index: object) -> str:
        name = self._var_name(index)
        local_index = _index_value(index)
        if self._is_semantic_style() and local_index is not None and local_index in self._declared_local_indexes:
            return name
        return f"var {name}"

    def _emit_block(self, node: Node, level: int, inline: bool) -> list[str]:
        if node.type != "begin":
            return [self._stmt(node, level)]

        lines: list[str] = []
        for child in node.children:
            if isinstance(child, Node):
                stmt = self._stmt(child, level)
                if stmt:
                    lines.append(stmt)
            else:
                lines.append(f"{self._pad(level)}/* unsupported literal stmt: {child!r} */")

        if inline and not lines:
            return [self._pad(level) + "// empty"]
        return lines

    def _stmt(self, node: Node, level: int) -> str:
        if node.type == "begin":
            lines = self._emit_block(node, level, inline=True)
            return "\n".join(lines) if lines else f"{self._pad(level)}/* empty */"

        if node.type in {"nop", "label", "push_scope", "pop_scope"}:
            return ""

        if node.type == "jump":
            target = node.children[0] if node.children else "?"
            return f"{self._pad(level)}/* jump {target} */"

        if node.type == "jump_if":
            flag = bool(node.children[0]) if node.children else True
            target: object = "?"
            cond_node: object | None = None

            # Historical IR variants:
            # 1) [flag, cond]
            # 2) [flag, target, cond]
            if len(node.children) >= 3 and not isinstance(node.children[1], Node):
                target = node.children[1]
                cond_node = node.children[2]
            elif len(node.children) >= 2:
                cond_node = node.children[1]

            cond_value: object = self._normalize_expr_node(cond_node) if cond_node is not None else Node("true")
            if not flag:
                cond_value = self._negate_condition(cond_value)
            cond_expr = self._expr_condition(cond_value)

            if target != "?":
                return f"{self._pad(level)}if ({cond_expr}) {{ /* goto {target} */ }}"
            return f"{self._pad(level)}if ({cond_expr}) {{}}"

        if node.type == "if":
            return self._emit_if(node, level)

        if node.type == "while":
            cond = self._expr_condition(node.children[0]) if node.children else "false"
            body = node.children[1] if len(node.children) > 1 and isinstance(node.children[1], Node) else Node("begin")

            for_init = node.metadata.get("for_init") if isinstance(node.metadata, dict) else None
            for_update = node.metadata.get("for_update") if isinstance(node.metadata, dict) else None
            if isinstance(for_init, Node) and isinstance(for_update, Node):
                init_text = self._stmt(for_init, 0).strip()
                if init_text.endswith(";"):
                    init_text = init_text[:-1]
                update_text = self._expr(for_update)
                lines = [f"{self._pad(level)}for ({init_text}; {cond}; {update_text}) {{"]
                lines.extend(self._emit_block(body, level + 1, inline=True))
                lines.append(f"{self._pad(level)}}}")
                return "\n".join(lines)

            lines = [f"{self._pad(level)}while ({cond}) {{"]
            lines.extend(self._emit_block(body, level + 1, inline=True))
            lines.append(f"{self._pad(level)}}}")
            return "\n".join(lines)

        if node.type == "for":
            init = node.children[0] if len(node.children) > 0 else None
            cond_node = node.children[1] if len(node.children) > 1 else Node("true")
            update = node.children[2] if len(node.children) > 2 else None
            body = node.children[3] if len(node.children) > 3 and isinstance(node.children[3], Node) else Node("begin")

            if isinstance(init, Node):
                init_text = self._stmt(init, 0).strip()
                if init_text.endswith(";"):
                    init_text = init_text[:-1]
            else:
                init_text = ""

            cond_text = self._expr_condition(cond_node)

            if isinstance(update, Node):
                update_text = self._expr(update)
            else:
                update_text = ""

            lines = [f"{self._pad(level)}for ({init_text}; {cond_text}; {update_text}) {{"]
            lines.extend(self._emit_block(body, level + 1, inline=True))
            lines.append(f"{self._pad(level)}}}")
            return "\n".join(lines)

        if node.type == "for_in":
            value_reg = node.children[0] if len(node.children) > 0 else 0
            object_reg = node.children[2] if len(node.children) > 2 else 0
            body = node.children[3] if len(node.children) > 3 and isinstance(node.children[3], Node) else Node("begin")

            lines = [f"{self._pad(level)}for ({self._loop_binding(value_reg)} in {self._var_name(object_reg)}) {{"]
            lines.extend(self._emit_block(body, level + 1, inline=True))
            lines.append(f"{self._pad(level)}}}")
            return "\n".join(lines)

        if node.type == "for_each_in":
            value_reg = node.children[0] if len(node.children) > 0 else 0
            object_reg = node.children[2] if len(node.children) > 2 else 0
            body = node.children[3] if len(node.children) > 3 and isinstance(node.children[3], Node) else Node("begin")

            lines = [f"{self._pad(level)}for each ({self._loop_binding(value_reg)} in {self._var_name(object_reg)}) {{"]
            lines.extend(self._emit_block(body, level + 1, inline=True))
            lines.append(f"{self._pad(level)}}}")
            return "\n".join(lines)

        if node.type == "with":
            scope_expr = self._expr(node.children[0]) if node.children else "this"
            body = node.children[1] if len(node.children) > 1 and isinstance(node.children[1], Node) else Node("begin")

            lines = [f"{self._pad(level)}with ({scope_expr}) {{"]
            lines.extend(self._emit_block(body, level + 1, inline=True))
            lines.append(f"{self._pad(level)}}}")
            return "\n".join(lines)

        if node.type == "switch":
            return self._emit_switch(node, level)

        if node.type == "field_initializers":
            return self._emit_field_initializers(node, level)

        if node.type == "case":
            value_node = node.children[0] if node.children else None
            avm2_name = None
            if isinstance(value_node, Node):
                avm2_name = value_node.metadata.get("avm2_constant_name")
            if self._is_semantic_output_style() and isinstance(avm2_name, str) and avm2_name:
                return f"{self._pad(level)}case this.{avm2_name}:"
            value = self._expr(value_node) if value_node is not None else "undefined"
            return f"{self._pad(level)}case {value}:"

        if node.type == "default":
            return f"{self._pad(level)}default:"

        if node.type == "lookup_switch":
            default_target = node.children[0] if len(node.children) > 0 else "?"
            case_targets = node.children[1] if len(node.children) > 1 else []
            expr = self._expr(node.children[2]) if len(node.children) > 2 else "/* expr */"
            return (
                f"{self._pad(level)}/* lookup_switch "
                f"expr={expr} default={default_target} cases={case_targets} */"
            )

        if node.type == "return_void":
            return f"{self._pad(level)}return;"

        if node.type == "return_value":
            value = self._expr(node.children[0]) if node.children else "undefined"
            return f"{self._pad(level)}return {value};"

        if node.type == "break":
            return f"{self._pad(level)}break;"

        if node.type == "continue":
            return f"{self._pad(level)}continue;"

        if node.type == "throw":
            value = self._expr(node.children[0]) if node.children else "undefined"
            return f"{self._pad(level)}throw {value};"

        if node.type == "set_local":
            if len(node.children) >= 2:
                index = node.children[0]
                value = self._expr(node.children[1])
                local_index = _index_value(index)
                if (
                    self._is_semantic_style()
                    and self.inline_vars
                    and local_index is not None
                    and local_index in self._inline_candidate_locals
                    and local_index not in self._inline_declared_locals
                ):
                    type_name = self._declared_local_types.get(local_index, "*")
                    self._inline_declared_locals.add(local_index)
                    self._declared_local_indexes.add(local_index)
                    return f"{self._pad(level)}var {self._var_name(index)}:{type_name} = {value};"
                return f"{self._pad(level)}{self._var_name(index)} = {value};"
            return f"{self._pad(level)}/* malformed set_local */"

        if node.type == "set_slot":
            if len(node.children) >= 3:
                slot_raw = node.children[0]
                scope_expr = self._expr(node.children[1])
                value_expr = self._expr(node.children[2])
                if self._is_semantic_style() and self.method_context is not None:
                    slot_name = self._slot_fallback_name(slot_raw)
                    if slot_name and _FIELD_IDENTIFIER_RE.match(slot_name):
                        return f"{self._pad(level)}{scope_expr}.{slot_name} = {value_expr};"
                    if slot_name:
                        return f"{self._pad(level)}{scope_expr}[\"{slot_name}\"] = {value_expr};"
                slot_index = self._expr(slot_raw)
                return f"{self._pad(level)}slot_set({scope_expr}, {slot_index}, {value_expr});"
            return f"{self._pad(level)}/* malformed set_slot */"

        if node.type in {"set_property", "init_property", "set_super"}:
            if len(node.children) >= 3:
                target = self._property_target(node.children[:-1])
                value = self._expr(node.children[-1])
                return f"{self._pad(level)}{target} = {value};"
            return f"{self._pad(level)}/* malformed {node.type} */"

        expr_text = self._expr(node)
        return f"{self._pad(level)}{expr_text};"

    def _emit_field_initializers(self, node: Node, level: int) -> str:
        owner = str(node.metadata.get("owner", "")).strip()
        header = "field initializers"
        if owner:
            header = f"{header} for {owner}"
        lines = [f"{self._pad(level)}/* {header}"]
        for child in node.children:
            if not isinstance(child, Node) or child.type != "field_initializer" or len(child.children) < 2:
                continue
            name = self._property_name(child.children[0])
            value = self._expr(child.children[1])
            lines.append(f"{self._pad(level)} * this.{name} = {value}")
        lines.append(f"{self._pad(level)} */")
        return "\n".join(lines)

    def _property_target(self, children: list[object]) -> str:
        if len(children) < 2:
            return "/* malformed-property */"

        subject_node = children[0]
        subject = self._expr(subject_node)
        name = children[1]
        runtime_parts = children[2:]
        if runtime_parts:
            key = self._expr(runtime_parts[-1])
            return f"{subject}[{key}]"
        prop_name = self._property_name(name)
        if self._is_semantic_output_style():
            find_base = self._find_property_base_name(subject_node)
            if find_base and find_base == prop_name:
                return prop_name
            if self._is_redundant_member_access(subject, prop_name):
                return prop_name
            if isinstance(subject_node, Node) and subject_node.type == "get_scope_object":
                return prop_name
        return f"{subject}.{self._property_name(name)}"

    def _emit_if(self, node: Node, level: int, prefix: str = "if") -> str:
        then_block = node.children[1] if len(node.children) > 1 and isinstance(node.children[1], Node) else Node("begin")
        else_block = node.children[2] if len(node.children) > 2 and isinstance(node.children[2], Node) else None
        cond_value: object = self._normalize_expr_node(node.children[0]) if node.children else Node("false")

        # Prefer positive-condition form by swapping branches when safe.
        if (
            else_block is not None
            and isinstance(cond_value, Node)
            and cond_value.type == "!"
            and len(cond_value.children) == 1
        ):
            cond_value = self._normalize_expr_node(cond_value.children[0])
            then_block, else_block = else_block, then_block

        cond = self._expr_condition(cond_value)

        lines = [f"{self._pad(level)}{prefix} ({cond}) {{"]
        lines.extend(self._emit_block(then_block, level + 1, inline=True))
        lines.append(f"{self._pad(level)}}}")

        if else_block is None:
            return "\n".join(lines)

        nested_if: Node | None = None
        if else_block.type == "if":
            nested_if = else_block
        elif else_block.type == "begin" and len(else_block.children) == 1:
            only = else_block.children[0]
            if isinstance(only, Node) and only.type == "if":
                nested_if = only

        if nested_if is not None:
            lines.append(self._emit_if(nested_if, level, prefix="else if"))
            return "\n".join(lines)

        lines.append(f"{self._pad(level)}else {{")
        lines.extend(self._emit_block(else_block, level + 1, inline=True))
        lines.append(f"{self._pad(level)}}}")
        return "\n".join(lines)

    def _normalize_expr_node(self, value: object) -> object:
        if not isinstance(value, Node):
            return value

        normalized_children = [self._normalize_expr_node(child) for child in value.children]
        kind = value.type

        if kind == "!":
            if not normalized_children:
                return Node("false")
            operand = normalized_children[0]
            if isinstance(operand, Node):
                if operand.type == "!" and len(operand.children) == 1:
                    return self._normalize_expr_node(operand.children[0])
                if operand.type == "true":
                    return Node("false")
                if operand.type == "false":
                    return Node("true")
                inverted = self._invert_comparison(operand)
                if inverted is not None:
                    return inverted
            if isinstance(operand, bool):
                return Node("true" if not operand else "false")
            return Node("!", [operand])

        if kind in {"ternary", "ternary_if", "ternary_if_boolean"} and len(normalized_children) >= 3:
            cond = normalized_children[0]
            when_true = normalized_children[1]
            when_false = normalized_children[2]
            if self._is_truthy_node(cond):
                return when_true
            if self._is_falsy_node(cond):
                return when_false
            if when_true == when_false:
                return when_true
            return Node(kind, [cond, when_true, when_false], dict(value.metadata))

        return Node(kind, normalized_children, dict(value.metadata))

    def _negate_condition(self, value: object) -> object:
        normalized = self._normalize_expr_node(value)
        if self._is_truthy_node(normalized):
            return Node("false")
        if self._is_falsy_node(normalized):
            return Node("true")
        if isinstance(normalized, Node) and normalized.type == "!" and len(normalized.children) == 1:
            return self._normalize_expr_node(normalized.children[0])
        return self._normalize_expr_node(Node("!", [normalized]))

    def _expr_condition(self, value: object) -> str:
        normalized = self._normalize_expr_node(value)
        simplified = self._strip_condition_wrappers(normalized) if self._is_semantic_output_style() else normalized
        return self._trim_redundant_outer_parentheses(self._expr(simplified))

    def _strip_condition_wrappers(self, value: object) -> object:
        current: object = value
        while isinstance(current, Node):
            if current.type == "coerce_b" and current.children:
                current = self._normalize_expr_node(current.children[-1])
                continue
            if current.type in {"coerce", "convert"} and len(current.children) >= 2:
                hinted = self._normalize_type_hint(current.children[0])
                if hinted == "Boolean":
                    current = self._normalize_expr_node(current.children[-1])
                    continue
            if self._is_boolean_wrapper_call(current):
                current = self._normalize_expr_node(current.children[-1])
                continue
            break
        return current

    def _call_wrapper_target_name(self, value: object) -> str | None:
        if not isinstance(value, Node) or not value.children:
            return None
        if value.type in {"get_lex", "find_property", "find_property_strict"}:
            return self._property_name(value.children[0])
        return None

    def _is_boolean_wrapper_call(self, value: object) -> bool:
        if not isinstance(value, Node):
            return False

        if value.type in {"call_property", "call_property_lex"}:
            if len(value.children) != 3:
                return False
            callee_name = self._call_wrapper_target_name(value.children[0])
            method_name = self._property_name(value.children[1])
            return callee_name == "Boolean" and method_name == "Boolean"

        if value.type == "call":
            if len(value.children) != 3:
                return False
            callee_name = self._call_wrapper_target_name(value.children[0])
            return callee_name == "Boolean"

        return False

    def _invert_comparison(self, node: Node) -> Node | None:
        invert_map = {
            "==": "!=",
            "!=": "==",
            "===": "!==",
            "!==": "===",
            "<": ">=",
            "<=": ">",
            ">": "<=",
            ">=": "<",
        }
        op = invert_map.get(node.type)
        if op is None or len(node.children) < 2:
            return None
        return Node(op, [node.children[0], node.children[1]], dict(node.metadata))

    @staticmethod
    def _is_truthy_node(value: object) -> bool:
        if isinstance(value, bool):
            return value
        return isinstance(value, Node) and value.type == "true"

    @staticmethod
    def _is_falsy_node(value: object) -> bool:
        if isinstance(value, bool):
            return not value
        return isinstance(value, Node) and value.type == "false"

    def _expr(self, value: object) -> str:
        if isinstance(value, Node):
            symbolic_op = self._SYMBOLIC_BINARY_OPS.get(value.type)
            if symbolic_op is not None:
                return self._binary(value, symbolic_op)
            if value.type == "!":
                if not value.children:
                    return "!false"
                operand = self._trim_redundant_outer_parentheses(self._expr(value.children[0]))
                return f"!({operand})"

            handler = self._expr_handler_cache.get(value.type, self._EXPR_HANDLER_MISSING)
            if handler is self._EXPR_HANDLER_MISSING:
                resolved = getattr(self, f"_expr_{value.type}", None)
                handler = resolved if callable(resolved) else None
                self._expr_handler_cache[value.type] = handler
            if handler is not None:
                return handler(value)  # type: ignore[misc]
            return f"/* unsupported expr: {value.type} */"

        if isinstance(value, str):
            return value

        if isinstance(value, bool):
            return "true" if value else "false"

        if value is None:
            return "null"

        return str(value)

    def _expr_begin(self, node: Node) -> str:
        if not node.children:
            return "/* empty */"
        return self._expr(node.children[-1])

    def _format_int_literal(self, value: object) -> str:
        parsed = _index_value(value)
        if parsed is None:
            return str(value)
        if self.int_format == "hex":
            prefix = "-0x" if parsed < 0 else "0x"
            return f"{prefix}{abs(parsed):X}"
        return str(parsed)

    def _expr_integer(self, node: Node) -> str:
        return self._format_int_literal(node.children[0]) if node.children else "0"

    def _expr_unsigned(self, node: Node) -> str:
        return self._format_int_literal(node.children[0]) if node.children else "0"

    def _expr_double(self, node: Node) -> str:
        return str(node.children[0]) if node.children else "0.0"

    def _expr_string(self, node: Node) -> str:
        text = str(node.children[0]) if node.children else ""
        return json.dumps(text, ensure_ascii=False)

    def _expr_true(self, node: Node) -> str:
        return "true"

    def _expr_false(self, node: Node) -> str:
        return "false"

    def _expr_null(self, node: Node) -> str:
        return "null"

    def _expr_undefined(self, node: Node) -> str:
        return "undefined"

    def _expr_nan(self, node: Node) -> str:
        return "NaN"

    def _expr_get_local(self, node: Node) -> str:
        index = node.children[0] if node.children else 0
        return self._var_name(index)

    def _expr_get_scope_object(self, node: Node) -> str:
        index = node.children[0] if node.children else 0
        return f"scope{index}"

    def _expr_get_global_scope(self, node: Node) -> str:
        return "this"

    def _expr_get_lex(self, node: Node) -> str:
        return self._property_name(node.children[0]) if node.children else "/* lex */"

    def _expr_get_property(self, node: Node) -> str:
        if len(node.children) < 2:
            return "/* malformed get_property */"
        subject_node = node.children[0]
        subject = self._expr(subject_node)
        name = node.children[1]
        runtime_parts = node.children[2:]
        if runtime_parts:
            key = self._expr(runtime_parts[-1])
            return f"{subject}[{key}]"
        prop_name = self._property_name(name)
        if self._is_semantic_output_style():
            find_base = self._find_property_base_name(subject_node)
            if find_base and find_base == prop_name:
                return prop_name
            if self._is_redundant_member_access(subject, prop_name):
                return prop_name
            if isinstance(subject_node, Node) and subject_node.type == "get_scope_object":
                return prop_name
        return f"{subject}.{prop_name}"

    def _expr_get_super(self, node: Node) -> str:
        if len(node.children) < 2:
            return "super"
        name = node.children[1]
        runtime_parts = node.children[2:]
        if runtime_parts:
            key = self._expr(runtime_parts[-1])
            return f"super[{key}]"
        return f"super.{self._property_name(name)}"

    def _expr_get_slot(self, node: Node) -> str:
        if len(node.children) < 2:
            return "/* malformed get_slot */"
        slot_raw = node.children[0]
        scope_expr = self._expr(node.children[1])
        if self._is_semantic_style() and self.method_context is not None:
            slot_name = self._slot_fallback_name(slot_raw)
            if slot_name and _FIELD_IDENTIFIER_RE.match(slot_name):
                return f"{scope_expr}.{slot_name}"
            if slot_name:
                return f"{scope_expr}[\"{slot_name}\"]"
        slot_index = self._expr(slot_raw)
        return f"slot({scope_expr}, {slot_index})"

    def _expr_find_property(self, node: Node) -> str:
        return self._property_name(node.children[0]) if node.children else "/* find_property */"

    def _expr_find_property_strict(self, node: Node) -> str:
        return self._property_name(node.children[0]) if node.children else "/* find_property_strict */"

    def _expr_call_property(self, node: Node) -> str:
        return self._call_property_like(node)

    def _expr_call_property_lex(self, node: Node) -> str:
        return self._call_property_like(node)

    def _expr_call_super(self, node: Node) -> str:
        return self._call_property_like(node, super_call=True)

    def _expr_call(self, node: Node) -> str:
        if len(node.children) < 2:
            return "/* malformed call */"
        target = self._expr(node.children[0])
        args = ", ".join(self._expr(arg) for arg in node.children[2:])
        return f"{target}({args})"

    def _expr_construct(self, node: Node) -> str:
        if not node.children:
            return "new Object()"
        ctor = self._trim_redundant_outer_parentheses(self._expr(node.children[0]))
        args = ", ".join(self._expr(arg) for arg in node.children[1:])
        return f"new {ctor}({args})"

    def _expr_construct_super(self, node: Node) -> str:
        # `construct_super` carries [receiver, *args] in low-level AST.
        args = ", ".join(self._expr(arg) for arg in node.children[1:])
        return f"super({args})"

    def _expr_construct_property(self, node: Node) -> str:
        if len(node.children) < 2:
            return "new Object()"
        subject_node = node.children[0]
        subject = self._expr(subject_node)
        name = self._property_name(node.children[1])
        args = ", ".join(self._expr(arg) for arg in node.children[2:])
        if self._is_semantic_output_style():
            find_base = self._find_property_base_name(subject_node)
            if find_base and find_base == name:
                return f"new {name}({args})"
            if self._is_redundant_member_access(subject, name):
                return f"new {subject}({args})"
        return f"new {subject}.{name}({args})"

    def _expr_new_array(self, node: Node) -> str:
        return "[" + ", ".join(self._expr(child) for child in node.children) + "]"

    def _expr_new_object(self, node: Node) -> str:
        items: list[str] = []
        it: Iterable[object] = node.children
        pairs = list(it)
        for index in range(0, len(pairs), 2):
            if index + 1 >= len(pairs):
                break
            key = self._expr(pairs[index])
            value = self._expr(pairs[index + 1])
            items.append(f"{key}: {value}")
        return "{ " + ", ".join(items) + " }"

    def _expr_coerce(self, node: Node) -> str:
        return self._expr(node.children[-1]) if node.children else "undefined"

    def _expr_convert(self, node: Node) -> str:
        return self._expr(node.children[-1]) if node.children else "undefined"

    def _expr_convert_i(self, node: Node) -> str:
        operand = self._expr(node.children[-1]) if node.children else "0"
        return f"int({operand})"

    def _expr_convert_u(self, node: Node) -> str:
        operand = self._expr(node.children[-1]) if node.children else "0"
        return f"uint({operand})"

    def _expr_convert_d(self, node: Node) -> str:
        operand = self._expr(node.children[-1]) if node.children else "0"
        return f"Number({operand})"

    def _expr_convert_s(self, node: Node) -> str:
        operand = self._expr(node.children[-1]) if node.children else "undefined"
        return f"String({operand})"

    def _expr_convert_o(self, node: Node) -> str:
        operand = self._expr(node.children[-1]) if node.children else "undefined"
        return f"Object({operand})"

    def _expr_coerce_b(self, node: Node) -> str:
        if node.children:
            return f"Boolean({self._expr(node.children[-1])})"
        return "false"

    def _expr_check_filter(self, node: Node) -> str:
        if node.children:
            return f"checkFilter({self._expr(node.children[-1])})"
        return "checkFilter(/* value */)"

    def _expr_type_hint(self, value: object) -> str:
        if isinstance(value, Node):
            if value.type in {"get_lex", "find_property", "find_property_strict"} and value.children:
                token = self._property_name(value.children[0])
                return token if token else "*"
            if value.type == "string" and value.children:
                token = self._property_name(value.children[0])
                return token if token else "*"
            if value.type == "stack_hole":
                return "*"

        token = self._trim_redundant_outer_parentheses(self._expr(value))
        if not token or token in {"undefined", "null"}:
            return "*"
        if "unsupported expr" in token or "stack_hole" in token:
            return "*"
        return token

    def _expr_as_type(self, node: Node) -> str:
        if len(node.children) >= 2:
            return f"({self._expr(node.children[0])} as {self._expr_type_hint(node.children[1])})"
        if node.children:
            return f"({self._expr(node.children[0])} as /* type */ *)"
        return "(/* as_type */ undefined)"

    def _expr_as_type_late(self, node: Node) -> str:
        if len(node.children) >= 2:
            return f"({self._expr(node.children[0])} as {self._expr_type_hint(node.children[1])})"
        if node.children:
            return f"({self._expr(node.children[0])} as /* type */ *)"
        return "(/* as_type_late */ undefined)"

    def _expr_is_type(self, node: Node) -> str:
        if len(node.children) >= 2:
            return f"({self._expr(node.children[0])} is {self._expr_type_hint(node.children[1])})"
        if node.children:
            return f"({self._expr(node.children[0])} is /* type */ *)"
        return "(/* is_type */ false)"

    def _expr_is_type_late(self, node: Node) -> str:
        if len(node.children) >= 2:
            return f"({self._expr(node.children[0])} is {self._expr_type_hint(node.children[1])})"
        if node.children:
            return f"({self._expr(node.children[0])} is /* type */ *)"
        return "(/* is_type_late */ false)"

    def _expr_ternary(self, node: Node) -> str:
        if len(node.children) < 3:
            return "/* malformed ternary */"
        cond_expr = self._expr_condition(node.children[0])
        return f"({cond_expr} ? {self._expr(node.children[1])} : {self._expr(node.children[2])})"

    def _expr_ternary_if(self, node: Node) -> str:
        if len(node.children) < 3:
            return "/* malformed ternary_if */"
        cond_expr = self._expr_condition(node.children[0])
        return f"({cond_expr} ? {self._expr(node.children[1])} : {self._expr(node.children[2])})"

    def _expr_ternary_if_boolean(self, node: Node) -> str:
        return self._expr_ternary_if(node)

    def _expr_not(self, node: Node) -> str:
        if not node.children:
            return "!false"
        operand = self._trim_redundant_outer_parentheses(self._expr(node.children[0]))
        return f"!({operand})"

    def _expr_negate(self, node: Node) -> str:
        if not node.children:
            return "-0"
        operand = self._trim_redundant_outer_parentheses(self._expr(node.children[0]))
        return f"-({operand})"

    def _expr_increment(self, node: Node) -> str:
        return f"({self._expr(node.children[0])} + 1)" if node.children else "1"

    def _expr_increment_i(self, node: Node) -> str:
        return self._expr_increment(node)

    def _expr_decrement(self, node: Node) -> str:
        return f"({self._expr(node.children[0])} - 1)" if node.children else "-1"

    def _expr_decrement_i(self, node: Node) -> str:
        return self._expr_decrement(node)

    @staticmethod
    def _trim_redundant_outer_parentheses(expr: str) -> str:
        text = expr.strip()
        while AS3Emitter._is_fully_wrapped_by_parentheses(text):
            text = text[1:-1].strip()
        return text

    @staticmethod
    def _is_fully_wrapped_by_parentheses(expr: str) -> bool:
        if len(expr) < 2 or expr[0] != "(" or expr[-1] != ")":
            return False

        depth = 0
        in_single = False
        in_double = False
        escaped = False
        for index, ch in enumerate(expr):
            if escaped:
                escaped = False
                continue
            if ch == "\\":
                escaped = True
                continue
            if in_single:
                if ch == "'":
                    in_single = False
                continue
            if in_double:
                if ch == '"':
                    in_double = False
                continue
            if ch == "'":
                in_single = True
                continue
            if ch == '"':
                in_double = True
                continue
            if ch == "(":
                depth += 1
                continue
            if ch == ")":
                depth -= 1
                if depth < 0:
                    return False
                if depth == 0 and index != len(expr) - 1:
                    return False
        return depth == 0 and not in_single and not in_double

    def _expr_inc_local_i(self, node: Node) -> str:
        index = node.children[0] if node.children else "?"
        return f"++{self._var_name(index)}"

    def _expr_dec_local_i(self, node: Node) -> str:
        index = node.children[0] if node.children else "?"
        return f"--{self._var_name(index)}"

    def _expr_inc_local(self, node: Node) -> str:
        index = node.children[0] if node.children else "?"
        return f"++{self._var_name(index)}"

    def _expr_dec_local(self, node: Node) -> str:
        index = node.children[0] if node.children else "?"
        return f"--{self._var_name(index)}"

    def _expr_post_increment_local(self, node: Node) -> str:
        index = node.children[0] if node.children else "?"
        return f"{self._var_name(index)}++"

    def _expr_pre_increment_local(self, node: Node) -> str:
        index = node.children[0] if node.children else "?"
        return f"++{self._var_name(index)}"

    def _expr_post_decrement_local(self, node: Node) -> str:
        index = node.children[0] if node.children else "?"
        return f"{self._var_name(index)}--"

    def _expr_pre_decrement_local(self, node: Node) -> str:
        index = node.children[0] if node.children else "?"
        return f"--{self._var_name(index)}"

    def _expr_new_activation(self, node: Node) -> str:
        return "new Object() /* activation */"

    def _expr_new_catch(self, node: Node) -> str:
        if node.children:
            return f"new Object() /* catch {self._expr(node.children[0])} */"
        return "new Object() /* catch */"

    def _expr_new_function(self, node: Node) -> str:
        method_index = node.children[0] if node.children else "?"
        return f"function /* method_{method_index} */() {{}}"

    def _expr_push_with(self, node: Node) -> str:
        if node.children:
            return f"/* push_with {self._expr(node.children[0])} */"
        return "/* push_with */"

    def _expr_has_next(self, node: Node) -> str:
        if len(node.children) >= 2:
            return f"hasNext({self._expr(node.children[0])}, {self._expr(node.children[1])})"
        return "hasNext(/* object */, /* index */)"

    def _expr_has_next2(self, node: Node) -> str:
        if len(node.children) >= 2:
            obj_ref = self._local_or_expr(node.children[0])
            idx_ref = self._local_or_expr(node.children[1])
            return f"hasnext2({obj_ref}, {idx_ref})"
        return "hasnext2(/* objectReg */, /* indexReg */)"

    def _expr_next_name(self, node: Node) -> str:
        if len(node.children) >= 2:
            return f"nextName({self._expr(node.children[0])}, {self._expr(node.children[1])})"
        return "nextName(/* object */, /* index */)"

    def _expr_next_value(self, node: Node) -> str:
        if len(node.children) >= 2:
            return f"nextValue({self._expr(node.children[0])}, {self._expr(node.children[1])})"
        return "nextValue(/* object */, /* index */)"

    def _expr_delete_property(self, node: Node) -> str:
        if len(node.children) >= 2:
            subject = self._expr(node.children[0])
            name = node.children[1]
            runtime_parts = node.children[2:]
            if runtime_parts:
                key = self._expr(runtime_parts[-1])
                return f"delete {subject}[{key}]"
            return f"delete {subject}.{self._property_name(name)}"
        if node.children:
            name = self._property_name(node.children[0])
            if name == "*":
                return "/* delete_property(*) */"
            return f"delete {name}"
        return "delete /* property */"

    def _expr_stack_hole(self, node: Node) -> str:
        if node.children:
            return f"undefined /* stack_hole:{node.children[0]} */"
        return "undefined /* stack_hole */"

    def _expr_add(self, node: Node) -> str:
        flattened = self._collect_left_associative_add_terms(node)
        if flattened is not None:
            return f"({' + '.join(flattened)})"
        return self._binary(node, "+")

    def _expr_subtract(self, node: Node) -> str:
        return self._binary(node, "-")

    def _expr_multiply(self, node: Node) -> str:
        return self._binary(node, "*")

    def _expr_divide(self, node: Node) -> str:
        return self._binary(node, "/")

    def _expr_modulo(self, node: Node) -> str:
        return self._binary(node, "%")

    def _expr_bit_and(self, node: Node) -> str:
        return self._binary(node, "&")

    def _expr_bit_or(self, node: Node) -> str:
        return self._binary(node, "|")

    def _expr_bit_xor(self, node: Node) -> str:
        return self._binary(node, "^")

    def _expr_lshift(self, node: Node) -> str:
        return self._binary(node, "<<")

    def _expr_rshift(self, node: Node) -> str:
        return self._binary(node, ">>")

    def _expr_urshift(self, node: Node) -> str:
        return self._binary(node, ">>>")

    def _expr_and(self, node: Node) -> str:
        return self._binary(node, "&&")

    def _expr_or(self, node: Node) -> str:
        return self._binary(node, "||")

    def _expr_equals(self, node: Node) -> str:
        return self._binary(node, "==")

    def _expr_strict_equals(self, node: Node) -> str:
        return self._binary(node, "===")

    def _expr_less_than(self, node: Node) -> str:
        return self._binary(node, "<")

    def _expr_less_equals(self, node: Node) -> str:
        return self._binary(node, "<=")

    def _expr_greater_than(self, node: Node) -> str:
        return self._binary(node, ">")

    def _expr_greater_equals(self, node: Node) -> str:
        return self._binary(node, ">=")

    def _expr_in(self, node: Node) -> str:
        return self._binary(node, "in")

    def _collect_left_associative_add_terms(self, node: Node) -> list[str] | None:
        if node.type != "add" or len(node.children) < 2:
            return None

        left = node.children[0]
        right = node.children[1]
        # Keep explicit right-grouping semantics: a + (b + c)
        if isinstance(right, Node) and right.type == "add":
            return None

        right_expr = self._expr(right)
        if isinstance(left, Node) and left.type == "add":
            left_terms = self._collect_left_associative_add_terms(left)
            if left_terms is None:
                return None
            left_terms.append(right_expr)
            return left_terms
        return [self._expr(left), right_expr]

    def _binary(self, node: Node, op: str) -> str:
        if len(node.children) < 2:
            return f"/* malformed {node.type} */"
        parent_meta = self._BINARY_META_BY_TYPE.get(node.type, (op, 0))
        parent_prec = parent_meta[1]
        left = self._binary_child_expr(node.children[0], parent_op=op, parent_prec=parent_prec, is_right=False)
        right = self._binary_child_expr(node.children[1], parent_op=op, parent_prec=parent_prec, is_right=True)
        return f"{left} {op} {right}"

    def _binary_child_expr(self, value: object, *, parent_op: str, parent_prec: int, is_right: bool) -> str:
        expr = self._expr(value)
        if not isinstance(value, Node):
            return expr

        child_meta = self._BINARY_META_BY_TYPE.get(value.type)
        if child_meta is None:
            return expr
        child_op, child_prec = child_meta

        needs_parentheses = False
        if child_prec < parent_prec:
            needs_parentheses = True
        elif child_prec == parent_prec and is_right:
            if not (parent_op in self._ASSOCIATIVE_BINARY_OPS and child_op == parent_op):
                needs_parentheses = True

        if needs_parentheses:
            return f"({expr})"
        return expr

    @staticmethod
    def _property_name(name: object) -> str:
        text = _strip_known_namespace_prefix(str(name))
        if "::" in text:
            text = text.rsplit("::", 1)[1]
        return AS3Emitter._collapse_redundant_qualifier(text)

    @staticmethod
    def _collapse_redundant_qualifier(text: str) -> str:
        """Collapse redundant X.X style qualifiers emitted by low-level names."""
        parts = [segment for segment in text.split(".") if segment]
        if not parts:
            return text
        while len(parts) >= 2 and parts[-1] == parts[-2]:
            parts.pop(-2)
        return ".".join(parts)

    @staticmethod
    def _is_redundant_member_access(subject: str, member: str) -> bool:
        if not subject or not member:
            return False
        tail = subject.rsplit(".", 1)[-1]
        return tail == member

    def _find_property_base_name(self, value: object) -> str | None:
        if not isinstance(value, Node):
            return None
        if value.type not in {"find_property", "find_property_strict"}:
            return None
        if not value.children:
            return None
        return self._property_name(value.children[0])

    def _call_property_like(self, node: Node, super_call: bool = False) -> str:
        if len(node.children) < 2:
            return "/* malformed call_property */"
        subject = "super" if super_call else self._expr(node.children[0])
        name = self._property_name(node.children[1])
        args = ", ".join(self._expr(arg) for arg in node.children[2:])
        if not super_call and self._is_semantic_output_style() and self._is_redundant_member_access(subject, name):
            return f"{subject}({args})"
        return f"{subject}.{name}({args})"

    @staticmethod
    def _slot_fallback_name(slot_index: object) -> str | None:
        numeric = _index_value(slot_index)
        if numeric is not None and numeric >= 0:
            return f"__slot{numeric}"
        text = str(slot_index).strip()
        if not text:
            return None
        text = _IDENTIFIER_SANITIZE_RE.sub("_", text).strip("_")
        if not text:
            return None
        if text[0].isdigit():
            text = f"_{text}"
        return f"__slot_{text}"

    def _pad(self, level: int) -> str:
        return self.indent * level

    def _var_name(self, index: object) -> str:
        local_index = _index_value(index)
        if local_index is None:
            return f"local{index}"
        mapped = self._local_name_map.get(local_index)
        if mapped is not None:
            return mapped
        return f"local{local_index}"

    def _local_or_expr(self, value: object) -> str:
        if _index_value(value) is not None:
            return self._var_name(value)
        return self._expr(value)

    def _emit_switch(self, node: Node, level: int) -> str:
        cond_node = node.children[0] if node.children else Node("integer", [0])
        body = node.children[1] if len(node.children) > 1 and isinstance(node.children[1], Node) else Node("begin")
        prepared_cond, preamble, sections = self._prepare_switch_layout(cond_node, body.children)
        cond = self._expr_condition(prepared_cond)
        lines = [f"{self._pad(level)}switch ({cond}) {{"]
        lines.extend(self._emit_switch_sections(preamble, sections, level + 1))
        lines.append(f"{self._pad(level)}}}")
        return "\n".join(lines)

    def _prepare_switch_layout(
        self,
        cond_node: object,
        children: list[object],
    ) -> tuple[object, list[object], list[SwitchSection]]:
        normalized_children = self._normalized_switch_children(children)
        preamble, sections = self._build_switch_sections(normalized_children)
        rewritten_cond, sections = self._rewrite_switch_selector_chain(cond_node, sections)
        sections, has_duplicate_case_bodies = self._collapse_duplicate_switch_sections(sections)
        self._analyze_switch_sections(sections)
        sections = self._move_default_to_end_if_safe(sections)
        self._analyze_switch_sections(sections)

        for idx, section in enumerate(sections):
            section.synthetic_break = self._should_insert_switch_break(
                section,
                idx,
                sections,
                aggressive_group_breaks=has_duplicate_case_bodies,
            )
        self._analyze_switch_sections(sections)
        return rewritten_cond, preamble, sections

    def _emit_switch_sections(
        self,
        preamble: list[object],
        sections: list[SwitchSection],
        level: int,
    ) -> list[str]:
        lines: list[str] = []

        for item in preamble:
            if isinstance(item, Node):
                stmt = self._stmt(item, level)
                if stmt:
                    lines.append(stmt)
            else:
                lines.append(f"{self._pad(level)}/* unsupported literal stmt: {item!r} */")

        for section in sections:
            lines.append(self._stmt(section.label, level))
            for item in section.body:
                if isinstance(item, Node):
                    stmt = self._stmt(item, level + 1)
                    if stmt:
                        lines.append(stmt)
                else:
                    lines.append(f"{self._pad(level + 1)}/* unsupported literal stmt: {item!r} */")
            if section.synthetic_break:
                lines.append(f"{self._pad(level + 1)}break;")

        return lines

    def _build_switch_sections(self, children: list[object]) -> tuple[list[object], list[SwitchSection]]:
        preamble: list[object] = []
        sections: list[SwitchSection] = []
        current_label: Node | None = None
        current_body: list[object] = []

        def _flush_section() -> None:
            if current_label is None:
                return
            sections.append(
                SwitchSection(
                    label=self._clone_node(current_label),
                    body=list(current_body),
                    terminal=None,
                    fallthrough_to=None,
                    origin_order=len(sections),
                )
            )

        for child in children:
            if isinstance(child, Node) and child.type in {"case", "default"}:
                _flush_section()
                current_label = child
                current_body = []
                continue

            if current_label is None:
                preamble.append(child)
            else:
                current_body.append(child)

        _flush_section()
        return preamble, sections

    def _collapse_duplicate_switch_sections(
        self,
        sections: list[SwitchSection],
    ) -> tuple[list[SwitchSection], bool]:
        if not sections:
            return sections, False

        collapsed = [self._clone_switch_section(section) for section in sections]
        had_duplicates = False
        signatures: list[tuple[str, ...]] = [
            self._switch_section_signature(section.body) if section.body else ()
            for section in collapsed
        ]

        idx = 0
        while idx < len(collapsed):
            sig = signatures[idx]
            if not sig:
                idx += 1
                continue

            run_end = idx
            while run_end + 1 < len(collapsed) and signatures[run_end + 1] == sig:
                run_end += 1

            if run_end > idx:
                for run_idx in range(idx, run_end):
                    collapsed[run_idx].body = []
                    signatures[run_idx] = ()
                had_duplicates = True
            idx = run_end + 1

        return collapsed, had_duplicates

    def _switch_section_signature(self, statements: list[object]) -> tuple[str, ...]:
        signature: list[str] = []
        for item in statements:
            if isinstance(item, Node):
                rendered = self._stmt(item, 0)
                signature.append(rendered if rendered is not None else "")
            else:
                signature.append(f"literal:{item!r}")
        return tuple(signature)

    def _analyze_switch_sections(self, sections: list[SwitchSection]) -> None:
        for idx, section in enumerate(sections):
            section.terminal = self._section_terminal_type(section)
            if idx + 1 < len(sections) and section.terminal is None:
                section.fallthrough_to = idx + 1
            else:
                section.fallthrough_to = None

    def _section_terminal_type(self, section: SwitchSection) -> str | None:
        if section.synthetic_break:
            return "break"
        for item in reversed(section.body):
            if isinstance(item, Node) and item.type in self._TERMINAL_STMTS:
                return item.type
        return None

    def _move_default_to_end_if_safe(self, sections: list[SwitchSection]) -> list[SwitchSection]:
        default_idx = -1
        for idx, section in enumerate(sections):
            if section.label.type == "default":
                default_idx = idx
                break
        if default_idx == -1 or default_idx == len(sections) - 1:
            return sections

        default_section = sections[default_idx]
        if not default_section.body:
            return sections
        if default_section.fallthrough_to is not None:
            return sections
        if default_idx > 0 and sections[default_idx - 1].fallthrough_to == default_idx:
            return sections

        return sections[:default_idx] + sections[default_idx + 1 :] + [default_section]

    def _should_insert_switch_break(
        self,
        section: SwitchSection,
        index: int,
        sections: list[SwitchSection],
        aggressive_group_breaks: bool = False,
    ) -> bool:
        if not section.body:
            return False
        if section.terminal is not None:
            return False

        next_non_empty = self._next_non_empty_switch_section(index, sections)
        if next_non_empty is None:
            return False

        if section.label.type == "default":
            return True
        if next_non_empty > index + 1:
            return True
        if aggressive_group_breaks:
            if self._switch_section_signature(section.body) != self._switch_section_signature(sections[next_non_empty].body):
                return True
        return False

    @staticmethod
    def _next_non_empty_switch_section(index: int, sections: list[SwitchSection]) -> int | None:
        for next_idx in range(index + 1, len(sections)):
            if sections[next_idx].body:
                return next_idx
        return None

    def _rewrite_switch_selector_chain(
        self,
        cond_node: object,
        sections: list[SwitchSection],
    ) -> tuple[object, list[SwitchSection]]:
        decoded = self._decode_ternary_switch_selector(cond_node)
        if decoded is None:
            return cond_node, sections
        selector_expr, case_key_by_index, default_index = decoded

        rewritten = [self._clone_switch_section(section) for section in sections]
        explicit_default_indices: list[int] = []
        synthesized_default_idx: int | None = None

        for idx, section in enumerate(rewritten):
            label = section.label
            if label.type == "default":
                explicit_default_indices.append(idx)
                continue
            case_index = self._case_label_int(label)
            if case_index is None:
                continue
            if case_index == default_index:
                section.label = Node("default", [], dict(label.metadata))
                synthesized_default_idx = idx
                continue
            mapped_key = case_key_by_index.get(case_index)
            if mapped_key is None:
                continue
            rewritten_key = self._normalize_switch_case_key(self._clone_object(mapped_key))
            section.label = Node("case", [rewritten_key], dict(label.metadata))

        if synthesized_default_idx is not None and explicit_default_indices:
            explicit_defaults = set(explicit_default_indices)
            rewritten = [section for idx, section in enumerate(rewritten) if idx not in explicit_defaults]

        if not any(section.label.type == "default" for section in rewritten):
            return cond_node, sections

        return selector_expr, rewritten

    def _decode_ternary_switch_selector(
        self,
        cond_node: object,
    ) -> tuple[object, dict[int, object], int] | None:
        cursor = self._normalize_expr_node(cond_node)
        comparisons: list[tuple[object, object, int]] = []

        while isinstance(cursor, Node) and cursor.type in {"ternary", "ternary_if", "ternary_if_boolean"} and len(cursor.children) >= 3:
            cond = cursor.children[0]
            when_true = cursor.children[1]
            when_false = cursor.children[2]
            index_value = self._int_like_value(when_true)
            if index_value is None:
                return None
            operands = self._extract_comparison_operands(cond)
            if operands is None:
                return None
            comparisons.append((operands[0], operands[1], index_value))
            cursor = when_false

        default_index = self._int_like_value(cursor)
        if default_index is None or not comparisons:
            return None

        candidate_selectors = [comparisons[0][0], comparisons[0][1]]
        selector_expr: object | None = None
        mapping: dict[int, object] = {}

        for candidate in candidate_selectors:
            if not self._is_safe_switch_selector_key(candidate):
                continue
            candidate_mapping: dict[int, object] = {}
            valid = True
            for left, right, index_value in comparisons:
                if self._nodes_equivalent(left, candidate):
                    key = right
                elif self._nodes_equivalent(right, candidate):
                    key = left
                else:
                    valid = False
                    break
                if not self._is_safe_switch_selector_key(key):
                    valid = False
                    break
                existing = candidate_mapping.get(index_value)
                if existing is not None and not self._nodes_equivalent(existing, key):
                    valid = False
                    break
                candidate_mapping[index_value] = key
            if valid:
                selector_expr = candidate
                mapping = candidate_mapping
                break

        if selector_expr is None:
            return None

        indices = sorted(mapping.keys())
        if not indices or len(set(indices)) != len(indices):
            return None
        if indices != list(range(indices[0], indices[-1] + 1)):
            return None

        return self._clone_object(selector_expr), mapping, default_index

    @staticmethod
    def _extract_comparison_operands(cond: object) -> tuple[object, object] | None:
        if not isinstance(cond, Node):
            return None
        if cond.type not in {"==", "==="}:
            return None
        if len(cond.children) < 2:
            return None
        return cond.children[0], cond.children[1]

    @staticmethod
    def _is_this_or_global_scope_expr(value: object) -> bool:
        if not isinstance(value, Node):
            return False
        if value.type == "get_global_scope":
            return True
        if value.type == "get_local" and value.children:
            return _index_value(value.children[0]) == 0
        return False

    def _normalize_switch_case_key(self, value: object) -> object:
        normalized = self._normalize_expr_node(value)
        if not isinstance(normalized, Node):
            return normalized
        if normalized.type != "get_property" or len(normalized.children) != 2:
            return normalized
        subject = normalized.children[0]
        if not self._is_this_or_global_scope_expr(subject):
            return normalized
        prop_name = self._property_name(normalized.children[1])
        context_map = self.method_context.avm2_constant_value_map if self.method_context is not None else {}
        literal_value = context_map.get(prop_name)
        if literal_value is None:
            literal_value = self._AVM2_SWITCH_CASE_CONSTANTS.get(prop_name)
        if literal_value is None:
            return normalized
        return Node("integer", [literal_value], {"avm2_constant_name": prop_name})

    def _is_safe_switch_selector_key(self, value: object) -> bool:
        if isinstance(value, (int, float, str, bool)) or value is None:
            return True
        if not isinstance(value, Node):
            return False

        allowed_leaf = {
            "integer",
            "unsigned",
            "double",
            "string",
            "true",
            "false",
            "null",
            "undefined",
            "get_local",
            "get_scope_object",
            "get_global_scope",
            "get_lex",
        }
        if value.type in allowed_leaf:
            return all(self._is_safe_switch_selector_key(child) for child in value.children)
        if value.type == "get_property":
            if len(value.children) != 2:
                return False
            subject = value.children[0]
            name = value.children[1]
            if not self._is_safe_switch_selector_key(subject):
                return False
            if isinstance(name, Node):
                # Keep property keys side-effect free (literal name only).
                return name.type in {"string", "integer", "unsigned"} and self._is_safe_switch_selector_key(name)
            return isinstance(name, (str, int, float, bool)) or name is None
        if value.type == "get_slot":
            return all(self._is_safe_switch_selector_key(child) for child in value.children)
        return False

    @staticmethod
    def _nodes_equivalent(left: object, right: object) -> bool:
        if isinstance(left, Node) and isinstance(right, Node):
            return left.is_equivalent(right)
        return left == right

    def _clone_switch_section(self, section: SwitchSection) -> SwitchSection:
        return SwitchSection(
            label=self._clone_node(section.label),
            body=list(section.body),
            terminal=section.terminal,
            fallthrough_to=section.fallthrough_to,
            origin_order=section.origin_order,
            synthetic_break=section.synthetic_break,
        )

    def _clone_object(self, value: object) -> object:
        if isinstance(value, Node):
            return self._clone_node(value)
        return value

    def _clone_node(self, node: Node) -> Node:
        children: list[object] = []
        for child in node.children:
            if isinstance(child, Node):
                children.append(self._clone_node(child))
            else:
                children.append(child)
        return Node(node.type, children, dict(node.metadata))

    @staticmethod
    def _int_like_value(value: object) -> int | None:
        if isinstance(value, int):
            return value
        if isinstance(value, Node):
            if value.type in {"integer", "unsigned"} and value.children and isinstance(value.children[0], int):
                return int(value.children[0])
        return None

    def _case_label_int(self, label: Node) -> int | None:
        if label.type != "case" or not label.children:
            return None
        return self._int_like_value(label.children[0])

    def _normalized_switch_children(self, children: list[object]) -> list[object]:
        sections: list[tuple[Node, list[object]]] = []
        preamble: list[object] = []
        current_label: Node | None = None
        current_body: list[object] = []

        for child in children:
            if isinstance(child, Node) and child.type in {"case", "default"}:
                if current_label is not None:
                    sections.append((current_label, current_body))
                current_label = child
                current_body = []
                continue
            if current_label is None:
                preamble.append(child)
            else:
                current_body.append(child)

        if current_label is not None:
            sections.append((current_label, current_body))

        if not sections:
            return list(children)
        if preamble:
            # Keep unusual preamble-in-switch layout untouched.
            return list(children)
        if not self._can_sort_switch_sections(sections):
            return list(children)

        def _label_sort_key(section: tuple[Node, list[object]]) -> tuple[int, int, str]:
            label = section[0]
            if label.type == "default":
                return (2, 0, "")
            if label.type == "case" and label.children:
                case_value = label.children[0]
                if isinstance(case_value, Node) and case_value.type in {"integer", "unsigned"} and case_value.children:
                    raw = case_value.children[0]
                    if isinstance(raw, int):
                        return (0, raw, "")
            text = self._expr(label.children[0]) if label.children else ""
            return (1, 0, text)

        sorted_sections = sorted(sections, key=_label_sort_key)
        flattened: list[object] = []
        for label, body_nodes in sorted_sections:
            flattened.append(label)
            flattened.extend(body_nodes)
        return flattened

    def _can_sort_switch_sections(self, sections: list[tuple[Node, list[object]]]) -> bool:
        # Sorting is safe only when sections are isolated (no fallthrough).
        for _label, body in sections:
            if not body:
                return False
            tail = body[-1]
            if not isinstance(tail, Node):
                return False
            if tail.type not in self._TERMINAL_STMTS:
                return False
        return True


def decompile_method(
    body: MethodBody,
    *,
    style: str = "semantic",
    abc: ABCFile | None = None,
    method_context: MethodContext | None = None,
    int_format: str = "dec",
    inline_vars: bool = False,
) -> str:
    normalized_int_format = _normalize_int_format(int_format)
    context = method_context
    if context is None and abc is not None:
        context = _build_method_context(abc, body)
    fast_text = _try_fast_emit_method_text(body, context, int_format=normalized_int_format)
    if fast_text is not None:
        return fast_text

    nf, context = _build_method_ir(
        body,
        style=style,
        abc=abc,
        method_context=context,
    )
    emitter = AS3Emitter(style=style, method_context=context, int_format=normalized_int_format, inline_vars=inline_vars)
    return emitter.emit(nf)


def _decompile_abc_methods_layout(
    abc: ABCFile,
    method_idx: int | None = None,
    *,
    style: str = "semantic",
    int_format: str = "dec",
    owner_map: dict[int, _MethodOwnerRef] | None = None,
    inline_vars: bool = False,
) -> str:
    if owner_map is None:
        owner_map = _build_method_owner_map(abc)

    def _header(method_body: MethodBody) -> str:
        method_info = abc.methods[method_body.method]
        return (
            f"// method {method_body.method} "
            f"params={len(method_info.params)} "
            f"locals={method_body.num_locals}"
        )

    if method_idx is not None:
        body = abc.method_body_at(method_idx)
        if body is None:
            raise ValueError(f"method index {method_idx} has no method body")
        context = _build_method_context(abc, body, owner_map)
        rendered = decompile_method(body, style=style, method_context=context, int_format=int_format, inline_vars=inline_vars)
        return f"{_header(body)}\n{rendered}"

    chunks: list[str] = []
    for body in abc.method_bodies:
        context = _build_method_context(abc, body, owner_map)
        rendered = decompile_method(body, style=style, method_context=context, int_format=int_format, inline_vars=inline_vars)
        chunks.append(f"{_header(body)}\n{rendered}")
    return "\n\n".join(chunks)


def _collect_script_method_entries(abc: ABCFile, script_index: int) -> tuple[str, list[_ClassMethodEntry]]:
    script = abc.scripts[script_index]
    owner_name = f"script_{script_index}"

    entries: list[_ClassMethodEntry] = []
    seen_method_indexes: set[int] = set()

    def _append(method_index: int | None, method_name: str, *, trait_kind: object | None) -> None:
        if method_index is None or method_index < 0:
            return
        if method_index in seen_method_indexes:
            return
        seen_method_indexes.add(method_index)
        entries.append(
            _ClassMethodEntry(
                method_index=method_index,
                method_name=method_name,
                trait_kind=trait_kind,
                static=True,
                is_constructor=False,
            )
        )

    _append(
        _index_value(getattr(script, "init_method", None)),
        "__script_init__",
        trait_kind=TraitKind.METHOD,
    )

    for trait in getattr(script, "traits", []):
        method_index = _trait_method_index(trait)
        if method_index is None:
            continue
        method_name = _short_multiname(getattr(trait, "name", f"method_{method_index}")) or f"method_{method_index}"
        _append(method_index, method_name, trait_kind=getattr(trait, "kind", None))

    return owner_name, entries


def _decompile_abc_classes_layout_blocks(
    abc: ABCFile,
    *,
    style: str = "semantic",
    int_format: str = "dec",
    owner_map: dict[int, _MethodOwnerRef] | None = None,
    inline_vars: bool = False,
) -> list[_ClassLayoutBlock]:
    if owner_map is None:
        owner_map = _build_method_owner_map(abc)

    blocks: list[_ClassLayoutBlock] = []

    class_count = min(len(abc.instances), len(abc.classes))
    covered_methods: set[int] = set()
    for class_index in range(class_count):
        package_parts, class_name, entries = _collect_class_method_entries(abc, class_index)
        instance = abc.instances[class_index] if class_index < len(abc.instances) else None
        cls = abc.classes[class_index] if class_index < len(abc.classes) else None
        class_signature = _build_class_signature(class_name, instance)
        lines = [f"{class_signature} {{"]

        field_initializers: dict[str, str] = {}
        rendered_methods: list[tuple[_ClassMethodEntry, MethodBody, MethodInfo, str, str]] = []

        for entry in entries:
            if not (0 <= entry.method_index < len(abc.methods)):
                continue
            body = abc.method_body_at(entry.method_index)
            if body is None:
                continue

            method_info = abc.methods[entry.method_index]
            context: MethodContext | None = None
            method_text = ""

            try:
                context = _build_method_context(abc, body, owner_map)
                fast_text = _try_fast_emit_method_text(body, context, int_format=int_format)
                if fast_text is not None:
                    method_text = fast_text
                else:
                    nf, context = _build_method_ir(
                        body,
                        style=style,
                        abc=abc,
                        owner_map=owner_map,
                        method_context=context,
                    )
                    nf, extracted = _extract_method_field_initializers(
                        nf,
                        style=style,
                        method_context=context,
                        int_format=int_format,
                    )
                    if entry.is_constructor:
                        for name, value in extracted.items():
                            field_initializers.setdefault(name, value)
                    method_text = AS3Emitter(
                        style=style,
                        method_context=context,
                        int_format=int_format,
                        inline_vars=inline_vars,
                    ).emit(nf).strip()
            except Exception as exc:  # pragma: no cover - defensive export fallback
                method_text = f"/* decompile_error: {exc.__class__.__name__}: {exc} */"

            signature = _render_layout_method_signature(
                class_name=class_name,
                entry=entry,
                method_info=method_info,
                context=context,
            )
            rendered_methods.append((entry, body, method_info, signature, method_text))
            covered_methods.add(entry.method_index)

        # 去重处理：避免instance_traits和class_traits包含相同的trait
        instance_traits_list = list(getattr(instance, "traits", [])) if instance is not None else []
        class_traits_list = list(getattr(cls, "traits", [])) if cls is not None else []
        
        # 使用trait名称作为key进行去重
        seen_trait_names: set[str] = set()
        unique_instance_traits: list[object] = []
        unique_class_traits: list[object] = []
        
        for trait in instance_traits_list:
            trait_name = _short_multiname(getattr(trait, "name", "")).strip()
            if trait_name and trait_name not in seen_trait_names:
                seen_trait_names.add(trait_name)
                unique_instance_traits.append(trait)
        
        for trait in class_traits_list:
            trait_name = _short_multiname(getattr(trait, "name", "")).strip()
            if trait_name and trait_name not in seen_trait_names:
                seen_trait_names.add(trait_name)
                unique_class_traits.append(trait)
        
        member_lines, _declared_members = _build_class_member_lines(
            abc,
            instance_traits=unique_instance_traits,
            class_traits=unique_class_traits,
            constructor_initializers=field_initializers,
        )
        if member_lines:
            lines.extend(member_lines)
            lines.append("")

        if not rendered_methods:
            lines.append("    // no resolvable methods")
            lines.append("}")
            blocks.append(_ClassLayoutBlock(class_name=class_name, source="\n".join(lines), package_parts=package_parts))
            continue

        for index, (entry, body, method_info, signature, method_text) in enumerate(rendered_methods):
            lines.append(
                f"    // method {entry.method_index} "
                f"params={len(method_info.params)} "
                f"locals={body.num_locals}"
            )
            lines.append(f"    {signature} {{")
            if method_text:
                for raw in method_text.splitlines():
                    lines.append(f"        {raw}")
            else:
                lines.append("        // empty")
            lines.append("    }")
            if index < len(rendered_methods) - 1:
                lines.append("")

        lines.append("}")
        blocks.append(_ClassLayoutBlock(class_name=class_name, source="\n".join(lines), package_parts=package_parts))

    for script_index in range(len(abc.scripts)):
        owner_name, entries = _collect_script_method_entries(abc, script_index)
        if not entries:
            continue

        lines = [f"class {owner_name} {{"]
        rendered = 0
        for entry in entries:
            if not (0 <= entry.method_index < len(abc.methods)):
                continue
            body = abc.method_body_at(entry.method_index)
            if body is None:
                continue

            method_info = abc.methods[entry.method_index]
            context: MethodContext | None = None
            method_text = ""
            try:
                context = _build_method_context(abc, body, owner_map)
                method_text = decompile_method(
                    body,
                    style=style,
                    method_context=context,
                    int_format=int_format,
                    inline_vars=inline_vars,
                ).strip()
            except Exception as exc:  # pragma: no cover - defensive export fallback
                method_text = f"/* decompile_error: {exc.__class__.__name__}: {exc} */"

            signature = _render_layout_method_signature(
                class_name=owner_name,
                entry=entry,
                method_info=method_info,
                context=context,
            )
            lines.append(
                f"    // method {entry.method_index} "
                f"params={len(method_info.params)} "
                f"locals={body.num_locals}"
            )
            lines.append(f"    {signature} {{")
            if method_text:
                for raw in method_text.splitlines():
                    lines.append(f"        {raw}")
            else:
                lines.append("        // empty")
            lines.append("    }")
            lines.append("")
            rendered += 1
            covered_methods.add(entry.method_index)

        if rendered <= 0:
            continue
        if lines and lines[-1] == "":
            lines.pop()
        lines.append("}")
        blocks.append(_ClassLayoutBlock(class_name=owner_name, source="\n".join(lines), package_parts=(), kind="script"))

    orphan_bodies = [body for body in abc.method_bodies if body.method not in covered_methods]
    if orphan_bodies:
        orphan_lines = ["class __orphan_methods__ {"]
        for index, body in enumerate(orphan_bodies):
            method_index = body.method
            if not (0 <= method_index < len(abc.methods)):
                continue
            method_info = abc.methods[method_index]
            entry = _ClassMethodEntry(
                method_index=method_index,
                method_name=f"method_{method_index}",
                trait_kind=None,
                static=True,
                is_constructor=False,
            )

            context: MethodContext | None = None
            method_text = ""
            try:
                context = _build_method_context(abc, body, owner_map)
                method_text = decompile_method(
                    body,
                    style=style,
                    method_context=context,
                    int_format=int_format,
                    inline_vars=inline_vars,
                ).strip()
            except Exception as exc:  # pragma: no cover - defensive export fallback
                method_text = f"/* decompile_error: {exc.__class__.__name__}: {exc} */"

            signature = _render_layout_method_signature(
                class_name="__orphan_methods__",
                entry=entry,
                method_info=method_info,
                context=context,
            )
            orphan_lines.append(
                f"    // method {method_index} "
                f"params={len(method_info.params)} "
                f"locals={body.num_locals}"
            )
            orphan_lines.append(f"    {signature} {{")
            if method_text:
                for raw in method_text.splitlines():
                    orphan_lines.append(f"        {raw}")
            else:
                orphan_lines.append("        // empty")
            orphan_lines.append("    }")
            if index < len(orphan_bodies) - 1:
                orphan_lines.append("")
        orphan_lines.append("}")
        blocks.append(_ClassLayoutBlock(class_name="__orphan_methods__", source="\n".join(orphan_lines), package_parts=(), kind="orphan"))

    return blocks


def _decompile_abc_classes_layout(
    abc: ABCFile,
    *,
    style: str = "semantic",
    int_format: str = "dec",
    owner_map: dict[int, _MethodOwnerRef] | None = None,
    inline_vars: bool = False,
) -> str:
    blocks = _decompile_abc_classes_layout_blocks(
        abc,
        style=style,
        int_format=int_format,
        owner_map=owner_map,
        inline_vars=inline_vars,
    )
    if not blocks:
        return _decompile_abc_methods_layout(
            abc,
            method_idx=None,
            style=style,
            int_format=int_format,
            owner_map=owner_map,
            inline_vars=inline_vars,
        )
    return "\n\n".join(block.source for block in blocks)


def _materialize_output_path(
    output_dir: Path,
    package_parts: tuple[str, ...],
    class_name: str,
    used_keys: set[str],
) -> Path:
    base = output_dir.joinpath(*package_parts, f"{class_name}.as")
    candidate = base
    suffix = 1
    key = candidate.as_posix().lower()
    while key in used_keys:
        candidate = output_dir.joinpath(*package_parts, f"{class_name}_{suffix}.as")
        key = candidate.as_posix().lower()
        suffix += 1
    used_keys.add(key)
    return candidate


def _prepare_output_root(output_root: Path, *, clean_output: bool) -> None:
    """Prepare output directory for file emission with defensive corner-case handling."""
    resolved_output = output_root.resolve()

    if clean_output:
        resolved_cwd = Path.cwd().resolve()
        if resolved_output == resolved_cwd:
            raise ValueError(
                "refusing to clean output_dir that resolves to current working directory"
            )
        if resolved_output.parent == resolved_output:
            raise ValueError("refusing to clean output_dir that resolves to filesystem root")

    if output_root.exists():
        if output_root.is_dir():
            if clean_output:
                shutil.rmtree(output_root)
        else:
            if not clean_output:
                raise NotADirectoryError(
                    f"output_dir points to a file and clean_output=False: {output_root}"
                )
            output_root.unlink()

    output_root.mkdir(parents=True, exist_ok=True)


def _decompile_abc_parsed_to_files(
    abc: ABCFile,
    output_dir: str | Path,
    *,
    style: str = "semantic",
    int_format: str = "dec",
    clean_output: bool = True,
    inline_vars: bool = False,
) -> list[Path]:
    normalized_int_format = _normalize_int_format(int_format)
    blocks = _decompile_abc_classes_layout_blocks(
        abc,
        style=style,
        int_format=normalized_int_format,
        owner_map=_build_method_owner_map(abc),
        inline_vars=inline_vars,
    )

    output_root = Path(output_dir)
    _prepare_output_root(output_root, clean_output=clean_output)

    written: list[Path] = []
    used_keys: set[str] = set()
    for block in blocks:
        output_path = _materialize_output_path(output_root, block.package_parts, block.class_name, used_keys)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(block.source + "\n", encoding="utf-8")
        written.append(output_path)
    return written


def decompile_abc_to_files(
    abc_data: bytes,
    output_dir: str | Path,
    *,
    style: str = "semantic",
    int_format: str = "dec",
    clean_output: bool = True,
    inline_vars: bool = False,
) -> list[Path]:
    abc = ABCFile.from_bytes(bytes(abc_data))
    return _decompile_abc_parsed_to_files(
        abc,
        output_dir,
        style=style,
        int_format=int_format,
        clean_output=clean_output,
        inline_vars=inline_vars,
    )


def _decompile_abc_parsed(
    abc: ABCFile,
    method_idx: int | None = None,
    *,
    style: str = "semantic",
    layout: str = "methods",
    int_format: str = "dec",
    inline_vars: bool = False,
) -> str:
    normalized_int_format = _normalize_int_format(int_format)
    if layout not in {"methods", "classes"}:
        raise ValueError(f"unsupported decompile layout: {layout}")

    owner_map = _build_method_owner_map(abc)
    if method_idx is not None or layout == "methods":
        return _decompile_abc_methods_layout(
            abc,
            method_idx=method_idx,
            style=style,
            int_format=normalized_int_format,
            owner_map=owner_map,
            inline_vars=inline_vars,
        )
    return _decompile_abc_classes_layout(
        abc,
        style=style,
        int_format=normalized_int_format,
        owner_map=owner_map,
        inline_vars=inline_vars,
    )


def _decompile_abc_uncached(
    abc_data: bytes,
    method_idx: int | None = None,
    *,
    style: str = "semantic",
    layout: str = "methods",
    int_format: str = "dec",
    inline_vars: bool = False,
) -> str:
    abc = ABCFile.from_bytes(abc_data)
    return _decompile_abc_parsed(
        abc,
        method_idx=method_idx,
        style=style,
        layout=layout,
        int_format=int_format,
        inline_vars=inline_vars,
    )


@lru_cache(maxsize=16)
def _decompile_abc_cached(
    abc_data: bytes,
    method_idx: int | None,
    style: str,
    layout: str,
    int_format: str,
    inline_vars: bool,
) -> str:
    return _decompile_abc_uncached(
        abc_data,
        method_idx=method_idx,
        style=style,
        layout=layout,
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
    # Cache is keyed by exact byte content and rendering style.
    normalized_int_format = _normalize_int_format(int_format)
    return _decompile_abc_cached(bytes(abc_data), method_idx, style, layout, normalized_int_format, bool(inline_vars))
