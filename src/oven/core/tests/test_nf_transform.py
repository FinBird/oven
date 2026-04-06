"""Test normal form transform functionality."""

from __future__ import annotations

import pytest
from oven.core.ast import Node
from oven.avm2.transform.nf_transform import NFNormalize


class TestNFNormalize:
    """Test NFNormalize transformation."""

    def test_remove_useless_return_void(self) -> None:
        """Test removal of trailing return_void."""
        code_body = Node(
            "begin",
            children=[
                Node("get_local", children=[0]),
                Node("push_scope"),
                Node("return_void"),
            ],
        )

        normalizer = NFNormalize()
        result = normalizer.transform(code_body)

        # return_void should be removed
        assert result.type == "begin"
        assert len(result.children) == 2
        assert result.children[0].type == "get_local"
        assert result.children[1].type == "push_scope"

    def test_keep_non_void_return(self) -> None:
        """Test that non-void returns are kept."""
        code_body = Node(
            "begin",
            children=[
                Node("get_local", children=[0]),
                Node("return_value", children=[Node("literal", [42])]),
            ],
        )

        normalizer = NFNormalize()
        result = normalizer.transform(code_body)

        # return_value should be kept
        assert result.type == "begin"
        assert len(result.children) == 2
        assert result.children[1].type == "return_value"

    def test_remove_nop(self) -> None:
        """Test removal of nop nodes."""
        code_body = Node(
            "begin",
            children=[
                Node("nop"),
                Node("get_local", children=[0]),
                Node("nop"),
                Node("literal", [42]),
            ],
        )

        normalizer = NFNormalize()
        result = normalizer.transform(code_body)

        # nops should be removed
        assert result.type == "begin"
        assert len(result.children) == 2
        assert result.children[0].type == "get_local"
        assert result.children[1].type == "literal"

    def test_local_increment_optimization(self) -> None:
        """Test local increment optimization."""
        # i = i + 1 -> inc_local_i
        set_local = Node(
            "set_local",
            children=[
                0,
                Node(
                    "add",
                    children=[
                        Node("get_local", children=[0]),
                        Node("integer", children=[1]),
                    ],
                ),
            ],
        )

        normalizer = NFNormalize()
        result = normalizer.transform(set_local)

        # Should be optimized to increment
        assert result.type in {
            "inc_local_i",
            "pre_increment_local",
            "post_increment_local",
        }

    def test_local_decrement_optimization(self) -> None:
        """Test local decrement optimization."""
        # i = i - 1 -> dec_local_i
        set_local = Node(
            "set_local",
            children=[
                0,
                Node(
                    "subtract",
                    children=[
                        Node("get_local", children=[0]),
                        Node("integer", children=[1]),
                    ],
                ),
            ],
        )

        normalizer = NFNormalize()
        result = normalizer.transform(set_local)

        # Should be optimized to decrement
        assert result.type in {
            "dec_local_i",
            "pre_decrement_local",
            "post_decrement_local",
        }

    def test_catch_scope_object_removal(self) -> None:
        """Test removal of set_local with catch_scope_object."""
        set_local = Node("set_local", children=[0, Node("catch_scope_object")])

        normalizer = NFNormalize()
        result = normalizer.transform(set_local)

        # Should be removed
        assert result.type == "remove"

    def test_dead_code_after_return_void(self) -> None:
        """Test removal of dead code after return_void."""
        code_body = Node(
            "begin",
            children=[
                Node("get_local", children=[0]),
                Node("return_void"),
                Node("dead_code_1"),
                Node("dead_code_2"),
            ],
        )

        normalizer = NFNormalize()
        result = normalizer.transform(code_body)

        # Dead code and trailing return_void should be removed
        assert result.type == "begin"
        assert len(result.children) == 1
        assert result.children[0].type == "get_local"

    def test_dead_code_after_return_value(self) -> None:
        """Test removal of dead code after return_value."""
        code_body = Node(
            "begin",
            children=[
                Node("get_local", children=[0]),
                Node("return_value", children=[Node("literal", [42])]),
                Node("dead_code"),
            ],
        )

        normalizer = NFNormalize()
        result = normalizer.transform(code_body)

        # Dead code should be removed
        assert result.type == "begin"
        assert len(result.children) == 2
        assert result.children[1].type == "return_value"

    def test_dead_code_after_break(self) -> None:
        """Test removal of dead code after break."""
        code_body = Node(
            "begin",
            children=[
                Node("get_local", children=[0]),
                Node("break"),
                Node("dead_code"),
            ],
        )

        normalizer = NFNormalize()
        result = normalizer.transform(code_body)

        # Dead code should be removed
        assert result.type == "begin"
        assert len(result.children) == 2
        assert result.children[1].type == "break"

    def test_dead_code_after_continue(self) -> None:
        """Test removal of dead code after continue."""
        code_body = Node(
            "begin",
            children=[
                Node("get_local", children=[0]),
                Node("continue"),
                Node("dead_code"),
            ],
        )

        normalizer = NFNormalize()
        result = normalizer.transform(code_body)

        # Dead code should be removed
        assert result.type == "begin"
        assert len(result.children) == 2
        assert result.children[1].type == "continue"

    def test_dead_code_after_throw(self) -> None:
        """Test removal of dead code after throw."""
        code_body = Node(
            "begin",
            children=[
                Node("get_local", children=[0]),
                Node("throw", children=[Node("literal", ["error"])]),
                Node("dead_code"),
            ],
        )

        normalizer = NFNormalize()
        result = normalizer.transform(code_body)

        # Dead code should be removed
        assert result.type == "begin"
        assert len(result.children) == 2
        assert result.children[1].type == "throw"

    def test_with_scope_folding(self) -> None:
        """Test folding of push_with/pop_scope into with node."""
        scope_object = Node("get_scope_object", children=[1])

        ast = Node(
            "begin",
            children=[
                Node("push_with", children=[scope_object]),
                Node("call_something"),
                Node("pop_scope"),
                Node("return_void"),
            ],
        )

        normalizer = NFNormalize()
        result = normalizer.transform(ast)

        # Should be folded into with node
        assert result.type == "begin"
        assert len(result.children) == 1
        assert result.children[0].type == "with"
        assert result.children[0].children[0] == scope_object
        assert result.children[0].children[1].type == "begin"
        assert len(result.children[0].children[1].children) == 1
        assert result.children[0].children[1].children[0].type == "call_something"

    def test_nested_with_scope_folding(self) -> None:
        """Test folding of nested with scopes."""
        scope_object1 = Node("get_scope_object", children=[1])
        scope_object2 = Node("get_scope_object", children=[2])

        ast = Node(
            "begin",
            children=[
                Node("push_with", children=[scope_object1]),
                Node("push_with", children=[scope_object2]),
                Node("inner_call"),
                Node("pop_scope"),
                Node("outer_call"),
                Node("pop_scope"),
                Node("return_void"),
            ],
        )

        normalizer = NFNormalize()
        result = normalizer.transform(ast)

        # Should fold both with scopes
        assert result.type == "begin"
        assert len(result.children) == 1
        assert result.children[0].type == "with"
        assert result.children[0].children[0] == scope_object1
        inner_with = result.children[0].children[1]
        assert inner_with.type == "begin"
        assert len(inner_with.children) == 2
        assert inner_with.children[0].type == "with"
        assert inner_with.children[0].children[0] == scope_object2

    def test_superfluous_continue_removal(self) -> None:
        """Test removal of superfluous continue at end of loop body."""
        loop = Node(
            "while",
            children=[
                Node("condition"),
                Node(
                    "begin",
                    children=[Node("get_local", children=[0]), Node("continue")],
                ),
            ],
        )

        normalizer = NFNormalize()
        result = normalizer.transform(loop)

        # Continue should be removed
        assert result.type == "while"
        body = result.children[1]
        assert body.type == "begin"
        assert len(body.children) == 1
        assert body.children[0].type == "get_local"

    def test_for_loop_recovery(self) -> None:
        """Test recovery of for loop from while loop pattern."""
        # Pattern: init; while(cond) { body; update; }
        init = Node("set_local", children=[0, Node("integer", children=[0])])
        loop = Node(
            "while",
            children=[
                Node(
                    "less_than",
                    children=[
                        Node("get_local", children=[0]),
                        Node("integer", children=[10]),
                    ],
                ),
                Node(
                    "begin",
                    children=[
                        Node("call", children=[]),
                        Node(
                            "set_local",
                            children=[
                                0,
                                Node(
                                    "add",
                                    children=[
                                        Node("get_local", children=[0]),
                                        Node("integer", children=[1]),
                                    ],
                                ),
                            ],
                        ),
                    ],
                ),
            ],
        )

        ast = Node("begin", children=[init, loop])

        normalizer = NFNormalize()
        result = normalizer.transform(ast)

        # Loop should be converted to for loop
        assert result.type == "begin"
        assert len(result.children) == 1
        loop_node = result.children[0]
        assert loop_node.type == "while"
        # Check metadata for for_init and for_update
        assert "for_init" in loop_node.metadata
        assert "for_update" in loop_node.metadata

    def test_switch_case_dead_code_preservation(self) -> None:
        """Test that dead code removal is skipped in switch bodies."""
        switch_body = Node(
            "begin",
            children=[
                Node("case", children=[Node("integer", children=[0])]),
                Node("get_local", children=[0]),
                Node("break"),
                Node("case", children=[Node("integer", children=[1])]),
                Node("get_local", children=[1]),
                Node("return_void"),
            ],
        )

        normalizer = NFNormalize()
        result = normalizer.transform(switch_body)

        # All cases should be preserved
        assert result.type == "begin"
        case_nodes = [c for c in result.children if c.type == "case"]
        assert len(case_nodes) == 2

    def test_ternary_to_switch_optimization(self) -> None:
        """Test optimization of ternary chain to switch."""
        # Pattern: ternary(===, case_value, get_local(index), case_index, nested)
        condition = Node(
            "ternary",
            children=[
                Node(
                    "===",
                    children=[
                        Node("get_local", children=[0]),
                        Node("integer", children=[1]),
                    ],
                ),
                Node("integer", children=[0]),
                Node(
                    "ternary",
                    children=[
                        Node(
                            "===",
                            children=[
                                Node("get_local", children=[0]),
                                Node("integer", children=[2]),
                            ],
                        ),
                        Node("integer", children=[1]),
                        Node("integer", children=[2]),
                    ],
                ),
            ],
        )

        switch_body = Node(
            "begin",
            children=[
                Node("case", children=[Node("integer", children=[0])]),
                Node("break"),
                Node("case", children=[Node("integer", children=[1])]),
                Node("break"),
                Node("case", children=[Node("integer", children=[2])]),
                Node("break"),
            ],
        )

        switch = Node("switch", children=[condition, switch_body])

        normalizer = NFNormalize()
        result = normalizer.transform(switch)

        # Should be optimized
        assert result.type == "switch"
        assert result.children[0].type == "get_local"

    def test_empty_body_handling(self) -> None:
        """Test handling of empty begin nodes."""
        ast = Node("begin", children=[])

        normalizer = NFNormalize()
        result = normalizer.transform(ast)

        # Should handle empty gracefully
        assert result.type == "begin"
        assert len(result.children) == 0

    def test_single_statement_body(self) -> None:
        """Test handling of single statement body."""
        ast = Node("begin", children=[Node("get_local", children=[0])])

        normalizer = NFNormalize()
        result = normalizer.transform(ast)

        # Should handle single statement
        assert result.type == "begin"
        assert len(result.children) == 1
        assert result.children[0].type == "get_local"

    def test_mixed_control_flow(self) -> None:
        """Test mixed control flow with various terminals."""
        ast = Node(
            "begin",
            children=[
                Node(
                    "if",
                    children=[Node("condition"), Node("return_void"), Node("break")],
                ),
                Node("dead_code"),
                Node("continue"),
                Node("more_dead_code"),
            ],
        )

        normalizer = NFNormalize()
        result = normalizer.transform(ast)

        # Dead code should be removed
        assert result.type == "begin"
        assert len(result.children) == 1
        assert result.children[0].type == "if"

    def test_nested_begin_flattening(self) -> None:
        """Test that nested begin nodes are handled correctly."""
        ast = Node(
            "begin",
            children=[
                Node(
                    "begin",
                    children=[
                        Node("get_local", children=[0]),
                        Node("get_local", children=[1]),
                    ],
                ),
                Node("literal", [42]),
            ],
        )

        normalizer = NFNormalize()
        result = normalizer.transform(ast)

        # Should preserve structure
        assert result.type == "begin"
        assert len(result.children) == 2

    def test_complex_expression_optimization(self) -> None:
        """Test optimization of complex expressions."""
        # Complex increment: i = i + 1 with coerce
        set_local = Node(
            "set_local",
            children=[
                0,
                Node(
                    "coerce",
                    children=[
                        "any",
                        Node(
                            "add",
                            children=[
                                Node("get_local", children=[0]),
                                Node("integer", children=[1]),
                            ],
                        ),
                    ],
                ),
            ],
        )

        normalizer = NFNormalize()
        result = normalizer.transform(set_local)

        # Should be optimized
        assert result.type in {
            "inc_local_i",
            "pre_increment_local",
            "post_increment_local",
        }

    def test_preserve_non_optimizable_patterns(self) -> None:
        """Test that non-optimizable patterns are preserved."""
        # Pattern that doesn't match increment: i = j + 1
        set_local = Node(
            "set_local",
            children=[
                0,
                Node(
                    "add",
                    children=[
                        Node("get_local", children=[1]),  # Different local
                        Node("integer", children=[1]),
                    ],
                ),
            ],
        )

        normalizer = NFNormalize()
        result = normalizer.transform(set_local)

        # Should not be optimized
        assert result.type == "set_local"
        assert result.children[1].type == "add"

    def test_multiple_returns_in_sequence(self) -> None:
        """Test handling of multiple returns in sequence."""
        ast = Node(
            "begin",
            children=[Node("return_void"), Node("return_void"), Node("return_void")],
        )

        normalizer = NFNormalize()
        result = normalizer.transform(ast)

        # All return_void should be removed (they're all redundant)
        assert result.type == "begin"
        assert len(result.children) == 0

    def test_scope_object_in_with_block(self) -> None:
        """Test that scope objects are properly handled in with blocks."""
        scope = Node("get_scope_object", children=[1])
        inner_scope = Node("get_scope_object", children=[2])

        ast = Node(
            "begin",
            children=[
                Node("push_with", children=[scope]),
                Node("get_local", children=[0]),
                Node("push_scope", children=[inner_scope]),
                Node("pop_scope"),
                Node("pop_scope"),
            ],
        )

        normalizer = NFNormalize()
        result = normalizer.transform(ast)

        # Should handle nested scopes
        assert result.type == "begin"
        assert result.children[0].type == "with"
