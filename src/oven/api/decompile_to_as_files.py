from __future__ import annotations

import os
import platform
import re
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

from oven.avm2 import parse, ParseMode
from oven.avm2.file import ABCFile
from oven.avm2.enums import TraitKind, ConstantKind 
from oven.api.decompiler import (
    AS3Emitter,
    _build_class_member_lines,
    _build_class_signature,
    _build_method_context,
    _build_method_ir,
    _build_method_owner_map,
    _collect_class_method_entries,
    _decompile_abc_classes_layout_blocks,
    _extract_method_field_initializers,
    _render_layout_method_signature,
    _try_fast_emit_method_text,
)
from oven.api.formatter import AS3Lexer, AS3Processor, CommentPolicy, ProcessorConfig

META_PREFIXES = ('PACKAGE_NAMESPACE', 'PACKAGE_INTERNAL', 'PRIVATE_NS', 'PROTECTED_', 'STATIC_PROTECTED_')
AS3_KW = ABCFile.AS3_KEYWORDS
_FUNCTION_SIGNATURE_RE = re.compile(
    r'(?m)^\s*(?:public|private|protected|internal)\s+(?:static\s+)?function(?:\s+(?:get|set))?\s+[A-Za-z_$][0-9A-Za-z_$]*\s*\('
)
_EXISTING_IMPORT_RE = re.compile(
    r'(?m)^\s*import\s+([A-Za-z_$][0-9A-Za-z_$]*(?:\.[A-Za-z_$][0-9A-Za-z_$]*|\.\*)*)\s*;\s*$'
)
_ID_TOKEN_RE = re.compile(r'^[A-Za-z_$][0-9A-Za-z_$]*$')
_POOL_AUTO_IMPORT_INDEX_ATTR = "_cached_auto_import_index_by_name"

_SANITIZE_NON_IDENTIFIER_RE = re.compile(r'[^0-9A-Za-z_$]')
_SANITIZE_LEADING_DIGITS_RE = re.compile(r'^[0-9]+')
_MEMBER_DECLARATION_NAME_RE = re.compile(
    r'(?m)^\s*(?:public|private|protected|internal)\s+(?:static\s+)?(?:var|const)\s+([A-Za-z_$][0-9A-Za-z_$]*)\b'
)
_FIELD_INITIALIZERS_BLOCK_RE = re.compile(
    r'/\*\s*field\s+initializers(?:\s+for\s+([A-Za-z_$][0-9A-Za-z_$]*))?\s*(.*?)\*/',
    re.DOTALL,
)
_FIELD_INITIALIZER_LINE_RE = re.compile(r'^\s*\*\s*this\.([A-Za-z_$][0-9A-Za-z_$]*)\s*=\s*(.*?)\s*;?\s*$')
_IMPORT_LINE_RE = re.compile(
    r'^\s*import\s+[A-Za-z_$][0-9A-Za-z_$]*(?:\.[A-Za-z_$][0-9A-Za-z_$]*|\.\*)*\s*;\s*$'
)
_HAS_IMPORT_RE = re.compile(
    r'(?m)^\s*import\s+[A-Za-z_$][0-9A-Za-z_$]*(?:\.[A-Za-z_$][0-9A-Za-z_$]*|\.\*)*\s*;\s*$'
)

_RE_REDUNDANT_MEMBER = re.compile(r'\b([A-Za-z_$][0-9A-Za-z_$]*)\.\1\s*=')
_RE_VOID_VARIANT = re.compile(r':void(?:_i\d+)?\b')
_RE_AS_TYPE_LATE = re.compile(r'\(\s*/\*\s*as_type_late\s*\*/\s*undefined\s*\);\s*')
_RE_UNSUPPORTED_CONVERT = re.compile(r'/\*\s*unsupported expr:\s*convert_([iudso])\s*\*/\s*\((.*?)\)')
_RE_NAMESPACE_PREFIX = re.compile(
    r'(?:PACKAGE_[A-Z_]+|PRIVATE_NS|PROTECTED_[A-Z0-9_]*|EXPLICIT_NAMESPACE|STATIC_PROTECTED_NS)(?:::[A-Za-z0-9_$]+)?::'
)
_RE_NAMESPACE_QUOTED_CHAIN = re.compile(
    r'"(?:[A-Za-z_$][0-9A-Za-z_$.:]*::)+([A-Za-z_$][0-9A-Za-z_$]*)"'
)
_RE_NAMESPACE_CHAIN = re.compile(
    r'\b(?:[A-Za-z_$][0-9A-Za-z_$.:]*::)+([A-Za-z_$][0-9A-Za-z_$]*)\b'
)
_RE_NSSET_PREFIX = re.compile(r'\[NsSet\]::')
_RE_THIS_CONST_PREFIX = re.compile(r'\bthis\.([A-Z][A-Za-z0-9_]*)\b')
_SWITCH_TERNARY_VAR_RE = re.compile(r'===\s*([A-Za-z_$][0-9A-Za-z_$]*)\s*\?')
_SWITCH_TERNARY_CONST_RE = re.compile(
    r'([A-Za-z_$][0-9A-Za-z_$]*(?:\.[A-Za-z_$][0-9A-Za-z_$]*)?)\s*==='
)
_CONVERT_SUFFIX_TO_WRAPPER = {
    "i": "int",
    "u": "uint",
    "d": "Number",
    "s": "String",
    "o": "Object",
}
_RE_DUP_NEW_FIX = re.compile(
    r'(?m)^([ \t]*)([A-Za-z_$][0-9A-Za-z_$]*)\s*=\s*(\(\s*new[^\n;]+?\))\s*;\s*\n\1\3\.'
)
_RE_DUP_AS_FIX = re.compile(
    r'(?m)^([ \t]*)([A-Za-z_$][0-9A-Za-z_$]*)\s*=\s*(\(\s*new[^\n;]+?\s+as\s+[A-Za-z_$][0-9A-Za-z_$.]*\s*\))\s*;\s*\n\1([A-Za-z_$][0-9A-Za-z_$]*)\s*=\s*new\s+\2\s*\(\s*\)\s*;'
)
_RE_LOCAL_NEW_FIX = re.compile(
    r'(?m)^([ \t]*)([A-Za-z_$][0-9A-Za-z_$]*)\s*=\s*([A-Za-z_$][0-9A-Za-z_$]*)\s*;\s*\n\1\3\.read\(([^\n)]*)\);'
)
_RE_ELSE_IF = re.compile(r'\}\s*else\s*\{\s*if\s*\((.*?)\)\s*\{(.*?)\}\s*\}', re.DOTALL)
_RE_UNARY_PARENS = re.compile(r'\(\s*(\+\+[A-Za-z0-9_$]+|--[A-Za-z0-9_$]+|[A-Za-z0-9_$]+\+\+|[A-Za-z0-9_$]+--)\s*\)\s*;')
_RE_SELF_ASSIGN = re.compile(r'(?m)^\s*([A-Za-z_$][0-9A-Za-z_$]*)\s*=\s*\1\s*;\s*\n?')
_RE_EMITTER_COMMENT = re.compile(r'(?m)^\s*// method \d+ params=\d+ locals=\d+\s*\n?')
_RE_EMPTY_STATIC = re.compile(
    r'(?ms)^\s*private\s+static\s+function\s+__static_init__\(\)\s*\{\s*(?:(?:var\s+[^;]+;\s*)|(?://[^\n]*\n\s*)|(?:/\*.*?\*/\s*)|(?:\s*;\s*)|\s)*\}\s*\n?'
)
_RE_LITERAL_CAST_NUMERIC = re.compile(r'\b(?:int|uint|Number)\((-?\d+(?:\.\d+)?)\)')
_RE_SWITCH_TEMP_INLINE = re.compile(
    r'(?m)^([ \t]*)([A-Za-z_$][0-9A-Za-z_$]*)\s*=\s*([^;\n]+?)\s*;\s*\n\1switch\s*\(\2\)'
)
_RE_CASE_FALLTHROUGH_COMPACT = re.compile(
    r'(?m)^([ \t]*case\s+[^:\n]+:\s*)\n(?:(?:[ \t]*//[^\n]*\n)|(?:[ \t]*\n))+(?=[ \t]*case\s+)'
)
_RE_SWITCH_STATEMENT_LINE = re.compile(r'(?m)^(?P<indent>[ \t]*)switch\s*\(')
_RE_CASE_LABEL_LINE = re.compile(r'(?m)^(?P<indent>[ \t]*)(?:case\s+[^:\n]+|default)\s*:\s*$')
_RE_BREAK_LINE = re.compile(r'^\s*break\s*;\s*$')
_RE_POST_INCREMENT_LINE = re.compile(r'^\s*([A-Za-z_$][0-9A-Za-z_$]*)\s*\+\+\s*;\s*$')
_RE_NAMESPACE_NOISE_QUOTED = re.compile(
    r'"(?:PACKAGE|PRIVATE|PROTECTED|STATIC|EXPLICIT)[A-Z_0-9:]*::(?:.*?::)?([A-Za-z_$][A-Za-z0-9_$]*)"'
)
_RE_NAMESPACE_NOISE_UNQUOTED = re.compile(
    r'\b(?:PACKAGE|PRIVATE|PROTECTED|STATIC|EXPLICIT)[A-Z_0-9:]*::(?:.*?::)?([A-Za-z_$][A-Za-z0-9_$]*)\b'
)

