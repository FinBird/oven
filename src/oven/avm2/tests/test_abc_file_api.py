"""
ABCFile API tests (TDD for milestone M1).
"""
from pathlib import Path
import pytest
from oven.avm2 import parse_abc
from oven.avm2.constant_pool import ConstantPool, Multiname, NamespaceInfo
from oven.avm2.file import ABCFile
from oven.avm2.methods import MethodBody, MethodFlags, MethodInfo
from oven.avm2.enums import Index, MultinameKind, NamespaceKind
def _empty_pool() -> ConstantPool:
    return ConstantPool(ints=[], uints=[], doubles=[], strings=[], namespaces=[], namespace_sets=[], multinames=[])
def _body(method_index: int) -> MethodBody:
    return MethodBody(method=method_index, max_stack=0, num_locals=0, init_scope_depth=0, max_scope_depth=0, code=b'', exceptions=[], traits=[], instructions=[])
def _method(name: str='') -> MethodInfo:
    return MethodInfo(name=name, params=[], return_type='*', flags=MethodFlags.NONE)
def _fixture_path(name: str) -> Path:
    # The fixtures directory is at the project root, not under src
    return Path(__file__).resolve().parents[4] / 'fixtures' / 'abc' / name
def test_method_body_at_returns_body_for_valid_method_index() -> None:
    abc = ABCFile(minor_version=16, major_version=46, constant_pool=_empty_pool(), methods=[_method('m0'), _method('m1'), _method('m2')], metadata=[], instances=[], classes=[], scripts=[], method_bodies=[_body(0), _body(2)])
    body = abc.method_body_at(2)
    assert body is not None
    assert body.method == 2
def test_method_body_at_returns_none_for_missing_method_index() -> None:
    abc = ABCFile(minor_version=16, major_version=46, constant_pool=_empty_pool(), methods=[_method('m0'), _method('m1')], metadata=[], instances=[], classes=[], scripts=[], method_bodies=[_body(0)])
    assert abc.method_body_at(1) is None
def test_method_body_at_rejects_negative_index() -> None:
    abc = ABCFile(minor_version=16, major_version=46, constant_pool=_empty_pool(), methods=[_method('m0')], metadata=[], instances=[], classes=[], scripts=[], method_bodies=[_body(0)])
    with pytest.raises(ValueError):
        abc.method_body_at(-1)
def test_abcfile_decompile_forwards_inline_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    abc = ABCFile(minor_version=16, major_version=46, constant_pool=_empty_pool(), methods=[_method('m0')], metadata=[], instances=[], classes=[], scripts=[], method_bodies=[_body(0)])
    captured: dict[str, object] = {}
    def _fake_decompile(parsed_abc: ABCFile, *, method_idx: int | None=None, style: str='semantic', layout: str='methods', int_format: str='dec', inline_vars: bool=False) -> str:
        captured.update({'abc': parsed_abc, 'method_idx': method_idx, 'style': style, 'layout': layout, 'int_format': int_format, 'inline_vars': inline_vars})
        return 'ok'
    import oven.avm2.decompiler as decompiler
    monkeypatch.setattr(decompiler, '_decompile_abc_parsed', _fake_decompile)
    rendered = abc.decompile(method_idx=0, style='semantic', layout='methods', int_format='hex', inline_vars=True)
    assert rendered == 'ok'
    assert captured['abc'] is abc
    assert captured['method_idx'] == 0
    assert captured['style'] == 'semantic'
    assert captured['layout'] == 'methods'
    assert captured['int_format'] == 'hex'
    assert captured['inline_vars'] is True
def test_abcfile_decompile_to_files_forwards_inline_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    abc = ABCFile(minor_version=16, major_version=46, constant_pool=_empty_pool(), methods=[_method('m0')], metadata=[], instances=[], classes=[], scripts=[], method_bodies=[_body(0)])
    captured: dict[str, object] = {}
    def _fake_decompile_to_files(parsed_abc: ABCFile, output_dir: str | Path, *, style: str='semantic', int_format: str='dec', clean_output: bool=True, inline_vars: bool=False, insert_debug_comments: bool=False) -> list[Path]:
        captured.update({'abc': parsed_abc, 'output_dir': output_dir, 'style': style, 'int_format': int_format, 'clean_output': clean_output, 'inline_vars': inline_vars, 'insert_debug_comments': insert_debug_comments})
        return [Path(output_dir) / 'Demo.as']
    import oven.avm2.decompiler as decompiler
    monkeypatch.setattr(decompiler, '_decompile_abc_parsed_to_files', _fake_decompile_to_files)
    written = abc.decompile_to_files('out', style='semantic', int_format='hex', clean_output=False, inline_vars=True)
    assert written == [Path('out') / 'Demo.as']
    assert captured['abc'] is abc
    assert captured['output_dir'] == 'out'
    assert captured['style'] == 'semantic'
    assert captured['int_format'] == 'hex'
    assert captured['clean_output'] is False
    assert captured['inline_vars'] is True
    assert captured['insert_debug_comments'] is False
