from __future__ import annotations
from oven.api.formatter import CommentPolicy, ProcessorConfig, AS3Lexer, AS3Processor

def _run(raw_code: str, *, is_minify: bool) -> str:
    config = ProcessorConfig(is_minify=is_minify, comment_policy=CommentPolicy.ALL)
    tokens = AS3Lexer(config).tokenize(raw_code)
    return AS3Processor(tokens, config).run()
def test_format_keeps_leading_single_line_comment_without_spurious_semicolon() -> None:
    raw_code = '// leading comment\nvar a:int=1;'
    out = _run(raw_code, is_minify=False)
    assert out == '// leading comment\nvar a:int = 1;'
    assert '// leading comment;' not in out
def test_minify_adds_statement_separator_after_leading_single_line_comment() -> None:
    raw_code = '//! leading comment\nvar a:int=1;'
    out = _run(raw_code, is_minify=True)
    assert out == '//! leading comment;\nvar a:int=1;'
def test_format_keeps_leading_block_comment_without_spurious_semicolon() -> None:
    raw_code = '/* @license MIT */\nvar a:int=1;'
    out = _run(raw_code, is_minify=False)
    assert out == '/* @license MIT */\nvar a:int = 1;'
    assert '/* @license MIT */;' not in out
def test_minify_keeps_leading_block_comment_without_spurious_semicolon() -> None:
    raw_code = '/* @license MIT */\nvar a:int=1;'
    out = _run(raw_code, is_minify=True)
    assert out == '/* @license MIT */var a:int=1;'
    assert '/* @license MIT */;' not in out
def test_comment_immediately_followed_by_code_has_no_spurious_semicolon() -> None:
    raw_code = '/* @license MIT */var a:int=1;'
    out_format = _run(raw_code, is_minify=False)
    out_minify = _run(raw_code, is_minify=True)
    assert out_format == '/* @license MIT */\nvar a:int = 1;'
    assert out_minify == '/* @license MIT */var a:int=1;'
    assert '/* @license MIT */;' not in out_format
    assert '/* @license MIT */;' not in out_minify
def test_minify_single_line_license_comment_is_separated_from_following_code() -> None:
    raw_code = '// @license MIT\npackage demo{var a:int=1;}'
    out = _run(raw_code, is_minify=True)
    assert out.startswith('// @license MIT;\npackage demo')
