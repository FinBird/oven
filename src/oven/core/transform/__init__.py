from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

from oven.core.pipeline import Pipeline, Transform

__all__ = [
    "Transform",
    "Pipeline",
    "PropagateLabels",
    "PropagateConstants",
    "CFGBuild",
    "CFGReduce",
]

# Clear stale eager bindings when the module is reloaded in tests or tooling.
for _symbol in (
    "PropagateLabels",
    "PropagateConstants",
    "CFGBuild",
    "CFGReduce",
):
    globals().pop(_symbol, None)

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "PropagateLabels": (".propagate_labels", "PropagateLabels"),
    "PropagateConstants": (".propagate_constants", "PropagateConstants"),
    "CFGBuild": (".cfg_build", "CFGBuild"),
    "CFGReduce": (".cfg_reduce", "CFGReduce"),
}


def __getattr__(name: str) -> Any:
    """Lazily resolve transform classes to avoid import cycles."""
    try:
        module_name, attr_name = _LAZY_EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    value = getattr(import_module(module_name, __name__), attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))


if TYPE_CHECKING:
    from .cfg_build import CFGBuild
    from .cfg_reduce import CFGReduce
    from .propagate_constants import PropagateConstants
    from .propagate_labels import PropagateLabels
