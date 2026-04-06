# Oven

`Oven` is an AVM2 / ABC parsing and decompilation project for Python 3.10+.
The repository currently exposes a class-oriented public API under `src/oven/api`,
low-level AVM2 parsing utilities under `src/oven/avm2`, and reusable AST / CFG /
transform infrastructure under `src/oven/core`.

## Requirements

- Python 3.10 or newer
- Git LFS, because fixture files such as `*.abc`, `*.asasm`, and `*.pdf` are tracked with LFS
- `pip` with editable install support for local development
- Optional: JPEXS Free Flash Decompiler if you need to regenerate fixture corpora under `fixtures/jpexs/`

## Quick Start

### 1. Prepare the environment

Windows `cmd`:

```bat
python -m venv .venv
.venv\Scripts\activate
python -m pip install -U pip
python -m pip install -e .[dev]
```

PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -e .[dev]
```

### 2. Enable repository hooks

The repository ships tracked hooks under `.githooks/`. Enable them once per clone:

```bat
git config core.hooksPath .githooks
```

After activation, every `git commit` will:

- run `black` on staged Python files and re-stage the formatter output
- run `mypy` with the committed strict configuration from `pyproject.toml`
- block the commit if formatting, type checking, or hook prerequisites fail

## Common Usage

### CLI usage

The command-line entrypoint lives in `src/oven/cli/__main__.py` and is exposed as
the `oven` console script after an editable install.

```bat
oven fixtures\abc\Test.abc -o out\Test.as --style semantic --debug
```

Equivalent module invocation:

```bat
python -m oven.cli fixtures\abc\Test.abc -o out\Test.as --style semantic --debug
```

CLI parameters:

- `file`: input `.abc` file path
- `-o`, `--output`: write merged output to a single file
- `--style`: emitter style, default is `semantic`
- `--debug`: include bytecode debug comments in generated output

### Python API usage

```python
from pathlib import Path

from oven.api import Decompiler, ExportOptions
from oven.avm2.config import ParseMode

abc_path = Path("fixtures/abc/Test.abc")
out_dir = Path("out/Test")

decompiler = Decompiler.from_file(
    abc_path,
    options=ExportOptions(
        style="semantic",
        int_format="hex",
        inline_vars=True,
        debug=False,
        mode=ParseMode.RELAXED,
        failure_policy="continue",
    ),
)

result = decompiler.export_to_disk(out_dir, clean=True)
print(result.output_files)
print(result.recovery_flags)
```

### Useful `ExportOptions`

- `style`: output style, currently used by the emitter / decompiler pipeline
- `int_format`: integer formatting, typically `hex` or `dec`
- `inline_vars`: enable inline variable recovery in output
- `debug`: include offset / opcode / operand comments
- `mode`: parse mode, one of `fast`, `relaxed`, `strict`
- `profile`: verification profile override when needed
- `failure_policy`: `continue` or `fail_fast`
- `enable_static_init_lifting`: lift static init logic when possible
- `enable_constructor_field_lifting`: lift constructor field assignments
- `enable_auto_imports`: auto-import symbols during emission
- `enable_namespace_cleanup`: simplify namespace output
- `enable_switch_optimization`: optimize switch reconstruction
- `enable_text_cleanup`: normalize emitted text

## Repository Layout

```text
oven/
|-- README.md
|-- pyproject.toml
|-- pytest.ini
|-- profile_decompile.py
|-- .githooks/
|-- examples/
|   `-- export_angel_libs.py
|-- fixtures/
|   |-- abc/
|   |-- jpexs/
|   `-- THIRD_PARTY_TEST_DEPENDENCIES.md
|-- jpexs-decompiler/
|-- out/
|-- reports/
|-- scripts/
|   `-- git_hook_pre_commit.py
`-- src/
    `-- oven/
        |-- __init__.py
        |-- py.typed
        |-- api/
        |   |-- __init__.py
        |   |-- transforms/
        |   `-- tests/
        |-- avm2/
        |   |-- __init__.py
        |   |-- abc/
        |   |-- decompiler/
        |   |-- transform/
        |   `-- tests/
        |-- cli/
        |   `-- __main__.py
        `-- core/
            |-- __init__.py
            |-- ast/
            |-- cfg/
            |-- code/
            |-- docs/
            |-- tests/
            |-- transform/
            `-- utils/
