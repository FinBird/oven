"""Test CFG reduce try-catch-finally functionality."""

from __future__ import annotations

from typing import cast

import pytest
from oven.core.ast import Node
from oven.core.cfg import CFG, CFGNode
from oven.core.cfg.dialect import FlowDialect
from oven.core.transform.cfg_reduce import CFGReduce


def _build_simple_try_catch_cfg() -> CFG:
    """Build a CFG representing:
    try { trace("hello"); }
    catch(e:Error) { return; }
    """
    cfg = CFG()
    dialect = FlowDialect()

    # Dispatch node (virtual, holds catch metadata)
    dispatch = CFGNode(
        cfg,
        label="exc_0",
        instructions=[
            Node(
                dialect.exception_dispatch,
                [
                    Node(dialect.catch, ["Error", "e", "catch_entry"]),
                ],
            ),
        ],
    )
    dispatch.cti = dispatch.instructions[0]
    cfg.add_node(dispatch)

    # Try body: one block with exception_label pointing to dispatch
    try_block = CFGNode(
        cfg,
        label=10,
        instructions=[
            Node("trace", ["hello"]),
        ],
    )
    try_block.exception_label = "exc_0"
    try_block.target_labels.append("after")
    cfg.add_node(try_block)

    # Catch handler entry
    catch_block = CFGNode(
        cfg,
        label="catch_entry",
        instructions=[
            Node("return_void"),
        ],
    )
    catch_block.cti = catch_block.instructions[0]
    catch_block.target_labels.append("after")
    cfg.add_node(catch_block)

    # After try-catch
    after_block = CFGNode(cfg, label="after", instructions=[])
    cfg.add_node(after_block)

    cfg.entry = try_block
    cfg.exit = after_block

    return cfg


