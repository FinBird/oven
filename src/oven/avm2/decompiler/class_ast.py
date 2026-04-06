from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from oven.avm2.enums import TraitKind
from oven.avm2.file import ABCFile
from oven.avm2.transform.semantic_passes import (
    AstConstructorCleanupPass,
    AstSemanticNormalizePass,
    ImportDiscoveryPass,
    MoveStaticInitsToFieldsPass,
    NamespaceCleanupPass,
    TextCleanupPass,
)
from oven.core.ast import Node
from oven.core.pipeline import Pipeline

from .engine import (
    AS3Emitter,
    MethodContext,
    _build_method_context,
    _build_method_owner_map,
    _collect_class_method_entries,
    _extract_method_field_initializers,
    _method_to_nf,
    _ordered_field_traits,
    _try_fast_emit_method_text,
    _render_layout_method_signature,
    _short_multiname,
    _sanitize_identifier,
    _resolve_trait_type_name,
    _trait_default_initializer_expr,
    _visibility_from_namespace_kind,
    _namespace_kind_from_qualified_name,
    _strip_known_namespace_prefix,
)
from .models import DecompilerConfig


# Built-in type mappings
BUILT_IN_TYPES = {
    "Sprite": "flash.display.Sprite",
    "MovieClip": "flash.display.MovieClip",
    "IExternalizable": "flash.utils.IExternalizable",
    # Add more as needed
}


