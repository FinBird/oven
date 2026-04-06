from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING, Literal, NamedTuple, Optional, TypeAlias

from .enums import EdgeKind
from .exceptions import InvalidABCCodeError
from .methods import MethodBody

if TYPE_CHECKING:
    from .abc.reader import ABCReader


class _StackValidationTables(NamedTuple):
    offset_to_index: dict[int, int]
    instruction_offsets: set[int]
    stack_effect_by_index: list[tuple[int, int]]
    local_indices_by_index: list[tuple[int, ...]]
    scope_indices_by_index: list[tuple[int, ...]]
    successors_by_index: list[list[tuple[int, EdgeKind]]]


class MethodBodyStackVerifier:
    """Stack-semantics verifier extracted from ABCReader."""

    def __init__(self, reader: "ABCReader") -> None:
        self._reader = reader

    def validate_method_body_stack(self, method_index: int, body: MethodBody) -> None:
        reader = self._reader
        instructions = body.instructions
        if not instructions:
            return

        tables = self._build_stack_validation_tables(body)
        offset_to_index = tables.offset_to_index
        stack_effect_by_index = tables.stack_effect_by_index
        local_indices_by_index = tables.local_indices_by_index
        scope_indices_by_index = tables.scope_indices_by_index
        successors_by_index = tables.successors_by_index

        instruction_count = len(instructions)
        instruction_offsets_list = [inst.offset for inst in instructions]
        stack_state_by_index: list[tuple[str, ...] | None] = [None] * instruction_count
        local_state_by_index: list[tuple[str, ...] | None] = [None] * instruction_count
        scope_state_by_index: list[tuple[str, ...] | None] = [None] * instruction_count
        worklist: deque[int] = deque()
        queued_indices: list[bool] = [False] * instruction_count
        initial_local_state = tuple(
            reader._STACK_TYPE_ANY for _ in range(body.num_locals)
        )
        # Initial scope entries represent pre-existing activation/global objects.
        initial_scope_state = tuple(
            reader._STACK_TYPE_OBJECT for _ in range(body.init_scope_depth)
        )

        merge_stack_state = self._merge_stack_state_indexed
        merge_local_state = self._merge_local_state_indexed
        merge_scope_state = self._merge_scope_state_indexed
        stack_state_after_instruction = reader._stack_state_after_instruction
        local_state_after_instruction = reader._local_state_after_instruction
        scope_state_after_instruction = reader._scope_state_after_instruction
        local_state_mutation_opcodes = reader._LOCAL_STATE_MUTATION_OPCODES
        scope_state_mutation_opcodes = reader._SCOPE_STATE_MUTATION_OPCODES
        verify_relaxed = reader._verify_relaxed
        validate_operand_indices = not verify_relaxed
        enforce_max_stack = not verify_relaxed
        body_num_locals = body.num_locals
        body_max_stack = body.max_stack
        edge_kind_entry = reader._EDGE_KIND_ENTRY
        edge_kind_exception_entry = reader._EDGE_KIND_EXCEPTION_ENTRY
        exception_entry_stack_state = reader._EXCEPTION_HANDLER_ENTRY_STACK_STATE

        merge_stack_state(
            stack_state_by_index=stack_state_by_index,
            worklist=worklist,
            queued_indices=queued_indices,
            method_index=method_index,
            target_index=0,
            join_offset=instruction_offsets_list[0],
            incoming_state=(),
            edge_kind=edge_kind_entry,
        )
        merge_local_state(
            local_state_by_index=local_state_by_index,
            worklist=worklist,
            queued_indices=queued_indices,
            method_index=method_index,
            target_index=0,
            join_offset=instruction_offsets_list[0],
            incoming_state=initial_local_state,
        )
        merge_scope_state(
            scope_state_by_index=scope_state_by_index,
            worklist=worklist,
            queued_indices=queued_indices,
            method_index=method_index,
            target_index=0,
            join_offset=instruction_offsets_list[0],
            incoming_state=initial_scope_state,
            edge_kind=edge_kind_entry,
        )

        # AVM2 exception handler entry starts with thrown value on operand stack.
        for exc in body.exceptions:
            target_index = offset_to_index.get(exc.target_offset)
            if target_index is None:
                raise InvalidABCCodeError(
                    f"Invalid exception target offset: {exc.target_offset}"
                )
            join_offset = instruction_offsets_list[target_index]
            merge_stack_state(
                stack_state_by_index=stack_state_by_index,
                worklist=worklist,
                queued_indices=queued_indices,
                method_index=method_index,
                target_index=target_index,
                join_offset=join_offset,
                incoming_state=exception_entry_stack_state,
                edge_kind=edge_kind_exception_entry,
            )
            merge_local_state(
                local_state_by_index=local_state_by_index,
                worklist=worklist,
                queued_indices=queued_indices,
                method_index=method_index,
                target_index=target_index,
                join_offset=join_offset,
                incoming_state=initial_local_state,
            )
            merge_scope_state(
                scope_state_by_index=scope_state_by_index,
                worklist=worklist,
                queued_indices=queued_indices,
                method_index=method_index,
                target_index=target_index,
                join_offset=join_offset,
                incoming_state=initial_scope_state,
                edge_kind=edge_kind_exception_entry,
            )

        while worklist:
            idx = worklist.popleft()
            queued_indices[idx] = False
            stack_in = stack_state_by_index[idx]
            local_in = local_state_by_index[idx]
            scope_in = scope_state_by_index[idx]
            if stack_in is None or local_in is None or scope_in is None:
                continue

            depth_in = len(stack_in)
            instruction = instructions[idx]
            opcode = instruction.opcode
            local_indices = local_indices_by_index[idx]
            scope_indices = scope_indices_by_index[idx]

            if validate_operand_indices and local_indices:
                for local_index in local_indices:
                    if local_index < 0 or local_index >= body_num_locals:
                        raise InvalidABCCodeError(
                            "local register index out of range: "
                            f"method={method_index}, offset={instruction.offset}, opcode={instruction.opcode.name}, "
                            f"index={local_index}, num_locals={body_num_locals}"
                        )

            if validate_operand_indices and scope_indices:
                scope_depth = len(scope_in)
                for scope_index in scope_indices:
                    if scope_index < 0 or scope_index >= scope_depth:
                        raise InvalidABCCodeError(
                            "scope object index out of range: "
                            f"method={method_index}, offset={instruction.offset}, opcode={instruction.opcode.name}, "
                            f"index={scope_index}, scope_depth={scope_depth}"
                        )

            pops, pushes = stack_effect_by_index[idx]
            effective_pops = pops
            if depth_in < pops:
                if verify_relaxed:
                    effective_pops = depth_in
                else:
                    raise InvalidABCCodeError(
                        "stack underflow: "
                        f"method={method_index}, offset={instruction.offset}, opcode={instruction.opcode.name}, "
                        f"required={pops}, actual={depth_in}"
                    )

            depth_out = depth_in - effective_pops + pushes
            if enforce_max_stack and depth_out > body_max_stack:
                raise InvalidABCCodeError(
                    "max_stack exceeded: "
                    f"method={method_index}, offset={instruction.offset}, "
                    f"depth={depth_out}, max_stack={body_max_stack}"
                )

            successors = successors_by_index[idx]
            if not successors:
                continue

            if pushes == 0:
                stack_out = stack_in[:-effective_pops] if effective_pops else stack_in
            else:
                stack_out = stack_state_after_instruction(
                    instruction=instruction,
                    stack_in=stack_in,
                    pops=effective_pops,
                    pushes=pushes,
                    local_state=local_in,
                    scope_state=scope_in,
                    local_indices=local_indices,
                )

            if opcode in local_state_mutation_opcodes:
                local_out = local_state_after_instruction(
                    instruction=instruction,
                    stack_in=stack_in,
                    local_state=local_in,
                    local_indices=local_indices,
                )
            else:
                local_out = local_in

            if opcode in scope_state_mutation_opcodes:
                scope_out = scope_state_after_instruction(
                    method_index=method_index,
                    body=body,
                    instruction=instruction,
                    stack_in=stack_in,
                    scope_state=scope_in,
                )
            else:
                scope_out = scope_in

            for successor_index, edge_kind in successors:
                join_offset = instruction_offsets_list[successor_index]
                merge_stack_state(
                    stack_state_by_index=stack_state_by_index,
                    worklist=worklist,
                    queued_indices=queued_indices,
                    method_index=method_index,
                    target_index=successor_index,
                    join_offset=join_offset,
                    incoming_state=stack_out,
                    edge_kind=edge_kind,
                )
                merge_local_state(
                    local_state_by_index=local_state_by_index,
                    worklist=worklist,
                    queued_indices=queued_indices,
                    method_index=method_index,
                    target_index=successor_index,
                    join_offset=join_offset,
                    incoming_state=local_out,
                )
                merge_scope_state(
                    scope_state_by_index=scope_state_by_index,
                    worklist=worklist,
                    queued_indices=queued_indices,
                    method_index=method_index,
                    target_index=successor_index,
                    join_offset=join_offset,
                    incoming_state=scope_out,
                    edge_kind=edge_kind,
                )

    def _build_stack_validation_tables(
        self,
        body: MethodBody,
    ) -> _StackValidationTables:
        reader = self._reader
        instructions = body.instructions
        instruction_count = len(instructions)
        instruction_offsets_list = [inst.offset for inst in instructions]
        offset_to_index = {
            offset: idx for idx, offset in enumerate(instruction_offsets_list)
        }
        instruction_offsets = set(offset_to_index)
        stack_effect_by_index: list[tuple[int, int]] = [(0, 0)] * instruction_count
        local_indices_by_index: list[tuple[int, ...]] = [()] * instruction_count
        scope_indices_by_index: list[tuple[int, ...]] = [()] * instruction_count
        successors_by_index: list[list[tuple[int, EdgeKind]]] = [
            [] for _ in range(instruction_count)
        ]

        stack_effect_for_instruction = reader._stack_effect_for_instruction
        local_indices_for_instruction = reader._local_indices_for_instruction
        scope_indices_for_instruction = reader._scope_indices_for_instruction
        instruction_successor_offsets = reader._instruction_successor_offsets
        local_index_candidate_opcodes = reader._LOCAL_INDEX_CANDIDATE_OPCODES
        scope_index_candidate_opcodes = reader._SCOPE_INDEX_CANDIDATE_OPCODES
        code_length = len(body.code)
        next_offsets: list[Optional[int]] = list(instruction_offsets_list[1:])
        next_offsets.append(None)
        offset_to_index_get = offset_to_index.get

        for idx, inst in enumerate(instructions):
            opcode = inst.opcode
            stack_effect_by_index[idx] = stack_effect_for_instruction(inst)
            if opcode in local_index_candidate_opcodes:
                local_indices_by_index[idx] = local_indices_for_instruction(inst)
            if opcode in scope_index_candidate_opcodes:
                scope_indices_by_index[idx] = scope_indices_for_instruction(inst)
            successor_offsets = instruction_successor_offsets(
                instruction=inst,
                next_offset=next_offsets[idx],
                instruction_offsets=instruction_offsets,
                code_length=code_length,
            )
            if not successor_offsets:
                continue

            append_successor = successors_by_index[idx].append
            for successor_offset, edge_kind in successor_offsets:
                successor_index = offset_to_index_get(successor_offset)
                if successor_index is not None:
                    append_successor((successor_index, edge_kind))

        return _StackValidationTables(
            offset_to_index=offset_to_index,
            instruction_offsets=instruction_offsets,
            stack_effect_by_index=stack_effect_by_index,
            local_indices_by_index=local_indices_by_index,
            scope_indices_by_index=scope_indices_by_index,
            successors_by_index=successors_by_index,
        )

    def _merge_stack_state_indexed(
        self,
        *,
        stack_state_by_index: list[Optional[tuple[str, ...]]],
        worklist: deque[int],
        queued_indices: list[bool],
        method_index: int,
        target_index: int,
        join_offset: int,
        incoming_state: tuple[str, ...],
        edge_kind: EdgeKind,
    ) -> None:
        reader = self._reader
        worklist_append = worklist.append
        queued = queued_indices
        target = target_index
        existing_state = stack_state_by_index[target]
        if existing_state is None:
            stack_state_by_index[target] = incoming_state
            if not queued[target]:
                queued[target] = True
                worklist_append(target)
            return
        if existing_state == incoming_state:
            return

        if len(existing_state) != len(incoming_state):
            if reader._relax_join_depth:
                existing_state, incoming_state = reader._normalize_relaxed_join_states(
                    existing_state=existing_state,
                    incoming_state=incoming_state,
                    edge_kind=edge_kind,
                )
            else:
                raise InvalidABCCodeError(
                    "stack depth mismatch: "
                    f"method={method_index}, join_offset={join_offset}, "
                    f"existing={len(existing_state)}, incoming={len(incoming_state)}"
                )
            if existing_state == incoming_state:
                return

        merged_slots: Optional[list[str]] = None
        merge_lattice_slot_type = reader._merge_lattice_slot_type
        state_length = len(existing_state)
        for slot in range(state_length):
            existing_type = existing_state[slot]
            incoming_type = incoming_state[slot]
            if existing_type == incoming_type:
                continue
            merged_type = merge_lattice_slot_type(existing_type, incoming_type)
            if merged_type is None:
                raise InvalidABCCodeError(
                    (
                        "stack type mismatch: "
                        f"method={method_index}, join_offset={join_offset}, slot={slot}, "
                        f"existing={existing_type}, incoming={incoming_type}"
                    )
                )
            if merged_type == existing_type:
                continue
            if merged_slots is None:
                merged_slots = list(existing_state)
            merged_slots[slot] = merged_type

        if merged_slots is not None:
            stack_state_by_index[target] = tuple(merged_slots)
            if not queued[target]:
                queued[target] = True
                worklist_append(target)

    def _merge_local_state_indexed(
        self,
        *,
        local_state_by_index: list[Optional[tuple[str, ...]]],
        worklist: deque[int],
        queued_indices: list[bool],
        method_index: int,
        target_index: int,
        join_offset: int,
        incoming_state: tuple[str, ...],
    ) -> None:
        reader = self._reader
        worklist_append = worklist.append
        queued = queued_indices
        target = target_index
        existing_state = local_state_by_index[target]
        if existing_state is None:
            local_state_by_index[target] = incoming_state
            if not queued[target]:
                queued[target] = True
                worklist_append(target)
            return
        if existing_state == incoming_state:
            return

        if len(existing_state) != len(incoming_state):
            raise InvalidABCCodeError(
                "local state length mismatch: "
                f"method={method_index}, join_offset={join_offset}, "
                f"existing={len(existing_state)}, incoming={len(incoming_state)}"
            )

        merged_slots: Optional[list[str]] = None
        merge_lattice_slot_type = reader._merge_lattice_slot_type
        state_length = len(existing_state)
        for local_index in range(state_length):
            existing_type = existing_state[local_index]
            incoming_type = incoming_state[local_index]
            if existing_type == incoming_type:
                continue
            merged_type = merge_lattice_slot_type(existing_type, incoming_type)
            if merged_type is None:
                raise InvalidABCCodeError(
                    (
                        "local type mismatch: "
                        f"method={method_index}, join_offset={join_offset}, local={local_index}, "
                        f"existing={existing_type}, incoming={incoming_type}"
                    )
                )
            if merged_type == existing_type:
                continue
            if merged_slots is None:
                merged_slots = list(existing_state)
            merged_slots[local_index] = merged_type

        if merged_slots is not None:
            local_state_by_index[target] = tuple(merged_slots)
            if not queued[target]:
                queued[target] = True
                worklist_append(target)

    def _merge_scope_state_indexed(
        self,
        *,
        scope_state_by_index: list[Optional[tuple[str, ...]]],
        worklist: deque[int],
        queued_indices: list[bool],
        method_index: int,
        target_index: int,
        join_offset: int,
        incoming_state: tuple[str, ...],
        edge_kind: EdgeKind,
    ) -> None:
        reader = self._reader
        worklist_append = worklist.append
        queued = queued_indices
        target = target_index
        existing_state = scope_state_by_index[target]
        if existing_state is None:
            scope_state_by_index[target] = incoming_state
            if not queued[target]:
                queued[target] = True
                worklist_append(target)
            return
        if existing_state == incoming_state:
            return

        if len(existing_state) != len(incoming_state):
            if reader._relax_join_depth:
                target_depth = min(len(existing_state), len(incoming_state))
                existing_state = existing_state[:target_depth]
                incoming_state = incoming_state[:target_depth]
            else:
                raise InvalidABCCodeError(
                    "scope depth mismatch: "
                    f"method={method_index}, join_offset={join_offset}, "
                    f"existing={len(existing_state)}, incoming={len(incoming_state)}"
                )
            if existing_state == incoming_state:
                return

        merged_slots: Optional[list[str]] = None
        merge_lattice_slot_type = reader._merge_lattice_slot_type
        state_length = len(existing_state)
        for slot in range(state_length):
            existing_type = existing_state[slot]
            incoming_type = incoming_state[slot]
            if existing_type == incoming_type:
                continue
            merged_type = merge_lattice_slot_type(existing_type, incoming_type)
            if merged_type is None:
                raise InvalidABCCodeError(
                    (
                        "scope type mismatch: "
                        f"method={method_index}, join_offset={join_offset}, slot={slot}, "
                        f"existing={existing_type}, incoming={incoming_type}"
                    )
                )
            if merged_type == existing_type:
                continue
            if merged_slots is None:
                merged_slots = list(existing_state)
            merged_slots[slot] = merged_type

        if merged_slots is not None:
            scope_state_by_index[target] = tuple(merged_slots)
            if not queued[target]:
                queued[target] = True
                worklist_append(target)
