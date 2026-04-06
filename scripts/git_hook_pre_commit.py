from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def git_output(*args: str) -> list[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=False,
    )
    return [
        item.decode("utf-8", errors="surrogateescape")
        for item in result.stdout.split(b"\0")
        if item
    ]


def run_checked(command: list[str], *, label: str) -> None:
    print(f"[pre-commit] {label}")
    completed = subprocess.run(command, cwd=REPO_ROOT)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def select_python_files(paths: list[str]) -> list[str]:
    selected: list[str] = []
    for rel_path in paths:
        path = REPO_ROOT / rel_path
        if path.suffix in {".py", ".pyi"} and path.is_file():
            selected.append(rel_path)
    return selected


def main() -> int:
    python_cmd = sys.executable
    if shutil.which("git") is None:
        print("[pre-commit] git is not available on PATH.", file=sys.stderr)
        return 1

    staged_paths = git_output(
        "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"
    )
    staged_python_files = select_python_files(staged_paths)

    if staged_python_files:
        unstaged_paths = set(git_output("diff", "--name-only", "-z"))
        conflicted = [path for path in staged_python_files if path in unstaged_paths]
        if conflicted:
            print(
                "[pre-commit] Refusing to auto-format files that also have unstaged changes:",
                file=sys.stderr,
            )
            for path in conflicted:
                print(f"  - {path}", file=sys.stderr)
            print(
                "[pre-commit] Stage or stash those edits, then commit again.",
                file=sys.stderr,
            )
            return 1

        run_checked(
            [python_cmd, "-m", "black", *staged_python_files],
            label="Formatting staged Python files with black",
        )
        run_checked(
            ["git", "add", "--", *staged_python_files],
            label="Restaging formatted files",
        )
    else:
        print("[pre-commit] No staged Python files to format.")

    run_checked(
        [python_cmd, "-m", "mypy"], label="Running mypy --strict from pyproject.toml"
    )
    print("[pre-commit] Checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
