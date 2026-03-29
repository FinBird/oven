from __future__ import annotations

from typing import Any

from oven.core.pipeline import Transform
from oven.core.ast import NodeVisitor, Node, m


class NFNormalize(Transform, NodeVisitor):
    """
    Normal Form Normalization Transformation.
    Refactored from Furnace::AVM2::Transform::NFNormalize.
    """

    def transform(self, *args: Any) -> Any:
        if not args:
            return args

        nf = args[0]
        if isinstance(nf, Node):
            # Normalize hierarchy to ensure parent pointers are valid for upward search
            nf.normalize_hierarchy()
            self.nf = nf

            self._remove_useless_return()
            self.visit(nf)

            if len(args) == 1:
                return self.nf

            return self.nf, *args[1:]


        return args

    def _remove_useless_return(self) -> None:
        if self.nf.children and isinstance(self.nf.children[-1], Node):
            if self.nf.children[-1].type == "return_void":
                self.nf.children.pop()

    def on_nop(self, node: Node) -> None:
        node.update(node_type="remove")

    # =========================================================================
    # Local Increment/Decrement Optimization
    # =========================================================================

    LocalIncDecMatcher = m.seq(
        m.one_of(
            m.of("set_slot", m.capture("index"), m.capture("scope")),
            m.of("set_local", m.capture("index")),
        ),
        m.one_of(
            m.of("convert", m.any, m.capture("inner")),
            m.of("coerce", "any", m.capture("inner")),
            m.capture("inner")
        )
    )

    LocalIncDecInnerMatcher = m.seq(
        m.capture("operator"),
        m.one_of(
            m.of("convert", m.any, m.capture("getter")),
            m.capture("getter")
        )
    )

    LocalIncDecGetterMatcher = m.one_of(
        m.of("get_slot", m.backref("index"), m.backref("scope")),
        m.of("get_local", m.backref("index"))
    )

    IncDecOperators = {
        "pre_increment", "post_increment",
        "pre_decrement", "post_decrement"
    }

    def _extract_local_incdec_captures(self, node: Node) -> dict[str, Any] | None:
        captures: dict[str, Any] = {}
        if not self.LocalIncDecMatcher.match(node.children, captures):
            return None

        inner = captures.get("inner")
        if not isinstance(inner, Node):
            return None

        if not self.LocalIncDecInnerMatcher.match(inner.children, captures):
            return None

        operator = captures.get("operator")
        if isinstance(operator, Node):
            operator_type = operator.type
        else:
            operator_type = str(operator)

        if operator_type not in self.IncDecOperators:
            return None

        captures["operator_type"] = operator_type
        return captures

    def on_set_local(self, node: Node) -> None:
        if len(node.children) >= 2:
            val = node.children[1]
            if isinstance(val, Node) and val.type == "catch_scope_object":
                node.update(node_type="remove")
                return

        captures = self._extract_local_incdec_captures(node)
        if captures is None:
            return

        getter = captures["getter"]
        operator_type = str(captures["operator_type"])

        # Check if the getter matches the setter (e.g. i = i + 1)
        if (isinstance(getter, Node) and
                self.LocalIncDecGetterMatcher.match(getter, captures)):

            target_type = f"{operator_type}_slot" if "scope" in captures else f"{operator_type}_local"

            children = [captures["index"]]
            if "scope" in captures:
                children.append(captures["scope"])

            node.update(node_type=target_type, children=children)
        else:
            # Fallback for non-canonical inc/dec form:
            # rebuild as add(set_local(..., getter), integer(1)).
            set_node_type = node.type  # set_local or set_slot
            # Build children for the nested set node: [index, (scope?), getter].

            set_children = [captures["index"]]
            if "scope" in captures:
                set_children.append(captures["scope"])

            # Append the value being assigned.
            set_children.append(getter)

            new_set_node = Node(set_node_type, children=set_children)

            node.update(node_type="add", children=[
                new_set_node,
                Node("integer", children=[1])
            ])

    # Alias on_set_slot to use the same logic
    on_set_slot = on_set_local

    # =========================================================================
    # Loop Expansion (if -> while)
    # =========================================================================

    ExpandedForInMatcher = m.of("if",
                                m.of("has_next2", m.skip()),
                                m.skip()
                                )

    def on_if(self, node: Node) -> None:
        if self.ExpandedForInMatcher.match(node, {}):
            # (if (has_next2 ...) body rest...)
            condition = node.children[0]
            body = node.children[1]
            # rest are subsequent children if any (Ruby: `condition, body, rest = node.children`)
            # But Ruby destructuring `rest` captures just the 3rd element or nil if strictly 3?
            # Ruby: `condition, body, rest = node.children` assigns rest to the 3rd element.
            rest = node.children[2] if len(node.children) > 2 else None

            # Append 'break' to the body block
            if isinstance(body, Node):
                body.children.append(Node("break"))

            loop_node = Node("while", children=[condition, body])

            # Manually trigger on_while transformation for the newly created loop
            self.on_while(loop_node, parent=node.parent, enclosure=node)

            new_children = [loop_node]

            # If there was a 'else' block or subsequent instructions (in the `if` node children)
            # The Ruby code `if rest node.update(:expand, [ loop ] + rest.children)`
            # assumes `rest` is a Block/Node containing instructions.
            if isinstance(rest, Node):
                # If rest is a block-like node, we flatten it?
                # Ruby: `rest.children` implies it's expanding a block.
                new_children.extend(rest.children)
            elif rest is not None:
                new_children.append(rest)

            node.update(node_type="expand", children=new_children)

    # =========================================================================
    # For-In / For-Each-In Reconstruction
    # =========================================================================

    ForInMatcher = m.of("while",
                        m.of("has_next2", m.capture("object_reg"), m.capture("index_reg")),
                        m.of("begin",
                             m.seq(
                                 m.one_of(
                                     m.of("set_local", m.capture("value_reg")),
                                     m.of("set_slot", m.capture("value_reg"), m.of("get_scope_object", m.eq(1)))
                                 ),
                                 m.seq(
                                     m.one_of(m.of("coerce"), m.of("convert")),
                                     m.capture("value_type"),
                                     m.seq(
                                         m.capture("iterator"),  # next_name or next_value
                                         m.of("get_local", m.backref("object_reg")),
                                         m.of("get_local", m.backref("index_reg"))
                                     )
                                 ),
                                 m.rest("body")
                             )
                             )
                        )

    ForInIndexMatcher = m.of("set_local", m.backref("index_reg"), m.of("integer", m.eq(0)))

    ForInObjectMatcher = m.of("set_local", m.backref("object_reg"),
                              m.of("coerce", "any", m.capture("root"))
                              )

    SuperfluousContinueMatcher = m.of("continue")

    _LOCAL_OPS = {
        "get_local",
        "set_local",
        "inc_local",
        "inc_local_i",
        "dec_local",
        "dec_local_i",
        "pre_increment_local",
        "post_increment_local",
        "pre_decrement_local",
        "post_decrement_local",
        "kill",
    }

    _LOCAL_WRITE_OPS = {
        "set_local",
        "inc_local",
        "inc_local_i",
        "dec_local",
        "dec_local_i",
        "pre_increment_local",
        "post_increment_local",
        "pre_decrement_local",
        "post_decrement_local",
        "kill",
    }

    _IGNORABLE_FLOW_TYPES = {"nop", "label"}

    @staticmethod
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

    def _unwrap_convert_chain(self, value: object) -> object:
        current = value
        while isinstance(current, Node):
            if current.type == "coerce" and len(current.children) >= 2:
                current = current.children[-1]
                continue
            if current.type == "convert" and len(current.children) >= 2:
                current = current.children[-1]
                continue
            if current.type == "coerce_b" and current.children:
                current = current.children[-1]
                continue
            if current.type in {"convert_i", "convert_u", "convert_d", "convert_s", "convert_o"} and current.children:
                current = current.children[-1]
                continue
            break
        return current

    def _extract_value_type_and_inner(self, value: object) -> tuple[object, object]:
        current = value
        extracted_type: object = "any"
        while isinstance(current, Node):
            if current.type == "coerce" and len(current.children) >= 2:
                if extracted_type == "any":
                    extracted_type = current.children[0]
                current = current.children[-1]
                continue
            if current.type == "convert" and len(current.children) >= 2:
                if extracted_type == "any":
                    extracted_type = current.children[0]
                current = current.children[-1]
                continue
            if current.type == "coerce_b" and current.children:
                if extracted_type == "any":
                    extracted_type = "Boolean"
                current = current.children[-1]
                continue
            if current.type == "convert_i" and current.children:
                if extracted_type == "any":
                    extracted_type = "int"
                current = current.children[-1]
                continue
            if current.type == "convert_u" and current.children:
                if extracted_type == "any":
                    extracted_type = "uint"
                current = current.children[-1]
                continue
            if current.type == "convert_d" and current.children:
                if extracted_type == "any":
                    extracted_type = "Number"
                current = current.children[-1]
                continue
            if current.type == "convert_s" and current.children:
                if extracted_type == "any":
                    extracted_type = "String"
                current = current.children[-1]
                continue
            if current.type == "convert_o" and current.children:
                current = current.children[-1]
                continue
            break
        return extracted_type, current

    def _match_alias_assignment(self, node: Node, alias_map: dict[int, int]) -> bool:
        if node.type != "set_local" or len(node.children) < 2:
            return False
        target = self._index_value(node.children[0])
        if target is None:
            return False
        rhs = self._unwrap_convert_chain(node.children[1])
        if not isinstance(rhs, Node) or rhs.type != "get_local" or not rhs.children:
            return False
        source = self._index_value(rhs.children[0])
        if source is None or source not in alias_map:
            return False
        alias_map[target] = alias_map[source]
        return True

    def _extract_reg_reference(self, value: object, alias_map: dict[int, int]) -> int | None:
        inner = self._unwrap_convert_chain(value)
        if not isinstance(inner, Node) or inner.type != "get_local" or not inner.children:
            return None
        source = self._index_value(inner.children[0])
        if source is None:
            return None
        return alias_map.get(source, source)

    def _extract_loop_value_assignment(
        self,
        stmt: object,
        object_reg: int,
        index_reg: int,
        alias_map: dict[int, int],
    ) -> tuple[object, object, str] | None:
        if not isinstance(stmt, Node):
            return None

        if stmt.type == "set_local" and len(stmt.children) >= 2:
            value_reg = stmt.children[0]
            rhs = stmt.children[1]
        elif stmt.type == "set_slot" and len(stmt.children) >= 3:
            scope = stmt.children[1]
            if not (isinstance(scope, Node) and scope.type == "get_scope_object" and scope.children and scope.children[0] == 1):
                return None
            value_reg = stmt.children[0]
            rhs = stmt.children[2]
        else:
            return None

        value_type, inner = self._extract_value_type_and_inner(rhs)
        if not isinstance(inner, Node) or inner.type not in {"next_name", "next_value"} or len(inner.children) < 2:
            return None

        obj_ref = self._extract_reg_reference(inner.children[0], alias_map)
        idx_ref = self._extract_reg_reference(inner.children[1], alias_map)
        if obj_ref != object_reg or idx_ref != index_reg:
            return None

        return value_reg, value_type, inner.type

    def _extract_for_in_captures(self, loop: Node) -> dict[str, object] | None:
        if loop.type != "while" or len(loop.children) < 2:
            return None
        condition = loop.children[0]
        body = loop.children[1]
        if not (isinstance(condition, Node) and condition.type == "has_next2" and len(condition.children) >= 2):
            return None
        if not isinstance(body, Node):
            return None

        object_reg = self._index_value(condition.children[0])
        index_reg = self._index_value(condition.children[1])
        if object_reg is None or index_reg is None:
            return None

        statements = list(body.children)
        if not statements:
            return None

        alias_map = {object_reg: object_reg, index_reg: index_reg}
        assignment_pos = 0
        while assignment_pos < len(statements):
            stmt = statements[assignment_pos]
            if not isinstance(stmt, Node) or not self._match_alias_assignment(stmt, alias_map):
                break
            assignment_pos += 1

        if assignment_pos >= len(statements):
            return None

        assignment = self._extract_loop_value_assignment(
            statements[assignment_pos],
            object_reg=object_reg,
            index_reg=index_reg,
            alias_map=alias_map,
        )
        if assignment is None:
            return None

        value_reg, value_type, iterator_type = assignment
        return {
            "object_reg": object_reg,
            "index_reg": index_reg,
            "iterator": iterator_type,
            "value_reg": value_reg,
            "value_type": value_type,
            "body": statements[assignment_pos + 1:],
        }

    def _node_mentions_local(self, node: Node, local_index: int) -> bool:
        stack = [node]
        while stack:
            current = stack.pop()
            if current.type in self._LOCAL_OPS and current.children:
                idx = self._index_value(current.children[0])
                if idx == local_index:
                    return True
            elif current.type == "has_next2" and len(current.children) >= 2:
                obj_idx = self._index_value(current.children[0])
                key_idx = self._index_value(current.children[1])
                if obj_idx == local_index or key_idx == local_index:
                    return True
            elif current.type in {"for_in", "for_each_in"}:
                if len(current.children) > 0 and self._index_value(current.children[0]) == local_index:
                    return True
                if len(current.children) > 2 and self._index_value(current.children[2]) == local_index:
                    return True

            for child in current.children:
                if isinstance(child, Node):
                    stack.append(child)
        return False

    def _has_extra_local_use(self, parent: Node, local_index: int, excluded_nodes: set[Node]) -> bool:
        for sibling in parent.children:
            if sibling in excluded_nodes:
                continue
            if isinstance(sibling, Node) and self._node_mentions_local(sibling, local_index):
                return True
        return False

    def _clone_tree(self, value: object) -> object:
        if isinstance(value, Node):
            return Node(
                value.type,
                [self._clone_tree(child) for child in value.children],
                dict(value.metadata),
            )
        return value

    def _is_ignorable_flow_stmt(self, stmt: object) -> bool:
        return isinstance(stmt, Node) and stmt.type in self._IGNORABLE_FLOW_TYPES

    def _is_local_write_stmt(self, stmt: object, local_index: int) -> bool:
        if not isinstance(stmt, Node):
            return False
        if stmt.type not in self._LOCAL_WRITE_OPS or not stmt.children:
            return False
        return self._index_value(stmt.children[0]) == local_index

    def _extract_update_local_index(self, stmt: object) -> int | None:
        if not isinstance(stmt, Node):
            return None

        if stmt.type in {
            "post_increment_local",
            "pre_increment_local",
            "post_decrement_local",
            "pre_decrement_local",
            "inc_local",
            "inc_local_i",
            "dec_local",
            "dec_local_i",
        } and stmt.children:
            return self._index_value(stmt.children[0])

        if stmt.type == "set_local" and len(stmt.children) >= 2:
            local_index = self._index_value(stmt.children[0])
            if local_index is None:
                return None
            rhs = stmt.children[1]
            if not isinstance(rhs, Node) or len(rhs.children) < 2:
                return None

            if rhs.type in {"add", "add_i", "subtract", "subtract_i"}:
                left = self._extract_reg_reference(rhs.children[0], {local_index: local_index})
                right = self._extract_reg_reference(rhs.children[1], {local_index: local_index})
                left_num = self._index_value(rhs.children[0])
                right_num = self._index_value(rhs.children[1])

                if left == local_index and right_num in {1, -1}:
                    return local_index
                if right == local_index and left_num in {1, -1}:
                    return local_index

        return None

    def _condition_mentions_local(self, value: object, local_index: int) -> bool:
        if not isinstance(value, Node):
            return False
        stack = [value]
        while stack:
            current = stack.pop()
            if current.type == "get_local" and current.children:
                if self._index_value(current.children[0]) == local_index:
                    return True
            if current.type == "has_next2" and len(current.children) >= 2:
                if self._index_value(current.children[0]) == local_index:
                    return True
                if self._index_value(current.children[1]) == local_index:
                    return True
            for child in current.children:
                if isinstance(child, Node):
                    stack.append(child)
        return False

    def _recover_for_loop(self, node: Node, parent: Node, enclosure: Node) -> bool:
        if node.type != "while" or len(node.children) < 2:
            return False

        condition = node.children[0]
        body = node.children[1]
        if isinstance(condition, Node) and condition.type == "has_next2":
            # Iterator loops must be handled by for-in/for-each reconstruction,
            # never by generic counter-loop recovery.
            return False
        if not isinstance(body, Node) or body.type != "begin" or not body.children:
            return False

        update_stmt: Node | None = None
        update_pos = -1
        local_index: int | None = None

        for idx in range(len(body.children) - 1, -1, -1):
            candidate = body.children[idx]
            if self._is_ignorable_flow_stmt(candidate):
                continue
            if isinstance(candidate, Node) and candidate.type == "continue":
                # `continue` can legally trail canonical update in lowered IR.
                continue

            detected_index = self._extract_update_local_index(candidate)
            if detected_index is None:
                return False
            update_stmt = candidate if isinstance(candidate, Node) else None
            update_pos = idx
            local_index = detected_index
            break

        if update_stmt is None or update_pos < 0 or local_index is None:
            return False

        if not self._condition_mentions_local(condition, local_index):
            return False

        try:
            loop_index = parent.children.index(enclosure)
        except ValueError:
            return False

        init_stmt: Node | None = None
        for idx in range(loop_index - 1, -1, -1):
            sibling = parent.children[idx]
            if self._is_ignorable_flow_stmt(sibling):
                continue
            if not isinstance(sibling, Node):
                return False
            if sibling.type == "set_local" and len(sibling.children) >= 2 and self._index_value(sibling.children[0]) == local_index:
                init_stmt = sibling
                break
            if self._is_local_write_stmt(sibling, local_index):
                return False
            return False

        if init_stmt is None:
            return False

        init_clone = self._clone_tree(init_stmt)
        update_clone = self._clone_tree(update_stmt)

        del body.children[update_pos]
        init_stmt.update(node_type="remove")

        metadata = dict(node.metadata)
        metadata["for_init"] = init_clone
        metadata["for_update"] = update_clone
        node.update(metadata=metadata)
        return True

    def on_while(self, node: Node, parent: Node | None = None, enclosure: Node | None = None) -> None:
        parent = parent or node.parent
        enclosure = enclosure or node

        if not parent:
            return

        # 1. Remove superfluous continue at end of body
        # node.children: [*whatever, code]
        if node.children:
            code = node.children[-1]
            if isinstance(code, Node) and code.children:
                last_stmt = code.children[-1]
                if self.SuperfluousContinueMatcher.match(last_stmt, {}):
                    code.children.pop()

        # 1.5 Recover canonical for(init; cond; update) from while when safe.
        if self._recover_for_loop(node, parent, enclosure):
            return

        # 2. Match For-In Pattern
        captures: dict[str, object] = {}
        if self.ForInMatcher.match(node, captures):
            pass
        else:
            inferred = self._extract_for_in_captures(node)
            if inferred is None:
                return
            captures = inferred

        if captures:
            iterator_type = captures["iterator"]
            if isinstance(iterator_type, Node):
                iterator_type = iterator_type.type

            if iterator_type == "next_name":
                loop_type = "for_in"
            elif iterator_type == "next_value":
                loop_type = "for_each_in"
            else:
                return

            object_reg = self._index_value(captures.get("object_reg"))
            index_reg = self._index_value(captures.get("index_reg"))
            if object_reg is None or index_reg is None:
                return

            index_node: Node | None = None
            object_node: Node | None = None

            # Look backwards in parent children to find initialization
            try:
                loop_index = parent.children.index(enclosure)
            except ValueError:
                return

            # Scan backwards from loop_index
            for i in range(loop_index, -1, -1):
                sibling = parent.children[i]
                if isinstance(sibling, Node):
                    if self.ForInIndexMatcher.match(sibling, captures):
                        index_node = sibling
                    elif self.ForInObjectMatcher.match(sibling, captures):
                        object_node = sibling

                if index_node and object_node:
                    break

            if not (index_node and object_node):
                return

            excluded = {enclosure, index_node, object_node}

            # Mark initialization nodes for removal only when they are not
            # used by any sibling statement outside the loop reconstruction.
            if not self._has_extra_local_use(parent, index_reg, excluded):
                index_node.update(node_type="remove")
            if (
                loop_type != "for_each_in"
                and not self._has_extra_local_use(parent, object_reg, excluded)
            ):
                object_node.update(node_type="remove")

            # Update loop node
            node.update(node_type=loop_type, children=[
                captures["value_reg"],
                captures["value_type"],
                object_reg,
                Node("begin", children=captures["body"])
            ])

    # =========================================================================
    # Scope Folding (with) & Dead Code Removal
    # =========================================================================

    def on_begin(self, node: Node) -> None:
        # 1. Fold (with) blocks
        # Find index of :push_with
        with_begin = -1
        for i, child in enumerate(node.children):
            if isinstance(child, Node) and child.type == "push_with":
                with_begin = i
                break

        with_end = -1

        if with_begin != -1:
            nesting = 0
            # iterate from with_begin to end
            for i in range(with_begin, len(node.children)):
                child = node.children[i]
                if isinstance(child, Node):
                    if child.type in ("push_with", "push_scope"):
                        nesting += 1
                    elif child.type == "pop_scope":
                        nesting -= 1
                        if nesting == 0:
                            with_end = i
                            break

            if nesting == 0 and with_end != -1:
                # Ruby: with_scope, = node.children[with_begin].children
                with_stmt = node.children[with_begin]
                with_scope = with_stmt.children[0] if with_stmt.children else None

                # Ruby: slice (with_begin + 1)..(with_end - 1)
                # Python slice is [start : end] (exclusive)
                with_content = node.children[with_begin + 1: with_end]

                with_node = Node("with", children=[
                    with_scope,
                    Node("begin", children=with_content)
                ])

                # Replace range [with_begin .. with_end] with new node
                # Python slice assignment: node.children[start : end+1]
                node.children[with_begin: with_end + 1] = [with_node]

        # 2. Remove obviously dead code
        # Switch bodies are represented as a flat begin-block that interleaves
        # labels and statements. Trimming everything after the first terminal
        # would incorrectly delete subsequent case/default sections.
        has_switch_labels = any(
            isinstance(child, Node) and child.type in {"case", "default"}
            for child in node.children
        )
        if has_switch_labels:
            return

        dead_types = {"return_void", "return_value", "break", "continue", "throw"}
        first_ctn = -1
        for i, child in enumerate(node.children):
            if isinstance(child, Node) and child.type in dead_types:
                first_ctn = i
                break

        if first_ctn != -1:
            # Remove everything after the flow control instruction
            del node.children[first_ctn + 1:]

    # =========================================================================
    # Switch Optimization
    # =========================================================================

    OptimizedSwitchSeed = m.of("ternary",
                               m.of("===", m.capture("case_value"), m.of("get_local", m.capture("local_index"))),
                               m.of("integer", m.capture("case_index")),
                               m.capture("nested")
                               )

    OptimizedSwitchNested = m.one_of(
        m.of("ternary",
             m.of("===", m.capture("case_value"), m.of("get_local", m.backref("local_index"))),
             m.of("integer", m.capture("case_index")),
             m.capture("nested")
             ),
        m.of("integer", m.capture("default_index"))
    )

    NumericCase = m.of("case", m.of("integer", m.capture("index")))

    def _prune_unreachable_inside_switch_body(self, body: Node) -> None:
        if body.type != "begin":
            return

        labels = {"case", "default"}
        terminals = {"break", "continue", "return_value", "return_void", "throw"}
        children = body.children
        if not children:
            return

        pruned: list[Any] = []
        branch_live = True
        for child in children:
            if isinstance(child, Node) and child.type in labels:
                branch_live = True
                pruned.append(child)
                continue

            if not branch_live:
                continue

            pruned.append(child)
            if isinstance(child, Node) and child.type in terminals:
                branch_live = False

        body.children = pruned

    def on_switch(self, node: Node) -> None:
        if len(node.children) < 2:
            return

        condition = node.children[0]
        body = node.children[1]

        captures = {}
        # 1. Match the seed (root ternary)
        if self.OptimizedSwitchSeed.match(condition, captures):
            mapping = {captures["case_index"]: captures["case_value"]}

            # 2. Traverse nested ternaries
            current_nested = captures["nested"]
            while True:
                # Need to clear/update captures for recursive match,
                # but preserve 'local_index' for backref check.
                # Since Matcher accumulates captures, we are fine passing the dict.
                if self.OptimizedSwitchNested.match(current_nested, captures):
                    if "default_index" in captures:
                        # Reached the leaf (default case)
                        break

                    # Found another case
                    mapping[captures["case_index"]] = captures["case_value"]
                    # Clean up 'case_index'/'case_value' from captures to avoid pollution?
                    # The Matcher overwrites keys, so it's generally fine,
                    # but we must ensure we are reading the *new* values.
                    # Move to next nested level
                    current_nested = captures["nested"]
                    # Clean ephemeral captures that define the step
                    del captures["case_index"]
                    del captures["case_value"]
                    del captures["nested"]
                else:
                    # Structure mismatch
                    return

            default_index = captures.get("default_index")
            case_mapping: dict[Node, Any] = {}

            # 3. Map switch body cases to values
            for child in body.children:
                # We need a fresh capture dict for checking the Case node
                case_caps = {}
                if self.NumericCase.match(child, case_caps):
                    case_idx = case_caps["index"]

                    if default_index == case_idx:
                        # Mark for removal
                        case_mapping[child] = None
                    elif case_idx in mapping:
                        # Map to value
                        case_mapping[child] = mapping[case_idx]
                    else:
                        # Fallback: found a case index not in our ternary map
                        return

            # 4. Transform
            # Replace condition with get_local
            node.children[0] = Node("get_local", children=[captures["local_index"]])

            # Update body children
            # Since we are iterating and modifying, we construct a new list
            new_body_children = []
            for child in body.children:
                if child in case_mapping:
                    val = case_mapping[child]
                    if val is None:
                        # Remove default case (matches default_index logic in Ruby code)
                        continue
                    else:
                        # Update case value (child is Node("case", [integer]))
                        # We want Node("case", [value])
                        child.children[0] = val
                new_body_children.append(child)

            body.children = new_body_children

        if isinstance(body, Node):
            self._prune_unreachable_inside_switch_body(body)

