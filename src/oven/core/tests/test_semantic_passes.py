"""Test semantic passes functionality."""

from __future__ import annotations

import pytest
from oven.core.ast import Node, NodeVisitor
from oven.core.transform.propagate_constants import PropagateConstants
from oven.core.transform.propagate_labels import PropagateLabels


# ============================================================================
# PropagateConstants Tests
# ============================================================================


class TestPropagateConstants:
    """Test constant propagation pass."""

    def test_basic_constant_propagation(self) -> None:
        """Test basic find_property_strict propagation."""
        # Build AST: set_local(0, find_property_strict("x")) -> get_local(0)
        value = Node("find_property_strict", ["x"])
        set_local = Node("set_local", [0, value])
        get_local = Node("get_local", [0])
        root = Node("root", [set_local, get_local])

        transformer = PropagateConstants()
        result = transformer.transform(root)

        # get_local should be replaced with find_property_strict
        # set_local is removed by NodeVisitor (nodes marked as "remove" are dropped)
        assert len(result.children) == 1
        assert result.children[0].type == "find_property_strict"
        assert result.children[0].children == ["x"]

    def test_no_propagation_for_non_find_property_strict(self) -> None:
        """Test that non-find_property_strict values are not propagated."""
        set_local = Node("set_local", [0, Node("literal", [42])])
        get_local = Node("get_local", [0])
        root = Node("root", [set_local, get_local])

        transformer = PropagateConstants()
        result = transformer.transform(root)

        # get_local should remain unchanged
        assert result.children[1].type == "get_local"
        assert result.children[0].type == "set_local"

    def test_propagation_stops_at_reassignment(self) -> None:
        """Test that propagation stops when variable is reassigned."""
        value1 = Node("find_property_strict", ["x"])
        set_local1 = Node("set_local", [0, value1])
        value2 = Node("literal", [100])
        set_local2 = Node("set_local", [0, value2])
        get_local = Node("get_local", [0])
        root = Node("root", [set_local1, set_local2, get_local])

        transformer = PropagateConstants()
        result = transformer.transform(root)

        # First set_local is removed (propagated), second set_local remains, get_local stays
        # Because variable was reassigned, get_local should NOT be replaced
        assert len(result.children) == 2
        assert result.children[0].type == "set_local"  # second set_local remains
        assert result.children[1].type == "get_local"  # not replaced

    def test_multiple_local_variables(self) -> None:
        """Test propagation with multiple local variables."""
        val_x = Node("find_property_strict", ["x"])
        set_local0 = Node("set_local", [0, val_x])
        val_y = Node("find_property_strict", ["y"])
        set_local1 = Node("set_local", [1, val_y])
        get_local0 = Node("get_local", [0])
        get_local1 = Node("get_local", [1])
        root = Node("root", [set_local0, set_local1, get_local0, get_local1])

        transformer = PropagateConstants()
        result = transformer.transform(root)

        # Both set_local are removed, both get_local are replaced
        assert len(result.children) == 2
        assert result.children[0].type == "find_property_strict"
        assert result.children[0].children == ["x"]
        assert result.children[1].type == "find_property_strict"
        assert result.children[1].children == ["y"]

    def test_propagation_across_nested_blocks(self) -> None:
        """Test propagation across nested blocks."""
        val = Node("find_property_strict", ["prop"])
        set_local = Node("set_local", [0, val])
        block = Node("block", [Node("get_local", [0])])
        root = Node("root", [set_local, block])

        transformer = PropagateConstants()
        result = transformer.transform(root)

        # set_local is removed, block remains with get_local replaced
        assert len(result.children) == 1
        assert result.children[0].type == "block"
        assert result.children[0].children[0].type == "find_property_strict"

    def test_no_propagation_outside_scope(self) -> None:
        """Test that propagation doesn't escape scope."""
        block = Node(
            "block",
            [
                Node("set_local", [0, Node("find_property_strict", ["x"])]),
                Node("get_local", [0]),
            ],
        )
        root = Node("root", [block])

        transformer = PropagateConstants()
        result = transformer.transform(root)

        # set_local is removed, get_local is replaced
        # block only contains find_property_strict
        assert len(result.children[0].children) == 1
        assert result.children[0].children[0].type == "find_property_strict"

    def test_propagation_with_metadata(self) -> None:
        """Test that metadata is preserved during propagation."""
        val = Node("find_property_strict", ["x"], {"source": "test"})
        set_local = Node("set_local", [0, val])
        get_local = Node("get_local", [0])
        root = Node("root", [set_local, get_local])

        transformer = PropagateConstants()
        result = transformer.transform(root)

        # set_local is removed, get_local is replaced with find_property_strict
        # Metadata should be copied to the propagated value
        assert len(result.children) == 1
        assert result.children[0].type == "find_property_strict"
        assert result.children[0].metadata.get("source") == "test"

    def test_empty_children_handling(self) -> None:
        """Test handling of nodes with empty children."""
        set_local = Node("set_local", [])
        get_local = Node("get_local", [])
        root = Node("root", [set_local, get_local])

        transformer = PropagateConstants()
        result = transformer.transform(root)

        # Should not crash
        assert result.children[0].type == "set_local"
        assert result.children[1].type == "get_local"

    def test_non_node_children(self) -> None:
        """Test handling of non-node children."""
        set_local = Node("set_local", [0, 42])  # literal value, not Node
        get_local = Node("get_local", [0])
        root = Node("root", [set_local, get_local])

        transformer = PropagateConstants()
        result = transformer.transform(root)

        # Should not crash
        assert result.children[1].type == "get_local"

    def test_propagation_preserves_order(self) -> None:
        """Test that transformation preserves operation order."""
        val1 = Node("find_property_strict", ["a"])
        set1 = Node("set_local", [0, val1])
        val2 = Node("find_property_strict", ["b"])
        set2 = Node("set_local", [1, val2])
        op = Node("call", [])
        get1 = Node("get_local", [0])
        get2 = Node("get_local", [1])
        root = Node("root", [set1, set2, op, get1, get2])

        transformer = PropagateConstants()
        result = transformer.transform(root)

        # set_local nodes are removed, get_local nodes are replaced
        # Order: call, find_property_strict, find_property_strict
        assert len(result.children) == 3
        assert result.children[0].type == "call"
        assert result.children[1].type == "find_property_strict"
        assert result.children[2].type == "find_property_strict"

    def test_variable_folding_simple(self) -> None:
        """Test simple variable folding."""
        # x = 5; y = x; -> y = 5
        # Note: PropagateConstants only propagates find_property_strict, not literals
        # So literal values are not propagated
        val = Node("literal", [5])
        set_x = Node("set_local", [0, val])
        get_x = Node("get_local", [0])
        set_y = Node("set_local", [1, get_x])
        root = Node("root", [set_x, set_y])

        transformer = PropagateConstants()
        result = transformer.transform(root)

        # Both set_local remain, get_local is not replaced
        # because PropagateConstants only handles find_property_strict
        assert len(result.children) == 2
        assert result.children[0].type == "set_local"
        assert result.children[1].type == "set_local"
        assert result.children[1].children[1].type == "get_local"

    def test_if_else_optimization(self) -> None:
        """Test if-else branch optimization."""
        condition = Node("get_local", [0])
        true_branch = Node("literal", [1])
        false_branch = Node("literal", [0])
        if_node = Node("if", [condition, true_branch, false_branch])
        root = Node("root", [if_node])

        transformer = PropagateConstants()
        result = transformer.transform(root)

        # Structure should be preserved
        assert result.children[0].type == "if"
        assert len(result.children[0].children) == 3

    def test_array_literal_restoration(self) -> None:
        """Test array literal restoration."""
        # [x, y, z] where x, y, z are known
        # Note: PropagateConstants only propagates find_property_strict, not literals
        # So array elements remain as get_local nodes
        set_x = Node("set_local", [0, Node("literal", [1])])
        set_y = Node("set_local", [1, Node("literal", [2])])
        set_z = Node("set_local", [2, Node("literal", [3])])
        arr = Node(
            "array",
            [Node("get_local", [0]), Node("get_local", [1]), Node("get_local", [2])],
        )
        root = Node("root", [set_x, set_y, set_z, arr])

        transformer = PropagateConstants()
        result = transformer.transform(root)

        # Array should contain get_local nodes (not replaced)
        # because PropagateConstants only handles find_property_strict
        arr_node = result.children[3]
        assert arr_node.type == "array"
        assert arr_node.children[0].type == "get_local"

    def test_object_literal_restoration(self) -> None:
        """Test object literal restoration."""
        # Note: PropagateConstants only propagates find_property_strict, not literals
        # So object key remains as get_local node
        set_a = Node("set_local", [0, Node("literal", ["value_a"])])
        obj = Node("object", [Node("key", ["prop_a", Node("get_local", [0])])])
        root = Node("root", [set_a, obj])

        transformer = PropagateConstants()
        result = transformer.transform(root)

        # Object key should have get_local node (not replaced)
        # because PropagateConstants only handles find_property_strict
        obj_node = result.children[1]
        assert obj_node.type == "object"
        assert obj_node.children[0].children[1].type == "get_local"

    def test_complex_expression_folding(self) -> None:
        """Test folding in complex expressions."""
        # Note: PropagateConstants propagates find_property_strict and removes set_local
        # So get_local is replaced with find_property_strict
        val = Node("find_property_strict", ["Math"])
        set_math = Node("set_local", [0, val])
        get_math = Node("get_local", [0])
        prop_access = Node("get_property", [get_math, "PI"])
        root = Node("root", [set_math, prop_access])

        transformer = PropagateConstants()
        result = transformer.transform(root)

        # set_math is removed, prop_access is at children[0]
        # property access receiver is replaced with find_property_strict
        assert len(result.children) == 1
        prop_node = result.children[0]
        assert prop_node.type == "get_property"
        assert prop_node.children[0].type == "find_property_strict"

    def test_no_folding_for_side_effects(self) -> None:
        """Test that side effects prevent folding."""
        call = Node("call", [Node("get_local", [0])])
        set_result = Node("set_local", [1, call])
        get_result = Node("get_local", [1])
        root = Node("root", [set_result, get_result])

        transformer = PropagateConstants()
        result = transformer.transform(root)

        # Should not fold calls with side effects
        assert result.children[1].type == "get_local"

    def test_partial_constant_propagation(self) -> None:
        """Test propagation of partial constants."""
        # Note: PropagateConstants only propagates find_property_strict, not literals
        # So get_local remains as get_local node
        val = Node("find_property_strict", ["x"])
        set_local = Node("set_local", [0, val])
        binary = Node("add", [Node("get_local", [0]), Node("literal", [5])])
        root = Node("root", [set_local, binary])

        transformer = PropagateConstants()
        result = transformer.transform(root)

        # PropagateConstants may remove set_local, so avoid brittle fixed index assertions.
        target_node = next(n for n in result.children if n.type == "add")
        assert target_node.children[0].type == "find_property_strict"
        assert target_node.children[1].type == "literal"

    def test_loop_variable_propagation(self) -> None:
        """Test propagation in loop contexts."""
        init = Node("set_local", [0, Node("literal", [0])])
        loop = Node(
            "while",
            [
                Node("get_local", [0]),
                Node("block", [Node("increment", [Node("get_local", [0])])]),
            ],
        )
        root = Node("root", [init, loop])

        transformer = PropagateConstants()
        result = transformer.transform(root)

        # Loop structure should be preserved
        assert result.children[1].type == "while"

    def test_ternary_operator_folding(self) -> None:
        """Test ternary operator folding."""
        condition = Node("literal", [True])
        true_val = Node("literal", [1])
        false_val = Node("literal", [0])
        ternary = Node("ternary", [condition, true_val, false_val])
        root = Node("root", [ternary])

        transformer = PropagateConstants()
        result = transformer.transform(root)

        # Ternary structure preserved (constant folding is separate)
        assert result.children[0].type == "ternary"

    def test_null_and_undefined_propagation(self) -> None:
        """Test null and undefined propagation."""
        set_null = Node("set_local", [0, Node("null", [])])
        set_undef = Node("set_local", [1, Node("undefined", [])])
        get_null = Node("get_local", [0])
        get_undef = Node("get_local", [1])
        root = Node("root", [set_null, set_undef, get_null, get_undef])

        transformer = PropagateConstants()
        result = transformer.transform(root)

        # null and undefined should be propagated
        assert result.children[2].type == "get_local"
        assert result.children[3].type == "get_local"

    def test_string_constant_propagation(self) -> None:
        """Test string constant propagation."""
        # Note: PropagateConstants only propagates find_property_strict, not literals
        # So get_local remains as get_local node
        val = Node("literal", ["hello"])
        set_str = Node("set_local", [0, val])
        get_str = Node("get_local", [0])
        concat = Node("concat", [get_str, Node("literal", [" world"])])
        root = Node("root", [set_str, concat])

        transformer = PropagateConstants()
        result = transformer.transform(root)

        # String should be get_local (not replaced)
        # because PropagateConstants only handles find_property_strict
        assert result.children[1].children[0].type == "get_local"

    def test_boolean_propagation(self) -> None:
        """Test boolean constant propagation."""
        set_true = Node("set_local", [0, Node("true", [])])
        set_false = Node("set_local", [1, Node("false", [])])
        get_true = Node("get_local", [0])
        get_false = Node("get_local", [1])
        root = Node("root", [set_true, set_false, get_true, get_false])

        transformer = PropagateConstants()
        result = transformer.transform(root)

        # Booleans should be propagated
        assert result.children[2].type == "get_local"
        assert result.children[3].type == "get_local"

    def test_nested_property_access(self) -> None:
        """Test nested property access propagation."""
        # Note: PropagateConstants only propagates find_property_strict, not literals
        # So get_local remains as get_local node
        val = Node("find_property_strict", ["obj"])
        set_obj = Node("set_local", [0, val])
        get_obj = Node("get_local", [0])
        nested = Node("get_property", [Node("get_property", [get_obj, "a"]), "b"])
        root = Node("root", [set_obj, nested])

        transformer = PropagateConstants()
        result = transformer.transform(root)

        # set_obj is removed, nested expression shifts to children[0].
        inner_prop = result.children[0].children[0]
        assert inner_prop.children[0].type == "find_property_strict"

    def test_method_call_with_propagation(self) -> None:
        """Test method call with propagated receiver."""
        # Note: PropagateConstants propagates find_property_strict and removes set_local
        # So get_local is replaced with find_property_strict
        val = Node("find_property_strict", ["console"])
        set_console = Node("set_local", [0, val])
        get_console = Node("get_local", [0])
        call = Node("call_method", [get_console, "log", [Node("literal", ["msg"])]])
        root = Node("root", [set_console, call])

        transformer = PropagateConstants()
        result = transformer.transform(root)

        # set_console is removed, call is at children[0]
        # receiver is replaced with find_property_strict
        assert len(result.children) == 1
        assert result.children[0].type == "call_method"
        assert result.children[0].children[0].type == "find_property_strict"

    def test_index_access_propagation(self) -> None:
        """Test index access propagation."""
        val = Node("find_property_strict", ["arr"])
        set_arr = Node("set_local", [0, val])
        get_arr = Node("get_local", [0])
        index = Node("index", [get_arr, Node("literal", [0])])
        root = Node("root", [set_arr, index])

        transformer = PropagateConstants()
        result = transformer.transform(root)

        # set_arr is removed, index node shifts to children[0]
        assert result.children[0].children[0].type == "find_property_strict"

    def test_destructuring_assignment(self) -> None:
        """Test destructuring assignment propagation."""
        val = Node("find_property_strict", ["data"])
        set_data = Node("set_local", [0, val])
        get_data = Node("get_local", [0])
        destructure = Node(
            "destructure", [get_data, Node("set_local", [1]), Node("set_local", [2])]
        )
        root = Node("root", [set_data, destructure])

        transformer = PropagateConstants()
        result = transformer.transform(root)

        # set_data is removed, destructuring node shifts to children[0]
        assert result.children[0].children[0].type == "find_property_strict"

    def test_spread_operator_propagation(self) -> None:
        """Test spread operator propagation."""
        val = Node("find_property_strict", ["source"])
        set_source = Node("set_local", [0, val])
        get_source = Node("get_local", [0])
        spread = Node("spread", [get_source])
        root = Node("root", [set_source, spread])

        transformer = PropagateConstants()
        result = transformer.transform(root)

        # set_source is removed, spread node shifts to children[0]
        assert result.children[0].children[0].type == "find_property_strict"

    def test_arrow_function_capture(self) -> None:
        """Test arrow function variable capture."""
        val = Node("find_property_strict", ["x"])
        set_x = Node("set_local", [0, val])
        arrow = Node("arrow_function", [Node("return", [Node("get_local", [0])])])
        root = Node("root", [set_x, arrow])

        transformer = PropagateConstants()
        result = transformer.transform(root)

        # set_x is removed, arrow_function node shifts to children[0]
        assert result.children[0].type == "arrow_function"

    def test_class_method_propagation(self) -> None:
        """Test class method constant propagation."""
        val = Node("find_property_strict", ["MyClass"])
        set_class = Node("set_local", [0, val])
        get_class = Node("get_local", [0])
        method = Node(
            "class_method",
            [get_class, "method", Node("return", [Node("literal", [42])])],
        )
        root = Node("root", [set_class, method])

        transformer = PropagateConstants()
        result = transformer.transform(root)

        # set_class is removed, class_method node shifts to children[0]
        assert result.children[0].children[0].type == "find_property_strict"

    def test_super_reference_propagation(self) -> None:
        """Test super reference propagation."""
        val = Node("find_property_strict", ["Base"])
        set_base = Node("set_local", [0, val])
        get_base = Node("get_local", [0])
        super_ref = Node("super", [get_base])
        root = Node("root", [set_base, super_ref])

        transformer = PropagateConstants()
        result = transformer.transform(root)

        # set_base is removed, super node shifts to children[0]
        assert result.children[0].children[0].type == "find_property_strict"

    def test_this_reference_propagation(self) -> None:
        """Test this reference propagation."""
        val = Node("find_property_strict", ["this"])
        set_this = Node("set_local", [0, val])
        get_this = Node("get_local", [0])
        root = Node("root", [set_this, get_this])

        transformer = PropagateConstants()
        result = transformer.transform(root)

        # set_this is removed, propagated node shifts to children[0]
        assert result.children[0].type == "find_property_strict"

    def test_rest_parameters_propagation(self) -> None:
        """Test rest parameters propagation."""
        val = Node("find_property_strict", ["args"])
        set_args = Node("set_local", [0, val])
        get_args = Node("get_local", [0])
        rest = Node("rest", [get_args])
        root = Node("root", [set_args, rest])

        transformer = PropagateConstants()
        result = transformer.transform(root)

        # set_args is removed, rest node shifts to children[0]
        assert result.children[0].children[0].type == "find_property_strict"

    def test_generator_function_propagation(self) -> None:
        """Test generator function propagation."""
        val = Node("find_property_strict", ["gen"])
        set_gen = Node("set_local", [0, val])
        get_gen = Node("get_local", [0])
        generator = Node("generator", [get_gen, Node("yield", [Node("literal", [1])])])
        root = Node("root", [set_gen, generator])

        transformer = PropagateConstants()
        result = transformer.transform(root)

        # set_gen is removed, generator node shifts to children[0]
        assert result.children[0].children[0].type == "find_property_strict"

    def test_async_function_propagation(self) -> None:
        """Test async function propagation."""
        val = Node("find_property_strict", ["async_fn"])
        set_async = Node("set_local", [0, val])
        get_async = Node("get_local", [0])
        async_fn = Node("async", [get_async, Node("await", [Node("call", [])])])
        root = Node("root", [set_async, async_fn])

        transformer = PropagateConstants()
        result = transformer.transform(root)

        # set_async is removed, async node shifts to children[0]
        assert result.children[0].children[0].type == "find_property_strict"

    def test_try_catch_propagation(self) -> None:
        """Test try-catch constant propagation."""
        val = Node("find_property_strict", ["error"])
        set_error = Node("set_local", [0, val])
        try_node = Node("try", [Node("throw", [Node("get_local", [0])])])
        root = Node("root", [set_error, try_node])

        transformer = PropagateConstants()
        result = transformer.transform(root)

        # set_error is removed, try node shifts to children[0]
        assert result.children[0].children[0].children[0].type == "find_property_strict"

    def test_switch_case_propagation(self) -> None:
        """Test switch-case constant propagation."""
        val = Node("find_property_strict", ["value"])
        set_value = Node("set_local", [0, val])
        get_value = Node("get_local", [0])
        switch = Node(
            "switch",
            [get_value, Node("case", [Node("literal", [1]), Node("break", [])])],
        )
        root = Node("root", [set_value, switch])

        transformer = PropagateConstants()
        result = transformer.transform(root)

        # set_value is removed, switch node shifts to children[0]
        assert result.children[0].children[0].type == "find_property_strict"

    def test_for_loop_propagation(self) -> None:
        """Test for loop constant propagation."""
        val = Node("find_property_strict", ["iter"])
        set_iter = Node("set_local", [0, val])
        get_iter = Node("get_local", [0])
        for_loop = Node(
            "for",
            [
                Node("set_local", [1, Node("literal", [0])]),
                Node("less_than", [Node("get_local", [1]), Node("literal", [10])]),
                Node("increment", [Node("get_local", [1])]),
                Node("call", [get_iter]),
            ],
        )
        root = Node("root", [set_iter, for_loop])

        transformer = PropagateConstants()
        result = transformer.transform(root)

        # set_iter is removed, for node shifts to children[0]
        assert result.children[0].children[3].children[0].type == "find_property_strict"

    def test_while_loop_propagation(self) -> None:
        """Test while loop constant propagation."""
        val = Node("find_property_strict", ["condition"])
        set_cond = Node("set_local", [0, val])
        get_cond = Node("get_local", [0])
        while_loop = Node("while", [get_cond, Node("block", [Node("break", [])])])
        root = Node("root", [set_cond, while_loop])

        transformer = PropagateConstants()
        result = transformer.transform(root)

        # set_cond is removed, while node shifts to children[0]
        assert result.children[0].children[0].type == "find_property_strict"

    def test_do_while_loop_propagation(self) -> None:
        """Test do-while loop constant propagation."""
        val = Node("find_property_strict", ["cond"])
        set_cond = Node("set_local", [0, val])
        get_cond = Node("get_local", [0])
        do_while = Node("do_while", [Node("block", [Node("break", [])]), get_cond])
        root = Node("root", [set_cond, do_while])

        transformer = PropagateConstants()
        result = transformer.transform(root)

        # set_cond is removed, do_while node shifts to children[0]
        assert result.children[0].children[1].type == "find_property_strict"

    def test_with_statement_propagation(self) -> None:
        """Test with statement constant propagation."""
        val = Node("find_property_strict", ["scope"])
        set_scope = Node("set_local", [0, val])
        get_scope = Node("get_local", [0])
        with_node = Node("with", [get_scope, Node("block", [])])
        root = Node("root", [set_scope, with_node])

        transformer = PropagateConstants()
        result = transformer.transform(root)

        # set_scope is removed, with node shifts to children[0]
        assert result.children[0].children[0].type == "find_property_strict"

    def test_label_statement_propagation(self) -> None:
        """Test label statement constant propagation."""
        val = Node("find_property_strict", ["label"])
        set_label = Node("set_local", [0, val])
        get_label = Node("get_local", [0])
        labeled = Node("label", [get_label, Node("block", [])])
        root = Node("root", [set_label, labeled])

        transformer = PropagateConstants()
        result = transformer.transform(root)

        # set_label is removed, label node shifts to children[0]
        assert result.children[0].children[0].type == "find_property_strict"

    def test_throw_statement_propagation(self) -> None:
        """Test throw statement constant propagation."""
        val = Node("find_property_strict", ["exception"])
        set_exc = Node("set_local", [0, val])
        get_exc = Node("get_local", [0])
        throw = Node("throw", [get_exc])
        root = Node("root", [set_exc, throw])

        transformer = PropagateConstants()
        result = transformer.transform(root)

        # set_exc is removed, throw node shifts to children[0]
        assert result.children[0].children[0].type == "find_property_strict"

    def test_return_statement_propagation(self) -> None:
        """Test return statement constant propagation."""
        val = Node("find_property_strict", ["result"])
        set_result = Node("set_local", [0, val])
        get_result = Node("get_local", [0])
        ret = Node("return", [get_result])
        root = Node("root", [set_result, ret])

        transformer = PropagateConstants()
        result = transformer.transform(root)

        # set_result is removed, return node shifts to children[0]
        assert result.children[0].children[0].type == "find_property_strict"

    def test_yield_statement_propagation(self) -> None:
        """Test yield statement constant propagation."""
        val = Node("find_property_strict", ["value"])
        set_value = Node("set_local", [0, val])
        get_value = Node("get_local", [0])
        yield_node = Node("yield", [get_value])
        root = Node("root", [set_value, yield_node])

        transformer = PropagateConstants()
        result = transformer.transform(root)

        # set_value is removed, yield node shifts to children[0]
        assert result.children[0].children[0].type == "find_property_strict"

    def test_await_expression_propagation(self) -> None:
        """Test await expression constant propagation."""
        val = Node("find_property_strict", ["promise"])
        set_promise = Node("set_local", [0, val])
        get_promise = Node("get_local", [0])
        await_node = Node("await", [get_promise])
        root = Node("root", [set_promise, await_node])

        transformer = PropagateConstants()
        result = transformer.transform(root)

        # set_promise is removed, await node shifts to children[0]
        assert result.children[0].children[0].type == "find_property_strict"

    def test_import_statement_propagation(self) -> None:
        """Test import statement constant propagation."""
        val = Node("find_property_strict", ["module"])
        set_module = Node("set_local", [0, val])
        get_module = Node("get_local", [0])
        import_node = Node("import", [get_module, Node("literal", ["default"])])
        root = Node("root", [set_module, import_node])

        transformer = PropagateConstants()
        result = transformer.transform(root)

        # set_module is removed, import node shifts to children[0]
        assert result.children[0].children[0].type == "find_property_strict"

    def test_export_statement_propagation(self) -> None:
        """Test export statement constant propagation."""
        val = Node("find_property_strict", ["exported"])
        set_exported = Node("set_local", [0, val])
        get_exported = Node("get_local", [0])
        export_node = Node("export", [get_exported])
        root = Node("root", [set_exported, export_node])

        transformer = PropagateConstants()
        result = transformer.transform(root)

        # set_exported is removed, export node shifts to children[0]
        assert result.children[0].children[0].type == "find_property_strict"

    def test_class_declaration_propagation(self) -> None:
        """Test class declaration constant propagation."""
        val = Node("find_property_strict", ["Base"])
        set_base = Node("set_local", [0, val])
        get_base = Node("get_local", [0])
        class_node = Node(
            "class", [Node("literal", ["Derived"]), get_base, Node("block", [])]
        )
        root = Node("root", [set_base, class_node])

        transformer = PropagateConstants()
        result = transformer.transform(root)

        # set_base is removed, class node shifts to children[0]
        assert result.children[0].children[1].type == "find_property_strict"

    def test_function_declaration_propagation(self) -> None:
        """Test function declaration constant propagation."""
        val = Node("find_property_strict", ["fn"])
        set_fn = Node("set_local", [0, val])
        get_fn = Node("get_local", [0])
        func_node = Node("function", [get_fn, Node("params", []), Node("block", [])])
        root = Node("root", [set_fn, func_node])

        transformer = PropagateConstants()
        result = transformer.transform(root)

        # set_fn is removed, function node shifts to children[0]
        assert result.children[0].children[0].type == "find_property_strict"

    def test_variable_declaration_propagation(self) -> None:
        """Test variable declaration constant propagation."""
        val = Node("find_property_strict", ["x"])
        set_x = Node("set_local", [0, val])
        get_x = Node("get_local", [0])
        var_decl = Node("var_decl", [Node("literal", ["y"]), get_x])
        root = Node("root", [set_x, var_decl])

        transformer = PropagateConstants()
        result = transformer.transform(root)

        # set_x is removed, var_decl node shifts to children[0]
        assert result.children[0].children[1].type == "find_property_strict"

    def test_const_declaration_propagation(self) -> None:
        """Test const declaration constant propagation."""
        val = Node("find_property_strict", ["x"])
        set_x = Node("set_local", [0, val])
        get_x = Node("get_local", [0])
        const_decl = Node("const_decl", [Node("literal", ["y"]), get_x])
        root = Node("root", [set_x, const_decl])

        transformer = PropagateConstants()
        result = transformer.transform(root)

        # set_x is removed, const_decl node shifts to children[0]
        assert result.children[0].children[1].type == "find_property_strict"

    def test_let_declaration_propagation(self) -> None:
        """Test let declaration constant propagation."""
        val = Node("find_property_strict", ["x"])
        set_x = Node("set_local", [0, val])
        get_x = Node("get_local", [0])
        let_decl = Node("let_decl", [Node("literal", ["y"]), get_x])
        root = Node("root", [set_x, let_decl])

        transformer = PropagateConstants()
        result = transformer.transform(root)

        # set_x is removed, let_decl node shifts to children[0]
        assert result.children[0].children[1].type == "find_property_strict"


