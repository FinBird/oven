from __future__ import annotations

from collections import defaultdict
from collections.abc import Hashable, Sequence
from dataclasses import dataclass, field
from typing import TypeAlias

from ..ast import Node
from ..utils import Graphviz

__all__ = ["CFG", "CFGNode"]

Label: TypeAlias = int | str | None
InstructionValue: TypeAlias = Node
CTIValue: TypeAlias = Node


@dataclass(slots=True)
class CFGNode:
    cfg: CFG | None = field(default=None)
    label: Label = None
    instructions: list[InstructionValue] = field(default_factory=list)
    cti: CTIValue | None = None  # Control Transfer Instruction
    target_labels: list[Label] = field(default_factory=list)
    exception_label: Label = None

    @property
    def targets(self) -> tuple[CFGNode, ...]:
        if self.cfg is None:
            return ()
        return tuple(self.cfg.find_node(l) for l in self.target_labels)

    @property
    def sources(self) -> list[CFGNode]:
        if self.cfg is None:
            return []
        return self.cfg.sources_for(self)

    @property
    def exception(self) -> CFGNode | None:
        if self.cfg is None:
            return None
        return (
            self.cfg.find_node(self.exception_label)
            if self.exception_label is not None
            else None
        )

    @property
    def exception_sources(self) -> list[CFGNode]:
        if self.cfg is None:
            return []
        return self.cfg.sources_for(self, exceptions=True)

    def add_target(self, target: CFGNode) -> None:
        """Add a target node to this node's target labels."""
        if target.label is None:
            raise ValueError("Cannot add target with None label")
        self.target_labels.append(target.label)

    def exits(self) -> bool:
        if self.cfg is None:
            return False
        return self.targets == (self.cfg.exit,)

    def __hash__(self) -> int:
        return hash(self.label) if self.label is not None else hash(id(self))

    def __repr__(self) -> str:
        if self.label is not None and self.instructions:
            ins = ", ".join(map(str, self.instructions))
            return f"<{self.label}:{ins}>"
        return f"<{self.label}>" if self.label is not None else "<!exit>"


