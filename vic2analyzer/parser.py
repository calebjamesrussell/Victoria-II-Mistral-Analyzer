"""Clausewitz (.v2) save parser for Victoria II.

Handles the text format used by Victoria II: A House Divided / Heart of
Darkness saves: brace-delimited nodes, ``key=value`` pairs, ``key={...}``
blocks, anonymous value lists inside braces, quoted strings, dates as keys,
``yes``/``no`` booleans, and whitespace-separated numeric arrays.
"""

from __future__ import annotations

import codecs
from typing import Any, Dict, Iterator, List, Optional, Tuple, Union

__all__ = ["parse_file", "parse_string", "ClausewitzSyntaxError"]

Value = Union[str, int, float, bool, List["Value"], Dict[str, "Value"]]

Node = Dict[str, Value]


class ClausewitzSyntaxError(ValueError):
    def __init__(self, message: str):
        super().__init__(message)


class _Tokenizer:
    _WS = " \t\r\n"
    _TOKEN_END = _WS + "{}="

    def __init__(self, text: str):
        self.text = text

    def tokens(self) -> Iterator[Tuple[str, str, int]]:
        text = self.text
        n = len(text)
        pos = 0
        while pos < n:
            c = text[pos]
            if c in self._WS:
                pos += 1
                continue
            if c == "#":
                end = text.find("\n", pos)
                pos = n if end == -1 else end + 1
                continue
            if c in "{}=":
                yield (c, c, pos)
                pos += 1
                continue
            if c == '"':
                end = text.find('"', pos + 1)
                if end == -1:
                    raise ClausewitzSyntaxError("unterminated string")
                yield ("str", text[pos + 1:end], pos)
                pos = end + 1
                continue
            start = pos
            while pos < n and text[pos] not in self._TOKEN_END and text[pos] != "#":
                pos += 1
            yield ("tok", text[start:pos], start)


def _convert(raw: str) -> Value:
    if raw == "yes":
        return True
    if raw == "no":
        return False
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        return raw


def _assign(node: Node, key: str, value: Value) -> None:
    existing = node.get(key)
    if existing is None:
        node[key] = value
        return
    if isinstance(existing, _Repeated):
        existing.append(value)
        return
    node[key] = _Repeated([existing, value])


class _Repeated(list):
    """Marker for values produced from a repeated key (e.g. ``state=``)."""


def _collapse(value: Any) -> Any:
    if isinstance(value, _Repeated) and len(value) == 1:
        return value[0]
    return value


class _Parser:
    """Recursive-descent parser producing nested dict/list structures.

    A block like ``{ a=1 a=2 b=3 }`` becomes ``{"a": [1, 2], "b": 3}`` while
    ``{ 1 2 3 }`` (no ``=``) stays a plain list.  Repeated named blocks
    (``state={...} state={...}``) are collected into lists.
    """

    def __init__(self, text: str):
        self.tokens = list(_Tokenizer(text).tokens())
        self.i = 0

    def _peek(self) -> Optional[Tuple[str, str, int]]:
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def _next(self) -> Tuple[str, str, int]:
        tok = self._peek()
        if tok is None:
            raise ClausewitzSyntaxError("unexpected end of input")
        self.i += 1
        return tok

    def parse(self) -> Node:
        node: Node = {}
        self._parse_entries(node, top_level=True)
        return node

    def _parse_entries(self, node: Node, top_level: bool) -> None:
        while True:
            tok = self._peek()
            if tok is None:
                if not top_level:
                    raise ClausewitzSyntaxError("missing closing brace")
                return
            kind, val, pos = tok
            if kind == "}":
                if top_level:
                    self.i += 1
                    continue
                self.i += 1
                return
            if kind == "{":
                raise ClausewitzSyntaxError("unexpected opening brace")
            if kind == "=":
                self.i += 1
                continue
            if kind == "str":
                self._next()
                nxt = self._peek()
                if nxt is not None and nxt[0] == "=":
                    self._next()
                    _assign(node, val, self._parse_value())
                else:
                    _assign(node, val, val)
                continue
            self._next()
            nxt = self._peek()
            if nxt is not None and nxt[0] == "=":
                self._next()
                _assign(node, val, self._parse_value())
            elif nxt is not None and nxt[0] == "{":
                self._next()
                _assign(node, val, self._parse_block_body())
            else:
                _assign(node, val, _convert(val))

    def _parse_value(self) -> Value:
        tok = self._next()
        kind, val, pos = tok
        if kind == "{":
            return self._parse_block_body()
        if kind == "str":
            return val
        return _convert(val)

    def _parse_block_body(self) -> Value:
        node: Node = {}
        values: List[Value] = []
        saw_pair = False
        while True:
            tok = self._peek()
            if tok is None:
                raise ClausewitzSyntaxError("missing closing brace")
            kind, val, pos = tok
            if kind == "}":
                self.i += 1
                break
            if kind == "{":
                self._next()
                values.append(self._parse_block_body())
                continue
            if kind == "=":
                self.i += 1
                continue
            if kind == "str":
                self._next()
                nxt = self._peek()
                if nxt is not None and nxt[0] == "=":
                    self._next()
                    _assign(node, val, self._parse_value())
                    saw_pair = True
                else:
                    values.append(val)
                continue
            self._next()
            nxt = self._peek()
            if nxt is not None and nxt[0] == "=":
                self._next()
                _assign(node, val, self._parse_value())
                saw_pair = True
            elif nxt is not None and nxt[0] == "{":
                self._next()
                _assign(node, val, self._parse_block_body())
                saw_pair = True
            else:
                values.append(_convert(val))
        if not saw_pair and not node:
            return values
        if values and not node:
            return values
        if values:
            node["__values__"] = values
        return node

    def _parse_block_body_nested(self) -> Value:
        return self._parse_block_body()


def parse_string(text: str) -> Node:
    """Parse save text (already decoded) into a dictionary tree."""
    return _Parser(text).parse()


def parse_file(path, encoding: str = "cp1252") -> Node:
    """Parse a .v2 save file. Returns a dictionary tree."""
    with codecs.open(path, "r", encoding=encoding, errors="replace") as fh:
        text = fh.read()
    return parse_string(text)