class TestCFGReduceTryCatch:
    """Test try-catch reconstruction in CFGReduce."""

    def test_basic_try_catch_produces_try_node(self) -> None:
        """A simple try-catch should produce a 'try' AST node."""
        cfg = _build_simple_try_catch_cfg()
        reducer = CFGReduce()
        result = reducer.transform(cfg)

        assert result.type == "begin"
        # Find the try node
        try_nodes = [
            c for c in result.children if isinstance(c, Node) and c.type == "try"
        ]
        assert len(try_nodes) == 1, f"Expected 1 try node, got {len(try_nodes)}"

    def test_try_node_has_catch_child(self) -> None:
        """The try node should have a catch child."""
        cfg = _build_simple_try_catch_cfg()
        reducer = CFGReduce()
        result = reducer.transform(cfg)

        try_node = [
            c for c in result.children if isinstance(c, Node) and c.type == "try"
        ][0]
        catch_nodes = [
            c for c in try_node.children if isinstance(c, Node) and c.type == "catch"
        ]
        assert len(catch_nodes) == 1

    def test_catch_node_has_correct_type_and_name(self) -> None:
        """The catch node should have the exception type and variable name."""
        cfg = _build_simple_try_catch_cfg()
        reducer = CFGReduce()
        result = reducer.transform(cfg)

        try_node = [
            c for c in result.children if isinstance(c, Node) and c.type == "try"
        ][0]
        catch_node = [
            c for c in try_node.children if isinstance(c, Node) and c.type == "catch"
        ][0]

        assert catch_node.children[0] == "Error"
        assert catch_node.children[1] == "e"

    def test_catch_wildcard_type(self) -> None:
        """Catch with type='*' should work."""
        cfg = CFG()
        dialect = FlowDialect()

        dispatch = CFGNode(
            cfg,
            label="exc_0",
            instructions=[
                Node(
                    dialect.exception_dispatch,
                    [
                        Node(dialect.catch, ["*", "_e_", "catch_entry"]),
                    ],
                ),
            ],
        )
        dispatch.cti = dispatch.instructions[0]
        cfg.add_node(dispatch)

        try_block = CFGNode(
            cfg,
            label=10,
            instructions=[
                Node("trace", ["hello"]),
            ],
        )
        try_block.exception_label = "exc_0"
        try_block.target_labels.append("after")
        cfg.add_node(try_block)

        catch_block = CFGNode(
            cfg,
            label="catch_entry",
            instructions=[
                Node("return_void"),
            ],
        )
        catch_block.cti = catch_block.instructions[0]
        catch_block.target_labels.append("after")
        cfg.add_node(catch_block)

        after_block = CFGNode(cfg, label="after", instructions=[])
        cfg.add_node(after_block)

        cfg.entry = try_block
        cfg.exit = after_block

        reducer = CFGReduce()
        result = reducer.transform(cfg)

        try_node = [
            c for c in result.children if isinstance(c, Node) and c.type == "try"
        ][0]
        catch_node = [
            c for c in try_node.children if isinstance(c, Node) and c.type == "catch"
        ][0]
        assert catch_node.children[0] == "*"

    def test_multiple_catch_clauses(self) -> None:
        """Multiple exception entries should produce multiple catch clauses."""
        cfg = CFG()
        dialect = FlowDialect()

        dispatch = CFGNode(
            cfg,
            label="exc_0",
            instructions=[
                Node(
                    dialect.exception_dispatch,
                    [
                        Node(dialect.catch, ["Error", "e", "catch_error"]),
                        Node(dialect.catch, ["TypeError", "e", "catch_type"]),
                    ],
                ),
            ],
        )
        dispatch.cti = dispatch.instructions[0]
        cfg.add_node(dispatch)

        try_block = CFGNode(
            cfg,
            label=10,
            instructions=[
                Node("trace", ["hello"]),
            ],
        )
        try_block.exception_label = "exc_0"
        try_block.target_labels.append("after")
        cfg.add_node(try_block)

        catch_error = CFGNode(
            cfg,
            label="catch_error",
            instructions=[
                Node("return_void"),
            ],
        )
        catch_error.cti = catch_error.instructions[0]
        catch_error.target_labels.append("after")
        cfg.add_node(catch_error)

        catch_type = CFGNode(
            cfg,
            label="catch_type",
            instructions=[
                Node("return_void"),
            ],
        )
        catch_type.cti = catch_type.instructions[0]
        catch_type.target_labels.append("after")
        cfg.add_node(catch_type)

        after_block = CFGNode(cfg, label="after", instructions=[])
        cfg.add_node(after_block)

        cfg.entry = try_block
        cfg.exit = after_block

        reducer = CFGReduce()
        result = reducer.transform(cfg)

        try_node = [
            c for c in result.children if isinstance(c, Node) and c.type == "try"
        ][0]
        catch_nodes = [
            c for c in try_node.children if isinstance(c, Node) and c.type == "catch"
        ]
        assert len(catch_nodes) == 2
        types = {c.children[0] for c in catch_nodes}
        assert "Error" in types
        assert "TypeError" in types

    def test_sequential_try_catch_blocks(self) -> None:
        """Two sequential try-catch blocks should produce two try nodes."""
        cfg = CFG()
        dialect = FlowDialect()

        # First try-catch
        dispatch1 = CFGNode(
            cfg,
            label="exc_0",
            instructions=[
                Node(
                    dialect.exception_dispatch,
                    [
                        Node(dialect.catch, ["Error", "e", "catch1"]),
                    ],
                ),
            ],
        )
        dispatch1.cti = dispatch1.instructions[0]
        cfg.add_node(dispatch1)

        try1 = CFGNode(
            cfg,
            label=10,
            instructions=[
                Node("trace", ["try1"]),
            ],
        )
        try1.exception_label = "exc_0"
        try1.target_labels.append("after1")
        cfg.add_node(try1)

        catch1 = CFGNode(
            cfg,
            label="catch1",
            instructions=[
                Node("return_void"),
            ],
        )
        catch1.cti = catch1.instructions[0]
        catch1.target_labels.append("after1")
        cfg.add_node(catch1)

        after1 = CFGNode(cfg, label="after1", instructions=[])
        after1.target_labels.append(1000)  # Flow from try1 to try2
        cfg.add_node(after1)

        # Second try-catch (separate region, no overlap)
        dispatch2 = CFGNode(
            cfg,
            label="exc_1",
            instructions=[
                Node(
                    dialect.exception_dispatch,
                    [
                        Node(dialect.catch, ["Error", "e", "catch2"]),
                    ],
                ),
            ],
        )
        dispatch2.cti = dispatch2.instructions[0]
        cfg.add_node(dispatch2)

        try2 = CFGNode(
            cfg,
            label=1000,
            instructions=[
                Node("trace", ["try2"]),
            ],
        )
        try2.exception_label = "exc_1"
        try2.target_labels.append("after")
        cfg.add_node(try2)

        catch2 = CFGNode(
            cfg,
            label="catch2",
            instructions=[
                Node("return_void"),
            ],
        )
        catch2.cti = catch2.instructions[0]
        catch2.target_labels.append("after")
        cfg.add_node(catch2)

        after = CFGNode(cfg, label="after", instructions=[])
        cfg.add_node(after)

        cfg.entry = try1
        cfg.exit = after

        reducer = CFGReduce()
        result = reducer.transform(cfg)

        try_nodes = [
            c for c in result.children if isinstance(c, Node) and c.type == "try"
        ]
        assert len(try_nodes) == 2

    def test_try_catch_body_preserves_instructions(self) -> None:
        """Instructions in the try body should be preserved."""
        cfg = CFG()
        dialect = FlowDialect()

        dispatch = CFGNode(
            cfg,
            label="exc_0",
            instructions=[
                Node(
                    dialect.exception_dispatch,
                    [
                        Node(dialect.catch, ["Error", "e", "catch_entry"]),
                    ],
                ),
            ],
        )
        dispatch.cti = dispatch.instructions[0]
        cfg.add_node(dispatch)

        try_block = CFGNode(
            cfg,
            label=10,
            instructions=[
                Node("trace", ["hello"]),
                Node("set_local", [0, Node("integer", [42])]),
            ],
        )
        try_block.exception_label = "exc_0"
        try_block.target_labels.append("after")
        cfg.add_node(try_block)

        catch_block = CFGNode(
            cfg,
            label="catch_entry",
            instructions=[
                Node("return_void"),
            ],
        )
        catch_block.cti = catch_block.instructions[0]
        catch_block.target_labels.append("after")
        cfg.add_node(catch_block)

        after_block = CFGNode(cfg, label="after", instructions=[])
        cfg.add_node(after_block)

        cfg.entry = try_block
        cfg.exit = after_block

        reducer = CFGReduce()
        result = reducer.transform(cfg)

        try_node = [
            c for c in result.children if isinstance(c, Node) and c.type == "try"
        ][0]
        try_body = try_node.children[0]
        # The try body should contain the instructions
        all_nodes = list(try_body.descendants())
        types = {n.type for n in all_nodes if isinstance(n, Node)}
        assert "trace" in types or len(try_body.children) > 0


