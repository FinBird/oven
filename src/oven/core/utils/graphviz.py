from __future__ import annotations

import html
import re
import textwrap
from typing import Union

__all__ = ["Graphviz"]


class Graphviz:
    """Graphviz DOT generator for CFG and AST visualization."""

    __slots__ = ("_buffer", "default_node_opts")

    _BOLD_PATTERN = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)

    def __init__(self, graph_attr: dict[str, str] | None = None) -> None:
        self._buffer: list[str] = ["digraph {\n"]
        self._emit("node [labeljust=l,nojustify=true,fontname=monospace];")

        if graph_attr is None:
            self._emit("rankdir=TB;")
        else:
            for key, value in graph_attr.items():
                self._emit(f'{key}="{value}";')

        self.default_node_opts: dict[str, Union[str, int, bool]] = {"shape": "box"}

    def _emit(self, line: str) -> None:
        self._buffer.append(f"    {line}\n")

    @staticmethod
    def _node_id(name: str | None) -> str:
        if name is None:
            return '"__exit__"'
        escaped = name.replace('"', '\\"')
        return f'"{escaped}"'

    @staticmethod
    def _validate_wrap_width(wrap_width: int) -> None:
        if wrap_width <= 0:
            raise ValueError(f"wrap_width must be a positive integer, got: {wrap_width}")

    def _normalize_lines(self, content: str, wrap_width: int) -> list[str]:
        self._validate_wrap_width(wrap_width)

        lines: list[str] = []
        for line in content.splitlines():
            if len(line) <= wrap_width:
                lines.append(line)
                continue
            lines.extend(textwrap.wrap(line, width=wrap_width))
        return lines

    def _build_html_label(self, content: str, wrap_width: int) -> str:
        lines = self._normalize_lines(content, wrap_width)
        escaped_lines = [html.escape(line, quote=False) for line in lines]
        full_content = "\n".join(escaped_lines)
        full_content = self._BOLD_PATTERN.sub(r"<b>\1</b>", full_content)

        rows = "".join(
            f'<tr><td align="left">{line}</td></tr>'
            for line in full_content.splitlines()
        )
        if not rows:
            return "<empty>"
        return f'<<table border="0">{rows}</table>>'

    def node(
        self,
        name: str | None,
        content: str,
        options: dict[str, Union[str, int, bool]] | None = None,
        wrap_width: int = 40,
    ) -> None:
        safe_name = self._node_id(name)

        node_opts = self.default_node_opts.copy()
        if options:
            node_opts.update(options)
        node_opts["label"] = self._build_html_label(content, wrap_width)

        self._emit(f"{safe_name} {self._graphviz_options(node_opts)};")

    def edge(
        self,
        from_node: str | None,
        to_node: str | None,
        label: str = "",
        options: dict[str, Union[str, int, bool]] | None = None,
    ) -> None:
        src = self._node_id(from_node)
        dst = self._node_id(to_node)

        opts: dict[str, Union[str, int, bool]] = options.copy() if options else {}
        if label:
            opts["label"] = label

        self._emit(f"{src} -> {dst} {self._graphviz_options(opts)};")

    def _graphviz_options(self, options: dict[str, Union[str, int, bool]]) -> str:
        items: list[str] = []
        for key, value in options.items():
            text_value = str(value)
            if key == "label" and text_value.startswith("<"):
                items.append(f"{key}={text_value}")
            else:
                escaped = text_value.replace('"', '\\"')
                items.append(f'{key}="{escaped}"')
        return f"[{','.join(items)}]"

    def __str__(self) -> str:
        return "".join(self._buffer) + "}"

