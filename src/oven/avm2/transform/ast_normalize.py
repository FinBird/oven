from __future__ import annotations

from typing import Any
from oven.core.pipeline import Transform, Pipeline
from oven.core.ast import NodeVisitor, Node


class ASTNormalize(Transform[Any, Any], NodeVisitor):
    """
    AST Normalization Transformation.
    Refactored from Furnace::AVM2::Transform::ASTNormalize (Ruby).
    """

    IF_MAPPING: dict[str, tuple[bool, str]] = {
        "eq": (False, "=="),
        "ne": (False, "!="),
        "ge": (False, ">="),
        "nge": (True, ">="),
        "gt": (False, ">"),
        "ngt": (True, ">"),
        "le": (False, "<="),
        "nle": (True, "<="),
        "lt": (False, "<"),
        "nlt": (True, "<"),
        "strict_eq": (False, "==="),
        "strict_ne": (True, "==="),
        "true": (False, "expand"),
        "false": (True, "expand"),
    }

    def __init__(self, options: dict[str, Any] | None = None) -> None:
        self.options = options or {}

    def transform(self, *args: Any) -> Any:
        """
        Entry point for the pipeline.
        Expects args[0] to be the AST.
        Returns (ast, *rest).
        """
        if not args:
            return args

        ast = args[0]
        if isinstance(ast, Node):
            self.visit(ast)
            # Remove trailing return_void from method bodies
            self._remove_trailing_returns(ast)

        if len(args) == 1:
            return ast

        return args

    def _remove_trailing_returns(self, node: Node) -> None:
        """Remove trailing return_void statements from the end of begin blocks."""
        if node.type == "begin" and node.children:
            # Check if the last child is a return_void
            last_child = node.children[-1]
            if isinstance(last_child, Node) and last_child.type == "return_void":
                # Remove the trailing return_void
                node.children.pop()
        # Recursively process all child nodes
        for child in node.children:
            if isinstance(child, Node):
                self._remove_trailing_returns(child)

    # (pop x) -> (expand x (nop))
    def on_pop(self, node: Node) -> None:
        child = node.children[0]

        # Special case: pop(delete(...)) -> delete(...) as statement
        if isinstance(child, Node) and child.type == "delete":
            # Replace pop with the delete node directly
            node.update(
                node_type="delete", children=child.children, metadata=child.metadata
            )
            return

        # Create a NOP node copying metadata from the current node
        nop_node = Node("nop", metadata=node.metadata.copy())

        node.update(node_type="expand", children=[child, nop_node])

    # (call-property-void *) -> (call-property *)
    def on_call_property_void(self, node: Node) -> None:
        node.update(node_type="call_property")

    # (call-super-void *) -> (call-super *)
    def on_call_super_void(self, node: Node) -> None:
        node.update(node_type="call_super")

    def _transform_conditional(self, node: Node, comp: str, reverse: bool) -> None:
        node.update(node_type=comp)
        if reverse and node.parent:
            # Assuming the first child of the parent is the boolean flag
            # (standard for jump_if / ternary_if_boolean in this IR)
            # We toggle the boolean flag.
            current_flag = node.parent.children[0]
            if isinstance(current_flag, bool):
                node.parent.children[0] = not current_flag

    def _handle_if_logic(self, node: Node, reverse: bool, comp: str) -> None:
        parent = node.parent

        # Case 1: Parent is a conditional (jump_if) or explicit comparison
        if parent and (parent.type == "jump_if" or comp != "expand"):
            self._transform_conditional(node, comp, reverse)

        # Case 2: Parent is a ternary operator without comparison logic yet,
        # and this node is in the condition position (index 1).
        elif parent and parent.type == "ternary_if" and node.index_in_parent == 1:
            self._transform_conditional(node, comp, reverse)
            parent.update(node_type="ternary_if_boolean")

        # Case 3: Implicit comparison (expression context).
        # Convert to ternary_if_boolean explicitly.
        elif len(node.children) == 2:
            # In Ruby: node.update(:ternary_if_boolean, [ !comp, *node.children ])
            # !comp implies False if comp is a symbol/string.
            # We use `not comp` effectively passing False.
            new_children = [not comp] + list(node.children)
            node.update(node_type="ternary_if_boolean", children=new_children)

            # Immediately visit the new structure
            self.on_ternary_if_boolean(node)

        else:
            self._transform_conditional(node, comp, reverse)

    def __getattr__(self, name: str) -> Any:
        """
        Dynamic dispatch for on_if_* methods to avoid Setattr and boilerplate.
        """
        if name.startswith("on_if_"):
            key = name[6:]  # strip "on_if_"
            if key in self.IF_MAPPING:
                reverse, comp = self.IF_MAPPING[key]
                # Return a closure bound to the specific configuration
                return lambda node: self._handle_if_logic(node, reverse, comp)

        raise AttributeError(
            f"'{type(self).__name__}' object has no attribute '{name}'"
        )

    # (ternary-if * (op a b x y)) -> (ternary-if-boolean * (op a b) x y)
    def on_ternary_if(self, node: Node) -> None:
        # children: [comparison_bool, op_node]
        if len(node.children) < 2:
            return

        op = node.children[1]

        # Move children from op (index 2 onwards) to the ternary node
        # Ruby: node.children.concat op.children.slice!(2..-1)
        if isinstance(op, Node):
            moved_children = op.children[2:]
            op.children = op.children[:2]
            node.children.extend(moved_children)

        self.on_ternary_if_boolean(node)

    # (ternary-if-boolean true  (op a b) x y) -> (ternary (op a b) x y)
    # (ternary-if-boolean false (op a b) x y) -> (ternary (op a b) y x)
    def on_ternary_if_boolean(self, node: Node) -> None:
        children = node.children
        # Safely unpack potentially incomplete child layouts.
        comparison = children[0] if len(children) > 0 else None
        condition = children[1] if len(children) > 1 else None
        if_true = children[2] if len(children) > 2 else None
        if_false = children[3] if len(children) > 3 else None

        new_children: list[Any]
        if comparison:
            new_children = [condition, if_true, if_false]
        else:
            new_children = [condition, if_false, if_true]

        node.update(node_type="ternary", children=new_children)

    # (&& (coerce-b ...) (coerce-b ...)) -> (&& ... ...)
    def fix_boolean(self, node: Node) -> None:
        new_children = []
        for child in node.children:
            if isinstance(child, Node) and child.type == "coerce_b":
                # Unwrap coerce_b
                if child.children:
                    new_children.append(child.children[0])
            else:
                new_children.append(child)
        node.children = new_children

    # Aliases for boolean fixing
    on_and = fix_boolean
    on_or = fix_boolean
    on_jump_if = fix_boolean

    def _replace_with_nop(self, node: Node) -> None:
        node.update(node_type="nop")

    # Aliases for NOP replacement
    on_kill = _replace_with_nop
    on_debug = _replace_with_nop
    on_debug_file = _replace_with_nop
    on_debug_line = _replace_with_nop