_LEADING_WHITESPACE_RE = re.compile(r'^\s*')
_SAFE_NUMERIC_LITERAL_RE = re.compile(r'-?\d+(?:\.\d+)?')
_SAFE_STRING_LITERAL_RE = re.compile(r'"(?:[^"\\]|\\.)*"')
_SAFE_IDENTIFIER_CHAIN_RE = re.compile(r'[A-Za-z_$][0-9A-Za-z_$]*(?:\.[A-Za-z_$][0-9A-Za-z_$]*)*')
_SAFE_NEW_EXPR_RE = re.compile(r'new\s+[A-Za-z_$][0-9A-Za-z_$]*(?:\s*\(\s*\))?')

_DECL_PATTERN = re.compile(
    r'(?m)^(?P<indent>\s*)(?P<vis>public|private|protected|internal)\s+'
    r'(?P<static>static\s+)?(?P<kind>var|const)\s+'
    r'(?P<name>[A-Za-z_$][0-9A-Za-z_$]*)\s*:\s*(?P<type>[^=;\n]+?)'
    r'(?P<init>\s*=\s*[^;\n]+)?;\s*$'
)
_CTOR_PATTERN = re.compile(
    r'(?ms)(?P<head>public\s+function\s+[A-Za-z_$][0-9A-Za-z_$]*\s*\(\s*\)\s*\{\s*)'
    r'(?P<assign>(?:[ \t]*[A-Za-z_$][0-9A-Za-z_$]*\s*=\s*[^;]+;\s*)+)'
    r'(?P<super>[ \t]*super\(\);\s*)'
)
_ASSIGNMENT_PATTERN = re.compile(
    r'(?m)^(?P<indent>[ \t]*)(?P<name>[A-Za-z_$][0-9A-Za-z_$]*)\s*=\s*(?P<expr>[^;]+);\s*$'
)

_STATIC_INIT_MATCH_RE = re.compile(r'private static function __static_init__\(\) \{(.*?)\n\s*\}', re.DOTALL)
_STATIC_INIT_ASSIGNMENTS_RE = re.compile(r'^\s*([A-Za-z0-9_$]+)(?:\.\1)?\s*=\s*(.*?);', re.MULTILINE)
_STATIC_INIT_REMOVE_RE = re.compile(
    r'\s*// method \d+ params=0 locals=\d+\n\s*private static function __static_init__\(\) \{.*?\n\s*\}',
    re.DOTALL,
)
_CLASS_OPEN_RE = re.compile(r'(class\s+[A-Za-z0-9_$]+\s*\{)')
_PUBLIC_CLASS_HEADER_RE = re.compile(r'(?m)^(\s*public\s+class\s+[A-Za-z_$][0-9A-Za-z_$]*[^\{]*\{)')


@lru_cache(maxsize=256)
def _class_def_regex(old_name: str) -> re.Pattern[str]:
    return re.compile(r'(?m)^(\s*)class\s+' + re.escape(old_name) + r'\b')


@lru_cache(maxsize=256)
def _ctor_rename_regex(old_name: str) -> re.Pattern[str]:
    return re.compile(r'(\bfunction\s+)' + re.escape(old_name) + r'(\s*\()')

def _format_with_as3fmt(src: str) -> str:
    """Format AS3 text using the shared formatter and keep a trailing newline."""
    conf = ProcessorConfig(is_minify=False, comment_policy=CommentPolicy.ALL)
    formatted = AS3Processor(AS3Lexer(conf).tokenize(src), conf).run()
    return formatted + "\n"


def _slice_text(text: str, start: int, end: int | None = None) -> str:
    text_len = len(text)
    left = max(0, start)
    right = text_len if end is None else min(text_len, max(left, end))
    return "".join(text[index] for index in range(left, right))


def _find_text(text: str, needle: str, start: int = 0) -> int:
    token_len = len(needle)
    if token_len == 0:
        return max(0, min(start, len(text)))
    cursor = max(0, start)
    limit = len(text) - token_len
    while cursor <= limit:
        if _slice_text(text, cursor, cursor + token_len) == needle:
            return cursor
        cursor = cursor + 1
    return -1


def _char_at(text: str, index: int) -> str:
    if 0 <= index < len(text):
        return text[index]
    return ""


def sanitize_name(token: str, fallback: str = 'X') -> str:
    s = _SANITIZE_NON_IDENTIFIER_RE.sub('', str(token or '').strip())
    s = _SANITIZE_LEADING_DIGITS_RE.sub('', s)
    if not s: s = fallback
    if s and s[0].isdigit(): s = '_' + s
    if s in AS3_KW: s = s + '_'
    return s

def parse_package_and_class(raw_qname: str, fallback_cls: str) -> tuple[list[str], str]:
    raw_text = str(raw_qname or '').strip()
    if '::' in raw_text:
        parts = raw_text.split('::')
        cls_name = parts[-1]
        pkg_raw = parts[-2] if len(parts) > 1 else ""
    else:
        pkg_raw = ""
        cls_name = raw_text

    pkg_text = str(pkg_raw)
    pkg_parts: list[str] = []
    for seg in pkg_text.replace(':', '.').strip('.').split('.'):
        if not seg or seg == '*' or any(seg.upper().startswith(p) for p in META_PREFIXES):
            continue
        pkg_parts.append(sanitize_name(seg, 'pkg'))
    return pkg_parts, (cls_name or fallback_cls)

def infer_type(val_str: str, metadata_type: str) -> str:
    """Infer an AS3 type from assignment text and trait metadata."""
    # Normalize metadata type text (e.g. "http://...::int" -> "int").
    m_type = metadata_type.split('::')[-1] if '::' in metadata_type else metadata_type

    # Trust metadata when it is explicit (not wildcard).
    if m_type != '*':
        match m_type.lower():
            case 'int' | 'integer':
                return "int"
            case 'uint' | 'unsignedint':
                return "uint"
            case _:
                return m_type

    # Fallback inference from assignment expression text.
    v = val_str.strip()
    if v.startswith('[') or v.startswith('new Array'):
        return "Array"
    if v.startswith('"'):
        return "String"
    if v.startswith('0x'):
        return "uint"
    if v == "true" or v == "false":
        return "Boolean"

    digit_check = v.replace('-', '')
    if digit_check.isdigit():
        val_int = int(v)
        # Preserve legacy AS3 heuristic: values outside signed int32 are emitted as uint.
        if not (-2147483648 <= val_int <= 2147483647):
            return "uint"
        return "int"

    # Keep wildcard when inference is not reliable.
    # TODO: Migrate final type recovery to AST/data-flow analysis and remove string heuristics.
    return "*"