def test_fix_names_sanitizes_invalid_identifier_parts() -> None:
    pool = ConstantPool(ints=[], uints=[], doubles=[], strings=['123foo.-bar.baz!', '9@bad-name'], namespaces=[NamespaceInfo(NamespaceKind.NAMESPACE, 1)], namespace_sets=[], multinames=[Multiname(MultinameKind.QNAME, {'namespace': Index(0), 'name': Index(2)})])
    abc = ABCFile(minor_version=16, major_version=46, constant_pool=pool, methods=[], metadata=[], instances=[], classes=[], scripts=[], method_bodies=[])
    abc.fix_names()
    assert abc.constant_pool.strings[0] == 'foo.bar.baz'
    assert abc.constant_pool.strings[1] == 'badname'
def test_fix_names_keeps_http_namespace_unchanged() -> None:
    pool = ConstantPool(ints=[], uints=[], doubles=[], strings=['http://example.com/ns.path'], namespaces=[NamespaceInfo(NamespaceKind.NAMESPACE, 1)], namespace_sets=[], multinames=[])
    abc = ABCFile(minor_version=16, major_version=46, constant_pool=pool, methods=[], metadata=[], instances=[], classes=[], scripts=[], method_bodies=[])
    abc.fix_names()
    assert abc.constant_pool.strings[0] == 'http://example.com/ns.path'
def test_fix_names_renames_keywords_and_deduplicates_with_i_suffix() -> None:
    pool = ConstantPool(ints=[], uints=[], doubles=[], strings=['for', 'for'], namespaces=[NamespaceInfo(NamespaceKind.NAMESPACE, 1), NamespaceInfo(NamespaceKind.NAMESPACE, 2)], namespace_sets=[], multinames=[])
    abc = ABCFile(minor_version=16, major_version=46, constant_pool=pool, methods=[], metadata=[], instances=[], classes=[], scripts=[], method_bodies=[])
    abc.fix_names()
    assert abc.constant_pool.strings[0] == 'for_i0'
    assert abc.constant_pool.strings[1] == 'for_i1'
def test_fix_names_skips_empty_and_star_entries() -> None:
    pool = ConstantPool(ints=[], uints=[], doubles=[], strings=['', '*'], namespaces=[NamespaceInfo(NamespaceKind.NAMESPACE, 1), NamespaceInfo(NamespaceKind.NAMESPACE, 2)], namespace_sets=[], multinames=[Multiname(MultinameKind.QNAME, {'namespace': Index(0), 'name': Index(1)}), Multiname(MultinameKind.QNAME, {'namespace': Index(0), 'name': Index(2)})])
    abc = ABCFile(minor_version=16, major_version=46, constant_pool=pool, methods=[], metadata=[], instances=[], classes=[], scripts=[], method_bodies=[])
    abc.fix_names()
    assert abc.constant_pool.strings[0] == ''
    assert abc.constant_pool.strings[1] == '*'
def test_to_dict_returns_complete_top_level_structure_for_parsed_fixture() -> None:
    abc = parse_abc(_fixture_path('Test.abc').read_bytes())
    serialized = abc.to_dict()
    assert set(serialized.keys()) == {'minor_version', 'major_version', 'constant_pool', 'methods', 'metadata', 'instances', 'classes', 'scripts', 'method_bodies'}
    assert serialized['major_version'] == abc.major_version
    assert serialized['minor_version'] == abc.minor_version
    assert isinstance(serialized['constant_pool'], dict)
    assert len(serialized['methods']) == len(abc.methods)
    assert len(serialized['method_bodies']) == len(abc.method_bodies)
    assert len(serialized['instances']) == len(abc.instances)
    assert len(serialized['classes']) == len(abc.classes)
    assert len(serialized['scripts']) == len(abc.scripts)
def test_to_dict_resolve_flag_preserves_shape_and_method_body_links() -> None:
    abc = parse_abc(_fixture_path('Test.abc').read_bytes())
    unresolved = abc.to_dict(resolve=False)
    resolved = abc.to_dict(resolve=True)
    for key in ('methods', 'metadata', 'instances', 'classes', 'scripts', 'method_bodies'):
        assert len(unresolved[key]) == len(resolved[key])
    method_body_indices = {body.method for body in abc.method_bodies}
    for method in resolved['methods']:
        linked_body = method['body']
        if linked_body is None:
            continue
        assert linked_body in method_body_indices
