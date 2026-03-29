from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Iterable, TypeVar, Generic

T_in = TypeVar('T_in')
T_out = TypeVar('T_out')


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

    def __or__(self, other: Transform) -> Pipeline:
        if not isinstance(other, Transform):
            return NotImplemented

        if isinstance(other, Pipeline):
            return Pipeline([self, *other.stages])
        return Pipeline([self, other])


class Pipeline(Transform):
    __slots__ = ("stages",)

    def __init__(self, stages: Iterable[Transform | None]) -> None:
        self.stages: list[Transform] = [s for s in stages if s is not None]

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

    def __or__(self, other: Transform) -> Pipeline:
        if not isinstance(other, Transform):
            return NotImplemented

        if isinstance(other, Pipeline):
            return Pipeline(self.stages + other.stages)
        return Pipeline(self.stages + [other])

    def __ror__(self, other: Transform) -> Pipeline:
        if isinstance(other, Transform):
            return Pipeline([other] + self.stages)
        return NotImplemented