def _short_type_name(raw: object, fallback: str = "*") -> str:
    text = str(raw or "").strip()
    if not text:
        return fallback
    if text.startswith("[NsSet]::"):
        text = text.split("::", 1)[-1]
    text = _RE_NAMESPACE_PREFIX.sub("", text)
    if "::" in text:
        text = text.rsplit("::", 1)[-1]
    if text in {"*", "void"}:
        return text
    return sanitize_name(text, fallback)


def _trait_visibility(trait_name: object) -> str:
    text = str(trait_name or "").strip()
    if text.startswith("PRIVATE_NS::"):
        return "private"
    if text.startswith("PACKAGE_INTERNAL_NS::"):
        return "internal"
    if text.startswith("PROTECTED_NAMESPACE::") or text.startswith("STATIC_PROTECTED_NS::"):
        return "protected"
    return "public"


def _resolve_trait_type_name(trait: object, abc_obj: ABCFile) -> str:
    data = getattr(trait, "data", None)
    if not isinstance(data, dict):
        return "*"

    type_name = data.get("type_name")
    if type_name is None:
        return "*"

    raw: object
    if hasattr(type_name, "resolve"):
        raw = type_name.resolve(abc_obj.constant_pool, "multiname")
    else:
        raw = type_name
    return _short_type_name(raw, "*")


def _resolve_slot_default_literal(trait: object, abc_obj: ABCFile) -> str | None:
    data = getattr(trait, "data", None)
    if not isinstance(data, dict):
        return None

    value = data.get("value")
    if value is None:
        return None

    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)

    index = getattr(value, "value", None)
    value_kind_raw = data.get("value_kind")
    value_kind = getattr(value_kind_raw, "value", value_kind_raw)

    if isinstance(index, int) and isinstance(value_kind, int):
        try:
            kind = ConstantKind(value_kind)
        except ValueError:
            kind = None

        if kind == ConstantKind.UTF8:
            text = abc_obj.constant_pool.resolve_index(index, "string")
            escaped = str(text).replace("\\", "\\\\").replace('"', '\\"')
            return f'"{escaped}"'
        if kind == ConstantKind.INT:
            return str(abc_obj.constant_pool.resolve_index(index, "int"))
        if kind == ConstantKind.UINT:
            return str(abc_obj.constant_pool.resolve_index(index, "uint"))
        if kind == ConstantKind.DOUBLE:
            return str(abc_obj.constant_pool.resolve_index(index, "double"))
        if kind == ConstantKind.TRUE:
            return "true"
        if kind == ConstantKind.FALSE:
            return "false"
        if kind == ConstantKind.NULL:
            return "null"
        if kind == ConstantKind.UNDEFINED:
            return "undefined"

    return str(value)


def _collect_existing_member_names(src: str) -> set[str]:
    matches = _MEMBER_DECLARATION_NAME_RE.findall(src)
    return {sanitize_name(name, "X") for name in matches}


def _generate_member_declarations(
    instance_traits: list,
    class_traits: list,
    abc_obj: ABCFile,
    existing_names: set[str],
) -> str:
    lines: list[str] = []

    def _append(trait: object, *, is_static: bool) -> None:
        kind = getattr(trait, "kind", None)
        if kind not in (TraitKind.SLOT, TraitKind.CONST):
            return

        raw_name = getattr(trait, "name", "")
        name = sanitize_name(_short_type_name(raw_name, "field"), "field")
        if name in {"__static_init__", "prototype"}:
            return
        if name in existing_names:
            return

        type_name = _resolve_trait_type_name(trait, abc_obj)
        default_literal = _resolve_slot_default_literal(trait, abc_obj)
        static_kw = " static" if is_static else ""
        kind_kw = "const" if kind == TraitKind.CONST else "var"

        visibility = _trait_visibility(getattr(trait, "name", ""))
        line = f"      {visibility}{static_kw} {kind_kw} {name}:{type_name}"
        if default_literal is not None:
            line += f" = {default_literal}"
        line += ";"
        lines.append(line)
        # 添加到已声明集合，防止重复声明
        existing_names.add(name)

    for trait in instance_traits:
        _append(trait, is_static=False)
    for trait in class_traits:
        _append(trait, is_static=True)

    return "\n".join(lines)


def _build_implements_clause(interfaces: list[str]) -> str:
    names: list[str] = []
    seen: set[str] = set()
    for raw in interfaces:
        iface = _short_type_name(raw, "IInterface")
        if iface in seen:
            continue
        seen.add(iface)
        names.append(iface)
    if not names:
        return ""
    return " implements " + ", ".join(names)


def _extract_field_initializers_from_method_text(source: str, expected_owner: str) -> tuple[str, dict[str, str]]:
    match = _FIELD_INITIALIZERS_BLOCK_RE.search(source)
    if not match:
        return source, {}

    owner = match.group(1)
    if owner and expected_owner and owner != expected_owner:
        return source, {}

    payload_text = str(match.group(2) or "")

    extracted: dict[str, str] = {}
    for raw_line in payload_text.split("\n"):
        line_match = _FIELD_INITIALIZER_LINE_RE.match(raw_line)
        if not line_match:
            continue
        extracted[line_match.group(1)] = line_match.group(2)

    cleaned = source.replace(match.group(0), "", 1).strip()
    return cleaned, extracted


def _existing_imports(src: str) -> set[str]:
    found = _EXISTING_IMPORT_RE.findall(src)
    return {item.strip() for item in found if item.strip()}


_BUILTIN_IMPORTS: dict[str, str] = {
    "IDataInput": "flash.utils.IDataInput",
    "IDataOutput": "flash.utils.IDataOutput",
    "Dictionary": "flash.utils.Dictionary",
    "ByteArray": "flash.utils.ByteArray",
}


_ALLOWED_NAMESPACE_KINDS = {"PACKAGE_NAMESPACE", "PACKAGE_INTERNAL_NS"}


def _index_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    index = getattr(value, "value", None)
    if isinstance(index, int):
        return index
    return None


def _build_pool_auto_import_index(pool: object) -> dict[str, tuple[str, ...]]:
    multinames = getattr(pool, "multinames", None)
    if not isinstance(multinames, list):
        return {}

    resolve_index = getattr(pool, "resolve_index", None)
    if not callable(resolve_index):
        return {}

    by_name: dict[str, set[str]] = {}
    for multiname in multinames:
        data = getattr(multiname, "data", None)
        if not isinstance(data, dict):
            continue

        name_idx = _index_int(data.get("name"))
        ns_idx = _index_int(data.get("namespace"))
        if not isinstance(name_idx, int) or name_idx <= 0:
            continue
        if not isinstance(ns_idx, int) or ns_idx <= 0:
            continue

        try:
            member_name = str(resolve_index(name_idx, "string"))
            namespace_repr = str(resolve_index(ns_idx, "namespace"))
        except Exception:
            continue

        if not _ID_TOKEN_RE.fullmatch(member_name) or member_name in AS3_KW:
            continue

        namespace_kind, sep, package_name = namespace_repr.partition("::")
        if not sep or namespace_kind not in _ALLOWED_NAMESPACE_KINDS:
            continue
        if not package_name or package_name == "*" or package_name.startswith("http://"):
            continue

        fqcn = f"{package_name}.{member_name}"
        bucket = by_name.get(member_name)
        if bucket is None:
            by_name[member_name] = {fqcn}
        else:
            bucket.add(fqcn)

    return {name: tuple(sorted(values)) for name, values in by_name.items()}


def _pool_auto_import_index(pool: object) -> dict[str, tuple[str, ...]]:
    cached = getattr(pool, _POOL_AUTO_IMPORT_INDEX_ATTR, None)
    if isinstance(cached, dict):
        return cached

    built = _build_pool_auto_import_index(pool)
    try:
        setattr(pool, _POOL_AUTO_IMPORT_INDEX_ATTR, built)
    except Exception:
        pass
    return built


def _prefer_wildcard_import_for_package(pkg: str, classes: list[str]) -> bool:
    """Heuristic for choosing wildcard imports while preserving existing expectations."""
    if not classes:
        return False

    # Legacy post-processing behavior prefers wildcard for ByteArray-only utility imports.
    if pkg == "flash.utils":
        return len(classes) == 1 and classes[0] == "ByteArray"

    # Keep historical wildcard behavior for the common game.data package pair imports.
    if pkg == "game.data" and len(classes) >= 2:
        return True

    # Default policy: use wildcard only for larger package groups.
    return len(classes) >= 3


