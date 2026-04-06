from __future__ import annotations

from typing import Any

from oven.core.ast import Node

# Pre-computed indent strings for performance
_INDENTS = ["    " * i for i in range(64)]


def emit_class_ast(node: Node, indent_level: int = 0) -> str:
    """Convert a class AST node to AS3 source code.

    Args:
        node: Class AST node (type "class")
        indent_level: Current indentation level (0 = top-level)

    Returns:
        AS3 source code string
    """
    if node.type == "package":
        return _emit_package_node(node, indent_level)
    elif node.type == "class":
        # Check if this class node has package metadata
        package_name = node.metadata.get("package", "")
        imports = node.metadata.get("imports", [])
        if package_name or imports:
            # Create a temporary package node for emission
            package_node = Node(
                "package", [node], {"package": package_name, "imports": imports}
            )
            return _emit_package_node(package_node, indent_level)
        else:
            return _emit_class_node(node, indent_level)
    elif node.type == "interface":
        # Check if this interface node has package metadata
        package_name = node.metadata.get("package", "")
        imports = node.metadata.get("imports", [])
        if package_name or imports:
            # Create a temporary package node for emission
            package_node = Node(
                "package", [node], {"package": package_name, "imports": imports}
            )
            return _emit_package_node(package_node, indent_level)
        else:
            return _emit_interface_node(node, indent_level)
    else:
        # Assume it's already a class node
        return _emit_class_node(node, indent_level)


def _emit_package_node(node: Node, indent_level: int) -> str:
    """Emit a package node with imports and class/interface."""
    package_name = node.metadata.get("package", "")
    imports = node.metadata.get("imports", [])
    content_node = None
    content_type = None
    for child in node.children:
        if isinstance(child, Node) and child.type in ("class", "interface"):
            content_node = child
            content_type = child.type
            break

    lines = []
    if package_name:
        lines.append(f"package {package_name}")
    else:
        lines.append("package")
    lines.append("{")
    lines.append("")

    for imp in sorted(imports):
        lines.append(f"    import {imp};")
    if imports:
        lines.append("")

    if content_node:
        if content_type == "class":
            content_source = _emit_class_node(content_node, indent_level + 1)
        else:  # interface
            content_source = _emit_interface_node(content_node, indent_level + 1)
        lines.append(content_source)

    lines.append("}")
    return "\n".join(lines)


def _emit_interface_node(node: Node, indent_level: int) -> str:
    """Emit an interface node with fields and methods."""
    class_name = ""
    extends = ""
    implements = ""
    fields: list[Node] = []
    methods: list[Node] = []

    # Extract information from children
    for child in node.children:
        if not isinstance(child, Node):
            continue
        if child.type == "class_name":
            class_name = child.children[0] if child.children else ""
        elif child.type == "extends":
            extends = child.children[0] if child.children else ""
        elif child.type == "implements":
            implements = child.children[0] if child.children else ""
        elif child.type == "fields":
            fields = [c for c in child.children if isinstance(c, Node)]
        elif child.type == "methods":
            methods = [c for c in child.children if isinstance(c, Node)]

    indent = _INDENTS[indent_level] if indent_level < 64 else "    " * indent_level
    # Get visibility from metadata, default to public
    visibility = node.metadata.get("visibility", "public")
    interface_head = f"{indent}{visibility} interface {class_name}"
    if extends:
        interface_head += f" extends {extends}"
    if implements:
        interface_head += f" implements {implements}"
    interface_head += " {"

    lines = [interface_head]

    # Emit methods (interfaces don't have fields)
    for method in methods:
        method_source = _emit_method_node(method, indent_level + 1)
        if method_source:
            lines.append(method_source)

    lines.append(f"{indent}}}")
    return "\n".join(lines)


def _emit_class_node(node: Node, indent_level: int) -> str:
    """Emit a class node with fields and methods."""
    class_name = ""
    extends = ""
    implements = ""
    fields: list[Node] = []
    methods: list[Node] = []

    # Extract information from children
    for child in node.children:
        if not isinstance(child, Node):
            continue
        if child.type == "class_name":
            class_name = child.children[0] if child.children else ""
        elif child.type == "extends":
            extends = child.children[0] if child.children else ""
        elif child.type == "implements":
            implements = child.children[0] if child.children else ""
        elif child.type == "fields":
            fields = [c for c in child.children if isinstance(c, Node)]
        elif child.type == "methods":
            methods = [c for c in child.children if isinstance(c, Node)]

    indent = _INDENTS[indent_level] if indent_level < 64 else "    " * indent_level
    # Get visibility from metadata, default to public
    visibility = node.metadata.get("visibility", "public")
    class_head = f"{indent}{visibility} class {class_name}"
    if extends:
        class_head += f" extends {extends}"
    if implements:
        class_head += f" implements {implements}"
    class_head += " {"

    lines = [class_head]

    # Emit fields
    for field in fields:
        field_source = _emit_field_node(field, indent_level + 1)
        if field_source:
            lines.append(field_source)

    # Emit methods
    for method in methods:
        method_source = _emit_method_node(method, indent_level + 1)
        if method_source:
            lines.append(method_source)

    lines.append(f"{indent}}}")
    return "\n".join(lines)


def _emit_field_node(node: Node, indent_level: int) -> str:
    """Emit a field declaration node."""
    metadata = node.metadata
    name = metadata.get("name", "")
    type_name = metadata.get("type", "*")
    visibility = metadata.get("visibility", "private")
    is_static = metadata.get("static", False)
    is_const = metadata.get("const", False)
    init_expr = metadata.get("init_expr")

    if not name:
        return ""

    indent = _INDENTS[indent_level] if indent_level < 64 else "    " * indent_level
    parts = [indent, visibility]
    if is_static:
        parts.append(" static")
    if is_const:
        parts.append(" const")
    else:
        parts.append(" var")
    parts.append(f" {name}:{type_name}")
    if init_expr is not None:
        # Format numeric constants as hex
        if init_expr.isdigit():
            init_expr = f"0x{int(init_expr):X}"
        parts.append(f" = {init_expr}")
    parts.append(";")

    return "".join(parts)


def _emit_method_node(node: Node, indent_level: int) -> str:
    """Emit a method node."""
    signature = ""
    body_text = ""
    is_constructor = node.metadata.get("is_constructor", False)
    for child in node.children:
        if not isinstance(child, Node):
            continue
        if child.type == "method_signature":
            signature = child.children[0] if child.children else ""
        elif child.type == "method_body_text":
            body_text = child.children[0] if child.children else ""

    indent = _INDENTS[indent_level] if indent_level < 64 else "    " * indent_level
    lines = []
    lines.append(f"{indent}{signature} {{")

    # Add method body lines with extra indentation
    if body_text:
        for line in body_text.splitlines():
            lines.append(f"{indent}    {line}")
    else:
        lines.append(f"{indent}    // empty")

    lines.append(f"{indent}}}")
    return "\n".join(lines)
