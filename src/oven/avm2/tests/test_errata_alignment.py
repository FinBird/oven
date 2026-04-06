"""
AVM2 overview and Tamarin errata alignment tests.
"""

import pytest

from oven.avm2 import ABCReader, ConstantPool
from oven.avm2.constant_pool import Multiname
from oven.avm2.exceptions import InvalidABCCodeError
from oven.avm2.methods import MethodFlags
from oven.avm2.enums import Index, MultinameKind


def test_constant_pool_count_minus_one_layout() -> None:
    data = bytes([1, 1, 1, 1, 1, 1, 1])
    pool = ABCReader(data).read_constant_pool()
    assert pool.ints == []
    assert pool.uints == []
    assert pool.doubles == []
    assert pool.strings == []
    assert pool.namespaces == []
    assert pool.namespace_sets == []
    assert pool.multinames == []


def test_method_optional_uses_param_count_constraint() -> None:
    pool = ConstantPool([], [], [], [""], [], [], [])
    data = bytes([1, 0, 0, 0, MethodFlags.HAS_OPTIONAL.value, 2])
    reader = ABCReader(data)
    with pytest.raises(InvalidABCCodeError):
        reader.read_method(pool)


def test_metadata_info_keys_values_separate_arrays() -> None:
    pool = ConstantPool([], [], [], ["Meta", "k1", "v1", "v2"], [], [], [])
    data = bytes([1, 2, 2, 0, 3, 4])
    reader = ABCReader(data)
    md = reader.read_metadata_item(pool)
    assert md.name == "Meta"
    assert md.items[0].key == "k1"
    assert md.items[0].value == "v1"
    assert md.items[1].key is None
    assert md.items[1].value == "v2"


def test_exception_info_uses_multiname_indices() -> None:
    pool = ConstantPool(
        ints=[],
        uints=[],
        doubles=[],
        strings=["STRING_ONE", "MULTINAME_ONE"],
        namespaces=[],
        namespace_sets=[],
        multinames=[
            Multiname(MultinameKind.QNAME, {"namespace": None, "name": Index(2)})
        ],
    )
    data = bytes([0, 1, 1, 0, 1, 1, 71, 1, 0, 0, 0, 1, 1, 0])
    body = ABCReader(data).read_method_body(pool)
    assert len(body.exceptions) == 1
    exc = body.exceptions[0]
    assert exc.exc_type == "MULTINAME_ONE"
    assert exc.var_name == "MULTINAME_ONE"
