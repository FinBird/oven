from __future__ import annotations
import pytest
from oven.avm2 import parse, parse_abc
from oven.avm2.config import ParseMode, VerifyProfile
from oven.avm2.exceptions import InvalidABCCodeError
from oven.avm2.tests.abc_testkit import (
    ABCFixture,
    abc_fixtures,
    deterministic_mutations,
)

_FIXTURES = abc_fixtures()


@pytest.mark.slow
@pytest.mark.skipif(not _FIXTURES, reason="No ABC fixtures available")
@pytest.mark.parametrize("fixture", _FIXTURES, ids=lambda f: f.name)
def test_fuzz_mutations_raise_only_controlled_parser_errors(
    fixture: ABCFixture,
) -> None:
    data = fixture.read_bytes()
    mutations = deterministic_mutations(data, seed=42405, count=16)
    for mutated in mutations:
        try:
            parse_abc(mutated, verify_stack=False)
        except InvalidABCCodeError:
            continue


@pytest.mark.slow
@pytest.mark.skipif(not _FIXTURES, reason="No ABC fixtures available")
@pytest.mark.parametrize("fixture", _FIXTURES, ids=lambda f: f.name)
def test_fuzz_profile_matrix_does_not_escape_unexpected_exceptions(
    fixture: ABCFixture,
) -> None:
    data = fixture.read_bytes()
    mutations = deterministic_mutations(data, seed=23130, count=16)
    for mutated in mutations:
        try:
            parse(mutated, mode=ParseMode.RELAXED)
        except InvalidABCCodeError:
            pass
        try:
            parse(mutated, profile=VerifyProfile.STRICT)
        except InvalidABCCodeError:
            pass


@pytest.mark.slow
@pytest.mark.skipif(not _FIXTURES, reason="No ABC fixtures available")
@pytest.mark.parametrize("fixture", _FIXTURES, ids=lambda f: f.name)
def test_fuzz_truncation_prefixes_fail_cleanly(fixture: ABCFixture) -> None:
    data = fixture.read_bytes()
    cuts = sorted({0, 1, 2, 3, 4, 5, 8, len(data) // 4, len(data) // 2, len(data) - 1})
    for cut in cuts:
        if cut <= 0 or cut >= len(data):
            continue
        with pytest.raises(InvalidABCCodeError):
            parse_abc(data[:cut], verify_stack=False)
