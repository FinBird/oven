# Optimized semantic passes for AVM2 decompilation.
# Performance: keep transformations in a unified visitor pipeline to reduce repeated AST traversals.
from __future__ import annotations

import json
import re
import sys
from typing import Any, Iterator, cast

from oven.core.ast import Node, NodeVisitor, m

# Cache for pool auto-import index to avoid rebuilding for each method
_pool_auto_import_cache: dict[int, dict[str, tuple[str, ...]]] = {}
from oven.core.pipeline import Transform

from .node_types import AS3NodeTypes as NT
from oven.avm2.file import ABCFile
from oven.avm2.enums import TraitKind


def _index_value(value: object) -> int | None:
    if isinstance(value, int):
        return value
    idx = getattr(value, "value", None)
    if isinstance(idx, int):
        return idx
    if isinstance(value, str) and value.isdigit():
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
    else:
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
        if (
            value.type in {NT.GET_LEX, NT.FIND_PROPERTY, NT.FIND_PROPERTY_STRICT}
            and value.children
        ):
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
        NT.COERCE_I,
        NT.COERCE_U,
        NT.COERCE_D,
        NT.COERCE_S,
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
    while (
        isinstance(current, Node)
        and current.type in _CONVERT_WRAPPER_TYPES
        and current.children
    ):
        current = current.children[-1]
    return current


