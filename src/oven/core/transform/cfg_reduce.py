from __future__ import annotations

from typing import Any

from oven.core.ast import Node
from oven.core.ast.node import AstChild
from oven.core.cfg import CFG, CFGNode
from oven.core.cfg.dialect import FlowDialect
from oven.core.pipeline import Transform
from oven.core.cfg.core import Label


class CFGReduce(Transform[CFG, Node]):
    """
    Reduce CFG to a structured AST (minimal, practical subset):
    - linear blocks
    - simple if/else diamonds
    - simple while loops with a back-edge
    """

    def __init__(self, dialect: FlowDialect | None = None) -> None:
        self.dialect = dialect or FlowDialect()

    def transform(self, cfg: CFG) -> Node:
        self._cfg = cfg
        self._visited: set[CFGNode] = set()
        self._loops = cfg.identify_loops()
        self._exc_processed: set[object] = set()

        if cfg.entry is None:
            return Node(self.dialect.ast_begin, [])

        ast = self._reduce_from(cfg.entry, stop=None)
        return ast

    def _reduce_from(
        self,
        block: CFGNode | None,
        stop: CFGNode | None,
        barriers: set[CFGNode] | None = None,
        loop_nodes: set[CFGNode] | None = None,
        break_target: CFGNode | None = None,
        continue_target: CFGNode | None = None,
    ) -> Node:
        nodes: list[Node] = []
        iteration_count = 0
        max_iterations = 500000  # Increased limit for complex CFGs
        block_visit_count: dict[CFGNode, int] = {}

        while block is not None:
            iteration_count += 1
            if iteration_count > max_iterations:
                break

            # Prevent infinite loops on irreducible control flow
            if block not in block_visit_count:
                block_visit_count[block] = 0
            block_visit_count[block] += 1
            if block_visit_count[block] > 5:  # Same block visited too many times
                break
            if break_target is not None and block == break_target:
                nodes.append(Node(self.dialect.ast_break))
                break
            if (
                continue_target is not None
                and block == continue_target
                and stop != continue_target
            ):
                nodes.append(Node(self.dialect.ast_continue))
                break

            if block == stop or block == self._cfg.exit:
                break
            if loop_nodes is not None and block not in loop_nodes:
                if break_target is not None:
                    nodes.append(Node(self.dialect.ast_break))
                break
            if barriers is not None and block in barriers:
                break

            # --- Try-Catch-Finally interception ---
            exc_label = block.exception_label
            if exc_label is not None and exc_label not in self._exc_processed:
                try_node, next_block = self._reduce_try_catch_finally(
                    block,
                    exc_label,
                    barriers,
                    loop_nodes,
                    break_target,
                    continue_target,
                )
                nodes.append(try_node)
                block = next_block
                continue
            # ----------------------------------------

            if block in self._visited:
                # Already consumed by an enclosing control construct.
                break
            self._visited.add(block)

            self._append_non_cti(block, nodes)

            cti = block.cti
            if cti is None:
                if len(block.targets) == 1:
                    nxt = block.targets[0]
                    # When walking inside an exception region, stop following
                    # normal edges if the target has a different exception_label.
                    if exc_label is not None and nxt.exception_label != exc_label:
                        block = None
                        continue
                    target_kind = self._classify_loop_target(
                        nxt,
                        loop_nodes=loop_nodes,
                        break_target=break_target,
                        continue_target=continue_target,
                    )
                    if target_kind == self.dialect.ast_break:
                        nodes.append(Node(self.dialect.ast_break))
                        block = None
                        continue
                    if target_kind == self.dialect.ast_continue:
                        if stop != continue_target:
                            nodes.append(Node(self.dialect.ast_continue))
                            block = None
                        else:
                            block = nxt
                        continue
                    if (
                        target_kind == "outside"
                        and break_target is not None
                        and nxt != self._cfg.exit
                    ):
                        nodes.append(Node(self.dialect.ast_break))
                        block = None
                        continue
                    block = nxt
                else:
                    block = None
                continue

            if cti.type in self.dialect.terminal_transfers:
                nodes.append(cti)
                block = None
                continue

            if (
                cti.type == self.dialect.jump
                and len(block.targets) == 1
                and (
                    loop_nodes is not None
                    or break_target is not None
                    or continue_target is not None
                )
            ):
                nxt = block.targets[0]
                target_kind = self._classify_loop_target(
                    nxt,
                    loop_nodes=loop_nodes,
                    break_target=break_target,
                    continue_target=continue_target,
                )
                if target_kind == self.dialect.ast_break:
                    nodes.append(Node(self.dialect.ast_break))
                    block = None
                    continue
                if target_kind == self.dialect.ast_continue:
                    if stop != continue_target:
                        nodes.append(Node(self.dialect.ast_continue))
                        block = None
                    else:
                        block = nxt
                    continue
                if (
                    target_kind == "outside"
                    and break_target is not None
                    and nxt != self._cfg.exit
                ):
                    nodes.append(Node(self.dialect.ast_break))
                    block = None
                    continue
                # Structured forward jump inside a loop region: continue from target.
                block = nxt
                continue

            if cti.type in self.dialect.conditional_jumps and len(block.targets) == 2:
                loop_branch, next_block = self._reduce_loop_jump_if_if_possible(
                    block,
                    loop_nodes=loop_nodes,
                    break_target=break_target,
                    continue_target=continue_target,
                )
                if loop_branch is not None:
                    nodes.append(loop_branch)
                    block = next_block
                    continue

                loop_node = self._reduce_while_if_possible(block, barriers=barriers)
                if loop_node is not None:
                    nodes.append(loop_node)
                    # choose the outside edge
                    loop_set = self._loops.get(block, set())
                    out_target = None
                    for t in block.targets:
                        if t not in loop_set:
                            out_target = t
                            break
                    block = out_target
                    continue

                if_node, merge = self._reduce_if_if_possible(
                    block,
                    barriers=barriers,
                    loop_nodes=loop_nodes,
                    break_target=break_target,
                    continue_target=continue_target,
                )
                if if_node is not None:
                    nodes.append(if_node)
                    block = merge
                    continue

                # Fallback: emit low-level jump_if node
                nodes.append(cti)
                block = block.targets[0]
                continue

            if cti.type in self.dialect.switches and len(block.targets) >= 1:
                switch_node, merge = self._reduce_switch(block, barriers=barriers)
                nodes.append(switch_node)
                block = merge
                continue

            # Unknown CTI form: keep as-is and stop to avoid wrong structure.
            nodes.append(cti)
            block = None

        return Node(self.dialect.ast_begin, nodes)

    def _append_non_cti(self, block: CFGNode, out: list[Node]) -> None:
        for insn in block.instructions:
            if insn is block.cti:
                continue
            if type(insn) is Node:
                out.append(insn)

    def _classify_loop_target(
        self,
        target: CFGNode,
        *,
        loop_nodes: set[CFGNode] | None,
        break_target: CFGNode | None,
        continue_target: CFGNode | None,
    ) -> str:
        if break_target is not None and target == break_target:
            return self.dialect.ast_break
        if continue_target is not None and target == continue_target:
            return self.dialect.ast_continue
        if loop_nodes is None or target in loop_nodes:
            return "inside"
        return "outside"

    def _reduce_loop_jump_if_if_possible(
        self,
        header: CFGNode,
        *,
        loop_nodes: set[CFGNode] | None,
        break_target: CFGNode | None,
        continue_target: CFGNode | None,
    ) -> tuple[Node | None, CFGNode | None]:
        if loop_nodes is None or len(header.targets) != 2:
            return None, None

        t0, t1 = header.targets
        kind0 = self._classify_loop_target(
            t0,
            loop_nodes=loop_nodes,
            break_target=break_target,
            continue_target=continue_target,
        )
        kind1 = self._classify_loop_target(
            t1,
            loop_nodes=loop_nodes,
            break_target=break_target,
            continue_target=continue_target,
        )

        controls = {self.dialect.ast_break, self.dialect.ast_continue}
        cond = self._condition_from_jump_if(header)

        if kind0 in controls and kind1 == "inside":
            return (
                Node(
                    self.dialect.ast_if,
                    [cond, Node(self.dialect.ast_begin, [Node(kind0)])],
                ),
                t1,
            )

        if kind1 in controls and kind0 == "inside":
            return (
                Node(
                    self.dialect.ast_if,
                    [
                        Node(self.dialect.ast_not, [cond]),
                        Node(self.dialect.ast_begin, [Node(kind1)]),
                    ],
                ),
                t0,
            )

        if kind0 in controls and kind1 in controls:
            return (
                Node(
                    self.dialect.ast_if,
                    [
                        cond,
                        Node(self.dialect.ast_begin, [Node(kind0)]),
                        Node(self.dialect.ast_begin, [Node(kind1)]),
                    ],
                ),
                None,
            )

        return None, None

    def _condition_from_jump_if(self, block: CFGNode) -> Node:
        cti = block.cti
        if type(cti) is not Node:
            return Node(self.dialect.ast_true)
        children = list(cti.children)
        flag = bool(children[0]) if children else True

        # Historical IR variants:
        # 1) [flag, cond]
        # 2) [flag, target, cond]
        cond_raw: Any
        if len(children) >= 3 and type(children[1]) is not Node:
            cond_raw = children[2]
        elif len(children) >= 2:
            cond_raw = children[1]
        else:
            cond_raw = Node(self.dialect.ast_true)

        cond = cond_raw if type(cond_raw) is Node else Node(self.dialect.ast_true)
        if flag:
            return cond
        return Node(self.dialect.ast_not, [cond])

    def _forward_distances(
        self, start: CFGNode, max_steps: int = 100000
    ) -> dict[CFGNode, int]:
        dist: dict[CFGNode, int] = {start: 0}
        queue: list[CFGNode] = [start]
        steps = 0
        while queue and steps < max_steps:
            node = queue.pop(0)
            base = dist[node]
            for nxt in node.targets:
                if nxt not in dist:
                    dist[nxt] = base + 1
                    queue.append(nxt)
            steps += 1
        return dist

    def _find_merge_node(self, left: CFGNode, right: CFGNode) -> CFGNode | None:
        cfg = getattr(self, "_cfg", None) or left.cfg or right.cfg
        if cfg is None:
            return None
        post = cfg.postdominators
        left_pd = post.get(left, set())
        right_pd = post.get(right, set())
        common = left_pd & right_pd

        terminals = self.dialect.terminal_transfers
        left_terminal = type(left.cti) is Node and left.cti.type in terminals
        right_terminal = type(right.cti) is Node and right.cti.type in terminals

        # One-arm terminal diamond: treat terminal arm as no-merge contributor,
        # pick the nearest non-exit node reachable from the productive arm.
        if left_terminal ^ right_terminal:
            productive = right if left_terminal else left
            dist = self._forward_distances(productive)
            productive_candidates: list[tuple[int, str, CFGNode]] = []
            for cand, steps in dist.items():
                if cand in {productive, cfg.exit}:
                    continue
                productive_candidates.append((steps, str(cand.label), cand))
            if productive_candidates:
                productive_candidates.sort(key=lambda item: (item[0], item[1]))
                return productive_candidates[0][2]

        dl = self._forward_distances(left)
        dr = self._forward_distances(right)
        ranked: list[tuple[int, int, int, str, CFGNode]] = []
        for cand in common:
            if cand not in dl or cand not in dr:
                continue
            d1 = dl[cand]
            d2 = dr[cand]
            prefer_non_exit = 0 if cand != cfg.exit else 1
            ranked.append(
                (prefer_non_exit, max(d1, d2), d1 + d2, str(cand.label), cand)
            )

        if ranked:
            ranked.sort(key=lambda item: (item[0], item[1], item[2], item[3]))
            return ranked[0][4]

        return None

    def _reduce_while_if_possible(
        self,
        header: CFGNode,
        barriers: set[CFGNode] | None = None,
    ) -> Node | None:
        if header not in self._loops:
            return None
        loop_set = self._loops[header]
        if not loop_set:
            return None
        if len(header.targets) != 2:
            return None

        inside = None
        outside = None
        for t in header.targets:
            if t in loop_set:
                inside = t
            else:
                outside = t
        if inside is None or outside is None:
            return None

        body = self._reduce_from(
            inside,
            stop=header,
            barriers=barriers,
            loop_nodes=loop_set,
            break_target=outside,
            continue_target=header,
        )
        cond = self._condition_from_jump_if(header)
        return Node(self.dialect.ast_while, [cond, body])

    def _single_succ(self, block: CFGNode) -> CFGNode | None:
        if len(block.targets) == 1:
            return block.targets[0]
        return None

    def _ends_with_terminal_stmt(self, node: Node) -> bool:
        """Check if a node (typically a begin block) ends with a terminal statement."""
        if not isinstance(node, Node):
            return False
        if node.type in ("return_void", "return_value", "break", "continue", "throw"):
            return True
        if node.type == "begin" and node.children:
            # Check the last child
            last_child = node.children[-1]
            return self._ends_with_terminal_stmt(last_child)
        return False

    def _optimize_nested_if_else_duplication(
        self, outer_cond: Node, then_ast: Node, else_ast: Node
    ) -> Node | None:
        """
        Optimize pattern: if (A) { if (B) { X } else { terminal } } else { X }
        to: if (A && !B) { terminal } X
        """
        if not isinstance(then_ast, Node) or then_ast.type != self.dialect.ast_if:
            return None
        if len(then_ast.children) != 3:  # Must have condition, then, else
            return None

        inner_cond = then_ast.children[0]
        inner_then = then_ast.children[1]
        inner_else = then_ast.children[2]

        # Check if inner_else is terminal
        if not self._ends_with_terminal_stmt(inner_else):
            return None

        # Check if inner_then equals else_ast
        if not self._ast_equal(inner_then, else_ast):
            return None

        # Create optimized structure: if (A && !B) { terminal } followed by X
        # For now, create a simple if without else, followed by the common code
        negated_inner_cond = Node(self.dialect.ast_not, [inner_cond])
        # We need to combine conditions. For simplicity, create a compound condition
        # This is a placeholder - actual implementation would need proper logical AND
        combined_cond = Node(
            "&&", [outer_cond, negated_inner_cond]
        )  # Use string for now

        return Node(
            self.dialect.ast_begin,
            [Node(self.dialect.ast_if, [combined_cond, inner_else]), else_ast],
        )

    def _ast_equal(self, a: Node, b: Node) -> bool:
        """Check if two AST nodes are structurally equal."""
        if not isinstance(a, Node) or not isinstance(b, Node):
            return a == b
        if a.type != b.type or len(a.children) != len(b.children):
            return False
        return all(self._ast_equal(ca, cb) for ca, cb in zip(a.children, b.children))

    def _reduce_if_if_possible(
        self,
        header: CFGNode,
        barriers: set[CFGNode] | None = None,
        loop_nodes: set[CFGNode] | None = None,
        break_target: CFGNode | None = None,
        continue_target: CFGNode | None = None,
    ) -> tuple[Node | None, CFGNode | None]:
        t_then, t_else = header.targets
        s_then = self._single_succ(t_then)
        s_else = self._single_succ(t_else)

        # two-way diamond
        if s_then is not None and s_then == s_else:
            diamond_merge = s_then
            then_ast = self._reduce_from(
                t_then,
                stop=diamond_merge,
                barriers=barriers,
                loop_nodes=loop_nodes,
                break_target=break_target,
                continue_target=continue_target,
            )
            else_ast = self._reduce_from(
                t_else,
                stop=diamond_merge,
                barriers=barriers,
                loop_nodes=loop_nodes,
                break_target=break_target,
                continue_target=continue_target,
            )
            cond = self._condition_from_jump_if(header)

            # Optimization: if then branch ends with terminal statement, flatten else
            if self._ends_with_terminal_stmt(then_ast):
                # Create a begin block with if (no else) followed by else content
                if_stmts = [Node(self.dialect.ast_if, [cond, then_ast])]
                if else_ast.children:  # Only add else if it has content
                    if_stmts.extend(else_ast.children)
                flattened_ast = Node(self.dialect.ast_begin, if_stmts)
                return flattened_ast, diamond_merge

            # Optimization: detect nested if-else where outer else duplicates inner then
            optimized = self._optimize_nested_if_else_duplication(
                cond, then_ast, else_ast
            )
            if optimized is not None:
                return optimized, diamond_merge

            return Node(self.dialect.ast_if, [cond, then_ast, else_ast]), diamond_merge

        # one-way if: then falls into else root
        if s_then is not None and s_then == t_else:
            then_ast = self._reduce_from(
                t_then,
                stop=t_else,
                barriers=barriers,
                loop_nodes=loop_nodes,
                break_target=break_target,
                continue_target=continue_target,
            )
            cond = self._condition_from_jump_if(header)
            return Node(self.dialect.ast_if, [cond, then_ast]), t_else

        # one-way if with swapped sides
        if s_else is not None and s_else == t_then:
            else_cond = self._condition_from_jump_if(header)
            cond = Node(self.dialect.ast_not, [else_cond])
            then_ast = self._reduce_from(
                t_else,
                stop=t_then,
                barriers=barriers,
                loop_nodes=loop_nodes,
                break_target=break_target,
                continue_target=continue_target,
            )
            return Node(self.dialect.ast_if, [cond, then_ast]), t_then

        # General case: choose nearest common post-dominator as merge.
        merge = self._find_merge_node(t_then, t_else)
        if merge is not None:
            cond = self._condition_from_jump_if(header)

            # One-way forms where one arm directly acts as merge.
            if merge == t_else:
                then_ast = self._reduce_from(
                    t_then,
                    stop=merge,
                    barriers=barriers,
                    loop_nodes=loop_nodes,
                    break_target=break_target,
                    continue_target=continue_target,
                )
                return Node(self.dialect.ast_if, [cond, then_ast]), merge
            if merge == t_then:
                then_ast = self._reduce_from(
                    t_else,
                    stop=merge,
                    barriers=barriers,
                    loop_nodes=loop_nodes,
                    break_target=break_target,
                    continue_target=continue_target,
                )
                return (
                    Node(
                        self.dialect.ast_if,
                        [Node(self.dialect.ast_not, [cond]), then_ast],
                    ),
                    merge,
                )

            then_ast = self._reduce_from(
                t_then,
                stop=merge,
                barriers=barriers,
                loop_nodes=loop_nodes,
                break_target=break_target,
                continue_target=continue_target,
            )
            else_ast = self._reduce_from(
                t_else,
                stop=merge,
                barriers=barriers,
                loop_nodes=loop_nodes,
                break_target=break_target,
                continue_target=continue_target,
            )

            if not else_ast.children:
                return Node(self.dialect.ast_if, [cond, then_ast]), merge
            if not then_ast.children:
                return (
                    Node(
                        self.dialect.ast_if,
                        [Node(self.dialect.ast_not, [cond]), else_ast],
                    ),
                    merge,
                )
            return Node(self.dialect.ast_if, [cond, then_ast, else_ast]), merge

        return None, None

    def _find_switch_merge(self, targets: list[CFGNode]) -> CFGNode | None:
        if not targets:
            return None

        dist_maps = [self._forward_distances(target) for target in targets]

        terminating_cti_types = self.dialect.terminal_transfers
        productive_maps: list[dict[CFGNode, int]] = []
        for target, dist_map in zip(targets, dist_maps):
            cti_type = getattr(target.cti, "type", None)
            if cti_type in terminating_cti_types:
                continue
            has_nontrivial_successor = any(
                node != target and node != self._cfg.exit for node in dist_map.keys()
            )
            if has_nontrivial_successor:
                productive_maps.append(dist_map)

        # 如果所有分支都提前终止（throw/return），则不存在 merge。
        if not productive_maps:
            return None

        target_set = set(targets)

        # 先尝试严格公共汇合（所有 productive 分支交集）
        common_nodes = set(productive_maps[0].keys())
        for dist_map in productive_maps[1:]:
            common_nodes &= set(dist_map.keys())

        strict_candidates = [node for node in common_nodes if node not in target_set]
        strict_non_exit = [node for node in strict_candidates if node != self._cfg.exit]

        # 优先使用严格交集中的非 exit 候选。
        candidates = strict_non_exit

        # 若严格交集只剩 exit（或为空），退化到“少数服从多数”：至少被 2 个 productive 分支到达。
        if not candidates:
            reach_counts: dict[CFGNode, int] = {}
            for dist_map in productive_maps:
                for node in dist_map.keys():
                    if node in target_set or node == self._cfg.exit:
                        continue
                    reach_counts[node] = reach_counts.get(node, 0) + 1

            if reach_counts:
                max_reach = max(reach_counts.values())
                if max_reach >= 2:
                    candidates = [
                        node
                        for node, count in reach_counts.items()
                        if count == max_reach
                    ]

        # 若仍无候选，但严格交集含 exit，则退回 exit。
        if not candidates:
            if self._cfg.exit in strict_candidates:
                return self._cfg.exit
            return None

        ranked: list[tuple[int, int, str, CFGNode]] = []
        for cand in candidates:
            dists = [dist_map[cand] for dist_map in productive_maps if cand in dist_map]
            ranked.append((max(dists), sum(dists), str(cand.label), cand))

        ranked.sort(key=lambda item: (item[0], item[1], item[2]))
        return ranked[0][3]

    def _is_terminal_block(self, block: CFGNode) -> bool:
        cti = block.cti
        return type(cti) is Node and cti.type in self.dialect.terminal_transfers

    def _reduce_switch(
        self,
        block: CFGNode,
        barriers: set[CFGNode] | None = None,
    ) -> tuple[Node, CFGNode | None]:
        cti = block.cti
        expr = Node(self.dialect.ast_true)
        if type(cti) is Node:
            if len(cti.children) == 1 and type(cti.children[0]) is Node:
                expr = cti.children[0]
            elif (
                len(cti.children) > self.dialect.switch_expr_index
                and type(cti.children[self.dialect.switch_expr_index]) is Node
            ):
                expr = cti.children[self.dialect.switch_expr_index]

        targets = list(block.targets)
        merge = self._find_switch_merge(targets)
        body_children: list[Node] = []
        target_set = set(targets)
        inherited_barriers = set(barriers) if barriers is not None else set()
        base_visited = set(self._visited)
        switch_consumed: set[CFGNode] = set()

        # 将相同 target 的所有标签合并到第一次出现处，避免重复注入分支体。
        grouped_indices: dict[CFGNode, list[int]] = {}
        group_order: list[CFGNode] = []
        for label_index, target in enumerate(targets):
            if target not in grouped_indices:
                grouped_indices[target] = []
                group_order.append(target)
            grouped_indices[target].append(label_index)

        for target in group_order:
            label_indexes = grouped_indices[target]
            for label_index in label_indexes:
                label_meta = {
                    "switch_origin_order": label_index,
                    "switch_target_label": target.label,
                }
                if label_index == 0:
                    body_children.append(
                        Node(self.dialect.ast_default, metadata=label_meta)
                    )
                else:
                    body_children.append(
                        Node(
                            self.dialect.ast_case,
                            [Node(self.dialect.ast_integer, [label_index - 1])],
                            metadata=label_meta,
                        )
                    )

            case_barriers = set(target_set)
            case_barriers.discard(target)
            case_barriers.update(inherited_barriers)
            for sibling_target in target_set:
                if sibling_target is target:
                    continue
                if self._is_terminal_block(sibling_target):
                    case_barriers.discard(sibling_target)
            # Isolate case-arm reduction from sibling-arm visitation side effects.
            self._visited = set(base_visited)
            case_ast = self._reduce_from(target, stop=merge, barriers=case_barriers)
            switch_consumed.update(self._visited - base_visited)

            if case_ast.children and merge is not None:
                # 若 case 末尾是显式 jump 到 switch merge，将其规约为 break。
                last_stmt = case_ast.children[-1]
                if (
                    type(last_stmt) is Node
                    and last_stmt.type == self.dialect.jump
                    and last_stmt.children
                ):
                    jump_label = last_stmt.children[0]
                    jump_target: CFGNode | None
                    if type(jump_label) is CFGNode:
                        jump_target = jump_label
                    else:
                        try:
                            jump_target = self._cfg.find_node(jump_label)
                        except Exception:
                            jump_target = None
                    if jump_target == merge:
                        case_ast.children = case_ast.children[:-1] + [
                            Node(self.dialect.ast_break)
                        ]

            if case_ast.children:
                body_children.extend(case_ast.children)

            terminators = set(self.dialect.terminal_transfers) | {
                self.dialect.ast_break,
                self.dialect.ast_continue,
                self.dialect.jump,
            }
            has_case_terminator = any(
                type(node) is Node and node.type in terminators
                for node in case_ast.descendants()
            )
            # 对直达 merge 的分支，或缺失终止语义的分支，补显式 break，防止 fallthrough。
            if (merge is not None and target == merge) or (
                not has_case_terminator and target != self._cfg.exit
            ):
                body_children.append(Node(self.dialect.ast_break))

        self._visited = base_visited | switch_consumed

        switch_metadata = {
            "switch_source": self.dialect.switch_source,
            "switch_target_count": len(block.targets),
        }
        return (
            Node(
                self.dialect.ast_switch,
                [expr, Node(self.dialect.ast_begin, body_children)],
                metadata=switch_metadata,
            ),
            merge,
        )

    def _reduce_try_catch_finally(
        self,
        start_block: CFGNode,
        exc_label: Label,
        barriers: set[CFGNode] | None,
        loop_nodes: set[CFGNode] | None,
        break_target: CFGNode | None,
        continue_target: CFGNode | None,
    ) -> tuple[Node, CFGNode | None]:

        self._exc_processed.add(exc_label)

        try:
            dispatch_node = self._cfg.find_node(exc_label)
        except KeyError:
            return Node(self.dialect.ast_begin, []), None

        catch_defs: list[tuple[object, object, int | str | None]] = []
        for insn in dispatch_node.instructions:
            if type(insn) is Node and insn.type == self.dialect.exception_dispatch:
                for catch_child in insn.children:
                    if (
                        type(catch_child) is Node
                        and catch_child.type == self.dialect.catch
                    ):
                        exc_type = (
                            catch_child.children[0]
                            if len(catch_child.children) > 0
                            else None
                        )
                        var_name = (
                            catch_child.children[1]
                            if len(catch_child.children) > 1
                            else None
                        )
                        target_off = (
                            catch_child.children[2]
                            if len(catch_child.children) > 2
                            else None
                        )
                        catch_defs.append((exc_type, var_name, target_off))

        if not catch_defs:
            return Node(self.dialect.ast_begin, []), None

        try_region = {n for n in self._cfg.nodes if n.exception_label == exc_label}
        if not try_region:
            return Node(self.dialect.ast_begin, []), None

        try_barriers = set(barriers) if barriers else set()
        try_barriers.add(dispatch_node)

        try_ast = self._reduce_from(
            start_block,
            stop=None,
            barriers=try_barriers,
            loop_nodes=loop_nodes,
            break_target=break_target,
            continue_target=continue_target,
        )

        catch_asts: list[Node] = []
        finally_ast: Node | None = None
        continuation: CFGNode | None = None

        finally_block: CFGNode | None = None
        try_exit_nodes: list[CFGNode] = []
        for node in try_region:
            for tgt in node.targets:
                if tgt not in try_region and tgt is not dispatch_node:
                    try_exit_nodes.append(node)
                    break
        if try_exit_nodes and catch_defs:
            first_catch_target = catch_defs[0][2]
            try:
                first_catch_entry = self._cfg.find_node(first_catch_target)
            except KeyError:
                first_catch_entry = None
            if first_catch_entry is not None:
                merge = self._find_merge_node(try_exit_nodes[0], first_catch_entry)
                if merge is not None and merge not in set(try_exit_nodes) | {
                    first_catch_entry,
                    dispatch_node,
                }:
                    finally_block = self._detect_finally_block(
                        merge, try_region, dispatch_node
                    )

        for exc_type, var_name, target_off in catch_defs:
            try:
                catch_entry = self._cfg.find_node(target_off)
            except KeyError:
                continue

            catch_stop = finally_block if finally_block is not None else None

            prev_suppress = getattr(self, "_suppress_exc", False)
            self._suppress_exc = True
            catch_body = self._reduce_from(
                catch_entry,
                stop=catch_stop,
                barriers=barriers,
                loop_nodes=loop_nodes,
                break_target=break_target,
                continue_target=continue_target,
            )
            self._suppress_exc = prev_suppress

            type_str = str(exc_type) if exc_type is not None else "*"
            name_str = str(var_name) if var_name is not None else "_e_"
            catch_asts.append(
                Node(self.dialect.ast_catch, [type_str, name_str, catch_body])
            )

            if continuation is None and finally_block is None:
                continuation = self._find_finally_merge_point(
                    try_region, catch_entry, dispatch_node
                )

        if finally_block is not None:
            self._visited.discard(finally_block)
            finally_body = self._reduce_from(
                finally_block,
                stop=None,
                barriers=barriers,
                loop_nodes=loop_nodes,
                break_target=break_target,
                continue_target=continue_target,
            )
            finally_ast = Node(self.dialect.ast_finally, [finally_body])
            continuation = self._find_post_finally_continuation(finally_block)

        try_children = [try_ast] + catch_asts
        if finally_ast is not None:
            try_children.append(finally_ast)

        return Node(self.dialect.ast_try, try_children), continuation

    def _find_finally_merge_point(
        self,
        try_region: set[CFGNode],
        catch_entry: CFGNode,
        dispatch_node: CFGNode,
    ) -> CFGNode | None:
        try_exit_nodes = []
        for node in try_region:
            for tgt in node.targets:
                if tgt not in try_region and tgt is not dispatch_node:
                    try_exit_nodes.append(node)
                    break
        if not try_exit_nodes:
            return None
        input_nodes = set(try_exit_nodes) | {catch_entry, dispatch_node}
        merge = self._find_merge_node(try_exit_nodes[0], catch_entry)
        if merge is not None and merge not in input_nodes:
            return merge
        return None

    def _detect_finally_block(
        self,
        candidate: CFGNode,
        try_region: set[CFGNode],
        dispatch_node: CFGNode,
    ) -> CFGNode | None:
        if candidate is dispatch_node or candidate in try_region:
            return None
        cti = candidate.cti
        if type(cti) is not Node:
            return None
        if cti.type != self.dialect.switch_source:
            return None
        if len(candidate.sources) < 2:
            return None
        return candidate

    def _find_post_finally_continuation(self, finally_block: CFGNode) -> CFGNode | None:
        cti = finally_block.cti
        if type(cti) is not Node:
            return None
        terminals = self.dialect.terminal_transfers
        for tgt in finally_block.targets:
            if type(tgt.cti) is Node and tgt.cti.type in terminals:
                continue
            if tgt is self._cfg.exit:
                continue
            return tgt
        return None
