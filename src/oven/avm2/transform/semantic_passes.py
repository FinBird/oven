# Optimized semantic passes for AVM2 decompilation.
# Performance: keep transformations in a unified visitor pipeline to reduce repeated AST traversals.
from __future__ import annotations

from typing import Any, Iterator

from oven.core.ast import Node, NodeVisitor, m
from oven.core.pipeline import Transform

from .node_types import AS3NodeTypes as NT


def _index_value(value: object) -> int | None:
    if isinstance(value, int):
        return value
    idx = getattr(value, "value", None)
    if isinstance(idx, int):
        return idx
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed


def _property_name(value: object) -> str:
    text = str(value)
    if "::" in text:
        text = text.rsplit("::", 1)[1]
    parts = [segment for segment in text.split(".") if segment]
    while len(parts) >= 2 and parts[-1] == parts[-2]:
        parts.pop(-2)
    return ".".join(parts) if parts else text


def _normalize_type_hint(value: object) -> str | None:
    if isinstance(value, Node):
        if value.type == NT.STRING and value.children:
            return _normalize_type_hint(value.children[0])
        if value.type in {NT.GET_LEX, NT.FIND_PROPERTY, NT.FIND_PROPERTY_STRICT} and value.children:
            return _normalize_type_hint(value.children[0])
        return None

    text = str(value).strip()
    if not text:
        return None
    text = _property_name(text)
    lowered = text.lower()
    if lowered in {"boolean", "bool"}:
        return "Boolean"
    if lowered in {"*", "any"}:
        return "*"
    return text


_CONVERT_WRAPPER_TYPES = frozenset(
    {
        NT.COERCE,
        NT.CONVERT,
        NT.COERCE_B,
        NT.CONVERT_I,
        NT.CONVERT_U,
        NT.CONVERT_D,
        NT.CONVERT_S,
        NT.CONVERT_O,
    }
)

_BOOLEAN_CONVERT_WRAPPER_TYPES = frozenset({NT.COERCE_B})


def _unwrap_convert_chain(value: object) -> object:
    current = value
    while isinstance(current, Node) and current.type in _CONVERT_WRAPPER_TYPES and current.children:
        current = current.children[-1]
    return current


