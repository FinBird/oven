from __future__ import annotations

import argparse
import sys
from pathlib import Path

from oven.api import decompile


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Oven AVM2 ABC decompiler")
    parser.add_argument("file", type=Path, help="Input .abc file (or path readable as binary ABC)")
    parser.add_argument("-o", "--output", type=Path, help="Write AS3 to this file instead of stdout")
    parser.add_argument(
        "--no-format",
        action="store_true",
        help="Skip AS3 pretty-printer (raw emitter output)",
    )
    parser.add_argument("--minify", action="store_true", help="Minify output (implies formatting pass)")
    parser.add_argument("--style", default="semantic", help="Emitter style (default: semantic)")
    args = parser.parse_args(argv)

    data = args.file.read_bytes()
    if args.no_format:
        from oven.api.decompiler import _decompile_abc_parsed
        from oven.avm2 import parse_abc

        abc = parse_abc(data)
        result = _decompile_abc_parsed(abc, None, style=args.style)
    else:
        result = decompile(data, style=args.style, minify=args.minify)

    if args.output:
        args.output.write_text(result, encoding="utf-8", newline="\n")
    else:
        sys.stdout.write(result)
        if not result.endswith("\n"):
            sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
