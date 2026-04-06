from __future__ import annotations

from pathlib import Path
from typing import Any

from oven.avm2.decompiler import (
    _decompile_abc_parsed_to_files,
    _sanitize_identifier,
)
from oven.avm2.decompiler.class_ast import build_class_ast
from oven.avm2.decompiler.class_emitter import emit_class_ast
from oven.core.ast import Node
from oven.avm2.file import ABCFile
from oven.core.ast import Node

from .models import DecompilationResult, DecompilerConfig


class PathResolver:
    """Resolve collisions in emitted output paths."""

    def __init__(self) -> None:
        self._used_paths: set[str] = set()
        self._name_counters: dict[str, int] = {}

    def resolve(
        self,
        package_parts: list[str],
        base_class_name: str,
    ) -> tuple[list[str], str]:
        pkg_key = ".".join(package_parts)
        identity_key = f"{pkg_key}::{base_class_name}".lower()
        suffix = self._name_counters.get(identity_key, 0)
        while True:
            candidate = (
                base_class_name if suffix == 0 else f"{base_class_name}_{suffix}"
            )
            rel_key = (
                str((Path(*package_parts) / f"{candidate}.as"))
                .replace("\\", "/")
                .lower()
            )
            if rel_key not in self._used_paths:
                self._used_paths.add(rel_key)
                self._name_counters[identity_key] = suffix + 1
                return package_parts, candidate
            suffix += 1


class AS3Decompiler:
    """Thin compatibility orchestrator over the AVM2 decompiler package."""

    def __init__(self, abc: ABCFile, config: DecompilerConfig) -> None:
        self.abc = abc
        self.config = config
        self._path_resolver = PathResolver()

    def decompile_all_to_disk(
        self,
        output_dir: Path,
        *,
        clean: bool = True,
    ) -> list[Path]:
        return _decompile_abc_parsed_to_files(
            self.abc,
            output_dir,
            style=self.config.style,
            int_format=self.config.int_format,
            clean_output=clean,
            inline_vars=self.config.inline_vars,
        )

    def decompile_class(self, class_index: int) -> str:
        class_node = build_class_ast(self.abc, class_index, self.config)
        return emit_class_ast(class_node, indent_level=0)

    def _decompile_class_structured(self, class_index: int) -> DecompilationResult:
        class_node = build_class_ast(self.abc, class_index, self.config)
        package_name = str(class_node.metadata.get("package", ""))
        imports = set(class_node.metadata.get("imports", []))
        package_parts = package_name.split(".") if package_name else []
        class_name = self._extract_class_name(class_node, class_index)
        return DecompilationResult(
            package_parts=package_parts,
            class_name=class_name,
            imports=imports,
            class_ast=class_node,
        )

    @staticmethod
    def _extract_class_name(class_node: Node, class_index: int) -> str:
        for child in class_node.children:
            if (
                isinstance(child, Node)
                and child.type == "class_name"
                and child.children
            ):
                return _sanitize_identifier(
                    child.children[0],
                    f"Class{class_index}",
                    set(),
                )
        return f"Class{class_index}"
