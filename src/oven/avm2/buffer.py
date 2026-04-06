from __future__ import annotations


class BufferError(Exception):
    """Binary buffer read error."""


class Buffer:
    """Small binary reader tailored for AVM2 ABC parsing."""

    __slots__ = ("_data", "offset")

    def __init__(self, data: bytes):
        self._data = memoryview(data)
        self.offset = 0

    @property
    def data(self) -> bytes:
        return self._data.tobytes()

    def eof(self) -> bool:
        return self.offset >= len(self._data)

    def _require(self, size: int) -> None:
        if size < 0:
            raise BufferError(f"Negative read size: {size}")
        if self.offset + size > len(self._data):
            raise BufferError(
                f"Read out of range: need {size} bytes at {self.offset}, "
                f"available {len(self._data) - self.offset}"
            )

    def read_u8(self) -> int:
        self._require(1)
        value = self._data[self.offset]
        self.offset += 1
        return int(value)

    def read_u16(self) -> int:
        self._require(2)
        start = self.offset
        self.offset += 2
        return int.from_bytes(self._data[start : start + 2], "little", signed=False)

    def read_s24(self) -> int:
        self._require(3)
        b0, b1, b2 = self._data[self.offset : self.offset + 3]
        self.offset += 3
        value = b0 | (b1 << 8) | (b2 << 16)
        if value & 0x800000:
            value -= 0x1000000
        return int(value)

    def read_double(self) -> float:
        # Keep struct-based IEEE-754 decode path; int.from_bytes is not a drop-in
        # replacement for floating point binary decoding.
        import struct

        self._require(8)
        value = struct.unpack("<d", self._data[self.offset : self.offset + 8])[0]
        self.offset += 8
        return float(value)

    def read_bytes(self, length: int) -> bytes:
        self._require(length)
        start = self.offset
        self.offset += length
        return self._data[start : start + length].tobytes()

    def read_vuint32(self) -> int:
        value = 0
        shift = 0
        for idx in range(5):
            byte = self.read_u8()
            value |= (byte & 0x7F) << shift
            if (byte & 0x80) == 0:
                if value < 0:
                    raise BufferError("Invalid u32 value")
                return value
            shift += 7
            if idx == 4:
                raise ValueError("Invalid u30/u32 encoding: malformed 5-byte sequence.")
        raise ValueError("Invalid u30/u32 encoding")

    def read_vuint30(self) -> int:
        value = self.read_vuint32()
        if value > 0x3FFFFFFF:
            raise ValueError(f"u30 out of range: {value}")
        return value

    def read_vint32(self) -> int:
        value = self.read_vuint32()
        if value & 0x80000000:
            value -= 0x100000000
        return value

    def read_string(self) -> str:
        length = self.read_vuint30()
        raw = self.read_bytes(length)
        return raw.decode("utf-8")
