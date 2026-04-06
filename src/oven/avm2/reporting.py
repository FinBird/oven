from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import inspect
from pathlib import Path
import re
from typing import Any, Iterable, Sequence

from . import parse_abc
from .enums import Opcode, TraitKind
from .file import ABCFile
from .abc.reader import ABCReader
from .abc.opcode_registry import (
    MULTINAME_INDEX_OPERAND_OPCODES,
    NO_OPERAND_OPCODES,
    POOL_INDEX_OPERAND_KINDS,
    RELATIVE_I24_OPERAND_OPCODES,
    S8_OPERAND_OPCODES,
    TWO_U30_MULTINAME_COUNT_OPERAND_OPCODES,
    TWO_U30_PLAIN_OPERAND_OPCODES,
    U8_OPERAND_OPCODES,
    U30_PLAIN_OPERAND_OPCODES,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _fixtures_root(repo_root: Path | None = None) -> Path:
    base = _repo_root() if repo_root is None else repo_root
    return base / "fixtures"


def _jpexs_main_abc_path(repo_root: Path | None = None) -> Path:
    fixtures_main_abc = (
        _fixtures_root(repo_root)
        / "jpexs"
        / "as3_assembled"
        / "abc"
        / "as3_assembled-0"
        / "as3_assembled-0.main.abc"
    )
    if fixtures_main_abc.exists():
        return fixtures_main_abc

    base = _repo_root() if repo_root is None else repo_root
    jpexs_root = base / "jpexs-decompiler"
    if not jpexs_root.exists() and (base.parent / "jpexs-decompiler").exists():
        base = base.parent

    return (
        base
        / "jpexs-decompiler"
        / "libsrc"
        / "ffdec_lib"
        / "testdata"
        / "as3_assembled"
        / "abc"
        / "as3_assembled-0"
        / "as3_assembled-0.main.abc"
    )


def _jpexs_asasm_root(repo_root: Path | None = None) -> Path:
    return _jpexs_main_abc_path(repo_root).parent


def _jpexs_main_asasm_path(repo_root: Path | None = None) -> Path:
    return _jpexs_asasm_root(repo_root) / "as3_assembled-0.main.asasm"


def _short_name(name: str) -> str:
    if "::" in name:
        return name.split("::")[-1]
    return name


def _trait_method_names(traits: list[Any]) -> set[str]:
    names: set[str] = set()
    for trait in traits:
        if trait.kind not in {TraitKind.METHOD, TraitKind.GETTER, TraitKind.SETTER}:
            continue
        names.add(_short_name(trait.name))
    return names


def _class_name_from_asasm_path(path: Path) -> str:
    return path.name.replace(".class.asasm", "")


_INCLUDE_LINE_RE = re.compile(r'^\s*#include\s+"([^"]+)"\s*$', flags=re.M)


def _extract_asasm_includes(asasm_path: Path) -> tuple[Path, ...]:
    text = asasm_path.read_text(encoding="utf-8")
    includes: list[Path] = []
    for rel in _INCLUDE_LINE_RE.findall(text):
        includes.append((asasm_path.parent / rel).resolve())
    return tuple(includes)


def _resolve_reachable_class_asasm_paths(main_asasm: Path) -> tuple[Path, ...]:
    if not main_asasm.exists():
        return ()

    stack: list[Path] = [main_asasm.resolve()]
    visited: set[Path] = set()
    classes: set[Path] = set()

    while stack:
        current = stack.pop()
        if current in visited or not current.exists() or not current.is_file():
            continue
        visited.add(current)

        for include_path in _extract_asasm_includes(current):
            if include_path.name.endswith(".class.asasm"):
                classes.add(include_path)
            if include_path.suffix == ".asasm":
                stack.append(include_path)

    return tuple(sorted(classes))


def _extract_asasm_trait_methods(class_asasm: Path) -> set[str]:
    text = class_asasm.read_text(encoding="utf-8")
    return set(
        re.findall(
            r'^\s*trait\s+(?:method|getter|setter)\s+.*?"([^"]+)"\)(?:\s+.*)?$',
            text,
            flags=re.M,
        )
    )


def _extract_asasm_inits(class_asasm: Path) -> tuple[bool, bool]:
    text = class_asasm.read_text(encoding="utf-8")
    has_iinit = re.search(r"^\s*iinit\s*$", text, flags=re.M) is not None
    has_cinit = re.search(r"^\s*cinit\s*$", text, flags=re.M) is not None
    return has_iinit, has_cinit


@dataclass(frozen=True)
class AsasmClassAst:
    class_name: str
    methods: tuple[str, ...]
    has_iinit: bool
    has_cinit: bool


@dataclass(frozen=True)
class ParsedClassAst:
    class_name: str
    methods: tuple[str, ...]
    has_iinit: bool
    has_cinit: bool


@dataclass(frozen=True)
class ClassAstDiff:
    class_name: str
    in_asasm: bool
    in_parsed: bool
    expected_methods: tuple[str, ...]
    parsed_methods: tuple[str, ...]
    missing_methods: tuple[str, ...]
    extra_methods: tuple[str, ...]
    expected_iinit: bool
    parsed_iinit: bool
    expected_cinit: bool
    parsed_cinit: bool


@dataclass(frozen=True)
class JpexsAstDiffSummary:
    total_classes: int
    matched_classes: int
    missing_classes: int
    extra_classes: int
    classes_with_method_diff: int
    classes_with_init_diff: int
    missing_methods_total: int
    extra_methods_total: int


@dataclass(frozen=True)
class JpexsAstDiffReport:
    summary: JpexsAstDiffSummary
    class_diffs: tuple[ClassAstDiff, ...]


def _load_asasm_class_ast(
    asasm_root: Path, class_asasm_paths: Iterable[Path] | None = None
) -> dict[str, AsasmClassAst]:
    result: dict[str, AsasmClassAst] = {}
    class_paths = (
        sorted(asasm_root.rglob("*.class.asasm"))
        if class_asasm_paths is None
        else sorted(class_asasm_paths)
    )
    for class_asasm in class_paths:
        class_name = _class_name_from_asasm_path(class_asasm)
        methods = tuple(sorted(_extract_asasm_trait_methods(class_asasm)))
        has_iinit, has_cinit = _extract_asasm_inits(class_asasm)
        result[class_name] = AsasmClassAst(
            class_name=class_name,
            methods=methods,
            has_iinit=has_iinit,
            has_cinit=has_cinit,
        )
    return result


def _load_parsed_class_ast(abc: ABCFile) -> dict[str, ParsedClassAst]:
    result: dict[str, ParsedClassAst] = {}
    for instance, cls in zip(abc.instances, abc.classes):
        class_name = _short_name(instance.name)
        methods = tuple(
            sorted(
                _trait_method_names(instance.traits) | _trait_method_names(cls.traits)
            )
        )
        has_iinit = abc.method_body_at(instance.init_method) is not None
        has_cinit = abc.method_body_at(cls.init_method) is not None
        result[class_name] = ParsedClassAst(
            class_name=class_name,
            methods=methods,
            has_iinit=has_iinit,
            has_cinit=has_cinit,
        )
    return result


def build_jpexs_ast_diff_report(repo_root: Path | None = None) -> JpexsAstDiffReport:
    asasm_root = _jpexs_asasm_root(repo_root)
    main_asasm_path = _jpexs_main_asasm_path(repo_root)
    main_abc_path = _jpexs_main_abc_path(repo_root)

    reachable_class_paths = _resolve_reachable_class_asasm_paths(main_asasm_path)
    expected = _load_asasm_class_ast(
        asasm_root,
        class_asasm_paths=reachable_class_paths if reachable_class_paths else None,
    )
    parsed_abc = parse_abc(main_abc_path.read_bytes(), mode="relaxed")
    parsed = _load_parsed_class_ast(parsed_abc)

    class_names = sorted(set(expected) | set(parsed))
    diffs: list[ClassAstDiff] = []

    matched_classes = 0
    missing_classes = 0
    extra_classes = 0
    classes_with_method_diff = 0
    classes_with_init_diff = 0
    missing_methods_total = 0
    extra_methods_total = 0

    for class_name in class_names:
        expected_class = expected.get(class_name)
        parsed_class = parsed.get(class_name)

        in_asasm = expected_class is not None
        in_parsed = parsed_class is not None

        if in_asasm and in_parsed:
            matched_classes += 1
        elif in_asasm and not in_parsed:
            missing_classes += 1
        elif in_parsed and not in_asasm:
            extra_classes += 1

        expected_methods = set(expected_class.methods) if expected_class else set()
        parsed_methods = set(parsed_class.methods) if parsed_class else set()
        missing_methods = tuple(sorted(expected_methods - parsed_methods))
        extra_methods = tuple(sorted(parsed_methods - expected_methods))

        expected_iinit = expected_class.has_iinit if expected_class else False
        parsed_iinit = parsed_class.has_iinit if parsed_class else False
        expected_cinit = expected_class.has_cinit if expected_class else False
        parsed_cinit = parsed_class.has_cinit if parsed_class else False

        if missing_methods or extra_methods:
            classes_with_method_diff += 1
        if expected_iinit != parsed_iinit or expected_cinit != parsed_cinit:
            classes_with_init_diff += 1

        missing_methods_total += len(missing_methods)
        extra_methods_total += len(extra_methods)

        diffs.append(
            ClassAstDiff(
                class_name=class_name,
                in_asasm=in_asasm,
                in_parsed=in_parsed,
                expected_methods=tuple(sorted(expected_methods)),
                parsed_methods=tuple(sorted(parsed_methods)),
                missing_methods=missing_methods,
                extra_methods=extra_methods,
                expected_iinit=expected_iinit,
                parsed_iinit=parsed_iinit,
                expected_cinit=expected_cinit,
                parsed_cinit=parsed_cinit,
            )
        )

    summary = JpexsAstDiffSummary(
        total_classes=len(class_names),
        matched_classes=matched_classes,
        missing_classes=missing_classes,
        extra_classes=extra_classes,
        classes_with_method_diff=classes_with_method_diff,
        classes_with_init_diff=classes_with_init_diff,
        missing_methods_total=missing_methods_total,
        extra_methods_total=extra_methods_total,
    )
    return JpexsAstDiffReport(summary=summary, class_diffs=tuple(diffs))


def _class_ast_diff_has_delta(diff: ClassAstDiff) -> bool:
    return (
        not diff.in_asasm
        or not diff.in_parsed
        or bool(diff.missing_methods)
        or bool(diff.extra_methods)
        or diff.expected_iinit != diff.parsed_iinit
        or diff.expected_cinit != diff.parsed_cinit
    )


def render_jpexs_ast_diff_markdown(report: JpexsAstDiffReport) -> str:
    summary = report.summary
    lines: list[str] = []
    lines.append("# JPEXS AST Diff Report")
    lines.append("")
    lines.append("Generated from:")
    lines.append(
        "- Parsed source: `as3_assembled-0.main.abc` via `parse_abc(..., mode='relaxed')`"
    )
    lines.append(
        "- Reference source: JPEXS `as3_assembled-0.main.asasm` reachable `.class.asasm` trait/method declarations"
    )
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Total classes (union): `{summary.total_classes}`")
    lines.append(f"- Matched classes: `{summary.matched_classes}`")
    lines.append(f"- Missing classes in parsed ABC: `{summary.missing_classes}`")
    lines.append(f"- Extra classes in parsed ABC: `{summary.extra_classes}`")
    lines.append(
        f"- Classes with method-level diffs: `{summary.classes_with_method_diff}`"
    )
    lines.append(
        f"- Classes with init diffs (`iinit/cinit`): `{summary.classes_with_init_diff}`"
    )
    lines.append(f"- Missing methods total: `{summary.missing_methods_total}`")
    lines.append(f"- Extra methods total: `{summary.extra_methods_total}`")
    lines.append("")

    diff_rows = [diff for diff in report.class_diffs if _class_ast_diff_has_delta(diff)]
    lines.append("## Diffs")
    lines.append("")
    if not diff_rows:
        lines.append("- No diffs.")
        lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    lines.append(
        "| Class | ASASM | Parsed | Missing Methods | Extra Methods | iinit | cinit |"
    )
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for diff in diff_rows:
        missing = ", ".join(diff.missing_methods) if diff.missing_methods else "-"
        extra = ", ".join(diff.extra_methods) if diff.extra_methods else "-"
        iinit = f"{diff.expected_iinit}/{diff.parsed_iinit}"
        cinit = f"{diff.expected_cinit}/{diff.parsed_cinit}"
        lines.append(
            f"| `{diff.class_name}` | `{diff.in_asasm}` | `{diff.in_parsed}` | "
            f"`{missing}` | `{extra}` | `{iinit}` | `{cinit}` |"
        )
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


@dataclass(frozen=True)
class OpcodeFamilyCoverageRow:
    family: str
    opcodes: tuple[Opcode, ...]
    parse_supported: tuple[Opcode, ...]
    stack_effect_supported: tuple[Opcode, ...]
    type_merge_supported: tuple[Opcode, ...]


@dataclass(frozen=True)
class OpcodeFamilyCoverageReport:
    rows: tuple[OpcodeFamilyCoverageRow, ...]
    uncovered_families: tuple[str, ...]
    duplicate_opcodes: tuple[str, ...]


def _extract_opcode_names_from_source(source: str) -> set[str]:
    return set(re.findall(r"Opcode\.([A-Za-z0-9_]+)", source))


def _extract_opcodes_from_callable(obj: Any) -> set[Opcode]:
    source = inspect.getsource(obj)
    names = _extract_opcode_names_from_source(source)
    result: set[Opcode] = set()
    for name in names:
        if hasattr(Opcode, name):
            result.add(getattr(Opcode, name))
    return result


def _extract_opcodes_from_value(value: object) -> set[Opcode]:
    items: Iterable[object]
    if isinstance(value, dict):
        items = value.keys()
    elif isinstance(value, (set, frozenset, tuple, list)):
        items = value
    else:
        return set()
    return {item for item in items if isinstance(item, Opcode)}


def _extract_opcodes_from_reader_attrs(*attribute_names: str) -> set[Opcode]:
    result: set[Opcode] = set()
    for attribute_name in attribute_names:
        result |= _extract_opcodes_from_value(getattr(ABCReader, attribute_name))
    return result


def _opcode_families_from_enums_source() -> dict[str, list[Opcode]]:
    enums_path = Path(__file__).with_name("enums.py")
    text = enums_path.read_text(encoding="utf-8")

    families: dict[str, list[Opcode]] = defaultdict(list)
    in_opcode_class = False
    current_family = "Uncategorized"

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if line.startswith("class Opcode("):
            in_opcode_class = True
            continue
        if in_opcode_class and line.startswith("# TypedDicts"):
            break
        if not in_opcode_class:
            continue

        family_match = re.match(r"^\s*#\s+(.+?)\s*$", line)
        if family_match:
            current_family = family_match.group(1)
            continue

        opcode_match = re.match(
            r"^\s*([A-Za-z][A-Za-z0-9_]*)\s*=\s*0x[0-9a-fA-F]+\s*$", line
        )
        if not opcode_match:
            continue
        opcode_name = opcode_match.group(1)
        if hasattr(Opcode, opcode_name):
            families[current_family].append(getattr(Opcode, opcode_name))

    return {family: opcodes for family, opcodes in families.items() if opcodes}


def build_opcode_family_coverage_report() -> OpcodeFamilyCoverageReport:
    families = _opcode_families_from_enums_source()

    parse_supported: set[Opcode] = (
        set(NO_OPERAND_OPCODES)
        | set(RELATIVE_I24_OPERAND_OPCODES)
        | set(S8_OPERAND_OPCODES)
        | set(U8_OPERAND_OPCODES)
        | set(U30_PLAIN_OPERAND_OPCODES)
        | set(POOL_INDEX_OPERAND_KINDS.keys())
        | set(MULTINAME_INDEX_OPERAND_OPCODES)
        | set(TWO_U30_PLAIN_OPERAND_OPCODES)
        | set(TWO_U30_MULTINAME_COUNT_OPERAND_OPCODES)
        | {Opcode.LookupSwitch, Opcode.Debug, Opcode.DebugLine}
    )

    stack_effect_supported: set[Opcode] = (
        set(ABCReader._STACK_EFFECT_STATIC_OPCODES.keys())
        | _extract_opcodes_from_reader_attrs(
            "_STACK_EFFECT_GET_PROPERTY_OPCODES",
            "_STACK_EFFECT_SET_PROPERTY_OPCODES",
            "_STACK_EFFECT_FIND_PROPERTY_OPCODES",
            "_STACK_EFFECT_CALL_PROPERTY_OPCODES",
            "_STACK_EFFECT_CALL_PROPVOID_OPCODES",
        )
        | _extract_opcodes_from_callable(ABCReader._stack_effect_for_instruction)
    )

    type_merge_supported: set[Opcode] = (
        _extract_opcodes_from_reader_attrs(
            "_STACK_STATE_COERCE_RESULT_OPCODES",
            "_STACK_STATE_FIND_PROPERTY_OBJECT_OPCODES",
            "_STACK_STATE_ANY_RESULT_OPCODES",
            "_STACK_STATE_OBJECT_RESULT_OPCODES",
            "_STACK_STATE_STRING_RESULT_OPCODES",
            "_STACK_STATE_GETLOCAL_OPCODES",
            "_STACK_STATE_CALL_PROPERTY_OPCODES",
            "_DEFAULT_PUSH_TYPE_OVERRIDES",
        )
        | _extract_opcodes_from_callable(ABCReader._stack_state_after_instruction)
        | _extract_opcodes_from_callable(ABCReader._local_state_after_instruction)
        | _extract_opcodes_from_callable(ABCReader._scope_state_after_instruction)
        | _extract_opcodes_from_callable(ABCReader._default_push_type_for_instruction)
    )

    rows: list[OpcodeFamilyCoverageRow] = []
    seen: dict[Opcode, str] = {}
    duplicate_entries: list[str] = []
    for family, opcodes in families.items():
        for opcode in opcodes:
            previous = seen.get(opcode)
            if previous is not None and previous != family:
                duplicate_entries.append(f"{opcode.name}: {previous} + {family}")
            else:
                seen[opcode] = family

        opcode_tuple = tuple(opcodes)
        rows.append(
            OpcodeFamilyCoverageRow(
                family=family,
                opcodes=opcode_tuple,
                parse_supported=tuple(
                    sorted(
                        (set(opcode_tuple) & parse_supported), key=lambda op: op.value
                    )
                ),
                stack_effect_supported=tuple(
                    sorted(
                        (set(opcode_tuple) & stack_effect_supported),
                        key=lambda op: op.value,
                    )
                ),
                type_merge_supported=tuple(
                    sorted(
                        (set(opcode_tuple) & type_merge_supported),
                        key=lambda op: op.value,
                    )
                ),
            )
        )

    uncovered = sorted(op.name for op in Opcode if op not in seen)
    return OpcodeFamilyCoverageReport(
        rows=tuple(rows),
        uncovered_families=tuple(uncovered),
        duplicate_opcodes=tuple(sorted(set(duplicate_entries))),
    )


def _format_supported_ratio(supported: Sequence[Opcode], total: int) -> str:
    count = len(supported)
    if total <= 0:
        return "0/0 (0%)"
    pct = round((count * 100.0) / total)
    return f"{count}/{total} ({pct}%)"


def _format_csv_or_dash(values: Sequence[str]) -> str:
    return ", ".join(values) if values else "-"


def render_opcode_family_coverage_markdown(report: OpcodeFamilyCoverageReport) -> str:
    lines: list[str] = []
    lines.append("# Opcode Family Coverage")
    lines.append("")
    lines.append("Columns:")
    lines.append("- Parse: operand decoding support coverage")
    lines.append("- Stack Effect: explicit stack pop/push semantics coverage")
    lines.append("- Type Merge: explicit type-aware stack/local/scope merge coverage")
    lines.append("")
    lines.append("## Family Summary")
    lines.append("")
    lines.append("| Family | Opcode Count | Parse | Stack Effect | Type Merge |")
    lines.append("| --- | --- | --- | --- | --- |")
    for row in report.rows:
        total = len(row.opcodes)
        lines.append(
            f"| {row.family} | `{total}` | "
            f"`{_format_supported_ratio(row.parse_supported, total)}` | "
            f"`{_format_supported_ratio(row.stack_effect_supported, total)}` | "
            f"`{_format_supported_ratio(row.type_merge_supported, total)}` |"
        )
    lines.append("")

    total_opcodes = sum(len(row.opcodes) for row in report.rows)
    total_parse_supported = sum(len(row.parse_supported) for row in report.rows)
    total_stack_supported = sum(len(row.stack_effect_supported) for row in report.rows)
    total_type_supported = sum(len(row.type_merge_supported) for row in report.rows)
    lines.append("## Overall Coverage")
    lines.append("")
    lines.append(f"- Parse: `{total_parse_supported}/{total_opcodes}`")
    lines.append(f"- Stack Effect: `{total_stack_supported}/{total_opcodes}`")
    lines.append(f"- Type Merge: `{total_type_supported}/{total_opcodes}`")
    lines.append("")

    gap_rows = []
    for row in report.rows:
        opcode_set = set(row.opcodes)
        parse_gap = sorted(op.name for op in opcode_set - set(row.parse_supported))
        stack_gap = sorted(
            op.name for op in opcode_set - set(row.stack_effect_supported)
        )
        type_gap = sorted(op.name for op in opcode_set - set(row.type_merge_supported))
        if parse_gap or stack_gap or type_gap:
            gap_rows.append((row.family, parse_gap, stack_gap, type_gap))
    lines.append("## Coverage Gaps")
    lines.append("")
    if not gap_rows:
        lines.append("- None")
    else:
        lines.append("| Family | Parse Gaps | Stack Effect Gaps | Type Merge Gaps |")
        lines.append("| --- | --- | --- | --- |")
        for family, parse_gap, stack_gap, type_gap in gap_rows:
            lines.append(
                f"| {family} | `{_format_csv_or_dash(parse_gap)}` | "
                f"`{_format_csv_or_dash(stack_gap)}` | `{_format_csv_or_dash(type_gap)}` |"
            )
    lines.append("")

    lines.append("## Global Consistency")
    lines.append("")
    lines.append(
        f"- Duplicate family assignments: `{_format_csv_or_dash(report.duplicate_opcodes)}`"
    )
    lines.append(
        f"- Uncovered opcodes in family extraction: `{_format_csv_or_dash(report.uncovered_families)}`"
    )
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"