class CFG:
    """Control Flow Graph with dominance analysis and optimizations."""

    def __init__(self) -> None:
        self.nodes: set[CFGNode] = set()
        self.entry: CFGNode | None = None
        self.exit: CFGNode | None = None

        # Caches and mappings
        self._label_map: dict[Label, CFGNode] = {}
        self._source_map: dict[CFGNode, list[CFGNode]] | None = None
        self._exception_source_map: dict[CFGNode, list[CFGNode]] | None = None
        self._dominators: dict[CFGNode, set[CFGNode]] | None = None
        self._postdominators: dict[CFGNode, set[CFGNode]] | None = None
        self._idom_forward: dict[CFGNode, CFGNode] | None = None
        self._idom_reverse: dict[CFGNode, CFGNode] | None = None
        self._dom_tree_forward_intervals: (
            tuple[dict[CFGNode, int], dict[CFGNode, int]] | None
        ) = None
        self._dom_tree_reverse_intervals: (
            tuple[dict[CFGNode, int], dict[CFGNode, int]] | None
        ) = None

    def find_node(self, label: Label) -> CFGNode:
        return self._resolve_label(label)

    def add_node(
        self,
        label: Label | CFGNode = None,
        insns: Sequence[InstructionValue] | None = None,
    ) -> CFGNode:
        # Backward-compatible path: accept an already constructed CFGNode.
        if isinstance(label, CFGNode):
            if insns is not None:
                raise ValueError("insns must be None when adding an existing CFGNode")
            node = label
            node.cfg = self
        else:
            node = CFGNode(
                self, label=label, instructions=list(insns) if insns is not None else []
            )

        self.nodes.add(node)
        if node.label is not None:
            self._label_map[node.label] = node
        self._invalidate_analysis()
        return node

    def flush_caches(self) -> None:
        """Invalidate all analysis caches and rebuild label lookup."""
        self._invalidate_analysis()
        self._label_map = {
            node.label: node for node in self.nodes if node.label is not None
        }

    def sources_for(self, node: CFGNode, exceptions: bool = False) -> list[CFGNode]:
        self._ensure_source_maps()
        source_map = self._exception_source_map if exceptions else self._source_map
        if source_map is None:
            raise RuntimeError("source map cache is unexpectedly empty")
        return source_map[node]

    def _invalidate_analysis(self, *, keep_source_maps: bool = False) -> None:
        if not keep_source_maps:
            self._source_map = None
            self._exception_source_map = None
        self._dominators = None
        self._postdominators = None
        self._idom_forward = None
        self._idom_reverse = None
        self._dom_tree_forward_intervals = None
        self._dom_tree_reverse_intervals = None

    def _ensure_source_maps(self) -> None:
        if self._source_map is None or self._exception_source_map is None:
            self._compute_source_maps()

    def _resolve_label(
        self,
        label: Label,
        label_map: dict[Label, CFGNode] | None = None,
        exit_node: CFGNode | None = None,
    ) -> CFGNode:
        if label_map is None:
            label_map = self._label_map
        if exit_node is None:
            exit_node = self.exit

        if label is None:
            if exit_node is None:
                raise KeyError("CFG exit node not found")
            return exit_node

        node = label_map.get(label)
        if node is None:
            raise KeyError(f"CFG node {label} not found")
        return node

    def _compute_source_maps(self) -> None:
        source_map: dict[CFGNode, list[CFGNode]] = defaultdict(list)
        exception_source_map: dict[CFGNode, list[CFGNode]] = defaultdict(list)
        label_map = self._label_map
        exit_node = self.exit
        resolve = self._resolve_label

        for node in self.nodes:
            for target_label in node.target_labels:
                source_map[resolve(target_label, label_map, exit_node)].append(node)

            exc_label = node.exception_label
            if exc_label is not None:
                exception_source_map[resolve(exc_label, label_map, exit_node)].append(
                    node
                )

        self._source_map = source_map
        self._exception_source_map = exception_source_map

    def get_reverse_post_order(
        self, start_node: CFGNode | None = None, *, forward: bool = True
    ) -> list[CFGNode]:
        """Compute reverse post-order from entry (or exit for reverse analysis)."""
        if start_node is None:
            start_node = self.entry if forward else self.exit
        if start_node is None:
            return []

        if not forward:
            self._ensure_source_maps()
            if self._source_map is None or self._exception_source_map is None:
                raise RuntimeError("source map cache is unexpectedly empty")

        visited: set[CFGNode] = set()
        post_order: list[CFGNode] = []
        stack: list[tuple[CFGNode, bool]] = [(start_node, False)]

        label_map = self._label_map
        exit_node = self.exit
        resolve = self._resolve_label

        while stack:
            node, expanded = stack.pop()
            if expanded:
                post_order.append(node)
                continue
            if node in visited:
                continue

            visited.add(node)
            stack.append((node, True))

            if forward:
                exc_label = node.exception_label
                if exc_label is not None:
                    stack.append((resolve(exc_label, label_map, exit_node), False))

                target_labels = node.target_labels
                for index in range(len(target_labels) - 1, -1, -1):
                    stack.append(
                        (resolve(target_labels[index], label_map, exit_node), False)
                    )
            else:
                exception_source_map = self._exception_source_map
                source_map = self._source_map
                if exception_source_map is None or source_map is None:
                    raise RuntimeError("source map cache is unexpectedly empty")
                for pred in reversed(exception_source_map[node]):
                    stack.append((pred, False))
                for pred in reversed(source_map[node]):
                    stack.append((pred, False))

        post_order.reverse()
        return post_order

    def eliminate_unreachable(self) -> None:
        """Remove nodes not reachable from entry."""
        entry = self.entry
        if entry is None:
            return

        label_map = self._label_map
        exit_node = self.exit
        resolve = self._resolve_label
        reachable = {entry}
        stack = [entry]

        while stack:
            node = stack.pop()

            for target_label in node.target_labels:
                target = resolve(target_label, label_map, exit_node)
                if target not in reachable:
                    reachable.add(target)
                    stack.append(target)

            exc_label = node.exception_label
            if exc_label is not None:
                exc_node = resolve(exc_label, label_map, exit_node)
                if exc_node not in reachable:
                    reachable.add(exc_node)
                    stack.append(exc_node)

        if reachable == self.nodes:
            return

        self.nodes.intersection_update(reachable)
        if self.entry not in self.nodes:
            self.entry = None
        if self.exit is not None and self.exit not in self.nodes:
            self.exit = None
        self.flush_caches()

    @staticmethod
    def _remove_one_ref(refs: list[CFGNode], node: CFGNode) -> None:
        for idx, ref in enumerate(refs):
            if ref is node:
                del refs[idx]
                return

    @staticmethod
    def _discard_identity(seq: list[InstructionValue], value: object) -> None:
        if not seq:
            return
        if seq[-1] is value:
            seq.pop()
            return
        for idx, item in enumerate(seq):
            if item is value:
                del seq[idx]
                return

    def merge_redundant(self) -> None:
        """Merge basic blocks and simplify the graph incrementally (worklist)."""
        self._ensure_source_maps()

        source_map = self._source_map
        exception_source_map = self._exception_source_map
        if source_map is None or exception_source_map is None:
            raise RuntimeError("source map cache initialization failed")

        label_map = self._label_map
        exit_node = self.exit
        resolve = self._resolve_label
        worklist: set[CFGNode] = set(self.nodes)

        while worklist:
            node = worklist.pop()

            if node not in self.nodes:
                continue
            if len(node.target_labels) != 1:
                continue

            cti = node.cti
            if cti and hasattr(cti, "metadata") and cti.metadata.get("keep"):
                continue

            target = resolve(node.target_labels[0], label_map, exit_node)

            # Case 1: Empty block forwarding
            if not node.instructions and target is not node:
                self._remove_one_ref(source_map[target], node)

                incoming_normal = source_map[node]
                if incoming_normal:
                    for source in set(incoming_normal):
                        replaced = 0
                        labels = source.target_labels
                        for idx, label in enumerate(labels):
                            if label == node.label:
                                labels[idx] = target.label
                                replaced += 1
                        if replaced:
                            source_map[target].extend([source] * replaced)
                            if source in self.nodes:
                                worklist.add(source)
                    incoming_normal.clear()

                incoming_exception = exception_source_map[node]
                if incoming_exception:
                    for source in incoming_exception:
                        if source.exception_label == node.label:
                            source.exception_label = target.label
                        exception_source_map[target].append(source)
                        if source in self.nodes:
                            worklist.add(source)
                    incoming_exception.clear()

                exc_label = node.exception_label
                if exc_label is not None:
                    exc_target = resolve(exc_label, label_map, exit_node)
                    self._remove_one_ref(exception_source_map[exc_target], node)

                if self.entry is node:
                    self.entry = target

                self._remove_node_from_cfg(node, keep_source_maps=True)
                if target in self.nodes:
                    worklist.add(target)
                continue

            # Case 2: Simple linear merge (node -> target)
            if (
                target is not node
                and target is not exit_node
                and len(source_map[target]) == 1
                and not exception_source_map[target]
                and node.exception_label == target.exception_label
            ):
                if self.entry is target:
                    self.entry = node

                self._discard_identity(node.instructions, cti)

                old_target_labels = list(target.target_labels)
                node.instructions.extend(target.instructions)
                node.target_labels = old_target_labels
                node.cti = target.cti

                self._remove_one_ref(source_map[target], node)

                for successor_label in old_target_labels:
                    successor = resolve(successor_label, label_map, exit_node)
                    refs = source_map[successor]
                    for idx, source in enumerate(refs):
                        if source is target:
                            refs[idx] = node

                target_exc_label = target.exception_label
                if target_exc_label is not None:
                    exc_target = resolve(target_exc_label, label_map, exit_node)
                    self._remove_one_ref(exception_source_map[exc_target], target)

                self._remove_node_from_cfg(target, keep_source_maps=True)
                if node in self.nodes:
                    worklist.add(node)

        # Source maps 已按增量方式维护；仅清掉依赖 CFG 拓扑的分析缓存。
        self._invalidate_analysis(keep_source_maps=True)

    def _remove_node_from_cfg(
        self, node: CFGNode, *, keep_source_maps: bool = False
    ) -> None:
        """Remove a node and its map entries from the CFG."""
        self.nodes.remove(node)
        self._label_map.pop(node.label, None)
        if self._source_map is not None:
            self._source_map.pop(node, None)
        if self._exception_source_map is not None:
            self._exception_source_map.pop(node, None)
        self._invalidate_analysis(keep_source_maps=keep_source_maps)

    @staticmethod
    def _intersect_idom(
        b1: CFGNode,
        b2: CFGNode,
        idom: dict[CFGNode, CFGNode | None],
        rpo_index: dict[CFGNode, int],
    ) -> CFGNode:
        finger1 = b1
        finger2 = b2
        while finger1 is not finger2:
            while rpo_index[finger1] > rpo_index[finger2]:
                parent = idom[finger1]
                if parent is None:
                    break
                finger1 = parent
            while rpo_index[finger2] > rpo_index[finger1]:
                parent = idom[finger2]
                if parent is None:
                    break
                finger2 = parent
        return finger1

    def _compute_idom(
        self, start_node: CFGNode, *, forward: bool
    ) -> tuple[list[CFGNode], dict[CFGNode, CFGNode | None]]:
        rpo = self.get_reverse_post_order(start_node, forward=forward)
        if not rpo:
            return [], {}

        reachable = set(rpo)
        rpo_index = {node: idx for idx, node in enumerate(rpo)}

        if forward:
            self._ensure_source_maps()
            if self._source_map is None or self._exception_source_map is None:
                raise RuntimeError("source map cache is unexpectedly empty")

            source_map = self._source_map
            exception_source_map = self._exception_source_map
            preds: dict[CFGNode, list[CFGNode]] = {}
            for node in rpo:
                pred_list = [pred for pred in source_map[node] if pred in reachable]
                pred_list.extend(
                    pred for pred in exception_source_map[node] if pred in reachable
                )
                preds[node] = pred_list
        else:
            preds = {}
            label_map = self._label_map
            exit_node = self.exit
            resolve = self._resolve_label

            for node in rpo:
                reverse_preds: list[CFGNode] = []
                for label in node.target_labels:
                    pred = resolve(label, label_map, exit_node)
                    if pred in reachable:
                        reverse_preds.append(pred)

                exc_label = node.exception_label
                if exc_label is not None:
                    pred = resolve(exc_label, label_map, exit_node)
                    if pred in reachable:
                        reverse_preds.append(pred)

                preds[node] = reverse_preds

        idom: dict[CFGNode, CFGNode | None] = {node: None for node in rpo}
        idom[start_node] = start_node

        changed = True
        while changed:
            changed = False
            for node in rpo[1:]:
                pred_candidates = [
                    pred for pred in preds[node] if idom.get(pred) is not None
                ]
                if not pred_candidates:
                    continue

                new_idom = pred_candidates[0]
                for pred in pred_candidates[1:]:
                    new_idom = self._intersect_idom(new_idom, pred, idom, rpo_index)

                if idom[node] is not new_idom:
                    idom[node] = new_idom
                    changed = True

        return rpo, idom

    def _get_immediate_dominators(self, *, forward: bool) -> dict[CFGNode, CFGNode]:
        cache = self._idom_forward if forward else self._idom_reverse
        if cache is not None:
            return cache

        start_node = self.entry if forward else self.exit
        if start_node is None:
            return {}

        _, idom = self._compute_idom(start_node, forward=forward)
        normalized = {
            node: parent for node, parent in idom.items() if parent is not None
        }
        if forward:
            self._idom_forward = normalized
        else:
            self._idom_reverse = normalized
        return normalized

    def _compute_domination_legacy(
        self, start_node: CFGNode, forward: bool
    ) -> dict[CFGNode, set[CFGNode]]:
        """Legacy iterative set-intersection algorithm, kept for perf comparison baselines."""
        all_nodes = list(self.nodes)
        all_nodes_set = set(self.nodes)

        preds_cache: dict[CFGNode, list[CFGNode]] = {}
        for node in all_nodes:
            if forward:
                preds_cache[node] = node.sources + node.exception_sources
            else:
                preds = list(node.targets)
                if exc := node.exception:
                    preds.append(exc)
                preds_cache[node] = preds

        dom: dict[CFGNode, set[CFGNode]] = {
            node: all_nodes_set.copy() for node in all_nodes
        }
        dom[start_node] = {start_node}

        changed = True
        while changed:
            changed = False
            for node in all_nodes:
                if node is start_node:
                    continue

                preds = preds_cache[node]
                if not preds:
                    new_dom = {node}
                else:
                    iterator = iter(preds)
                    new_dom = dom[next(iterator)].copy()
                    for pred in iterator:
                        new_dom.intersection_update(dom[pred])
                    new_dom.add(node)

                if new_dom != dom[node]:
                    dom[node] = new_dom
                    changed = True
        return dom

    def _compute_domination(
        self, start_node: CFGNode, forward: bool
    ) -> dict[CFGNode, set[CFGNode]]:
        if start_node is None:
            return {}

        rpo, idom = self._compute_idom(start_node, forward=forward)
        if not rpo:
            return {}

        reachable = set(rpo)
        normalized_idom = {
            node: parent for node, parent in idom.items() if parent is not None
        }
        if forward:
            self._idom_forward = normalized_idom
        else:
            self._idom_reverse = normalized_idom

        dom: dict[CFGNode, set[CFGNode]] = {
            node: {node} for node in self.nodes if node not in reachable
        }

        dom[start_node] = {start_node}
        for node in rpo[1:]:
            parent = normalized_idom.get(node)
            dom[node] = {node} if parent is None else (dom[parent] | {node})

        return dom

    @property
    def dominators(self) -> dict[CFGNode, set[CFGNode]]:
        if self.entry is None:
            return {}
        if self._dominators is None:
            self._dominators = self._compute_domination(self.entry, True)
        return self._dominators

    @property
    def postdominators(self) -> dict[CFGNode, set[CFGNode]]:
        if self.exit is None:
            return {}
        if self._postdominators is None:
            self._postdominators = self._compute_domination(self.exit, False)
        return self._postdominators

    @staticmethod
    def _is_dominated_by(
        node: CFGNode, header: CFGNode, idom: dict[CFGNode, CFGNode]
    ) -> bool:
        cursor: CFGNode | None = node
        while cursor is not None:
            if cursor is header:
                return True
            parent = idom.get(cursor)
            if parent is None or parent is cursor:
                return False
            cursor = parent
        return False

    def _identify_loops_legacy(self) -> dict[CFGNode, set[CFGNode]]:
        loops: dict[CFGNode, set[CFGNode]] = defaultdict(set)
        dom = self.dominators

        back_edges = [(m, n) for m in self.nodes for n in m.targets if n in dom[m]]

        for source, header in back_edges:
            body = loops[header]
            body.add(header)
            stack = [source]
            visited = {source}
            while stack:
                curr = stack.pop()
                if curr not in body:
                    body.add(curr)
                    for prev in self.sources_for(curr):
                        if prev != header and prev not in visited:
                            visited.add(prev)
                            stack.append(prev)
        return loops

    def _compute_dom_tree_intervals(
        self, *, forward: bool
    ) -> tuple[dict[CFGNode, int], dict[CFGNode, int]]:
        cached = (
            self._dom_tree_forward_intervals
            if forward
            else self._dom_tree_reverse_intervals
        )
        if cached is not None:
            return cached

        idom = self._get_immediate_dominators(forward=forward)
        if not idom:
            empty: tuple[dict[CFGNode, int], dict[CFGNode, int]] = ({}, {})
            if forward:
                self._dom_tree_forward_intervals = empty
            else:
                self._dom_tree_reverse_intervals = empty
            return empty

        children: dict[CFGNode, list[CFGNode]] = defaultdict(list)
        roots: list[CFGNode] = []
        for node, parent in idom.items():
            if parent is node or parent not in idom:
                roots.append(node)
            else:
                children[parent].append(node)

        tin: dict[CFGNode, int] = {}
        tout: dict[CFGNode, int] = {}
        timer = 0

        for root in roots:
            if root in tin:
                continue

            stack: list[tuple[CFGNode, bool]] = [(root, False)]
            while stack:
                node, expanded = stack.pop()
                if not expanded:
                    if node in tin:
                        continue
                    tin[node] = timer
                    timer += 1
                    stack.append((node, True))
                    for child in reversed(children.get(node, [])):
                        if child not in tin:
                            stack.append((child, False))
                else:
                    tout[node] = timer

        result = (tin, tout)
        if forward:
            self._dom_tree_forward_intervals = result
        else:
            self._dom_tree_reverse_intervals = result
        return result

    def identify_loops(self) -> dict[CFGNode, set[CFGNode]]:
        """Identify natural loops using back-edges over the immediate-dominator tree."""
        self._ensure_source_maps()
        source_map = self._source_map
        if source_map is None:
            raise RuntimeError("source map cache is unexpectedly empty")

        idom = self._get_immediate_dominators(forward=True)
        if not idom:
            return {}

        tin, tout = self._compute_dom_tree_intervals(forward=True)
        label_map = self._label_map
        exit_node = self.exit
        resolve = self._resolve_label

        # 按 header 聚合回边，避免同一 header 多次做重复反向搜索。
        backedge_sources: dict[CFGNode, list[CFGNode]] = defaultdict(list)
        for source in self.nodes:
            source_in = tin.get(source)
            if source_in is None:
                continue

            for target_label in source.target_labels:
                header = resolve(target_label, label_map, exit_node)
                header_in = tin.get(header)
                header_out = tout.get(header)
                if header_in is None or header_out is None:
                    continue
                if header_in <= source_in < header_out:
                    backedge_sources[header].append(source)

        loops: dict[CFGNode, set[CFGNode]] = {}
        for header, sources in backedge_sources.items():
            body = {header}
            visited = {header}
            worklist = list(sources)

            while worklist:
                curr = worklist.pop()
                if curr in visited:
                    continue
                visited.add(curr)
                body.add(curr)
                for prev in source_map[curr]:
                    if prev not in visited:
                        worklist.append(prev)

            loops[header] = body

        return loops

    def to_graphviz(self) -> str:
        """Export CFG to Graphviz DOT format."""
        graph = Graphviz()
        for node in self.nodes:
            content = [f"<{node.label!r}>"] if node.label else []
            content.extend(repr(ins) for ins in node.instructions)

            label_text = "\n".join(content) if content else "<exit>"
            node_key = str(node.label) if node.label is not None else "None"

            opts: dict[str, str | int | bool] = {}
            if self.entry == node:
                opts["color"] = "green"
            if self.exit == node:
                opts["color"] = "red"

            graph.node(node_key, label_text, opts)

            for idx, target in enumerate(node.target_labels):
                graph.edge(node_key, str(target), label=str(idx))
            if node.exception_label:
                graph.edge(
                    node_key,
                    str(node.exception_label),
                    label="Exc",
                    options={"color": "orange"},
                )
        return str(graph)

    def to_graphviz_file(self, filename: str) -> None:
        with open(filename, "w", encoding="utf-8") as handle:
            handle.write(self.to_graphviz())
