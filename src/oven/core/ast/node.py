from __future__ import annotations

from collections import deque
from typing import (
    Any,
    Iterator,
    Protocol,
    Self,
    Sequence,
    TypeAlias,
    TypeVar,
    overload,
    runtime_checkable,
)
import sys


@runtime_checkable
@runtime_checkable
class SupportsToAstNode(Protocol):
    def to_ast_node(self) -> "Node": ...


T = TypeVar("T")
AstScalar: TypeAlias = str | int | float | bool | None
AstChild: TypeAlias = Any  # Recursive union with list causes invariance issues
AstChildren: TypeAlias = list[AstChild]


@overload
def to_ast_node(obj: SupportsToAstNode) -> "Node": ...


@overload
def to_ast_node(obj: T) -> T: ...


def to_ast_node(obj: SupportsToAstNode | T) -> "Node | T":
    """Helper to convert objects to AST Nodes if supported."""
    if type(obj) is Node:
        return obj
    if hasattr(obj, "to_ast_node"):
        return obj.to_ast_node()
    return obj


class Node:
    """Abstract Syntax Tree Node."""

    __slots__ = ("type", "children", "_metadata", "parent", "_index_hint")
    __match_args__ = ("type", "children", "metadata")

    _EMPTY_METADATA: dict[str, Any] = {}
    _LEAF_SINGLETON_TYPES: frozenset[str] = frozenset(
        {"true", "false", "null", "undefined", "nan"}
    )
    _LEAF_SINGLETONS: dict[str, "Node"] = {}

    def __init__(
        self,
        node_type: str,
        children: AstChildren | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        # Intern string for memory efficiency and faster comparison
        self.type: str = sys.intern(str(node_type))
        self.children: AstChildren = children or []
        # Always create a new dict to avoid shared mutable state
        self._metadata: dict[str, Any] = metadata if metadata is not None else {}
        self.parent: Node | None = None

        # Cache index in parent's list for O(1) lookups during replacement
        self._index_hint: int | None = None

        for idx, child in enumerate(self.children):
            if type(child) is Node:
                child.parent = self
                child._index_hint = idx

    @property
    def metadata(self) -> dict[str, Any]:
        """Get metadata dictionary."""
        return self._metadata

    @metadata.setter
    def metadata(self, value: dict[str, Any] | None) -> None:
        """Set metadata dictionary, converting None to empty dict."""
        self._metadata = value if value is not None else {}

    @classmethod
    def leaf(cls, node_type: str, *, metadata: dict[str, Any] | None = None) -> "Node":
        interned = sys.intern(str(node_type))
        if metadata:
            return cls(interned, [], metadata)
        cached = cls._LEAF_SINGLETONS.get(interned)
        if cached is not None:
            return cached
        if interned in cls._LEAF_SINGLETON_TYPES:
            node = cls(interned, [], None)
            cls._LEAF_SINGLETONS[interned] = node
            return node
        return cls(interned, [], None)

    def ensure_metadata(self) -> dict[str, Any]:
        if self.metadata is self._EMPTY_METADATA:
            self.metadata = {}
        return self.metadata

    def normalize_hierarchy(self) -> Self:
        """Recursively set parent pointers for all descendants."""
        stack: list[Node] = [self]
        while stack:
            node = stack.pop()
            for idx, child in enumerate(node.children):
                if type(child) is Node:
                    child.parent = node
                    child._index_hint = idx
                    stack.append(child)
        return self

    def descendants(self) -> Iterator[Node]:
        """Yield all descendant nodes using BFS."""
        queue: deque[Node] = deque()
        for child in self.children:
            if type(child) is Node:
                queue.append(child)

        while queue:
            node = queue.popleft()
            yield node
            for child in node.children:
                if type(child) is Node:
                    queue.append(child)

    def set_children(self, children: AstChildren) -> Self:
        """Unified method to modify children with efficient local hierarchy sync."""
        self.children = children
        for idx, child in enumerate(self.children):
            if type(child) is Node:
                child.parent = self
                child._index_hint = idx
        return self

    def replace_child(self, old_child: Node, new_child: Node) -> Self:
        """Replace a child node with another, O(1) hierarchy sync."""
        try:
            idx = self.children.index(old_child)
        except ValueError:
            raise ValueError("old_child not found in children")

        self.children[idx] = new_child
        if type(new_child) is Node:
            new_child.parent = self
            new_child._index_hint = idx

        old_child.parent = None
        old_child._index_hint = None
        return self

    def update(
        self,
        node_type: str | None = None,
        children: AstChildren | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Self:
        """Mutable update of the current node."""
        if node_type is not None:
            self.type = node_type
        if children is not None:
            self.set_children(children)
        if metadata:
            self.ensure_metadata().update(metadata)
        return self

    def updated(
        self,
        node_type: str | None = None,
        children: Sequence[AstChild] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Node:
        """Immutable update: returns a new Node instance (Copy-on-Write style)."""
        new_type = sys.intern(str(node_type)) if node_type is not None else self.type

        if new_type is self.type and children is None and metadata is None:
            return self

        new_children = list(children) if children is not None else self.children[:]
        new_metadata = self.metadata.copy()
        if metadata:
            new_metadata.update(metadata)

        return Node(new_type, new_children, new_metadata)

    def clone(self) -> Node:
        """Shallow copy of the node (copies list and dict containers)."""
        return Node(self.type, self.children[:], self.metadata.copy())

    @property
    def index_in_parent(self) -> int:
        """Return the index of this node in its parent's children list."""
        if self.parent is None:
            return -1
        parent_children = self.parent.children
        hint = self._index_hint
        if (
            hint is not None
            and hint < len(parent_children)
            and parent_children[hint] is self
        ):
            return hint
        try:
            idx = parent_children.index(self)
            self._index_hint = idx
            return idx
        except ValueError:
            return -1

    @property
    def next_sibling(self) -> Any | None:
        if self.parent is None:
            return None
        idx = self.index_in_parent
        if idx == -1 or idx >= len(self.parent.children) - 1:
            return None
        sibling = self.parent.children[idx + 1]
        return sibling if type(sibling) is Node else None

    @property
    def prev_sibling(self) -> Any | None:
        if self.parent is None:
            return None
        idx = self.index_in_parent
        if idx <= 0:
            return None
        sibling = self.parent.children[idx - 1]
        return sibling if type(sibling) is Node else None

    def is_equivalent(self, other: Any) -> bool:
        """Structural equality check (useful for testing)."""
        if self is other:
            return True
        if type(other) is not Node:
            return False
        if self.type != other.type:
            return False
        if self.metadata != other.metadata:
            return False
        if len(self.children) != len(other.children):
            return False

        for c1, c2 in zip(self.children, other.children):
            if type(c1) is Node and type(c2) is Node:
                if not c1.is_equivalent(c2):
                    return False
            elif c1 != c2:
                return False
        return True

    def replace_with(self, new_node: "Node") -> None:
        """Replace this node with a new node in the parent's children list."""
        if not self.parent:
            raise ValueError("Cannot replace root node without context")

        parent_children = self.parent.children

        # Use index hint optimization if valid
        if (
            self._index_hint is not None
            and self._index_hint < len(parent_children)
            and parent_children[self._index_hint] is self
        ):
            idx = self._index_hint
        else:
            try:
                idx = self.parent.children.index(self)
            except ValueError:
                return  # Node already removed

        parent_children[idx] = new_node

        if type(new_node) is Node:
            new_node.parent = self.parent
            new_node._index_hint = idx  # Inherit hint

        self.parent = None
        self._index_hint = None

    def replace_with_children(self) -> None:
        """Remove self and lift children into the parent's list."""
        if not self.parent:
            return
        idx = self.index_in_parent
        if idx == -1:
            return
        parent = self.parent

        parent.children.pop(idx)
        for i, child in enumerate(self.children):
            if type(child) is Node:
                child.parent = parent
                child._index_hint = idx + i
            parent.children.insert(idx + i, child)

        for new_idx in range(idx + len(self.children), len(parent.children)):
            sibling = parent.children[new_idx]
            if type(sibling) is Node:
                sibling._index_hint = new_idx

        self.parent = None
        self._index_hint = None

    def remove(self) -> None:
        """Remove this node from the AST."""
        if not self.parent:
            return
        idx = self.index_in_parent
        if idx == -1:
            return
        parent = self.parent
        parent.children.pop(idx)
        for new_idx in range(idx, len(parent.children)):
            sibling = parent.children[new_idx]
            if type(sibling) is Node:
                sibling._index_hint = new_idx
        self.parent = None
        self._index_hint = None

    def to_sexp(self, indent: int = 0) -> str:
        """Convert to S-Expression string representation."""
        spaces = "  " * indent
        label = self.metadata.get("label") or self.metadata.get("name")
        fancy_type = self.type.replace("_", "-")

        display_type = f"{label}:{fancy_type}" if label else fancy_type

        has_complex_child = False
        for child in self.children:
            if type(child) is Node:
                has_complex_child = True
                break
            if isinstance(child, list) and any(type(c) is Node for c in child):
                has_complex_child = True
                break

        parts = [f"{spaces}({display_type}"]
        val = self.metadata.get("val")

        if val is not None and not self.children:
            parts.append(f" {repr(val)}")
        else:
            for child in self.children:
                if has_complex_child:
                    if type(child) is Node:
                        parts.append(f"\n{child.to_sexp(indent + 1)}")
                    elif hasattr(child, "to_sexp"):
                        parts.append(f"\n{child.to_sexp(indent + 1)}")
                    else:
                        parts.append(f"\n{spaces}  {repr(child)}")
                else:
                    parts.append(f" {repr(child)}")

        parts.append(")")
        return "".join(parts)

    def __repr__(self) -> str:
        parts = [self.type]
        if self.metadata:
            if len(self.metadata) == 1 and "val" in self.metadata:
                parts.append(repr(self.metadata["val"]))
            else:
                parts.append(str(self.metadata))
        if self.children:
            parts.extend([repr(c) for c in self.children])
        return f"Node({' '.join(parts)})"

    def __iter__(self) -> Iterator[Any]:
        return iter(self.children)

    def __len__(self) -> int:
        return len(self.children)

    def __getitem__(self, index: Any) -> Any:
        return self.children[index]

    def __contains__(self, item: Any) -> bool:
        return item in self.children

    def __eq__(self, other: Any) -> bool:
        if type(other) is not Node:
            return False
        # Metadata doesn't affect equality
        return self.type == other.type and self.children == other.children

    def __hash__(self) -> int:
        # Hash based on type and children only, metadata excluded as per tests
        return hash((self.type, tuple(self.children)))

    def index(self, value: Any) -> int:
        """Return first index of value in children."""
        return self.children.index(value)

    def count(self, value: Any) -> int:
        """Return count of value in children."""
        return self.children.count(value)


class NodeVisitor:
    """AST Visitor that supports recursive modifications."""

    STRICT_HIERARCHY: bool = (
        True  # Set to False for passes that don't modify tree structure
    )

    _dispatch_table: dict[str, str] = {}
    _has_on_any: bool = False
    _MISSING = object()

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        cls._build_dispatch_table()

    @classmethod
    def _build_dispatch_table(cls) -> None:
        table: dict[str, str] = {}
        for name in dir(cls):
            if not name.startswith("on_") or name == "on_any" or len(name) <= 3:
                continue
            handler = getattr(cls, name, None)
            if callable(handler):
                table[sys.intern(name[3:])] = name
        cls._dispatch_table = table
        cls._has_on_any = callable(getattr(cls, "on_any", None))

    def visit(self, node: Node) -> Node:
        # Conditionally pre-seed index hints before recursion only if STRICT_HIERARCHY
        if self.STRICT_HIERARCHY:
            for idx, child in enumerate(node.children):
                if type(child) is Node:
                    child._index_hint = idx

        # Pass 1: recurse node children with snapshot to avoid corruption
        for child in list(node.children):
            if type(child) is Node:
                self.visit(child)

        # Process expand and remove nodes in a single pass
        final_children: AstChildren = []
        for child in node.children:
            if type(child) is Node:
                self._flatten_child(child, final_children)
            else:
                final_children.append(child)

        node.children = final_children
        # Conditionally rebuild hierarchy and index hints only if STRICT_HIERARCHY
        if self.STRICT_HIERARCHY:
            for idx, child in enumerate(final_children):
                if type(child) is Node:
                    child.parent = node
                    child._index_hint = idx

        # Execute handler via dispatch table (avoid getattr in hot path)
        dispatch_table = type(self)._dispatch_table
        handler_name = dispatch_table.get(node.type)
        if handler_name is not None:
            getattr(self, handler_name)(node)
        else:
            dynamic_cache = getattr(self, "_visitor_dynamic_handler_cache", None)
            if not isinstance(dynamic_cache, dict):
                dynamic_cache = {}
                object.__setattr__(
                    self, "_visitor_dynamic_handler_cache", dynamic_cache
                )

            handler = dynamic_cache.get(node.type, self._MISSING)
            if handler is self._MISSING:
                resolved = getattr(self, f"on_{node.type}", None)
                handler = resolved if callable(resolved) else None
                dynamic_cache[node.type] = handler

            if handler is not None:
                handler(node)
            elif type(self)._has_on_any:
                on_any = getattr(self, "on_any", None)
                if callable(on_any):
                    on_any(node)

        return node

    def _flatten_child(self, child: Node, new_children: AstChildren) -> None:
        if child.type == "expand":
            for sub in child.children:
                if isinstance(sub, Node):
                    if sub.type == "remove":
                        continue
                    elif sub.type == "expand":
                        self._flatten_child(sub, new_children)
                    else:
                        new_children.append(sub)
                else:
                    new_children.append(sub)
        elif child.type != "remove":
            new_children.append(child)