class AstSemanticNormalizePass(Transform[Any, Any], NodeVisitor):
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
        self._global_slot_name_map = (
            _normalize(global_slot_name_map)
            if global_slot_name_map is not None
            else dict(self._slot_name_map)
        )
        self._assume_normalized = bool(assume_normalized)

    def visit(self, node: Node) -> Node:
        # Preserve the hot-path visitor cache behavior from NodeVisitor.
        method = getattr(self, f"visit_{node.type}", None)
        if method is not None:
            return cast("Node", method(node))
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

    def visit_begin(self, node: Node) -> Node:
        self._fold_redundant_locals(node.children)
        self._propagate_alias_local_reads_and_fold(node)
        self._inline_single_use_temps(node)
        self._fold_increment_assignments(node)
        self._flatten_if_else_return_guards(node)
        self._flatten_if_terminal_branches(node)
        self._fold_ternary_type_conversions(node)
        for child in node.children:
            if isinstance(child, Node):
                self.visit(child)
        return node

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
        raw_name: object = value.children[0]
        return _property_name(raw_name) == _property_name(name)

    def _is_get_local_of(self, value: object, index: int) -> bool:
        unwrapped = _unwrap_convert_chain(value)
        if (
            not isinstance(unwrapped, Node)
            or unwrapped.type != NT.GET_LOCAL
            or not unwrapped.children
        ):
            return False
        return _index_value(unwrapped.children[0]) == index

    def _subject_local_index(self, value: object) -> int | None:
        unwrapped = _unwrap_convert_chain(value)
        if (
            not isinstance(unwrapped, Node)
            or unwrapped.type != NT.GET_LOCAL
            or not unwrapped.children
        ):
            return None
        return _index_value(unwrapped.children[0])

    @staticmethod
    def _is_ignorable_literal_stmt(value: object) -> bool:
        return isinstance(value, Node) and value.type in {NT.NOP, NT.LABEL}

    def _alias_local_assignment(self, stmt: object, aliases: set[int]) -> int | None:
        if (
            not isinstance(stmt, Node)
            or stmt.type != NT.SET_LOCAL
            or len(stmt.children) < 2
        ):
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
        if (
            isinstance(value, Node)
            and value.type in {NT.INTEGER, NT.UNSIGNED}
            and value.children
        ):
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

    def _reconstruct_array_literal(
        self, children: list[object], start: int
    ) -> tuple[Node, list[int]] | None:
        stmt = children[start]
        if (
            not isinstance(stmt, Node)
            or stmt.type != NT.SET_LOCAL
            or len(stmt.children) < 2
        ):
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
            rebuilt = Node(
                NT.SET_LOCAL, [local_index, Node(NT.NEW_ARRAY, [])], dict(stmt.metadata)
            )
            return rebuilt, []

        # new Array(a, b, c) -> [a, b, c]
        if arity > 1:
            rebuilt = Node(
                NT.SET_LOCAL,
                [local_index, Node(NT.NEW_ARRAY, list(rhs.children[1:]))],
                dict(stmt.metadata),
            )
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

            if (
                not isinstance(candidate, Node)
                or candidate.type not in {NT.SET_PROPERTY, NT.INIT_PROPERTY}
                or len(candidate.children) != 3
            ):
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
                rebuilt = Node(
                    NT.SET_LOCAL,
                    [local_index, Node(NT.NEW_ARRAY, [])],
                    dict(stmt.metadata),
                )
                return rebuilt, []
            return None

        max_index = max(assignments)
        if sorted(assignments.keys()) != list(range(max_index + 1)):
            return None
        if declared_len is not None and declared_len != max_index + 1:
            return None

        values = [assignments[idx] for idx in range(max_index + 1)]
        rebuilt = Node(
            NT.SET_LOCAL, [local_index, Node(NT.NEW_ARRAY, values)], dict(stmt.metadata)
        )
        return rebuilt, removable_indexes

    def _reconstruct_object_literal(
        self, children: list[object], start: int
    ) -> tuple[Node, list[int]] | None:
        stmt = children[start]
        if (
            not isinstance(stmt, Node)
            or stmt.type != NT.SET_LOCAL
            or len(stmt.children) < 2
        ):
            return None
        local_index = _index_value(stmt.children[0])
        rhs = stmt.children[1]
        if (
            local_index is None
            or not isinstance(rhs, Node)
            or not self._object_construct(rhs)
        ):
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

            if (
                not isinstance(candidate, Node)
                or candidate.type not in {NT.SET_PROPERTY, NT.INIT_PROPERTY}
                or len(candidate.children) != 3
            ):
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
            rebuilt = Node(
                NT.SET_LOCAL,
                [local_index, Node(NT.NEW_OBJECT, [])],
                dict(stmt.metadata),
            )
            return rebuilt, []
        rebuilt = Node(
            NT.SET_LOCAL, [local_index, Node(NT.NEW_OBJECT, pairs)], dict(stmt.metadata)
        )
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
        local_indexed_ops = self._LOCAL_INDEXED_OPS
        for node in self._iter_nodes(value):
            if node.type in local_indexed_ops and node.children:
                idx = _index_value(node.children[0])
                if idx == local_index:
                    count += 1
            elif node.type in {NT.FOR_IN, NT.FOR_EACH_IN}:
                if (
                    len(node.children) > 0
                    and _index_value(node.children[0]) == local_index
                ):
                    count += 1
                if (
                    len(node.children) > 2
                    and _index_value(node.children[2]) == local_index
                ):
                    count += 1
        return count

    def _replace_local_reads_in_expr(
        self,
        value: object,
        local_index: int,
        replacement: object,
    ) -> object | None:
        """Replace all GET_LOCAL references to local_index with replacement in an expression."""
        if isinstance(value, Node):
            if value.type == NT.GET_LOCAL and value.children:
                if _index_value(value.children[0]) == local_index:
                    return replacement

            # Recursively replace in children
            updated_children = []
            for child in value.children:
                replaced_child = self._replace_local_reads_in_expr(
                    child, local_index, replacement
                )
                if replaced_child is None:
                    return None  # Cannot replace in this subtree
                updated_children.append(replaced_child)

            return Node(value.type, updated_children, dict(value.metadata))
        return value

    def _replace_local_in_convert_chain(
        self,
        value: object,
        local_index: int,
        replacement: object,
    ) -> object | None:
        if (
            isinstance(value, Node)
            and value.type in _CONVERT_WRAPPER_TYPES
            and value.children
        ):
            replaced_tail = self._replace_local_in_convert_chain(
                value.children[-1], local_index, replacement
            )
            if replaced_tail is None:
                return None
            updated_children = list(value.children)
            updated_children[-1] = replaced_tail
            return Node(value.type, updated_children, dict(value.metadata))

        if isinstance(value, Node) and value.type == NT.GET_LOCAL and value.children:
            if _index_value(value.children[0]) == local_index:
                return replacement
        return None

    def _replace_local_reads(
        self, value: object, local_index: int, replacement: Node
    ) -> tuple[object, int]:
        if not isinstance(value, Node):
            return value, 0

        if (
            value.type == NT.GET_LOCAL
            and value.children
            and _index_value(value.children[0]) == local_index
        ):
            return self._clone_tree(replacement), 1

        local_indexed_ops = self._LOCAL_INDEXED_OPS
        for_in_types = {NT.FOR_IN, NT.FOR_EACH_IN}
        replaced_count = 0
        updated_children: list[object] = []
        for idx, child in enumerate(value.children):
            # Local-indexed ops encode destination/source index in operand position 0.
            if value.type in local_indexed_ops and idx == 0:
                updated_children.append(child)
                continue
            # for-in forms store local indexes in slot positions, not expression reads.
            if value.type in for_in_types and idx in {0, 2}:
                updated_children.append(child)
                continue

            rewritten_child, child_count = self._replace_local_reads(
                child, local_index, replacement
            )
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
            if isinstance(child, Node) and child.type in {
                NT.RETURN_VALUE,
                NT.RETURN_VOID,
            }:
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
        if (
            isinstance(value, Node)
            and value.type in {NT.INTEGER, NT.UNSIGNED}
            and value.children
        ):
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
            self._rewrite_to_literal(
                node, NT.STRING, left.children[0] + right.children[0]
            )
            return

        if right_int == 0 and isinstance(left, Node):
            self._rewrite_to(node, left)
            return
        if left_int == 0 and isinstance(right, Node):
            self._rewrite_to(node, right)
            return

        match node.children:
            case [
                Node(node_type, [x, Node(NT.INTEGER, [a], _)], _),
                Node(NT.INTEGER, [b], _),
            ] if (
                node_type in self._SUBTRACT_OPS
                and isinstance(a, int)
                and isinstance(b, int)
                and a == b
            ):
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
            if (
                nested_right_int is not None
                and nested_right_int == right_int
                and isinstance(nested_left, Node)
            ):
                self._rewrite_to(node, nested_left)
                return
            if (
                nested_left_int is not None
                and nested_left_int == right_int
                and isinstance(nested_right, Node)
            ):
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

        if (
            isinstance(left, Node)
            and left.type in {NT.TRUE, NT.FALSE}
            and isinstance(right, Node)
            and right.type in {NT.TRUE, NT.FALSE}
        ):
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

        if (
            isinstance(left, Node)
            and left.type in {NT.TRUE, NT.FALSE}
            and isinstance(right, Node)
            and right.type in {NT.TRUE, NT.FALSE}
        ):
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

    def _is_get_property_of(
        self, getter: object, subject: object, name: object
    ) -> bool:
        """Check if getter is get_property with matching subject and name."""
        if not isinstance(getter, Node) or getter.type != NT.GET_PROPERTY:
            return False
        if len(getter.children) < 2:
            return False
        getter_subject = getter.children[0]
        getter_name = getter.children[1]
        # Only match if subject is the same node type and matches directly
        # (avoid matching get_local which might alias to different things)
        if type(getter_subject) is not type(subject):
            return False
        return cast("bool", getter_subject == subject and getter_name == name)

    def _get_convert_type(self, node: Node) -> str | None:
        if node.type in _CONVERT_WRAPPER_TYPES:
            if node.type in {NT.COERCE, NT.CONVERT}:
                if len(node.children) >= 1:
                    type_hint = _normalize_type_hint(node.children[0])
                    return type_hint
            elif node.type == NT.COERCE_B:
                return "Boolean"
            elif node.type == NT.CONVERT_I:
                return "int"
            elif node.type == NT.CONVERT_U:
                return "uint"
            elif node.type == NT.CONVERT_D:
                return "Number"
            elif node.type == NT.CONVERT_S:
                return "String"
            elif node.type == NT.COERCE_I:
                return "int"
            elif node.type == NT.COERCE_U:
                return "uint"
            elif node.type == NT.COERCE_D:
                return "Number"
            elif node.type == NT.COERCE_S:
                return "String"
            elif node.type == NT.CONVERT_O:
                return "Object"
        return None

    def _get_convert_value(self, node: Node) -> object | None:
        if node.type in {NT.COERCE, NT.CONVERT}:
            if len(node.children) >= 2:
                return cast("object", node.children[1])
        elif node.type in _CONVERT_WRAPPER_TYPES:
            if len(node.children) >= 1:
                return cast("object", node.children[0])
        return None

    def _make_convert_node(self, type_str: str, value: Node) -> Node:
        if type_str == "Boolean":
            return Node(NT.COERCE_B, [value])
        elif type_str == "int":
            return Node(NT.COERCE_I, [value])
        elif type_str == "uint":
            return Node(NT.COERCE_U, [value])
        elif type_str == "Number":
            return Node(NT.COERCE_D, [value])
        elif type_str == "String":
            return Node(NT.COERCE_S, [value])
        else:
            return Node(NT.CONVERT, [type_str, value])

    def _fold_ternary_type_conversions(self, node: Node) -> None:
        """Fold redundant type conversions in ternary expressions."""
        for idx, child in enumerate(node.children):
            if not isinstance(child, Node):
                continue
            if child.type == NT.TERNARY and len(child.children) == 3:
                cond, then_expr, else_expr = child.children
                if isinstance(then_expr, Node) and isinstance(else_expr, Node):
                    then_type = self._get_convert_type(then_expr)
                    else_type = self._get_convert_type(else_expr)
                    if then_type and else_type and then_type == else_type:
                        then_value = self._get_convert_value(then_expr)
                        else_value = self._get_convert_value(else_expr)
                        if then_value is not None and else_value is not None:
                            inner_ternary = Node(
                                NT.TERNARY,
                                [cond, then_value, else_value],
                                dict(child.metadata),
                            )
                            new_ternary = self._make_convert_node(
                                then_type, inner_ternary
                            )
                            node.children[idx] = new_ternary
            self._fold_ternary_type_conversions(child)

    def _rewrite_increment_assignment(self, stmt: object) -> Node | None:
        if not isinstance(stmt, Node) or len(stmt.children) < 2:
            return None

        getter_checker = None
        target_args = None
        increment_type = None
        decrement_type = None
        local_index = None

        # Handle local variables
        if stmt.type == NT.SET_LOCAL:
            local_index = _index_value(stmt.children[0])
            rhs = _unwrap_convert_chain(stmt.children[1])
            if local_index is None or not isinstance(rhs, Node):
                return None
            getter_checker = lambda getter: self._is_get_local_of(getter, local_index)
            increment_type = (
                NT.PRE_INCREMENT_LOCAL
            )  # set_local(index, increment(get_local(index))) is pre-increment
            decrement_type = NT.PRE_DECREMENT_LOCAL
            target_args = [local_index]
        # Handle property assignments
        elif stmt.type == NT.SET_PROPERTY and len(stmt.children) >= 3:
            subject = stmt.children[0]
            name = stmt.children[1]
            rhs = _unwrap_convert_chain(stmt.children[2])
            if not isinstance(rhs, Node):
                return None
            getter_checker = lambda getter: self._is_get_property_of(
                getter, subject, name
            )
            increment_type = (
                NT.PRE_INCREMENT_PROPERTY
            )  # set_property(subject, name, increment(get_property(subject, name))) is pre-increment
            decrement_type = NT.PRE_DECREMENT_PROPERTY
            target_args = [subject, name]
        else:
            return None

        if (
            rhs.type in {NT.INCREMENT, NT.INCREMENT_I}
            and rhs.children
            and getter_checker(rhs.children[0])
        ):
            return Node(increment_type, target_args, dict(stmt.metadata))
        if (
            rhs.type in {NT.DECREMENT, NT.DECREMENT_I}
            and rhs.children
            and getter_checker(rhs.children[0])
        ):
            return Node(decrement_type, target_args, dict(stmt.metadata))
        if (
            stmt.type == NT.SET_LOCAL
            and rhs.type in {NT.INC_LOCAL, NT.INC_LOCAL_I}
            and rhs.children
            and _index_value(rhs.children[0]) == local_index
        ):
            return Node(NT.POST_INCREMENT_LOCAL, [local_index], dict(stmt.metadata))
        if (
            stmt.type == NT.SET_LOCAL
            and rhs.type in {NT.DEC_LOCAL, NT.DEC_LOCAL_I}
            and rhs.children
            and _index_value(rhs.children[0]) == local_index
        ):
            return Node(NT.POST_DECREMENT_LOCAL, [local_index], dict(stmt.metadata))
        if rhs.type not in {"+", "-", NT.ADD, "subtract"} or len(rhs.children) < 2:
            return None

        left = _unwrap_convert_chain(rhs.children[0])
        right = _unwrap_convert_chain(rhs.children[1])
        left_matches = getter_checker(left)
        right_matches = getter_checker(right)
        left_int = self._int_literal_value(left)
        right_int = self._int_literal_value(right)

        if rhs.type in {"+", NT.ADD}:
            if (left_matches and right_int == 1) or (right_matches and left_int == 1):
                return Node(increment_type, target_args, dict(stmt.metadata))
            if (left_matches and right_int == -1) or (right_matches and left_int == -1):
                return Node(decrement_type, target_args, dict(stmt.metadata))
            return None

        # rhs.type in {"-", "subtract"}
        if left_matches and right_int == 1:
            return Node(decrement_type, target_args, dict(stmt.metadata))
        if left_matches and right_int == -1:
            return Node(increment_type, target_args, dict(stmt.metadata))
        return None

        # Handle local variables
        if stmt.type == NT.SET_LOCAL:
            local_index = _index_value(stmt.children[0])
            rhs = _unwrap_convert_chain(stmt.children[1])
            if local_index is None or not isinstance(rhs, Node):
                return None
            getter_checker = lambda getter: self._is_get_local_of(getter, local_index)
            increment_type = NT.POST_INCREMENT_LOCAL
            decrement_type = NT.POST_DECREMENT_LOCAL
        # Handle property assignments
        elif stmt.type == NT.SET_PROPERTY and len(stmt.children) >= 3:
            subject = stmt.children[0]
            name = stmt.children[1]
            rhs = _unwrap_convert_chain(stmt.children[2])
            if not isinstance(rhs, Node):
                return None
            getter_checker = lambda getter: self._is_get_property_of(
                getter, subject, name
            )
            increment_type = (
                NT.PRE_INCREMENT_PROPERTY
            )  # set_property(subject, name, increment(get_property(subject, name))) is pre-increment
            decrement_type = NT.PRE_DECREMENT_PROPERTY
        else:
            return None

        if (
            rhs.type in {NT.INCREMENT, NT.INCREMENT_I}
            and rhs.children
            and getter_checker(rhs.children[0])
        ):
            return Node(
                increment_type,
                [subject, name] if stmt.type == NT.SET_PROPERTY else [local_index],
                dict(stmt.metadata),
            )
        if (
            rhs.type in {NT.DECREMENT, NT.DECREMENT_I}
            and rhs.children
            and getter_checker(rhs.children[0])
        ):
            return Node(
                decrement_type,
                [subject, name] if stmt.type == NT.SET_PROPERTY else [local_index],
                dict(stmt.metadata),
            )
        if (
            rhs.type in {NT.INC_LOCAL, NT.INC_LOCAL_I}
            and rhs.children
            and _index_value(rhs.children[0]) == local_index
        ):
            return Node(NT.POST_INCREMENT_LOCAL, [local_index], dict(stmt.metadata))
        if (
            rhs.type in {NT.DEC_LOCAL, NT.DEC_LOCAL_I}
            and rhs.children
            and _index_value(rhs.children[0]) == local_index
        ):
            return Node(NT.POST_DECREMENT_LOCAL, [local_index], dict(stmt.metadata))
        if rhs.type not in {"+", "-", NT.ADD, "subtract"} or len(rhs.children) < 2:
            return None

        left = _unwrap_convert_chain(rhs.children[0])
        right = _unwrap_convert_chain(rhs.children[1])
        left_matches = getter_checker(left)
        right_matches = getter_checker(right)
        left_int = self._int_literal_value(left)
        right_int = self._int_literal_value(right)

        if rhs.type in {"+", NT.ADD}:
            if (left_matches and right_int == 1) or (right_matches and left_int == 1):
                return Node(
                    increment_type,
                    [subject, name] if stmt.type == NT.SET_PROPERTY else [local_index],
                    dict(stmt.metadata),
                )
            if (left_matches and right_int == -1) or (right_matches and left_int == -1):
                return Node(
                    decrement_type,
                    [subject, name] if stmt.type == NT.SET_PROPERTY else [local_index],
                    dict(stmt.metadata),
                )
            return None

        # rhs.type in {"-", "subtract"}
        if left_matches and right_int == 1:
            return Node(
                decrement_type,
                [subject, name] if stmt.type == NT.SET_PROPERTY else [local_index],
                dict(stmt.metadata),
            )
        if left_matches and right_int == -1:
            return Node(
                increment_type,
                [subject, name] if stmt.type == NT.SET_PROPERTY else [local_index],
                dict(stmt.metadata),
            )
        return None

    def _uses_local_before_redefinition(
        self, children: list[object], start_idx: int, local_index: int
    ) -> bool:
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

    def _inline_switch_temp(
        self, children: list[object], assign_idx: int, switch_idx: int
    ) -> bool:
        assign_stmt = children[assign_idx]
        switch_stmt = children[switch_idx]
        if (
            not isinstance(assign_stmt, Node)
            or assign_stmt.type != NT.SET_LOCAL
            or len(assign_stmt.children) < 2
        ):
            return False
        if (
            not isinstance(switch_stmt, Node)
            or switch_stmt.type != NT.SWITCH
            or not switch_stmt.children
        ):
            return False

        local_index = _index_value(assign_stmt.children[0])
        if local_index is None:
            return False
        if self._count_local_mentions(assign_stmt, local_index) != 1:
            return False

        cond = switch_stmt.children[0]
        replaced_cond = self._replace_local_in_convert_chain(
            cond, local_index, assign_stmt.children[1]
        )
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

    def _inline_assignment_temp(
        self, children: list[object], assign_idx: int, use_idx: int
    ) -> bool:
        assign_stmt = children[assign_idx]
        use_stmt = children[use_idx]
        if (
            not isinstance(assign_stmt, Node)
            or assign_stmt.type != NT.SET_LOCAL
            or len(assign_stmt.children) < 2
        ):
            return False
        if not isinstance(use_stmt, Node) or use_stmt.type not in {
            NT.SET_PROPERTY,
            NT.INIT_PROPERTY,
            NT.SET_SUPER,
        }:
            return False
        if not use_stmt.children:
            return False

        local_index = _index_value(assign_stmt.children[0])
        if local_index is None:
            return False
        if self._count_local_mentions(assign_stmt, local_index) != 1:
            return False

        value = use_stmt.children[-1]
        replaced_value = self._replace_local_in_convert_chain(
            value, local_index, assign_stmt.children[1]
        )
        if replaced_value is None:
            return False

        value_mentions = self._count_local_mentions(value, local_index)
        if value_mentions != 1:
            return False
        if self._uses_local_before_redefinition(children, use_idx + 1, local_index):
            return False

        updated_children = list(use_stmt.children)
        updated_children[-1] = replaced_value
        children[use_idx] = Node(
            use_stmt.type, updated_children, dict(use_stmt.metadata)
        )
        del children[assign_idx]
        return True

    @staticmethod
    def _nodes_equivalent(left: object, right: object) -> bool:
        if isinstance(left, Node) and isinstance(right, Node):
            if left.type != right.type or len(left.children) != len(right.children):
                return False
            return all(
                AstSemanticNormalizePass._nodes_equivalent(lc, rc)
                for lc, rc in zip(left.children, right.children)
            )
        return left == right

    def _reuse_duplicate_construct_assignment(
        self, children: list[object], assign_idx: int, use_idx: int
    ) -> bool:
        assign_stmt = children[assign_idx]
        use_stmt = children[use_idx]
        if (
            not isinstance(assign_stmt, Node)
            or assign_stmt.type != NT.SET_LOCAL
            or len(assign_stmt.children) < 2
        ):
            return False
        if not isinstance(use_stmt, Node) or use_stmt.type not in {
            NT.SET_PROPERTY,
            NT.INIT_PROPERTY,
            NT.SET_SUPER,
        }:
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
        children[use_idx] = Node(
            use_stmt.type, updated_children, dict(use_stmt.metadata)
        )
        return True

    def _inline_type_local_assignment(
        self, children: list[object], assign_idx: int, use_idx: int
    ) -> bool:
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
        if (
            not isinstance(assign_stmt, Node)
            or assign_stmt.type != NT.SET_LOCAL
            or len(assign_stmt.children) < 2
        ):
            return False
        if (
            not isinstance(use_stmt, Node)
            or use_stmt.type != NT.SET_LOCAL
            or len(use_stmt.children) < 2
        ):
            return False

        local_index = _index_value(assign_stmt.children[0])
        if local_index is None:
            return False

        rhs = use_stmt.children[1]
        if not isinstance(rhs, Node) or rhs.type not in {
            NT.AS_TYPE,
            NT.AS_TYPE_LATE,
            NT.IS_TYPE,
            NT.IS_TYPE_LATE,
        }:
            return False
        if len(rhs.children) < 2:
            return False

        type_expr = rhs.children[1]
        replaced_type = self._replace_local_in_convert_chain(
            type_expr, local_index, assign_stmt.children[1]
        )
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
        children[use_idx] = Node(
            use_stmt.type, updated_use_children, dict(use_stmt.metadata)
        )
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

    def _inline_construct_temp_new_assignment(
        self, children: list[object], assign_idx: int, use_idx: int
    ) -> bool:
        """
        Collapse spurious two-step construct pattern:

            tmp = (<construct-like expr>);
            dst = new tmp();

        into:
            dst = (<construct-like expr>);
        """
        assign_stmt = children[assign_idx]
        use_stmt = children[use_idx]
        if (
            not isinstance(assign_stmt, Node)
            or assign_stmt.type != NT.SET_LOCAL
            or len(assign_stmt.children) < 2
        ):
            return False
        if (
            not isinstance(use_stmt, Node)
            or use_stmt.type != NT.SET_LOCAL
            or len(use_stmt.children) < 2
        ):
            return False

        local_index = _index_value(assign_stmt.children[0])
        if local_index is None:
            return False
        if self._count_local_mentions(assign_stmt, local_index) != 1:
            return False

        rhs = use_stmt.children[1]
        if (
            not isinstance(rhs, Node)
            or rhs.type != NT.CONSTRUCT
            or len(rhs.children) != 1
        ):
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
        children[use_idx] = Node(
            use_stmt.type, updated_use_children, dict(use_stmt.metadata)
        )
        del children[assign_idx]
        return True

    def _alias_rhs_value(self, value: object) -> Node | None:
        current = _unwrap_convert_chain(value)
        if (
            not isinstance(current, Node)
            or current.type not in self._ALIASABLE_RHS_TYPES
        ):
            return None
        if current.type == NT.GET_LOCAL and (
            not current.children or _index_value(current.children[0]) is None
        ):
            return None
        return cast(Node, self._clone_tree(current))

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
        local_indexed_ops = self._LOCAL_INDEXED_OPS
        for_in_types = {NT.FOR_IN, NT.FOR_EACH_IN}
        stack: list[Node] = [node]
        while stack:
            current = stack.pop()
            for idx, child in enumerate(current.children):
                if current.type in local_indexed_ops and idx == 0:
                    continue
                if current.type in for_in_types and idx in {0, 2}:
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
                if (
                    isinstance(rhs, Node)
                    and rhs.type == NT.GET_LOCAL
                    and rhs.children
                    and _index_value(rhs.children[0]) == target
                ):
                    stmt.update(node_type=NT.NOP, children=[])
                    stmt.metadata = {}
                    self._evict_alias_dependencies(aliases, target)
                    continue

                alias_rhs = self._alias_rhs_value(stmt.children[1])
                if alias_rhs is not None:
                    prev_alias = aliases.get(target)
                    if prev_alias is not None and self._nodes_equivalent(
                        prev_alias, alias_rhs
                    ):
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
            if (
                not isinstance(assign_stmt, Node)
                or assign_stmt.type != NT.SET_LOCAL
                or len(assign_stmt.children) < 2
            ):
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
            if (
                not isinstance(alias_stmt, Node)
                or alias_stmt.type != NT.SET_LOCAL
                or len(alias_stmt.children) < 2
            ):
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
                if self._is_local_write_stmt(
                    candidate, source_local
                ) or self._is_local_write_stmt(candidate, target_local):
                    break

                rewritten_candidate, replaced_count = self._replace_local_reads(
                    candidate, source_local, replacement_local
                )
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
            node.children[alias_idx] = Node(
                NT.SET_LOCAL, alias_children, dict(alias_stmt.metadata)
            )
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

    def _inline_throw_temp(
        self, children: list[object], assign_idx: int, throw_idx: int
    ) -> bool:
        assign_stmt = children[assign_idx]
        throw_stmt = children[throw_idx]
        if (
            not isinstance(assign_stmt, Node)
            or assign_stmt.type != NT.SET_LOCAL
            or len(assign_stmt.children) < 2
        ):
            return False
        if (
            not isinstance(throw_stmt, Node)
            or throw_stmt.type != NT.THROW
            or not throw_stmt.children
        ):
            return False

        local_index = _index_value(assign_stmt.children[0])
        if local_index is None:
            return False
        if self._count_local_mentions(assign_stmt, local_index) != 1:
            return False

        throw_value = throw_stmt.children[0]
        replaced_throw = self._replace_local_in_convert_chain(
            throw_value, local_index, self._clone_tree(assign_stmt.children[1])
        )
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

    def _inline_condition_temp(
        self, children: list[object], assign_idx: int, use_idx: int
    ) -> bool:
        assign_stmt = children[assign_idx]
        use_stmt = children[use_idx]
        if (
            not isinstance(assign_stmt, Node)
            or assign_stmt.type != NT.SET_LOCAL
            or len(assign_stmt.children) < 2
        ):
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
        replaced_cond = self._replace_local_reads_in_expr(
            cond, local_index, self._clone_tree(assign_stmt.children[1])
        )
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
        children[use_idx] = Node(
            use_stmt.type, updated_children, dict(use_stmt.metadata)
        )
        del children[assign_idx]
        return True

    def _inline_single_use_pair(
        self, children: list[object], assign_idx: int, use_idx: int
    ) -> bool:
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
                if self._inline_construct_temp_new_assignment(
                    children, assign_idx, use_idx
                ):
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
            if (
                not isinstance(stmt, Node)
                or stmt.type != NT.IF
                or len(stmt.children) < 3
            ):
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
    def _ends_with_terminal(node: object) -> bool:
        if isinstance(node, Node):
            if node.type in (NT.RETURN_VALUE, NT.RETURN_VOID, NT.THROW):
                return True
            if node.type == NT.BEGIN and node.children:
                return AstSemanticNormalizePass._ends_with_terminal(node.children[-1])
        return False

    def _flatten_if_terminal_branches(self, node: Node) -> None:
        if node.type != NT.BEGIN:
            return
        new_children = []
        for stmt in node.children:
            if (
                isinstance(stmt, Node)
                and stmt.type == NT.IF
                and len(stmt.children) == 3
            ):
                cond, then_block, else_block = stmt.children
                if self._ends_with_terminal(then_block):
                    new_children.append(
                        Node(NT.IF, [cond, then_block], dict(stmt.metadata))
                    )
                    if isinstance(else_block, Node) and else_block.type == NT.BEGIN:
                        new_children.extend(else_block.children)
                    else:
                        new_children.append(else_block)
                    continue
            new_children.append(stmt)
        node.children[:] = new_children

    @staticmethod
    def _post_increment_local_index(stmt: object) -> int | None:
        if not isinstance(stmt, Node):
            return None
        if stmt.type != NT.POST_INCREMENT_LOCAL or not stmt.children:
            return None
        return _index_value(stmt.children[0])

    def _hoist_common_switch_post_increment_stmt(self, stmt: object) -> int | None:
        if (
            not isinstance(stmt, Node)
            or stmt.type != NT.SWITCH
            or len(stmt.children) < 2
        ):
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
            label_end = (
                label_positions[idx + 1]
                if idx + 1 < len(label_positions)
                else len(body.children)
            )
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
            local_idx = self._hoist_common_switch_post_increment_stmt(
                node.children[idx]
            )
            if local_idx is None:
                idx += 1
                continue

            next_idx = self._next_meaningful_stmt(node.children, idx + 1)
            if next_idx is not None:
                existing_next = self._post_increment_local_index(
                    node.children[next_idx]
                )
                if existing_next == local_idx:
                    idx += 1
                    continue

            node.children.insert(
                idx + 1, Node(NT.POST_INCREMENT_LOCAL, [local_idx], {})
            )
            idx += 2

    def _collapse_empty_if_in_begin(self, node: Node) -> None:
        for idx, stmt in enumerate(node.children):
            if (
                not isinstance(stmt, Node)
                or stmt.type != NT.IF
                or len(stmt.children) < 2
            ):
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
            if (
                not isinstance(normalized_cond, Node)
                or normalized_cond.type not in self._NOT_EQUALS_OPS
            ):
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
        if len(node.children) == 2 and self._is_find_property_of(
            node.children[0], node.children[1]
        ):
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
        if len(node.children) == 3 and self._is_find_property_of(
            node.children[0], node.children[1]
        ):
            node.children[0] = Node(NT.GET_LEX, [node.children[1]])

    on_init_property = on_set_property

    def _fallback_slot_name(self, slot_id: int) -> str:
        return f"var_slot{slot_id}"

    def _resolve_slot_subject_name(
        self, slot_id: int, scope_expr: object
    ) -> tuple[Node | None, str | None]:
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
            return Node(
                NT.GET_SCOPE_OBJECT, list(scope_value.children)
            ), self._slot_name_map.get(slot_id, self._fallback_slot_name(slot_id))
        return None, None

    def on_get_slot(self, node: Node) -> None:
        if len(node.children) < 2:
            return
        slot_id = _index_value(node.children[0])
        if slot_id is None:
            return
        subject_node, slot_name = self._resolve_slot_subject_name(
            slot_id, node.children[1]
        )
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
        subject_node, slot_name = self._resolve_slot_subject_name(
            slot_id, node.children[1]
        )
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
        # Fold redundant type conversions in ternary expressions.
        self._fold_ternary_type_conversions(node)
        # Hoist identical trailing `localX++` from switch branches.
        self._hoist_common_switch_post_increment_in_begin(node)
        # Prefer guard-return control flow over nested `if (...) { ... } else { return ... }`.
        self._flatten_if_else_return_guards(node)
        # Collapse no-op conditional shells: `if (cond) {}` -> `cond;`
        # to avoid synthetic empty-branch noise while preserving condition evaluation.
        self._collapse_empty_if_in_begin(node)


