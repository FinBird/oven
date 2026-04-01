from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from oven.core.ast import Node
from oven.core.cfg import CFG, CFGNode
from oven.core.cfg.dialect import (
    CTIKind,
    ControlFlowAdapter,
    DefaultControlFlowAdapter,
    FlowDialect,
)
from oven.core.pipeline import Transform


@dataclass(slots=True)
class _ExcRange:
    start: int
    end: int
    block: CFGNode

    def includes(self, label: int | None) -> bool:
        return label is not None and self.start <= label <= self.end


class CFGBuild(Transform):
    """
    Build a CFG from normalized AST nodes.
    """

    def __init__(
        self,
        dialect: FlowDialect | None = None,
        adapter: ControlFlowAdapter | None = None,
    ) -> None:
        if adapter is not None:
            self.adapter = adapter
            self.dialect = getattr(adapter, "dialect", dialect or FlowDialect())
        else:
            self.dialect = dialect or FlowDialect()
            self.adapter = DefaultControlFlowAdapter(self.dialect)

    def transform(
        self, ast: Node, body: Any, finallies: Iterable[Any] | None = None
    ) -> CFG:
        _ = finallies  # reserved for future compatibility

        self._cfg = CFG()
        self._jumps: set[int | str] = set()
        self._exceptions: list[_ExcRange] = []
        self._target_offsets: set[int | str] = set()

        self._build_exception_dispatchers(body)

        self._pending_label: int | None = None
        self._pending_exc_block: CFGNode | None = None
        self._pending_queue: list[Node] = []

        get_branch_info = self.adapter.get_branch_info
        is_label = self.adapter.is_label
        is_nop = self.adapter.is_nop
        jumps_add = self._jumps.add
        contains_target_offset = self._target_offsets.__contains__
        queue_append = self._pending_queue.append

        ast_children = ast.children
        total_nodes = len(ast_children)

        for idx, node in enumerate(ast_children):
            if not isinstance(node, Node):
                continue

            if self._pending_label is None:
                self._pending_label = node.metadata.get("label")
                self._pending_exc_block, _ = self._exception_block_for(
                    self._pending_label
                )

            node_type = node.type
            branch = get_branch_info(node)

            next_node = ast_children[idx + 1] if idx + 1 < total_nodes else None
            next_label = (
                next_node.metadata.get("label") if isinstance(next_node, Node) else None
            )

            if branch is None:
                if not is_nop(node_type) and not is_label(node_type):
                    queue_append(node)
            else:
                if branch.keep_node:
                    queue_append(node)

                match branch.kind:
                    case CTIKind.TERMINAL:
                        self._cutoff(None, [None])
                        continue

                    case CTIKind.JUMP:
                        target = branch.targets[0] if branch.targets else None
                        if target is not None:
                            jumps_add(target)
                        self._cutoff(None, [target])
                        continue

                    case CTIKind.COND:
                        target = branch.targets[0] if branch.targets else None
                        if target is not None:
                            jumps_add(target)
                        if next_label is None and idx + 1 < total_nodes:
                            probe = ast_children[idx + 1]
                            if isinstance(probe, Node):
                                next_label = probe.metadata.get("label")
                        self._cutoff(node, [target, next_label])
                        continue

                    case CTIKind.SWITCH:
                        jumps_to = list(branch.targets)
                        for target in jumps_to:
                            if target is not None:
                                jumps_add(target)
                        self._cutoff(node, jumps_to)
                        continue

            next_exc_block, _ = self._exception_block_for(next_label)
            should_cut = (
                next_label in self._jumps
                or (isinstance(next_node, Node) and is_label(next_node.type))
                or contains_target_offset(next_label)
                or self._pending_exc_block is not next_exc_block
            )
            if should_cut:
                self._cutoff(None, [next_label])

        if self._pending_label is not None:
            self._cutoff(None, [None])

        exit_node = self._cfg.add_node(None, [])
        self._cfg.exit = exit_node

        self._cfg.eliminate_unreachable()
        self._cfg.merge_redundant()

        return self._cfg

    def _build_exception_dispatchers(self, body: Any) -> None:
        exceptions = list(getattr(body, "exceptions", []) or [])
        for index, exc in enumerate(exceptions):
            label = f"exc_{index}"
            exc_node = self._cfg.add_node(label, [])
            dispatch_node = Node(
                self.adapter.exception_dispatch_type, [], {"keep": True}
            )
            exc_node.instructions.append(dispatch_node)
            exc_node.cti = dispatch_node

            target = getattr(exc, "target_offset", None)
            if target is not None:
                exc_node.target_labels.append(target)
                self._target_offsets.add(target)

            catch = Node(
                self.adapter.catch_type,
                [
                    getattr(exc, "exc_type", None),
                    getattr(exc, "var_name", None),
                    target,
                ],
            )
            dispatch_node.children.append(catch)

            start = int(getattr(exc, "from_offset", 0))
            end = int(getattr(exc, "to_offset", 0))
            self._exceptions.append(_ExcRange(start, end, exc_node))

    def _exception_block_for(
        self, label: int | None
    ) -> tuple[CFGNode | None, _ExcRange | None]:
        if label is None:
            return None, None
        for item in self._exceptions:
            if item.includes(label):
                return item.block, item
        return None, None

    def _cutoff(self, cti: Node | None, targets: list[Any]) -> None:
        label = self._pending_label
        if label is None:
            return

        node = self._cfg.add_node(label, self._pending_queue[:])
        node.cti = cti
        node.target_labels = targets
        if self._pending_exc_block is not None:
            node.exception_label = self._pending_exc_block.label

        if self._cfg.entry is None:
            self._cfg.entry = node

        self._pending_label = None
        self._pending_exc_block = None
        self._pending_queue.clear()
