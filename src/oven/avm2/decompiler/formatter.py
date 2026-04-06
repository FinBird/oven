"""AS3 source formatting ( lexer + pretty-printer / minify )."""

import re
import time
from dataclasses import dataclass
from enum import IntEnum
from itertools import chain, islice
from typing import List, cast


class CommentPolicy(IntEnum):
    ALL = 1
    NONE = 2
    IMPORTANT = 3


@dataclass(slots=True)
class ProcessorConfig:
    is_minify: bool = False
    indent_size: int = 4
    comment_policy: CommentPolicy = CommentPolicy.IMPORTANT
    preserve_e4x_whitespace: bool = True


class TokenType(IntEnum):
    WHITESPACE = 1
    COMMENT = 2
    STRING = 3
    NUMBER = 4
    KEYWORD = 5
    IDENTIFIER = 6
    OPERATOR = 7
    PUNCTUATION = 8
    REGEX = 9
    XML = 10


@dataclass(slots=True)
class Token:
    type: TokenType
    value: str
    is_important_comment: bool = False


class AS3Lexer:
    KEYWORDS = {
        "package",
        "class",
        "interface",
        "function",
        "var",
        "const",
        "public",
        "private",
        "protected",
        "internal",
        "static",
        "return",
        "if",
        "else",
        "for",
        "while",
        "do",
        "switch",
        "case",
        "new",
        "this",
        "import",
        "extends",
        "implements",
        "try",
        "catch",
        "finally",
        "throw",
        "typeof",
        "is",
        "as",
        "use",
        "namespace",
        "super",
        "void",
        "uint",
        "int",
        "Number",
        "Boolean",
        "String",
        "Array",
        "Object",
        "Class",
        "XML",
    }

    RULES = [
        ("IDENTIFIER", r"[a-zA-Z_$][a-zA-Z0-9_$]*"),
        ("PUNCTUATION", r"[{}()\[\],;?]"),
        ("NUMBER", r"0x[0-9a-fA-F]+|\d+(\.\d+)?([eE][+-]?\d+)?"),
        ("STRING", r'"[^"\\]*(?:\\.[^"\\]*)*"|\'[^\'\\]*(?:\\.[^\'\\]*)*\''),
        ("COMMENT", r"//.*|/\*[\s\S]*?\*/"),
        (
            "OPERATOR",
            r"===|!==|==|!=|<=|>=|&&|\|\||\+\+|--|\.\.\.|\+=|-=|\*=|/=|%=|<<=|>>=|>>>=|<<|>>|>>>|[+\-*/%|=<>!&|^~.:@]",
        ),
        ("WHITESPACE", r"\s+"),
        ("UNKNOWN", r"[^\s]"),
    ]

    KIND_MAP = {
        "IDENTIFIER": TokenType.IDENTIFIER,
        "PUNCTUATION": TokenType.PUNCTUATION,
        "NUMBER": TokenType.NUMBER,
        "OPERATOR": TokenType.OPERATOR,
        "STRING": TokenType.STRING,
        "COMMENT": TokenType.COMMENT,
        "WHITESPACE": TokenType.WHITESPACE,
    }

    MASTER_RE = re.compile("|".join(f"(?P<{name}>{rule})" for name, rule in RULES))
    XML_STRUCT_RE = re.compile(r"<(/?)([a-zA-Z0-9_:]+)|/>|<!--|<!\[CDATA\[|\{")

    def __init__(self, config: ProcessorConfig):
        self.config = config

    def _scan_e4x(self, text: str, start: int) -> str:
        pos = start
        tag_stack: list[str] = []
        struct_re = self.XML_STRUCT_RE
        if not struct_re.match(text, pos):
            return text[pos : pos + 1]
        while pos < len(text):
            m = struct_re.search(text, pos)
            if not m:
                break
            trigger = m.group(0)
            if trigger == "{":
                depth = 1
                idx = m.end()
                while idx < len(text) and depth > 0:
                    c = text[idx]
                    if c == "{":
                        depth += 1
                    elif c == "}":
                        depth -= 1
                    idx += 1
                pos = idx
            elif trigger == "<!--":
                pos = text.find("-->", m.end()) + 3
            elif trigger == "<![CDATA[":
                pos = text.find("]]>", m.end()) + 3
            elif trigger == "/>":
                if not tag_stack:
                    return text[start : m.end()]
                tag_stack.pop()
                pos = m.end()
                if not tag_stack:
                    return text[start:pos]
            elif trigger.startswith("</"):
                if tag_stack:
                    tag_stack.pop()
                pos = text.find(">", m.end()) + 1
                if not tag_stack:
                    return text[start:pos]
            elif trigger.startswith("<"):
                tag_stack.append(m.group(2))
                h_end = text.find(">", m.end())
                if text[h_end - 1] == "/":
                    tag_stack.pop()
                    if not tag_stack:
                        return text[start : h_end + 1]
                pos = h_end + 1
        return text[start:pos]

    def tokenize(self, code: str) -> List[Token]:
        tokens: list[Token] = []
        t_append = tokens.append
        keywords = self.KEYWORDS
        m_re = self.MASTER_RE.match
        k_map = self.KIND_MAP

        T_COMMENT = TokenType.COMMENT
        T_IDENTIFIER = TokenType.IDENTIFIER
        T_KEYWORD = TokenType.KEYWORD
        T_XML = TokenType.XML
        T_REGEX = TokenType.REGEX
        C_POLICY_ALL = CommentPolicy.ALL
        C_POLICY_IMP = CommentPolicy.IMPORTANT

        pos = 0
        code_len = len(code)
        last_t = None
        policy = self.config.comment_policy

        while pos < code_len:
            char = code[pos]
            if char == "/":
                if code.startswith("//", pos) or code.startswith("/*", pos):
                    pass
                elif not last_t or (last_t.type <= T_KEYWORD and last_t.value != ")"):
                    rm = re.match(r"/(?![/*])(?:\\.|[^/])+/([gimuy]*)", code[pos:])
                    if rm:
                        last_t = Token(T_REGEX, rm.group())
                        t_append(last_t)
                        pos += rm.end()
                        continue
            elif char == "<":
                if last_t and last_t.value in (
                    "=",
                    ":",
                    "(",
                    "[",
                    ",",
                    "return",
                    "throw",
                ):
                    xc = self._scan_e4x(code, pos)
                    last_t = Token(T_XML, xc)
                    t_append(last_t)
                    pos += len(xc)
                    continue

            m = m_re(code, pos)
            if m:
                k = m.lastgroup
                v = m.group()
                pos = m.end()

                if k == "IDENTIFIER":
                    last_t = Token(T_KEYWORD if v in keywords else T_IDENTIFIER, v)
                    t_append(last_t)
                elif k == "WHITESPACE":
                    continue
                elif k == "COMMENT":
                    is_imp = (
                        "!" in v or "license" in v.lower() or "copyright" in v.lower()
                    )
                    if policy == C_POLICY_ALL or (policy == C_POLICY_IMP and is_imp):
                        last_t = Token(T_COMMENT, v, is_imp)
                        t_append(last_t)
                else:
                    if k is not None:
                        last_t = Token(k_map[k], v)
                        t_append(last_t)
                pos = m.end()
            else:
                pos += 1
        return tokens


