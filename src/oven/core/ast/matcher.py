from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Iterable, MutableMapping
from dataclasses import dataclass
import sys

from .node import Node

CaptureDict = MutableMapping[str, Any]


def _capture_mark(captures: CaptureDict) -> int:
    return len(captures)


def _rollback_captures(captures: CaptureDict, mark: int) -> None:
    if len(captures) <= mark:
        return

    if isinstance(captures, dict):
        while len(captures) > mark:
            captures.popitem()
        return

    # Fallback for custom mutable mappings.
    keys = tuple(captures.keys())
    for key in keys[mark:]:
        del captures[key]


class MatchError(Exception):
    pass


class BaseMatcher(ABC):
    """Base class for all matchers supporting operator overloading."""

    __slots__ = ()

    @abstractmethod
    def match(self, target: Any, captures: CaptureDict) -> bool:
        """Perform match. Return True on success and populate captures."""
        raise NotImplementedError

    def __or__(self, other: BaseMatcher) -> BaseMatcher:
        return m.one_of(self, other)

    def __and__(self, other: BaseMatcher) -> BaseMatcher:
        return m.all_of(self, other)

    def __invert__(self) -> BaseMatcher:
        return _Not(self)

    def match_root(self, target: Any) -> CaptureDict | None:
        """Entry point: creates capture context and executes match."""
        captures: CaptureDict = {}
        if self.match(target, captures):
            return captures
        return None


def _ensure_matcher(obj: Any) -> BaseMatcher:
    """Helper: Auto-convert literals to matchers."""
    if isinstance(obj, BaseMatcher):
        return obj
    if isinstance(obj, str):
        return _TypeOf(obj)
    return _Equals(obj)



@dataclass(slots=True, frozen=True)
class _AnyNode(BaseMatcher):
    def match(self, target: Any, captures: CaptureDict) -> bool:
        return True


@dataclass(slots=True, frozen=True)
class _Equals(BaseMatcher):
    value: Any

    def match(self, target: Any, captures: CaptureDict) -> bool:
        return target == self.value


@dataclass(slots=True, frozen=True)
class _IsType(BaseMatcher):
    cls_type: type | tuple[type, ...]

    def match(self, target: Any, captures: CaptureDict) -> bool:
        return isinstance(target, self.cls_type)


@dataclass(slots=True, frozen=True)
class _TypeOf(BaseMatcher):
    """Matches Node.type string or string literals."""
    node_type: str

    def __post_init__(self):
        # Intern string for comparison speed
        object.__setattr__(self, 'node_type', sys.intern(self.node_type))

    def match(self, target: Any, captures: CaptureDict) -> bool:
        if isinstance(target, Node):
            return target.type is self.node_type
        elif isinstance(target, str):
            return target == self.node_type
        return False



@dataclass(slots=True, frozen=True)
class _OneOf(BaseMatcher):
    """Logical OR."""
    matchers: tuple[BaseMatcher, ...]

    def match(self, target: Any, captures: CaptureDict) -> bool:
        for matcher in self.matchers:
            mark = _capture_mark(captures)
            if matcher.match(target, captures):
                return True
            _rollback_captures(captures, mark)
        return False

@dataclass(slots=True, frozen=True)
class _AllOf(BaseMatcher):
    """Logical AND."""
    matchers: tuple[BaseMatcher, ...]

    def match(self, target: Any, captures: CaptureDict) -> bool:
        for matcher in self.matchers:
            if not matcher.match(target, captures):
                return False
        return True


@dataclass(slots=True, frozen=True)
class _Not(BaseMatcher):
    matcher: BaseMatcher

    def match(self, target: Any, captures: CaptureDict) -> bool:
        return not self.matcher.match(target, {})



@dataclass(slots=True, frozen=True)
class _Capture(BaseMatcher):
    name: str
    inner: BaseMatcher

    def match(self, target: Any, captures: CaptureDict) -> bool:
        if self.inner.match(target, captures):
            captures[self.name] = target
            return True
        return False


@dataclass(slots=True, frozen=True)
class _BackRef(BaseMatcher):
    """Matches against a previously captured value."""
    name: str

    def match(self, target: Any, captures: CaptureDict) -> bool:
        if self.name in captures:
            return target == captures[self.name]
        return False



@dataclass(slots=True, frozen=True)
class _Rest(BaseMatcher):
    """Marker: Matches remaining items in a sequence."""
    capture_name: str | None = None

    def match(self, target: Any, captures: CaptureDict) -> bool:
        return True


@dataclass(slots=True, frozen=True)
class _Maybe(BaseMatcher):
    pattern: "_SequenceMatcher"

    def match(self, target: Any, captures: CaptureDict) -> bool:
        return self.pattern.match(target, captures)


