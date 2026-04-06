from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal, Optional

from oven.avm2.file import ABCFile
from oven.avm2.config import ParseMode, VerifyProfile
from oven.core.ast import Node
from .formatter import AS3Lexer, AS3Processor, CommentPolicy, ProcessorConfig


@dataclass(frozen=True, slots=True)
class DecompilerConfig:
    """Configuration for AS3 decompilation behavior."""

    # Emitter and formatting settings (existing parameters)
    style: str = "semantic"
    layout: str = "methods"  # "methods" or "classes"
    int_format: str = "hex"
    inline_vars: bool = True
    minify: bool = False
    insert_debug_comments: bool = False

    # Debug comment settings
    debug_include_offset: bool = True
    debug_include_opcode: bool = True
    debug_include_operands: bool = True

    # Output settings
    encoding: str = "utf-8"
    newline: str = "\n"

    # ABC parsing settings
    mode: Optional[ParseMode] = None
    profile: Optional[VerifyProfile] = None

    # AST transform toggles (new)
    enable_static_init_lifting: bool = True
    enable_constructor_field_lifting: bool = True
    enable_auto_imports: bool = True
    enable_namespace_cleanup: bool = True
    enable_switch_optimization: bool = True
    enable_text_cleanup: bool = True

    # Pipeline stages configuration
    pipeline_stages: list[str] = field(
        default_factory=lambda: [
            "AstSemanticNormalizePass",
            "MoveStaticInitsToFieldsPass",
            "NamespaceCleanupPass",
            "ImportDiscoveryPass",
            "TextCleanupPass",
            "AstConstructorCleanupPass",
            # "AstNormalizePass",  # TODO: implement
            # "AstOptimizePass",   # TODO: implement
            # "CfgBuildPass",      # TODO: implement
            # "CfgReducePass",     # TODO: implement
            # "NFNormalizePass",   # TODO: implement
        ]
    )

    # Manual import mapping (replaces hardcoded project-specific imports)
    manual_import_mapping: dict[str, str] = field(default_factory=dict)

    # Project‑specific hooks (replaces hardcoded logic)
    project_specific_hooks: list[Callable[[Node, ABCFile], Node]] = field(
        default_factory=list
    )

    @classmethod
    def from_legacy_params(
        cls,
        style: str = "semantic",
        layout: str = "methods",
        int_format: str = "hex",
        inline_vars: bool = True,
        minify: bool = False,
        insert_debug_comments: bool = False,
        mode: Optional[ParseMode | str] = None,
        profile: Optional[VerifyProfile | str] = None,
    ) -> DecompilerConfig:
        """Create a config from the legacy positional/keyword arguments."""
        # Convert string to enum if needed
        parsed_mode: Optional[ParseMode] = None
        if mode is not None:
            if isinstance(mode, str):
                parsed_mode = ParseMode(mode)
            else:
                parsed_mode = mode

        parsed_profile: Optional[VerifyProfile] = None
        if profile is not None:
            if isinstance(profile, str):
                parsed_profile = VerifyProfile(profile)
            else:
                parsed_profile = profile

        return cls(
            style=style,
            layout=layout,
            int_format=int_format,
            inline_vars=inline_vars,
            minify=minify,
            insert_debug_comments=insert_debug_comments,
            mode=parsed_mode,
            profile=parsed_profile,
        )


@dataclass(slots=True)
class DecompilationResult:
    """Structured result of decompiling a single ABC class."""

    package_parts: list[str]
    class_name: str
    imports: set[str] = field(default_factory=set)
    member_declarations: list[str] = field(default_factory=list)
    extends_clause: str = ""
    implements_clause: str = ""
    methods_text: list[str] = field(default_factory=list)
    field_initializers: dict[str, str] = field(default_factory=dict)
    static_initializers: list[Node] = field(default_factory=list)
    instance_initializers: list[Node] = field(default_factory=list)
    class_ast: Node | None = None

    def to_source(self) -> str:
        """Render the structured result to final AS3 source code."""
        # If class AST is available, use it for emission
        if self.class_ast is not None:
            from .class_emitter import emit_class_ast

            # Create a package node that includes imports and class
            package_node = Node(
                "package",
                [self.class_ast],
                {
                    "package": ".".join(self.package_parts)
                    if self.package_parts
                    else "",
                    "imports": list(self.imports),
                },
            )
            source = emit_class_ast(package_node, indent_level=0)
            # Format using AS3 formatter
            conf = ProcessorConfig(is_minify=False, comment_policy=CommentPolicy.ALL)
            formatted = AS3Processor(AS3Lexer(conf).tokenize(source), conf).run()
            return formatted + "\n"

        # Fallback to legacy rendering
        lines = []
        # Package block
        if self.package_parts:
            pkg_header = f"package {'.'.join(self.package_parts)}"
        else:
            pkg_header = "package"
        lines.append(pkg_header)
        lines.append("{")
        # Imports
        for imp in sorted(self.imports):
            lines.append(f"    import {imp};")
        if self.imports:
            lines.append("")
        # Class signature
        class_head = f"    public class {self.class_name}"
        if self.extends_clause:
            class_head += f" extends {self.extends_clause}"
        class_head += (
            self.implements_clause
        )  # already includes " implements " if needed
        class_head += " {"
        lines.append(class_head)
        # Member declarations
        if self.member_declarations:
            lines.extend(f"        {decl}" for decl in self.member_declarations)
            if self.member_declarations:
                lines.append("")
        # Methods
        for method in self.methods_text:
            # method text is raw without indentation; add 8 spaces for class + method body
            for line in method.splitlines():
                lines.append(f"        {line}")
            lines.append("")
        # Close class
        lines.append("    }")
        # Close package
        lines.append("}")
        raw_source = "\n".join(lines)
        # Format using AS3 formatter
        conf = ProcessorConfig(is_minify=False, comment_policy=CommentPolicy.ALL)
        formatted = AS3Processor(AS3Lexer(conf).tokenize(raw_source), conf).run()
        return formatted + "\n"
