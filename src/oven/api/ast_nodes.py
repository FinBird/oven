from __future__ import annotations

from typing import Final, Literal, TypeAlias


class AS3ClassNodeTypes:
    """AST node types for AS3 class-level constructs."""

    # Package and module structure
    PACKAGE: Final[str] = "package"
    IMPORT: Final[str] = "import"
    CLASS: Final[str] = "class"
    INTERFACE: Final[str] = "interface"

    # Class members
    FIELD_DECLARATION: Final[str] = "field_declaration"
    PROPERTY_DECLARATION: Final[str] = "property_declaration"
    METHOD: Final[str] = "method"
    CONSTRUCTOR: Final[str] = "constructor"
    STATIC_INITIALIZER: Final[str] = "static_initializer"

    # Modifiers and annotations
    MODIFIERS: Final[str] = "modifiers"
    ANNOTATION: Final[str] = "annotation"

    # Type references
    TYPE_REFERENCE: Final[str] = "type_reference"
    TYPE_PARAMETER: Final[str] = "type_parameter"
    TYPE_ARGUMENT: Final[str] = "type_argument"

    # Signatures
    CLASS_SIGNATURE: Final[str] = "class_signature"
    METHOD_SIGNATURE: Final[str] = "method_signature"
    CONSTRUCTOR_SIGNATURE: Final[str] = "constructor_signature"

    # Implementation clauses
    EXTENDS_CLAUSE: Final[str] = "extends_clause"
    IMPLEMENTS_CLAUSE: Final[str] = "implements_clause"


AS3ClassNodeType: TypeAlias = Literal[
    "package",
    "import",
    "class",
    "interface",
    "field_declaration",
    "property_declaration",
    "method",
    "constructor",
    "static_initializer",
    "modifiers",
    "annotation",
    "type_reference",
    "type_parameter",
    "type_argument",
    "class_signature",
    "method_signature",
    "constructor_signature",
    "extends_clause",
    "implements_clause",
]
