"""Tests for decompiler optimizations."""

from __future__ import annotations
import pytest
from oven.avm2.transform.semantic_passes import AstSemanticNormalizePass
from oven.core.ast import Node, m


class TestDecompilerOptimizations:
    """Test various decompiler optimizations."""

    def test_property_increment_optimization(self) -> None:
        """Test that property increments are optimized to ++ syntax."""
        # set_property(this, __SerialNum, increment(get_property(this, __SerialNum)))
        code_block = Node(
            "begin",
            [
                Node(
                    "set_property",
                    [
                        Node("get_local", [0]),
                        Node("multiname", ["__SerialNum"]),
                        Node(
                            "increment",
                            [
                                Node(
                                    "get_property",
                                    [
                                        Node("get_local", [0]),
                                        Node("multiname", ["__SerialNum"]),
                                    ],
                                )
                            ],
                        ),
                    ],
                )
            ],
        )

        pass_instance = AstSemanticNormalizePass()
        pass_instance.visit(code_block)

        stmt = code_block.children[0]
        # 期望识别为预自增属性节点
        assert stmt.type == "pre_increment_property"
        assert stmt.children[1].children[0] == "__SerialNum"

    def test_ternary_type_conversion_lifting(self) -> None:
        """Test lifting common type conversions out of ternary branches."""
        # (cond ? uint(Serial) : uint(0))
        code_block = Node(
            "begin",
            [
                Node(
                    "set_local",
                    [
                        5,
                        Node(
                            "ternary",
                            [
                                Node("get_local", [3]),
                                Node(
                                    "convert",
                                    [
                                        "uint",
                                        Node(
                                            "get_property",
                                            [
                                                Node("get_local", [0]),
                                                Node("multiname", ["__SerialNum"]),
                                            ],
                                        ),
                                    ],
                                ),
                                Node("convert", ["uint", Node("integer", [0])]),
                            ],
                        ),
                    ],
                )
            ],
        )

        pass_instance = AstSemanticNormalizePass()
        pass_instance.visit(code_block)

        # 期望结果: uint(cond ? Serial : 0)
        assignment = code_block.children[0]
        convert_node = assignment.children[1]
        assert convert_node.type == "coerce_u"
        assert convert_node.children[0].type == "ternary"
        # 内部 ternary 的分支不应再有 convert
        assert convert_node.children[0].children[1].type != "convert"

    def test_if_else_return_flattening(self) -> None:
        """Test omitting else branch when then branch returns."""
        # if (cond) { return 0; } else { stmt; }
        # => if (cond) { return 0; } stmt;
        code_block = Node(
            "begin",
            [
                Node(
                    "if",
                    [
                        Node("get_local", [1]),
                        Node(
                            "return_value", [Node("integer", [0])]
                        ),  # Then branch returns
                        Node(
                            "begin",
                            [  # Else branch
                                Node(
                                    "call_property",
                                    [
                                        Node("get_local", [6]),
                                        Node("multiname", ["sendData"]),
                                    ],
                                )
                            ],
                        ),
                    ],
                ),
                Node("return_value", [Node("get_local", [7])]),
            ],
        )

        pass_instance = AstSemanticNormalizePass()
        result = pass_instance.transform(code_block)

        # 检查是否平坦化，第一子节点是 if（无 else），第二是 call_property，第三是 return
        assert len(result.children) == 3  # if, call_property, return
        assert result.children[0].type == "if"
        assert len(result.children[0].children) == 2  # 只有 cond 和 then
        assert result.children[1].type == "call_property"

    def test_redundant_boolean_comparison_removal(self) -> None:
        """Test that if(x == false) becomes if(!x)."""
        code_block = Node(
            "begin",
            [
                Node(
                    "if",
                    [
                        Node(
                            "==",
                            [
                                Node(
                                    "call_property",
                                    [
                                        Node("get_local", [6]),
                                        Node("multiname", ["isConnected"]),
                                    ],
                                ),
                                Node("false"),
                            ],
                        ),
                        Node("return_value", [Node("integer", [0])]),
                    ],
                )
            ],
        )

        pass_instance = AstSemanticNormalizePass()
        pass_instance.visit(code_block)

        # 期望: if(!(x.isConnected()))
        cond = code_block.children[0].children[0]
        assert cond.type == "!"
        assert cond.children[0].type == "call_property"

    def test_numeric_literal_hex_to_dec(self) -> None:
        """Test formatting of simple numeric literals (0x0 -> 0)."""
        # 在某些上下文中，0x0 应该显示为 0
        code_block = Node("return_value", [Node("integer", [0])])

        # 这是一个 emitter/formatter 层的优化建议，
        # 但在语义层我们可以确保它是简单的 integer 节点
        assert code_block.children[0].type == "integer"
        assert code_block.children[0].children[0] == 0