```

Structure notes:

- `pyproject.toml`: packaging metadata, editable install settings, development extras, and shared mypy configuration
- `.githooks/`: tracked Git hook entrypoints, including the blocking pre-commit gate and preserved Git LFS hooks
- `src/oven/api/`: stable public orchestration layer for decompilation and export
- `src/oven/avm2/`: parser, verifier, ABC model, decompiler internals, and AVM2-specific tests
- `src/oven/cli/`: installable command-line entrypoint exposed as `oven`
- `src/oven/core/`: reusable AST, CFG, token, pipeline, transform, utility, and documentation helpers
- `scripts/git_hook_pre_commit.py`: hook implementation that formats staged Python files and runs strict mypy
- `fixtures/abc/`: local binary ABC fixtures used by parser and decompiler tests
- `fixtures/jpexs/`: third-party fixture corpus mirrored from JPEXS-related sources
- `jpexs-decompiler/`: upstream reference tree kept in-repo for comparison and fixture generation workflows
- `out/`: generated decompilation output written by examples and local experiments
- `reports/`: generated HTML test and coverage reports
- `examples/export_angel_libs.py`: end-to-end export example
- `profile_decompile.py`: simple `cProfile`-based decompilation profiling script

## Pytest Usage

Current pytest behavior is controlled by `pytest.ini`:

- test discovery root: `src`
- test filename pattern: `test_*.py`
- editable install expected: run `python -m pip install -e .[dev]` before invoking pytest
- strict mode: `--strict-config`, `--strict-markers`, `xfail_strict = true`
- parallel execution: `-n auto --dist loadscope`
- HTML report: `reports/test_report.html`
- coverage targets: `--cov=oven`, plus terminal and HTML coverage reports

Common commands:

```bat
python -m pytest
python -m pytest src/oven/core/tests/test_cfg.py
python -m pytest src/oven/avm2/tests -m "not slow"
python -m pytest src/oven/api/tests/test_output.py
```

Available markers:

- `slow`: long-running tests
- `fixture`: tests that require binary fixtures
- `performance`: performance-sensitive tests

## Mypy and Strict Type Checking

Strict type checking is committed in `pyproject.toml` under `[tool.mypy]`.
The shared policy pins Python 3.10 semantics, checks `src/oven`, enables
`strict = true`, and prints mypy error codes by default.

Run mypy from the repository root:

```bat
python -m mypy
```

Package-scoped invocations still work when you want a narrower loop:

```bat
python -m mypy src/oven/api
python -m mypy src/oven/core
python -m mypy src/oven/avm2
```

## Commit Hooks

The tracked pre-commit hook is implemented in `.githooks/pre-commit` and delegates
to `scripts/git_hook_pre_commit.py`.

Behavior:

- formats staged `*.py` files with `black`
- re-stages formatter changes automatically
- refuses to auto-format a staged Python file when that file also has unstaged edits
- runs `python -m mypy` using the strict repository configuration
- exits non-zero on any failure so `git commit` is rejected

## TODO

- Split fixture-heavy regression tests from the default fast path more clearly
- Add CI commands that run pytest plus mypy in a consistent environment
- Expand root-level documentation as the public API surface stabilizes

## Additional Notes

- Some AVM2 tests depend on fixture files under `fixtures/abc/` and `fixtures/jpexs/`.
- JPEXS export instructions for `.abc` / `.asasm` fixtures are documented in
  `fixtures/THIRD_PARTY_TEST_DEPENDENCIES.md`.
- Standard local development now uses the editable install above instead of a
  manual `PYTHONPATH=src` step.
- `examples/export_angel_libs.py` still bootstraps `src/` internally so it can
  run directly from a checkout when needed.
