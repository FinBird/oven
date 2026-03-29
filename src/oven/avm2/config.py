from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ParseMode(str, Enum):
    FAST = "fast"
    RELAXED = "relaxed"
    STRICT = "strict"


class VerifyProfile(str, Enum):
    STRICT = "strict"
    STACK_ONLY = "stack_only"
    BRANCH_ONLY = "branch_only"
    RELAXED_FULL = "relaxed_full"
    STRICT_RELAXED_JOINS = "strict_relaxed_joins"
    STRICT_PRECISE_JOINS = "strict_precise_joins"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class VerifyConfig:
    strict_metadata_indices: bool
    verify_stack_semantics: bool
    verify_branch_targets: bool
    verify_relaxed: bool
    strict_lookupswitch: bool
    relax_join_depth: bool
    relax_join_types: bool
    prefer_precise_any_join: bool

    @classmethod
    def from_parse_mode(cls, mode: ParseMode) -> "VerifyConfig":
        if mode == ParseMode.FAST:
            return cls(
                strict_metadata_indices=False,
                verify_stack_semantics=False,
                verify_branch_targets=False,
                verify_relaxed=False,
                strict_lookupswitch=False,
                relax_join_depth=False,
                relax_join_types=False,
                prefer_precise_any_join=False,
            )
        if mode == ParseMode.STRICT:
            return cls(
                strict_metadata_indices=True,
                verify_stack_semantics=True,
                verify_branch_targets=True,
                verify_relaxed=False,
                strict_lookupswitch=True,
                relax_join_depth=False,
                relax_join_types=False,
                prefer_precise_any_join=False,
            )
        # RELAXED (default)
        return cls(
            strict_metadata_indices=False,
            verify_stack_semantics=True,
            verify_branch_targets=True,
            verify_relaxed=True,
            strict_lookupswitch=False,
            relax_join_depth=True,
            relax_join_types=True,
            prefer_precise_any_join=False,
        )

    @classmethod
    def from_verify_profile(cls, profile: VerifyProfile) -> "VerifyConfig":
        if profile == VerifyProfile.NONE:
            return cls(
                strict_metadata_indices=False,
                verify_stack_semantics=False,
                verify_branch_targets=False,
                verify_relaxed=False,
                strict_lookupswitch=False,
                relax_join_depth=False,
                relax_join_types=False,
                prefer_precise_any_join=False,
            )
        if profile == VerifyProfile.RELAXED_FULL:
            return cls(
                strict_metadata_indices=False,
                verify_stack_semantics=True,
                verify_branch_targets=True,
                verify_relaxed=True,
                strict_lookupswitch=False,
                relax_join_depth=True,
                relax_join_types=True,
                prefer_precise_any_join=False,
            )
        if profile == VerifyProfile.STACK_ONLY:
            return cls(
                strict_metadata_indices=False,
                verify_stack_semantics=True,
                verify_branch_targets=False,
                verify_relaxed=True,
                strict_lookupswitch=False,
                relax_join_depth=True,
                relax_join_types=True,
                prefer_precise_any_join=False,
            )
        if profile == VerifyProfile.BRANCH_ONLY:
            return cls(
                strict_metadata_indices=False,
                verify_stack_semantics=False,
                verify_branch_targets=True,
                verify_relaxed=False,
                strict_lookupswitch=True,
                relax_join_depth=False,
                relax_join_types=False,
                prefer_precise_any_join=False,
            )
        if profile == VerifyProfile.STRICT_RELAXED_JOINS:
            return cls(
                strict_metadata_indices=True,
                verify_stack_semantics=True,
                verify_branch_targets=True,
                verify_relaxed=False,
                strict_lookupswitch=True,
                relax_join_depth=True,
                relax_join_types=True,
                prefer_precise_any_join=False,
            )
        if profile == VerifyProfile.STRICT_PRECISE_JOINS:
            return cls(
                strict_metadata_indices=True,
                verify_stack_semantics=True,
                verify_branch_targets=True,
                verify_relaxed=False,
                strict_lookupswitch=True,
                relax_join_depth=False,
                relax_join_types=False,
                prefer_precise_any_join=True,
            )
        # STRICT
        return cls(
            strict_metadata_indices=True,
            verify_stack_semantics=True,
            verify_branch_targets=True,
            verify_relaxed=False,
            strict_lookupswitch=True,
            relax_join_depth=False,
            relax_join_types=False,
            prefer_precise_any_join=False,
        )