if __name__ == "__main__":
    def print_diff(title: str, original: Node, transformed: Node) -> None:
        print(f"\n{'=' * 10} {title} {'=' * 10}")
        print(f"[Before]: {original.to_sexp()}")
        print(f"[After] : {transformed.to_sexp()}")


    def example_useless_return() -> None:
        """Example 1: remove trailing return_void in function body."""
        # Build AST: (function (begin (instruction) (return_void)))
        # NFNormalize works on the top-level body node.

        code_body = Node("begin", children=[
            Node("get_local", children=[0]),
            Node("push_scope"),
            Node("return_void")  # This trailing return is removable.
        ])

        # Keep a root reference used by remove_useless_return.
        root = code_body

        normalizer = NFNormalize()

        # Execute transform in-place.
        normalizer.transform(root)

        print_diff("Remove Useless Return",
                   Node("begin", children=[Node("get_local"), Node("push_scope"), Node("return_void")]),
                   root)


    def example_dead_code_and_with() -> None:
        """Example 2: fold with-scope and remove dead code after return."""
        # Scenario:
        # 1. push_with ... pop_scope should fold into a single with node.
        # 2. Nodes after return_void should be removed.
        scope_object = Node("get_scope_object", children=[1])

        ast = Node("begin", children=[
            # --- With Block Start ---
            Node("push_with", children=[scope_object]),

            Node("call_something"),

            Node("pop_scope"),
            # --- With Block End ---

            Node("return_void"),  # Control-flow stop point.

            Node("dead_code_1"),  # All following nodes are dead code.
            Node("dead_code_2")
        ])

        print(f"\n{'=' * 10} Dead Code & With Folding {'=' * 10}")
        print(f"[Before]:\n{ast.to_sexp()}")

        normalizer = NFNormalize()
        normalizer.transform(ast)

        print(f"\n[After]:\n{ast.to_sexp()}")
        # Expected shape:
        # (begin
        #   (with (get_scope_object 1))
        #   (call_something)
        #   (return_void))

    example_useless_return()
    example_dead_code_and_with()
