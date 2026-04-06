from __future__ import annotations
import sys
from pathlib import Path
from typing import Callable
import pytest
from oven.avm2.enums import Opcode

PROJECT_ROOT = Path(__file__).resolve().parents[3]
project_root_str = str(PROJECT_ROOT)
if project_root_str not in sys.path:
    sys.path.insert(0, project_root_str)


@pytest.fixture(scope="session")
def fixture_dir() -> Path:
    return PROJECT_ROOT / "fixtures" / "abc"


@pytest.fixture
def fixture_bytes(fixture_dir: Path) -> Callable[[str], bytes]:
    def _load(name: str) -> bytes:
        return (fixture_dir / name).read_bytes()

    return _load


@pytest.fixture
def i24() -> Callable[[int], bytes]:
    def _encode(value: int) -> bytes:
        if value < 0:
            value = (1 << 24) + value
        return value.to_bytes(3, "little")

    return _encode


@pytest.fixture
def build_single_method_abc() -> Callable[[bytes, int, int], bytes]:
    def _build(bytecode: bytes, max_stack: int = 1, num_locals: int = 0) -> bytes:
        blob = bytearray()
        blob.extend((16).to_bytes(2, "little"))
        blob.extend((46).to_bytes(2, "little"))
        blob.extend([1, 1, 1, 1, 1, 1, 1])
        blob.append(1)
        blob.append(0)
        blob.append(0)
        blob.append(0)
        blob.append(0)
        blob.append(0)
        blob.append(0)
        blob.append(0)
        blob.append(1)
        blob.append(0)
        blob.append(max_stack)
        blob.append(num_locals)
        blob.append(0)
        blob.append(1)
        blob.append(len(bytecode))
        blob.extend(bytecode)
        blob.append(0)
        blob.append(0)
        return bytes(blob)

    return _build


@pytest.fixture
def build_invalid_lookupswitch_abc(
    i24: Callable[[int], bytes],
    build_single_method_abc: Callable[[bytes, int, int], bytes],
) -> Callable[[], bytes]:
    def _build() -> bytes:
        bytecode = bytes(
            [
                Opcode.PushByte.value,
                0,
                Opcode.LookupSwitch.value,
                *i24(100),
                0,
                *i24(6),
                Opcode.Nop.value,
                Opcode.Nop.value,
                Opcode.Nop.value,
                Opcode.Nop.value,
                Opcode.Nop.value,
                Opcode.Nop.value,
                Opcode.ReturnVoid.value,
            ]
        )
        return build_single_method_abc(bytecode, 1, 0)

    return _build