class AstSemanticNormalizePass(Transform, NodeVisitor):
    """Semantic cleanup pass for decompiler-friendly AST output."""
    _LOCAL_INDEXED_OPS = frozenset(
        {
            NT.GET_LOCAL,
            NT.SET_LOCAL,
            NT.INC_LOCAL,
            NT.INC_LOCAL_I,
            NT.DEC_LOCAL,
            NT.DEC_LOCAL_I,
            NT.PRE_INCREMENT_LOCAL,
            NT.POST_INCREMENT_LOCAL,
            NT.PRE_DECREMENT_LOCAL,
            NT.POST_DECREMENT_LOCAL,
            NT.KILL,
        }
    )
    _LOCAL_WRITE_OPS = frozenset(
        {
            NT.SET_LOCAL,
            NT.INC_LOCAL,
            NT.INC_LOCAL_I,
            NT.DEC_LOCAL,
            NT.DEC_LOCAL_I,
            NT.PRE_INCREMENT_LOCAL,
            NT.POST_INCREMENT_LOCAL,
            NT.PRE_DECREMENT_LOCAL,
            NT.POST_DECREMENT_LOCAL,
            NT.KILL,
        }
    )
    _ADD_OPS = frozenset({NT.ADD, "+"})
    _SUBTRACT_OPS = frozenset({"subtract", "-"})
    _MULTIPLY_OPS = frozenset({"multiply", "*"})
    _EQUALS_OPS = frozenset({"==", "==="})
    _NOT_EQUALS_OPS = frozenset({"!=", "!=="})
    _ALIASABLE_RHS_TYPES = frozenset({NT.GET_LOCAL})

    def __init__(
        self,
        *,
        slot_name_map: dict[int, str] | None = None,
        global_slot_name_map: dict[int, str] | None = None,
        assume_normalized: bool = False,
    ) -> None:
        def _normalize(raw_map: dict[int, str] | None) -> dict[int, str]:
            normalized: dict[int, str] = {}
            if not raw_map:
                return normalized
            for raw_slot_id, raw_name in raw_map.items():
                slot_id = _index_value(raw_slot_id)
                if slot_id is None or slot_id <= 0:
                    continue
                slot_name = _property_name(raw_name).strip()
                if not slot_name:
                    continue
                normalized[slot_id] = slot_name
            return normalized

        self._slot_name_map = _normalize(slot_name_map)
        # Backward compatibility: when no dedicated global map is provided,
        # preserve the historical behavior that reused slot_name_map.
        self._global_slot_name_map = _normalize(global_slot_name_map) if global_slot_name_map is not None else dict(self._slot_name_map)
        self._assume_normalized = bool(assume_normalized)

    def visit(self, node: Node) -> Node:
        # Preserve the hot-path visitor cache behavior from NodeVisitor.
        return super().visit(node)

    # TODO: Implement structural pattern matching for Vector.<T> initialization.
    # TODO: Add data-flow analysis to eliminate dead local assignments before return paths.

    def transform(self, *args: Any) -> Any:
        if not args:
            return args
        root = args[0]
        if not isinstance(root, Node):
            return args

        if not self._assume_normalized:
            root.normalize_hierarchy()
        self.visit(root)
        if len(args) == 1:
            return root
        return (root, *args[1:])

    def _strip_boolean_wrapper(self, value: object) -> object:
        current = value
        while isinstance(current, Node):
            if current.type in _BOOLEAN_CONVERT_WRAPPER_TYPES and current.children:
                current = current.children[-1]
                continue
            if current.type in {NT.COERCE, NT.CONVERT} and len(current.children) >= 2:
                hinted = _normalize_type_hint(current.children[0])
                if hinted == "Boolean":
                    current = current.children[-1]
                    continue
            break
        return current

    @staticmethod
    def _invert_comparison(value: Node) -> Node | None:
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
        op = invert_map.get(value.type)
        if op is None or len(value.children) < 2:
            return None
        return Node(op, [value.children[0], value.children[1]], dict(value.metadata))

    def _is_find_property_of(self, value: object, name: object) -> bool:
        if not isinstance(value, Node):
            return False
        if value.type not in {NT.FIND_PROPERTY, NT.FIND_PROPERTY_STRICT}:
            return False
        if not value.children:
            return False
        return _property_name(value.children[0]) == _property_name(name)

    def _is_get_local_of(self, value: object, index: int) -> bool:
        unwrapped = _unwrap_convert_chain(value)
        if not isinstance(unwrapped, Node) or unwrapped.type != NT.GET_LOCAL or not unwrapped.children:
            return False
        return _index_value(unwrapped.children[0]) == index

    def _subject_local_index(self, value: object) -> int | None:
        unwrapped = _unwrap_convert_chain(value)
        if not isinstance(unwrapped, Node) or unwrapped.type != NT.GET_LOCAL or not unwrapped.children:
            return None
        return _index_value(unwrapped.children[0])

    @staticmethod
    def _is_ignorable_literal_stmt(value: object) -> bool:
        return isinstance(value, Node) and value.type in {NT.NOP, NT.LABEL}

    def _alias_local_assignment(self, stmt: object, aliases: set[int]) -> int | None:
        if not isinstance(stmt, Node) or stmt.type != NT.SET_LOCAL or len(stmt.children) < 2:
            return None
        target_idx = _index_value(stmt.children[0])
        if target_idx is None:
            return None
        source_idx = self._subject_local_index(stmt.children[1])
        if source_idx is None or source_idx not in aliases:
            return None
        return target_idx

    def _array_construct_arity(self, rhs: Node) -> int | None:
        if rhs.type != NT.CONSTRUCT or not rhs.children:
            return None
        ctor = _unwrap_convert_chain(rhs.children[0])
        if not isinstance(ctor, Node) or ctor.type != NT.GET_LEX or not ctor.children:
            return None
        if _property_name(ctor.children[0]) != "Array":
            return None
        # construct children: [ctor, *args]
        return len(rhs.children) - 1

    def _object_construct(self, rhs: Node) -> bool:
        if rhs.type != NT.CONSTRUCT or not rhs.children:
            return False
        ctor = _unwrap_convert_chain(rhs.children[0])
        if not isinstance(ctor, Node) or ctor.type != NT.GET_LEX or not ctor.children:
            return False
        return _property_name(ctor.children[0]) == "Object"

    def _literal_index(self, value: object) -> int | None:
        if isinstance(value, Node) and value.type in {NT.INTEGER, NT.UNSIGNED} and value.children:
            return _index_value(value.children[0])
        if isinstance(value, int):
            return value
        return None

    def _literal_key(self, value: object) -> Node | None:
        if isinstance(value, Node):
            if value.type in {NT.STRING, NT.INTEGER, NT.UNSIGNED}:
                return value
            return None
        if isinstance(value, str):
            return Node(NT.STRING, [value])
        if isinstance(value, int):
            return Node(NT.INTEGER, [value])
        return None

    def _reconstruct_array_literal(self, children: list[object], start: int) -> tuple[Node, list[int]] | None:
        stmt = children[start]
        if not isinstance(stmt, Node) or stmt.type != NT.SET_LOCAL or len(stmt.children) < 2:
            return None

        local_index = _index_value(stmt.children[0])
        rhs = stmt.children[1]
        if local_index is None or not isinstance(rhs, Node):
            return None

        arity = self._array_construct_arity(rhs)
        if arity is None:
            return None

        # new Array() -> []
        if arity == 0:
            rebuilt = Node(NT.SET_LOCAL, [local_index, Node(NT.NEW_ARRAY, [])], dict(stmt.metadata))
            return rebuilt, []

        # new Array(a, b, c) -> [a, b, c]
        if arity > 1:
            rebuilt = Node(NT.SET_LOCAL, [local_index, Node(NT.NEW_ARRAY, list(rhs.children[1:]))], dict(stmt.metadata))
            return rebuilt, []

        declared_len: int | None = None
        if arity == 1:
            declared_len = self._literal_index(rhs.children[1])

        assignments: dict[int, object] = {}
        removable_indexes: list[int] = []
        aliases = {local_index}
        cursor = start + 1
        while cursor < len(children):
            candidate = children[cursor]
            if self._is_ignorable_literal_stmt(candidate):
                cursor += 1
                continue

            alias_local = self._alias_local_assignment(candidate, aliases)
            if alias_local is not None:
                aliases.add(alias_local)
                cursor += 1
                continue

            if not isinstance(candidate, Node) or candidate.type not in {NT.SET_PROPERTY, NT.INIT_PROPERTY} or len(candidate.children) != 3:
                break
            subject_local = self._subject_local_index(candidate.children[0])
            if subject_local is None or subject_local not in aliases:
                break
            idx = self._literal_index(candidate.children[1])
            if idx is None or idx < 0 or idx in assignments:
                break
            assignments[idx] = candidate.children[2]
            removable_indexes.append(cursor)
            cursor += 1

        if not assignments:
            if declared_len == 0:
                rebuilt = Node(NT.SET_LOCAL, [local_index, Node(NT.NEW_ARRAY, [])], dict(stmt.metadata))
                return rebuilt, []
            return None

        max_index = max(assignments)
        if sorted(assignments.keys()) != list(range(max_index + 1)):
            return None
        if declared_len is not None and declared_len != max_index + 1:
            return None

        values = [assignments[idx] for idx in range(max_index + 1)]
        rebuilt = Node(NT.SET_LOCAL, [local_index, Node(NT.NEW_ARRAY, values)], dict(stmt.metadata))
        return rebuilt, removable_indexes

    def _reconstruct_object_literal(self, children: list[object], start: int) -> tuple[Node, list[int]] | None:
        stmt = children[start]
        if not isinstance(stmt, Node) or stmt.type != NT.SET_LOCAL or len(stmt.children) < 2:
            return None
        local_index = _index_value(stmt.children[0])
        rhs = stmt.children[1]
        if local_index is None or not isinstance(rhs, Node) or not self._object_construct(rhs):
            return None

        pairs: list[object] = []
        removable_indexes: list[int] = []
        aliases = {local_index}
        cursor = start + 1
        while cursor < len(children):
            candidate = children[cursor]
            if self._is_ignorable_literal_stmt(candidate):
                cursor += 1
                continue

            alias_local = self._alias_local_assignment(candidate, aliases)
            if alias_local is not None:
                aliases.add(alias_local)
                cursor += 1
                continue

            if not isinstance(candidate, Node) or candidate.type not in {NT.SET_PROPERTY, NT.INIT_PROPERTY} or len(candidate.children) != 3:
                break
            subject_local = self._subject_local_index(candidate.children[0])
            if subject_local is None or subject_local not in aliases:
                break
            key = self._literal_key(candidate.children[1])
            if key is None:
                break
            pairs.extend([key, candidate.children[2]])
            removable_indexes.append(cursor)
            cursor += 1

        if not pairs:
            rebuilt = Node(NT.SET_LOCAL, [local_index, Node(NT.NEW_OBJECT, [])], dict(stmt.metadata))
            return rebuilt, []
        rebuilt = Node(NT.SET_LOCAL, [local_index, Node(NT.NEW_OBJECT, pairs)], dict(stmt.metadata))
        return rebuilt, removable_indexes

    def _iter_nodes(self, value: object) -> Iterator[Node]:
        if not isinstance(value, Node):
            return
        stack: list[Node] = [value]
        while stack:
            node = stack.pop()
            yield node
            for child in reversed(node.children):
                if isinstance(child, Node):
                    stack.append(child)

    def _count_local_mentions(self, value: object, local_index: int) -> int:
        count = 0
        for node in self._iter_nodes(value):
            if node.type in self._LOCAL_INDEXED_OPS and node.children:
                idx = _index_value(node.children[0])
                if idx == local_index:
                    count += 1
            elif node.type in {NT.FOR_IN, NT.FOR_EACH_IN}:
                if len(node.children) > 0 and _index_value(node.children[0]) == local_index:
                    count += 1
                if len(node.children) > 2 and _index_value(node.children[2]) == local_index:
                    count += 1
        return count

    def _replace_local_in_convert_chain(
        self,
        value: object,
        local_index: int,
        replacement: object,
    ) -> object | None:
        if isinstance(value, Node) and value.type in _CONVERT_WRAPPER_TYPES and value.children:
            replaced_tail = self._replace_local_in_convert_chain(value.children[-1], local_index, replacement)
            if replaced_tail is None:
                return None
            updated_children = list(value.children)
            updated_children[-1] = replaced_tail
            return Node(value.type, updated_children, dict(value.metadata))

        if isinstance(value, Node) and value.type == NT.GET_LOCAL and value.children:
            if _index_value(value.children[0]) == local_index:
                return replacement
        return None

    def _replace_local_reads(self, value: object, local_index: int, replacement: Node) -> tuple[object, int]:
        if not isinstance(value, Node):
            return value, 0

        if value.type == NT.GET_LOCAL and value.children and _index_value(value.children[0]) == local_index:
            return self._clone_tree(replacement), 1

        replaced_count = 0
        updated_children: list[object] = []
        for idx, child in enumerate(value.children):
            # Local-indexed ops encode destination/source index in operand position 0.
            if value.type in self._LOCAL_INDEXED_OPS and idx == 0:
                updated_children.append(child)
                continue
            # for-in forms store local indexes in slot positions, not expression reads.
            if value.type in {NT.FOR_IN, NT.FOR_EACH_IN} and idx in {0, 2}:
                updated_children.append(child)
                continue

            rewritten_child, child_count = self._replace_local_reads(child, local_index, replacement)
            replaced_count += child_count
            updated_children.append(rewritten_child)

        if replaced_count == 0:
            return value, 0
        return Node(value.type, updated_children, dict(value.metadata)), replaced_count

    def _is_local_write_stmt(self, stmt: object, local_index: int) -> bool:
        if not isinstance(stmt, Node):
            return False

        if stmt.type in self._LOCAL_WRITE_OPS and stmt.children:
            return _index_value(stmt.children[0]) == local_index

        if stmt.type in {NT.FOR_IN, NT.FOR_EACH_IN}:
            if len(stmt.children) > 0 and _index_value(stmt.children[0]) == local_index:
                return True
            if len(stmt.children) > 2 and _index_value(stmt.children[2]) == local_index:
                return True

        return False

    def _next_meaningful_stmt(self, children: list[object], start: int) -> int | None:
        idx = start
        while idx < len(children):
            if self._is_ignorable_literal_stmt(children[idx]):
                idx += 1
                continue
            return idx
        return None

    @staticmethod
    def _clone_tree(value: object) -> object:
        if not isinstance(value, Node):
            return value
        return Node(
            value.type,
            [AstSemanticNormalizePass._clone_tree(child) for child in value.children],
            dict(value.metadata),
        )

    @staticmethod
    def _as_begin_block(value: object) -> Node:
        if isinstance(value, Node):
            if value.type == NT.BEGIN:
                return value
            return Node(NT.BEGIN, [value], dict(value.metadata))
        return Node(NT.BEGIN)

    @staticmethod
    def _single_return_stmt(value: object) -> Node | None:
        if not isinstance(value, Node):
            return None
        if value.type in {NT.RETURN_VALUE, NT.RETURN_VOID}:
            return value
        if value.type == NT.BEGIN and len(value.children) == 1:
            child = value.children[0]
            if isinstance(child, Node) and child.type in {NT.RETURN_VALUE, NT.RETURN_VOID}:
                return child
        return None

    @staticmethod
    def _is_effectively_empty_block(value: object) -> bool:
        if not isinstance(value, Node):
            return True
        if value.type in {NT.NOP, NT.LABEL}:
            return True
        if value.type != NT.BEGIN:
            return False

        for child in value.children:
            if not isinstance(child, Node):
                return False
            if child.type not in {NT.NOP, NT.LABEL}:
                return False
        return True

    @staticmethod
    def _negated_condition(value: object) -> object:
        if isinstance(value, Node) and value.type == "!" and len(value.children) == 1:
            return value.children[0]
        return Node("!", [value])

    @staticmethod
    def _int_literal_value(value: object) -> int | None:
        if isinstance(value, int):
            return value
        if isinstance(value, Node) and value.type in {NT.INTEGER, NT.UNSIGNED} and value.children:
            return _index_value(value.children[0])
        return None

    @staticmethod
    def _rewrite_to(node: Node, replacement: Node) -> None:
        node.update(node_type=replacement.type, children=list(replacement.children))
        node.metadata = dict(replacement.metadata)

    @staticmethod
    def _rewrite_to_literal(node: Node, node_type: str, value: object) -> None:
        node.update(node_type=node_type, children=[value])
        node.metadata = {}

    @staticmethod
    def _rewrite_to_leaf(node: Node, node_type: str) -> None:
        node.update(node_type=node_type, children=[])
        node.metadata = {}

    def _fold_add(self, node: Node) -> None:
        if len(node.children) != 2:
            return
        left, right = node.children
        left_int = self._int_literal_value(left)
        right_int = self._int_literal_value(right)

        if left_int is not None and right_int is not None:
            self._rewrite_to_literal(node, NT.INTEGER, left_int + right_int)
            return

        if (
            isinstance(left, Node)
            and left.type == NT.STRING
            and left.children
            and isinstance(right, Node)
            and right.type == NT.STRING
            and right.children
            and isinstance(left.children[0], str)
            and isinstance(right.children[0], str)
        ):
            self._rewrite_to_literal(node, NT.STRING, left.children[0] + right.children[0])
            return

        if right_int == 0 and isinstance(left, Node):
            self._rewrite_to(node, left)
            return
        if left_int == 0 and isinstance(right, Node):
            self._rewrite_to(node, right)
            return

        match node.children:
            case [Node(node_type, [x, Node(NT.INTEGER, [a], _)], _), Node(NT.INTEGER, [b], _)] if node_type in self._SUBTRACT_OPS and isinstance(a, int) and isinstance(b, int) and a == b:
                if isinstance(x, Node):
                    self._rewrite_to(node, x)
            case _:
                return

    def _fold_subtract(self, node: Node) -> None:
        if len(node.children) != 2:
            return
        left, right = node.children
        left_int = self._int_literal_value(left)
        right_int = self._int_literal_value(right)

        if left_int is not None and right_int is not None:
            self._rewrite_to_literal(node, NT.INTEGER, left_int - right_int)
            return

        if right_int == 0 and isinstance(left, Node):
            self._rewrite_to(node, left)
            return

        left_local = self._subject_local_index(left)
        right_local = self._subject_local_index(right)
        if left_local is not None and left_local == right_local:
            self._rewrite_to_literal(node, NT.INTEGER, 0)
            return

        if (
            isinstance(left, Node)
            and left.type in self._ADD_OPS
            and len(left.children) == 2
            and right_int is not None
        ):
            nested_left, nested_right = left.children
            nested_left_int = self._int_literal_value(nested_left)
            nested_right_int = self._int_literal_value(nested_right)
            if nested_right_int is not None and nested_right_int == right_int and isinstance(nested_left, Node):
                self._rewrite_to(node, nested_left)
                return
            if nested_left_int is not None and nested_left_int == right_int and isinstance(nested_right, Node):
                self._rewrite_to(node, nested_right)

    def _fold_multiply(self, node: Node) -> None:
        if len(node.children) != 2:
            return
        left, right = node.children
        left_int = self._int_literal_value(left)
        right_int = self._int_literal_value(right)

        if left_int is not None and right_int is not None:
            self._rewrite_to_literal(node, NT.INTEGER, left_int * right_int)
            return

        if right_int == 1 and isinstance(left, Node):
            self._rewrite_to(node, left)
            return
        if left_int == 1 and isinstance(right, Node):
            self._rewrite_to(node, right)
            return
        if right_int == 0 or left_int == 0:
            self._rewrite_to_literal(node, NT.INTEGER, 0)

    def _fold_not(self, node: Node) -> None:
        if len(node.children) != 1:
            return
        child = node.children[0]

        if isinstance(child, Node) and child.type == NT.TRUE:
            self._rewrite_to_leaf(node, NT.FALSE)
            return
        if isinstance(child, Node) and child.type == NT.FALSE:
            self._rewrite_to_leaf(node, NT.TRUE)
            return
        if isinstance(child, Node) and child.type == "!" and len(child.children) == 1:
            node.update(node_type=NT.COERCE_B, children=[child.children[0]])
            node.metadata = {}

    def _fold_equals(self, node: Node) -> None:
        if len(node.children) != 2:
            return
        left, right = node.children

        if isinstance(left, Node) and left.type in {NT.TRUE, NT.FALSE} and isinstance(right, Node) and right.type in {NT.TRUE, NT.FALSE}:
            truth = left.type == right.type
            self._rewrite_to_leaf(node, NT.TRUE if truth else NT.FALSE)
            return

        if isinstance(right, Node) and right.type == NT.TRUE:
            node.update(node_type=NT.COERCE_B, children=[left])
            node.metadata = {}
            return
        if isinstance(left, Node) and left.type == NT.TRUE:
            node.update(node_type=NT.COERCE_B, children=[right])
            node.metadata = {}
            return

        if isinstance(right, Node) and right.type == NT.FALSE:
            node.update(node_type="!", children=[left])
            node.metadata = {}
            return
        if isinstance(left, Node) and left.type == NT.FALSE:
            node.update(node_type="!", children=[right])
            node.metadata = {}

    def _fold_not_equals(self, node: Node) -> None:
        if len(node.children) != 2:
            return
        left, right = node.children

        if isinstance(left, Node) and left.type in {NT.TRUE, NT.FALSE} and isinstance(right, Node) and right.type in {NT.TRUE, NT.FALSE}:
            truth = left.type != right.type
            self._rewrite_to_leaf(node, NT.TRUE if truth else NT.FALSE)
            return

        if isinstance(right, Node) and right.type == NT.TRUE:
            node.update(node_type="!", children=[left])
            node.metadata = {}
            return
        if isinstance(left, Node) and left.type == NT.TRUE:
            node.update(node_type="!", children=[right])
            node.metadata = {}
            return

        if isinstance(right, Node) and right.type == NT.FALSE:
            node.update(node_type=NT.COERCE_B, children=[left])
            node.metadata = {}
            return
        if isinstance(left, Node) and left.type == NT.FALSE:
            node.update(node_type=NT.COERCE_B, children=[right])
            node.metadata = {}

    def _rewrite_increment_assignment(self, stmt: object) -> Node | None:
        if not isinstance(stmt, Node) or stmt.type != NT.SET_LOCAL or len(stmt.children) < 2:
            return None
        local_index = _index_value(stmt.children[0])
        rhs = _unwrap_convert_chain(stmt.children[1])
        if local_index is None or not isinstance(rhs, Node):
            return None
        if rhs.type in {NT.INCREMENT, NT.INCREMENT_I} and rhs.children and self._is_get_local_of(rhs.children[0], local_index):
            return Node(NT.POST_INCREMENT_LOCAL, [local_index], dict(stmt.metadata))
        if rhs.type in {NT.DECREMENT, NT.DECREMENT_I} and rhs.children and self._is_get_local_of(rhs.children[0], local_index):
            return Node(NT.POST_DECREMENT_LOCAL, [local_index], dict(stmt.metadata))
        if rhs.type in {NT.INC_LOCAL, NT.INC_LOCAL_I} and rhs.children and _index_value(rhs.children[0]) == local_index:
            return Node(NT.POST_INCREMENT_LOCAL, [local_index], dict(stmt.metadata))
        if rhs.type in {NT.DEC_LOCAL, NT.DEC_LOCAL_I} and rhs.children and _index_value(rhs.children[0]) == local_index:
            return Node(NT.POST_DECREMENT_LOCAL, [local_index], dict(stmt.metadata))
        if rhs.type not in {"+", "-", NT.ADD, "subtract"} or len(rhs.children) < 2:
            return None

        left = _unwrap_convert_chain(rhs.children[0])
        right = _unwrap_convert_chain(rhs.children[1])
        left_is_local = self._is_get_local_of(left, local_index)
        right_is_local = self._is_get_local_of(right, local_index)
        left_int = self._int_literal_value(left)
        right_int = self._int_literal_value(right)

        if rhs.type in {"+", NT.ADD}:
            if (left_is_local and right_int == 1) or (right_is_local and left_int == 1):
                return Node(NT.POST_INCREMENT_LOCAL, [local_index], dict(stmt.metadata))
            if (left_is_local and right_int == -1) or (right_is_local and left_int == -1):
                return Node(NT.POST_DECREMENT_LOCAL, [local_index], dict(stmt.metadata))
            return None

        # rhs.type in {"-", "subtract"}
        if left_is_local and right_int == 1:
            return Node(NT.POST_DECREMENT_LOCAL, [local_index], dict(stmt.metadata))
        if left_is_local and right_int == -1:
            return Node(NT.POST_INCREMENT_LOCAL, [local_index], dict(stmt.metadata))
        return None

    def _uses_local_before_redefinition(self, children: list[object], start_idx: int, local_index: int) -> bool:
        for idx in range(start_idx, len(children)):
            stmt = children[idx]
            if (
                isinstance(stmt, Node)
                and stmt.type == NT.SET_LOCAL
                and stmt.children
                and _index_value(stmt.children[0]) == local_index
            ):
                return False
            if self._count_local_mentions(stmt, local_index) > 0:
                return True
        return False

    def _inline_switch_temp(self, children: list[object], assign_idx: int, switch_idx: int) -> bool:
        assign_stmt = children[assign_idx]
        switch_stmt = children[switch_idx]
        if not isinstance(assign_stmt, Node) or assign_stmt.type != NT.SET_LOCAL or len(assign_stmt.children) < 2:
            return False
        if not isinstance(switch_stmt, Node) or switch_stmt.type != NT.SWITCH or not switch_stmt.children:
            return False

        local_index = _index_value(assign_stmt.children[0])
        if local_index is None:
            return False
        if self._count_local_mentions(assign_stmt, local_index) != 1:
            return False

        cond = switch_stmt.children[0]
        replaced_cond = self._replace_local_in_convert_chain(cond, local_index, assign_stmt.children[1])
        if replaced_cond is None:
            return False
        cond_mentions = self._count_local_mentions(cond, local_index)
        if cond_mentions != 1:
            return False
        if self._uses_local_before_redefinition(children, switch_idx + 1, local_index):
            return False

        switch_stmt.children[0] = replaced_cond
        del children[assign_idx]
        return True

    def _inline_assignment_temp(self, children: list[object], assign_idx: int, use_idx: int) -> bool:
        assign_stmt = children[assign_idx]
        use_stmt = children[use_idx]
        if not isinstance(assign_stmt, Node) or assign_stmt.type != NT.SET_LOCAL or len(assign_stmt.children) < 2:
            return False
        if not isinstance(use_stmt, Node) or use_stmt.type not in {NT.SET_PROPERTY, NT.INIT_PROPERTY, NT.SET_SUPER}:
            return False
        if not use_stmt.children:
            return False

        local_index = _index_value(assign_stmt.children[0])
        if local_index is None:
            return False
        if self._count_local_mentions(assign_stmt, local_index) != 1:
            return False

        value = use_stmt.children[-1]
        replaced_value = self._replace_local_in_convert_chain(value, local_index, assign_stmt.children[1])
        if replaced_value is None:
            return False

        value_mentions = self._count_local_mentions(value, local_index)
        if value_mentions != 1:
            return False
        if self._uses_local_before_redefinition(children, use_idx + 1, local_index):
            return False

        updated_children = list(use_stmt.children)
        updated_children[-1] = replaced_value
        children[use_idx] = Node(use_stmt.type, updated_children, dict(use_stmt.metadata))
        del children[assign_idx]
        return True

    @staticmethod
    def _nodes_equivalent(left: object, right: object) -> bool:
        if isinstance(left, Node) and isinstance(right, Node):
            if left.type != right.type or len(left.children) != len(right.children):
                return False
            return all(AstSemanticNormalizePass._nodes_equivalent(lc, rc) for lc, rc in zip(left.children, right.children))
        return left == right

    def _reuse_duplicate_construct_assignment(self, children: list[object], assign_idx: int, use_idx: int) -> bool:
        assign_stmt = children[assign_idx]
        use_stmt = children[use_idx]
        if not isinstance(assign_stmt, Node) or assign_stmt.type != NT.SET_LOCAL or len(assign_stmt.children) < 2:
            return False
        if not isinstance(use_stmt, Node) or use_stmt.type not in {NT.SET_PROPERTY, NT.INIT_PROPERTY, NT.SET_SUPER}:
            return False
        if len(use_stmt.children) < 3:
            return False

        local_index = _index_value(assign_stmt.children[0])
        if local_index is None:
            return False

        assign_value = _unwrap_convert_chain(assign_stmt.children[1])
        property_value = _unwrap_convert_chain(use_stmt.children[-1])
        if not isinstance(assign_value, Node) or not isinstance(property_value, Node):
            return False
        if assign_value.type != NT.CONSTRUCT or property_value.type != NT.CONSTRUCT:
            return False
        if not self._nodes_equivalent(assign_value, property_value):
            return False
        if self._count_local_mentions(use_stmt, local_index) != 0:
            return False

        updated_children = list(use_stmt.children)
        updated_children[-1] = Node(NT.GET_LOCAL, [local_index], {})
        children[use_idx] = Node(use_stmt.type, updated_children, dict(use_stmt.metadata))
        return True

    def _inline_type_local_assignment(self, children: list[object], assign_idx: int, use_idx: int) -> bool:
        """
        Inline one-step class/type temporary used by as_type_late/is_type_late.

        Pattern:
            set_local t, <type_expr>
            set_local v, as_type_late(<value>, get_local t)

        Rewrites into:
            set_local v, as_type_late(<value>, <type_expr>)
        """
        assign_stmt = children[assign_idx]
        use_stmt = children[use_idx]
        if not isinstance(assign_stmt, Node) or assign_stmt.type != NT.SET_LOCAL or len(assign_stmt.children) < 2:
            return False
        if not isinstance(use_stmt, Node) or use_stmt.type != NT.SET_LOCAL or len(use_stmt.children) < 2:
            return False

        local_index = _index_value(assign_stmt.children[0])
        if local_index is None:
            return False

        rhs = use_stmt.children[1]
        if not isinstance(rhs, Node) or rhs.type not in {NT.AS_TYPE, NT.AS_TYPE_LATE, NT.IS_TYPE, NT.IS_TYPE_LATE}:
            return False
        if len(rhs.children) < 2:
            return False

        type_expr = rhs.children[1]
        replaced_type = self._replace_local_in_convert_chain(type_expr, local_index, assign_stmt.children[1])
        if replaced_type is None:
            return False

        if self._count_local_mentions(type_expr, local_index) != 1:
            return False
        if self._uses_local_before_redefinition(children, use_idx + 1, local_index):
            return False

        updated_rhs_children = list(rhs.children)
        updated_rhs_children[1] = replaced_type
        updated_rhs = Node(rhs.type, updated_rhs_children, dict(rhs.metadata))

        updated_use_children = list(use_stmt.children)
        updated_use_children[1] = updated_rhs
        children[use_idx] = Node(use_stmt.type, updated_use_children, dict(use_stmt.metadata))
        del children[assign_idx]
        return True

    def _is_construct_instance_expr(self, value: object) -> bool:
        current = _unwrap_convert_chain(value)
        if not isinstance(current, Node):
            return False
        if current.type == NT.CONSTRUCT:
            return True
        if current.type in {NT.AS_TYPE, NT.AS_TYPE_LATE} and current.children:
            return self._is_construct_instance_expr(current.children[0])
        return False

    def _inline_construct_temp_new_assignment(self, children: list[object], assign_idx: int, use_idx: int) -> bool:
        """
        Collapse spurious two-step construct pattern:

            tmp = (<construct-like expr>);
            dst = new tmp();

        into:
            dst = (<construct-like expr>);
        """
        assign_stmt = children[assign_idx]
        use_stmt = children[use_idx]
        if not isinstance(assign_stmt, Node) or assign_stmt.type != NT.SET_LOCAL or len(assign_stmt.children) < 2:
            return False
        if not isinstance(use_stmt, Node) or use_stmt.type != NT.SET_LOCAL or len(use_stmt.children) < 2:
            return False

        local_index = _index_value(assign_stmt.children[0])
        if local_index is None:
            return False
        if self._count_local_mentions(assign_stmt, local_index) != 1:
            return False

        rhs = use_stmt.children[1]
        if not isinstance(rhs, Node) or rhs.type != NT.CONSTRUCT or len(rhs.children) != 1:
            return False
        if self._subject_local_index(rhs.children[0]) != local_index:
            return False
        if self._count_local_mentions(rhs, local_index) != 1:
            return False
        if not self._is_construct_instance_expr(assign_stmt.children[1]):
            return False
        if self._uses_local_before_redefinition(children, use_idx + 1, local_index):
            return False

        updated_use_children = list(use_stmt.children)
        updated_use_children[1] = self._clone_tree(assign_stmt.children[1])
        children[use_idx] = Node(use_stmt.type, updated_use_children, dict(use_stmt.metadata))
        del children[assign_idx]
        return True

    def _alias_rhs_value(self, value: object) -> Node | None:
        current = _unwrap_convert_chain(value)
        if not isinstance(current, Node) or current.type not in self._ALIASABLE_RHS_TYPES:
            return None
        if current.type == NT.GET_LOCAL and (not current.children or _index_value(current.children[0]) is None):
            return None
        return self._clone_tree(current)

    @staticmethod
    def _evict_alias_dependencies(aliases: dict[int, Node], local_index: int) -> None:
        aliases.pop(local_index, None)
        stale_targets = [
            target
            for target, rhs in aliases.items()
            if isinstance(rhs, Node)
            and rhs.type == NT.GET_LOCAL
            and rhs.children
            and _index_value(rhs.children[0]) == local_index
        ]
        for target in stale_targets:
            aliases.pop(target, None)

    def _replace_aliases_in_node(self, node: Node, aliases: dict[int, Node]) -> None:
        stack: list[Node] = [node]
        while stack:
            current = stack.pop()
            for idx, child in enumerate(current.children):
                if current.type in self._LOCAL_INDEXED_OPS and idx == 0:
                    continue
                if current.type in {NT.FOR_IN, NT.FOR_EACH_IN} and idx in {0, 2}:
                    continue
                if not isinstance(child, Node):
                    continue

                if child.type == NT.GET_LOCAL and child.children:
                    local_idx = _index_value(child.children[0])
                    if local_idx is not None:
                        replacement = aliases.get(local_idx)
                        if replacement is not None:
                            updated = self._clone_tree(replacement)
                            if isinstance(updated, Node):
                                current.children[idx] = updated
                                stack.append(updated)
                                continue

                stack.append(child)

    def _fold_redundant_locals(self, children: list[object]) -> None:
        aliases: dict[int, Node] = {}
        for stmt in children:
            if not isinstance(stmt, Node):
                continue

            self._replace_aliases_in_node(stmt, aliases)

            if stmt.type == NT.SET_LOCAL and len(stmt.children) >= 2:
                target = _index_value(stmt.children[0])
                if target is None:
                    continue

                rhs = _unwrap_convert_chain(stmt.children[1])
                if isinstance(rhs, Node) and rhs.type == NT.GET_LOCAL and rhs.children and _index_value(rhs.children[0]) == target:
                    stmt.update(node_type=NT.NOP, children=[])
                    stmt.metadata = {}
                    self._evict_alias_dependencies(aliases, target)
                    continue

                alias_rhs = self._alias_rhs_value(stmt.children[1])
                if alias_rhs is not None:
                    prev_alias = aliases.get(target)
                    if prev_alias is not None and self._nodes_equivalent(prev_alias, alias_rhs):
                        stmt.update(node_type=NT.NOP, children=[])
                        stmt.metadata = {}
                        continue

                if alias_rhs is None:
                    self._evict_alias_dependencies(aliases, target)
                else:
                    self._evict_alias_dependencies(aliases, target)
                    aliases[target] = alias_rhs
                continue

            if stmt.type in self._LOCAL_WRITE_OPS and stmt.children:
                target = _index_value(stmt.children[0])
                if target is not None:
                    self._evict_alias_dependencies(aliases, target)
                continue

            if stmt.type in {NT.FOR_IN, NT.FOR_EACH_IN}:
                if len(stmt.children) > 0:
                    target0 = _index_value(stmt.children[0])
                    if target0 is not None:
                        self._evict_alias_dependencies(aliases, target0)
                if len(stmt.children) > 2:
                    target2 = _index_value(stmt.children[2])
                    if target2 is not None:
                        self._evict_alias_dependencies(aliases, target2)

    def _propagate_alias_local_reads_and_fold(self, node: Node) -> None:
        i = 0
        while i < len(node.children):
            assign_stmt = node.children[i]
            if not isinstance(assign_stmt, Node) or assign_stmt.type != NT.SET_LOCAL or len(assign_stmt.children) < 2:
                i += 1
                continue

            source_local = _index_value(assign_stmt.children[0])
            if source_local is None:
                i += 1
                continue

            alias_idx = self._next_meaningful_stmt(node.children, i + 1)
            if alias_idx is None:
                i += 1
                continue

            alias_stmt = node.children[alias_idx]
            if not isinstance(alias_stmt, Node) or alias_stmt.type != NT.SET_LOCAL or len(alias_stmt.children) < 2:
                i += 1
                continue

            target_local = _index_value(alias_stmt.children[0])
            if target_local is None or target_local == source_local:
                i += 1
                continue

            if self._subject_local_index(alias_stmt.children[1]) != source_local:
                i += 1
                continue

            replacement_local = Node(NT.GET_LOCAL, [target_local], {})
            cursor = alias_idx + 1
            replaced_any = False
            while cursor < len(node.children):
                candidate = node.children[cursor]
                if self._is_local_write_stmt(candidate, source_local) or self._is_local_write_stmt(candidate, target_local):
                    break

                rewritten_candidate, replaced_count = self._replace_local_reads(candidate, source_local, replacement_local)
                if replaced_count > 0:
                    node.children[cursor] = rewritten_candidate
                    replaced_any = True
                cursor += 1

            # If there was no post-alias use rewritten, keep downstream passes unchanged.
            if not replaced_any:
                i += 1
                continue

            updated_alias_rhs = self._replace_local_in_convert_chain(
                alias_stmt.children[1],
                source_local,
                self._clone_tree(assign_stmt.children[1]),
            )
            if updated_alias_rhs is None:
                i += 1
                continue
            if self._count_local_mentions(alias_stmt.children[1], source_local) != 1:
                i += 1
                continue

            alias_children = list(alias_stmt.children)
            alias_children[1] = updated_alias_rhs
            node.children[alias_idx] = Node(NT.SET_LOCAL, alias_children, dict(alias_stmt.metadata))
            del node.children[i]
            if i > 0:
                i -= 1

    def _condition_child_index(self, stmt: Node) -> int | None:
        if stmt.type in {NT.IF, NT.WHILE, NT.SWITCH}:
            if stmt.children:
                return 0
            return None
        if stmt.type == NT.JUMP_IF:
            if len(stmt.children) >= 3 and isinstance(stmt.children[1], (int, str)):
                return 2
            if len(stmt.children) >= 2:
                return 1
        return None

    def _inline_throw_temp(self, children: list[object], assign_idx: int, throw_idx: int) -> bool:
        assign_stmt = children[assign_idx]
        throw_stmt = children[throw_idx]
        if not isinstance(assign_stmt, Node) or assign_stmt.type != NT.SET_LOCAL or len(assign_stmt.children) < 2:
            return False
        if not isinstance(throw_stmt, Node) or throw_stmt.type != NT.THROW or not throw_stmt.children:
            return False

        local_index = _index_value(assign_stmt.children[0])
        if local_index is None:
            return False
        if self._count_local_mentions(assign_stmt, local_index) != 1:
            return False

        throw_value = throw_stmt.children[0]
        replaced_throw = self._replace_local_in_convert_chain(throw_value, local_index, self._clone_tree(assign_stmt.children[1]))
        if replaced_throw is None:
            return False
        throw_mentions = self._count_local_mentions(throw_value, local_index)
        if throw_mentions != 1:
            return False
        if self._count_local_mentions(throw_stmt, local_index) != throw_mentions:
            return False

        updated_throw = list(throw_stmt.children)
        updated_throw[0] = replaced_throw
        children[throw_idx] = Node(NT.THROW, updated_throw, dict(throw_stmt.metadata))
        del children[assign_idx]
        return True

    def _inline_condition_temp(self, children: list[object], assign_idx: int, use_idx: int) -> bool:
        assign_stmt = children[assign_idx]
        use_stmt = children[use_idx]
        if not isinstance(assign_stmt, Node) or assign_stmt.type != NT.SET_LOCAL or len(assign_stmt.children) < 2:
            return False
        if not isinstance(use_stmt, Node):
            return False

        cond_idx = self._condition_child_index(use_stmt)
        if cond_idx is None or cond_idx >= len(use_stmt.children):
            return False

        local_index = _index_value(assign_stmt.children[0])
        if local_index is None:
            return False
        if self._count_local_mentions(assign_stmt, local_index) != 1:
            return False

        cond = use_stmt.children[cond_idx]
        replaced_cond = self._replace_local_in_convert_chain(cond, local_index, self._clone_tree(assign_stmt.children[1]))
        if replaced_cond is None:
            return False

        cond_mentions = self._count_local_mentions(cond, local_index)
        if cond_mentions != 1:
            return False
        # Safety: only rewrite when the temp is used solely as condition input.
        if self._count_local_mentions(use_stmt, local_index) != cond_mentions:
            return False
        if self._uses_local_before_redefinition(children, use_idx + 1, local_index):
            return False

        updated_children = list(use_stmt.children)
        updated_children[cond_idx] = replaced_cond
        children[use_idx] = Node(use_stmt.type, updated_children, dict(use_stmt.metadata))
        del children[assign_idx]
        return True

    def _inline_single_use_pair(self, children: list[object], assign_idx: int, use_idx: int) -> bool:
        """Inline one-step temporary locals using structural dispatch."""
        use_stmt = children[use_idx]
        if not isinstance(use_stmt, Node):
            return False

        match use_stmt.type:
            case NT.THROW:
                return self._inline_throw_temp(children, assign_idx, use_idx)
            case NT.IF | NT.WHILE | NT.JUMP_IF:
                return self._inline_condition_temp(children, assign_idx, use_idx)
            case NT.SWITCH:
                return self._inline_switch_temp(children, assign_idx, use_idx)
            case NT.SET_LOCAL:
                if self._inline_construct_temp_new_assignment(children, assign_idx, use_idx):
                    return True
                return self._inline_type_local_assignment(children, assign_idx, use_idx)
            case NT.SET_PROPERTY | NT.INIT_PROPERTY | NT.SET_SUPER:
                return self._inline_assignment_temp(children, assign_idx, use_idx)
            case _:
                return False

    def _inline_single_use_temps(self, node: Node) -> None:
        i = 0
        while i < len(node.children):
            assign = node.children[i]
            if not isinstance(assign, Node) or assign.type != NT.SET_LOCAL:
                i += 1
                continue

            next_idx = self._next_meaningful_stmt(node.children, i + 1)
            if next_idx is None:
                i += 1
                continue

            if self._inline_single_use_pair(node.children, i, next_idx):
                if i > 0:
                    i -= 1
                continue
            if self._reuse_duplicate_construct_assignment(node.children, i, next_idx):
                i += 1
                continue
            i += 1

    def _fold_increment_assignments(self, node: Node) -> None:
        for idx, stmt in enumerate(node.children):
            rewritten = self._rewrite_increment_assignment(stmt)
            if rewritten is not None:
                node.children[idx] = rewritten

    def _flatten_if_else_return_guards(self, node: Node) -> None:
        i = 0
        while i < len(node.children):
            stmt = node.children[i]
            if not isinstance(stmt, Node) or stmt.type != NT.IF or len(stmt.children) < 3:
                i += 1
                continue

            return_stmt = self._single_return_stmt(stmt.children[2])
            if return_stmt is None:
                i += 1
                continue

            condition = stmt.children[0]
            then_block = self._as_begin_block(stmt.children[1])

            guard_if = Node(
                NT.IF,
                [
                    self._negated_condition(condition),
                    Node(
                        NT.BEGIN,
                        [self._clone_tree(return_stmt)],
                    ),
                ],
                dict(stmt.metadata),
            )
            replacement = [guard_if, *then_block.children]
            node.children[i : i + 1] = replacement
            i += 1

    @staticmethod
    def _post_increment_local_index(stmt: object) -> int | None:
        if not isinstance(stmt, Node):
            return None
        if stmt.type != NT.POST_INCREMENT_LOCAL or not stmt.children:
            return None
        return _index_value(stmt.children[0])

    def _hoist_common_switch_post_increment_stmt(self, stmt: object) -> int | None:
        if not isinstance(stmt, Node) or stmt.type != NT.SWITCH or len(stmt.children) < 2:
            return None

        body = stmt.children[1]
        if not isinstance(body, Node) or body.type != NT.BEGIN:
            return None

        label_positions = [
            idx
            for idx, child in enumerate(body.children)
            if isinstance(child, Node) and child.type in {NT.CASE, NT.DEFAULT}
        ]
        if len(label_positions) < 2:
            return None

        break_sections = 0
        increment_local: int | None = None
        remove_positions: list[int] = []

        for idx, label_start in enumerate(label_positions):
            label_end = label_positions[idx + 1] if idx + 1 < len(label_positions) else len(body.children)
            section_items = body.children[label_start + 1 : label_end]
            meaningful: list[tuple[int, Node]] = []
            for rel_idx, item in enumerate(section_items):
                if isinstance(item, Node) and item.type not in {NT.NOP, NT.LABEL}:
                    meaningful.append((rel_idx, item))

            if not meaningful:
                continue

            last_rel, last_node = meaningful[-1]
            if last_node.type != NT.BREAK:
                continue

            break_sections += 1
            if len(meaningful) < 2:
                return None

            prev_rel, prev_node = meaningful[-2]
            local_idx = self._post_increment_local_index(prev_node)
            if local_idx is None:
                return None

            if increment_local is None:
                increment_local = local_idx
            elif increment_local != local_idx:
                return None

            remove_positions.append(label_start + 1 + prev_rel)

        if break_sections < 2 or increment_local is None:
            return None

        for pos in sorted(set(remove_positions), reverse=True):
            if 0 <= pos < len(body.children):
                del body.children[pos]

        return increment_local

    def _hoist_common_switch_post_increment_in_begin(self, node: Node) -> None:
        idx = 0
        while idx < len(node.children):
            local_idx = self._hoist_common_switch_post_increment_stmt(node.children[idx])
            if local_idx is None:
                idx += 1
                continue

            next_idx = self._next_meaningful_stmt(node.children, idx + 1)
            if next_idx is not None:
                existing_next = self._post_increment_local_index(node.children[next_idx])
                if existing_next == local_idx:
                    idx += 1
                    continue

            node.children.insert(idx + 1, Node(NT.POST_INCREMENT_LOCAL, [local_idx], {}))
            idx += 2

    def _collapse_empty_if_in_begin(self, node: Node) -> None:
        for idx, stmt in enumerate(node.children):
            if not isinstance(stmt, Node) or stmt.type != NT.IF or len(stmt.children) < 2:
                continue

            then_block = stmt.children[1]
            else_block = stmt.children[2] if len(stmt.children) > 2 else None
            if else_block is not None:
                continue
            if not self._is_effectively_empty_block(then_block):
                continue

            raw_cond = stmt.children[0] if stmt.children else Node(NT.TRUE)
            normalized_cond = self._strip_boolean_wrapper(raw_cond)
            # Conservative gate: only collapse known obfuscation-noise patterns
            # such as `if (a !== b) {}` / `if (a != b) {}`.
            if not isinstance(normalized_cond, Node) or normalized_cond.type not in self._NOT_EQUALS_OPS:
                continue

            node.children[idx] = normalized_cond

    def _on_add_like(self, node: Node) -> None:
        self._fold_add(node)

    def _on_subtract_like(self, node: Node) -> None:
        self._fold_subtract(node)

    def _on_multiply_like(self, node: Node) -> None:
        self._fold_multiply(node)

    def _on_not_like(self, node: Node) -> None:
        self._fold_not(node)

    def _on_equals_like(self, node: Node) -> None:
        self._fold_equals(node)

    def _on_not_equals_like(self, node: Node) -> None:
        self._fold_not_equals(node)

    on_add = _on_add_like
    on_subtract = _on_subtract_like
    on_multiply = _on_multiply_like
    locals()["on_+"] = _on_add_like
    locals()["on_-"] = _on_subtract_like
    locals()["on_*"] = _on_multiply_like
    locals()["on_!"] = _on_not_like
    locals()["on_=="] = _on_equals_like
    locals()["on_==="] = _on_equals_like
    locals()["on_!="] = _on_not_equals_like
    locals()["on_!=="] = _on_not_equals_like

    def on_if(self, node: Node) -> None:
        if not node.children:
            return

        node.children[0] = self._strip_boolean_wrapper(node.children[0])

        # Collapse else { if (...) { ... } } into else-if shape.
        if len(node.children) >= 3:
            match node.children[2]:
                case Node(NT.BEGIN, [Node(NT.IF, _, _) as nested_if], _):
                    node.children[2] = nested_if
                case _:
                    pass

        # Prefer positive comparison forms when both branches exist.
        # if (a != b) { A } else { B }  ->  if (a == b) { B } else { A }
        if len(node.children) >= 3 and isinstance(node.children[0], Node):
            cond = node.children[0]
            if cond.type in {"!=", "!=="}:
                inverted = self._invert_comparison(cond)
                if inverted is not None:
                    then_block = node.children[1]
                    else_block = node.children[2]
                    node.children[0] = inverted
                    node.children[1] = else_block
                    node.children[2] = then_block

    def on_while(self, node: Node) -> None:
        if node.children:
            node.children[0] = self._strip_boolean_wrapper(node.children[0])

    def on_switch(self, node: Node) -> None:
        if node.children:
            node.children[0] = self._strip_boolean_wrapper(node.children[0])
        # TODO: Continue migrating remaining source-level switch rewrites
        # from example.decompile_abc_to_as_files into semantic AST passes.

    def on_jump_if(self, node: Node) -> None:
        if len(node.children) >= 3 and isinstance(node.children[1], (int, str)):
            node.children[2] = self._strip_boolean_wrapper(node.children[2])
        elif len(node.children) >= 2:
            node.children[1] = self._strip_boolean_wrapper(node.children[1])

    def on_get_property(self, node: Node) -> None:
        if len(node.children) == 2 and self._is_find_property_of(node.children[0], node.children[1]):
            node.update(node_type=NT.GET_LEX, children=[node.children[1]])

    def on_construct(self, node: Node) -> None:
        if len(node.children) != 1:
            return
        callee = _unwrap_convert_chain(node.children[0])
        if not isinstance(callee, Node):
            return

        if callee.type == NT.CONSTRUCT:
            node.update(
                node_type=NT.CONSTRUCT,
                children=[self._clone_tree(child) for child in callee.children],
            )
            return

        if callee.type in {NT.AS_TYPE, NT.AS_TYPE_LATE} and callee.children:
            inner = _unwrap_convert_chain(callee.children[0])
            if isinstance(inner, Node) and inner.type == NT.CONSTRUCT:
                node.update(
                    node_type=callee.type,
                    children=[self._clone_tree(child) for child in callee.children],
                )

    def on_construct_property(self, node: Node) -> None:
        if len(node.children) < 2:
            return
        if self._is_find_property_of(node.children[0], node.children[1]):
            ctor = Node(NT.GET_LEX, [node.children[1]])
            args = list(node.children[2:])
            node.update(node_type=NT.CONSTRUCT, children=[ctor, *args])

    def on_set_property(self, node: Node) -> None:
        if len(node.children) == 3 and self._is_find_property_of(node.children[0], node.children[1]):
            node.children[0] = Node(NT.GET_LEX, [node.children[1]])

    on_init_property = on_set_property

    def _fallback_slot_name(self, slot_id: int) -> str:
        return f"var_slot{slot_id}"

    def _resolve_slot_subject_name(self, slot_id: int, scope_expr: object) -> tuple[Node | None, str | None]:
        scope_value = _unwrap_convert_chain(scope_expr)
        if isinstance(scope_value, Node) and scope_value.type == NT.GET_GLOBAL_SCOPE:
            mapped = self._global_slot_name_map.get(slot_id)
            if mapped:
                return Node(NT.GET_GLOBAL_SCOPE, []), mapped
            return None, None
        if self._subject_local_index(scope_expr) == 0:
            mapped = self._slot_name_map.get(slot_id)
            if mapped:
                return Node(NT.GET_LOCAL, [0]), mapped
            return None, None
        if isinstance(scope_value, Node) and scope_value.type == NT.GET_SCOPE_OBJECT:
            return Node(NT.GET_SCOPE_OBJECT, list(scope_value.children)), self._slot_name_map.get(slot_id, self._fallback_slot_name(slot_id))
        return None, None

    def on_get_slot(self, node: Node) -> None:
        if len(node.children) < 2:
            return
        slot_id = _index_value(node.children[0])
        if slot_id is None:
            return
        subject_node, slot_name = self._resolve_slot_subject_name(slot_id, node.children[1])
        if slot_name is None or subject_node is None:
            return
        node.update(
            node_type=NT.GET_PROPERTY,
            children=[subject_node, slot_name],
        )

    def on_set_slot(self, node: Node) -> None:
        if len(node.children) < 3:
            return
        slot_id = _index_value(node.children[0])
        if slot_id is None:
            return
        subject_node, slot_name = self._resolve_slot_subject_name(slot_id, node.children[1])
        if slot_name is None or subject_node is None:
            return
        node.update(
            node_type=NT.SET_PROPERTY,
            children=[subject_node, slot_name, node.children[2]],
        )

    def on_begin(self, node: Node) -> None:
        # Cross-statement literal reconstruction
        i = 0
        while i < len(node.children):
            reconstructed = self._reconstruct_array_literal(node.children, i)
            if reconstructed is None:
                reconstructed = self._reconstruct_object_literal(node.children, i)

            if reconstructed is None:
                i += 1
                continue

            replacement, removable_indexes = reconstructed
            node.children[i] = replacement
            if removable_indexes:
                for idx in sorted(set(removable_indexes), reverse=True):
                    if idx <= i or idx >= len(node.children):
                        continue
                    del node.children[idx]
            i += 1

        # Peephole: block-local alias/constant propagation for local temporaries.
        self._fold_redundant_locals(node.children)
        # Propagate Dup-style alias locals to canonical destination locals,
        # then fold redundant source temp assignments.
        self._propagate_alias_local_reads_and_fold(node)
        # Single-use temp locals can be safely inlined in narrow adjacent patterns.
        self._inline_single_use_temps(node)
        # Canonicalize `localX = (localX +/- 1)` into explicit inc/dec local nodes.
        self._fold_increment_assignments(node)
        # Hoist identical trailing `localX++` from switch branches.
        self._hoist_common_switch_post_increment_in_begin(node)
        # Prefer guard-return control flow over nested `if (...) { ... } else { return ... }`.
        self._flatten_if_else_return_guards(node)
        # Collapse no-op conditional shells: `if (cond) {}` -> `cond;`
        # to avoid synthetic empty-branch noise while preserving condition evaluation.
        self._collapse_empty_if_in_begin(node)


