from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Callable, Protocol, TypeAlias

from oven.core.ast import Node


class CTIKind(IntEnum):
    """Control-transfer instruction categories enum."""

    NONE = 0
    JUMP = 1
    COND = 2
    SWITCH = 3
    TERMINAL = 4


CTITarget: TypeAlias = int | str | None
CTIResult: TypeAlias = tuple[CTIKind, list[CTITarget]]
CTIHandler: TypeAlias = Callable[[Node], CTIResult]


@dataclass(frozen=True, slots=True)
class BranchInfo:
    """Normalized branch description consumed by CFG builders."""

    kind: CTIKind
    targets: list[CTITarget]
    keep_node: bool = True


class ControlFlowAdapter(Protocol):
    """Protocol used by `core.transform.cfg_build.CFGBuild` to decode CTI nodes."""

    def get_branch_info(self, node: Node) -> BranchInfo | None: ...

    # Kept for backward compatibility in adapters/tests that still access raw handlers.
    def get_cti_handler(self, node_type: str) -> CTIHandler | None: ...

    def is_label(self, node_type: str) -> bool: ...

    def is_nop(self, node_type: str) -> bool: ...

    @property
    def exception_dispatch_type(self) -> str: ...

    @property
    def catch_type(self) -> str: ...


@dataclass(frozen=True, slots=True)
class FlowDialect:
    """Dialect mapping for CFG build/reduce control-transfer semantics."""

    nop: str = "nop"
    label: str = "label"
    jump: str = "jump"
    conditional_jumps: frozenset[str] = frozenset({"jump_if"})
    switches: frozenset[str] = frozenset({"lookup_switch"})
    return_nodes: frozenset[str] = frozenset({"return_value", "return_void"})
    throw_nodes: frozenset[str] = frozenset({"throw"})

    exception_dispatch: str = "exception_dispatch"
    catch: str = "catch"

    jump_target_index: int = 0
    conditional_jump_target_index: int = 1
    switch_default_index: int = 0
    switch_cases_index: int = 1
    switch_expr_index: int = 2

    ast_begin: str = "begin"
    ast_if: str = "if"
    ast_while: str = "while"
    ast_switch: str = "switch"
    ast_case: str = "case"
    ast_default: str = "default"
    ast_break: str = "break"
    ast_continue: str = "continue"
    ast_not: str = "!"
    ast_true: str = "true"
    ast_integer: str = "integer"

    ast_try: str = "try"
    ast_catch: str = "catch"
    ast_finally: str = "finally"

    switch_source: str = "lookup_switch"

    @property
    def terminal_transfers(self) -> frozenset[str]:
        return self.return_nodes | self.throw_nodes


class DefaultControlFlowAdapter:
    """Default adapter preserving historical `FlowDialect` behavior."""

    __slots__ = ("dialect", "_handlers")

    def __init__(self, dialect: FlowDialect | None = None) -> None:
        self.dialect = dialect or FlowDialect()
        self._handlers: dict[str, CTIHandler] = {
            self.dialect.jump: self._handle_jump,
            **{name: self._handle_cond for name in self.dialect.conditional_jumps},
            **{name: self._handle_switch for name in self.dialect.switches},
            **{name: self._handle_terminal for name in self.dialect.terminal_transfers},
        }

    def get_cti_handler(self, node_type: str) -> CTIHandler | None:
        return self._handlers.get(node_type)

    def get_branch_info(self, node: Node) -> BranchInfo | None:
        handler = self._handlers.get(node.type)
        if handler is None:
            return None
        kind, targets = handler(node)
        return BranchInfo(kind=kind, targets=targets, keep_node=(kind != CTIKind.JUMP))

    def is_label(self, node_type: str) -> bool:
        return node_type == self.dialect.label

    def is_nop(self, node_type: str) -> bool:
        return node_type == self.dialect.nop

    @property
    def exception_dispatch_type(self) -> str:
        return self.dialect.exception_dispatch

    @property
    def catch_type(self) -> str:
        return self.dialect.catch

    def _handle_jump(self, node: Node) -> CTIResult:
        target = (
            node.children[self.dialect.jump_target_index]
            if len(node.children) > self.dialect.jump_target_index
            else None
        )
        node.children = []
        if isinstance(target, Node):
            label: CTITarget = target.type
        elif isinstance(target, (int, str, type(None))):
            label = target
        else:
            label = None
        return CTIKind.JUMP, [label]

    def _handle_cond(self, node: Node) -> CTIResult:
        idx = self.dialect.conditional_jump_target_index
        target = node.children[idx] if 0 <= idx < len(node.children) else None
        if 0 <= idx < len(node.children):
            node.children = node.children[:idx] + node.children[idx + 1 :]
        if isinstance(target, Node):
            label: CTITarget = target.type
        elif isinstance(target, (int, str, type(None))):
            label = target
        else:
            label = None
        return CTIKind.COND, [label]

    def _handle_switch(self, node: Node) -> CTIResult:
        default_raw = (
            node.children[self.dialect.switch_default_index]
            if len(node.children) > self.dialect.switch_default_index
            else None
        )
        if isinstance(default_raw, Node):
            default: CTITarget = default_raw.type
        elif isinstance(default_raw, (int, str, type(None))):
            default = default_raw
        else:
            default = None

        case_targets: list[CTITarget] = []
        if len(node.children) > self.dialect.switch_cases_index:
            raw_cases = node.children[self.dialect.switch_cases_index]
            if isinstance(raw_cases, list):
                for item in raw_cases:
                    if isinstance(item, Node):
                        case_targets.append(item.type)
                    elif isinstance(item, (int, str)):
                        case_targets.append(item)

        expr = (
            node.children[self.dialect.switch_expr_index]
            if len(node.children) > self.dialect.switch_expr_index
            else None
        )
        node.children = [expr] if isinstance(expr, Node) else []
        return CTIKind.SWITCH, [default, *case_targets]

    @staticmethod
    def _handle_terminal(node: Node) -> CTIResult:
        return CTIKind.TERMINAL, []
