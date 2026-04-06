from __future__ import annotations

from types import SimpleNamespace
from typing import cast

from oven.avm2.file import ABCFile
from oven.avm2.transform import AS3NodeTypes as NT
from oven.avm2.transform.semantic_passes import MoveStaticInitsToFieldsPass
from oven.core.ast import Node

_DUMMY_ABC = cast(ABCFile, object())


def test_move_static_inits_lifts_find_property_assignments() -> None:
    root = Node(
        NT.BEGIN,
        [
            Node(NT.PUSH_SCOPE, [Node(NT.GET_LOCAL, [0])]),
            Node(
                NT.INIT_PROPERTY,
                [
                    Node(NT.FIND_PROPERTY, ["PACKAGE_NAMESPACE::::ALL_FREE_TS"]),
                    "PACKAGE_NAMESPACE::::ALL_FREE_TS",
                    Node(
                        NT.NEW_ARRAY,
                        [Node(NT.GET_LEX, ["PACKAGE_NAMESPACE::::T_SPIRIT_BAG_DATA"])],
                    ),
                ],
            ),
            Node("return_void", []),
        ],
    )

    transformed = MoveStaticInitsToFieldsPass(
        owner_name="ADFCmdsType",
        method_name="__static_init__",
        class_traits=[
            SimpleNamespace(name="PACKAGE_NAMESPACE::::ALL_FREE_TS"),
            SimpleNamespace(name="PACKAGE_NAMESPACE::::T_SPIRIT_BAG_DATA"),
        ],
        abc_obj=_DUMMY_ABC,
    ).transform(root)

    assert transformed.children[0].type == NT.FIELD_INITIALIZERS
    assert transformed.children[0].metadata == {
        "static": True,
        "owner": "ADFCmdsType",
    }
    assert transformed.children[0].children[0].children[0] == "ALL_FREE_TS"
    assert transformed.children[0].children[0].children[1].type == NT.NEW_ARRAY
    assert all(
        not (isinstance(child, Node) and child.type == NT.INIT_PROPERTY)
        for child in transformed.children
    )


def test_move_static_inits_lifts_normalized_get_lex_assignments() -> None:
    root = Node(
        NT.BEGIN,
        [
            Node(
                NT.INIT_PROPERTY,
                [
                    Node(NT.GET_LEX, ["PACKAGE_NAMESPACE::::ALL_FREE_TS"]),
                    "PACKAGE_NAMESPACE::::ALL_FREE_TS",
                    Node(
                        NT.NEW_ARRAY,
                        [Node(NT.GET_LEX, ["PACKAGE_NAMESPACE::::T_SPIRIT_BAG_DATA"])],
                    ),
                ],
            ),
            Node("return_void", []),
        ],
    )

    transformed = MoveStaticInitsToFieldsPass(
        owner_name="ADFCmdsType",
        method_name="__static_init__",
        class_traits=[SimpleNamespace(name="PACKAGE_NAMESPACE::::ALL_FREE_TS")],
        abc_obj=_DUMMY_ABC,
    ).transform(root)

    assert transformed.children[0].type == NT.FIELD_INITIALIZERS
    assert transformed.children[0].children[0].children[0] == "ALL_FREE_TS"
    assert all(
        not (isinstance(child, Node) and child.type == NT.INIT_PROPERTY)
        for child in transformed.children
    )
