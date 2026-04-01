from __future__ import annotations

from typing import Any

from oven.core.ast import Node
from oven.core.cfg.dialect import (
    BranchInfo,
    CTIKind,
    CTIHandler,
    CTIResult,
)


class AVM2ControlFlowAdapter:
    """AVM2-specific control-flow adapter used by `core.transform.cfg_build.CFGBuild`."""

    __slots__ = ("_handlers",)

    def __init__(self) -> None:
        self._handlers: dict[str, CTIHandler] = {
            "jump": self._handle_jump,
            "jump_if": self._handle_jump_if,
            "lookup_switch": self._handle_lookup_switch,
            "return_void": self._handle_terminal,
            "return_value": self._handle_terminal,
            "throw": self._handle_terminal,
        }

    def get_cti_handler(self, node_type: str) -> CTIHandler | None:
        return self._handlers.get(node_type)

    def get_branch_info(self, node: Node) -> BranchInfo | None:
        handler = self._handlers.get(node.type)
        if handler is None:
            return None
        kind, targets = handler(node)
        return BranchInfo(kind=kind, targets=targets, keep_node=(kind != CTIKind.JUMP))

    @staticmethod
    def is_label(node_type: str) -> bool:
        return node_type == "label"

    @staticmethod
    def is_nop(node_type: str) -> bool:
        return node_type == "nop"

    @property
    def exception_dispatch_type(self) -> str:
        return "exception_dispatch"

    @property
    def catch_type(self) -> str:
        return "catch"

    @staticmethod
    def _handle_jump(node: Node) -> CTIResult:
        target = node.children[0] if node.children else None
        node.children = []
        return CTIKind.JUMP, [target]

    @staticmethod
    def _handle_jump_if(node: Node) -> CTIResult:
        target: Any = None
        flag = bool(node.children[0]) if node.children else True
        cond: Any = node.children[1] if len(node.children) > 1 else Node("true")

        if len(node.children) >= 3 and not isinstance(node.children[1], Node):
            target = node.children[1]
            cond = node.children[2]

        node.children = [flag, cond]
        return CTIKind.COND, [target]

    @staticmethod
    def _handle_lookup_switch(node: Node) -> CTIResult:
        default_target = node.children[0] if node.children else None
        case_targets: list[Any] = []
        if len(node.children) > 1 and isinstance(node.children[1], list):
            case_targets = list(node.children[1])

        expr = node.children[2] if len(node.children) > 2 else None
        node.children = [expr] if isinstance(expr, Node) else []

        return CTIKind.SWITCH, [default_target, *case_targets]

    @staticmethod
    def _handle_terminal(node: Node) -> CTIResult:
        return CTIKind.TERMINAL, []