def _collect_auto_imports(
    src: str,
    abc_obj: ABCFile | None,
    *,
    current_class_name: str | None = None,
    current_fqcn: str | None = None,
) -> list[str]:
    type_refs = set(re.findall(r':\s*([A-Za-z_$][0-9A-Za-z_$]*)\b', src))

    call_targets = set(
        re.findall(
            r'\b(?:new\s+)?([A-Za-z_$][0-9A-Za-z_$]*)\s*\(',
            src,
        )
    )

    inheritance_refs: set[str] = set()
    for match in re.finditer(
        r'\b(?:extends|implements)\s+([A-Za-z_$][0-9A-Za-z_$]*(?:\s*,\s*[A-Za-z_$][0-9A-Za-z_$]*)*)',
        src,
    ):
        inheritance_refs.update(name.strip() for name in match.group(1).split(',') if name.strip())

    static_owner_refs = set(re.findall(r'\b([A-Z][A-Za-z0-9_$]*)\s*\.', src))

    words_in_src = (type_refs | call_targets | inheritance_refs | static_owner_refs) - set(AS3_KW)
    if current_class_name:
        words_in_src.discard(current_class_name)
    if not words_in_src:
        return []

    current_package = ""
    if current_fqcn and "." in current_fqcn:
        current_package = current_fqcn.rsplit(".", 1)[0]

    existing = _existing_imports(src)
    pkg_groups: dict[str, set[str]] = {}

    def _add_fqcn(fqcn: str) -> None:
        if not fqcn or "." not in fqcn:
            return
        pkg, cls = fqcn.rsplit(".", 1)
        if not pkg or not cls:
            return
        if current_fqcn and fqcn == current_fqcn:
            return
        if pkg == current_package:
            return
        bucket = pkg_groups.get(pkg)
        if bucket is None:
            pkg_groups[pkg] = {cls}
        else:
            bucket.add(cls)

    for word, fqcn in _BUILTIN_IMPORTS.items():
        if word in words_in_src:
            _add_fqcn(fqcn)

    if abc_obj is not None:
        pool = getattr(abc_obj, "constant_pool", None)
        if pool is not None:
            by_name = _pool_auto_import_index(pool)
            for member_name in words_in_src:
                for fqcn in by_name.get(member_name, ()):
                    _add_fqcn(fqcn)

    normalized: list[str] = []
    for pkg in sorted(pkg_groups):
        classes = sorted(pkg_groups[pkg])
        if not classes:
            continue

        if _prefer_wildcard_import_for_package(pkg, classes):
            import_path = f"{pkg}.*"
            if import_path not in existing:
                normalized.append(f"import {import_path};")
            continue

        for cls in classes:
            import_path = f"{pkg}.{cls}"
            if import_path in existing or f"{pkg}.*" in existing:
                continue
            normalized.append(f"import {import_path};")

    return normalized


def _inject_imports(src: str, imports: list[str]) -> str:
    if not imports:
        return src

    if _HAS_IMPORT_RE.search(src):
        lines = [str(line) for line in src.splitlines()]
        insert_at: int = 0
        for idx in range(len(lines)):
            line = lines[idx]
            if _IMPORT_LINE_RE.match(line):
                insert_at = idx + 1

        before = [lines[idx] for idx in range(0, insert_at)]
        after = [lines[idx] for idx in range(insert_at, len(lines))]
        updated = before + imports + after
        return "\n".join(updated)

    return "\n".join(imports) + "\n\n" + src


def _replace_unsupported_convert_expr(match: re.Match[str]) -> str:
    suffix = match.group(1)
    wrapper = _CONVERT_SUFFIX_TO_WRAPPER.get(suffix)
    if wrapper is None:
        return match.group(0)
    return f"{wrapper}({match.group(2)})"


def cleanup_namespace_noise(src: str) -> str:
    if "::" not in src:
        return src

    src = _RE_NSSET_PREFIX.sub("", src)
    src = _RE_NAMESPACE_PREFIX.sub("", src)
    src = _RE_NAMESPACE_NOISE_QUOTED.sub(r'"\1"', src)
    src = _RE_NAMESPACE_NOISE_UNQUOTED.sub(r'\1', src)

    while "::::" in src:
        src = src.replace("::::", "::")

    src = _RE_NAMESPACE_QUOTED_CHAIN.sub(r'"\1"', src)
    src = _RE_NAMESPACE_CHAIN.sub(r'\1', src)
    src = src.replace("::::length", ".length")
    if "::length" in src:
        src = src.replace("::length", ".length")
    return src


class SourcePostProcessor:
    """Apply source cleanup and import-injection rules for emitted AS3 text."""

    def __init__(
        self,
        abc_obj: ABCFile | None = None,
        *,
        current_class_name: str | None = None,
        current_package_parts: list[str] | tuple[str, ...] | None = None,
    ) -> None:
        self._abc_obj = abc_obj
        self._current_class_name = current_class_name
        self._current_package_parts = current_package_parts

    def process(self, src: str) -> str:
        return _post_process_source_logic_impl(
            src,
            self._abc_obj,
            current_class_name=self._current_class_name,
            current_package_parts=self._current_package_parts,
        )


def _post_process_source_logic(
    src: str,
    abc_obj: ABCFile | None = None,
    *,
    current_class_name: str | None = None,
    current_package_parts: list[str] | tuple[str, ...] | None = None,
) -> str:
    """Backward-compatible wrapper for source post-processing."""
    return SourcePostProcessor(
        abc_obj,
        current_class_name=current_class_name,
        current_package_parts=current_package_parts,
    ).process(src)


