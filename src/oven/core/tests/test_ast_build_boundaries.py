"""Test AST building boundary conditions."""

from __future__ import annotations

import pytest
from oven.core.ast import Node


def test_ast_build_empty_children() -> None:
    """Test building AST with empty children."""
    node = Node("test", [])
    assert node.type == "test"
    assert node.children == []
    assert len(node) == 0


def test_ast_build_none_children() -> None:
    """Test building AST with None children."""
    node = Node("test", None)
    assert node.type == "test"
    assert node.children == []


def test_ast_build_deep_nesting() -> None:
    """Test building deeply nested AST."""
    current = Node("leaf", [1])
    for i in range(100):
        current = Node(f"level{i}", [current])

    assert current.type == "level99"
    assert len(current) == 1


def test_ast_build_wide_structure() -> None:
    """Test building wide AST structure."""
    children = [Node(f"child{i}", [i]) for i in range(1000)]
    parent = Node("parent", children)

    assert len(parent) == 1000
    assert parent[0].type == "child0"
    assert parent[999].type == "child999"
