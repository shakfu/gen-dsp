"""GDSP DSL parser: tokenizer, recursive-descent parser, and compiler.

Parses ``.gdsp`` source text into :class:`Graph` objects via a three-stage
pipeline: tokenizer (Token stream) -> parser (AST) -> compiler (Graph).

Public API::

    from gen_dsp.graph.dsl import parse, parse_file, parse_multi

    graph = parse("graph gain { ... }")
    graph = parse_file("synth.gdsp")
    graphs = parse_multi("graph a { ... } graph b { ... }")
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Union

from gen_dsp.graph.algebra import parallel as _algebra_parallel
from gen_dsp.graph.algebra import series as _algebra_series
from gen_dsp.graph.models import (
    SVF,
    ADSR,
    Accum,
    Allpass,
    AudioInput,
    AudioOutput,
    BinOp,
    Biquad,
    Buffer,
    BufRead,
    BufSize,
    BufWrite,
    Change,
    Clamp,
    Compare,
    Constant,
    Counter,
    Cycle,
    DCBlock,
    DelayLine,
    DelayRead,
    DelayWrite,
    Delta,
    Elapsed,
    Fold,
    GateOut,
    GateRoute,
    Graph,
    History,
    Latch,
    Lookup,
    Mix,
    NamedConstant,
    Noise,
    Node,
    OnePole,
    Param,
    Pass,
    Peek,
    Phasor,
    PulseOsc,
    RateDiv,
    SampleHold,
    SampleRate,
    SawOsc,
    Scale,
    Select,
    Selector,
    SinOsc,
    Slide,
    Smoothstep,
    SmoothParam,
    Splat,
    Subgraph,
    TriOsc,
    UnaryOp,
    Wave,
    Wrap,
)


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


# ---------------------------------------------------------------------------
# AST nodes
# ---------------------------------------------------------------------------


@dataclass
class ASTGraph:
    name: str
    options: dict[str, Union[str, float]]
    body: list[ASTStmt]
    line: int


@dataclass
class ASTInDecl:
    ids: list[str]
    line: int = 0


@dataclass
class ASTOutDecl:
    name: str
    source: ASTExpr
    line: int = 0


@dataclass
class ASTParamDecl:
    name: str
    min_val: float
    max_val: float
    default: float
    control: bool = False
    line: int = 0


@dataclass
class ASTBufferDecl:
    name: str
    size: int
    fill: str = "zeros"
    line: int = 0


@dataclass
class ASTDelayDecl:
    name: str
    max_samples: int
    line: int = 0


@dataclass
class ASTHistoryDecl:
    name: str
    init: float
    line: int = 0


@dataclass
class ASTFeedbackWrite:
    name: str
    value: ASTExpr
    line: int = 0


@dataclass
class ASTDelayWriteStmt:
    delay: str
    value: ASTExpr
    line: int = 0


@dataclass
class ASTBufWriteStmt:
    op: str  # "buf_write" or "splat"
    buffer: str
    index: ASTExpr
    value: ASTExpr
    line: int = 0


@dataclass
class ASTAssign:
    targets: list[str]
    value: ASTExpr
    control: bool = False
    line: int = 0


@dataclass
class ASTImportAssign:
    target: str
    path: str
    graph_name: str | None
    args: list[ASTArg]
    line: int = 0


# Expression nodes
@dataclass
class ASTNumber:
    value: float


@dataclass
class ASTIdent:
    name: str


@dataclass
class ASTBinExpr:
    op: str
    left: ASTExpr
    right: ASTExpr


@dataclass
class ASTUnaryExpr:
    op: str
    operand: ASTExpr


@dataclass
class ASTCall:
    name: str
    args: list[ASTArg]


@dataclass
class ASTDotAccess:
    obj: ASTExpr
    field_name: str


@dataclass
class ASTCompose:
    op: str  # ">>" or "//"
    left: ASTExpr
    right: ASTExpr


@dataclass
class ASTArg:
    name: str | None
    value: ASTExpr


# Type aliases for AST
ASTExpr = Union[
    ASTNumber,
    ASTIdent,
    ASTBinExpr,
    ASTUnaryExpr,
    ASTCall,
    ASTDotAccess,
    ASTCompose,
]

ASTStmt = Union[
    ASTInDecl,
    ASTOutDecl,
    ASTParamDecl,
    ASTBufferDecl,
    ASTDelayDecl,
    ASTHistoryDecl,
    ASTFeedbackWrite,
    ASTDelayWriteStmt,
    ASTBufWriteStmt,
    ASTAssign,
    ASTImportAssign,
]


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class Parser:
    """Recursive descent parser for GDSP."""

    def __init__(self, tokens: list[Token], filename: str = "<string>"):
        self.tokens = tokens
        self.pos = 0
        self.filename = filename

    def _peek(self) -> Token:
        if self.pos >= len(self.tokens):
            # Return a synthetic EOF
            last = self.tokens[-1] if self.tokens else Token(EOF, "", 1, 1)
            return Token(EOF, "", last.line, last.col)
        return self.tokens[self.pos]

    def _advance(self) -> Token:
        if self.pos >= len(self.tokens):
            last = self.tokens[-1] if self.tokens else Token(EOF, "", 1, 1)
            raise GDSPSyntaxError(
                "unexpected end of input", last.line, last.col, self.filename
            )
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def _at(self, type_: str, value: str | None = None) -> bool:
        tok = self._peek()
        if tok.type != type_:
            return False
        if value is not None and tok.value != value:
            return False
        return True

    def _expect(self, type_: str, value: str | None = None) -> Token:
        tok = self._advance()
        if tok.type != type_ or (value is not None and tok.value != value):
            expected = f"{type_}" if value is None else f"{type_}({value!r})"
            raise GDSPSyntaxError(
                f"expected {expected}, got {tok.type}({tok.value!r})",
                tok.line,
                tok.col,
                self.filename,
            )
        return tok

    def _skip_newlines(self) -> None:
        while self._at(NEWLINE) or self._at(OP, ";"):
            self._advance()

    def parse_file(self) -> list[ASTGraph]:
        """Parse a complete .gdsp file (one or more graph definitions)."""
        graphs: list[ASTGraph] = []
        self._skip_newlines()
        while not self._at(EOF):
            graphs.append(self._parse_graph_def())
            self._skip_newlines()
        return graphs

    def _parse_graph_def(self) -> ASTGraph:
        tok = self._expect(IDENT, "graph")
        name_tok = self._expect(IDENT)

        # Optional options in parens
        options: dict[str, Union[str, float]] = {}
        if self._at(OP, "("):
            self._advance()
            while not self._at(OP, ")"):
                opt_name = self._expect(IDENT).value
                self._expect(OP, "=")
                if self._at(NUMBER):
                    opt_val: Union[str, float] = float(self._advance().value)
                else:
                    opt_val = self._expect(IDENT).value
                options[opt_name] = opt_val
                if self._at(OP, ","):
                    self._advance()
            self._expect(OP, ")")

        self._expect(OP, "{")
        self._skip_newlines()

        body: list[ASTStmt] = []
        while not self._at(OP, "}"):
            stmt = self._parse_stmt()
            if stmt is not None:
                body.append(stmt)
            self._skip_newlines()

        self._expect(OP, "}")
        return ASTGraph(name=name_tok.value, options=options, body=body, line=tok.line)

    def _parse_stmt(self) -> ASTStmt | None:
        tok = self._peek()

        # @control prefix
        if tok.type == OP and tok.value == "@":
            self._advance()
            self._expect(IDENT, "control")
            return self._parse_stmt_after_control()

        if tok.type == IDENT:
            kw = tok.value
            if kw == "in":
                return self._parse_in_decl()
            if kw == "out":
                return self._parse_out_decl()
            if kw == "param":
                return self._parse_param_decl(control=False)
            if kw == "buffer":
                return self._parse_buffer_decl()
            if kw == "delay" and not self._is_delay_assign():
                return self._parse_delay_decl()
            if kw == "history":
                return self._parse_history_decl()
            if kw == "delay_write":
                return self._parse_delay_write_stmt()
            if kw in ("buf_write", "splat"):
                return self._parse_buf_write_stmt()
            # Otherwise: assignment or feedback write
            return self._parse_assignment_or_feedback()

        # Skip stray newlines/semicolons
        if tok.type in (NEWLINE, EOF) or (tok.type == OP and tok.value == ";"):
            self._advance()
            return None

        raise GDSPSyntaxError(
            f"unexpected token {tok.value!r}", tok.line, tok.col, self.filename
        )

    def _is_delay_assign(self) -> bool:
        """Lookahead: is 'delay' used as an identifier in an assignment?

        Pattern: delay = expr (delay is just a variable name)
        vs: delay NAME NUMBER (delay declaration)
        """
        # Check token after 'delay': if it's '=' or ',', it's an assignment
        if self.pos + 1 < len(self.tokens):
            next_tok = self.tokens[self.pos + 1]
            if next_tok.type == OP and next_tok.value in ("=", ",", "<-"):
                return True
        return False

    def _parse_stmt_after_control(self) -> ASTStmt:
        tok = self._peek()
        if tok.type == IDENT and tok.value == "param":
            return self._parse_param_decl(control=True)
        # @control assignment
        return self._parse_assignment_or_feedback(control=True)

    def _parse_in_decl(self) -> ASTInDecl:
        tok = self._advance()  # consume 'in'
        ids = [self._expect(IDENT).value]
        while self._at(OP, ","):
            self._advance()
            ids.append(self._expect(IDENT).value)
        return ASTInDecl(ids=ids, line=tok.line)

    def _parse_out_decl(self) -> ASTOutDecl:
        tok = self._advance()  # consume 'out'
        name = self._expect(IDENT).value
        self._expect(OP, "=")
        expr = self._parse_expr()
        return ASTOutDecl(name=name, source=expr, line=tok.line)

    def _parse_param_number(self) -> float:
        """Parse a possibly-negative number in param declarations."""
        neg = False
        if self._at(OP, "-"):
            neg = True
            self._advance()
        val = float(self._expect(NUMBER).value)
        return -val if neg else val

    def _parse_param_decl(self, control: bool) -> ASTParamDecl:
        tok = self._advance()  # consume 'param'
        name = self._expect(IDENT).value
        min_val = self._parse_param_number()
        self._expect(OP, "..")
        max_val = self._parse_param_number()
        self._expect(OP, "=")
        default = self._parse_param_number()

        return ASTParamDecl(
            name=name,
            min_val=min_val,
            max_val=max_val,
            default=default,
            control=control,
            line=tok.line,
        )

    def _parse_buffer_decl(self) -> ASTBufferDecl:
        tok = self._advance()  # consume 'buffer'
        name = self._expect(IDENT).value
        size = int(self._expect(NUMBER).value)
        fill = "zeros"
        # Optional key=value pairs
        while self._at(IDENT) and self.pos + 1 < len(self.tokens):
            next_tok = self.tokens[self.pos + 1]
            if next_tok.type == OP and next_tok.value == "=":
                key = self._advance().value
                self._advance()  # =
                val = self._expect(IDENT).value
                if key == "fill":
                    fill = val
            else:
                break
        return ASTBufferDecl(name=name, size=size, fill=fill, line=tok.line)

    def _parse_delay_decl(self) -> ASTDelayDecl:
        tok = self._advance()  # consume 'delay'
        name = self._expect(IDENT).value
        max_samples = int(self._expect(NUMBER).value)
        return ASTDelayDecl(name=name, max_samples=max_samples, line=tok.line)

    def _parse_history_decl(self) -> ASTHistoryDecl:
        tok = self._advance()  # consume 'history'
        name = self._expect(IDENT).value
        self._expect(OP, "=")

        neg = False
        if self._at(OP, "-"):
            neg = True
            self._advance()
        init = float(self._expect(NUMBER).value)
        if neg:
            init = -init

        return ASTHistoryDecl(name=name, init=init, line=tok.line)

    def _parse_delay_write_stmt(self) -> ASTDelayWriteStmt:
        tok = self._advance()  # consume 'delay_write'
        delay_name = self._expect(IDENT).value
        self._expect(OP, "(")
        value = self._parse_expr()
        self._expect(OP, ")")
        return ASTDelayWriteStmt(delay=delay_name, value=value, line=tok.line)

    def _parse_buf_write_stmt(self) -> ASTBufWriteStmt:
        tok = self._advance()  # consume 'buf_write' or 'splat'
        op = tok.value
        self._expect(OP, "(")
        buffer_name = self._expect(IDENT).value
        self._expect(OP, ",")
        index = self._parse_expr()
        self._expect(OP, ",")
        value = self._parse_expr()
        self._expect(OP, ")")
        return ASTBufWriteStmt(
            op=op, buffer=buffer_name, index=index, value=value, line=tok.line
        )

    def _parse_assignment_or_feedback(self, control: bool = False) -> ASTStmt:
        tok = self._peek()
        line = tok.line

        # Collect identifiers for potential destructuring or single assignment
        targets = [self._expect(IDENT).value]

        # Check for feedback write: name <-
        if self._at(OP, "<-"):
            self._advance()
            value = self._parse_expr()
            return ASTFeedbackWrite(name=targets[0], value=value, line=line)

        # Check for import: name = import ...
        if self._at(OP, "=") and self.pos + 1 < len(self.tokens):
            next_tok = self.tokens[self.pos + 1]
            if next_tok.type == IDENT and next_tok.value == "import":
                self._advance()  # consume =
                return self._parse_import_assign(targets[0], line)

        # Destructuring: a, b, c = expr
        while self._at(OP, ","):
            self._advance()
            targets.append(self._expect(IDENT).value)

        self._expect(OP, "=")
        value = self._parse_expr()
        return ASTAssign(targets=targets, value=value, control=control, line=line)

    def _parse_import_assign(self, target: str, line: int) -> ASTImportAssign:
        self._advance()  # consume 'import'
        path = self._expect(STRING).value

        graph_name: str | None = None
        if self._at(OP, ":"):
            self._advance()
            graph_name = self._expect(IDENT).value

        self._expect(OP, "(")
        args: list[ASTArg] = []
        if not self._at(OP, ")"):
            args = self._parse_arg_list()
        self._expect(OP, ")")

        return ASTImportAssign(
            target=target, path=path, graph_name=graph_name, args=args, line=line
        )

    # --- Expression parsing (precedence climbing) ---

    def _parse_expr(self) -> ASTExpr:
        return self._parse_composition()

    def _parse_composition(self) -> ASTExpr:
        left = self._parse_comparison()
        while self._at(OP, ">>") or self._at(OP, "//"):
            op = self._advance().value
            right = self._parse_comparison()
            left = ASTCompose(op=op, left=left, right=right)
        return left

    def _parse_comparison(self) -> ASTExpr:
        left = self._parse_addition()
        if self._peek().type == OP and self._peek().value in (
            ">",
            "<",
            ">=",
            "<=",
            "==",
            "!=",
        ):
            op = self._advance().value
            right = self._parse_addition()
            # Map to Compare op names
            op_map = {
                ">": "gt",
                "<": "lt",
                ">=": "gte",
                "<=": "lte",
                "==": "eq",
                "!=": "neq",
            }
            left = ASTBinExpr(op=op_map[op], left=left, right=right)
        return left

    def _parse_addition(self) -> ASTExpr:
        left = self._parse_multiply()
        while self._at(OP, "+") or self._at(OP, "-"):
            op = self._advance().value
            op_name = "add" if op == "+" else "sub"
            right = self._parse_multiply()
            left = ASTBinExpr(op=op_name, left=left, right=right)
        return left

    def _parse_multiply(self) -> ASTExpr:
        left = self._parse_power()
        while (
            self._at(OP, "*")
            or (self._at(OP, "/") and not self._at(OP, "//"))
            or self._at(OP, "%")
        ):
            tok = self._peek()
            if tok.value == "/" and self.pos + 1 < len(self.tokens):
                next_ch = self.tokens[self.pos + 1]
                if next_ch.type == OP and next_ch.value == "/":
                    break  # // is composition, not divide+divide
            op = self._advance().value
            op_map = {"*": "mul", "/": "div", "%": "mod"}
            right = self._parse_power()
            left = ASTBinExpr(op=op_map[op], left=left, right=right)
        return left

    def _parse_power(self) -> ASTExpr:
        base = self._parse_unary()
        if self._at(OP, "**"):
            self._advance()
            exp = self._parse_power()  # right-assoc
            base = ASTBinExpr(op="pow", left=base, right=exp)
        return base

    def _parse_unary(self) -> ASTExpr:
        if self._at(OP, "-"):
            self._advance()
            operand = self._parse_unary()
            # Fold constant negation
            if isinstance(operand, ASTNumber):
                return ASTNumber(value=-operand.value)
            return ASTUnaryExpr(op="neg", operand=operand)
        return self._parse_postfix()

    def _parse_postfix(self) -> ASTExpr:
        expr = self._parse_atom()
        while self._at(OP, "."):
            self._advance()
            field = self._expect(IDENT).value
            expr = ASTDotAccess(obj=expr, field_name=field)
        return expr

    def _parse_atom(self) -> ASTExpr:
        tok = self._peek()

        # Number
        if tok.type == NUMBER:
            self._advance()
            return ASTNumber(value=float(tok.value))

        # Parenthesized expression
        if tok.type == OP and tok.value == "(":
            self._advance()
            expr = self._parse_expr()
            self._expect(OP, ")")
            return expr

        # Identifier or function call
        if tok.type == IDENT:
            # Special: delay_read is parsed as a call with delay name as first arg
            if tok.value == "delay_read":
                return self._parse_delay_read_expr()

            self._advance()
            # Check for function call
            if self._at(OP, "("):
                self._advance()
                args: list[ASTArg] = []
                if not self._at(OP, ")"):
                    args = self._parse_arg_list()
                self._expect(OP, ")")
                return ASTCall(name=tok.value, args=args)
            return ASTIdent(name=tok.value)

        raise GDSPSyntaxError(
            f"unexpected token {tok.value!r} in expression",
            tok.line,
            tok.col,
            self.filename,
        )

    def _parse_delay_read_expr(self) -> ASTCall:
        """Parse: delay_read NAME (args)"""
        self._advance()  # consume 'delay_read'
        delay_name = self._expect(IDENT).value
        self._expect(OP, "(")
        args: list[ASTArg] = []
        # Inject delay name as first positional arg
        args.append(ASTArg(name=None, value=ASTIdent(name=delay_name)))
        if not self._at(OP, ")"):
            args.extend(self._parse_arg_list())
        self._expect(OP, ")")
        return ASTCall(name="delay_read", args=args)

    def _parse_arg_list(self) -> list[ASTArg]:
        args: list[ASTArg] = []
        args.append(self._parse_arg())
        while self._at(OP, ","):
            self._advance()
            args.append(self._parse_arg())
        return args

    def _parse_arg(self) -> ASTArg:
        # Lookahead: IDENT = expr (keyword arg)
        if self._at(IDENT) and self.pos + 1 < len(self.tokens):
            next_tok = self.tokens[self.pos + 1]
            if next_tok.type == OP and next_tok.value == "=":
                name = self._advance().value
                self._advance()  # consume =
                value = self._parse_expr()
                return ASTArg(name=name, value=value)
        # Positional arg
        value = self._parse_expr()
        return ASTArg(name=None, value=value)


# ---------------------------------------------------------------------------
# Compiler (AST -> Graph)
# ---------------------------------------------------------------------------

# Named constants that can appear as bare identifiers
_NAMED_CONSTANTS = {
    "pi",
    "e",
    "twopi",
    "halfpi",
    "invpi",
    "degtorad",
    "radtodeg",
    "sqrt2",
    "sqrt1_2",
    "ln2",
    "ln10",
    "log2e",
    "log10e",
    "phi",
}

# Unary ops (DSL name -> UnaryOp.op)
_UNARY_OPS = {
    "sin",
    "cos",
    "tan",
    "tanh",
    "sinh",
    "cosh",
    "asin",
    "acos",
    "atan",
    "asinh",
    "acosh",
    "atanh",
    "exp",
    "exp2",
    "log",
    "log2",
    "log10",
    "abs",
    "sqrt",
    "neg",
    "sign",
    "floor",
    "ceil",
    "round",
    "trunc",
    "fract",
    "not",
    "bool",
    "mtof",
    "ftom",
    "atodb",
    "dbtoa",
    "phasewrap",
    "degrees",
    "radians",
    "mstosamps",
    "sampstoms",
    "t60",
    "t60time",
    "fixdenorm",
    "fixnan",
    "isdenorm",
    "isnan",
    "fastsin",
    "fastcos",
    "fasttan",
    "fastexp",
}

# Binary ops via function call (DSL name -> BinOp.op)
_BINOP_FUNCS = {
    "min",
    "max",
    "atan2",
    "hypot",
    "absdiff",
    "step",
    "and",
    "or",
    "xor",
    "fastpow",
}

# Builtin registry: name -> (ModelClass, positional_field_names, fixed_kwargs)
_BUILTINS: dict[str, tuple[type, list[str], dict[str, str]]] = {
    "phasor": (Phasor, ["freq"], {}),
    "sinosc": (SinOsc, ["freq"], {}),
    "triosc": (TriOsc, ["freq"], {}),
    "sawosc": (SawOsc, ["freq"], {}),
    "pulseosc": (PulseOsc, ["freq", "width"], {}),
    "noise": (Noise, [], {}),
    "onepole": (OnePole, ["a", "coeff"], {}),
    "svf": (SVF, ["a", "freq", "q"], {}),
    "biquad": (Biquad, ["a", "b0", "b1", "b2", "a1", "a2"], {}),
    "dcblock": (DCBlock, ["a"], {}),
    "allpass": (Allpass, ["a", "coeff"], {}),
    "clamp": (Clamp, ["a", "lo", "hi"], {}),
    "wrap": (Wrap, ["a", "lo", "hi"], {}),
    "fold": (Fold, ["a", "lo", "hi"], {}),
    "scale": (Scale, ["a", "in_lo", "in_hi", "out_lo", "out_hi"], {}),
    "mix": (Mix, ["a", "b", "t"], {}),
    "smoothstep": (Smoothstep, ["a", "edge0", "edge1"], {}),
    "smooth": (SmoothParam, ["a", "coeff"], {}),
    "slide": (Slide, ["a", "up", "down"], {}),
    "adsr": (ADSR, ["gate", "attack", "decay", "sustain", "release"], {}),
    "select": (Select, ["cond", "a", "b"], {}),
    "delta": (Delta, ["a"], {}),
    "change": (Change, ["a"], {}),
    "sample_hold": (SampleHold, ["a", "trig"], {}),
    "latch": (Latch, ["a", "trig"], {}),
    "accum": (Accum, ["incr", "reset"], {}),
    "counter": (Counter, ["trig", "max"], {}),
    "elapsed": (Elapsed, [], {}),
    "rate_div": (RateDiv, ["a", "divisor"], {}),
    "pass": (Pass, ["a"], {}),
    "peek": (Peek, ["a"], {}),
    "samplerate": (SampleRate, [], {}),
    "cycle": (Cycle, ["buffer", "phase"], {}),
    "wave": (Wave, ["buffer", "phase"], {}),
    "lookup": (Lookup, ["buffer", "index"], {}),
    "buf_read": (BufRead, ["buffer", "index"], {}),
    "buf_size": (BufSize, ["buffer"], {}),
}

# Fields that take string buffer/delay references (not Ref)
_STR_REF_FIELDS = {"buffer", "delay", "gate"}


@dataclass
class _IDCounter:
    """Auto-incrementing ID generator."""

    counters: dict[str, int] = field(default_factory=dict)

    def next(self, prefix: str) -> str:
        n = self.counters.get(prefix, 0)
        self.counters[prefix] = n + 1
        return f"_{prefix}_{n}"


class Compiler:
    """Compiles a list of ASTGraph into Graph objects."""

    def __init__(self, ast_graphs: list[ASTGraph], filename: str = "<string>"):
        self.ast_graphs = ast_graphs
        self.filename = filename
        # Collect all graph names for deferred resolution
        self.graph_names: set[str] = {g.name for g in ast_graphs}
        self.compiled: dict[str, Graph] = {}
        # Track graphs currently being compiled to detect recursive calls
        self._compiling: set[str] = set()

    def compile_all(self) -> dict[str, Graph]:
        for ast_g in self.ast_graphs:
            self.compiled[ast_g.name] = self._compile_graph(ast_g)
        return self.compiled

    def _compile_graph(self, ast_g: ASTGraph) -> Graph:
        if ast_g.name in self._compiling:
            raise GDSPCompileError(
                f"recursive graph reference: '{ast_g.name}' cannot call itself",
                filename=self.filename,
            )
        self._compiling.add(ast_g.name)
        try:
            return self._compile_graph_inner(ast_g)
        finally:
            self._compiling.discard(ast_g.name)

    def _compile_graph_inner(self, ast_g: ASTGraph) -> Graph:
        ctx = _GraphCtx(
            name=ast_g.name,
            options=ast_g.options,
            compiler=self,
            filename=self.filename,
        )

        # Implicit sr
        if "sr" in ast_g.options:
            ctx.nodes.append(SampleRate(id="sr"))
            ctx.defined_ids.add("sr")

        for stmt in ast_g.body:
            ctx.compile_stmt(stmt)

        sample_rate = float(ast_g.options.get("sr", 44100.0))
        control_interval = int(ast_g.options.get("control", 0))

        return Graph(
            name=ast_g.name,
            sample_rate=sample_rate,
            control_interval=control_interval,
            control_nodes=ctx.control_nodes,
            inputs=ctx.inputs,
            outputs=ctx.outputs,
            params=ctx.params,
            nodes=ctx.nodes,
        )


@dataclass
class _GraphCtx:
    """Compilation context for a single graph."""

    name: str
    options: dict[str, Union[str, float]]
    compiler: Compiler
    filename: str

    inputs: list[AudioInput] = field(default_factory=list)
    outputs: list[AudioOutput] = field(default_factory=list)
    params: list[Param] = field(default_factory=list)
    nodes: list[Node] = field(default_factory=list)
    control_nodes: list[str] = field(default_factory=list)
    defined_ids: set[str] = field(default_factory=set)
    id_counter: _IDCounter = field(default_factory=_IDCounter)
    # Track history declarations for feedback write resolution
    histories: dict[str, int] = field(default_factory=dict)  # name -> node index

    def _err(self, msg: str, line: int = 0) -> GDSPCompileError:
        return GDSPCompileError(msg, line=line, filename=self.filename)

    def _auto_id(self, prefix: str) -> str:
        return self.id_counter.next(prefix)

    def _add_node(self, node: Node) -> None:
        self.nodes.append(node)
        if hasattr(node, "id"):
            self.defined_ids.add(node.id)

    def compile_stmt(self, stmt: ASTStmt) -> None:
        if isinstance(stmt, ASTInDecl):
            for name in stmt.ids:
                self.inputs.append(AudioInput(id=name))
                self.defined_ids.add(name)

        elif isinstance(stmt, ASTOutDecl):
            source_ref = self._compile_expr(stmt.source)
            if isinstance(source_ref, (int, float)):
                # Wrap literal in a constant node
                cid = self._auto_id("const")
                self._add_node(Constant(id=cid, value=float(source_ref)))
                source_ref = cid
            self.outputs.append(AudioOutput(id=stmt.name, source=str(source_ref)))

        elif isinstance(stmt, ASTParamDecl):
            self.params.append(
                Param(
                    name=stmt.name,
                    min=stmt.min_val,
                    max=stmt.max_val,
                    default=max(stmt.min_val, min(stmt.max_val, stmt.default)),
                )
            )
            self.defined_ids.add(stmt.name)

        elif isinstance(stmt, ASTBufferDecl):
            self._add_node(
                Buffer(id=stmt.name, size=stmt.size, fill=stmt.fill)  # type: ignore[arg-type]
            )

        elif isinstance(stmt, ASTDelayDecl):
            self._add_node(DelayLine(id=stmt.name, max_samples=stmt.max_samples))

        elif isinstance(stmt, ASTHistoryDecl):
            # Add placeholder History node (input filled by feedback write)
            idx = len(self.nodes)
            self._add_node(History(id=stmt.name, init=stmt.init, input="__pending__"))
            self.histories[stmt.name] = idx

        elif isinstance(stmt, ASTFeedbackWrite):
            value_ref = self._compile_expr(stmt.value)
            if stmt.name not in self.histories:
                raise self._err(
                    f"feedback write to undeclared history '{stmt.name}'",
                    stmt.line,
                )
            idx = self.histories[stmt.name]
            old = self.nodes[idx]
            assert isinstance(old, History)
            self.nodes[idx] = History(
                id=old.id, init=old.init, input=str(self._ref_to_str(value_ref))
            )

        elif isinstance(stmt, ASTDelayWriteStmt):
            value_ref = self._compile_expr(stmt.value)
            dw_id = self._auto_id("dw")
            self._add_node(
                DelayWrite(
                    id=dw_id,
                    delay=stmt.delay,
                    value=self._to_ref(value_ref),
                )
            )

        elif isinstance(stmt, ASTBufWriteStmt):
            index_ref = self._compile_expr(stmt.index)
            value_ref = self._compile_expr(stmt.value)
            bw_id = self._auto_id("bw")
            cls = BufWrite if stmt.op == "buf_write" else Splat
            self._add_node(
                cls(
                    id=bw_id,
                    buffer=stmt.buffer,
                    index=self._to_ref(index_ref),
                    value=self._to_ref(value_ref),
                )
            )

        elif isinstance(stmt, ASTAssign):
            self._compile_assign(stmt)

        elif isinstance(stmt, ASTImportAssign):
            raise self._err("external imports not yet supported", stmt.line)

        else:
            raise self._err(f"unknown statement type: {type(stmt).__name__}")

    def _compile_assign(self, stmt: ASTAssign) -> None:
        targets = stmt.targets

        # Check for gate_route destructuring
        if len(targets) > 1:
            if not isinstance(stmt.value, ASTCall):
                raise self._err(
                    "destructuring assignment requires a function call",
                    stmt.line,
                )
            if stmt.value.name != "gate_route":
                raise self._err(
                    f"destructuring only supported for gate_route, got '{stmt.value.name}'",
                    stmt.line,
                )
            self._compile_gate_route_destructure(targets, stmt.value, stmt)
            return

        target = targets[0]
        value_ref = self._compile_expr(stmt.value, target_id=target)
        # If the expression already produced a node with the target ID, we're done.
        if isinstance(value_ref, str) and value_ref == target:
            pass
        else:
            # Need to alias: create a Pass node or rename
            # Check if the last added node can be renamed
            if isinstance(value_ref, (int, float)):
                self._add_node(Constant(id=target, value=float(value_ref)))
            elif isinstance(value_ref, str) and value_ref != target:
                # If the expression was a simple reference, create a Pass node
                # But if it was the ID of a node we just created, try to rename
                if self._try_rename_last_node(value_ref, target):
                    pass
                else:
                    self._add_node(Pass(id=target, a=value_ref))

        if stmt.control:
            self.control_nodes.append(target)

    def _try_rename_last_node(self, old_id: str, new_id: str) -> bool:
        """Try to rename the last added node from old_id to new_id."""
        if not self.nodes:
            return False
        last = self.nodes[-1]
        if hasattr(last, "id") and last.id == old_id:
            # Reconstruct with new id
            data = last.model_dump()
            data["id"] = new_id
            self.defined_ids.discard(old_id)
            self.nodes[-1] = type(last)(**data)
            self.defined_ids.add(new_id)
            return True
        return False

    def _compile_gate_route_destructure(
        self,
        targets: list[str],
        call: ASTCall,
        stmt: ASTAssign,
    ) -> None:
        # Resolve args
        pos_args, kw_args = self._split_args(call.args)
        if len(pos_args) < 3:
            raise self._err(
                "gate_route requires 3 positional args: signal, index, count",
                stmt.line,
            )
        signal_ref = self._compile_expr(pos_args[0])
        index_ref = self._compile_expr(pos_args[1])
        count_expr = pos_args[2]
        if not isinstance(count_expr, ASTNumber):
            raise self._err("gate_route count must be a literal integer", stmt.line)
        count = int(count_expr.value)

        if len(targets) != count:
            raise self._err(
                f"gate_route destructuring: {len(targets)} targets but count={count}",
                stmt.line,
            )

        gate_id = self._auto_id("gate")
        self._add_node(
            GateRoute(
                id=gate_id,
                a=self._to_ref(signal_ref),
                index=self._to_ref(index_ref),
                count=count,
            )
        )

        for i, t in enumerate(targets):
            self._add_node(GateOut(id=t, gate=gate_id, channel=i + 1))

    def _compile_expr(self, expr: ASTExpr, target_id: str | None = None) -> str | float:
        """Compile an expression, returning a Ref (node ID or float literal).

        If target_id is provided, the outermost node gets that ID instead of
        an auto-generated one.
        """
        if isinstance(expr, ASTNumber):
            return expr.value

        if isinstance(expr, ASTIdent):
            name = expr.name
            # Named constants
            if name in _NAMED_CONSTANTS:
                nid = target_id or self._auto_id(name)
                self._add_node(NamedConstant(id=nid, op=name))  # type: ignore[arg-type]
                return nid
            # Otherwise it's a reference to an existing name
            return name

        if isinstance(expr, ASTBinExpr):
            left = self._compile_expr(expr.left)
            right = self._compile_expr(expr.right)
            nid = target_id or self._auto_id(expr.op)

            # Comparison ops -> Compare
            if expr.op in ("gt", "lt", "gte", "lte", "eq", "neq"):
                self._add_node(
                    Compare(
                        id=nid,
                        op=expr.op,  # type: ignore[arg-type]
                        a=self._to_ref(left),
                        b=self._to_ref(right),
                    )
                )
            else:
                self._add_node(
                    BinOp(
                        id=nid,
                        op=expr.op,  # type: ignore[arg-type]
                        a=self._to_ref(left),
                        b=self._to_ref(right),
                    )
                )
            return nid

        if isinstance(expr, ASTUnaryExpr):
            operand = self._compile_expr(expr.operand)
            nid = target_id or self._auto_id(expr.op)
            self._add_node(
                UnaryOp(
                    id=nid,
                    op=expr.op,  # type: ignore[arg-type]
                    a=self._to_ref(operand),
                )
            )
            return nid

        if isinstance(expr, ASTCall):
            return self._compile_call(expr, target_id)

        if isinstance(expr, ASTDotAccess):
            obj_ref = self._compile_expr(expr.obj)
            # Dot access on subgraph output: "subgraph_id.output_name"
            return f"{obj_ref}.{expr.field_name}"

        if isinstance(expr, ASTCompose):
            return self._compile_compose(expr, target_id)

        raise self._err(f"unknown expression type: {type(expr).__name__}")

    def _compile_call(self, call: ASTCall, target_id: str | None = None) -> str | float:
        name = call.name
        pos_args, kw_args = self._split_args(call.args)

        # Deferred resolution: check graph names first
        if name in self.compiler.graph_names:
            return self._compile_subgraph_call(name, pos_args, kw_args, target_id)

        # Unary ops
        if name in _UNARY_OPS:
            if len(pos_args) != 1:
                raise self._err(f"'{name}' expects 1 argument, got {len(pos_args)}")
            a_ref = self._compile_expr(pos_args[0])
            nid = target_id or self._auto_id(name)
            self._add_node(
                UnaryOp(id=nid, op=name, a=self._to_ref(a_ref))  # type: ignore[arg-type]
            )
            return nid

        # Binary ops via function call
        if name in _BINOP_FUNCS:
            if len(pos_args) != 2:
                raise self._err(f"'{name}' expects 2 arguments, got {len(pos_args)}")
            a_ref = self._compile_expr(pos_args[0])
            b_ref = self._compile_expr(pos_args[1])
            nid = target_id or self._auto_id(name)
            self._add_node(
                BinOp(
                    id=nid,
                    op=name,  # type: ignore[arg-type]
                    a=self._to_ref(a_ref),
                    b=self._to_ref(b_ref),
                )
            )
            return nid

        # gate_route (non-destructuring, standalone)
        if name == "gate_route":
            return self._compile_gate_route_call(pos_args, kw_args, target_id)

        # gate_out
        if name == "gate_out":
            if len(pos_args) != 2:
                raise self._err("gate_out expects 2 args: gate_node, channel")
            gate_ref = self._compile_expr(pos_args[0])
            ch_expr = pos_args[1]
            if not isinstance(ch_expr, ASTNumber):
                raise self._err("gate_out channel must be a literal integer")
            nid = target_id or self._auto_id("gate_out")
            self._add_node(
                GateOut(
                    id=nid,
                    gate=str(self._ref_to_str(gate_ref)),
                    channel=int(ch_expr.value),
                )
            )
            return nid

        # selector (variadic)
        if name == "selector":
            return self._compile_selector(pos_args, kw_args, target_id)

        # delay_read (special syntax already parsed with delay name injected)
        if name == "delay_read":
            return self._compile_delay_read(pos_args, kw_args, target_id)

        # Builtins registry
        if name in _BUILTINS:
            return self._compile_builtin(name, pos_args, kw_args, target_id)

        raise self._err(f"undefined function '{name}'")

    def _compile_subgraph_call(
        self,
        graph_name: str,
        pos_args: list[ASTExpr],
        kw_args: dict[str, ASTExpr],
        target_id: str | None = None,
    ) -> str:
        # Compile the referenced graph if not already done
        if graph_name not in self.compiler.compiled:
            # Find the AST and compile it
            ast_g = next(g for g in self.compiler.ast_graphs if g.name == graph_name)
            self.compiler.compiled[graph_name] = self.compiler._compile_graph(ast_g)
        sub_graph = self.compiler.compiled[graph_name]

        nid = target_id or self._auto_id(graph_name)

        # Map keyword args to inputs and params
        input_names = {inp.id for inp in sub_graph.inputs}
        param_names = {p.name for p in sub_graph.params}

        inputs_map: dict[str, str | float] = {}
        params_map: dict[str, str | float] = {}

        for k, v_expr in kw_args.items():
            v_ref = self._compile_expr(v_expr)
            if k in input_names:
                inputs_map[k] = self._to_ref(v_ref)
            elif k in param_names:
                params_map[k] = self._to_ref(v_ref)
            else:
                raise self._err(f"subgraph '{graph_name}' has no input or param '{k}'")

        # Determine output (first output by default)
        output = sub_graph.outputs[0].id if sub_graph.outputs else ""

        self._add_node(
            Subgraph(
                id=nid,
                graph=sub_graph,
                inputs=inputs_map,
                params=params_map,
                output=output,
            )
        )
        return nid

    def _compile_gate_route_call(
        self,
        pos_args: list[ASTExpr],
        kw_args: dict[str, ASTExpr],
        target_id: str | None = None,
    ) -> str:
        if len(pos_args) < 3:
            raise self._err(
                "gate_route requires 3 positional args: signal, index, count"
            )
        signal_ref = self._compile_expr(pos_args[0])
        index_ref = self._compile_expr(pos_args[1])
        count_expr = pos_args[2]
        if not isinstance(count_expr, ASTNumber):
            raise self._err("gate_route count must be a literal integer")
        nid = target_id or self._auto_id("gate")
        self._add_node(
            GateRoute(
                id=nid,
                a=self._to_ref(signal_ref),
                index=self._to_ref(index_ref),
                count=int(count_expr.value),
            )
        )
        return nid

    def _compile_selector(
        self,
        pos_args: list[ASTExpr],
        kw_args: dict[str, ASTExpr],
        target_id: str | None = None,
    ) -> str:
        if len(pos_args) < 2:
            raise self._err("selector requires at least 2 args: index + inputs")

        # First arg is index, rest are inputs
        index_ref = self._compile_expr(pos_args[0])
        input_refs = [self._to_ref(self._compile_expr(a)) for a in pos_args[1:]]

        # Check for 'index' keyword arg
        if "index" in kw_args:
            index_ref = self._compile_expr(kw_args["index"])

        nid = target_id or self._auto_id("sel")
        self._add_node(
            Selector(
                id=nid,
                index=self._to_ref(index_ref),
                inputs=input_refs,
            )
        )
        return nid

    def _compile_delay_read(
        self,
        pos_args: list[ASTExpr],
        kw_args: dict[str, ASTExpr],
        target_id: str | None = None,
    ) -> str:
        # pos_args[0] is the delay name (injected by parser as ASTIdent)
        if len(pos_args) < 2:
            raise self._err("delay_read requires delay name and tap position")
        delay_name_expr = pos_args[0]
        if not isinstance(delay_name_expr, ASTIdent):
            raise self._err("delay_read first arg must be delay line name")
        delay_name = delay_name_expr.name

        tap_ref = self._compile_expr(pos_args[1])

        interp = "none"
        if "interp" in kw_args:
            interp_expr = kw_args["interp"]
            if isinstance(interp_expr, ASTIdent):
                interp = interp_expr.name
            else:
                raise self._err("delay_read interp must be an identifier")

        nid = target_id or self._auto_id("dr")
        self._add_node(
            DelayRead(
                id=nid,
                delay=delay_name,
                tap=self._to_ref(tap_ref),
                interp=interp,  # type: ignore[arg-type]
            )
        )
        return nid

    def _compile_builtin(
        self,
        name: str,
        pos_args: list[ASTExpr],
        kw_args: dict[str, ASTExpr],
        target_id: str | None = None,
    ) -> str:
        cls, field_names, fixed_kw = _BUILTINS[name]
        nid = target_id or self._auto_id(name)

        kwargs: dict[str, object] = {"id": nid}
        kwargs.update(fixed_kw)

        # Map positional args
        for i, field_name in enumerate(field_names):
            if i < len(pos_args):
                val = self._compile_expr(pos_args[i])
                if field_name in _STR_REF_FIELDS:
                    kwargs[field_name] = str(self._ref_to_str(val))
                else:
                    kwargs[field_name] = self._to_ref(val)

        # Map keyword args
        for k, v_expr in kw_args.items():
            val = self._compile_expr(v_expr)
            if k in _STR_REF_FIELDS:
                kwargs[k] = str(self._ref_to_str(val))
            elif k == "interp" or k == "mode":
                # String-valued keyword
                if isinstance(v_expr, ASTIdent):
                    kwargs[k] = v_expr.name
                else:
                    kwargs[k] = str(self._ref_to_str(val))
            else:
                kwargs[k] = self._to_ref(val)

        self._add_node(cls(**kwargs))
        return nid

    def _compile_compose(self, expr: ASTCompose, target_id: str | None = None) -> str:
        """Compile >> (series) or // (parallel) composition."""
        left_graph = self._expr_to_graph(expr.left)
        right_graph = self._expr_to_graph(expr.right)

        if expr.op == ">>":
            result = _algebra_series(left_graph, right_graph)
        else:
            result = _algebra_parallel(left_graph, right_graph)

        nid = target_id or self._auto_id("comp")

        # Wrap result graph as a subgraph node
        # Wire outer inputs from calling graph namespace
        inputs_map: dict[str, str | float] = {}
        for inp in result.inputs:
            inputs_map[inp.id] = inp.id

        params_map: dict[str, str | float] = {}
        for p in result.params:
            params_map[p.name] = p.name

        output = result.outputs[0].id if result.outputs else ""

        self._add_node(
            Subgraph(
                id=nid,
                graph=result,
                inputs=inputs_map,
                params=params_map,
                output=output,
            )
        )
        return nid

    def _expr_to_graph(self, expr: ASTExpr) -> Graph:
        """Convert an expression to a Graph for composition.

        Handles: graph function calls (partially applied) and nested compositions.
        """
        if isinstance(expr, ASTCall):
            name = expr.name
            if name in self.compiler.graph_names:
                # Compile the graph
                if name not in self.compiler.compiled:
                    ast_g = next(g for g in self.compiler.ast_graphs if g.name == name)
                    self.compiler.compiled[name] = self.compiler._compile_graph(ast_g)
                sub_graph = self.compiler.compiled[name]

                # Apply keyword args as param overrides
                _, kw_args = self._split_args(expr.args)
                # For composition, we return the graph itself with param defaults
                # overridden. The algebra functions handle the wiring.
                if kw_args:
                    # Create a modified graph with adjusted param defaults
                    new_params = []
                    for p in sub_graph.params:
                        if p.name in kw_args:
                            kw_expr = kw_args[p.name]
                            val = self._compile_expr(kw_expr)
                            if isinstance(val, (int, float)):
                                new_params.append(
                                    Param(
                                        name=p.name,
                                        min=p.min,
                                        max=p.max,
                                        default=float(val),
                                    )
                                )
                            else:
                                new_params.append(p)
                        else:
                            new_params.append(p)
                    return Graph(
                        name=sub_graph.name,
                        sample_rate=sub_graph.sample_rate,
                        control_interval=sub_graph.control_interval,
                        control_nodes=sub_graph.control_nodes,
                        inputs=sub_graph.inputs,
                        outputs=sub_graph.outputs,
                        params=new_params,
                        nodes=sub_graph.nodes,
                    )
                return sub_graph
            raise self._err(f"'{name}' is not a graph (cannot compose)")

        if isinstance(expr, ASTCompose):
            left_graph = self._expr_to_graph(expr.left)
            right_graph = self._expr_to_graph(expr.right)
            if expr.op == ">>":
                return _algebra_series(left_graph, right_graph)
            return _algebra_parallel(left_graph, right_graph)

        if isinstance(expr, ASTIdent):
            name = expr.name
            if name in self.compiler.graph_names:
                if name not in self.compiler.compiled:
                    ast_g = next(g for g in self.compiler.ast_graphs if g.name == name)
                    self.compiler.compiled[name] = self.compiler._compile_graph(ast_g)
                return self.compiler.compiled[name]
            raise self._err(f"'{name}' is not a graph (cannot compose)")

        raise self._err(f"cannot use {type(expr).__name__} in composition expression")

    def _split_args(
        self, args: list[ASTArg]
    ) -> tuple[list[ASTExpr], dict[str, ASTExpr]]:
        """Split argument list into positional and keyword args."""
        pos: list[ASTExpr] = []
        kw: dict[str, ASTExpr] = {}
        for arg in args:
            if arg.name is not None:
                kw[arg.name] = arg.value
            else:
                pos.append(arg.value)
        return pos, kw

    def _to_ref(self, val: str | float) -> str | float:
        """Convert compiler result to a Ref value."""
        return val

    def _ref_to_str(self, val: str | float) -> str:
        """Convert a ref to string (for fields that need str, not Ref)."""
        if isinstance(val, str):
            return val
        return str(val)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse(source: str, *, filename: str = "<string>") -> Graph:
    """Parse GDSP source and return a single Graph.

    If the source contains multiple graphs, returns the last one
    (typically the "main" graph that uses the others as subgraphs).
    """
    tokens = tokenize(source, filename)
    parser = Parser(tokens, filename)
    ast_graphs = parser.parse_file()
    if not ast_graphs:
        raise GDSPSyntaxError("no graph definitions found", filename=filename)
    compiler = Compiler(ast_graphs, filename)
    compiled = compiler.compile_all()
    # Return the last graph
    return compiled[ast_graphs[-1].name]


def parse_multi(source: str, *, filename: str = "<string>") -> dict[str, Graph]:
    """Parse GDSP source and return all graphs as a dict."""
    tokens = tokenize(source, filename)
    parser = Parser(tokens, filename)
    ast_graphs = parser.parse_file()
    if not ast_graphs:
        raise GDSPSyntaxError("no graph definitions found", filename=filename)
    compiler = Compiler(ast_graphs, filename)
    return compiler.compile_all()


def parse_file(path: str | Path, *, multi: bool = False) -> Graph | dict[str, Graph]:
    """Parse a .gdsp file.

    Args:
        path: Path to the .gdsp file.
        multi: If True, return dict of all graphs. If False, return last graph.
    """
    p = Path(path)
    source = p.read_text()
    filename = str(p)
    if multi:
        return parse_multi(source, filename=filename)
    return parse(source, filename=filename)