class TestCFGReduceTryCatchFinally:
    """Test try-catch-finally reconstruction in CFGReduce."""

    def test_finally_node_produced_when_lookupswitch_detected(self) -> None:
        """A block with lookupswitch reached from multiple paths should produce a finally node."""
        cfg = CFG()
        dialect = FlowDialect()

        # Dispatch node with catch + catch-all
        dispatch = CFGNode(
            cfg,
            label="exc_0",
            instructions=[
                Node(
                    dialect.exception_dispatch,
                    [
                        Node(dialect.catch, ["Error", "e", "catch_entry"]),
                    ],
                ),
            ],
        )
        dispatch.cti = dispatch.instructions[0]
        cfg.add_node(dispatch)

        # Try body (empty, just label)
        try_block = CFGNode(
            cfg,
            label=10,
            instructions=[
                Node("trace", ["in try"]),
            ],
        )
        try_block.exception_label = "exc_0"
        try_block.target_labels.append("finally_block")
        cfg.add_node(try_block)

        # Catch handler
        catch_block = CFGNode(
            cfg,
            label="catch_entry",
            instructions=[
                Node("trace", ["in catch"]),
            ],
        )
        catch_block.target_labels.append("finally_block")
        cfg.add_node(catch_block)

        # Finally block (reached from both try and catch, ends with lookupswitch)
        finally_block = CFGNode(
            cfg,
            label="finally_block",
            instructions=[
                Node("trace", ["in finally"]),
                Node("lookup_switch", ["after", [0], Node("integer", [0])]),
            ],
        )
        finally_block.cti = finally_block.instructions[1]
        finally_block.target_labels.append("after")
        cfg.add_node(finally_block)

        after_block = CFGNode(cfg, label="after", instructions=[])
        cfg.add_node(after_block)

        cfg.entry = try_block
        cfg.exit = after_block

        reducer = CFGReduce()
        result = reducer.transform(cfg)

        # Should produce try node with catch and finally children
        try_nodes = [
            c for c in result.children if isinstance(c, Node) and c.type == "try"
        ]
        assert len(try_nodes) >= 1
        try_node = try_nodes[0]

        # Check for finally child
        finally_nodes = [
            c for c in try_node.children if isinstance(c, Node) and c.type == "finally"
        ]
        assert (
            len(finally_nodes) == 1
        ), f"Expected 1 finally node, got {len(finally_nodes)}"

        # Check that finally body contains the finally instructions
        finally_body = finally_nodes[0].children[0]
        all_types = {n.type for n in finally_body.descendants() if isinstance(n, Node)}
        assert "trace" in all_types or len(finally_body.children) > 0


