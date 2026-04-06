# Third-party test dependencies and local fixtures

This document describes where critical test inputs originate and how they are staged inside this repository so that oven tests can run without relying on external worktrees or absolute paths.

## 1. Repository-native fixtures

- Directory: `fixtures/abc/`
- Purpose: Most of `src/oven/avm2/tests/` exercises rely on these ABC bundles (`Test.abc`, `Avm2Dummy.abc`, `abcdump.abc`, `builtin.abc`, `AngelClientLibs.abc`, etc.).

## 2. JPEXS-derived datasets

### 2.1 `as3_assembled` corpus (smoke matrices & reporting regression)

- Upstream reference: `jpexs-decompiler/libsrc/ffdec_lib/testdata/as3_assembled/`
- Local mirror: `fixtures/jpexs/as3_assembled/`
- Files under `fixtures/jpexs/as3_assembled/abc/` include:
  - `as3_assembled-0.abc`
  - `as3_assembled-0/as3_assembled-0.main.abc`
  - `as3_assembled-0/as3_assembled-0.main.asasm`
  - any dependent `*.class.asasm` metadata for the tests listed under `tests/`

These assets feed `test_abc_file_api.py`, `test_jpexs_assembled_smoke_matrix.py`, and other AVM2 regressions that compare decompiled output to the ASM dumps.

### 2.2 Java regression list

- Upstream reference: `jpexs-decompiler/libsrc/ffdec_lib/test/com/jpexs/decompiler/flash/as3decompile/ActionScript3AssembledDecompileTest.java`
- Local mirror: `fixtures/jpexs/java/ActionScript3AssembledDecompileTest.java`
- Purpose: exercise the `decompileMethod("assembled", "...")` matrix of method names.

## 3. Exporting `*.asasm` files with JPEXS

1. Download and launch [JPEXS Free Flash Decompiler](https://www.free-decompiler.com/flash/).
2. Choose `File → Open` and load `fixtures/jpexs/as3_assembled/bin/as3_assembled.swf`.
3. Expand the SWF tree until you reach the `abc` group; select the relevant `as3_assembled-0.main` or `tests` bundle.
4. Right-click an ABC node and use `Export selection → Save ABC file` to emit `fixtures/jpexs/as3_assembled/abc/.../*.abc`.
5. Reopen the same ABC node and choose `Export selection → Save ASASM file` to generate the text dumps (`*.asasm`) for `main`, `class`, and test scripts.
6. Repeat for each class or test case listed under `fixtures/jpexs/as3_assembled/abc/as3_assembled-0/tests/`, saving the `Template.class.asasm`, `TestDupAssignment.script.asasm`, etc. into the matching directory structure.
7. If the project compares decompiler output against the `.asasm` snapshots, make sure the exported files land in `fixtures/jpexs/as3_assembled/abc/` alongside their `.abc` counterparts.
8. Commit both the updated `.abc` files and their `.asasm` counterparts; the repository treats both as binary assets via Git LFS.

## 4. Directory mapping fallback order

1. `fixtures/jpexs/...` (project-local copies).
2. `../jpexs-decompiler/...` (legacy layout for developers keeping the original repo next door).
3. `C:\seer-swf\...` (optional local data set; not required for CI).

## 5. Manual synchronization recipe

Use the Python standard library or plain file copy commands to sync from the original JPEXS workspace:

```python
import shutil
from pathlib import Path

src_root = Path("../jpexs-decompiler/libsrc/ffdec_lib/testdata/as3_assembled")
dst_root = Path("fixtures/jpexs/as3_assembled")
shutil.copytree(src_root, dst_root, dirs_exist_ok=True)
```

Repeat a similar copy for `ActionScript3AssembledDecompileTest.java`.
