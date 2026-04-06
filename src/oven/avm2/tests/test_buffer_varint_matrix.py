from __future__ import annotations

from oven.avm2.buffer import Buffer


def _add_when_between(values: list[int], number: int, minimum: int, maximum: int) -> None:
    if minimum <= number <= maximum:
        values.append(number)


def _boundary_numbers(minimum: int, maximum: int) -> list[int]:
    values: list[int] = []
    _add_when_between(values, 1531, minimum, maximum)
    x = 1
    for _ in range(32):
        x <<= 1
        _add_when_between(values, x - 1, minimum, maximum)
        _add_when_between(values, x, minimum, maximum)
        _add_when_between(values, x + 1, minimum, maximum)
        _add_when_between(values, -(x - 1), minimum, maximum)
        _add_when_between(values, -x, minimum, maximum)
        _add_when_between(values, -(x + 1), minimum, maximum)
    deduped = dict.fromkeys(values)
    return list(deduped)


def _encode_u32(value: int) -> bytes:
    if value < 0 or value > 4294967295:
        raise ValueError(f"u32 out of range: {value}")
    out = bytearray()
    n = value
    while True:
        byte = n & 127
        n >>= 7
        if n:
            out.append(byte | 128)
        else:
            out.append(byte)
            return bytes(out)


def _encode_s32(value: int) -> bytes:
    if value < -(1 << 31) or value > (1 << 31) - 1:
        raise ValueError(f"s32 out of range: {value}")
    return _encode_u32(value & 4294967295)


def test_vuint30_boundary_matrix_roundtrip() -> None:
    for number in _boundary_numbers(0, (1 << 30) - 1):
        encoded = _encode_u32(number)
        decoded = Buffer(encoded).read_vuint30()
        assert decoded == number
        assert Buffer(encoded).read_vuint32() == number


def test_vuint32_boundary_matrix_roundtrip() -> None:
    for number in _boundary_numbers(0, (1 << 32) - 1):
        encoded = _encode_u32(number)
        buf = Buffer(encoded)
        assert buf.read_vuint32() == number
        assert buf.eof() is True


def test_vint32_boundary_matrix_roundtrip() -> None:
    for number in _boundary_numbers(-(1 << 31), (1 << 31) - 1):
        encoded = _encode_s32(number)
        buf = Buffer(encoded)
        assert buf.read_vint32() == number
        assert buf.eof() is True