from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from inspect import cleandoc
from typing import Any, Iterable, TypeVar, Generic

T_in = TypeVar("T_in")
T_out = TypeVar("T_out")


class Transform(ABC, Generic[T_in, T_out]):
    """
    Base class for all transformation logic.
    Subclasses must implement the `transform` method.
    """

    __slots__ = ()

    @abstractmethod
    def transform(self, *args: Any) -> Any:
        raise NotImplementedError

    def __call__(self, *args: Any) -> Any:
        return self.transform(*args)

    def __or__(self, other: Transform[Any, Any]) -> Pipeline:
        if not isinstance(other, Transform):
            return NotImplemented

        if isinstance(other, Pipeline):
            return Pipeline([self, *other.stages])
        return Pipeline([self, other])

    @property
    def stage_name(self) -> str:
        """A human-friendly label used when pipelines describe their stages."""
        return self.__class__.__name__

    @property
    def stage_description(self) -> str | None:
        """Supply a short description (first docstring line) when available."""
        doc = self.__class__.__doc__
        if not doc:
            return None
        return cleandoc(doc).splitlines()[0]


@dataclass(frozen=True)
class PipelineStageInfo:
    """Metadata captured for each transform within a pipeline."""

    transform: Transform[Any, Any]
    name: str
    description: str | None


class Pipeline(Transform[Any, Any]):
    __slots__ = ("stages", "_stage_info")

    def __init__(self, stages: Iterable[Transform[Any, Any] | None]) -> None:
        self.stages: list[Transform[Any, Any]] = [s for s in stages if s is not None]
        self._stage_info = tuple(
            PipelineStageInfo(
                transform=stage,
                name=stage.stage_name,
                description=stage.stage_description,
            )
            for stage in self.stages
        )

    def transform(self, *args: Any) -> Any:
        if len(args) == 1:
            node = args[0]
            for stage in self.stages:
                node = stage.transform(node)
            return node

        for stage in self.stages:
            result = stage.transform(*args)
            if isinstance(result, tuple):
                args = result
            else:
                args = (result,)
        return args[0] if len(args) == 1 else args

    def __or__(self, other: Transform[Any, Any]) -> Pipeline:
        if not isinstance(other, Transform):
            return NotImplemented

        if isinstance(other, Pipeline):
            return Pipeline(self.stages + other.stages)
        return Pipeline(self.stages + [other])

    def __ror__(self, other: Transform[Any, Any]) -> Pipeline:
        if isinstance(other, Transform):
            return Pipeline([other] + self.stages)
        return NotImplemented

    @property
    def stage_info(self) -> tuple[PipelineStageInfo, ...]:
        """Read-only metadata describing the transforms composing this pipeline."""
        return self._stage_info