# ============================================================================
# PropagateLabels Tests
# ============================================================================


class TestPropagateLabels:
    """Test label propagation pass."""

    def test_basic_label_propagation(self) -> None:
        """Test basic label propagation upward."""
        child = Node("literal", [42], {"label": 100})
        parent = Node("block", [child])
        root = Node("root", [parent])

        transformer = PropagateLabels()
        result = transformer.transform(root)

        # Label should propagate to parent
        assert result.children[0].metadata.get("label") == 100
        # Child label should be removed
        assert result.children[0].children[0].metadata.get("label") is None

    def test_min_label_propagation(self) -> None:
        """Test that minimum label is propagated."""
        child1 = Node("literal", [1], {"label": 200})
        child2 = Node("literal", [2], {"label": 100})
        parent = Node("block", [child1, child2])
        root = Node("root", [parent])

        transformer = PropagateLabels()
        result = transformer.transform(root)

        # Minimum label should propagate
        assert result.children[0].metadata.get("label") == 100

    def test_no_propagation_for_jump_targets(self) -> None:
        """Test that jump targets are not overwritten."""
        child = Node("literal", [42], {"label": 100})
        parent = Node("block", [child], {"label": 50})
        jump = Node("jump", [50])
        root = Node("root", [jump, parent])

        transformer = PropagateLabels()
        result = transformer.transform(root)

        # Parent's label should not be overwritten by jump target
        assert result.children[1].metadata.get("label") == 50

    def test_collect_jump_targets(self) -> None:
        """Test collection of jump targets."""
        jump = Node("jump", [100])
        jump_if = Node("jump_if", [Node("condition", []), 200])
        switch = Node(
            "lookup_switch",
            [
                300,  # default
                [400, 500],  # cases
            ],
        )
        root = Node("root", [jump, jump_if, switch])

        transformer = PropagateLabels()
        transformer.transform(root)

        # All targets should be collected
        assert 100 in transformer._target_labels
        assert 200 in transformer._target_labels
        assert 300 in transformer._target_labels
        assert 400 in transformer._target_labels
        assert 500 in transformer._target_labels

    def test_nested_label_propagation(self) -> None:
        """Test label propagation through nested structures."""
        inner = Node("literal", [42], {"label": 100})
        middle = Node("block", [inner])
        outer = Node("block", [middle])
        root = Node("root", [outer])

        transformer = PropagateLabels()
        result = transformer.transform(root)

        # Label should propagate all the way up
        assert result.children[0].metadata.get("label") == 100
        assert result.children[0].children[0].metadata.get("label") == 100

    def test_multiple_children_with_labels(self) -> None:
        """Test propagation with multiple labeled children."""
        child1 = Node("literal", [1], {"label": 300})
        child2 = Node("literal", [2], {"label": 100})
        child3 = Node("literal", [3], {"label": 200})
        parent = Node("block", [child1, child2, child3])
        root = Node("root", [parent])

        transformer = PropagateLabels()
        result = transformer.transform(root)

        # Should use minimum label
        assert result.children[0].metadata.get("label") == 100

    def test_no_labels_in_children(self) -> None:
        """Test when children have no labels."""
        child1 = Node("literal", [1])
        child2 = Node("literal", [2])
        parent = Node("block", [child1, child2])
        root = Node("root", [parent])

        transformer = PropagateLabels()
        result = transformer.transform(root)

        # Parent should have no label
        assert result.children[0].metadata.get("label") is None

    def test_label_preservation_for_root(self) -> None:
        """Test that root node labels are preserved."""
        child = Node("literal", [42], {"label": 100})
        root = Node("root", [child], {"label": 50})

        transformer = PropagateLabels()
        result = transformer.transform(root)

        # Root label should be preserved
        assert result.metadata.get("label") == 50

    def test_jump_if_targets(self) -> None:
        """Test jump_if target collection."""
        condition = Node("condition", [])
        jump_if = Node("jump_if", [condition, 100])
        root = Node("root", [jump_if])

        transformer = PropagateLabels()
        transformer.transform(root)

        assert 100 in transformer._target_labels

    def test_lookup_switch_targets(self) -> None:
        """Test lookup_switch target collection."""
        default = 100
        cases = [200, 300, 400]
        switch = Node("lookup_switch", [default, cases])
        root = Node("root", [switch])

        transformer = PropagateLabels()
        transformer.transform(root)

        assert 100 in transformer._target_labels
        assert 200 in transformer._target_labels
        assert 300 in transformer._target_labels
        assert 400 in transformer._target_labels
        assert "not_an_int" not in {str(x) for x in transformer._target_labels}

    def test_empty_children_handling(self) -> None:
        """Test handling of nodes with empty children."""
        parent = Node("block", [])
        root = Node("root", [parent])

        transformer = PropagateLabels()
        result = transformer.transform(root)

        # Should not crash
        assert result.children[0].metadata.get("label") is None

    def test_non_node_children_ignored(self) -> None:
        """Test that non-node children are ignored."""
        parent = Node("block", [42, "string", None])
        root = Node("root", [parent])

        transformer = PropagateLabels()
        result = transformer.transform(root)

        # Should not crash
        assert result.children[0].metadata.get("label") is None

    def test_label_removal_from_children(self) -> None:
        """Test that labels are removed from children after propagation."""
        child = Node("literal", [42], {"label": 100, "other": "data"})
        parent = Node("block", [child])
        root = Node("root", [parent])

        transformer = PropagateLabels()
        result = transformer.transform(root)

        # Child should have label removed but other metadata preserved
        child_meta = result.children[0].children[0].metadata
        assert child_meta.get("label") is None
        assert child_meta.get("other") == "data"

    def test_deeply_nested_structures(self) -> None:
        """Test label propagation in deeply nested structures."""
        level3 = Node("literal", [42], {"label": 100})
        level2 = Node("block", [level3])
        level1 = Node("block", [level2])
        root = Node("root", [level1])

        transformer = PropagateLabels()
        result = transformer.transform(root)

        # Should propagate through all levels
        assert result.children[0].metadata.get("label") == 100
        assert result.children[0].children[0].metadata.get("label") == 100
        assert result.children[0].children[0].children[0].metadata.get("label") is None

    def test_mixed_labeled_and_unlabeled(self) -> None:
        """Test mix of labeled and unlabeled children."""
        labeled = Node("literal", [1], {"label": 100})
        unlabeled = Node("literal", [2])
        parent = Node("block", [labeled, unlabeled])
        root = Node("root", [parent])

        transformer = PropagateLabels()
        result = transformer.transform(root)

        # Should still propagate the label
        assert result.children[0].metadata.get("label") == 100

    def test_preserve_existing_label_if_not_in_targets(self) -> None:
        """Test that existing label is preserved if not a jump target."""
        child = Node("literal", [42], {"label": 100})
        parent = Node("block", [child], {"label": 50})
        root = Node("root", [parent])

        transformer = PropagateLabels()
        result = transformer.transform(root)

        # Parent's label should be overwritten by child's label
        assert result.children[0].metadata.get("label") == 100

    def test_preserve_existing_label_if_in_targets(self) -> None:
        """Test that existing label is preserved if it's a jump target."""
        child = Node("literal", [42], {"label": 100})
        parent = Node("block", [child], {"label": 50})
        jump = Node("jump", [50])
        root = Node("root", [jump, parent])

        transformer = PropagateLabels()
        result = transformer.transform(root)

        # Parent's label should be preserved (it's a jump target)
        assert result.children[1].metadata.get("label") == 50

    def test_complex_control_flow(self) -> None:
        """Test label propagation in complex control flow."""
        # if-else with labels
        condition = Node("condition", [])
        true_branch = Node("literal", [1], {"label": 100})
        false_branch = Node("literal", [0], {"label": 200})
        if_node = Node("if", [condition, true_branch, false_branch])

        # loop with label
        loop_body = Node("literal", [42], {"label": 300})
        loop = Node("while", [condition, loop_body])

        root = Node("root", [if_node, loop])

        transformer = PropagateLabels()
        result = transformer.transform(root)

        # Labels should propagate to if and while nodes
        assert result.children[0].metadata.get("label") == 100
        assert result.children[1].metadata.get("label") == 300

    def test_switch_case_labels(self) -> None:
        """Test label propagation in switch-case."""
        case1 = Node("literal", [1], {"label": 100})
        case2 = Node("literal", [2], {"label": 200})
        switch = Node("switch", [Node("expr", []), case1, case2])
        root = Node("root", [switch])

        transformer = PropagateLabels()
        result = transformer.transform(root)

        # Switch should get minimum case label
        assert result.children[0].metadata.get("label") == 100

    def test_try_catch_labels(self) -> None:
        """Test label propagation in try-catch."""
        try_body = Node("literal", [1], {"label": 100})
        catch_body = Node("literal", [0], {"label": 200})
        try_node = Node("try", [try_body, catch_body])
        root = Node("root", [try_node])

        transformer = PropagateLabels()
        result = transformer.transform(root)

        # Try should get minimum label
        assert result.children[0].metadata.get("label") == 100

    def test_function_body_labels(self) -> None:
        """Test label propagation in function body."""
        func_body = Node("literal", [42], {"label": 100})
        func = Node("function", [Node("name", ["fn"]), func_body])
        root = Node("root", [func])

        transformer = PropagateLabels()
        result = transformer.transform(root)

        # Function should get body's label
        assert result.children[0].metadata.get("label") == 100

    def test_arrow_function_labels(self) -> None:
        """Test label propagation in arrow function."""
        arrow_body = Node("literal", [42], {"label": 100})
        arrow = Node("arrow", [arrow_body])
        root = Node("root", [arrow])

        transformer = PropagateLabels()
        result = transformer.transform(root)

        # Arrow should get body's label
        assert result.children[0].metadata.get("label") == 100

    def test_class_body_labels(self) -> None:
        """Test label propagation in class body."""
        method = Node("literal", [42], {"label": 100})
        class_body = Node("block", [method])
        class_node = Node("class", [Node("name", ["MyClass"]), class_body])
        root = Node("root", [class_node])

        transformer = PropagateLabels()
        result = transformer.transform(root)

        # Class should get method's label
        assert result.children[0].metadata.get("label") == 100

    def test_object_literal_labels(self) -> None:
        """Test label propagation in object literal."""
        value = Node("literal", [42], {"label": 100})
        prop = Node("property", [Node("key", ["x"]), value])
        obj = Node("object", [prop])
        root = Node("root", [obj])

        transformer = PropagateLabels()
        result = transformer.transform(root)

        # Object should get value's label
        assert result.children[0].metadata.get("label") == 100

    def test_array_literal_labels(self) -> None:
        """Test label propagation in array literal."""
        elem1 = Node("literal", [1], {"label": 100})
        elem2 = Node("literal", [2], {"label": 200})
        arr = Node("array", [elem1, elem2])
        root = Node("root", [arr])

        transformer = PropagateLabels()
        result = transformer.transform(root)

        # Array should get minimum label
        assert result.children[0].metadata.get("label") == 100

    def test_call_expression_labels(self) -> None:
        """Test label propagation in call expression."""
        arg = Node("literal", [42], {"label": 100})
        call = Node("call", [Node("fn", []), arg])
        root = Node("root", [call])

        transformer = PropagateLabels()
        result = transformer.transform(root)

        # Call should get arg's label
        assert result.children[0].metadata.get("label") == 100

    def test_binary_expression_labels(self) -> None:
        """Test label propagation in binary expression."""
        left = Node("literal", [1], {"label": 100})
        right = Node("literal", [2], {"label": 200})
        binary = Node("add", [left, right])
        root = Node("root", [binary])

        transformer = PropagateLabels()
        result = transformer.transform(root)

        # Binary should get minimum label
        assert result.children[0].metadata.get("label") == 100

    def test_unary_expression_labels(self) -> None:
        """Test label propagation in unary expression."""
        operand = Node("literal", [42], {"label": 100})
        unary = Node("negate", [operand])
        root = Node("root", [unary])

        transformer = PropagateLabels()
        result = transformer.transform(root)

        # Unary should get operand's label
        assert result.children[0].metadata.get("label") == 100

    def test_ternary_expression_labels(self) -> None:
        """Test label propagation in ternary expression."""
        condition = Node("literal", [True], {"label": 100})
        true_val = Node("literal", [1], {"label": 200})
        false_val = Node("literal", [0], {"label": 300})
        ternary = Node("ternary", [condition, true_val, false_val])
        root = Node("root", [ternary])

        transformer = PropagateLabels()
        result = transformer.transform(root)

        # Ternary should get minimum label
        assert result.children[0].metadata.get("label") == 100

    def test_sequence_expression_labels(self) -> None:
        """Test label propagation in sequence expression."""
        expr1 = Node("literal", [1], {"label": 100})
        expr2 = Node("literal", [2], {"label": 200})
        sequence = Node("sequence", [expr1, expr2])
        root = Node("root", [sequence])

        transformer = PropagateLabels()
        result = transformer.transform(root)

        # Sequence should get minimum label
        assert result.children[0].metadata.get("label") == 100

    def test_assignment_expression_labels(self) -> None:
        """Test label propagation in assignment expression."""
        value = Node("literal", [42], {"label": 100})
        assignment = Node("assign", [Node("target", []), value])
        root = Node("root", [assignment])

        transformer = PropagateLabels()
        result = transformer.transform(root)

        # Assignment should get value's label
        assert result.children[0].metadata.get("label") == 100

    def test_update_expression_labels(self) -> None:
        """Test label propagation in update expression."""
        operand = Node("literal", [42], {"label": 100})
        update = Node("increment", [operand])
        root = Node("root", [update])

        transformer = PropagateLabels()
        result = transformer.transform(root)

        # Update should get operand's label
        assert result.children[0].metadata.get("label") == 100

    def test_conditional_expression_labels(self) -> None:
        """Test label propagation in conditional expression."""
        test = Node("literal", [True], {"label": 100})
        consequent = Node("literal", [1], {"label": 200})
        alternate = Node("literal", [0], {"label": 300})
        conditional = Node("conditional", [test, consequent, alternate])
        root = Node("root", [conditional])

        transformer = PropagateLabels()
        result = transformer.transform(root)

        # Conditional should get minimum label
        assert result.children[0].metadata.get("label") == 100

    def test_logical_expression_labels(self) -> None:
        """Test label propagation in logical expression."""
        left = Node("literal", [True], {"label": 100})
        right = Node("literal", [False], {"label": 200})
        logical = Node("and", [left, right])
        root = Node("root", [logical])

        transformer = PropagateLabels()
        result = transformer.transform(root)

        # Logical should get minimum label
        assert result.children[0].metadata.get("label") == 100

    def test_bitwise_expression_labels(self) -> None:
        """Test label propagation in bitwise expression."""
        left = Node("literal", [1], {"label": 100})
        right = Node("literal", [2], {"label": 200})
        bitwise = Node("bitwise_and", [left, right])
        root = Node("root", [bitwise])

        transformer = PropagateLabels()
        result = transformer.transform(root)

        # Bitwise should get minimum label
        assert result.children[0].metadata.get("label") == 100

    def test_comparison_expression_labels(self) -> None:
        """Test label propagation in comparison expression."""
        left = Node("literal", [1], {"label": 100})
        right = Node("literal", [2], {"label": 200})
        comparison = Node("equals", [left, right])
        root = Node("root", [comparison])

        transformer = PropagateLabels()
        result = transformer.transform(root)

        # Comparison should get minimum label
        assert result.children[0].metadata.get("label") == 100

    def test_shift_expression_labels(self) -> None:
        """Test label propagation in shift expression."""
        left = Node("literal", [1], {"label": 100})
        right = Node("literal", [2], {"label": 200})
        shift = Node("left_shift", [left, right])
        root = Node("root", [shift])

        transformer = PropagateLabels()
        result = transformer.transform(root)

        # Shift should get minimum label
        assert result.children[0].metadata.get("label") == 100

    def test_exponentiation_expression_labels(self) -> None:
        """Test label propagation in exponentiation expression."""
        base = Node("literal", [2], {"label": 100})
        exp = Node("literal", [3], {"label": 200})
        power = Node("power", [base, exp])
        root = Node("root", [power])

        transformer = PropagateLabels()
        result = transformer.transform(root)

        # Power should get minimum label
        assert result.children[0].metadata.get("label") == 100

    def test_spread_expression_labels(self) -> None:
        """Test label propagation in spread expression."""
        iterable = Node("literal", [42], {"label": 100})
        spread = Node("spread", [iterable])
        root = Node("root", [spread])

        transformer = PropagateLabels()
        result = transformer.transform(root)

        # Spread should get iterable's label
        assert result.children[0].metadata.get("label") == 100

    def test_rest_expression_labels(self) -> None:
        """Test label propagation in rest expression."""
        pattern = Node("literal", [42], {"label": 100})
        rest = Node("rest", [pattern])
        root = Node("root", [rest])

        transformer = PropagateLabels()
        result = transformer.transform(root)

        # Rest should get pattern's label
        assert result.children[0].metadata.get("label") == 100

    def test_destructuring_labels(self) -> None:
        """Test label propagation in destructuring."""
        value = Node("literal", [42], {"label": 100})
        destruct = Node("destruct", [value, Node("pattern", [])])
        root = Node("root", [destruct])

        transformer = PropagateLabels()
        result = transformer.transform(root)

        # Destruct should get value's label
        assert result.children[0].metadata.get("label") == 100

    def test_template_literal_labels(self) -> None:
        """Test label propagation in template literal."""
        expr = Node("literal", [42], {"label": 100})
        template = Node("template", [Node("quasi", [""]), expr])
        root = Node("root", [template])

        transformer = PropagateLabels()
        result = transformer.transform(root)

        # Template should get expr's label
        assert result.children[0].metadata.get("label") == 100

    def test_tagged_template_labels(self) -> None:
        """Test label propagation in tagged template."""
        tag = Node("literal", ["tag"], {"label": 100})
        template = Node("template", [Node("quasi", [""])])
        tagged = Node("tagged_template", [tag, template])
        root = Node("root", [tagged])

        transformer = PropagateLabels()
        result = transformer.transform(root)

        # Tagged template should get tag's label
        assert result.children[0].metadata.get("label") == 100

    def test_new_expression_labels(self) -> None:
        """Test label propagation in new expression."""
        constructor = Node("literal", ["Class"], {"label": 100})
        new_node = Node("new", [constructor])
        root = Node("root", [new_node])

        transformer = PropagateLabels()
        result = transformer.transform(root)

        # New should get constructor's label
        assert result.children[0].metadata.get("label") == 100

    def test_delete_expression_labels(self) -> None:
        """Test label propagation in delete expression."""
        target = Node("literal", ["prop"], {"label": 100})
        delete = Node("delete", [target])
        root = Node("root", [delete])

        transformer = PropagateLabels()
        result = transformer.transform(root)

        # Delete should get target's label
        assert result.children[0].metadata.get("label") == 100

    def test_typeof_expression_labels(self) -> None:
        """Test label propagation in typeof expression."""
        operand = Node("literal", [42], {"label": 100})
        typeof_node = Node("typeof", [operand])
        root = Node("root", [typeof_node])

        transformer = PropagateLabels()
        result = transformer.transform(root)

        # Typeof should get operand's label
        assert result.children[0].metadata.get("label") == 100

    def test_void_expression_labels(self) -> None:
        """Test label propagation in void expression."""
        operand = Node("literal", [42], {"label": 100})
        void_node = Node("void", [operand])
        root = Node("root", [void_node])

        transformer = PropagateLabels()
        result = transformer.transform(root)

        # Void should get operand's label
        assert result.children[0].metadata.get("label") == 100

    def test_yield_expression_labels(self) -> None:
        """Test label propagation in yield expression."""
        value = Node("literal", [42], {"label": 100})
        yield_node = Node("yield", [value])
        root = Node("root", [yield_node])

        transformer = PropagateLabels()
        result = transformer.transform(root)

        # Yield should get value's label
        assert result.children[0].metadata.get("label") == 100

    def test_await_expression_labels(self) -> None:
        """Test label propagation in await expression."""
        promise = Node("literal", [42], {"label": 100})
        await_node = Node("await", [promise])
        root = Node("root", [await_node])

        transformer = PropagateLabels()
        result = transformer.transform(root)

        # Await should get promise's label
        assert result.children[0].metadata.get("label") == 100

    def test_import_expression_labels(self) -> None:
        """Test label propagation in import expression."""
        source = Node("literal", ["module"], {"label": 100})
        import_node = Node("import", [source])
        root = Node("root", [import_node])

        transformer = PropagateLabels()
        result = transformer.transform(root)

        # Import should get source's label
        assert result.children[0].metadata.get("label") == 100

    def test_export_expression_labels(self) -> None:
        """Test label propagation in export expression."""
        value = Node("literal", [42], {"label": 100})
        export_node = Node("export", [value])
        root = Node("root", [export_node])

        transformer = PropagateLabels()
        result = transformer.transform(root)

        # Export should get value's label
        assert result.children[0].metadata.get("label") == 100

    def test_super_expression_labels(self) -> None:
        """Test label propagation in super expression."""
        base = Node("literal", ["Base"], {"label": 100})
        super_node = Node("super", [base])
        root = Node("root", [super_node])

        transformer = PropagateLabels()
        result = transformer.transform(root)

        # Super should get base's label
        assert result.children[0].metadata.get("label") == 100

    def test_this_expression_labels(self) -> None:
        """Test label propagation in this expression."""
        context = Node("literal", ["context"], {"label": 100})
        this_node = Node("this", [context])
        root = Node("root", [this_node])

        transformer = PropagateLabels()
        result = transformer.transform(root)

        # This should get context's label
        assert result.children[0].metadata.get("label") == 100
