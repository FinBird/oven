from __future__ import annotations

from typing import Any

from oven.core.ast import Node, NodeVisitor
from oven.core.pipeline import Transform


class PropagateLabels(Transform, NodeVisitor):
    """
    Move child labels upward so CFG build can cut blocks on parent nodes.
    """

    def transform(self, ast: Node, *rest: Any) -> Any:
        self._target_labels = self._collect_targets(ast)
        self.visit(ast)
        if rest:
            return (ast, *rest)
        return ast

    def on_any(self, node: Node) -> None:
        if node.type == "root":
            return

        min_label: int | None = None
        for child in node.children:
            if not isinstance(child, Node):
                continue
            label = child.metadata.get("label")
            if label is None:
                continue
            if min_label is None or label < min_label:
                min_label = label
            if child.metadata:
                child.metadata.pop("label", None)

        existing_label = node.metadata.get("label")
        if existing_label in self._target_labels:
            return

        if min_label is not None:
            node.ensure_metadata()["label"] = min_label

    def _collect_targets(self, root: Node) -> set[int]:
        targets: set[int] = set()
        stack = [root]
        while stack:
            node = stack.pop()
            if not isinstance(node, Node):
                continue

            if node.type == "jump" and node.children:
                target = node.children[0]
                if isinstance(target, int):
                    targets.add(target)
            elif node.type == "jump_if" and len(node.children) > 1:
                target = node.children[1]
                if isinstance(target, int):
                    targets.add(target)
            elif node.type == "lookup_switch" and len(node.children) > 1:
                default = node.children[0]
                cases = node.children[1]
                if isinstance(default, int):
                    targets.add(default)
                if isinstance(cases, list):
                    for case_target in cases:
                        if isinstance(case_target, int):
                            targets.add(case_target)

            for child in node.children:
                if isinstance(child, Node):
                    stack.append(child)

        return targets
