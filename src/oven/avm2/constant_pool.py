from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, TypeAlias

from .enums import (
    Index,
    NamespaceKind,
    MultinameKind,
    NamespaceDict,
    MultinameDict,
    ConstantPoolDict,
    MultinameQNameDict,
    MultinameRTQNameDict,
    MultinameMultinameDict,
    MultinameMultinameLDict,
    MultinameTypeNameDict,
    MultinameRTQNameLDict,
)

ResolvedValue: TypeAlias = (
    "str | int | float | NamespaceInfo | NamespaceSet | Multiname | MultinameRef"
)


class NamespaceInfo:
    """Immutable namespace entry."""

    __slots__ = ("kind", "name")

    def __init__(self, kind: NamespaceKind, name: int):
        self.kind = kind
        self.name = name  # Index into the string constant pool.

    def to_dict(self, pool: Optional["ConstantPool"] = None) -> NamespaceDict:
        """Return a serializable dictionary."""
        name_res = self.name
        if pool:
            name_res = pool.resolve_index(self.name, "string")
        return {"kind": self.kind.name, "name": name_res}

    def __repr__(self) -> str:
        return f"NamespaceInfo({self.kind.name}, name_idx={self.name})"


class NamespaceSet:
    """Immutable namespace-set entry."""

    __slots__ = ("namespaces",)

    def __init__(self, namespaces: List[NamespaceInfo]):
        self.namespaces = tuple(namespaces)  # Store as immutable tuple.

    def to_dict(self, pool: Optional["ConstantPool"] = None) -> List[NamespaceDict]:
        return [ns.to_dict(pool) for ns in self.namespaces]

    def __repr__(self) -> str:
        return f"NamespaceSet({len(self.namespaces)} namespaces)"


class Multiname:
    """Immutable multiname entry."""

    __slots__ = ("kind", "data")

    def __init__(self, kind: MultinameKind, data: Dict[str, Any]):
        self.kind = kind
        self.data = data  # Keep raw payload for compatibility.

    def to_dict(self, pool: Optional["ConstantPool"] = None) -> MultinameDict:
        """Return a serializable dictionary."""
        if self.kind in (MultinameKind.QNAME, MultinameKind.QNAMEA):
            ns = self.data.get("namespace")
            name = self.data.get("name")
            return MultinameQNameDict(
                kind="QNAME" if self.kind == MultinameKind.QNAME else "QNAMEA",
                namespace=ns.value if ns and hasattr(ns, "value") else 0,
                name=name.value if name and hasattr(name, "value") else 0,
            )

        elif self.kind in (MultinameKind.RTQNAME, MultinameKind.RTQNAMEA):
            name = self.data.get("name")
            return MultinameRTQNameDict(
                kind="RTQNAME" if self.kind == MultinameKind.RTQNAME else "RTQNAMEA",
                name=name.value if name and hasattr(name, "value") else 0,
            )

        elif self.kind in (MultinameKind.MULTINAME, MultinameKind.MULTINAMEA):
            name = self.data.get("name")
            ns_set = self.data.get("namespace_set")
            ns_set_idx = self._get_ns_set_index(ns_set, pool)
            return MultinameMultinameDict(
                kind=(
                    "MULTINAME"
                    if self.kind == MultinameKind.MULTINAME
                    else "MULTINAMEA"
                ),
                name=name.value if name and hasattr(name, "value") else 0,
                namespace_set=ns_set_idx,
            )

        elif self.kind in (MultinameKind.MULTINAMEL, MultinameKind.MULTINAMELA):
            ns_set = self.data.get("namespace_set")
            ns_set_idx = self._get_ns_set_index(ns_set, pool)
            return MultinameMultinameLDict(
                kind=(
                    "MULTINAMEL"
                    if self.kind == MultinameKind.MULTINAMEL
                    else "MULTINAMELA"
                ),
                namespace_set=ns_set_idx,
            )

        elif self.kind in (MultinameKind.RTQNAMEL, MultinameKind.RTQNAMELA):
            return MultinameRTQNameLDict(
                kind="RTQNameL" if self.kind == MultinameKind.RTQNAMEL else "RTQNameLA"
            )

        elif self.kind == MultinameKind.TYPENAME:
            base_type = self.data.get("base_type")
            parameters = self.data.get("parameters", [])
            return MultinameTypeNameDict(
                kind="TYPENAME",
                base_type=(
                    base_type.value if base_type and hasattr(base_type, "value") else 0
                ),
                parameters=[
                    param.value if hasattr(param, "value") else param
                    for param in parameters
                ],
            )

        raise ValueError(f"Unknown multiname kind: {self.kind}")

    def _get_ns_set_index(
        self, ns_set: Optional[NamespaceSet], pool: Optional["ConstantPool"]
    ) -> int:
        """Resolve namespace-set index from constant pool (1-based)."""
        if not ns_set or not pool:
            return 0
        return pool._namespace_set_index_lookup().get(ns_set, 0)

    def __repr__(self) -> str:
        return f"Multiname({self.kind.name}, data={self.data})"