@dataclass(slots=True, frozen=True)
class _Each(BaseMatcher):
    patterns: tuple[BaseMatcher, ...]

    def match(self, target: Any, captures: CaptureDict) -> bool:
        if not isinstance(target, (list, tuple)):
            return False
        workset = list(target)
        local = dict(captures)
        for pattern in self.patterns:
            found_index = -1
            for idx, elem in enumerate(workset):
                snapshot = dict(local)
                if pattern.match(elem, snapshot):
                    local = snapshot
                    found_index = idx
                    break
            if found_index == -1:
                return False
            del workset[found_index]
        captures.update(local)
        return True


@dataclass(slots=True, frozen=True)
class _EitherMulti(BaseMatcher):
    options: tuple["_SequenceMatcher", ...]

    def match(self, target: Any, captures: CaptureDict) -> bool:
        if not isinstance(target, (list, tuple)):
            return False
        for option in self.options:
            snapshot = dict(captures)
            if option.match(list(target), snapshot):
                captures.update(snapshot)
                return True
        return False


@dataclass(slots=True, frozen=True)
class _Map(BaseMatcher):
    capture_name: str
    patterns: tuple[tuple[str | None, "_SequenceMatcher"], ...]

    def match(self, target: Any, captures: CaptureDict) -> bool:
        if not isinstance(target, (list, tuple)):
            return False
        items = list(target)
        index = 0
        records: list[tuple[str, CaptureDict]] = []
        while index < len(items):
            found = False
            for key, pattern in self.patterns:
                snapshot = dict(captures)
                consumed = pattern.match_prefix(items[index:], snapshot)
                if consumed is not None and consumed > 0:
                    if key is not None:
                        records.append((key, snapshot))
                    captures.update(snapshot)
                    index += consumed
                    found = True
                    break
            if not found:
                return False
        captures[self.capture_name] = records
        return True


@dataclass(slots=True, frozen=True)
class _SequenceMatcher(BaseMatcher):
    """Matches lists (e.g., node children)."""
    patterns: tuple[BaseMatcher, ...]

    def match(self, target: Any, captures: CaptureDict) -> bool:
        if not isinstance(target, (list, tuple)):
            return False
        consumed = self._match_impl(list(target), captures, allow_prefix=False)
        return consumed is not None

    def match_prefix(self, items: list[Any], captures: CaptureDict) -> int | None:
        return self._match_impl(items, captures, allow_prefix=True)

    def _match_impl(self, items: list[Any], captures: CaptureDict, allow_prefix: bool) -> int | None:
        p_idx = 0
        i_idx = 0
        n_p = len(self.patterns)
        n_i = len(items)

        while p_idx < n_p:
            pat = self.patterns[p_idx]

            if isinstance(pat, _Rest):
                remaining = items[i_idx:]
                if pat.capture_name:
                    captures[pat.capture_name] = remaining
                return n_i

            if isinstance(pat, _Maybe):
                mark = _capture_mark(captures)
                maybe_consumed = pat.pattern.match_prefix(items[i_idx:], captures)
                if maybe_consumed is not None:
                    i_idx += maybe_consumed
                else:
                    _rollback_captures(captures, mark)
                p_idx += 1
                continue

            if isinstance(pat, _EitherMulti):
                matched = False
                for option in pat.options:
                    mark = _capture_mark(captures)
                    option_consumed = option.match_prefix(items[i_idx:], captures)
                    if option_consumed is not None:
                        i_idx += option_consumed
                        matched = True
                        break
                    _rollback_captures(captures, mark)
                if not matched:
                    return None
                p_idx += 1
                continue

            if isinstance(pat, _Each):
                mark = _capture_mark(captures)
                if not pat.match(items[i_idx:], captures):
                    _rollback_captures(captures, mark)
                    return None
                # Keep Ruby behavior: :each advances one input position.
                i_idx += 1
                p_idx += 1
                continue

            if isinstance(pat, _Map):
                mark = _capture_mark(captures)
                if not pat.match(items[i_idx:], captures):
                    _rollback_captures(captures, mark)
                    return None
                i_idx = n_i
                p_idx += 1
                continue

            if i_idx >= n_i:
                return None

            if not pat.match(items[i_idx], captures):
                return None

            i_idx += 1
            p_idx += 1

        if allow_prefix:
            return i_idx
        return i_idx if i_idx == n_i else None


@dataclass(slots=True, frozen=True)
class _NodeMatcher(BaseMatcher):
    """Matches Node(type, children)."""
    type_matcher: BaseMatcher
    children_matcher: _SequenceMatcher | None = None

    def match(self, target: Any, captures: CaptureDict) -> bool:
        if not isinstance(target, Node): return False
        if not self.type_matcher.match(target.type, captures): return False
        if self.children_matcher:
            return self.children_matcher.match(target.children, captures)
        return True