def build_class_ast(
    abc: ABCFile,
    class_index: int,
    config: DecompilerConfig,
    owner_map: dict[int, Any] | None = None,
) -> Node:
    """Build a complete AST for a single class.

    Returns a Node with type "class" containing all members and methods.
    """
    if owner_map is None:
        owner_map = _build_method_owner_map(abc)

    # Collect class metadata
    package_parts, class_name, entries, trait_indices = _collect_class_method_entries(
        abc, class_index
    )
    instance = abc.instances[class_index] if class_index < len(abc.instances) else None
    cls = abc.classes[class_index] if class_index < len(abc.classes) else None
    class_traits = list(getattr(cls, "traits", [])) if cls is not None else []

    # Check if this is an interface (interfaces have different structure)
    is_interface = False
    if instance is not None:
        # Use the is_interface attribute from InstanceInfo
        is_interface = getattr(instance, "is_interface", False)
        # Fallback check: interfaces don't have class_info
        if not is_interface and cls is None:
            is_interface = True
        # Additional heuristic: if instance has no initializer body and no instance traits,
        # it's likely an interface
        if not is_interface:
            init_method_idx = getattr(instance, "init_method", -1)
            if init_method_idx >= 0 and init_method_idx < len(abc.methods):
                init_body = abc.method_body_at(init_method_idx)
                has_init_body = init_body is not None and getattr(
                    init_body, "code", None
                )
                instance_traits = getattr(instance, "traits", [])
                if not has_init_body and not instance_traits:
                    is_interface = True

    # Collect imports discovered during method processing
    all_imports: set[str] = set()

    # Process each method to build method ASTs
    method_nodes: list[Node] = []
    field_initializers: dict[str, str] = {}

    for entry in entries:
        method_index = entry.method_index
        if not (0 <= method_index < len(abc.methods)):
            continue
        body = abc.method_body_at(method_index)
        if body is None:
            continue

        method_info = abc.methods[method_index]
        context = _build_method_context(abc, body, owner_map)

        # Special handling for static initializer
        if entry.method_name == "__static_init__":
            nf = _method_to_nf(body)
            # Run MoveStaticInitsToFieldsPass to extract field initializers
            pass_instance = MoveStaticInitsToFieldsPass(
                owner_name=class_name,
                method_name="__static_init__",
                class_traits=class_traits,
                abc_obj=abc,
                field_initializers=field_initializers,
            )
            nf = pass_instance.transform(nf)
            continue  # Skip adding method

        # Try fast emission first
        fast_text = _try_fast_emit_method_text(
            body, context, int_format=config.int_format
        )
        if fast_text is not None:
            # Even for fast emission, run import discovery to collect imports
            nf = _method_to_nf(body)
            import_pipeline = Pipeline([ImportDiscoveryPass(method_context=context)])
            nf = import_pipeline.transform(nf)
            # Collect discovered imports
            if hasattr(context, "discovered_imports"):
                all_imports.update(context.discovered_imports)
            # Create a simple method node with text content
            # Generate full method signature including getter/setter keywords
            full_signature = _render_layout_method_signature(
                class_name=class_name,
                entry=entry,
                method_info=method_info,
                context=context,
            )

            method_node = Node(
                "method",
                [
                    Node("method_signature", [full_signature]),
                    Node("method_body_text", [fast_text]),
                ],
                {"method_index": method_index, "is_constructor": entry.is_constructor},
            )
            method_nodes.append(method_node)
            continue

        # Build full AST pipeline
        nf = _method_to_nf(body)

        # Apply semantic passes based on config
        pipeline_stages: list[Any] = []
        for stage_name in config.pipeline_stages:
            if stage_name == "AstSemanticNormalizePass":
                pipeline_stages.append(AstSemanticNormalizePass())
            elif stage_name == "MoveStaticInitsToFieldsPass":
                pipeline_stages.append(MoveStaticInitsToFieldsPass())
            elif stage_name == "NamespaceCleanupPass":
                pipeline_stages.append(NamespaceCleanupPass())
            elif stage_name == "ImportDiscoveryPass":
                pipeline_stages.append(ImportDiscoveryPass(method_context=context))
            elif stage_name == "TextCleanupPass":
                pipeline_stages.append(TextCleanupPass())
            elif stage_name == "AstConstructorCleanupPass":
                pipeline_stages.append(AstConstructorCleanupPass())

        if pipeline_stages:
            pipeline = Pipeline(pipeline_stages)
            nf = pipeline.transform(nf)

        # Collect discovered imports
        if hasattr(context, "discovered_imports"):
            all_imports.update(context.discovered_imports)

        # Extract field initializers from constructor
        nf, extracted = _extract_method_field_initializers(
            nf,
            style=config.style,
            method_context=context,
            int_format=config.int_format,
            insert_debug_comments=config.insert_debug_comments,
        )
        if entry.is_constructor:
            for name, value in extracted.items():
                if (
                    isinstance(name, str)
                    and isinstance(value, str)
                    and name not in field_initializers
                ):
                    field_initializers[name] = value

        # Convert NF to source text via AS3Emitter for now
        # TODO: Keep as AST and integrate into class AST
        method_text = (
            AS3Emitter(
                style=config.style,
                method_context=context,
                int_format=config.int_format,
                inline_vars=config.inline_vars,
            )
            .emit(nf)
            .strip()
        )

        # Generate full method signature including getter/setter keywords
        full_signature = _render_layout_method_signature(
            class_name=class_name,
            entry=entry,
            method_info=method_info,
            context=context,
        )

        method_node = Node(
            "method",
            [
                Node("method_signature", [full_signature]),
                Node("method_body_text", [method_text]),
            ],
            {"method_index": method_index, "is_constructor": entry.is_constructor},
        )
        method_nodes.append(method_node)

    # Build field declarations from traits
    field_nodes = _build_field_declarations(
        abc,
        instance,
        cls,
        field_initializers,
        trait_indices,
        {},
        int_format=config.int_format,
    )

    # Build class signature
    extends_clause = ""
    current_package = ".".join(package_parts) if package_parts else ""
    if instance is not None:
        super_name = getattr(instance, "super_name", None)
        if super_name:
            if hasattr(super_name, "resolve"):
                raw = super_name.resolve(abc.constant_pool, "multiname")
            else:
                raw = super_name
            super_str = str(raw)
            # Clean namespace prefix (e.g., "PACKAGE_NAMESPACE::" or "PACKAGE_NAMESPACE.")
            cleaned = _strip_known_namespace_prefix(super_str)
            # Now cleaned should be like "flash.display::Sprite" or "flash.display.Sprite"
            # For import, we need dot notation: "flash.display.Sprite"
            # For extends clause, we need short name "Sprite"
            if "::" in cleaned:
                # Split at first "::" to get package and name
                package, name = cleaned.split("::", 1)
                # The name may still contain "::" if nested (e.g., "display::Sprite")
                # Actually we should get the last part as short name
                if "::" in name:
                    # Handle cases like "display::Sprite"
                    package_part, short_name = name.rsplit("::", 1)
                    package = package + "." + package_part if package else package_part
                    name = short_name
                super_token = name
                # Add import if super class is from different package
                if package and package != current_package:
                    fqcn = f"{package}.{name}"
                    all_imports.add(fqcn)
            elif "." in cleaned:
                # Already in dot notation
                parts = cleaned.split(".")
                super_token = parts[-1]
                package = ".".join(parts[:-1]) if len(parts) > 1 else ""
                if package and package != current_package:
                    all_imports.add(cleaned)
            else:
                super_token = cleaned
            if super_token and super_token != "Object" and super_token != "*":
                extends_clause = super_token
                # Add import for extends type (built-in types)
                if super_token in BUILT_IN_TYPES:
                    all_imports.add(BUILT_IN_TYPES[super_token])

    interfaces = (
        list(getattr(instance, "interfaces", [])) if instance is not None else []
    )
    implements_clause_parts = []
    for iface in interfaces:
        iface_str = str(iface)
        # Clean namespace prefix
        cleaned = _strip_known_namespace_prefix(iface_str)
        if "::" in cleaned:
            package, name = cleaned.split("::", 1)
            if "::" in name:
                package_part, short_name = name.rsplit("::", 1)
                package = package + "." + package_part if package else package_part
                name = short_name
            iface_name = name
            # Add import if interface is from different package
            if package and package != current_package:
                fqcn = f"{package}.{name}"
                all_imports.add(fqcn)
        elif "." in cleaned:
            parts = cleaned.split(".")
            iface_name = parts[-1]
            package = ".".join(parts[:-1]) if len(parts) > 1 else ""
            if package and package != current_package:
                all_imports.add(cleaned)
        else:
            iface_name = cleaned
        implements_clause_parts.append(iface_name)
        # Add import for interface (built-in types)
        if iface_name in BUILT_IN_TYPES:
            all_imports.add(BUILT_IN_TYPES[iface_name])
    implements_clause = (
        ", ".join(implements_clause_parts) if implements_clause_parts else ""
    )

    # Calculate visibility for class/interface
    visibility = "public"  # default
    if instance is not None:
        visibility = _visibility_from_namespace_kind(
            _namespace_kind_from_qualified_name(getattr(instance, "name", "")),
            for_class=True,
        )

    # Create class/interface node
    node_type = "interface" if is_interface else "class"
    class_node = Node(
        node_type,
        [
            Node("class_name", [class_name]),
            Node("extends", [extends_clause]) if extends_clause else Node("nop"),
            (
                Node("implements", [implements_clause])
                if implements_clause
                else Node("nop")
            ),
            Node("fields", field_nodes),
            Node("methods", method_nodes),
        ],
        {
            "package": ".".join(package_parts) if package_parts else "",
            "imports": list(all_imports),
            "visibility": visibility,
        },
    )

    return class_node


