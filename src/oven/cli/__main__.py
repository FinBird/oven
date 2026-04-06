from __future__ import annotations

import argparse
import sys
from pathlib import Path

from oven.api import Decompiler, ExportOptions
from oven.avm2.config import ParseMode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Oven AVM2 ABC decompiler")
    parser.add_argument("file", type=Path, help="Input .abc file")
    parser.add_argument("-o", "--output", type=Path, help="Write output to this file")
    parser.add_argument("--style", default="semantic", help="Emitter style (default: semantic)")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Emit bytecode comments (offset + opcode + operands)",
    )
    args = parser.parse_args(argv)

    decompiler = Decompiler.from_file(
        args.file,
        options=ExportOptions(
            style=args.style,
            debug=args.debug,
            mode=ParseMode.RELAXED,
        ),
    )
    result = "\n\n".join(block.source for block in decompiler.iter_classes())

    if args.output:
        args.output.write_text(result, encoding="utf-8", newline="\n")
    else:
        sys.stdout.write(result)
        if not result.endswith("\n"):
            sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

