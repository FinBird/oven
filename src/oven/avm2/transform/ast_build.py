from __future__ import annotations

from typing import Any, Sequence, cast

from oven.avm2.enums import Instruction, MultinameKind, Opcode
from oven.core.ast import Node
from oven.core.pipeline import Transform


def safe_int(val: Any) -> int:
    """Safely convert value to int."""
    try:
        return int(val)
    except (TypeError, ValueError):
        return 0


class ASTBuild(Transform[Any, Any]):
    """
    Build low-level AST from AVM2 instructions.

    This stage intentionally keeps control-flow nodes close to the original
    bytecode shape so that later passes (`ASTNormalize`, `CFGBuild`,
    `CFGReduce`, `NFNormalize`) can structure the code.
    """

    _LOCAL_GET = {
        Opcode.GetLocal0: 0,
        Opcode.GetLocal1: 1,
        Opcode.GetLocal2: 2,
        Opcode.GetLocal3: 3,
    }

    _LOCAL_SET = {
        Opcode.SetLocal0: 0,
        Opcode.SetLocal1: 1,
        Opcode.SetLocal2: 2,
        Opcode.SetLocal3: 3,
    }

    _CONDITIONALS: dict[Opcode, tuple[str, int]] = {
        Opcode.IfEq: ("if_eq", 2),
        Opcode.IfFalse: ("if_false", 1),
        Opcode.IfGe: ("if_ge", 2),
        Opcode.IfGt: ("if_gt", 2),
        Opcode.IfLe: ("if_le", 2),
        Opcode.IfLt: ("if_lt", 2),
        Opcode.IfNe: ("if_ne", 2),
        Opcode.IfNge: ("if_nge", 2),
        Opcode.IfNgt: ("if_ngt", 2),
        Opcode.IfNle: ("if_nle", 2),
        Opcode.IfNlt: ("if_nlt", 2),
        Opcode.IfStrictEq: ("if_strict_eq", 2),
        Opcode.IfStrictNe: ("if_strict_ne", 2),
        Opcode.IfTrue: ("if_true", 1),
    }
    _CONDITIONAL_TYPES = frozenset(name for name, _ in _CONDITIONALS.values())

    _BINARY: dict[Opcode, str] = {
        Opcode.Add: "add",
        Opcode.Subtract: "subtract",
        Opcode.Multiply: "multiply",
        Opcode.Divide: "divide",
        Opcode.Modulo: "modulo",
        Opcode.BitAnd: "bit_and",
        Opcode.BitOr: "bit_or",
        Opcode.BitXor: "bit_xor",
        Opcode.LShift: "lshift",
        Opcode.RShift: "rshift",
        Opcode.URShift: "urshift",
        Opcode.Equals: "==",
        Opcode.StrictEquals: "===",
        Opcode.LessThan: "<",
        Opcode.LessEquals: "<=",
        Opcode.GreaterThan: ">",
        Opcode.GreaterEquals: ">=",
        Opcode.In: "in",
    }

    _UNARY: dict[Opcode, str] = {
        Opcode.Not: "!",
        Opcode.Negate: "negate",
        Opcode.Increment: "increment",
        Opcode.IncrementI: "increment_i",
        Opcode.Decrement: "decrement",
        Opcode.DecrementI: "decrement_i",
    }

    _SIMPLE_CONVERTS: dict[Opcode, str] = {
        Opcode.ConvertI: "integer",
        Opcode.ConvertU: "unsigned",
        Opcode.ConvertD: "double",
        Opcode.ConvertS: "string",
        Opcode.ConvertO: "object",
    }

    _COERCES: dict[Opcode, str] = {
        Opcode.CoerceI: "integer",
        Opcode.CoerceU: "unsigned",
        Opcode.CoerceD: "double",
        Opcode.CoerceS: "string",
        Opcode.CoerceO: "object",
        Opcode.CoerceA: "any",
    }

    _SHORTCUT_START = frozenset(
        {Opcode.ConvertB, Opcode.CoerceB, Opcode.IfTrue, Opcode.IfFalse}
    )
    _STACK_STATEMENTS: dict[Opcode, tuple[str, int]] = {
        Opcode.ReturnValue: ("return_value", 1),
        Opcode.Throw: ("throw", 1),
        Opcode.Pop: ("pop", 1),
        Opcode.PushScope: ("push_scope", 1),
        Opcode.PushWith: ("push_with", 1),
    }
    _ZERO_ARG_STATEMENTS: dict[Opcode, str] = {
        Opcode.ReturnVoid: "return_void",
        Opcode.PopScope: "pop_scope",
    }

    def __init__(self, options: dict[str, Any] | None = None) -> None:
        self.options = options or {}
        self._current_instruction: Instruction | None = None

    def transform(self, *args: Any) -> Any:
        """
        Entry point for the pipeline.
        Expects args[0] to be instruction sequence, args[1] to be method body.
        Returns (ast, body, []).
        """
        if len(args) < 2:
            # Should have at least code and body
            return args

        code: Sequence[Instruction] = args[0]
        body: Any = args[1]

        self._stack: list[Node] = []
        self._ast = Node("root")
        self._instructions = list(code)
        self._next_temp_local = self._initial_temp_local(body, self._instructions)

        self._shortjump_targets: list[int] = []
        self._ternary_targets: list[int] = []
        self._in_shortcut = False
        self._shortcut_armed = False

        for index, instruction in enumerate(self._instructions):
            self._finalize_complex_expressions(instruction.offset)
            self._maybe_enter_shortcut(instruction.opcode)
            if self._in_shortcut and self._handle_shortcut(index, instruction):
                continue
            self._dispatch(index, instruction)

        self._flush_conditionals()

        # Preserve strict diagnostics when requested.
        if self.options.get("validate_stack_exit") and self._stack:
            raise ValueError(f"nonempty stack on exit: {self._stack!r}")

        # Emit residual stack expressions as standalone statements so short
        # expression-only bytecode sequences still produce observable AST nodes.
        while self._stack:
            self._emit(self._stack.pop(0))

        return self._ast, body, []

    def _dispatch(self, index: int, instruction: Instruction) -> None:
        self._current_instruction = instruction
        opcode = instruction.opcode

        match opcode:
            case (
                Opcode.GetLocal0
                | Opcode.GetLocal1
                | Opcode.GetLocal2
                | Opcode.GetLocal3
                | Opcode.GetLocal
            ):
                self._handle_get_local(instruction)
                return

            case (
                Opcode.SetLocal0
                | Opcode.SetLocal1
                | Opcode.SetLocal2
                | Opcode.SetLocal3
                | Opcode.SetLocal
            ):
                self._handle_set_local(instruction)
                return

            case Opcode.Dup:
                self._handle_dup(instruction)
                return

            case Opcode.Swap:
                self._handle_swap(instruction)
                return

            case op if op in self._CONDITIONALS:
                self._handle_conditional(index, instruction)
                return

            case Opcode.Jump:
                self._handle_jump(index, instruction)
                return

            case Opcode.LookupSwitch:
                self._handle_lookup_switch(instruction)
                return

            case _ if self._handle_common_statement_opcode(instruction):
                return

            case Opcode.FindPropStrict | Opcode.FindProperty:
                target = instruction.operands[0] if instruction.operands else None
                node_type = (
                    "find_property_strict"
                    if opcode == Opcode.FindPropStrict
                    else "find_property"
                )
                self._produce(
                    Node(node_type, [target], self._label(instruction.offset))
                )
                return

            case Opcode.GetGlobalScope:
                self._produce(
                    Node("get_global_scope", [], self._label(instruction.offset))
                )
                return

            case Opcode.GetScopeObject:
                scope_index = (
                    safe_int(instruction.operands[0]) if instruction.operands else 0
                )
                self._produce(
                    Node(
                        "get_scope_object",
                        [scope_index],
                        self._label(instruction.offset),
                    )
                )
                return

            case Opcode.GetLex:
                target = instruction.operands[0] if instruction.operands else None
                self._produce(
                    Node("get_lex", [target], self._label(instruction.offset))
                )
                return

            case Opcode.GetSuper:
                name = instruction.operands[0] if instruction.operands else None
                runtime_arity = self._runtime_multiname_arity(name)
                values = self._consume(1 + runtime_arity, opcode)
                subject = values[0]
                runtime_name_parts = values[1:]
                self._produce(
                    Node(
                        "get_super",
                        [subject, name, *runtime_name_parts],
                        self._label(instruction.offset),
                    )
                )
                return

            case Opcode.SetSuper:
                name = instruction.operands[0] if instruction.operands else None
                runtime_arity = self._runtime_multiname_arity(name)
                values = self._consume(2 + runtime_arity, opcode)
                subject = values[0]
                runtime_name_parts = values[1 : 1 + runtime_arity]
                value = values[-1]
                self._flush_conditionals()
                self._emit(
                    Node(
                        "set_super",
                        [subject, name, *runtime_name_parts, value],
                        self._label(instruction.offset),
                    )
                )
                return

            case Opcode.GetProperty:
                name = instruction.operands[0] if instruction.operands else None
                runtime_arity = self._runtime_multiname_arity(name)
                values = self._consume(1 + runtime_arity, opcode)
                subject = values[0]
                runtime_name_parts = values[1:]
                self._produce(
                    Node(
                        "get_property",
                        [subject, name, *runtime_name_parts],
                        self._label(instruction.offset),
                    )
                )
                return

            case Opcode.GetSlot:
                (scope,) = self._consume(1, opcode)
                slot_index = (
                    safe_int(instruction.operands[0]) if instruction.operands else 0
                )
                self._produce(
                    Node(
                        "get_slot", [slot_index, scope], self._label(instruction.offset)
                    )
                )
                return

            case Opcode.SetProperty | Opcode.InitProperty:
                name = instruction.operands[0] if instruction.operands else None
                runtime_arity = self._runtime_multiname_arity(name)
                values = self._consume(2 + runtime_arity, opcode)
                subject = values[0]
                runtime_name_parts = values[1 : 1 + runtime_arity]
                value = values[-1]
                node_type = (
                    "init_property" if opcode == Opcode.InitProperty else "set_property"
                )
                self._flush_conditionals()
                self._emit(
                    Node(
                        node_type,
                        [subject, name, *runtime_name_parts, value],
                        self._label(instruction.offset),
                    )
                )
                return

            case Opcode.DeleteProperty:
                name = instruction.operands[0] if instruction.operands else None
                runtime_arity = self._runtime_multiname_arity(name)
                values = self._consume(1 + runtime_arity, opcode)
                subject = values[0]
                runtime_name_parts = values[1:]
                self._produce(
                    Node(
                        "delete",
                        [subject, name, *runtime_name_parts],
                        self._label(instruction.offset),
                    )
                )
                return

            case Opcode.SetSlot:
                scope, value = self._consume(2, opcode)
                slot_index = (
                    safe_int(instruction.operands[0]) if instruction.operands else 0
                )
                self._flush_conditionals()
                self._emit(
                    Node(
                        "set_slot",
                        [slot_index, scope, value],
                        self._label(instruction.offset),
                    )
                )
                return

            case (
                Opcode.CallProperty
                | Opcode.CallPropLex
                | Opcode.CallPropVoid
                | Opcode.CallSuper
                | Opcode.CallSuperVoid
            ):
                self._handle_call_like(instruction)
                return

            case Opcode.Call:
                self._handle_call(instruction)
                return

            case Opcode.ConstructProp:
                self._handle_construct_prop(instruction)
                return

            case Opcode.Construct:
                self._handle_construct(instruction)
                return

            case Opcode.ConstructSuper:
                self._handle_construct_super(instruction)
                return

            case Opcode.NewObject:
                self._handle_new_object(instruction)
                return

            case Opcode.NewArray:
                self._handle_new_array(instruction)
                return

            case Opcode.NewActivation:
                self._produce(
                    Node("new_activation", [], self._label(instruction.offset))
                )
                return

            case Opcode.NewClass:
                self._handle_new_class(instruction)
                return

            case Opcode.NewFunction:
                method_index = (
                    safe_int(instruction.operands[0]) if instruction.operands else 0
                )
                self._produce(
                    Node(
                        "new_function", [method_index], self._label(instruction.offset)
                    )
                )
                return

            case Opcode.NextName:
                obj, index_value = self._consume(2, opcode)
                self._produce(
                    Node(
                        "next_name", [obj, index_value], self._label(instruction.offset)
                    )
                )
                return

            case Opcode.NextValue:
                obj, index_value = self._consume(2, opcode)
                self._produce(
                    Node(
                        "next_value",
                        [obj, index_value],
                        self._label(instruction.offset),
                    )
                )
                return

            case Opcode.HasNext:
                obj, index_value = self._consume(2, opcode)
                self._produce(
                    Node(
                        "has_next", [obj, index_value], self._label(instruction.offset)
                    )
                )
                return

            case Opcode.HasNext2:
                obj_reg = (
                    safe_int(instruction.operands[0]) if instruction.operands else 0
                )
                index_reg = (
                    safe_int(instruction.operands[1])
                    if len(instruction.operands) > 1
                    else 0
                )
                self._produce(
                    Node(
                        "has_next2",
                        [obj_reg, index_reg],
                        self._label(instruction.offset),
                    )
                )
                return

            case op if op in self._SIMPLE_CONVERTS:
                (value,) = self._consume(1, opcode)
                convert_type = self._SIMPLE_CONVERTS[opcode]
                if convert_type == "integer":
                    node_type = "convert_i"
                    children = [value]
                elif convert_type == "unsigned":
                    node_type = "convert_u"
                    children = [value]
                elif convert_type == "double":
                    node_type = "convert_d"
                    children = [value]
                elif convert_type == "string":
                    node_type = "convert_s"
                    children = [value]
                elif convert_type == "object":
                    node_type = "convert_o"
                    children = [value]
                else:
                    node_type = "convert"
                    children = [Node("literal", [convert_type]), value]
                self._produce(
                    Node(node_type, children, self._label(instruction.offset))
                )
                return

            case Opcode.Kill:
                local_index = (
                    safe_int(instruction.operands[0]) if instruction.operands else 0
                )
                self._flush_conditionals()
                self._emit(Node("kill", [local_index], self._label(instruction.offset)))
                return

            case Opcode.Coerce:
                (value,) = self._consume(1, opcode)
                type_name = instruction.operands[0] if instruction.operands else None
                self._produce(
                    Node("coerce", [type_name, value], self._label(instruction.offset))
                )
                return

            case Opcode.AsType:
                (value,) = self._consume(1, opcode)
                type_name = instruction.operands[0] if instruction.operands else None
                self._produce(
                    Node(
                        "as_type",
                        [
                            value,
                            Node(
                                "literal",
                                [str(type_name) if type_name is not None else ""],
                            ),
                        ],
                        self._label(instruction.offset),
                    )
                )
                return

            case Opcode.AsTypeLate:
                value, type_name = self._consume(2, opcode)
                self._produce(
                    Node(
                        "as_type_late",
                        [value, type_name],
                        self._label(instruction.offset),
                    )
                )
                return

            case Opcode.IsType:
                (value,) = self._consume(1, opcode)
                type_name = instruction.operands[0] if instruction.operands else None
                self._produce(
                    Node(
                        "is_type",
                        [
                            value,
                            Node(
                                "literal",
                                [str(type_name) if type_name is not None else ""],
                            ),
                        ],
                        self._label(instruction.offset),
                    )
                )
                return

            case Opcode.IsTypeLate:
                value, type_name = self._consume(2, opcode)
                self._produce(
                    Node(
                        "is_type_late",
                        [value, type_name],
                        self._label(instruction.offset),
                    )
                )
                return

            case op if op in self._COERCES:
                (value,) = self._consume(1, opcode)
                self._produce(
                    Node(
                        "coerce",
                        [self._COERCES[opcode], value],
                        self._label(instruction.offset),
                    )
                )
                return

            case Opcode.ConvertB | Opcode.CoerceB:
                (value,) = self._consume(1, opcode)
                self._produce(
                    Node("coerce_b", [value], self._label(instruction.offset))
                )
                return

            case Opcode.Label:
                self._emit(Node("label", [], self._label(instruction.offset)))
                return

            case op if op in self._BINARY:
                left, right = self._consume(2, opcode)
                self._produce(
                    Node(
                        self._BINARY[opcode],
                        [left, right],
                        self._label(instruction.offset),
                    )
                )
                return

            case op if op in self._UNARY:
                (value,) = self._consume(1, opcode)
                self._produce(
                    Node(self._UNARY[opcode], [value], self._label(instruction.offset))
                )
                return

            case _:
                pass

        literal = self._literal_node(instruction)
        if literal is not None:
            self._produce(literal)
            return

        self._flush_conditionals()
        node = Node(
            self._opcode_to_ast_type(opcode),
            list(instruction.operands),
            self._label(instruction.offset),
        )
        self._emit(node)

    def _handle_get_local(self, instruction: Instruction) -> None:
        index = self._local_index(instruction)
        self._produce(Node("get_local", [index], self._label(instruction.offset)))

    def _handle_set_local(self, instruction: Instruction) -> None:
        index = self._local_index(instruction)
        (value,) = self._consume(1, instruction.opcode)
        self._flush_conditionals()
        self._emit(Node("set_local", [index, value], self._label(instruction.offset)))

    def _handle_dup(self, instruction: Instruction) -> None:
        (value,) = self._consume(1, instruction.opcode)

        if self._is_dup_safe_expression(value):
            self._produce(value)
            self._produce(self._clone_with_label(value, instruction.offset))
            self._shortcut_armed = True
            return

        temp_local = self._alloc_temp_local()
        self._flush_conditionals()
        self._emit(
            Node("set_local", [temp_local, value], self._label(instruction.offset))
        )

        first_ref = Node("get_local", [temp_local], self._label(instruction.offset))
        self._produce(first_ref)
        self._produce(self._clone_with_label(first_ref, instruction.offset))
        self._shortcut_armed = True

    def _handle_swap(self, instruction: Instruction) -> None:
        left, right = self._consume(2, instruction.opcode)
        self._produce(right)
        self._produce(left)

    def _handle_conditional(self, insn_index: int, instruction: Instruction) -> None:
        cond_type, consumes = self._CONDITIONALS[instruction.opcode]
        params = self._consume(consumes, instruction.opcode)
        target = self._branch_target(insn_index, instruction)
        self._produce(
            Node(cond_type, params, {"label": instruction.offset, "offset": target})
        )

    def _handle_jump(self, insn_index: int, instruction: Instruction) -> None:
        target = self._branch_target(insn_index, instruction)
        jump_delta = safe_int(instruction.operands[0]) if instruction.operands else 0

        if jump_delta == 0:
            # `jump 0` can appear in selector chains compiled as:
            #   ifne next; push case; jump done; ...; jump 0; push default
            # Flushing here would turn the pending comparisons into empty `if`
            # statements and leave the final `lookupswitch` keyed by a constant.
            pending_selector_target = any(
                pending > instruction.offset for pending in self._ternary_targets
            )
            pending_conditionals = any(
                node.type in self._CONDITIONAL_TYPES for node in self._stack
            )
            if not (pending_selector_target and pending_conditionals):
                self._flush_conditionals()
            self._emit(Node("nop", [], self._label(instruction.offset)))
            return

        if self._stack and self._stack[-1].type not in self._CONDITIONAL_TYPES:
            if self._extend_complex_expr(self._CONDITIONAL_TYPES):
                self._ternary_targets.append(target)
                return

        self._flush_conditionals()
        self._emit(Node("jump", [target], self._label(instruction.offset)))

    def _handle_lookup_switch(self, instruction: Instruction) -> None:
        # Accept both normalized 3-operand form
        #   [default_rel, max_case_index, [case_offsets...]]
        # and compact 2-operand test form
        #   [default_rel, [case_offsets...]].
        if len(instruction.operands) >= 3:
            default_rel = safe_int(instruction.operands[0])
            case_offsets = instruction.operands[2]
        elif len(instruction.operands) == 2:
            default_rel = safe_int(instruction.operands[0])
            case_offsets = instruction.operands[1]
        else:
            raise ValueError(
                f"lookup_switch expects 2 or 3 operands, got {instruction.operands!r}"
            )

        if not isinstance(case_offsets, list):
            raise ValueError(
                f"lookup_switch case offsets must be a list, got {case_offsets!r}"
            )

        # AVM2 overview: lookupswitch base location is the instruction address itself.
        default_target = instruction.offset + default_rel
        case_targets = [instruction.offset + int(offset) for offset in case_offsets]

        (expr,) = self._consume(1, instruction.opcode)
        self._emit_statement(
            "lookup_switch", [default_target, case_targets, expr], instruction.offset
        )

    def _handle_call_like(self, instruction: Instruction) -> None:
        name = instruction.operands[0] if instruction.operands else None
        argc = safe_int(instruction.operands[1]) if len(instruction.operands) > 1 else 0
        runtime_arity = self._runtime_multiname_arity(name)
        values = self._consume(argc + 1 + runtime_arity, instruction.opcode)
        subject = values[0]
        runtime_name_parts = values[1 : 1 + runtime_arity]
        args = values[1 + runtime_arity :]

        if instruction.opcode == Opcode.CallPropLex:
            node_type = "call_property_lex"
            void_call = False
        elif instruction.opcode == Opcode.CallPropVoid:
            node_type = "call_property_void"
            void_call = True
        elif instruction.opcode == Opcode.CallSuper:
            node_type = "call_super"
            void_call = False
        elif instruction.opcode == Opcode.CallSuperVoid:
            node_type = "call_super_void"
            void_call = True
        else:
            node_type = "call_property"
            void_call = False

        node = Node(
            node_type,
            [subject, name, *runtime_name_parts, *args],
            self._label(instruction.offset),
        )
        if void_call:
            self._flush_conditionals()
            self._emit(node)
        else:
            self._produce(node)

    def _handle_call(self, instruction: Instruction) -> None:
        argc = safe_int(instruction.operands[0]) if instruction.operands else 0
        values = self._consume(argc + 2, instruction.opcode)
        subject = values[0]
        this_obj = values[1]
        args = values[2:]
        self._produce(
            Node("call", [subject, this_obj, *args], self._label(instruction.offset))
        )

    def _handle_construct_prop(self, instruction: Instruction) -> None:
        name = instruction.operands[0] if instruction.operands else None
        argc = safe_int(instruction.operands[1]) if len(instruction.operands) > 1 else 0
        runtime_arity = self._runtime_multiname_arity(name)
        values = self._consume(argc + 1 + runtime_arity, instruction.opcode)
        subject = values[0]
        runtime_name_parts = values[1 : 1 + runtime_arity]
        args = values[1 + runtime_arity :]
        self._produce(
            Node(
                "construct_property",
                [subject, name, *runtime_name_parts, *args],
                self._label(instruction.offset),
            )
        )

    def _handle_construct(self, instruction: Instruction) -> None:
        argc = safe_int(instruction.operands[0]) if instruction.operands else 0
        values = self._consume(argc + 1, instruction.opcode)
        target, args = values[0], values[1:]
        self._produce(
            Node("construct", [target, *args], self._label(instruction.offset))
        )

    def _handle_construct_super(self, instruction: Instruction) -> None:
        argc = safe_int(instruction.operands[0]) if instruction.operands else 0
        values = self._consume(argc + 1, instruction.opcode)
        subject, args = values[0], values[1:]
        self._flush_conditionals()
        self._emit(
            Node("construct_super", [subject, *args], self._label(instruction.offset))
        )

    def _handle_new_object(self, instruction: Instruction) -> None:
        count = safe_int(instruction.operands[0]) if instruction.operands else 0
        values = self._consume(count * 2, instruction.opcode)
        self._produce(Node("new_object", values, self._label(instruction.offset)))

    def _handle_new_array(self, instruction: Instruction) -> None:
        count = safe_int(instruction.operands[0]) if instruction.operands else 0
        values = self._consume(count, instruction.opcode)
        self._produce(Node("new_array", values, self._label(instruction.offset)))

    def _handle_new_class(self, instruction: Instruction) -> None:
        (base,) = self._consume(1, instruction.opcode)
        class_index = safe_int(instruction.operands[0]) if instruction.operands else 0
        self._produce(
            Node("new_class", [base, class_index], self._label(instruction.offset))
        )

    def _finalize_complex_expressions(self, current_offset: int) -> None:
        self._finalize_complex_expr(
            self._ternary_targets,
            current_offset,
            self._CONDITIONAL_TYPES,
            wrap_to=("ternary_if", False),
        )
        self._finalize_complex_expr(
            self._shortjump_targets,
            current_offset,
            {"and", "or"},
            expected_depth=1,
        )

    def _finalize_complex_expr(
        self,
        targets: list[int],
        current_offset: int,
        valid_types: set[str] | frozenset[str],
        expected_depth: int | None = None,
        wrap_to: tuple[Any, ...] | None = None,
    ) -> None:
        while targets and targets[-1] == current_offset:
            if not self._extend_complex_expr(valid_types, expected_depth):
                if self.options.get("validate"):
                    raise ValueError("invalid complex expression state")
                targets.pop()
                continue

            if wrap_to:
                node_type, *prefix = wrap_to
                (expr,) = self._consume(1, Opcode.Nop)
                self._produce(
                    Node(str(node_type), [*prefix, expr], self._label(current_offset))
                )

            targets.pop()

    def _extend_complex_expr(
        self,
        valid_types: set[str] | frozenset[str],
        expected_depth: int | None = None,
    ) -> bool:
        if len(self._stack) < 2:
            return False
        expr, current = self._consume(2, Opcode.Nop)
        if expr.type not in valid_types:
            self._stack.extend([expr, current])
            return False
        if expected_depth is not None and len(expr.children) != expected_depth:
            self._stack.extend([expr, current])
            return False

        expr.children.append(current)
        self._produce(expr)
        return True

    def _flush_conditionals(self) -> None:
        queued: list[Node] = []
        while self._stack and self._stack[-1].type in self._CONDITIONAL_TYPES:
            (conditional,) = self._consume(1, Opcode.Nop)
            queued.insert(
                0,
                Node(
                    "jump_if",
                    [True, conditional.metadata.get("offset"), conditional],
                    self._label(int(conditional.metadata.get("label", 0))),
                ),
            )

        for node in queued:
            self._emit(node)

    def _emit_statement(self, node_type: str, children: list[Any], offset: int) -> None:
        self._flush_conditionals()
        self._emit(Node(node_type, children, self._label(offset)))

    def _handle_common_statement_opcode(self, instruction: Instruction) -> bool:
        opcode = instruction.opcode

        node_type = self._ZERO_ARG_STATEMENTS.get(opcode)
        if node_type is not None:
            self._emit_statement(node_type, [], instruction.offset)
            return True

        stack_stmt = self._STACK_STATEMENTS.get(opcode)
        if stack_stmt is not None:
            node_type, arity = stack_stmt
            values = self._consume(arity, opcode)
            self._emit_statement(node_type, values, instruction.offset)
            return True

        return False

    def _maybe_enter_shortcut(self, opcode: Opcode) -> None:
        if self._shortcut_armed and opcode in self._SHORTCUT_START:
            self._in_shortcut = True
            self._shortcut_armed = False
            self._collapse_shortcut_dup_copy()
            return

        if opcode != Opcode.Label:
            self._shortcut_armed = False

    def _collapse_shortcut_dup_copy(self) -> None:
        if len(self._stack) < 2:
            return

        if self._is_equivalent_ignoring_label(self._stack[-2], self._stack[-1]):
            self._stack.pop()

    def _handle_shortcut(self, insn_index: int, instruction: Instruction) -> bool:
        opcode = instruction.opcode
        if opcode in (Opcode.ConvertB, Opcode.CoerceB):
            return True

        if opcode == Opcode.IfTrue or opcode == Opcode.IfFalse:
            op_type = "or" if opcode == Opcode.IfTrue else "and"
            target = self._branch_target(insn_index, instruction)
            (lhs,) = self._consume(1, opcode)
            self._produce(Node(op_type, [lhs], self._label(instruction.offset)))
            self._shortjump_targets.append(target)
            return True

        if opcode == Opcode.Pop:
            self._in_shortcut = False
            return True

        if (
            opcode == Opcode.Jump
            and instruction.operands
            and safe_int(instruction.operands[0]) == 0
        ):
            return True

        if self.options.get("validate"):
            raise ValueError(f"invalid shortcut instruction: {opcode.name}")

        self._in_shortcut = False
        return False

    def _branch_target(self, insn_index: int, instruction: Instruction) -> int:
        if not instruction.operands:
            raise ValueError(f"{instruction.opcode.name} missing branch operand")
        relative = safe_int(instruction.operands[0])
        next_offset = self._next_offset(insn_index)
        return next_offset + relative

    def _next_offset(self, insn_index: int) -> int:
        if insn_index + 1 < len(self._instructions):
            return safe_int(self._instructions[insn_index + 1].offset)
        return safe_int(self._instructions[insn_index].offset)

    def _literal_node(self, instruction: Instruction) -> Node | None:
        opcode = instruction.opcode
        label = self._label(instruction.offset)

        if opcode in (Opcode.PushByte, Opcode.PushShort):
            value = safe_int(instruction.operands[0]) if instruction.operands else 0
            return Node("integer", [value], label)

        if opcode == Opcode.PushInt:
            value = safe_int(instruction.operands[0]) if instruction.operands else 0
            return Node("integer", [value], label)

        if opcode == Opcode.PushUint:
            uint_value = safe_int(instruction.operands[0]) if instruction.operands else 0
            return Node("unsigned", [uint_value], label)

        if opcode == Opcode.PushDouble:
            double_value = instruction.operands[0] if instruction.operands else 0.0
            return Node("double", [double_value], label)

        if opcode == Opcode.PushString:
            string_value = instruction.operands[0] if instruction.operands else ""
            return Node("string", [string_value], label)

        if opcode == Opcode.PushTrue:
            return Node.leaf("true", metadata=label)

        if opcode == Opcode.PushFalse:
            return Node.leaf("false", metadata=label)

        if opcode == Opcode.PushNaN:
            return Node.leaf("nan", metadata=label)

        if opcode == Opcode.PushNull:
            return Node.leaf("null", metadata=label)

        if opcode == Opcode.PushUndefined:
            return Node.leaf("undefined", metadata=label)

        return None

    def _local_index(self, instruction: Instruction) -> int:
        if instruction.opcode in (Opcode.GetLocal, Opcode.SetLocal):
            if not instruction.operands:
                raise ValueError(f"{instruction.opcode.name} missing local index")
            return safe_int(instruction.operands[0])

        if instruction.opcode in self._LOCAL_GET:
            return self._LOCAL_GET[instruction.opcode]
        if instruction.opcode in self._LOCAL_SET:
            return self._LOCAL_SET[instruction.opcode]

        raise ValueError(
            f"opcode does not represent local access: {instruction.opcode.name}"
        )

    def _consume(self, count: int, opcode: Opcode) -> list[Node]:
        if count == 0:
            return []
        if len(self._stack) < count:
            if self.options.get("tolerate_stack_underflow"):
                missing = count - len(self._stack)
                values = [self._synthetic_stack_value(opcode) for _ in range(missing)]
                values.extend(self._stack)
                self._stack.clear()
                return values
            raise ValueError(
                f"stack underflow for {opcode.name}: need {count}, have {len(self._stack)}"
            )

        values = self._stack[-count:]
        del self._stack[-count:]
        return values

    def _produce(self, node: Node) -> None:
        self._stack.append(node)

    def _emit(self, node: Node) -> None:
        if self._current_instruction is not None and "instruction" not in node.metadata:
            node.metadata["instruction"] = cast(Any, self._current_instruction)
        self._ast.children.append(node)

    def _label(self, offset: int) -> dict[str, Any]:
        metadata = {"label": int(offset)}
        if self._current_instruction is not None:
            metadata["instruction"] = cast(Any, self._current_instruction)
        return metadata

    @staticmethod
    def _synthetic_stack_value(opcode: Opcode) -> Node:
        return Node("stack_hole", [opcode.name], {"synthetic": 1})

    @staticmethod
    def _runtime_multiname_arity(name: Any) -> int:
        kind = getattr(name, "kind", None)
        if isinstance(kind, MultinameKind):
            if kind in (MultinameKind.RTQNAME, MultinameKind.RTQNAMEA):
                return 1
            if kind in (MultinameKind.MULTINAMEL, MultinameKind.MULTINAMELA):
                return 1
            if kind in (MultinameKind.RTQNAMEL, MultinameKind.RTQNAMELA):
                return 2
            return 0

        # MultinameL / RTQNameL-like operands require runtime name components.
        if isinstance(name, str):
            if name == "*":
                return 1
            if "::" in name and name.rsplit("::", 1)[1] == "*":
                return 1
            return 0

        if isinstance(name, dict):
            kind = str(name.get("kind", "")).upper()
            if kind in {"MULTINAMEL", "MULTINAMELA"}:
                return 1
            if kind in {"RTQNAMEL", "RTQNAMELA"}:
                return 2

        return 0

    @staticmethod
    def _initial_temp_local(body: Any, instructions: Sequence[Instruction]) -> int:
        max_seen = -1
        for instruction in instructions:
            opcode = instruction.opcode
            if opcode in ASTBuild._LOCAL_GET:
                max_seen = max(max_seen, ASTBuild._LOCAL_GET[opcode])
            elif opcode in ASTBuild._LOCAL_SET:
                max_seen = max(max_seen, ASTBuild._LOCAL_SET[opcode])
            elif opcode in (Opcode.GetLocal, Opcode.SetLocal) and instruction.operands:
                max_seen = max(max_seen, safe_int(instruction.operands[0]))
            elif opcode == Opcode.HasNext2:
                if instruction.operands:
                    max_seen = max(max_seen, safe_int(instruction.operands[0]))
                if len(instruction.operands) > 1:
                    max_seen = max(max_seen, safe_int(instruction.operands[1]))

        declared = 0
        for attr in ("num_locals", "local_count"):
            raw = getattr(body, attr, None)
            if isinstance(raw, int) and raw > declared:
                declared = raw

        if declared > 0:
            return max(declared, max_seen + 1)
        if max_seen >= 0:
            return max_seen + 1
        return 1

    def _alloc_temp_local(self) -> int:
        index = self._next_temp_local
        self._next_temp_local += 1
        return index

    @staticmethod
    def _is_dup_safe_expression(value: Node) -> bool:
        impure_types = {
            "call",
            "call_property",
            "call_property_lex",
            "call_property_void",
            "call_super",
            "call_super_void",
            "construct",
            "construct_property",
            "construct_super",
            "new_array",
            "new_object",
            "new_class",
            "new_function",
            "new_activation",
            "next_name",
            "next_value",
            "has_next",
            "has_next2",
            "get_property",
            "get_super",
            "get_slot",
        }

        stack: list[Node] = [value]
        while stack:
            current = stack.pop()
            if current.type in impure_types:
                return False
            for child in current.children:
                if isinstance(child, Node):
                    stack.append(child)
        return True

    @staticmethod
    def _clone_with_label(node: Node, offset: int) -> Node:
        clone = Node(node.type, list(node.children), dict(node.metadata))
        clone.ensure_metadata()["label"] = int(offset)
        return clone

    @staticmethod
    def _is_equivalent_ignoring_label(left: Node, right: Node) -> bool:
        if left is right:
            return True
        if left.type != right.type:
            return False

        left_meta = {k: v for k, v in left.metadata.items() if k != "label"}
        right_meta = {k: v for k, v in right.metadata.items() if k != "label"}
        if left_meta != right_meta:
            return False
        if len(left.children) != len(right.children):
            return False

        for left_child, right_child in zip(left.children, right.children):
            if isinstance(left_child, Node) and isinstance(right_child, Node):
                if not ASTBuild._is_equivalent_ignoring_label(left_child, right_child):
                    return False
            elif left_child != right_child:
                return False
        return True

    @staticmethod
    def _opcode_to_ast_type(opcode: Opcode) -> str:
        name = opcode.name
        if not name:
            return "unknown_opcode"

        result: list[str] = [name[0].lower()]
        for char in name[1:]:
            if char.isupper():
                result.append("_")
                result.append(char.lower())
            else:
                result.append(char)
        return "".join(result)