class MultinameRef(str):
    """
    Resolved multiname value with AVM2 kind metadata.

    It behaves like a plain string for backward compatibility while carrying
    enough information for strict stack-effect decisions in higher layers.
    """

    __slots__ = ("kind", "ref_index")

    kind: MultinameKind | None
    ref_index: int

    def __new__(
        cls, text: str, kind: Optional[MultinameKind], ref_index: int
    ) -> "MultinameRef":
        obj = super().__new__(cls, text)
        object.__setattr__(obj, "kind", kind)
        object.__setattr__(obj, "ref_index", ref_index)
        return obj

    @property
    def runtime_arity(self) -> int:
        if self.kind in (MultinameKind.RTQNAME, MultinameKind.RTQNAMEA):
            return 1
        if self.kind in (MultinameKind.MULTINAMEL, MultinameKind.MULTINAMELA):
            return 1
        if self.kind in (MultinameKind.RTQNAMEL, MultinameKind.RTQNAMELA):
            return 2
        return 0


@dataclass
class ConstantPool:
    """Constant-pool model and index resolver."""

    ints: List[int]
    uints: List[int]
    doubles: List[float]
    strings: List[str]
    namespaces: List[NamespaceInfo]
    namespace_sets: List[NamespaceSet]
    multinames: List[Multiname]
    _preloaded_ints_1based: Optional[List[int]] = field(
        default=None, init=False, repr=False, compare=False
    )
    _preloaded_uints_1based: Optional[List[int]] = field(
        default=None, init=False, repr=False, compare=False
    )
    _preloaded_doubles_1based: Optional[List[float]] = field(
        default=None, init=False, repr=False, compare=False
    )
    _preloaded_strings_1based: Optional[List[str]] = field(
        default=None, init=False, repr=False, compare=False
    )
    _preloaded_namespaces_1based: Optional[List[str]] = field(
        default=None, init=False, repr=False, compare=False
    )
    _preloaded_ns_sets_1based: Optional[List[str]] = field(
        default=None, init=False, repr=False, compare=False
    )
    _preloaded_multinames_1based: Optional[List[Any]] = field(
        default=None, init=False, repr=False, compare=False
    )

    def _namespace_index_lookup(self) -> Dict[NamespaceInfo, int]:
        cached = getattr(self, "_namespace_index_lookup_cache", None)
        if isinstance(cached, dict):
            return cached
        lookup = {ns: idx + 1 for idx, ns in enumerate(self.namespaces)}
        setattr(self, "_namespace_index_lookup_cache", lookup)
        return lookup

    def _namespace_set_index_lookup(self) -> Dict[NamespaceSet, int]:
        cached = getattr(self, "_namespace_set_index_lookup_cache", None)
        if isinstance(cached, dict):
            return cached
        lookup = {ns_set: idx + 1 for idx, ns_set in enumerate(self.namespace_sets)}
        setattr(self, "_namespace_set_index_lookup_cache", lookup)
        return lookup

    def _resolve_cached(
        self, cache_name: str, idx: int, resolver: Callable[[int], Any]
    ) -> Any:
        cache = getattr(self, cache_name, None)
        if not isinstance(cache, dict):
            cache = {}
            setattr(self, cache_name, cache)
        if idx in cache:
            return cache[idx]
        resolved = resolver(idx)
        cache[idx] = resolved
        return resolved

    @staticmethod
    def _index_like_value(value: Any) -> Optional[int]:
        if isinstance(value, int):
            return value
        if isinstance(value, Index):
            return value.value
        raw_value = getattr(value, "value", None)
        if isinstance(raw_value, int):
            return raw_value
        return None

    def preload_resolved_indices(self) -> None:
        """Materialize 1-based resolved tables once for hot decoder paths."""
        if (
            isinstance(self._preloaded_ints_1based, list)
            and isinstance(self._preloaded_uints_1based, list)
            and isinstance(self._preloaded_doubles_1based, list)
            and isinstance(self._preloaded_strings_1based, list)
            and isinstance(self._preloaded_namespaces_1based, list)
            and isinstance(self._preloaded_ns_sets_1based, list)
            and isinstance(self._preloaded_multinames_1based, list)
        ):
            return

        strings_1based: List[str] = ["*"]
        strings_1based.extend(self.strings)

        ints_1based: List[int] = [0]
        ints_1based.extend(self.ints)

        uints_1based: List[int] = [0]
        uints_1based.extend(self.uints)

        doubles_1based: List[float] = [0.0]
        doubles_1based.extend(self.doubles)

        namespaces_1based: List[str] = ["*"]
        for namespace in self.namespaces:
            if namespace.name == 0:
                name_val = "*"
            elif 0 < namespace.name < len(strings_1based):
                name_val = strings_1based[namespace.name]
            else:
                name_val = f"#string_{namespace.name}"
            namespaces_1based.append(f"{namespace.kind.name}::{name_val}")

        ns_sets_1based: List[str] = ["*"]
        namespace_lookup = self._namespace_index_lookup()
        for ns_set in self.namespace_sets:
            ns_indices = [
                namespace_lookup.get(ns_info, 0) for ns_info in ns_set.namespaces
            ]
            ns_sets_1based.append(
                "(" + ", ".join(str(index) for index in ns_indices) + ")"
            )

        multinames_cache: List[Any] = [None] * (len(self.multinames) + 1)
        multinames_cache[0] = "*"
        visiting: Set[int] = set()

        for index_val in range(1, len(multinames_cache)):
            self._resolve_multiname_preloaded_index(
                index_val=index_val,
                strings_1based=strings_1based,
                namespaces_1based=namespaces_1based,
                multinames_cache=multinames_cache,
                visiting=visiting,
            )

        self._preloaded_ints_1based = ints_1based
        self._preloaded_uints_1based = uints_1based
        self._preloaded_doubles_1based = doubles_1based
        self._preloaded_strings_1based = strings_1based
        self._preloaded_namespaces_1based = namespaces_1based
        self._preloaded_ns_sets_1based = ns_sets_1based
        self._preloaded_multinames_1based = [
            entry if entry is not None else "*" for entry in multinames_cache
        ]

    def _resolve_multiname_preloaded_index(
        self,
        *,
        index_val: int,
        strings_1based: List[str],
        namespaces_1based: List[str],
        multinames_cache: List[Any],
        visiting: Set[int],
    ) -> Any:
        cached = (
            multinames_cache[index_val]
            if 0 <= index_val < len(multinames_cache)
            else None
        )
        if cached is not None:
            return cached

        if index_val in visiting:
            cycle_ref = MultinameRef(f"#multiname_{index_val}", None, index_val)
            multinames_cache[index_val] = cycle_ref
            return cycle_ref

        visiting.add(index_val)
        try:
            idx = index_val - 1
            if not (0 <= idx < len(self.multinames)):
                resolved: Any = MultinameRef(f"#multiname_{index_val}", None, index_val)
            else:
                mn = self.multinames[idx]
                if not isinstance(mn, Multiname):
                    resolved = MultinameRef(str(mn), None, index_val)
                elif mn.kind == MultinameKind.TYPENAME:
                    base = self._resolve_typename_component_preloaded(
                        mn.data.get("base_type"),
                        strings_1based=strings_1based,
                        namespaces_1based=namespaces_1based,
                        multinames_cache=multinames_cache,
                        visiting=visiting,
                    )
                    raw_parameters = mn.data.get("parameters", [])
                    params: List[str] = []
                    for parameter in raw_parameters:
                        params.append(
                            self._resolve_typename_component_preloaded(
                                parameter,
                                strings_1based=strings_1based,
                                namespaces_1based=namespaces_1based,
                                multinames_cache=multinames_cache,
                                visiting=visiting,
                            )
                        )
                    resolved = MultinameRef(
                        f"{base}.<{', '.join(params)}>", mn.kind, index_val
                    )
                else:
                    resolved = MultinameRef(
                        self._format_multiname_preloaded(
                            mn, strings_1based, namespaces_1based
                        ),
                        mn.kind,
                        index_val,
                    )

            multinames_cache[index_val] = resolved
            return resolved
        finally:
            visiting.discard(index_val)

    def _resolve_typename_component_preloaded(
        self,
        raw_index: Any,
        *,
        strings_1based: List[str],
        namespaces_1based: List[str],
        multinames_cache: List[Any],
        visiting: Set[int],
    ) -> str:
        index_val = self._index_like_value(raw_index)
        if index_val is None or index_val <= 0:
            return "*"
        if index_val >= len(multinames_cache):
            return f"#multiname_{index_val}"

        resolved = self._resolve_multiname_preloaded_index(
            index_val=index_val,
            strings_1based=strings_1based,
            namespaces_1based=namespaces_1based,
            multinames_cache=multinames_cache,
            visiting=visiting,
        )
        return str(resolved)

    def _format_multiname_preloaded(
        self,
        mn: Multiname,
        strings_1based: List[str],
        namespaces_1based: List[str],
    ) -> str:
        """Format multiname from preloaded 1-based tables without resolve_index calls."""
        data = mn.data
        name = "*"
        ns_str = ""

        raw_name_index = self._index_like_value(data.get("name"))
        if raw_name_index is not None and raw_name_index > 0:
            if raw_name_index < len(strings_1based):
                name = strings_1based[raw_name_index]
            else:
                name = f"#string_{raw_name_index}"

        raw_ns_index = self._index_like_value(data.get("namespace"))
        if raw_ns_index is not None and raw_ns_index > 0:
            if raw_ns_index < len(namespaces_1based):
                ns_str = namespaces_1based[raw_ns_index] + "::"
            else:
                ns_str = f"#namespace_{raw_ns_index}::"
        elif "namespace_set" in data:
            ns_str = "[NsSet]::"

        return f"{ns_str}{name}"

    def get_preloaded_table(self, kind_hint: str) -> List[Any]:
        """Return resolved 1-based tables used by the decoder hot path."""
        self.preload_resolved_indices()

        if kind_hint == "int":
            return self._preloaded_ints_1based or [0]
        if kind_hint == "uint":
            return self._preloaded_uints_1based or [0]
        if kind_hint == "double":
            return self._preloaded_doubles_1based or [0.0]
        if kind_hint == "string":
            return self._preloaded_strings_1based or ["*"]
        if kind_hint == "namespace":
            return self._preloaded_namespaces_1based or ["*"]
        if kind_hint == "ns_set":
            return self._preloaded_ns_sets_1based or ["*"]
        if kind_hint == "multiname":
            return self._preloaded_multinames_1based or ["*"]
        return ["*"]

    def resolve_index(self, index_val: int, kind_hint: str | None = None) -> Any:
        """Resolve a 1-based constant-pool index with an optional kind hint."""
        if index_val == 0:
            return "*"  # AVM2 zero index means any/null/undefined.

        if kind_hint == "string" and isinstance(self._preloaded_strings_1based, list):
            if 0 < index_val < len(self._preloaded_strings_1based):
                return self._preloaded_strings_1based[index_val]
            return f"#string_{index_val}"

        if kind_hint == "namespace" and isinstance(
            self._preloaded_namespaces_1based, list
        ):
            if 0 < index_val < len(self._preloaded_namespaces_1based):
                return self._preloaded_namespaces_1based[index_val]
            return f"#namespace_{index_val}"

        if kind_hint == "ns_set" and isinstance(self._preloaded_ns_sets_1based, list):
            if 0 < index_val < len(self._preloaded_ns_sets_1based):
                return self._preloaded_ns_sets_1based[index_val]
            return f"#ns_set_{index_val}"

        if kind_hint == "multiname" and isinstance(
            self._preloaded_multinames_1based, list
        ):
            if 0 < index_val < len(self._preloaded_multinames_1based):
                return self._preloaded_multinames_1based[index_val]
            return MultinameRef(f"#multiname_{index_val}", None, index_val)

        if kind_hint == "int" and isinstance(self._preloaded_ints_1based, list):
            if 0 < index_val < len(self._preloaded_ints_1based):
                return self._preloaded_ints_1based[index_val]
            return 0

        if kind_hint == "uint" and isinstance(self._preloaded_uints_1based, list):
            if 0 < index_val < len(self._preloaded_uints_1based):
                return self._preloaded_uints_1based[index_val]
            return 0

        if kind_hint == "double" and isinstance(self._preloaded_doubles_1based, list):
            if 0 < index_val < len(self._preloaded_doubles_1based):
                return self._preloaded_doubles_1based[index_val]
            return 0.0

        idx = index_val - 1  # Constant-pool indices are 1-based.

        if kind_hint == "string":
            return self._resolve_string(idx)
        elif kind_hint == "namespace":
            return self._resolve_cached(
                "_namespace_resolve_cache", idx, self._resolve_namespace
            )
        elif kind_hint == "ns_set":
            return self._resolve_cached(
                "_ns_set_resolve_cache", idx, self._resolve_ns_set
            )
        elif kind_hint == "multiname":
            return self._resolve_cached(
                "_multiname_resolve_cache", idx, self._resolve_multiname
            )
        elif kind_hint == "int":
            return self._resolve_int(idx)
        elif kind_hint == "uint":
            return self._resolve_uint(idx)
        elif kind_hint == "double":
            return self._resolve_double(idx)

        return f"#{index_val}"

    def _resolve_string(self, idx: int) -> str:
        if 0 <= idx < len(self.strings):
            return self.strings[idx]
        return f"#string_{idx + 1}"

    def _resolve_namespace(self, idx: int) -> str:
        if 0 <= idx < len(self.namespaces):
            ns = self.namespaces[idx]
            name_val = self.resolve_index(ns.name, "string") if ns.name != 0 else "*"
            return f"{ns.kind.name}::{name_val}"
        return f"#namespace_{idx + 1}"

    def _resolve_ns_set(self, idx: int) -> str:
        if 0 <= idx < len(self.namespace_sets):
            ns_list = self.namespace_sets[idx].namespaces
            namespace_lookup = self._namespace_index_lookup()
            ns_indices = []
            for ns_info in ns_list:
                ns_indices.append(namespace_lookup.get(ns_info, 0))
            return "(" + ", ".join(str(i) for i in ns_indices) + ")"
        return f"#ns_set_{idx + 1}"

    def _resolve_multiname(self, idx: int) -> Any:
        if 0 <= idx < len(self.multinames):
            mn = self.multinames[idx]
            if not isinstance(mn, Multiname):
                return MultinameRef(str(mn), None, idx + 1)
            if mn.kind == MultinameKind.TYPENAME:
                base = self.resolve_index(mn.data["base_type"].value, "multiname")
                params = [
                    self.resolve_index(p.value, "multiname")
                    for p in mn.data["parameters"]
                ]
                return MultinameRef(f"{base}.<{', '.join(params)}>", mn.kind, idx + 1)
            return MultinameRef(self._format_multiname(mn), mn.kind, idx + 1)
        return MultinameRef(f"#multiname_{idx + 1}", None, idx + 1)

    def _resolve_int(self, idx: int) -> int:
        if 0 <= idx < len(self.ints):
            return self.ints[idx]
        return 0

    def _resolve_uint(self, idx: int) -> int:
        if 0 <= idx < len(self.uints):
            return self.uints[idx]
        return 0

    def _resolve_double(self, idx: int) -> float:
        if 0 <= idx < len(self.doubles):
            return self.doubles[idx]
        return 0.0

    def _format_multiname(self, mn: Multiname) -> str:
        """Format a multiname to a readable representation."""
        data = mn.data
        name = "*"
        ns_str = ""

        # Resolve short name.
        if "name" in data and isinstance(data["name"], Index):
            name_val = self.resolve_index(data["name"].value, "string")
            name = name_val if data["name"].value != 0 else "*"

        # Resolve namespace prefix.
        if "namespace" in data and isinstance(data["namespace"], Index):
            ns_str = self.resolve_index(data["namespace"].value, "namespace") + "::"
        elif "namespace_set" in data:
            ns_str = f"[NsSet]::"

        return f"{ns_str}{name}"

    def to_dict(self, pool: Optional["ConstantPool"] = None) -> ConstantPoolDict:
        """Return a serializable dictionary."""
        # Serialize namespace sets using cached index lookup.
        namespace_lookup = self._namespace_index_lookup()
        serialized_ns_sets = []
        for ns_set in self.namespace_sets:
            ns_indices = []
            for ns_info in ns_set.namespaces:
                ns_indices.append(namespace_lookup.get(ns_info, 0))
            serialized_ns_sets.append(ns_indices)

        # Serialize multinames.
        multinames = [mn.to_dict(pool) for mn in self.multinames]

        return {
            "ints": self.ints,
            "uints": self.uints,
            "doubles": self.doubles,
            "strings": self.strings,
            "namespaces": [ns.to_dict(pool) for ns in self.namespaces],
            "namespace_sets": serialized_ns_sets,
            "multinames": multinames,
        }

    def __repr__(self) -> str:
        return (
            f"ConstantPool(ints={len(self.ints)}, uints={len(self.uints)}, "
            f"doubles={len(self.doubles)}, strings={len(self.strings)}, "
            f"namespaces={len(self.namespaces)}, namespace_sets={len(self.namespace_sets)}, "
            f"multinames={len(self.multinames)})"
        )

    def __str__(self) -> str:
        """Return full constant-pool details without truncation."""
        lines = []
        lines.append("Constant Pool:")

        # Integer constant pool.
        lines.append(f"  Integers: {len(self.ints)} entries")
        if self.ints:
            for i, val in enumerate(self.ints):
                lines.append(f"    [{i}] {val}")

        # Unsigned integer constant pool.
        lines.append(f"  Unsigned Integers: {len(self.uints)} entries")
        if self.uints:
            for i, uint_val in enumerate(self.uints):
                lines.append(f"    [{i}] {uint_val}")

        # Double constant pool.
        lines.append(f"  Doubles: {len(self.doubles)} entries")
        if self.doubles:
            for i, double_val in enumerate(self.doubles):
                lines.append(f"    [{i}] {double_val}")

        # String constant pool.
        lines.append(f"  Strings: {len(self.strings)} entries")
        if self.strings:
            for i, string_val in enumerate(self.strings):
                lines.append(f'    [{i}] "{string_val}"')

        # Namespace constant pool.
        lines.append(f"  Namespaces: {len(self.namespaces)} entries")
        if self.namespaces:
            for i, ns in enumerate(self.namespaces):
                lines.append(f"    [{i}] {ns}")

        # Namespace-set constant pool.
        lines.append(f"  Namespace Sets: {len(self.namespace_sets)} entries")
        if self.namespace_sets:
            for i, ns_set in enumerate(self.namespace_sets):
                lines.append(f"    [{i}] {ns_set}")

        # Multiname constant pool.
        lines.append(f"  Multinames: {len(self.multinames)} entries")
        if self.multinames:
            for i, mn in enumerate(self.multinames):
                lines.append(f"    [{i}] {mn}")

        return "\n".join(lines)
