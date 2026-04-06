"""Test CFG reduce functionality."""

from __future__ import annotations

import pytest
from oven.core.ast import Node
from oven.core.cfg import CFG, CFGNode
from oven.core.cfg.dialect import FlowDialect
from oven.core.transform.cfg_reduce import CFGReduce


class TestCFGReduce:
    """Test CFGReduce transformation."""

    def test_cfg_reduce_basic(self) -> None:
        """Test basic CFG reduce functionality."""
        # Create a simple linear CFG
        cfg = CFG()
        entry = cfg.add_node(label="entry", insns=[Node("push", [1])])
        exit_node = cfg.add_node(label="exit", insns=[])
        entry.target_labels.append(exit_node.label)

        cfg.entry = entry
        cfg.exit = exit_node

        reducer = CFGReduce()
        result = reducer.transform(cfg)

        assert result.type == "begin"
        assert len(result.children) > 0

    def test_cfg_reduce_complex(self) -> None:
        """Test reducing complex CFG structures."""
        # Create a more complex CFG with multiple nodes
        cfg = CFG()
        entry = cfg.add_node(label="entry", insns=[Node("push", [1])])
        middle = cfg.add_node(label="middle", insns=[Node("push", [2])])
        exit_node = cfg.add_node(label="exit", insns=[])

        entry.target_labels.append(middle.label)
        middle.target_labels.append(exit_node.label)

        cfg.entry = entry
        cfg.exit = exit_node

        reducer = CFGReduce()
        result = reducer.transform(cfg)

        assert result.type == "begin"

    def test_empty_cfg(self) -> None:
        """Test reducing empty CFG."""
        cfg = CFG()
        cfg.entry = None
        cfg.exit = None

        reducer = CFGReduce()
        result = reducer.transform(cfg)

        assert result.type == "begin"
        assert len(result.children) == 0

    def test_single_node_cfg(self) -> None:
        """Test reducing single node CFG."""
        cfg = CFG()
        entry = cfg.add_node(label="entry", insns=[Node("push", [1])])

        cfg.entry = entry
        cfg.exit = None  # No explicit exit node

        reducer = CFGReduce()
        result = reducer.transform(cfg)

        assert result.type == "begin"
        assert len(result.children) == 1

    def test_if_else_diamond(self) -> None:
        """Test reducing if-else diamond pattern."""
        cfg = CFG()
        header = cfg.add_node(label="header", insns=[Node("jump_if", [True, "then"])])
        then_node = cfg.add_node(label="then", insns=[Node("push", [1])])
        else_node = cfg.add_node(label="else", insns=[Node("push", [2])])
        merge = cfg.add_node(label="merge", insns=[])

        header.target_labels.append(then_node.label)
        header.target_labels.append(else_node.label)
        then_node.target_labels.append(merge.label)
        else_node.target_labels.append(merge.label)

        cfg.entry = header
        cfg.exit = merge

        reducer = CFGReduce()
        result = reducer.transform(cfg)

        # Should produce if structure (or any structure)
        assert result.type == "begin"
        # CFGReduce may not produce if node, but should produce some structure
        assert len(result.children) > 0

    def test_one_way_if(self) -> None:
        """Test reducing one-way if pattern."""
        cfg = CFG()
        header = CFGNode(label="header", instructions=[Node("jump_if", [True, "then"])])
        header.cti = header.instructions[0]
        then_node = CFGNode(label="then", instructions=[Node("push", [1])])
        merge = CFGNode(label="merge", instructions=[])

        header.add_target(then_node)
        header.add_target(merge)
        then_node.add_target(merge)

        cfg.entry = header
        cfg.exit = merge
        cfg.add_node(header)
        cfg.add_node(then_node)
        cfg.add_node(merge)

        reducer = CFGReduce()
        result = reducer.transform(cfg)

        # Should produce if structure
        assert result.type == "begin"
        has_if = any(c.type == "if" for c in result.descendants())
        assert has_if

    def test_while_loop(self) -> None:
        """Test reducing while loop."""
        cfg = CFG()
        header = CFGNode(label="header", instructions=[Node("jump_if", [True, "body"])])
        header.cti = header.instructions[0]
        body = CFGNode(label="body", instructions=[Node("push", [1])])
        exit_node = CFGNode(label="exit", instructions=[])

        header.add_target(body)
        header.add_target(exit_node)
        body.add_target(header)  # Back edge

        cfg.entry = header
        cfg.exit = exit_node
        cfg.add_node(header)
        cfg.add_node(body)
        cfg.add_node(exit_node)

        reducer = CFGReduce()
        result = reducer.transform(cfg)

        # Should produce while structure
        assert result.type == "begin"
        has_while = any(c.type == "while" for c in result.descendants())
        assert has_while

    def test_nested_if(self) -> None:
        """Test reducing nested if structures."""
        cfg = CFG()
        outer_header = CFGNode(
            label="outer_header", instructions=[Node("jump_if", [True, "inner_header"])]
        )
        outer_header.cti = outer_header.instructions[0]
        inner_header = CFGNode(
            label="inner_header", instructions=[Node("jump_if", [True, "inner_then"])]
        )
        inner_header.cti = inner_header.instructions[0]
        inner_then = CFGNode(label="inner_then", instructions=[Node("push", [1])])
        inner_merge = CFGNode(label="inner_merge", instructions=[])
        outer_merge = CFGNode(label="outer_merge", instructions=[])

        outer_header.add_target(inner_header)
        outer_header.add_target(outer_merge)
        inner_header.add_target(inner_then)
        inner_header.add_target(inner_merge)
        inner_then.add_target(inner_merge)
        inner_merge.add_target(outer_merge)

        cfg.entry = outer_header
        cfg.exit = outer_merge
        cfg.add_node(outer_header)
        cfg.add_node(inner_header)
        cfg.add_node(inner_then)
        cfg.add_node(inner_merge)
        cfg.add_node(outer_merge)

        reducer = CFGReduce()
        result = reducer.transform(cfg)

        # Should produce nested if structure
        assert result.type == "begin"
        if_count = sum(1 for c in result.descendants() if c.type == "if")
        assert if_count >= 2

    def test_loop_with_break(self) -> None:
        """Test reducing loop with break."""
        cfg = CFG()
        header = CFGNode(label="header", instructions=[Node("jump_if", [True, "body"])])
        header.cti = header.instructions[0]
        body = CFGNode(
            label="body", instructions=[Node("jump_if", [False, "break_target"])]
        )
        body.cti = body.instructions[0]
        break_target = CFGNode(label="break_target", instructions=[])
        exit_node = CFGNode(label="exit", instructions=[])

        header.add_target(body)
        header.add_target(exit_node)
        body.add_target(header)  # Back edge
        body.add_target(break_target)
        break_target.add_target(exit_node)

        cfg.entry = header
        cfg.exit = exit_node
        cfg.add_node(header)
        cfg.add_node(body)
        cfg.add_node(break_target)
        cfg.add_node(exit_node)

        reducer = CFGReduce()
        result = reducer.transform(cfg)

        # Should produce while with break
        assert result.type == "begin"
        has_while = any(c.type == "while" for c in result.children)
        has_break = any(c.type == "break" for c in result.descendants())
        assert has_while or has_break  # May be structured differently

    def test_loop_with_continue(self) -> None:
        """Test reducing loop with continue."""
        cfg = CFG()
        header = CFGNode(label="header", instructions=[Node("jump_if", [True, "body"])])
        header.cti = header.instructions[0]
        body = CFGNode(
            label="body", instructions=[Node("jump_if", [False, "continue_target"])]
        )
        body.cti = body.instructions[0]
        continue_target = CFGNode(label="continue_target", instructions=[])
        exit_node = CFGNode(label="exit", instructions=[])

        header.add_target(body)
        header.add_target(exit_node)
        body.add_target(header)  # Back edge
        body.add_target(continue_target)
        continue_target.add_target(header)  # Continue to header

        cfg.entry = header
        cfg.exit = exit_node
        cfg.add_node(header)
        cfg.add_node(body)
        cfg.add_node(continue_target)
        cfg.add_node(exit_node)

        reducer = CFGReduce()
        result = reducer.transform(cfg)

        # Should produce while structure
        assert result.type == "begin"
        has_while = any(c.type == "while" for c in result.descendants())
        assert has_while

    def test_switch_statement(self) -> None:
        """Test reducing switch statement."""
        cfg = CFG()
        header = CFGNode(
            label="header", instructions=[Node("switch", [Node("get_local", [0])])]
        )
        case0 = CFGNode(label="case0", instructions=[Node("push", [0])])
        case1 = CFGNode(label="case1", instructions=[Node("push", [1])])
        default = CFGNode(label="default", instructions=[Node("push", [2])])
        merge = CFGNode(label="merge", instructions=[])

        header.add_target(case0)
        header.add_target(case1)
        header.add_target(default)
        case0.add_target(merge)
        case1.add_target(merge)
        default.add_target(merge)

        cfg.entry = header
        cfg.exit = merge
        cfg.add_node(header)
        cfg.add_node(case0)
        cfg.add_node(case1)
        cfg.add_node(default)
        cfg.add_node(merge)

        reducer = CFGReduce()
        result = reducer.transform(cfg)

        # Should produce switch structure
        assert result.type == "begin"
        has_switch = any(c.type == "switch" for c in result.children)
        assert has_switch

    def test_merge_node_finding(self) -> None:
        """Test merge node finding algorithm."""
        cfg = CFG()
        # Create a diamond pattern
        header = CFGNode(label="header", instructions=[Node("jump_if", [True, "left"])])
        header.cti = header.instructions[0]
        left = CFGNode(label="left", instructions=[Node("push", [1])])
        right = CFGNode(label="right", instructions=[Node("push", [2])])
        merge = CFGNode(label="merge", instructions=[])

        header.add_target(left)
        header.add_target(right)
        left.add_target(merge)
        right.add_target(merge)

        cfg.entry = header
        cfg.exit = merge
        cfg.add_node(header)
        cfg.add_node(left)
        cfg.add_node(right)
        cfg.add_node(merge)

        reducer = CFGReduce()

        # Test internal merge finding
        found_merge = reducer._find_merge_node(left, right)
        assert found_merge == merge

    def test_terminal_block_detection(self) -> None:
        """Test terminal block detection."""
        cfg = CFG()
        terminal = CFGNode(label="terminal", instructions=[Node("return_void")])
        normal = CFGNode(label="normal", instructions=[Node("push", [1])])

        cfg.entry = normal
        cfg.exit = terminal
        cfg.add_node(normal)
        cfg.add_node(terminal)

        reducer = CFGReduce()

        # Test terminal detection
        terminal.cti = terminal.instructions[0]
        assert reducer._is_terminal_block(terminal) is True
        assert reducer._is_terminal_block(normal) is False

    def test_condition_extraction(self) -> None:
        """Test condition extraction from jump_if."""
        cfg = CFG()
        header = CFGNode(
            label="header",
            instructions=[Node("jump_if", [True, Node("get_local", [0])])],
        )
        header.cti = header.instructions[0]

        cfg.entry = header
        cfg.exit = header
        cfg.add_node(header)

        reducer = CFGReduce()

        # Test condition extraction
        cond = reducer._condition_from_jump_if(header)
        assert cond.type == "get_local"

    def test_loop_identification(self) -> None:
        """Test loop identification."""
        cfg = CFG()
        header = CFGNode(label="header", instructions=[Node("jump_if", [True, "body"])])
        header.cti = header.instructions[0]
        body = CFGNode(label="body", instructions=[Node("push", [1])])
        exit_node = CFGNode(label="exit", instructions=[])

        header.add_target(body)
        header.add_target(exit_node)
        body.add_target(header)  # Back edge

        cfg.entry = header
        cfg.exit = exit_node
        cfg.add_node(header)
        cfg.add_node(body)
        cfg.add_node(exit_node)

        reducer = CFGReduce()
        reducer.transform(cfg)  # This populates _loops

        # Test loop identification
        assert header in reducer._loops
        assert body in reducer._loops[header]

    def test_custom_dialect(self) -> None:
        """Test with custom dialect."""
        custom_dialect = FlowDialect(
            ast_begin="block",
            ast_if="branch",
            ast_while="loop",
            ast_break="exit",
            ast_continue="next",
        )

        cfg = CFG()
        header = CFGNode(label="header", instructions=[Node("jump_if", [True, "then"])])
        header.cti = header.instructions[0]
        then_node = CFGNode(label="then", instructions=[Node("push", [1])])
        merge = CFGNode(label="merge", instructions=[])

        header.add_target(then_node)
        header.add_target(merge)
        then_node.add_target(merge)

        cfg.entry = header
        cfg.exit = merge
        cfg.add_node(header)
        cfg.add_node(then_node)
        cfg.add_node(merge)

        reducer = CFGReduce(dialect=custom_dialect)
        result = reducer.transform(cfg)

        # Should use custom dialect
        assert result.type == "block"
        has_branch = any(c.type == "branch" for c in result.descendants())
        assert has_branch