@dataclass(slots=True, frozen=True)
class _HasMatcher(BaseMatcher):
    """Recursive search (descendant check)."""
    pattern: BaseMatcher

    def match(self, target: Any, captures: CaptureDict) -> bool:
        if not isinstance(target, Node):
            return False

        stack = [target]
        while stack:
            node = stack.pop()
            snapshot = dict(captures)

            if self.pattern.match(node, snapshot):
                captures.update(snapshot)
                return True

            if isinstance(node, Node):
                # Reverse children for correct stack processing order
                for child in reversed(node.children):
                    if isinstance(child, Node):
                        stack.append(child)
        return False

class m:
    """Matcher Factory DSL."""
    any = _AnyNode()

    @staticmethod
    def of(type_name: str, *children: Any) -> _NodeMatcher:
        """Match a Node by type and optional children patterns."""
        t_m = _ensure_matcher(type_name)
        c_m = None
        if children:
            child_patterns = tuple(_ensure_matcher(p) for p in children)
            c_m = _SequenceMatcher(child_patterns)
        return _NodeMatcher(t_m, c_m)

    @staticmethod
    def backref(name: str) -> _BackRef:
        return _BackRef(name)

    @staticmethod
    def eq(value: Any) -> _Equals:
        return _Equals(value)

    @staticmethod
    def is_type(t: str | type | tuple[type, ...]) -> BaseMatcher:
        """Check instance type or Node.type string."""
        if isinstance(t, str):
            return _TypeOf(t)
        return _IsType(t)

    @staticmethod
    def seq(*items: Any) -> _SequenceMatcher:
        patterns = tuple(_ensure_matcher(p) for p in items)
        return _SequenceMatcher(patterns)

    @staticmethod
    def maybe(*items: Any) -> _Maybe:
        if not items:
            return _Maybe(m.seq())
        return _Maybe(m.seq(*items))

    @staticmethod
    def each(*items: Any) -> _Each:
        patterns = tuple(_ensure_matcher(p) for p in items)
        return _Each(patterns)

    @staticmethod
    def either_multi(*options: Any) -> _EitherMulti:
        seq_options: list[_SequenceMatcher] = []
        for option in options:
            if isinstance(option, _SequenceMatcher):
                seq_options.append(option)
            elif isinstance(option, (list, tuple)):
                seq_options.append(m.seq(*option))
            else:
                seq_options.append(m.seq(option))
        return _EitherMulti(tuple(seq_options))

    @staticmethod
    def map(name: str, pattern_map: dict[str | None, Any]) -> _Map:
        compiled: list[tuple[str | None, _SequenceMatcher]] = []
        for key, value in pattern_map.items():
            if isinstance(value, _SequenceMatcher):
                compiled.append((key, value))
            elif isinstance(value, (list, tuple)):
                compiled.append((key, m.seq(*value)))
            else:
                compiled.append((key, m.seq(value)))
        return _Map(name, tuple(compiled))

    @staticmethod
    def capture(name: str, matcher: Any = None) -> _Capture:
        inner = _ensure_matcher(matcher) if matcher is not None else _AnyNode()
        return _Capture(name, inner)

    @staticmethod
    def rest(capture_name: str | None = None) -> _Rest:
        return _Rest(capture_name)

    @staticmethod
    def skip() -> _Rest:
        return _Rest(None)

    @staticmethod
    def one_of(*options: Any) -> _OneOf:
        flat = []
        for opt in options:
            matcher = _ensure_matcher(opt)
            if isinstance(matcher, _OneOf):
                flat.extend(matcher.matchers)
            else:
                flat.append(matcher)
        return _OneOf(tuple(flat))

    @staticmethod
    def all_of(*options: Any) -> _AllOf:
        matchers = tuple(_ensure_matcher(o) for o in options)
        return _AllOf(matchers)

    @staticmethod
    def has(pattern: Any) -> BaseMatcher:
        return _HasMatcher(_ensure_matcher(pattern))

    @staticmethod
    def has_type(type_name: str) -> BaseMatcher:
        return _NodeMatcher(_TypeOf(type_name), None)

    @staticmethod
    def capture_children(name: str) -> BaseMatcher:
        return _Capture(name, m.seq(m.rest(name)))


class Matcher:
    """High-level wrapper for finding patterns."""

    def __init__(self, pattern: BaseMatcher):
        self.pattern = pattern

    def match(self, node: Any, captures: CaptureDict | None = None) -> CaptureDict | None:
        if captures is None:
            captures = {}

        if self.pattern.match(node, captures):
            return captures

        return None

    def find_all(self, collection: Iterable[Any]) -> list[tuple[Any, CaptureDict]]:
        results = []
        for elem in collection:
            if caps := self.match(elem):
                results.append((elem, caps))
        return results

    def find_one(self, collection: Iterable[Any]) -> tuple[Any, CaptureDict] | None:
        for elem in collection:
            if caps := self.match(elem):
                return elem, caps
        return None

