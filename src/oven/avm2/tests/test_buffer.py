"""
Buffer unit tests for low-level ABC binary reads.
"""

import pytest
from oven.avm2.buffer import Buffer, BufferError


def test_primitives() -> None:
    data = bytes([127, 52, 18, 254, 255, 255])
    buf = Buffer(data)
    assert buf.read_u8() == 127
    assert buf.read_u16() == 4660
    assert buf.read_s24() == -2
    assert buf.eof() is True


def test_vuint_and_vint() -> None:
    buf_u = Buffer(bytes([172, 2]))
    assert buf_u.read_vuint32() == 300
    buf_s = Buffer(bytes([246, 255, 255, 255, 15]))
    assert buf_s.read_vint32() == -10


def test_string_utf8() -> None:
    payload = "ÄãºÃÊÀ½ç".encode("utf-8")
    buf = Buffer(bytes([len(payload)]) + payload)
    assert buf.read_string() == "ÄãºÃÊÀ½ç"
    assert buf.eof() is True


def test_malformed_vuint32() -> None:
    buf = Buffer(bytes([129, 129, 129, 129, 129]))
    with pytest.raises(ValueError):
        buf.read_vuint32()


def test_underflow() -> None:
    buf = Buffer(bytes([1]))
    buf.read_u8()
    with pytest.raises(BufferError):
        buf.read_u8()
