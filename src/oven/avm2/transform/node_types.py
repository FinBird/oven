from __future__ import annotations

from typing import Final, Literal, TypeAlias


class AS3NodeTypes:
    """Canonical AVM2/AS3 node type names used by transform passes."""

    ADD: Final[str] = "add"
    AND: Final[str] = "and"
    AS_TYPE: Final[str] = "as_type"
    AS_TYPE_LATE: Final[str] = "as_type_late"
    BEGIN: Final[str] = "begin"
    BIT_AND: Final[str] = "bit_and"
    BIT_OR: Final[str] = "bit_or"
    BIT_XOR: Final[str] = "bit_xor"
    BREAK: Final[str] = "break"
    CALL: Final[str] = "call"
    CALL_PROPERTY: Final[str] = "call_property"
    CALL_PROPERTY_LEX: Final[str] = "call_property_lex"
    CALL_PROPERTY_VOID: Final[str] = "call_property_void"
    CALL_SUPER: Final[str] = "call_super"
    CALL_SUPER_VOID: Final[str] = "call_super_void"
    CASE: Final[str] = "case"
    CATCH_SCOPE_OBJECT: Final[str] = "catch_scope_object"
    COERCE: Final[str] = "coerce"
    COERCE_B: Final[str] = "coerce_b"
    COERCE_I: Final[str] = "coerce_i"
    COERCE_U: Final[str] = "coerce_u"
    COERCE_D: Final[str] = "coerce_d"
    COERCE_S: Final[str] = "coerce_s"
    CONSTRUCT: Final[str] = "construct"
    CONSTRUCT_PROPERTY: Final[str] = "construct_property"
    CONSTRUCT_SUPER: Final[str] = "construct_super"
    CONTINUE: Final[str] = "continue"
    CONVERT: Final[str] = "convert"
    CONVERT_D: Final[str] = "convert_d"
    CONVERT_I: Final[str] = "convert_i"
    CONVERT_O: Final[str] = "convert_o"
    CONVERT_S: Final[str] = "convert_s"
    CONVERT_U: Final[str] = "convert_u"
    DEC_LOCAL: Final[str] = "dec_local"
    DEC_LOCAL_I: Final[str] = "dec_local_i"
    DECREMENT: Final[str] = "decrement"
    DECREMENT_I: Final[str] = "decrement_i"
    DEFAULT: Final[str] = "default"
    DELETE: Final[str] = "delete"
    DIVIDE: Final[str] = "divide"
    DOUBLE: Final[str] = "double"
    EQ: Final[str] = "=="
    EXPAND: Final[str] = "expand"
    FALSE: Final[str] = "false"
    FIELD_INITIALIZER: Final[str] = "field_initializer"
    FIELD_INITIALIZERS: Final[str] = "field_initializers"
    FIND_PROPERTY: Final[str] = "find_property"
    FIND_PROPERTY_STRICT: Final[str] = "find_property_strict"
    FOR: Final[str] = "for"
    FOR_EACH_IN: Final[str] = "for_each_in"
    FOR_IN: Final[str] = "for_in"
    GE: Final[str] = ">="
    GET_GLOBAL_SCOPE: Final[str] = "get_global_scope"
    GET_LEX: Final[str] = "get_lex"
    GET_LOCAL: Final[str] = "get_local"
    GET_PROPERTY: Final[str] = "get_property"
    GET_SCOPE_OBJECT: Final[str] = "get_scope_object"
    GET_SLOT: Final[str] = "get_slot"
    GET_SUPER: Final[str] = "get_super"
    GT: Final[str] = ">"
    HAS_NEXT: Final[str] = "has_next"
    HAS_NEXT2: Final[str] = "has_next2"
    IF: Final[str] = "if"
    IN: Final[str] = "in"
    INC_LOCAL: Final[str] = "inc_local"
    INC_LOCAL_I: Final[str] = "inc_local_i"
    INCREMENT: Final[str] = "increment"
    INCREMENT_I: Final[str] = "increment_i"
    INIT_PROPERTY: Final[str] = "init_property"
    INTEGER: Final[str] = "integer"
    IS_TYPE: Final[str] = "is_type"
    IS_TYPE_LATE: Final[str] = "is_type_late"
    JUMP: Final[str] = "jump"
    JUMP_IF: Final[str] = "jump_if"
    KILL: Final[str] = "kill"
    LABEL: Final[str] = "label"
    LE: Final[str] = "<="
    LOOKUP_SWITCH: Final[str] = "lookup_switch"
    LSHIFT: Final[str] = "lshift"
    LT: Final[str] = "<"
    MODULO: Final[str] = "modulo"
    MULTIPLY: Final[str] = "multiply"
    NAN: Final[str] = "nan"
    NEGATE: Final[str] = "negate"
    NE: Final[str] = "!="
    NEW_ACTIVATION: Final[str] = "new_activation"
    NEW_ARRAY: Final[str] = "new_array"
    NEW_CLASS: Final[str] = "new_class"
    NEW_FUNCTION: Final[str] = "new_function"
    NEW_OBJECT: Final[str] = "new_object"
    NEXT_NAME: Final[str] = "next_name"
    NEXT_VALUE: Final[str] = "next_value"
    NOP: Final[str] = "nop"
    NOT: Final[str] = "!"
    NULL: Final[str] = "null"
    OR: Final[str] = "or"
    POP: Final[str] = "pop"
    POP_SCOPE: Final[str] = "pop_scope"
    POST_DECREMENT_LOCAL: Final[str] = "post_decrement_local"
    POST_DECREMENT_PROPERTY: Final[str] = "post_decrement_property"
    POST_INCREMENT_LOCAL: Final[str] = "post_increment_local"
    POST_INCREMENT_PROPERTY: Final[str] = "post_increment_property"
    PRE_DECREMENT_LOCAL: Final[str] = "pre_decrement_local"
    PRE_DECREMENT_PROPERTY: Final[str] = "pre_decrement_property"
    PRE_INCREMENT_LOCAL: Final[str] = "pre_increment_local"
    PRE_INCREMENT_PROPERTY: Final[str] = "pre_increment_property"
    PUSH_SCOPE: Final[str] = "push_scope"
    PUSH_WITH: Final[str] = "push_with"
    REMOVE: Final[str] = "remove"
    RETURN_VALUE: Final[str] = "return_value"
    RETURN_VOID: Final[str] = "return_void"
    ROOT: Final[str] = "root"
    RSHIFT: Final[str] = "rshift"
    SET_LOCAL: Final[str] = "set_local"
    SET_PROPERTY: Final[str] = "set_property"
    SET_SCOPE: Final[str] = "set_scope"
    SET_SLOT: Final[str] = "set_slot"
    SET_SUPER: Final[str] = "set_super"
    STACK_HOLE: Final[str] = "stack_hole"
    STRICT_EQ: Final[str] = "==="
    STRICT_NE: Final[str] = "!=="
    STRING: Final[str] = "string"
    SUBTRACT: Final[str] = "subtract"
    SWITCH: Final[str] = "switch"
    TERNARY: Final[str] = "ternary"
    TERNARY_IF: Final[str] = "ternary_if"
    TERNARY_IF_BOOLEAN: Final[str] = "ternary_if_boolean"
    THROW: Final[str] = "throw"
    TRUE: Final[str] = "true"
    UNDEFINED: Final[str] = "undefined"
    UNSIGNED: Final[str] = "unsigned"
    URSHIFT: Final[str] = "urshift"
    WHILE: Final[str] = "while"
    WITH: Final[str] = "with"


