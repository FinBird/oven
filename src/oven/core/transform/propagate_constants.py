from __future__ import annotations

from typing import Any

from oven.core.ast import Node, NodeVisitor
from oven.core.pipeline import Transform


class _StopReplace(Exception):
    pass


class _Replacer(NodeVisitor):
    def __init__(self, local_var: int, value: Node) -> None:
        self._local_var = local_var
        self._value = value
        self._nodes: list[Node] = []
        self._graceful_shutdown = True

    def replace_in(self, nodes: list[Node]) -> bool:
        self._nodes = nodes
        self._graceful_shutdown = True
        try:
            for node in nodes:
                self.visit(node)
        except _StopReplace:
            pass
        return self._graceful_shutdown

    def on_set_local(self, node: Node) -> None:
        if not node.children:
            return
        index = node.children[0]
        if index == self._local_var:
            self._graceful_shutdown = node in self._nodes
            raise _StopReplace()

    def on_get_local(self, node: Node) -> None:
        if not node.children:
            return
        index = node.children[0]
        if index == self._local_var:
            node.update(
                node_type=self._value.type,
                children=self._value.children[:],
                metadata=self._value.metadata.copy(),
            )


class PropagateConstants(Transform[Node, Node], NodeVisitor):
    """
    Cheap propagation for find_property_strict values bound to locals.
    """

    def transform(self, ast: Node, *rest: Any) -> Any:
        self.visit(ast)
        if rest:
            return (ast, *rest)
        return ast

    def on_set_local(self, node: Node) -> None:
        if len(node.children) < 2:
            return
        local_index, value = node.children[:2]
        if not isinstance(value, Node):
            return
        if value.type != "find_property_strict":
            return
        if node.parent is None:
            return
        if not isinstance(local_index, int):
            return

        siblings = node.parent.children
        try:
            start = siblings.index(node) + 1
        except ValueError:
            return
        tail_nodes = [n for n in siblings[start:] if isinstance(n, Node)]
        replacer = _Replacer(local_index, value)
        if replacer.replace_in(tail_nodes):
            node.update(node_type="remove")