if __name__ == "__main__":

    def print_ast(node: Node) -> None:
        print(f"Result AST: {node.to_sexp()}")

    def example_pop_expansion() -> None:
        print("--- Example 1: POP Expansion ---")
        # Input: (pop (int 1))
        # Rule: (pop x) -> (expand x (nop))
        ast = Node("pop", children=[Node("int", metadata={"val": 1})])

        print(f"Original:\n{ast.to_sexp()}")

        # Run through the pipeline entrypoint (simulating Furnace usage).
        pipeline = Pipeline([ASTNormalize()])

        pipeline.transform(ast)
        print(f"Transformed:\n{ast.to_sexp()}")

    def example_boolean_fix() -> None:
        print("\n--- Example 2: Boolean Coercion Removal ---")
        # Input: (and (coerce_b (local a)) (local b))
        # Rule: unwrap coerce_b nodes.
        ast = Node(
            "and",
            children=[
                Node("coerce_b", children=[Node("local", children=["a"])]),
                Node("local", children=["b"]),
            ],
        )

        print(f"Original:\n{ast.to_sexp()}")

        normalizer = ASTNormalize()
        normalizer.transform(ast)

        print(f"Transformed:\n{ast.to_sexp()}")

    def example_conditional_normalization() -> None:
        print("\n--- Example 3: Conditional Normalization (if_nge) ---")
        # Input: (jump_if false (if_nge (local a) (local b)) target)
        # Rule: if_nge -> >= and flip parent boolean flag from false to true.

        condition_node = Node(
            "if_nge",
            children=[Node("local", children=["a"]), Node("local", children=["b"])],
        )

        root = Node(
            "jump_if",
            children=[
                False,  # flag
                condition_node,  # condition
                "target_label",  # target
            ],
        )

        # Build parent pointers (normalization relies on parent links).
        root.normalize_hierarchy()

        print(f"Original:\n{root.to_sexp()}")

        normalizer = ASTNormalize()
        normalizer.transform(root)

        print(f"Transformed:\n{root.to_sexp()}")
        # Show that the branch flag was flipped.
        print(f"Flag is now:\n{root.children[0]}")

    example_pop_expansion()
    example_boolean_fix()
    example_conditional_normalization()
