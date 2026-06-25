"""GDSP DSL: parse .gdsp source into a Graph."""

from __future__ import annotations

from pathlib import Path

from gen_dsp.graph.dsl.lexer import (
    EOF,
    IDENT,
    NEWLINE,
    NUMBER,
    OP,
    STRING,
    GDSPCompileError,
    GDSPSyntaxError,
    Token,
    tokenize,
)
from gen_dsp.graph.dsl.parser import (
    ASTArg,
    ASTAssign,
    ASTBinExpr,
    ASTBufWriteStmt,
    ASTBufferDecl,
    ASTCall,
    ASTCompose,
    ASTDelayDecl,
    ASTDelayWriteStmt,
    ASTDotAccess,
    ASTFeedbackWrite,
    ASTGraph,
    ASTHistoryDecl,
    ASTIdent,
    ASTImportAssign,
    ASTInDecl,
    ASTNumber,
    ASTOutDecl,
    ASTParamDecl,
    ASTUnaryExpr,
    Parser,
)
from gen_dsp.graph.dsl.lower import Compiler
from gen_dsp.graph.models import Graph


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
    source = p.read_text(encoding="utf-8")
    filename = str(p)
    if multi:
        return parse_multi(source, filename=filename)
    return parse(source, filename=filename)


__all__ = [
    "EOF",
    "IDENT",
    "NEWLINE",
    "NUMBER",
    "OP",
    "STRING",
    "GDSPCompileError",
    "GDSPSyntaxError",
    "Token",
    "tokenize",
    "ASTArg",
    "ASTAssign",
    "ASTBinExpr",
    "ASTBufWriteStmt",
    "ASTBufferDecl",
    "ASTCall",
    "ASTCompose",
    "ASTDelayDecl",
    "ASTDelayWriteStmt",
    "ASTDotAccess",
    "ASTFeedbackWrite",
    "ASTGraph",
    "ASTHistoryDecl",
    "ASTIdent",
    "ASTImportAssign",
    "ASTInDecl",
    "ASTNumber",
    "ASTOutDecl",
    "ASTParamDecl",
    "ASTUnaryExpr",
    "Parser",
    "parse",
    "parse_multi",
    "parse_file",
]