AS3NodeType: TypeAlias = Literal[
    "!",
    "!=",
    "!==",
    "<",
    "<=",
    "==",
    "===",
    ">",
    ">=",
    "add",
    "and",
    "as_type",
    "as_type_late",
    "begin",
    "bit_and",
    "bit_or",
    "bit_xor",
    "break",
    "call",
    "call_property",
    "call_property_lex",
    "call_property_void",
    "call_super",
    "call_super_void",
    "case",
    "catch_scope_object",
    "coerce",
    "coerce_b",
    "coerce_i",
    "coerce_u",
    "coerce_d",
    "coerce_s",
    "construct",
    "construct_property",
    "construct_super",
    "continue",
    "convert",
    "convert_d",
    "convert_i",
    "convert_o",
    "convert_s",
    "convert_u",
    "dec_local",
    "dec_local_i",
    "decrement",
    "decrement_i",
    "default",
    "delete",
    "divide",
    "double",
    "expand",
    "false",
    "field_initializer",
    "field_initializers",
    "find_property",
    "find_property_strict",
    "for",
    "for_each_in",
    "for_in",
    "get_global_scope",
    "get_lex",
    "get_local",
    "get_property",
    "get_scope_object",
    "get_slot",
    "get_super",
    "has_next",
    "has_next2",
    "if",
    "in",
    "inc_local",
    "inc_local_i",
    "increment",
    "increment_i",
    "init_property",
    "integer",
    "is_type",
    "is_type_late",
    "jump",
    "jump_if",
    "kill",
    "label",
    "lookup_switch",
    "lshift",
    "modulo",
    "multiply",
    "nan",
    "negate",
    "new_activation",
    "new_array",
    "new_class",
    "new_function",
    "new_object",
    "next_name",
    "next_value",
    "nop",
    "null",
    "or",
    "pop",
    "pop_scope",
    "post_decrement_local",
    "post_decrement_property",
    "post_increment_local",
    "post_increment_property",
    "pre_decrement_local",
    "pre_decrement_property",
    "pre_increment_local",
    "pre_increment_property",
    "push_scope",
    "push_with",
    "remove",
    "return_value",
    "return_void",
    "root",
    "rshift",
    "set_local",
    "set_property",
    "set_scope",
    "set_slot",
    "set_super",
    "stack_hole",
    "string",
    "subtract",
    "switch",
    "ternary",
    "ternary_if",
    "ternary_if_boolean",
    "throw",
    "true",
    "undefined",
    "unsigned",
    "urshift",
    "while",
    "with",
]
