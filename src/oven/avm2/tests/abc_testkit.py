from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import random


@dataclass(frozen=True, slots=True)
class ABCFixture:
    name: str
    path: Path

    def read_bytes(self) -> bytes:
        return self.path.read_bytes()


def fixture_dir() -> Path:
    return Path(__file__).resolve().parents[4] / "fixtures" / "abc"


def abc_fixtures() -> list[ABCFixture]:
    base = fixture_dir()
    names = ["Test.abc", "Avm2Dummy.abc", "abcdump.abc", "builtin.abc"]
    fixtures: list[ABCFixture] = []
    for name in names:
        path = base / name
        if path.exists():
            fixtures.append(ABCFixture(name=name, path=path))
    return fixtures


def deterministic_mutations(
    data: bytes, *, seed: int, count: int, max_edits: int = 4, max_size: int = 2048
) -> list[bytes]:
    """
    Generate deterministic byte-level mutations.
    The strategy intentionally mixes bit flips, insertions, deletions, and
    truncations to hit parser boundary behavior while keeping payload size
    bounded for test speed.
    """
    rnd = random.Random(seed)
    mutations: list[bytes] = []
    base = bytes(data[:max_size])
    for _ in range(count):
        blob = bytearray(base)
        edit_count = rnd.randint(1, max_edits)
        for _ in range(edit_count):
            op = rnd.choice(("flip", "insert", "delete", "truncate"))
            if op == "flip":
                if not blob:
                    continue
                idx = rnd.randrange(len(blob))
                blob[idx] ^= 1 << rnd.randrange(8)
            elif op == "insert":
                if len(blob) >= max_size:
                    continue
                idx = rnd.randrange(len(blob) + 1)
                blob[idx:idx] = bytes([rnd.randrange(256)])
            elif op == "delete":
                if not blob:
                    continue
                idx = rnd.randrange(len(blob))
                del blob[idx]
            elif op == "truncate":
                if not blob:
                    continue
                new_len = rnd.randrange(len(blob))
                del blob[new_len:]
        mutations.append(bytes(blob))
    return mutations