class AstConstructorCleanupPass(Transform):
    """Extract constructor field initializers into a synthetic metadata node."""

    _FIELD_ASSIGNMENT_MATCHER = m.one_of(
        m.of(NT.SET_PROPERTY, m.capture("subject"), m.capture("name"), m.capture("value")),
        m.of(NT.INIT_PROPERTY, m.capture("subject"), m.capture("name"), m.capture("value")),
    )

    def __init__(
        self,
        *,
        owner_kind: str | None = None,
        owner_name: str | None = None,
        method_name: str | None = None,
    ) -> None:
        self.owner_kind = owner_kind
        self.owner_name = owner_name
        self.method_name = method_name

    def transform(self, *args: Any) -> Any:
        if not args:
            return args
        root = args[0]
        if not isinstance(root, Node):
            return args
        if root.type != NT.BEGIN:
            return args if len(args) > 1 else root

        if not self._is_constructor_method():
            return args if len(args) > 1 else root

        self._extract_field_initializers(root)
        if len(args) == 1:
            return root
        return (root, *args[1:])

    def _is_constructor_method(self) -> bool:
        if self.owner_kind != "instance":
            return False
        if not self.owner_name or not self.method_name:
            return False
        return self.method_name == self.owner_name

    def _is_simple_value(self, value: object) -> bool:
        if isinstance(value, (int, float, str, bool)) or value is None:
            return True
        if not isinstance(value, Node):
            return False
        if value.type in {NT.COERCE, NT.CONVERT} and len(value.children) >= 2:
            return self._is_simple_value(value.children[-1])
        if value.type in {
            NT.INTEGER,
            NT.UNSIGNED,
            "double",
            NT.STRING,
            "true",
            "false",
            "null",
            "undefined",
            "nan",
            NT.NEW_ARRAY,
            NT.NEW_OBJECT,
            NT.GET_LEX,
        }:
            return True
        if value.type == NT.CONSTRUCT and value.children:
            ctor = _unwrap_convert_chain(value.children[0])
            return isinstance(ctor, Node) and ctor.type == NT.GET_LEX
        return False

    def _field_assignment(self, stmt: object) -> tuple[object, object] | None:
        captures: dict[str, object] = {}
        if not self._FIELD_ASSIGNMENT_MATCHER.match(stmt, captures):
            return None

        subject = _unwrap_convert_chain(captures.get("subject"))
        if not (isinstance(subject, Node) and subject.type == NT.GET_LOCAL and subject.children):
            return None
        if _index_value(subject.children[0]) != 0:
            return None
        name = captures["name"]
        value = captures["value"]
        if not self._is_simple_value(value):
            return None
        return name, value

    @staticmethod
    def _is_ignorable_constructor_stmt(value: object) -> bool:
        return isinstance(value, Node) and value.type in {NT.NOP, NT.LABEL, NT.PUSH_SCOPE, NT.POP_SCOPE}

    def _collect_field_initializer_range(
        self,
        children: list[object],
        *,
        start: int,
        stop: int,
    ) -> tuple[list[int], list[Node]]:
        removable_indices: list[int] = []
        extracted: list[Node] = []
        idx = start
        while idx < stop:
            stmt = children[idx]
            matched = self._field_assignment(stmt)
            if matched is not None:
                name, value = matched
                extracted.append(Node(NT.FIELD_INITIALIZER, [name, value]))
                removable_indices.append(idx)
                idx += 1
                continue
            if self._is_ignorable_constructor_stmt(stmt):
                idx += 1
                continue
            break
        return removable_indices, extracted

    def _extract_field_initializers(self, root: Node) -> None:
        super_index = -1
        for idx, child in enumerate(root.children):
            if isinstance(child, Node) and child.type == NT.CONSTRUCT_SUPER:
                super_index = idx
                break
        if super_index < 0:
            return

        pre_removals, pre_extracted = self._collect_field_initializer_range(
            root.children,
            start=0,
            stop=super_index,
        )
        post_removals, post_extracted = self._collect_field_initializer_range(
            root.children,
            start=super_index + 1,
            stop=len(root.children),
        )

        removable_indices = sorted(set(pre_removals + post_removals))
        extracted = pre_extracted + post_extracted
        if not extracted:
            return

        for idx in reversed(removable_indices):
            del root.children[idx]

        root.children.insert(
            0,
            Node(
                NT.FIELD_INITIALIZERS,
                extracted,
                {"owner": self.owner_name or ""},
            ),
        )