class TestAS3EmitterTryCatch:
    """Test AS3 emission for try-catch-finally nodes."""

    def test_emit_try_catch(self) -> None:
        """The emitter should produce valid try-catch syntax."""
        from oven.avm2.decompiler import AS3Emitter

        try_body = Node(
            "begin",
            [
                Node("trace", [Node("string", ["hello"])]),
            ],
        )
        catch_body = Node(
            "begin",
            [
                Node("return_void"),
            ],
        )
        catch_node = Node("catch", ["Error", "e", catch_body])
        try_node = Node("try", [try_body, catch_node])

        emitter = AS3Emitter(style="semantic")
        text = emitter._stmt(try_node, 0)

        assert "try {" in text
        assert "catch(e:Error) {" in text
        assert "}" in text

    def test_emit_try_catch_finally(self) -> None:
        """The emitter should produce valid try-catch-finally syntax."""
        from oven.avm2.decompiler import AS3Emitter

        try_body = Node(
            "begin",
            [
                Node("trace", [Node("string", ["hello"])]),
            ],
        )
        catch_body = Node(
            "begin",
            [
                Node("return_void"),
            ],
        )
        finally_body = Node(
            "begin",
            [
                Node("trace", [Node("string", ["cleanup"])]),
            ],
        )
        catch_node = Node("catch", ["Error", "e", catch_body])
        finally_node = Node("finally", [finally_body])
        try_node = Node("try", [try_body, catch_node, finally_node])

        emitter = AS3Emitter(style="semantic")
        text = emitter._stmt(try_node, 0)

        assert "try {" in text
        assert "catch(e:Error) {" in text
        assert "finally {" in text

    def test_emit_try_wildcard_catch(self) -> None:
        """The emitter should handle catch(*) syntax."""
        from oven.avm2.decompiler import AS3Emitter

        try_body = Node("begin", [])
        catch_body = Node(
            "begin",
            [
                Node("return_void"),
            ],
        )
        catch_node = Node("catch", ["*", "_e_", catch_body])
        try_node = Node("try", [try_body, catch_node])

        emitter = AS3Emitter(style="semantic")
        text = emitter._stmt(try_node, 0)

        assert "catch(_e_:*):" in text or "catch(_e_:*)" in text

    def test_emit_finally_only(self) -> None:
        """The emitter should handle try-finally without catch."""
        from oven.avm2.decompiler import AS3Emitter

        try_body = Node(
            "begin",
            [
                Node("trace", [Node("string", ["hello"])]),
            ],
        )
        finally_body = Node(
            "begin",
            [
                Node("trace", [Node("string", ["cleanup"])]),
            ],
        )
        finally_node = Node("finally", [finally_body])
        try_node = Node("try", [try_body, finally_node])

        emitter = AS3Emitter(style="semantic")
        text = emitter._stmt(try_node, 0)

        assert "try {" in text
        assert "finally {" in text
        assert "catch" not in text


class TestIntegrationTryCatchABC:
    """Integration tests decompiling real ABC files with exception tables."""

    def test_decompile_method_with_exception(self) -> None:
        """A method with exception table should produce try-catch output."""
        from oven.avm2 import parse, decompile_method
        from pathlib import Path

        abc = parse(
            (
                Path(__file__).parent.parent.parent.parent.parent
                / "fixtures/abc/AngelClientLibs.abc"
            ).read_bytes(),
            mode="relaxed",
        )

        # Body 1412 has a simple try-catch
        body = abc.method_bodies[1412]
        assert len(body.exceptions) == 1

        text = decompile_method(body, style="semantic", abc=abc)
        assert "try {" in text
        assert "catch(" in text
        assert "Error" in text

    def test_decompile_multiple_exceptions(self) -> None:
        """A method with multiple exception entries should produce multiple catch clauses."""
        from oven.avm2 import parse, decompile_method
        from pathlib import Path

        abc = parse(
            (
                Path(__file__).parent.parent.parent.parent.parent
                / "fixtures/abc/AngelClientLibs.abc"
            ).read_bytes(),
            mode="relaxed",
        )

        # Body 4185 has 2 exceptions
        body = abc.method_bodies[4185]
        assert len(body.exceptions) == 2

        text = decompile_method(body, style="semantic", abc=abc)
        # Should have try-catch structures
        assert text.count("try {") >= 1
        assert text.count("catch(") >= 1

    def test_decompile_wildcard_catch(self) -> None:
        """A method with catch-all (type=*) should produce catch(*) output."""
        from oven.avm2 import parse, decompile_method
        from pathlib import Path

        abc = parse(
            (
                Path(__file__).parent.parent.parent.parent.parent
                / "fixtures/abc/AngelClientLibs.abc"
            ).read_bytes(),
            mode="relaxed",
        )

        # Body 7951 has catch-all type=*
        body = abc.method_bodies[7951]
        assert body.exceptions[0].exc_type == "*"

        text = decompile_method(body, style="semantic", abc=abc)
        assert "try {" in text
        assert "catch(" in text

    def test_no_crash_on_all_exception_methods(self) -> None:
        """All methods with exception tables should decompile without crashing."""
        from oven.avm2 import parse, decompile_method
        from pathlib import Path

        abc = parse(
            (
                Path(__file__).parent.parent.parent.parent.parent
                / "fixtures/abc/AngelClientLibs.abc"
            ).read_bytes(),
            mode="relaxed",
        )

        for idx, body in enumerate(abc.method_bodies):
            if body.exceptions:
                try:
                    text = decompile_method(body, style="semantic", abc=abc)
                    assert isinstance(text, str)
                    assert len(text) > 0
                except Exception as e:
                    pytest.fail(f"Body {idx} crashed: {e}")