class AstConstructorCleanupPass(Transform[Any, Any]):
    """Extract constructor field initializers into a synthetic metadata node."""

    _FIELD_ASSIGNMENT_MATCHER = m.one_of(
        m.of(
            NT.SET_PROPERTY, m.capture("subject"), m.capture("name"), m.capture("value")
        ),
        m.of(
            NT.INIT_PROPERTY,
            m.capture("subject"),
            m.capture("name"),
            m.capture("value"),
        ),
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
        if not (
            isinstance(subject, Node)
            and subject.type == NT.GET_LOCAL
            and subject.children
        ):
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
        return isinstance(value, Node) and value.type in {
            NT.NOP,
            NT.LABEL,
            NT.PUSH_SCOPE,
            NT.POP_SCOPE,
        }

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


class MoveStaticInitsToFieldsPass(Transform[Any, Any]):
    """Lift __static_init__ assignments into typed static member declarations."""

    _STATIC_FIELD_ASSIGNMENT_MATCHER = m.one_of(
        m.of(
            NT.SET_PROPERTY, m.capture("subject"), m.capture("name"), m.capture("value")
        ),
        m.of(
            NT.INIT_PROPERTY,
            m.capture("subject"),
            m.capture("name"),
            m.capture("value"),
        ),
    )

    def __init__(
        self,
        *,
        owner_name: str | None = None,
        method_name: str | None = None,
        class_traits: list[Any] | None = None,
        abc_obj: ABCFile | None = None,
        field_initializers: dict[str, str] | None = None,
    ) -> None:
        self.owner_name = owner_name
        self.method_name = method_name
        self.class_traits = class_traits or []
        self.class_trait_names = {
            _property_name(getattr(trait, "name", ""))
            for trait in self.class_traits
            if getattr(trait, "name", None) is not None
        }
        self.abc_obj = abc_obj
        self.field_initializers = field_initializers or {}

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
            NT.FIND_PROPERTY,
            NT.FIND_PROPERTY_STRICT,
        }:
            return True
        if value.type == NT.CONSTRUCT and value.children:
            ctor = _unwrap_convert_chain(value.children[0])
            return isinstance(ctor, Node) and ctor.type == NT.GET_LEX
        return False

    def _node_to_init_expr(self, value: Node) -> str | None:
        """Convert a simple value node to init expression string."""
        if value.type == NT.INTEGER:
            return str(value.children[0]) if value.children else None
        elif value.type == NT.UNSIGNED:
            return str(value.children[0]) if value.children else None
        elif value.type == "double":
            return str(value.children[0]) if value.children else None
        elif value.type == NT.STRING:
            return (
                json.dumps(value.children[0], ensure_ascii=False)
                if value.children
                else None
            )
        elif value.type == "true":
            return "true"
        elif value.type == "false":
            return "false"
        elif value.type == "null":
            return "null"
        elif value.type == "undefined":
            return "undefined"
        elif value.type == "nan":
            return "NaN"
        elif value.type == NT.NEW_ARRAY and value.children:
            # For [item]
            items = []
            for item in value.children:
                item_expr = (
                    self._node_to_init_expr(item)
                    if isinstance(item, Node)
                    else str(item)
                )
                if item_expr:
                    items.append(item_expr)
            return f"[{', '.join(items)}]"
        elif (
            value.type
            in {
                NT.GET_LEX,
                NT.FIND_PROPERTY,
                NT.FIND_PROPERTY_STRICT,
            }
            and value.children
        ):
            # For constants like T_SPIRIT_BAG_DATA
            raw_name = value.children[0]
            name = _property_name(raw_name)
            return name
        # Add more as needed
        return None

    def _subject_matches_static_field(self, subject: object, name: str) -> bool:
        if isinstance(subject, Node) and subject.children:
            if subject.type == NT.GET_LEX:
                get_lex_name: object = subject.children[0]
                subject_name = _property_name(get_lex_name)
                return subject_name in {self.owner_name, name}
            if subject.type in {NT.FIND_PROPERTY, NT.FIND_PROPERTY_STRICT}:
                find_property_name: object = subject.children[0]
                return _property_name(find_property_name) == name
            if subject.type == NT.STRING:
                string_value: object = subject.children[0]
                return string_value == self.owner_name
        if isinstance(subject, str):
            return _property_name(subject) == self.owner_name
        return False

    def _static_field_assignment(self, stmt: object) -> tuple[str, Node] | None:
        captures: dict[str, object] = {}
        if not self._STATIC_FIELD_ASSIGNMENT_MATCHER.match(stmt, captures):
            return None

        raw_name = captures["name"]
        name = _property_name(raw_name)
        if not name:
            return None
        if self.class_trait_names and name not in self.class_trait_names:
            return None

        subject = _unwrap_convert_chain(captures.get("subject"))
        if not self._subject_matches_static_field(subject, name):
            return None

        value = captures["value"]
        if not isinstance(value, Node):
            return None
        if not self._is_simple_value(value):
            return None
        # TODO: map name to trait for type inference
        return name, value

    def transform(self, *args: Any) -> Any:
        if not args:
            return args
        root = args[0]
        if not isinstance(root, Node):
            return args if len(args) > 1 else root
        if root.type != NT.BEGIN:
            return args if len(args) > 1 else root
        if self.method_name != "__static_init__":
            return args if len(args) > 1 else root
        if not self.class_traits or self.abc_obj is None:
            return args if len(args) > 1 else root

        self._extract_static_initializers(root)
        if len(args) == 1:
            return root
        return (root, *args[1:])

    def _is_ignorable_static_stmt(self, value: object) -> bool:
        return isinstance(value, Node) and value.type in {
            NT.NOP,
            NT.LABEL,
            NT.PUSH_SCOPE,
            NT.POP_SCOPE,
        }

    def _collect_static_initializer_range(
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
            matched = self._static_field_assignment(stmt)
            if matched is not None:
                name, value = matched
                extracted.append(Node(NT.FIELD_INITIALIZER, [name, value]))
                removable_indices.append(idx)
                idx += 1
                continue
            if self._is_ignorable_static_stmt(stmt):
                idx += 1
                continue
            break
        return removable_indices, extracted

    def _extract_static_initializers(self, root: Node) -> None:
        removable_indices, extracted = self._collect_static_initializer_range(
            root.children,
            start=0,
            stop=len(root.children),
        )
        if not extracted:
            return
        for idx in reversed(removable_indices):
            del root.children[idx]
        # Extract to field_initializers
        for init_node in extracted:
            if isinstance(init_node, Node) and len(init_node.children) >= 2:
                name = init_node.children[0]
                value = init_node.children[1]
                if isinstance(name, str):
                    expr = self._node_to_init_expr(value)
                    if expr is not None:
                        self.field_initializers[name] = expr
        root.children.insert(
            0,
            Node(
                NT.FIELD_INITIALIZERS,
                extracted,
                {"static": True, "owner": self.owner_name or ""},
            ),
        )


class NamespaceCleanupPass(Transform[Any, Any], NodeVisitor):
    """Strip namespace prefixes (PACKAGE_NAMESPACE:: etc.) from property names."""

    def __init__(self) -> None:
        super().__init__()

    def visit(self, node: Node) -> Node:
        # Process children first
        for i, child in enumerate(node.children):
            if isinstance(child, Node):
                node.children[i] = self.visit(child)
            elif isinstance(child, str) and "::" in child:
                # Strip namespace prefix using the same logic as _property_name
                node.children[i] = child.rsplit("::", 1)[-1]
        # Also process node's own metadata? Not needed.
        return node

    def transform(self, *args: Any) -> Any:
        if not args:
            return args
        root = args[0]
        if not isinstance(root, Node):
            return args
        self.visit(root)
        if len(args) == 1:
            return root
        return (root, *args[1:])


class ImportDiscoveryPass(Transform[Any, Any], NodeVisitor):
    """Collect type references (GET_LEX, CONSTRUCT, AS_TYPE, etc.) and map them to FQCN imports."""

    # Constants copied from decompile_to_as_files.py
    _ID_TOKEN_RE = re.compile(r"^[A-Za-z_$][0-9A-Za-z_$]*$")
    _ALLOWED_NAMESPACE_KINDS = {"PACKAGE_NAMESPACE", "PACKAGE_INTERNAL_NS"}
    _POOL_AUTO_IMPORT_INDEX_ATTR = "_auto_import_index_cache"

    # Built-in types that need imports (from JPEXS)
    _BUILT_IN_IMPORTS = {
        # Display
        "Sprite": "flash.display.Sprite",
        "MovieClip": "flash.display.MovieClip",
        "Shape": "flash.display.Shape",
        "Bitmap": "flash.display.Bitmap",
        "BitmapData": "flash.display.BitmapData",
        "DisplayObject": "flash.display.DisplayObject",
        "DisplayObjectContainer": "flash.display.DisplayObjectContainer",
        "InteractiveObject": "flash.display.InteractiveObject",
        "Stage": "flash.display.Stage",
        "Loader": "flash.display.Loader",
        "LoaderInfo": "flash.display.LoaderInfo",
        "Graphics": "flash.display.Graphics",
        "SimpleButton": "flash.display.SimpleButton",
        "FrameLabel": "flash.display.FrameLabel",
        "Scene": "flash.display.Scene",
        # Events
        "Event": "flash.events.Event",
        "EventDispatcher": "flash.events.EventDispatcher",
        "IEventDispatcher": "flash.events.IEventDispatcher",
        # System
        "IAngelSysAPI": "com.QQ.angel.api.IAngelSysAPI",
        "IHttpProxy": "com.QQ.angel.net.IHttpProxy",
        "IDataReceiver": "com.QQ.angel.net.IDataReceiver",
        "IDataProcessor": "com.QQ.angel.net.IDataProcessor",
        # Net
        "HttpRequest": "com.QQ.angel.net.HttpRequest",
        "URLLoader": "flash.net.URLLoader",
        "MouseEvent": "flash.events.MouseEvent",
        "KeyboardEvent": "flash.events.KeyboardEvent",
        "TimerEvent": "flash.events.TimerEvent",
        "ProgressEvent": "flash.events.ProgressEvent",
        "IOErrorEvent": "flash.events.IOErrorEvent",
        "SecurityErrorEvent": "flash.events.SecurityErrorEvent",
        "TextEvent": "flash.events.TextEvent",
        "FocusEvent": "flash.events.FocusEvent",
        "EventPhase": "flash.events.EventPhase",
        # Net
        "URLRequest": "flash.net.URLRequest",
        "URLLoader": "flash.net.URLLoader",
        "URLLoaderDataFormat": "flash.net.URLLoaderDataFormat",
        "URLVariables": "flash.net.URLVariables",
        "SendMathod": "flash.net.SendMethod",
        "FileReference": "flash.net.FileReference",
        "FileReferenceList": "flash.net.FileReferenceList",
        "Socket": "flash.net.Socket",
        "XMLSocket": "flash.net.XMLSocket",
        # Utils
        "Timer": "flash.utils.Timer",
        "ByteArray": "flash.utils.ByteArray",
        "Dictionary": "flash.utils.Dictionary",
        "IExternalizable": "flash.utils.IExternalizable",
        "Proxy": "flash.utils.Proxy",
        "Trace": "flash.utils.Trace",
        # System
        "ApplicationDomain": "flash.system.ApplicationDomain",
        "LoaderContext": "flash.system.LoaderContext",
        "SecurityDomain": "flash.system.SecurityDomain",
        "Security": "flash.system.Security",
        "Capabilities": "flash.system.Capabilities",
        # Text
        "TextField": "flash.text.TextField",
        "TextFormat": "flash.text.TextFormat",
        "TextFieldType": "flash.text.TextFieldType",
        "Font": "flash.text.Font",
        "StyleSheet": "flash.text.StyleSheet",
        # Geom
        "Point": "flash.geom.Point",
        "Rectangle": "flash.geom.Rectangle",
        "Matrix": "flash.geom.Matrix",
        "ColorTransform": "flash.geom.ColorTransform",
        "Transform": "flash.geom.Transform",
        # Media
        "Sound": "flash.media.Sound",
        "SoundChannel": "flash.media.SoundChannel",
        "SoundTransform": "flash.media.SoundTransform",
        "SoundLoaderContext": "flash.media.SoundLoaderContext",
        "Video": "flash.media.Video",
        "Camera": "flash.media.Camera",
        "Microphone": "flash.media.Microphone",
        # Filters
        "DropShadowFilter": "flash.filters.DropShadowFilter",
        "GlowFilter": "flash.filters.GlowFilter",
        "BlurFilter": "flash.filters.BlurFilter",
        "ColorMatrixFilter": "flash.filters.ColorMatrixFilter",
        "ConvolutionFilter": "flash.filters.ConvolutionFilter",
        "DisplacementMapFilter": "flash.filters.DisplacementMapFilter",
        "ShaderFilter": "flash.filters.ShaderFilter",
        "BevelFilter": "flash.filters.BevelFilter",
        # UI Components (common ones)
        "DisplayObjectContainer": "flash.display.DisplayObjectContainer",
        "InteractiveObject": "flash.display.InteractiveObject",
        "DisplayObject": "flash.display.DisplayObject",
        "StageAlign": "flash.display.StageAlign",
        "StageScaleMode": "flash.display.StageScaleMode",
        "StageQuality": "flash.display.StageQuality",
        "LoaderInfo": "flash.display.LoaderInfo",
    }

    def __init__(
        self,
        *,
        abc_obj: ABCFile | None = None,
        current_fqcn: str | None = None,
        method_context: Any | None = None,
        manual_import_mapping: dict[str, str] | None = None,
    ) -> None:
        super().__init__()
        self.abc_obj = abc_obj
        self.current_fqcn = current_fqcn
        self.method_context = method_context
        self._manual_import_mapping = manual_import_mapping or {}
        self._pool_index: dict[str, tuple[str, ...]] = {}
        if abc_obj is not None:
            pool_id = id(abc_obj.constant_pool)
            if pool_id not in _pool_auto_import_cache:
                _pool_auto_import_cache[pool_id] = self._build_pool_auto_import_index(
                    abc_obj.constant_pool
                )
            self._pool_index = _pool_auto_import_cache[pool_id]

    @classmethod
    def _build_pool_auto_import_index(cls, pool: object) -> dict[str, tuple[str, ...]]:
        """Adapted from decompile_to_as_files.py._build_pool_auto_import_index."""
        import re
        from oven.avm2.file import ABCFile

        multinames = getattr(pool, "multinames", None)
        if not isinstance(multinames, list):
            return {}

        resolve_index = getattr(pool, "resolve_index", None)
        if not callable(resolve_index):
            return {}

        by_name: dict[str, set[str]] = {}
        for multiname in multinames:
            data = getattr(multiname, "data", None)
            if not isinstance(data, dict):
                continue

            name_idx = _index_value(data.get("name"))
            ns_idx = _index_value(data.get("namespace"))
            if not isinstance(name_idx, int) or name_idx <= 0:
                continue
            if not isinstance(ns_idx, int) or ns_idx <= 0:
                continue

            try:
                member_name = str(resolve_index(name_idx, "string"))
                namespace_repr = str(resolve_index(ns_idx, "namespace"))
            except Exception:
                continue

            if (
                not cls._ID_TOKEN_RE.fullmatch(member_name)
                or member_name in ABCFile.AS3_KEYWORDS
            ):
                continue

            namespace_kind, sep, package_name = namespace_repr.partition("::")
            if not sep or namespace_kind not in cls._ALLOWED_NAMESPACE_KINDS:
                continue
            if (
                not package_name
                or package_name == "*"
                or package_name.startswith("http://")
            ):
                continue

            fqcn = f"{package_name}.{member_name}"
            bucket = by_name.get(member_name)
            if bucket is None:
                by_name[member_name] = {fqcn}
            else:
                bucket.add(fqcn)

        return {name: tuple(sorted(values)) for name, values in by_name.items()}

    def _add_import(self, simple_name: str) -> None:
        """Add FQCN import(s) for the given simple name."""
        if not simple_name or simple_name == "*":
            return

        # Handle generic types like "Vector.<String>" or "P_ReturnCode.<IExternalizable>"
        if ".<" in simple_name and simple_name.endswith(">"):
            # Extract base type and parameters
            base_end = simple_name.find(".<")
            base_name = simple_name[:base_end]
            param_part = simple_name[base_end + 2 : -1]  # Remove ".<" and ">"
            params = [p.strip() for p in param_part.split(",")]
            # Add import for base type
            self._add_simple_import(base_name)
            # Add imports for parameters
            for param in params:
                self._add_simple_import(param)
            return

        self._add_simple_import(simple_name)

    def _add_simple_import(self, simple_name: str) -> None:
        """Add FQCN import for a simple (non-generic) name."""
        if not simple_name or simple_name == "*":
            return
        if self.current_fqcn:
            # TODO: exclude self and same-package imports
            pass
        # Check manual mapping first
        if simple_name in self._manual_import_mapping:
            fqcn = self._manual_import_mapping[simple_name]
            if self.method_context is not None:
                self.method_context.discovered_imports.add(fqcn)
            return
        # Check built-in imports
        if simple_name in self._BUILT_IN_IMPORTS:
            fqcn = self._BUILT_IN_IMPORTS[simple_name]
            if self.method_context is not None:
                self.method_context.discovered_imports.add(fqcn)
            return
        # Check pool index
        candidates = self._pool_index.get(simple_name)
        if not candidates:
            return
        # For now, pick the first candidate. Heuristics may be needed.
        fqcn = candidates[0]
        if self.method_context is not None:
            # Add to discovered_imports set
            self.method_context.discovered_imports.add(fqcn)
        # TODO: store in a separate set if no context

    def visit(self, node: Node) -> Node:
        # Process children first
        for i, child in enumerate(node.children):
            if isinstance(child, Node):
                node.children[i] = self.visit(child)
        # Detect type references
        self._detect_type_references(node)
        return node

    def _detect_type_references(self, node: Node) -> None:
        """Examine node for type references and call _add_import."""
        # GET_LEX with a simple identifier (could be a class/interface)
        if node.type == NT.GET_LEX and node.children:
            raw_name = node.children[0]
            simple_name = _property_name(raw_name)
            if simple_name:
                self._add_import(simple_name)
        # CONSTRUCT with GET_LEX as first child
        elif node.type == NT.CONSTRUCT and node.children:
            ctor = node.children[0]
            if isinstance(ctor, Node) and ctor.type == NT.GET_LEX and ctor.children:
                raw_name = ctor.children[0]
                simple_name = _property_name(raw_name)
                if simple_name:
                    self._add_import(simple_name)
        # AS_TYPE, AS_TYPE_LATE, IS_TYPE, IS_TYPE_LATE with type child
        elif (
            node.type in {NT.AS_TYPE, NT.AS_TYPE_LATE, NT.IS_TYPE, NT.IS_TYPE_LATE}
            and len(node.children) >= 2
        ):
            type_expr = node.children[1]
            if (
                isinstance(type_expr, Node)
                and type_expr.type == NT.GET_LEX
                and type_expr.children
            ):
                raw_name = type_expr.children[0]
                simple_name = _property_name(raw_name)
                if simple_name:
                    self._add_import(simple_name)
        # COERCE, CONVERT with type hint child
        elif node.type in {NT.COERCE, NT.CONVERT} and len(node.children) >= 2:
            type_hint = node.children[0]
            normalized_type_name: str | None = _normalize_type_hint(type_hint)
            if normalized_type_name and normalized_type_name != "*":
                self._add_import(normalized_type_name)
        # CALL_PROPERTY, CALL_PROPERTY_LEX, CALL_PROPERTY_VOID for method calls that might need imports
        elif (
            node.type in {NT.CALL_PROPERTY, NT.CALL_PROPERTY_LEX, NT.CALL_PROPERTY_VOID}
            and len(node.children) >= 2
        ):
            # Check if subject is a GET_LEX (could be a static method call)
            subject = node.children[0]
            if (
                isinstance(subject, Node)
                and subject.type == NT.GET_LEX
                and subject.children
            ):
                raw_name = subject.children[0]
                simple_name = _property_name(raw_name)
                if simple_name:
                    self._add_import(simple_name)
        # FIND_PROPERTY, FIND_PROPERTY_STRICT for property access
        elif node.type in {NT.FIND_PROPERTY, NT.FIND_PROPERTY_STRICT} and node.children:
            raw_name = node.children[0]
            property_name = _property_name(raw_name)
            if property_name:
                self._add_import(property_name)
        # TODO: handle other patterns (extends/implements, static property owner)

    def transform(self, *args: Any) -> Any:
        if not args:
            return args
        root = args[0]
        if not isinstance(root, Node):
            return args
        self.visit(root)
        if len(args) == 1:
            return root
        return (root, *args[1:])


class TextCleanupPass(Transform[Any, Any], NodeVisitor):
    """Apply various AST-level cleanups that were previously regex-based post-processing."""

    # Matchers for numeric cast simplification
    _NUMERIC_CONVERT_MATCHER = m.one_of(
        m.of(NT.CONVERT_I, m.capture("inner")),
        m.of(NT.CONVERT_U, m.capture("inner")),
        m.of(NT.CONVERT_D, m.capture("inner")),
    )
    # Matcher for self-assignment: SET_LOCAL or SET_SLOT where left == right
    _SELF_ASSIGN_MATCHER = m.one_of(
        m.of(NT.SET_LOCAL, m.capture("index"), m.capture("value")),
        m.of(NT.SET_SLOT, m.capture("index"), m.capture("scope"), m.capture("value")),
    )
    # Matcher for property self-assignment: SET_PROPERTY where value is GET_PROPERTY with same subject and property
    _PROPERTY_SELF_ASSIGN_MATCHER = m.of(
        NT.SET_PROPERTY, m.capture("subject"), m.capture("prop"), m.capture("value")
    )
    # Matcher for redundant member access: SET_PROPERTY where prop name equals value identifier
    # TODO: implement after analyzing actual patterns
    _REDUNDANT_MEMBER_ACCESS_MATCHER = m.of(
        NT.SET_PROPERTY, m.capture("subject"), m.capture("prop"), m.capture("value")
    )

    DEBUG = False

    def __init__(self, *, enable_rules: dict[str, bool] | None = None) -> None:
        super().__init__()
        self.enable_rules = enable_rules or {}

    def visit(self, node: Node) -> Node:
        # Process children first (depth-first)
        for i, child in enumerate(node.children):
            if isinstance(child, Node):
                node.children[i] = self.visit(child)
        # Apply transformations that may replace the current node
        node = self._simplify_numeric_converts(node)
        node = self._remove_self_assignments(node)
        node = self._remove_property_self_assignments(node)
        node = self._simplify_numeric_wrappers(node)
        node = self._remove_as_type_late(node)
        node = self._remove_redundant_member_access(node)
        return node

    def _remove_redundant_member_access(self, node: Node) -> Node:
        """Simplify redundant member access like obj.prop = obj.prop; to obj.prop = prop;."""
        captures = self._REDUNDANT_MEMBER_ACCESS_MATCHER.match_root(node)
        if not captures:
            return node
        subject = captures["subject"]
        prop = captures["prop"]
        value = captures["value"]
        if isinstance(value, Node) and value.type == NT.GET_PROPERTY:
            if (
                len(value.children) >= 2
                and value.children[0] == subject
                and value.children[1] == prop
            ):
                # Replace the value with just the property name
                new_value = Node(NT.STRING, [str(prop)])
                return Node(NT.SET_PROPERTY, [subject, prop, new_value])
        return node

    def _simplify_numeric_converts(self, node: Node) -> Node:
        """Replace CONVERT_I/CONVERT_U/CONVERT_D with inner node if inner is numeric literal."""
        captures = self._NUMERIC_CONVERT_MATCHER.match_root(node)
        if not captures:
            return node
        inner = captures["inner"]
        if not isinstance(inner, Node):
            return node
        # Check if inner is a numeric literal
        if self._is_numeric_literal(inner):
            return inner
        # Also handle unary minus (negative numbers)
        if inner.type == NT.NEGATE and len(inner.children) == 1:
            child = inner.children[0]
            if isinstance(child, Node) and self._is_numeric_literal(child):
                return inner
        return node

    def _is_numeric_literal(self, node: Node) -> bool:
        """Return True if node is an integer, unsigned, or double literal."""
        return node.type in {NT.INTEGER, NT.UNSIGNED, NT.DOUBLE}

    def _remove_self_assignments(self, node: Node) -> Node:
        """Remove self-assignments like `x = x;`."""
        captures = self._SELF_ASSIGN_MATCHER.match_root(node)
        if not captures:
            return node
        import sys

        # For SET_LOCAL: index matches value? value must be GET_LOCAL with same index
        if node.type == NT.SET_LOCAL:
            index = captures["index"]
            value = captures["value"]
            if isinstance(value, Node) and value.type == NT.GET_LOCAL:
                if value.children and value.children[0] == index:
                    return Node(NT.NOP, [])
        # For SET_SLOT: index and scope match value's GET_SLOT
        elif node.type == NT.SET_SLOT:
            index = captures["index"]
            scope = captures["scope"]
            value = captures["value"]
            if isinstance(value, Node) and value.type == NT.GET_SLOT:
                if value.children[0] == index and (
                    len(value.children) > 1 and value.children[1] == scope
                ):
                    return Node(NT.NOP, [])
        return node

    def _remove_property_self_assignments(self, node: Node) -> Node:
        """Remove self-assignments like `obj.prop = obj.prop;`."""
        captures = self._PROPERTY_SELF_ASSIGN_MATCHER.match_root(node)
        if not captures:
            return node
        import sys

        subject = captures["subject"]
        prop = captures["prop"]
        value = captures["value"]
        if isinstance(value, Node) and value.type == NT.GET_PROPERTY:
            if (
                len(value.children) >= 2
                and value.children[0] == subject
                and value.children[1] == prop
            ):
                return Node(NT.NOP, [])
        return node

    def _simplify_numeric_wrappers(self, node: Node) -> Node:
        """Replace int(123) -> 123, uint(123) -> 123, Number(1.23) -> 1.23."""
        if node.type != NT.CALL:
            return node
        if len(node.children) != 2:  # function + single argument
            return node
        func, arg = node.children
        if not isinstance(func, Node) or func.type != NT.GET_LEX:
            return node
        if not func.children or not isinstance(func.children[0], str):
            return node
        func_name = func.children[0]
        if func_name not in {"int", "uint", "Number"}:
            return node
        if isinstance(arg, Node) and self._is_numeric_literal(arg):
            return arg
        # Also handle negated literal
        if isinstance(arg, Node) and arg.type == NT.NEGATE and len(arg.children) == 1:
            child = arg.children[0]
            if isinstance(child, Node) and self._is_numeric_literal(child):
                return arg
        return node

    def _remove_as_type_late(self, node: Node) -> Node:
        """Remove (/* as_type_late */ undefined); pattern."""
        if node.type != NT.AS_TYPE_LATE:
            return node
        # If it has a single child that is UNDEFINED, remove the node
        if (
            len(node.children) == 1
            and isinstance(node.children[0], Node)
            and node.children[0].type == NT.UNDEFINED
        ):
            return Node(NT.NOP, [])
        # Otherwise keep as is (maybe replace with child?)
        return node

    def transform(self, *args: Any) -> Any:
        if not args:
            return args
        root = args[0]
        if not isinstance(root, Node):
            return args
        self.visit(root)
        if len(args) == 1:
            return root
        return (root, *args[1:])