class AS3Processor:
    INDENTS = [" " * (i * 4) for i in range(256)]
    OP_SET = {
        "=",
        "==",
        "!=",
        "&&",
        "||",
        "<",
        ">",
        "<=",
        ">=",
        "+",
        "-",
        "*",
        "/",
        "+=",
        "-=",
        "=>",
    }

    ASI_STARTERS = {
        "if",
        "for",
        "while",
        "var",
        "const",
        "return",
        "import",
        "class",
        "package",
        "throw",
        "try",
        "do",
        "switch",
        "public",
        "private",
        "protected",
        "internal",
        "static",
        "final",
        "override",
    }
    ASI_SAFE_PREV = {
        "{",
        "}",
        ";",
        "(",
        "[",
        ",",
        ":",
        "else",
        "public",
        "private",
        "protected",
        "internal",
        "static",
        "final",
        "override",
    }

    def __init__(self, tokens: List[Token], config: ProcessorConfig):
        self.tokens = tokens
        self.config = config

    def run(self) -> str:
        return (
            self._emit_minified() if self.config.is_minify else self._emit_formatted()
        )

    def _emit_minified(self) -> str:
        res: list[str] = []
        res_append = res.append
        last_code_t = None

        T_COMMENT = TokenType.COMMENT
        T_XML = TokenType.XML
        T_KEYWORD = TokenType.KEYWORD
        xml_clean = re.compile(r">\s+<").sub

        asi_starters = self.ASI_STARTERS
        asi_safe = self.ASI_SAFE_PREV

        for t in self.tokens:
            if t.type == T_COMMENT:
                if not t.is_important_comment:
                    continue
                if res and not res[-1].isspace():
                    res_append(" ")
                res_append(t.value)
                if t.value.startswith("//"):
                    res_append(";\n")
                continue

            val = t.value
            if t.type == T_XML and not self.config.preserve_e4x_whitespace:
                val = xml_clean("><", val)

            if res:
                if t.type == T_KEYWORD and val in asi_starters:
                    if last_code_t and last_code_t.value not in asi_safe:
                        res_append(";")

                c1 = res[-1][-1]
                c2 = val[0]
                if (c1.isalnum() or c1 in "_$") and (c2.isalnum() or c2 in "_$"):
                    res_append(" ")

            res_append(val)
            last_code_t = t

        return "".join(res).strip()

    def _emit_formatted(self) -> str:
        tokens = self.tokens
        if not tokens:
            return ""

        res: list[str] = []
        res_append = res.append
        indent = 0
        p_depth = 0
        last_val = "\n"
        last_code_t = None

        indents = self.INDENTS
        op_set = self.OP_SET
        asi_starters = self.ASI_STARTERS
        asi_safe = self.ASI_SAFE_PREV

        T_COMMENT = TokenType.COMMENT
        T_KEYWORD = TokenType.KEYWORD
        T_IDENTIFIER = TokenType.IDENTIFIER
        T_NUMBER = TokenType.NUMBER

        nxt_iter = chain(islice(tokens, 1, None), [Token(TokenType.WHITESPACE, "")])

        for curr, nxt in zip(tokens, nxt_iter):
            val = curr.value
            t_type = curr.type

            if t_type == T_COMMENT:
                if last_val != "\n":
                    res_append("\n")
                res_append(val)
                res_append("\n")
                last_val = "\n"
                continue

            # 2. ASI 自动分号插入逻辑
            if last_code_t and t_type == T_KEYWORD and val in asi_starters:
                if last_code_t.value not in asi_safe:
                    res_append(";")
                    if last_val != "\n":
                        res_append("\n")
                    last_val = "\n"

            # 3. 缩进修正
            if val == "}":
                indent = indent - 1 if indent > 0 else 0
                if res and res[-1].strip() == "" and res[-1] != "\n":
                    res.pop()
                if last_val != "\n":
                    res_append("\n")
                res_append(indents[indent])
                last_val = indents[indent]
            elif last_val == "\n":
                res_append(indents[indent])
                last_val = indents[indent]

            # 4. 空格控制 (基于 last_code_t 判定)
            if (
                last_code_t
                and last_val != "\n"
                and not last_val.isspace()
                and val not in (";", ",", ")", ":", ".", "[")
            ):
                p_val, p_type = last_code_t.value, last_code_t.type
                if p_type == T_KEYWORD:
                    add_s = val not in (";", ":", "(", ")", "[", "]", ",", ".")
                elif t_type == T_KEYWORD:
                    add_s = p_val not in ("(", "{", "\n", ".", ":") or p_val == "*"
                elif p_val in op_set or val in op_set:
                    add_s = val not in (";", "(", ")", ":", ",", ".") and p_val not in (
                        "(",
                        ":",
                        ".",
                        "\n",
                    )
                else:
                    # 标识符/数字/关键字 之间的间距
                    add_s = (
                        (p_val == ",")
                        or (p_val == ")" and val == "{")
                        or (
                            p_type in (T_IDENTIFIER, T_NUMBER)
                            and t_type in (T_IDENTIFIER, T_NUMBER, T_KEYWORD)
                        )
                    )
                if add_s:
                    res_append(" ")

            # 5. 写入内容
            res_append(val)
            last_val = val

            # 6. 状态及 ASI 换行
            if val == "(":
                p_depth += 1
            elif val == ")":
                p_depth = max(0, p_depth - 1)
            elif val == "{":
                indent += 1
                res_append("\n")
                last_val = "\n"
            elif val == ";":
                if p_depth == 0:
                    res_append("\n")
                    last_val = "\n"
            elif val == "}":
                if not (nxt.value in ("else", "catch", "finally")):
                    if last_val != "\n":
                        res_append("\n")
                        last_val = "\n"

            last_code_t = curr

        return "".join(res).strip()