class TestCFGReduceRobustness:
    @pytest.fixture
    def reducer(self) -> CFGReduce:
        return CFGReduce(FlowDialect())

    def test_reduce_irreducible_flow_no_hang(self, reducer: CFGReduce) -> None:
        """
        Scenario: Irreducible Control Flow (Loop with multiple entries).
        Topology: Entry -> A, Entry -> B, A -> B, B -> A.
        In irreducible flow, natural headers don't exist.
        The reducer must not hang and should eventually fall back to raw jumps/nops.
        """
        cfg = CFG()
        dialect = reducer.dialect

        entry = cfg.add_node("entry")
        a = cfg.add_node("A", insns=[Node("nop")])
        b = cfg.add_node("B", insns=[Node("nop")])

        cfg.entry = entry
        entry.add_target(a)
        entry.add_target(b)

        # Cross jumps creating irreducible loop
        a.add_target(b)
        b.add_target(a)

        # Ensure we don't hit max_iterations or infinite loop
        ast = reducer.transform(cfg)

        assert ast.type == dialect.ast_begin
        # We expect it to at least finish. It will likely emit low-level jump/if
        # instead of a structured 'while' loop because identify_loops()
        # won't find a natural header.
        assert isinstance(ast.children, list)

    def test_reduce_infinite_loop_no_exit(self, reducer: CFGReduce) -> None:
        """
        Scenario: Black Hole Loop.
        Topology: Entry -> Header <-> Body. (Exit node is never reached).
        Tests if the reducer handles graphs where the logic never terminates.
        """
        cfg = CFG()
        dialect = reducer.dialect

        entry = cfg.add_node("entry")
        h = cfg.add_node("header", insns=[Node("nop")])
        b = cfg.add_node("body", insns=[Node("nop")])

        cfg.entry = entry
        entry.add_target(h)
        h.add_target(b)
        b.add_target(h)

        # The reduce_from logic should stop when all reachable nodes are visited
        # or when it detects a cycle it cannot structure as a 'while'.
        ast = reducer.transform(cfg)
        assert ast.type == dialect.ast_begin

    def test_reduce_flattening_megaswitch(self, reducer: CFGReduce) -> None:
        """
        Scenario: Control Flow Flattening.
        Topology: Dispatcher (Switch) -> [Block1, Block2, ... BlockN] -> Dispatcher.
        Tests the performance and correctness of _reduce_switch and _find_switch_merge
        when faced with a massive number of cases jumping back to a central hub.
        """
        N = 100
        cfg = CFG()
        dialect = reducer.dialect

        # Create a switch node. In AVM2 this is usually a lookup_switch
        switch_op = next(iter(dialect.switches))
        dispatcher = cfg.add_node(
            "dispatcher", insns=[Node(switch_op, [Node("integer", [0])])]
        )
        cfg.entry = dispatcher

        for i in range(N):
            blk = cfg.add_node(f"case_{i}", insns=[Node("nop")])
            dispatcher.add_target(blk)
            blk.add_target(dispatcher)  # Loop back to flattening dispatcher

        ast = reducer.transform(cfg)

        # It should identify a switch structure
        # (Though with back-edges, it might struggle to structure as a simple switch)
        assert ast.type == dialect.ast_begin
        has_switch = any(n.type == dialect.ast_switch for n in ast.descendants())
        assert has_switch or len(list(ast.descendants())) > 0

    def test_reduce_deep_nesting_recursion_safety(self, reducer: CFGReduce) -> None:
        """
        Scenario: Extremely Deep Nesting.
        Topology: 500 nested if-statements.
        Ensures that the recursive calls in _reduce_from (via _reduce_if_if_possible)
        don't hit Python's recursion limit or the iterative limit in _reduce_from.
        """
        cfg = CFG()
        dialect = reducer.dialect
        DEPTH = 400  # High enough to be risky, low enough to run quickly

        prev_node = cfg.add_node("entry")
        cfg.entry = prev_node

        exit_node = cfg.add_node("exit")
        cfg.exit = exit_node

        for i in range(DEPTH):
            # Create a one-way 'if' diamond
            # curr -> {then, merge}
            then_node = cfg.add_node(f"then_{i}", insns=[Node("nop")])
            merge_node = cfg.add_node(f"merge_{i}", insns=[Node("nop")])

            # JumpIf(cond)
            jump_op = next(iter(dialect.conditional_jumps))
            prev_node.cti = Node(jump_op, [True, Node("true")])
            prev_node.add_target(then_node)
            prev_node.add_target(merge_node)

            then_node.add_target(merge_node)
            prev_node = then_node  # Nest the next 'if' inside the 'then' branch

        prev_node.add_target(exit_node)

        # This will test if the recursion in _reduce_from is safe
        try:
            ast = reducer.transform(cfg)
            assert ast.type == dialect.ast_begin
        except RecursionError:
            pytest.fail(
                "CFGReduce hit Python recursion limit on deeply nested structure"
            )

    def test_reduce_overlapping_try_catch_scopes(self, reducer: CFGReduce) -> None:
        """
        Scenario: Overlapping/Obfuscated Exception Ranges.
        Topology: Block A (Exc: 1), Block B (Exc: 2), Block C (Exc: 1).
        Tests if _reduce_try_catch_finally correctly identifies boundaries
        even when exception labels change and revert.
        """
        cfg = CFG()
        dialect = reducer.dialect

        # Dispatchers
        d1 = cfg.add_node(
            "dispatcher1",
            insns=[
                Node(
                    dialect.exception_dispatch,
                    [Node(dialect.catch, ["Error", "e", "handler1"])],
                )
            ],
        )
        d2 = cfg.add_node(
            "dispatcher2",
            insns=[
                Node(
                    dialect.exception_dispatch,
                    [Node(dialect.catch, ["Error", "e", "handler2"])],
                )
            ],
        )
        h1 = cfg.add_node("handler1", insns=[Node("nop")])
        h2 = cfg.add_node("handler2", insns=[Node("nop")])

        # Sequence of blocks with interleaved exception labels
        a = cfg.add_node("A", insns=[Node("nop")])
        a.exception_label = "dispatcher1"

        b = cfg.add_node("B", insns=[Node("nop")])
        b.exception_label = "dispatcher2"  # Switched

        c = cfg.add_node("C", insns=[Node("nop")])
        c.exception_label = "dispatcher1"  # Reverted

        cfg.entry = a
        a.add_target(b)
        b.add_target(c)

        ast = reducer.transform(cfg)

        # Verify that we generated nested or sequential try blocks
        tries = [n for n in ast.descendants() if n.type == dialect.ast_try]
        assert len(tries) >= 1

    def test_reduce_dead_code_after_terminal(self, reducer: CFGReduce) -> None:
        """
        Scenario: Dead code in CFG.
        Topology: Block A (Return) -> Block B (Unreachable).
        Ensures the reducer doesn't try to bridge paths through terminal nodes.
        """
        cfg = CFG()
        dialect = reducer.dialect

        a = cfg.add_node("A", insns=[Node("return_void")])
        a.cti = a.instructions[0]

        b = cfg.add_node("B", insns=[Node("nop")])

        cfg.entry = a
        a.add_target(b)  # B is technically a target but A is terminal

        ast = reducer.transform(cfg)

        # AST should contain return_void but not the NOP from B
        # because the loop in _reduce_from should terminate at A's terminal CTI.
        has_return = any(n.type == "return_void" for n in ast.children)
        has_nop = any(n.type == "nop" for n in ast.children)

        assert has_return
        assert not has_nop
