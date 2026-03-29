from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol, TypeAlias

from oven.core.ast import Node

# Control-transfer instruction categories.
CTI_NONE: int = 0
CTI_JUMP: int = 1
CTI_COND: int = 2
CTI_SWITCH: int = 3
CTI_TERMINAL: int = 4

CTITarget: TypeAlias = int | str | None
CTIResult: TypeAlias = tuple[int, list[CTITarget]]
CTIHandler: TypeAlias = Callable[[Node], CTIResult]


@dataclass(frozen=True, slots=True)
class BranchInfo:
    """Normalized branch description consumed by CFG builders."""

    kind: int
    targets: list[CTITarget]
    keep_node: bool = True


class ControlFlowAdapter(Protocol):
    """Protocol used by `core.transform.cfg_build.CFGBuild` to decode CTI nodes."""

    def get_branch_info(self, node: Node) -> BranchInfo | None:
        ...

    # Kept for backward compatibility in adapters/tests that still access raw handlers.
    def get_cti_handler(self, node_type: str) -> CTIHandler | None:
        ...

    def is_label(self, node_type: str) -> bool:
        ...

    def is_nop(self, node_type: str) -> bool:
        ...

    @property
    def exception_dispatch_type(self) -> str:
        ...

    @property
    def catch_type(self) -> str:
        ...


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
        return BranchInfo(kind=kind, targets=targets, keep_node=(kind != CTI_JUMP))

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
        target = node.children[self.dialect.jump_target_index] if len(node.children) > self.dialect.jump_target_index else None
        node.children = []
        return CTI_JUMP, [target]

    def _handle_cond(self, node: Node) -> CTIResult:
        idx = self.dialect.conditional_jump_target_index
        target = node.children[idx] if 0 <= idx < len(node.children) else None
        if 0 <= idx < len(node.children):
            node.children = node.children[:idx] + node.children[idx + 1 :]
        return CTI_COND, [target]

    def _handle_switch(self, node: Node) -> CTIResult:
        default = node.children[self.dialect.switch_default_index] if len(node.children) > self.dialect.switch_default_index else None
        case_targets: list[CTITarget] = []
        if len(node.children) > self.dialect.switch_cases_index:
            raw_cases = node.children[self.dialect.switch_cases_index]
            if isinstance(raw_cases, list):
                case_targets = list(raw_cases)

        expr = node.children[self.dialect.switch_expr_index] if len(node.children) > self.dialect.switch_expr_index else None
        node.children = [expr] if isinstance(expr, Node) else []
        return CTI_SWITCH, [default, *case_targets]

    @staticmethod
    def _handle_terminal(node: Node) -> CTIResult:
        return CTI_TERMINAL, []
