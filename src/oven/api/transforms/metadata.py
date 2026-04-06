"""Metadata preserving transforms."""

from __future__ import annotations

from typing import Any, Callable, TypeVar, cast
from oven.core.pipeline import Transform
from oven.core.ast import Node


class MetadataPreservingTransform(Transform[Any, Any]):
    """Base class for transforms that preserve metadata.

    Ensures metadata is propagated from input nodes to output nodes
    during transformation.
    """

    def transform(self, node: Node, context: Any) -> Node:
        """Transform a node, preserving metadata.

        Subclasses should override _transform_impl instead of this method.
        """
        result = self._transform_impl(node, context)

        # Propagate metadata from input node to output node
        if hasattr(node, "metadata") and hasattr(result, "metadata"):
            # Update result metadata with node metadata (but don't overwrite)
            for key, value in node.metadata.items():
                if key not in result.metadata:
                    result.metadata[key] = value
                elif isinstance(value, dict) and isinstance(result.metadata[key], dict):
                    # Merge dictionaries
                    result.metadata[key].update(value)

        return result

    def _transform_impl(self, node: Node, context: Any) -> Node:
        """Implementation of transformation logic.

        Subclasses should override this method.
        """
        # Default implementation returns node unchanged
        return node


TTransform = TypeVar("TTransform", bound=type[Transform[Any, Any]])


def preserve_metadata(transform_class: TTransform) -> TTransform:
    """Decorator to make a transform class preserve metadata.

    Wraps the transform method to copy metadata from input to output.
    """
    original_transform = transform_class.transform

    def wrapped_transform(self: Transform[Any, Any], *args: Any) -> Any:
        if not args:
            return args

        result = original_transform(self, *args)

        # Handle different return types
        if isinstance(result, tuple):
            # Pipeline returns (ast, *rest)
            ast = result[0]
            if isinstance(ast, Node) and isinstance(args[0], Node):
                _propagate_metadata(args[0], ast)
            return result
        elif isinstance(result, Node) and isinstance(args[0], Node):
            _propagate_metadata(args[0], result)
            return result
        else:
            return result

    def _propagate_metadata(source: Node, target: Node) -> None:
        """Propagate metadata from source to target node."""
        if hasattr(source, "metadata") and hasattr(target, "metadata"):
            for key, value in source.metadata.items():
                if key not in target.metadata:
                    target.metadata[key] = value
                elif isinstance(value, dict) and isinstance(target.metadata[key], dict):
                    # Merge dictionaries
                    target.metadata[key].update(value)

    setattr(transform_class, "transform", cast(Callable[..., Any], wrapped_transform))
    return transform_class