def _build_field_declarations(
    abc: ABCFile,
    instance: Any | None,
    cls: Any | None,
    field_initializers: dict[str, str],
    trait_indices: list[int],
    constructor_initializers: dict[str, str] | None = None,
    *,
    int_format: str = "dec",
) -> list[Node]:
    """Build field declaration nodes from instance and class traits."""
    instance_traits = (
        list(getattr(instance, "traits", [])) if instance is not None else []
    )
    class_traits = list(getattr(cls, "traits", [])) if cls is not None else []
    constructor_initializers = constructor_initializers or {}
    del trait_indices

    field_nodes: list[Node] = []
    declared_names: set[str] = set()
    used_identifiers: set[str] = set()

    def _append_trait_member(trait: object, *, is_static: bool) -> None:
        kind = getattr(trait, "kind", None)
        if kind not in (TraitKind.SLOT, TraitKind.CONST):
            return  # Only output fields and constants

        raw_name = _short_multiname(getattr(trait, "name", "")).strip()
        if not raw_name:
            raw_name = "field"

        name = raw_name  # Constants should have unique names
        if name in {"prototype", "__static_init__"}:
            return

        # Avoid duplicate declarations
        # if name in declared_names:
        #     return

        raw_name = _short_multiname(getattr(trait, "name", "")).strip()
        if not raw_name:
            raw_name = "field"

        fallback = raw_name if raw_name else "field"
        name = _sanitize_identifier(raw_name, fallback, used_identifiers)
        if name in {"prototype", "__static_init__"}:
            return

        # Avoid duplicate declarations
        if name in declared_names:
            return

        type_name = _resolve_trait_type_name(abc, trait)
        init_expr = _trait_default_initializer_expr(abc, trait, int_format=int_format)
        # For static fields, prefer extracted initializers from __static_init__.
        if is_static and name in field_initializers:
            init_expr = field_initializers.get(name)

        # Infer type from init_expr if available
        if init_expr and type_name in ("*", "uint"):
            if init_expr.startswith("[") and init_expr.endswith("]"):
                type_name = "Array"

        visibility = _visibility_from_namespace_kind(
            _namespace_kind_from_qualified_name(getattr(trait, "name", "")),
            for_class=False,
        )

        field_node = Node(
            "field_declaration",
            [],
            {
                "name": name,
                "type": type_name,
                "visibility": visibility,
                "static": is_static,
                "const": kind == TraitKind.CONST,
                "init_expr": init_expr,
            },
        )
        field_nodes.append(field_node)
        declared_names.add(name)

    # Match the class-layout export path: static fields first, then instance fields,
    # both ordered by slot_id when available.
    for trait in _ordered_field_traits(class_traits):
        _append_trait_member(trait, is_static=True)
    for trait in _ordered_field_traits(instance_traits):
        _append_trait_member(trait, is_static=False)

    # Add fields from constructor initializers that weren't declared as traits
    if constructor_initializers:
        for name in sorted(constructor_initializers):
            if name in declared_names:
                continue
            value = constructor_initializers[name]
            field_node = Node(
                "field_declaration",
                [],
                {
                    "name": name,
                    "type": "*",
                    "visibility": "private",
                    "static": False,
                    "const": False,
                    "init_expr": value,
                },
            )
            field_nodes.append(field_node)
            declared_names.add(name)

    return field_nodes
