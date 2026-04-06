#!/usr/bin/env python3
"""cProfile analysis for decompile workflow."""

import cProfile
import pstats
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from oven.api import Decompiler, ExportOptions
from oven.avm2.config import ParseMode

ABC_PATH = ROOT / "fixtures" / "abc" / "AngelClientLibs.abc"


def decompile_task() -> None:
    """Single decompile task."""
    decompiler = Decompiler.from_file(
        ABC_PATH,
        options=ExportOptions(
            debug=False,
            mode=ParseMode.RELAXED,
            style="semantic",
            int_format="hex",
            inline_vars=True,
            failure_policy="continue",
        ),
    )
    list(decompiler.iter_classes())


def main() -> None:
    profiler = cProfile.Profile()
    profiler.enable()

    iterations = 3
    for i in range(iterations):
        print(f"Iteration {i + 1}/{iterations}...")
        decompile_task()

    profiler.disable()

    stats = pstats.Stats(profiler)
    print("\n" + "=" * 80)
    print("=== 函数级性能瓶颈 (按累计耗时排序) ===")
    print("=" * 80)
    stats.sort_stats("cumulative").print_stats(30)

    print("\n" + "=" * 80)
    print("=== 函数级性能瓶颈 (按总耗时排序) ===")
    print("=" * 80)
    stats.sort_stats("tottime").print_stats(20)


if __name__ == "__main__":
    main()