if __name__ == "__main__":
    raw_code = """
    // @license MIT 
    package com.QQ.angel.net.protocol{
    import com.QQ.angel.api.net.protocol.IAngelDataInput
    public class P_BagSpiritData implements IAngelDataInput {
    public function read(param1:IDataInput):void {/*abcdefghijklmn123456789*/
    var local3:* if(sex==1){sexNmae="male"}else if(sex==2){sexNmae="female"}
    for(local3=0local3<local2(++local3)){trace(local3)}}} }
    """
    conf_f = ProcessorConfig(is_minify=False)
    conf_m = ProcessorConfig(is_minify=True)
    lex_f = AS3Lexer(conf_f)
    lex_m = AS3Lexer(conf_m)

    t1 = time.time()
    s1 = ""
    s2 = ""
    for _ in range(1):  # reduce for demo
        tokens1 = lex_f.tokenize(raw_code)
        s1 = AS3Processor(tokens1, conf_f).run()
        tokens2 = lex_m.tokenize(s1)
        s2 = AS3Processor(tokens2, conf_m).run()
    print(f"Total Time: {time.time() - t1:.4f}s")
    print("\n--- Formatted Result ---")
    print(s1)
    print("\n--- Minified Result ---")
    print(s2)

    import time
    import pstats, cProfile

    def profile_workflow(raw_code: str) -> None:
        # 定义一个闭包函数，模拟一次完整流程
        def full_task() -> None:
            cfg = ProcessorConfig(is_minify=False)
            lexer = AS3Lexer(cfg)
            tokens = lexer.tokenize(raw_code)
            AS3Processor(tokens, cfg).run()

        # 启动性能统计
        profiler = cProfile.Profile()
        profiler.enable()

        # 运行 5000 次获取稳定样本
        for _ in range(100000):
            full_task()

        profiler.disable()

        # 打印结果，按累计时间排序
        stats = pstats.Stats(profiler).sort_stats("cumulative")
        print("\n=== 函数级性能瓶颈 (按累计耗时排序) ===")
        stats.print_stats(20)  # 只显示前 15 个最耗时的调用

    profile_workflow(raw_code)
