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

        # Recursively propagate labels from descendants upward
        self._propagate_from_children(node)

    def _propagate_from_children(self, node: Node) -> int | None:
        """Recursively propagate labels from descendants up through this node.

        Returns the minimum label found in descendants, or None if no labels found.
        """
        if not isinstance(node, Node):
            return None

        all_found_labels: list[int] = []
        for child in node.children:
            if not isinstance(child, Node):
                continue

            child_label = self._propagate_from_children(child)
            if child_label is not None:
                all_found_labels.append(child_label)

            child_own_label = child.metadata.get("label")
            if isinstance(child_own_label, int):
                all_found_labels.append(child_own_label)

        if not all_found_labels:
            return None

        min_label = min(all_found_labels)
        if node.metadata.get("label") not in self._target_labels:
            node.ensure_metadata()["label"] = min_label
            self._remove_label_from_source(node, min_label)

        return min_label

    def _remove_label_from_source(self, node: Node, label: int) -> bool:
        """Remove a propagated label from the deepest *leaf* source node.

        Returns True when a label was removed.
        """
        # Prefer deeper descendants first.
        for child in node.children:
            if isinstance(child, Node) and self._remove_label_from_source(child, label):
                return True

        # Remove only from leaf nodes to preserve propagated labels on
        # intermediate structural nodes.
        for child in node.children:
            if not isinstance(child, Node):
                continue
            if child.metadata.get("label") != label:
                continue
            has_node_child = any(isinstance(grand, Node) for grand in child.children)
            if not has_node_child:
                child.metadata.pop("label", None)
                return True

        return False

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
