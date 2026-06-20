"""AST definitions and recursive-descent parser for the GDSP DSL."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union

from gen_dsp.graph.dsl.lexer import (
    EOF,
    IDENT,
    NEWLINE,
    NUMBER,
    OP,
    STRING,
    GDSPSyntaxError,
    Token,
)


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
    line: int = 0
    col: int = 0


@dataclass
class ASTIdent:
    name: str
    line: int = 0
    col: int = 0


@dataclass
class ASTBinExpr:
    op: str
    left: ASTExpr
    right: ASTExpr
    line: int = 0
    col: int = 0


@dataclass
class ASTUnaryExpr:
    op: str
    operand: ASTExpr
    line: int = 0
    col: int = 0


@dataclass
class ASTCall:
    name: str
    args: list[ASTArg]
    line: int = 0
    col: int = 0


@dataclass
class ASTDotAccess:
    obj: ASTExpr
    field_name: str
    line: int = 0
    col: int = 0


@dataclass
class ASTCompose:
    op: str  # ">>" or "//"
    left: ASTExpr
    right: ASTExpr
    line: int = 0
    col: int = 0


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
            op_tok = self._advance()
            right = self._parse_comparison()
            left = ASTCompose(
                op=op_tok.value,
                left=left,
                right=right,
                line=op_tok.line,
                col=op_tok.col,
            )
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
            op_tok = self._advance()
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
            left = ASTBinExpr(
                op=op_map[op_tok.value],
                left=left,
                right=right,
                line=op_tok.line,
                col=op_tok.col,
            )
        return left

    def _parse_addition(self) -> ASTExpr:
        left = self._parse_multiply()
        while self._at(OP, "+") or self._at(OP, "-"):
            op_tok = self._advance()
            op_name = "add" if op_tok.value == "+" else "sub"
            right = self._parse_multiply()
            left = ASTBinExpr(
                op=op_name, left=left, right=right, line=op_tok.line, col=op_tok.col
            )
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
            op_tok = self._advance()
            op_map = {"*": "mul", "/": "div", "%": "mod"}
            right = self._parse_power()
            left = ASTBinExpr(
                op=op_map[op_tok.value],
                left=left,
                right=right,
                line=op_tok.line,
                col=op_tok.col,
            )
        return left

    def _parse_power(self) -> ASTExpr:
        base = self._parse_unary()
        if self._at(OP, "**"):
            op_tok = self._advance()
            exp = self._parse_power()  # right-assoc
            base = ASTBinExpr(
                op="pow", left=base, right=exp, line=op_tok.line, col=op_tok.col
            )
        return base

    def _parse_unary(self) -> ASTExpr:
        if self._at(OP, "-"):
            op_tok = self._advance()
            operand = self._parse_unary()
            # Fold constant negation
            if isinstance(operand, ASTNumber):
                return ASTNumber(value=-operand.value, line=op_tok.line, col=op_tok.col)
            return ASTUnaryExpr(
                op="neg", operand=operand, line=op_tok.line, col=op_tok.col
            )
        return self._parse_postfix()

    def _parse_postfix(self) -> ASTExpr:
        expr = self._parse_atom()
        while self._at(OP, "."):
            dot_tok = self._advance()
            field = self._expect(IDENT).value
            expr = ASTDotAccess(
                obj=expr, field_name=field, line=dot_tok.line, col=dot_tok.col
            )
        return expr

    def _parse_atom(self) -> ASTExpr:
        tok = self._peek()

        # Number
        if tok.type == NUMBER:
            self._advance()
            return ASTNumber(value=float(tok.value), line=tok.line, col=tok.col)

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
                return ASTCall(name=tok.value, args=args, line=tok.line, col=tok.col)
            return ASTIdent(name=tok.value, line=tok.line, col=tok.col)

        raise GDSPSyntaxError(
            f"unexpected token {tok.value!r} in expression",
            tok.line,
            tok.col,
            self.filename,
        )

    def _parse_delay_read_expr(self) -> ASTCall:
        """Parse: delay_read NAME (args)"""
        tok = self._advance()  # consume 'delay_read'
        name_tok = self._expect(IDENT)
        self._expect(OP, "(")
        args: list[ASTArg] = []
        # Inject delay name as first positional arg
        args.append(
            ASTArg(
                name=None,
                value=ASTIdent(
                    name=name_tok.value, line=name_tok.line, col=name_tok.col
                ),
            )
        )
        if not self._at(OP, ")"):
            args.extend(self._parse_arg_list())
        self._expect(OP, ")")
        return ASTCall(name="delay_read", args=args, line=tok.line, col=tok.col)

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
