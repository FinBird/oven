# Furnace API 指南（中文）

本文档说明 `furnace` 当前公开 API 的作用、典型使用方式与兼容性约定。  
本次重构后对外接口保持不变，以下导入路径仍然可用。

## 1. 包级导出（`furnace`）

```python
from furnace import (
    # AST
    Node, NodeVisitor, Matcher, m, to_ast_node, MatchError, CaptureDict, BaseMatcher,
    # CFG
    CFG, CFGNode,
    # Code
    Token, TerminalToken, NewlineToken, NonterminalToken, SurroundedToken, SeparatedToken, CodeFormatter,
    # Transform
    Transform, Pipeline, ASTBuild, PropagateLabels, PropagateConstants, CFGBuild, CFGReduce,
    # Utils
    Graphviz,
)
```

## 2. 子模块职责

### 2.1 `oven.ast`
- `Node`：统一 AST 节点结构（`type/children/metadata`）。
- `NodeVisitor`：访问并可变更 AST 的 visitor 基类。
- `Matcher` + `m`：模式匹配 DSL（结构匹配、捕获、回溯引用）。
- `to_ast_node`：将实现 `to_ast_node()` 协议的对象转换为 `Node`。

### 2.2 `oven.cfg`
- `CFGNode`：控制流图节点，包含指令、转移与异常边。
- `CFG`：控制流图容器，支持：
  - `eliminate_unreachable()`
  - `merge_redundant()`
  - `dominators/postdominators`
  - `identify_loops()`
  - `to_graphviz()`

### 2.3 `oven.code`
- `Token` 体系：代码输出的 token 树抽象。
- `CodeFormatter`：统一缩进与长行换行。

### 2.4 `oven.transform`
- `Transform`：变换基类。
- `Pipeline`：串联多个变换。
- AVM2 相关核心变换：
  - `ASTBuild`
  - `PropagateLabels`
  - `PropagateConstants`
  - `CFGBuild`
  - `CFGReduce`

### 2.5 `oven.utils`
- `Graphviz`：DOT 字符串构建工具（CFG/AST 可视化）。

## 3. 典型流水线示例（ASTBuild -> Normalize -> CFG -> NF）

```python
from oven.transform.ast_build import ASTBuild
from oven.transform.ast_normalize import ASTNormalize
from oven.transform.propagate_constants import PropagateConstants
from oven.transform.propagate_labels import PropagateLabels
from oven.transform.cfg_build import CFGBuild
from oven.transform.cfg_reduce import CFGReduce
from oven.transform.nf_transform import NFNormalize


def method_body_to_nf(body):
    ast, out_body, finallies = ASTBuild({"tolerate_stack_underflow": True}).transform(body.instructions, body)
    ASTNormalize().transform(ast)
    PropagateConstants().transform(ast)
    PropagateLabels().transform(ast)
    cfg = CFGBuild().transform(ast, out_body, finallies)
    reduced = CFGReduce().transform(cfg)
    return NFNormalize().transform(reduced)
```

说明：
- `ASTBuild` 生成低层语义 AST。
- `ASTNormalize` 与传播 pass 清理表达式与标签。
- `CFGBuild/CFGReduce` 做控制流结构化。
- `NFNormalize` 输出更稳定的 Normal Form AST。

## 4. Matcher DSL 示例

### 4.1 顺序匹配 + 捕获

```python
from oven.ast import m

pattern = m.seq(
    m.capture("lhs"),
    m.eq("+"),
    m.capture("rhs"),
)

captures = {}
ok = pattern.match([1, "+", 2], captures)
# ok == True, captures == {"lhs": 1, "rhs": 2}
```

### 4.2 节点结构匹配

```python
from oven.ast import Node, Matcher, m

node = Node("add", [Node("integer", [1]), Node("integer", [2])])
matcher = Matcher(m.of("add", m.of("integer"), m.of("integer")))
result = matcher.match(node)
# result is not None
```

### 4.3 递归包含匹配

```python
from oven.ast import m

# 匹配“某棵子树中是否含有 type=return_value 的节点”
has_return = m.has(m.of("return_value"))
```

## 5. CFG 与 Graphviz 示例

```python
from oven.cfg import CFG
from oven.ast import Node

cfg = CFG()
entry = cfg.add_node("entry", [Node("integer", [1])])
body = cfg.add_node("body", [Node("integer", [2])])
exit_node = cfg.add_node(None, [])
cfg.entry = entry
cfg.exit = exit_node

entry.target_labels = ["body"]
body.target_labels = [None]

dot = cfg.to_graphviz()
print(dot)
```

如果需要写文件：

```python
cfg.to_graphviz_file("cfg.dot")
```

## 6. Token/CodeFormatter 示例

```python
from oven.code import TerminalToken, NonterminalToken, CodeFormatter

token = NonterminalToken(
    None,
    [TerminalToken("var "), TerminalToken("x"), TerminalToken(" = "), TerminalToken("42"), TerminalToken(";")],
)
text = CodeFormatter(indent_width=2, wrap_length=80).format_token(token)
print(text)  # var x = 42;
```

## 7. 兼容性声明

- 本次重构未改变以下对外契约：
  - `furnace` 根包导出名集合。
  - `oven.ast/Cfg/Code/transform/Utils` 子包导出名集合。
  - 公开导入路径（例如 `from oven.cfg import CFG`、`from oven.transform.cfg_build import CFGBuild`）。
  - `oven.transform` 懒加载导出行为（`ASTBuild/PropagateLabels/PropagateConstants/CFGBuild/CFGReduce`）。
- 变更仅限内部组织、类型标注补强与低风险性能优化。