def _post_process_source_logic_impl(
    src: str,
    abc_obj: ABCFile | None = None,
    *,
    current_class_name: str | None = None,
    current_package_parts: list[str] | tuple[str, ...] | None = None,
) -> str:
    """
    Source-level compatibility cleanup.

    TODO: Incrementally migrate string/regex rewrites into AST semantic passes
    inside oven.transform.semantic_passes to reduce regex complexity and
    improve reliability on obfuscated sources.
    """
    def _find_matching_paren_index(text: str, paren_start: int) -> int:
        depth_stack: list[None] = []
        in_string: str | None = None
        in_line_comment = False
        in_block_comment = False
        i: int = paren_start

        while i < len(text):
            char = text[i]
            next_char = text[i + 1] if i + 1 < len(text) else ''

            if in_string is not None:
                if char == '\\':
                    i += 2
                    continue
                if char == in_string:
                    in_string = None
                i += 1
                continue

            if in_line_comment:
                if char in '\r\n':
                    in_line_comment = False
                i += 1
                continue

            if in_block_comment:
                if char == '*' and next_char == '/':
                    in_block_comment = False
                    i += 2
                    continue
                i += 1
                continue

            if char == '/' and next_char == '/':
                in_line_comment = True
                i += 2
                continue
            if char == '/' and next_char == '*':
                in_block_comment = True
                i += 2
                continue
            if char in {'"', "'"}:
                in_string = char
                i += 1
                continue

            if char == '(':
                depth_stack.append(None)
            elif char == ')':
                if depth_stack:
                    depth_stack.pop()
                if not depth_stack:
                    return i
            i += 1

        raise ValueError(f'unmatched switch paren at index {paren_start}')

    # 1) Fix redundant member access: name.name = -> name =
    if "." in src and "=" in src:
        src = _RE_REDUNDANT_MEMBER.sub(r'\1 =', src)

    # 2) Normalize void variants.
    if ":void" in src:
        src = _RE_VOID_VARIANT.sub(':void', src)

    # 3) Remove as_type_late marker noise.
    if "as_type_late" in src:
        src = _RE_AS_TYPE_LATE.sub('', src)

    # 3.1) Repair unsupported convert_* marker expressions.
    if "unsupported expr: convert_" in src:
        src = _RE_UNSUPPORTED_CONVERT.sub(_replace_unsupported_convert_expr, src)

    # 3.2) Remove AVM2 namespace prefix noise.
    if "::" in src:
        src = cleanup_namespace_noise(src)

    # 3.3) Remove redundant this. prefix for static constants.
    if "this." in src:
        src = _RE_THIS_CONST_PREFIX.sub(r"\1", src)

    # 3.4) Simplify redundant numeric literal wrappers.
    if "int(" in src or "uint(" in src or "Number(" in src:
        src = _RE_LITERAL_CAST_NUMERIC.sub(r'\1', src)

    # 3.5) Switch-related source rewrites (compatibility path).
    # NOTE: First-batch migration is now handled by AST semantic passes:
    #   - switch selector temp inlining
    #   - duplicate/new temp collapsing
    #   - else-if normalization
    # Keep only minimal switch text rewrites here for backwards compatibility.
    if "switch" in src and "===" in src and "?" in src:
        cursor: int = 0
        max_rewrites = 64
        for _attempt in range(max_rewrites):
            switch_idx = _find_text(src, "switch", cursor)
            if switch_idx < 0:
                break

            paren_start = _find_text(src, "(", switch_idx)
            if paren_start < 0:
                break

            try:
                paren_end = _find_matching_paren_index(src, paren_start)
            except ValueError:
                break

            expr = _slice_text(src, paren_start + 1, paren_end).strip()
            if not expr or "?" not in expr or "===" not in expr:
                cursor = paren_end + 1
                continue

            var_match = _SWITCH_TERNARY_VAR_RE.search(expr)
            if var_match is None:
                cursor = paren_end + 1
                continue
            switch_var = var_match.group(1)

            constants = _SWITCH_TERNARY_CONST_RE.findall(expr)
            if not constants:
                cursor = paren_end + 1
                continue

            brace_index = paren_end + 1
            while brace_index < len(src):
                current_char = _char_at(src, brace_index)
                if current_char not in {" ", "\t", "\r", "\n"}:
                    break
                brace_index = brace_index + 1
            if brace_index >= len(src) or _char_at(src, brace_index) != '{':
                cursor = paren_end + 1
                continue

            try:
                block_end = _find_matching_brace_span(src, brace_index)
            except ValueError:
                cursor = paren_end + 1
                continue

            switch_block = _slice_text(src, brace_index, block_end)
            for index, const_name in enumerate(constants):
                switch_block = re.sub(
                    rf'(?m)^(\s*)case\s+{index}\s*:',
                    rf'\1case {const_name}:',
                    switch_block,
                )

            # Remove ghost default case index left by ternary index reduction.
            default_idx = len(constants)
            switch_block = re.sub(
                rf'(?m)^[ \t]*case\s+{default_idx}\s*:\s*\n?',
                '',
                switch_block,
            )

            new_switch_head = _slice_text(src, switch_idx, paren_start) + f"({switch_var})"
            between_paren_and_brace = _slice_text(src, paren_end + 1, brace_index)
            src = (
                _slice_text(src, 0, switch_idx)
                + new_switch_head
                + between_paren_and_brace
                + switch_block
                + _slice_text(src, block_end)
            )
            cursor = switch_idx + len(new_switch_head) + len(between_paren_and_brace) + len(switch_block)

    # 3.6) Switch temp variable inline: tmp = expr; switch(tmp) -> switch(expr)
    if "switch" in src and "=" in src:
        src = _RE_SWITCH_TEMP_INLINE.sub(r'\1switch (\3)', src)

    # 3.7) Compact fallthrough case blocks.
    if "case" in src:
        old_src = ""
        while old_src != src:
            old_src = src
            src = _RE_CASE_FALLTHROUGH_COMPACT.sub(r'\1\n', src)

    # 3.8) Switched to AST semantic pass.
    # Keep source text unchanged here; canonicalization now happens in
    # oven.transform.semantic_passes.AstSemanticNormalizePass.

    # 4) Mitigate duplicate-new side effects with textual compatibility rewrites.
    if "new" in src:
        src = _RE_DUP_NEW_FIX.sub(r'\1\2 = \3;\n\1\2.', src)

    # 4.1) Collapse malformed temp-constructor chain into direct assignment.
    if " as " in src and "new" in src:
        src = _RE_DUP_AS_FIX.sub(r'\1\4 = \3;', src)

    # 5) Repair local class-instantiation fragments.
    if ".read(" in src and "=" in src:
        src = _RE_LOCAL_NEW_FIX.sub(r'\1\2 = new \3();\n\1\2.read(\4);', src)

    # 6) Merge else { if (...) { ... } } -> else if (...) { ... }
    if "else" in src and "if" in src:
        old_src = ""
        while old_src != src:
            old_src = src
            src = _RE_ELSE_IF.sub(r'} else if (\1) {\2}', src)

    # 7) Remove redundant parentheses around unary operators.
    if "++" in src or "--" in src:
        src = _RE_UNARY_PARENS.sub(r'\1;', src)

    # 8) Remove constructor self-assignment noise.
    if "=" in src:
        src = _RE_SELF_ASSIGN.sub('', src)

    # 9) Remove emitter method comments.
    if "// method" in src:
        src = _RE_EMITTER_COMMENT.sub('', src)

    # 10) Remove empty static initializer stubs.
    if "__static_init__" in src:
        src = _RE_EMPTY_STATIC.sub('', src)

    # 11) Auto-inject imports.
    fqcn: str | None = None
    if current_class_name and current_package_parts:
        package_name = ".".join(part for part in current_package_parts if part)
        if package_name:
            fqcn = f"{package_name}.{current_class_name}"
    imports = _collect_auto_imports(
        src,
        abc_obj,
        current_class_name=current_class_name,
        current_fqcn=fqcn,
    )
    src = _inject_imports(src, imports)
    return src



def _line_is_ignorable_for_tail(line: str) -> bool:
    stripped = line.strip()
    return not stripped or stripped.startswith("//")


def _rewrite_case_segment_tail_increment(segment: str) -> tuple[str, str | None, bool]:
    lines = segment.splitlines(keepends=True)
    if not lines:
        return segment, None, False

    last_meaningful = len(lines) - 1
    while last_meaningful >= 0 and _line_is_ignorable_for_tail(lines[last_meaningful]):
        last_meaningful -= 1

    if last_meaningful < 0:
        return segment, None, False

    if _RE_BREAK_LINE.match(lines[last_meaningful]) is None:
        return segment, None, False

    prev_meaningful = last_meaningful - 1
    while prev_meaningful >= 0 and _line_is_ignorable_for_tail(lines[prev_meaningful]):
        prev_meaningful -= 1

    if prev_meaningful < 0:
        return segment, None, True

    inc_match = _RE_POST_INCREMENT_LINE.match(lines[prev_meaningful])
    if inc_match is None:
        return segment, None, True

    lines[prev_meaningful] = ""
    return "".join(lines), inc_match.group(1), True


def _next_meaningful_line_is_post_increment(text: str, var_name: str) -> bool:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        match = _RE_POST_INCREMENT_LINE.match(stripped)
        return match is not None and match.group(1) == var_name
    return False


