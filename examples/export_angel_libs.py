#!/usr/bin/env python3
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from oven.api import Decompiler, ExportOptions
from oven.avm2.config import ParseMode

ABC_PATH = ROOT / "fixtures" / "abc" / "AngelClientLibs.abc"
OUTPUT_DIR = ROOT / "out" / "AngelClientLibs"
print(ABC_PATH)
print(OUTPUT_DIR)


def main() -> int:
    started_at = time.perf_counter()
    decompiler = Decompiler.from_file(
        ABC_PATH,
        options=ExportOptions(
            debug=True,
            mode=ParseMode.RELAXED,
            style="semantic",
            int_format="dec",
            inline_vars=True,
            failure_policy="continue",
        ),
    )
    result = decompiler.export_to_disk(OUTPUT_DIR, clean=True)
    files = result.output_files

    total_lines, total_bytes = 0, 0
    for file_path in files:
        text = file_path.read_text(encoding="utf-8")
        total_lines += len(text.splitlines())
        total_bytes += file_path.stat().st_size

    elapsed_seconds = time.perf_counter() - started_at

    print(f"exported {len(files)} files to {OUTPUT_DIR}")
    print(f"elapsed_seconds={elapsed_seconds:.3f}")
    print(f"total_lines={total_lines}")
    print(f"total_bytes={total_bytes}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
