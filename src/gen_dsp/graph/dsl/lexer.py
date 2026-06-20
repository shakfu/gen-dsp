"""Tokenizer and error types for the GDSP DSL."""

from __future__ import annotations

import re
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Error types
# ---------------------------------------------------------------------------


class GDSPSyntaxError(Exception):
    """Raised for tokenizer and parser errors."""

    def __init__(
        self, message: str, line: int = 0, col: int = 0, filename: str = "<string>"
    ):
        self.line = line
        self.col = col
        self.filename = filename
        loc = f"{filename}:{line}:{col}"
        super().__init__(f"{loc}: {message}")


class GDSPCompileError(Exception):
    """Raised for semantic / compilation errors."""

    def __init__(
        self, message: str, line: int = 0, col: int = 0, filename: str = "<string>"
    ):
        self.line = line
        self.col = col
        self.filename = filename
        loc = f"{filename}:{line}:{col}"
        super().__init__(f"{loc}: {message}")


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

# Token types
NUMBER = "NUMBER"


IDENT = "IDENT"


STRING = "STRING"


NEWLINE = "NEWLINE"


EOF = "EOF"


OP = "OP"  # operator tokens stored by value


@dataclass(frozen=True)
class Token:
    type: str
    value: str
    line: int
    col: int


# Multi-char operators, ordered longest-first for greedy matching
_MULTI_OPS = ["**", ">>", "//", ">=", "<=", "==", "!=", "..", "<-"]


_SINGLE_OPS = set("+-*/%><=(){},.;:@")


# Regex for numbers
_NUM_RE = re.compile(r"[0-9]+(\.[0-9]+)?")


_IDENT_RE = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*")


def tokenize(source: str, filename: str = "<string>") -> list[Token]:
    """Tokenize GDSP source into a list of Tokens."""
    tokens: list[Token] = []
    line = 1
    col = 1
    i = 0
    n = len(source)

    while i < n:
        ch = source[i]

        # Newlines
        if ch == "\n":
            tokens.append(Token(NEWLINE, "\n", line, col))
            line += 1
            col = 1
            i += 1
            continue

        # Whitespace (not newline)
        if ch in " \t\r":
            i += 1
            col += 1
            continue

        # Comments: # to EOL
        if ch == "#":
            while i < n and source[i] != "\n":
                i += 1
                col += 1
            continue

        # String literals
        if ch == '"':
            start_col = col
            i += 1
            col += 1
            s = ""
            while i < n and source[i] != '"':
                if source[i] == "\n":
                    raise GDSPSyntaxError(
                        "unterminated string literal", line, start_col, filename
                    )
                s += source[i]
                i += 1
                col += 1
            if i >= n:
                raise GDSPSyntaxError(
                    "unterminated string literal", line, start_col, filename
                )
            i += 1  # skip closing "
            col += 1
            tokens.append(Token(STRING, s, line, start_col))
            continue

        # Numbers
        m = _NUM_RE.match(source, i)
        if m and (i == 0 or not source[i - 1].isalpha()):
            val = m.group()
            tokens.append(Token(NUMBER, val, line, col))
            i += len(val)
            col += len(val)
            continue

        # Multi-char operators (check before single-char)
        matched_op = False
        for op in _MULTI_OPS:
            if source[i : i + len(op)] == op:
                # Disambiguation: // is parallel op (not comment)
                tokens.append(Token(OP, op, line, col))
                i += len(op)
                col += len(op)
                matched_op = True
                break
        if matched_op:
            continue

        # Single-char operators
        if ch in _SINGLE_OPS:
            tokens.append(Token(OP, ch, line, col))
            i += 1
            col += 1
            continue

        # Identifiers / keywords
        m = _IDENT_RE.match(source, i)
        if m:
            val = m.group()
            tokens.append(Token(IDENT, val, line, col))
            i += len(val)
            col += len(val)
            continue

        raise GDSPSyntaxError(f"unexpected character {ch!r}", line, col, filename)

    tokens.append(Token(EOF, "", line, col))
    return tokens