def _hoist_common_switch_post_increment(src: str) -> str:
    cursor: int = 0
    max_rewrites = 128

    for _attempt in range(max_rewrites):
        switch_match = _RE_SWITCH_STATEMENT_LINE.search(src, cursor)
        if switch_match is None:
            break

        switch_idx = switch_match.start()
        switch_indent = switch_match.group("indent")

        brace_index = src.find("{", switch_match.end())
        if brace_index < 0:
            cursor = switch_match.end()
            continue

        try:
            block_end = _find_matching_brace_span(src, brace_index)
        except ValueError:
            cursor = switch_match.end()
            continue

        switch_block = _slice_text(src, brace_index, block_end)
        if len(switch_block) < 2:
            cursor = block_end
            continue

        inner = _slice_text(switch_block, 1, len(switch_block) - 1)
        labels = list(_RE_CASE_LABEL_LINE.finditer(inner))
        if len(labels) < 2:
            cursor = block_end
            continue

        min_indent = min(len(match.group("indent")) for match in labels)
        top_labels = [match for match in labels if len(match.group("indent")) == min_indent]
        if len(top_labels) < 2:
            cursor = block_end
            continue

        prefix = _slice_text(inner, 0, top_labels[0].start())
        case_segments: list[str] = []
        for index, label in enumerate(top_labels):
            segment_start = label.start()
            segment_end = top_labels[index + 1].start() if index + 1 < len(top_labels) else len(inner)
            case_segments.append(_slice_text(inner, segment_start, segment_end))

        rewritten_segments: list[str] = []
        break_tail_inc_vars: list[str | None] = []
        inc_vars: set[str] = set()
        can_rewrite = True

        for segment in case_segments:
            rewritten, inc_var, has_break_tail = _rewrite_case_segment_tail_increment(segment)
            rewritten_segments.append(rewritten)
            if not has_break_tail:
                continue
            break_tail_inc_vars.append(inc_var)
            if inc_var is None:
                can_rewrite = False
                break
            inc_vars.add(inc_var)

        if not can_rewrite or len(break_tail_inc_vars) < 2 or len(inc_vars) != 1:
            cursor = block_end
            continue

        inc_var = next(iter(inc_vars))
        new_inner = prefix + "".join(rewritten_segments)
        if new_inner == inner:
            cursor = block_end
            continue

        new_switch_block = "{" + new_inner + "}"
        insertion = ""
        if not _next_meaningful_line_is_post_increment(_slice_text(src, block_end), inc_var):
            insertion = f"\n{switch_indent}{inc_var}++;"

        src = _slice_text(src, 0, brace_index) + new_switch_block + insertion + _slice_text(src, block_end)
        cursor = brace_index + len(new_switch_block) + len(insertion)

    return src


def _leading_indent(line: str) -> str:
    match = _LEADING_WHITESPACE_RE.match(line)
    return match.group(0) if match else ''


def _is_debuggable_source_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if stripped in {'{', '}'}:
        return False
    if stripped.startswith('//') or stripped.startswith('/*') or stripped.startswith('*'):
        return False
    return True


def _bucketize_debug_items(items: list[str], bucket_count: int) -> list[list[str]]:
    if bucket_count <= 0:
        return []

    buckets = [[] for _ in range(bucket_count)]
    if not items:
        return buckets

    item_count = len(items)
    for index, item in enumerate(items):
        bucket_index = min(bucket_count - 1, (index * bucket_count) // item_count)
        buckets[bucket_index].append(item)
    return buckets


def _find_matching_brace_span(text: str, brace_start: int) -> int:
    depth_stack: list[None] = []
    in_string: str | None = None
    in_line_comment = False
    in_block_comment = False
    i: int = brace_start

    while i < len(text):
        char = text[i]
        next_char = text[i + 1] if i + 1 < len(text) else ''

        if in_string is not None:
            if char == '\\':
                i += 2
                continue
            if char == in_string:
                in_string = None
            i += 1
            continue

        if in_line_comment:
            if char in '\r\n':
                in_line_comment = False
            i += 1
            continue

        if in_block_comment:
            if char == '*' and next_char == '/':
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue

        if char == '/' and next_char == '/':
            in_line_comment = True
            i += 2
            continue
        if char == '/' and next_char == '*':
            in_block_comment = True
            i += 2
            continue
        if char in {'"', "'"}:
            in_string = char
            i += 1
            continue

        if char == '{':
            depth_stack.append(None)
        elif char == '}':
            if depth_stack:
                depth_stack.pop()
            if not depth_stack:
                return i + 1
        i += 1

    raise ValueError(f'unmatched function brace at index {brace_start}')


def _find_function_spans(src: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    search_from = 0

    while True:
        match = _FUNCTION_SIGNATURE_RE.search(src, search_from)
        if match is None:
            break

        brace_start = _find_text(src, '{', match.end())
        if brace_start < 0:
            break

        block_end = _find_matching_brace_span(src, brace_start)
        spans.append((match.start(), block_end))
        search_from = block_end

    return spans


def _format_method_vm_comments(method_index: int, abc_obj: ABCFile) -> list[str]:
    body = abc_obj.method_body_at(method_index)
    if body is None:
        return []
    return [line.rstrip() for line in body.to_string(abc_obj.constant_pool, show_offsets=True).splitlines() if line.strip()]


def _annotate_function_block_with_vm_comments(function_src: str, method_index: int, vm_lines: list[str]) -> str:
    lines = function_src.splitlines()
    if not lines:
        return function_src

    annotated: list[str] = []
    signature_indent = _leading_indent(lines[0])
    annotated.append(f"{signature_indent}// vm: method {method_index} instructions={len(vm_lines)}")
    annotated.append(lines[0])

    candidate_indexes: list[int] = []
    for index in range(1, len(lines)):
        line = lines[index]
        if _is_debuggable_source_line(line):
            candidate_indexes.append(index)

    buckets = _bucketize_debug_items(vm_lines, len(candidate_indexes))
    bucket_by_line = {line_index: bucket for line_index, bucket in zip(candidate_indexes, buckets)}

    for index in range(1, len(lines)):
        line = lines[index]
        for vm_line in bucket_by_line.get(index, []):
            annotated.append(f"{_leading_indent(line)}// vm: {vm_line}")
        annotated.append(line)

    return '\n'.join(annotated)


def _annotate_source_with_vm_comments(src: str, method_indexes: list[int], abc_obj: ABCFile) -> str:
    spans = _find_function_spans(src)
    if not spans or not method_indexes:
        return src

    rendered: list[str] = []
    cursor = 0

    for span, method_index in zip(spans, method_indexes):
        start = int(span[0])
        end = int(span[1])
        rendered.append(_slice_text(src, cursor, start))
        rendered.append(
            _annotate_function_block_with_vm_comments(
                _slice_text(src, start, end),
                method_index,
                _format_method_vm_comments(method_index, abc_obj),
            )
        )
        cursor = end

    rendered.append(_slice_text(src, cursor))
    return ''.join(rendered)


def _is_safe_initializer_expression(expr: str) -> bool:
    token = expr.strip()
    if not token:
        return False
    if _SAFE_NUMERIC_LITERAL_RE.fullmatch(token):
        return True
    if _SAFE_STRING_LITERAL_RE.fullmatch(token):
        return True
    if token in {"true", "false", "null", "undefined", "[]"}:
        return True
    if _SAFE_IDENTIFIER_CHAIN_RE.fullmatch(token):
        return True
    if _SAFE_NEW_EXPR_RE.fullmatch(token):
        return True
    return False


def _lift_constructor_member_initializers(src: str) -> str:
    decl_state: dict[str, bool] = {}
    for m in _DECL_PATTERN.finditer(src):
        name = m.group("name")
        if m.group("static"):
            continue
        decl_state[name] = m.group("init") is not None

    if not decl_state:
        return src

    matched = _CTOR_PATTERN.search(src)
    if not matched:
        return src

    assign_block_text = str(matched.group("assign") or "")

    promoted: dict[str, str] = {}

    def _filter_assignment_line(line: str) -> str:
        m = _ASSIGNMENT_PATTERN.match(line)
        if not m:
            return line
        name = m.group("name")
        expr = m.group("expr").strip()
        has_init = decl_state.get(name)
        if has_init is None:
            return line
        if has_init:
            return line
        if not _is_safe_initializer_expression(expr):
            return line
        promoted[name] = expr
        decl_state[name] = True
        return ""

    kept_lines: list[str] = []
    for raw_line in assign_block_text.splitlines(keepends=True):
        kept = _filter_assignment_line(raw_line)
        if kept:
            kept_lines.append(kept)

    if not promoted:
        return src

    rebuilt_ctor = matched.group("head") + "".join(kept_lines) + matched.group("super")
    src = _slice_text(src, 0, matched.start()) + rebuilt_ctor + _slice_text(src, matched.end())

    def _inject_decl_init(m: re.Match[str]) -> str:
        name = m.group("name")
        init = m.group("init")
        if init is not None:     
            return m.group(0)
        expr = promoted.get(name)
        if expr is None:
            return m.group(0)
        return (
            f"{m.group('indent')}{m.group('vis')} "
            f"{m.group('static') or ''}{m.group('kind')} "
            f"{name}:{m.group('type')} = {expr};"
        )

    src = _DECL_PATTERN.sub(_inject_decl_init, src)
    return src


def lift_static_initializers(source: str, class_traits: list[Any], abc_obj: ABCFile) -> str:
    """Lift __static_init__ assignments into typed static member declarations."""
    init_match = _STATIC_INIT_MATCH_RE.search(source)
    if not init_match:
        return source

    init_body = init_match.group(1)
    assignments = _STATIC_INIT_ASSIGNMENTS_RE.findall(init_body)
    if not assignments:
        return source

    trait_map: dict[str, Any] = {}
    for trait in class_traits:
        kind = getattr(trait, "kind", None)
        if kind not in (TraitKind.SLOT, TraitKind.CONST):
            continue
        trait_name = sanitize_name(str(getattr(trait, "name", "")), "field")
        trait_map[trait_name] = trait

    declarations: list[str] = []
    processed_names: set[str] = set()

    for name, value in assignments:
        if name in processed_names:
            continue

        trait = trait_map.get(name)
        trait_kind = getattr(trait, "kind", None)
        is_const = "const" if (trait is None or trait_kind == TraitKind.CONST) else "var"

        raw_metadata_type = "*"
        trait_data = getattr(trait, "data", None)
        if isinstance(trait_data, dict) and 'type_name' in trait_data:
            tn = trait_data['type_name']
            if hasattr(tn, 'resolve'):
                raw_metadata_type = str(tn.resolve(abc_obj.constant_pool, 'multiname'))
            else:
                raw_metadata_type = str(tn)

        real_type = infer_type(value, raw_metadata_type)
        declarations.append(f"      public static {is_const} {name}:{real_type} = {value};")
        processed_names.add(name)

    source = _STATIC_INIT_REMOVE_RE.sub('', source)

    decl_block = "\n".join(declarations) + "\n"
    source = _CLASS_OPEN_RE.sub(r'\1\n' + decl_block, source)

    return source

def fix_source_structure(
    src: str,
    old_name: str,
    new_name: str,
    pkg_parts: list[str],
    instance_traits: list,
    class_traits: list,
    interfaces: list[str],
    abc_obj: ABCFile,
) -> str:
    # 1. Lift static initializers and recover declaration types.
    src = lift_static_initializers(src, class_traits, abc_obj)

    # 2. Generate and inject missing member declarations.
    existing = _collect_existing_member_names(src)
    member_decls = _generate_member_declarations(instance_traits, class_traits, abc_obj, existing)

    # 3. Normalize class modifiers and implements clause.
    implements_clause = _build_implements_clause(interfaces)
    class_def_pattern = _class_def_regex(old_name)
    src = class_def_pattern.sub(
        r'\1public class ' + new_name + implements_clause,
        src,
        count=1,
    )

    # 4. Rename constructor when class name changed.
    if old_name != new_name:
        ctor_pattern = _ctor_rename_regex(old_name)
        src = ctor_pattern.sub(r'\1' + new_name + r'\2', src)

    # 5. Insert generated member declarations at class-body start.
    if member_decls:
        src = _PUBLIC_CLASS_HEADER_RE.sub(r'\1\n' + member_decls + '\n', src, count=1)

    # 6. Post-process source text (including import auto-injection).
    src = SourcePostProcessor(
        abc_obj,
        current_class_name=new_name,
        current_package_parts=pkg_parts,
    ).process(src)

    # 7. Lift simple constructor field initializers into declarations.
    src = _lift_constructor_member_initializers(src)

    # 8. Wrap in package block and run shared AS3 formatter.
    if pkg_parts:
        pkg_header = f"package {'.'.join(pkg_parts)}"
    else:
        pkg_header = "package"
    wrapped = f'{pkg_header}\n{{\n{src}\n}}\n'
    return _format_with_as3fmt(wrapped)

def _allocate_unique_class_name(
    *,
    pkg_parts: list[str],
    base_class_name: str,
    identity_counters: dict[str, int],
    used_rel_paths: set[str],
) -> str:
    """Allocate a unique class name and avoid duplicate output paths."""
    pkg_key = ".".join(pkg_parts)
    identity_key = f"{pkg_key}::{base_class_name}".lower()
    suffix = identity_counters.get(identity_key, 0)

    while True:
        candidate = base_class_name if suffix == 0 else f"{base_class_name}_{suffix}"
        rel_key = str((Path(*pkg_parts) / f"{candidate}.as")).replace('\\', '/').lower()
        if rel_key not in used_rel_paths:
            used_rel_paths.add(rel_key)
            identity_counters[identity_key] = suffix + 1
            return candidate
        suffix += 1

    raise RuntimeError("unreachable unique-class allocation path")


_PARALLEL_WORKER_STATE: dict[str, Any] = {}


def _render_single_class_layout_block(
    abc: ABCFile,
    owner_map: dict[int, Any],
    class_index: int,
    *,
    style: str,
    int_format: str,
    inline_vars: bool,
) -> tuple[int, str, str]:
    package_parts, class_name, entries = _collect_class_method_entries(abc, class_index)
    instance = abc.instances[class_index] if class_index < len(abc.instances) else None
    cls = abc.classes[class_index] if class_index < len(abc.classes) else None
    class_signature = _build_class_signature(class_name, instance)
    lines = [f"{class_signature} {{"]

    field_initializers: dict[str, str] = {}
    rendered_methods: list[tuple[object, object, object, str, str]] = []

    for entry in entries:
        method_index = entry.method_index
        if not (0 <= method_index < len(abc.methods)):
            continue
        body = abc.method_body_at(method_index)
        if body is None:
            continue

        method_info = abc.methods[method_index]
        context: Any = None
        method_text = ""

        try:
            context = _build_method_context(abc, body, owner_map)
            fast_text = _try_fast_emit_method_text(body, context, int_format=int_format)
            if fast_text is not None:
                method_text = fast_text
            else:
                nf, context = _build_method_ir(
                    body,
                    style=style,
                    abc=abc,
                    owner_map=owner_map,
                    method_context=context,
                )
                nf, extracted = _extract_method_field_initializers(
                    nf,
                    style=style,
                    method_context=context,
                    int_format=int_format,
                )
                if entry.is_constructor:
                    for name, value in extracted.items():
                        if isinstance(name, str) and isinstance(value, str) and name not in field_initializers:
                            field_initializers[name] = value
                method_text = AS3Emitter(
                    style=style,
                    method_context=context,
                    int_format=int_format,
                    inline_vars=inline_vars,
                ).emit(nf).strip()
        except Exception as exc:  # pragma: no cover - defensive fallback
            method_text = f"/* decompile_error: {exc.__class__.__name__}: {exc} */"

        signature = _render_layout_method_signature(
            class_name=class_name,
            entry=entry,
            method_info=method_info,
            context=context,
        )
        rendered_methods.append((entry, body, method_info, signature, method_text))

    member_lines, _declared_members = _build_class_member_lines(
        abc,
        instance_traits=list(getattr(instance, "traits", [])) if instance is not None else [],
        class_traits=list(getattr(cls, "traits", [])) if cls is not None else [],
        constructor_initializers=field_initializers,
    )
    if member_lines:
        lines.extend(member_lines)
        lines.append("")

    if not rendered_methods:
        lines.append("    // no resolvable methods")
        lines.append("}")
        return class_index, class_name, "\n".join(lines)

    for index, (entry, body, method_info, signature, method_text) in enumerate(rendered_methods):
        lines.append(
            f"    // method {entry.method_index} "
            f"params={len(method_info.params)} "
            f"locals={body.num_locals}"
        )
        lines.append(f"    {signature} {{")
        if method_text:
            for raw in method_text.splitlines():
                lines.append(f"        {raw}")
        else:
            lines.append("        // empty")
        lines.append("    }")
        if index < len(rendered_methods) - 1:
            lines.append("")

    lines.append("}")
    return class_index, class_name, "\n".join(lines)


def _parallel_worker_init(
    abc_data: bytes,
    style: str,
    int_format: str,
    inline_vars: bool,
) -> None:
    abc = parse(abc_data, mode=ParseMode.RELAXED)
    _PARALLEL_WORKER_STATE["abc"] = abc
    _PARALLEL_WORKER_STATE["owner_map"] = _build_method_owner_map(abc)
    _PARALLEL_WORKER_STATE["style"] = style
    _PARALLEL_WORKER_STATE["int_format"] = int_format
    _PARALLEL_WORKER_STATE["inline_vars"] = inline_vars


def _parallel_render_class_block(class_index: int) -> tuple[int, str, str]:
    abc = _PARALLEL_WORKER_STATE.get("abc")
    owner_map = _PARALLEL_WORKER_STATE.get("owner_map")
    style = _PARALLEL_WORKER_STATE.get("style")
    int_format = _PARALLEL_WORKER_STATE.get("int_format")
    inline_vars = _PARALLEL_WORKER_STATE.get("inline_vars")
    if not isinstance(abc, ABCFile) or not isinstance(owner_map, dict):
        raise RuntimeError("parallel worker is not initialized")

    owner_map_typed = cast(dict[int, Any], owner_map)
    return _render_single_class_layout_block(
        abc,
        owner_map_typed,
        class_index,
        style=str(style),
        int_format=str(int_format),
        inline_vars=bool(inline_vars),
    )


def decompile_abc_to_as_files(
    abc_path: str | Path,
    output_dir: str | Path = "out/scripts",
    style: str = "semantic",
    int_format: str = "hex",
    inline_vars: bool = True,
    clean_output: bool = True,
    debug: bool = False,
    *,
    parallel: bool = False,
    max_workers: int | None = None,
    auto_disable_parallel_in_pypy: bool = True,
) -> list[Path]:
    abc_file = Path(abc_path)
    abc_data = abc_file.read_bytes()
    abc = parse(abc_data, mode=ParseMode.RELAXED)
    out_root = Path(output_dir)

    if clean_output and out_root.exists():
        # Safe cleanup: remove only generated .as files under output root.
        for as_file in out_root.rglob("*.as"):
            as_file.unlink(missing_ok=True)
        # Best-effort cleanup of now-empty directories (deepest first).
        for folder in sorted((p for p in out_root.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
            try:
                folder.rmdir()
            except OSError:
                pass
    out_root.mkdir(parents=True, exist_ok=True)

    # Auto-disable parallel processing in PyPy environment
    is_pypy = platform.python_implementation() == "PyPy"
    effective_parallel = parallel and not is_pypy
    
    if is_pypy and parallel:
        print("[!] Parallel processing disabled in PyPy environment (poor performance)")
        print(f"[*] Python implementation: {platform.python_implementation()}")
        print(f"[*] Parallel requested: {parallel}")
        print(f"[*] Effective parallel: {effective_parallel}")
    elif parallel:
        print(f"[*] Parallel processing enabled")
        print(f"[*] Python implementation: {platform.python_implementation()}")

    class_count = min(len(abc.instances), len(abc.classes))
    use_process_parallel = effective_parallel and class_count >= 32
    worker_count = max_workers if max_workers is not None else min(8, os.cpu_count() or 1)
    worker_count = max(1, int(worker_count))
    
    print(f"[*] Class count: {class_count}")
    print(f"[*] Worker count: {worker_count}")
    print(f"[*] Use process parallel: {use_process_parallel}")
    print(f"[*] Auto-disable in PyPy: {auto_disable_parallel_in_pypy}")

    class_blocks: list[tuple[int, str, str]] = []
    if use_process_parallel and worker_count > 1:
        try:
            chunk_size = max(1, class_count // (worker_count * 4))
            with ProcessPoolExecutor(
                max_workers=worker_count,
                initializer=_parallel_worker_init,
                initargs=(abc_data, style, int_format, inline_vars),
            ) as executor:
                for item in executor.map(
                    _parallel_render_class_block,
                    range(class_count),
                    chunksize=chunk_size,
                ):
                    class_blocks.append(item)
            class_blocks.sort(key=lambda item: item[0])
        except Exception:
            class_blocks.clear()

    if not class_blocks:
        owner_map = _build_method_owner_map(abc)
        blocks = [
            b
            for b in _decompile_abc_classes_layout_blocks(
                abc,
                style=style,
                int_format=int_format,
                owner_map=owner_map,
                inline_vars=inline_vars,
            )
            if b.kind == 'class'
        ]
        class_blocks = [(i, block.class_name, block.source) for i, block in enumerate(blocks)]

    tasks: list[tuple[int, str, str, Any | None, Any | None, list[str], str]] = []
    name_collision_tracker: dict[str, int] = {}
    used_output_rel_paths: set[str] = set()

    for i, block_name, block_source in class_blocks:
        instance = abc.instances[i] if i < len(abc.instances) else None
        class_info = abc.classes[i] if i < len(abc.classes) else None
        raw_name = str(instance.name) if instance else block_name

        pkg_parts, raw_cls = parse_package_and_class(raw_name, block_name)
        base_class_name = sanitize_name(raw_cls, f"Class{i}")

        final_class_name = _allocate_unique_class_name(
            pkg_parts=pkg_parts,
            base_class_name=base_class_name,
            identity_counters=name_collision_tracker,
            used_rel_paths=used_output_rel_paths,
        )
        tasks.append((i, block_name, block_source, instance, class_info, pkg_parts, final_class_name))

    def _render_task(
        index: int,
        block_name: str,
        block_source: str,
        instance_obj: Any | None,
        class_info_obj: Any | None,
        package_parts: list[str],
        class_name: str,
    ) -> tuple[int, Path, str]:
        final_code = fix_source_structure(
            block_source,
            block_name,
            class_name,
            package_parts,
            list(getattr(instance_obj, "traits", [])) if instance_obj is not None else [],
            list(getattr(class_info_obj, "traits", [])) if class_info_obj is not None else [],
            list(getattr(instance_obj, "interfaces", [])) if instance_obj is not None else [],
            abc,
        )

        if debug:
            _package_parts, _class_name, entries = _collect_class_method_entries(abc, index)
            debug_method_indexes = [
                entry.method_index
                for entry in entries
                if entry.method_name != '__static_init__' and abc.method_body_at(entry.method_index) is not None
            ]
            final_code = _annotate_source_with_vm_comments(final_code, debug_method_indexes, abc)

        rel_path = Path(*package_parts) / f"{class_name}.as"
        return index, rel_path, final_code

    post_parallel = parallel and len(tasks) > 1 and not use_process_parallel

    rendered: list[tuple[int, Path, str]] = []
    if post_parallel:
        with ThreadPoolExecutor(max_workers=max(1, min(worker_count, 16))) as executor:
            submit = cast(Any, executor.submit)
            futures: list[Any] = []
            for i, block_name, block_source, instance, class_info, pkg_parts, class_name in tasks:
                futures.append(submit(_render_task, i, block_name, block_source, instance, class_info, pkg_parts, class_name))
            for future in futures:
                rendered.append(future.result())
    else:
        for i, block_name, block_source, instance, class_info, pkg_parts, class_name in tasks:
            rendered.append(_render_task(i, block_name, block_source, instance, class_info, pkg_parts, class_name))

    rendered.sort(key=lambda item: item[0])

    written_files: list[Path] = []
    for _index, rel_path, final_code in rendered:
        target_file = out_root / rel_path
        target_file.parent.mkdir(parents=True, exist_ok=True)
        target_file.write_text(final_code, encoding='utf-8')
        written_files.append(target_file)

    print(f"[*] Successfully exported {len(written_files)} classes.")

    return written_files

if __name__ == "__main__":
    import sys

    args: list[str] = []
    for index, arg in enumerate(sys.argv):
        if index == 0:
            continue
        args.append(arg)

    debug = False
    if '--debug' in args:
        args = [arg for arg in args if arg != '--debug']
        debug = True

    target_abc = args[0] if len(args) > 0 else None
    decompile_abc_to_as_files(target_abc, debug=debug)
