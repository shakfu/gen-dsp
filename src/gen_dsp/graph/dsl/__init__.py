"""GDSP DSL: parse .gdsp source into a Graph."""

from __future__ import annotations

from collections.abc import Mapping
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
from gen_dsp.graph.dsl.lower import Compiler
from gen_dsp.graph.dsl.parser import (
    ASTArg,
    ASTAssign,
    ASTBinExpr,
    ASTBufferDecl,
    ASTBufWriteStmt,
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
from gen_dsp.graph.models import Graph

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse(
    source: str,
    *,
    filename: str = "<string>",
    import_roots: Mapping[str, str | Path] | None = None,
    allow_paths: bool | None = None,
) -> Graph:
    """Parse GDSP source and return a single Graph.

    If the source contains multiple graphs, returns the last one
    (typically the "main" graph that uses the others as subgraphs).
    See ``parse_multi`` for ``import_roots`` and ``allow_paths``.
    """
    compiled, last = _compile(source, filename, import_roots, allow_paths)
    return compiled[last]


def parse_multi(
    source: str,
    *,
    filename: str = "<string>",
    import_roots: Mapping[str, str | Path] | None = None,
    allow_paths: bool | None = None,
) -> dict[str, Graph]:
    """Parse GDSP source and return all graphs as a dict.

    Args:
        import_roots: Directories for ``import "<root>:<relpath>"``. An
            import must resolve inside its root, symlinks included.
        allow_paths: Allow plain relative and absolute import paths. Defaults
            to True without roots and False with them; pass roots and leave
            this False for untrusted source.
    """
    return _compile(source, filename, import_roots, allow_paths)[0]


def parse_file(
    path: str | Path,
    *,
    multi: bool = False,
    import_roots: Mapping[str, str | Path] | None = None,
) -> Graph | dict[str, Graph]:
    """Parse a .gdsp file.

    Args:
        path: Path to the .gdsp file.
        multi: If True, return dict of all graphs. If False, return last graph.
        import_roots: Defaults to the ``std`` and ``user`` library roots.
            Plain import paths stay allowed.
    """
    from gen_dsp.library import default_import_roots

    p = Path(path)
    source = p.read_text(encoding="utf-8")
    filename = str(p)
    roots = default_import_roots() if import_roots is None else import_roots
    compiled, last = _compile(source, filename, roots, True)
    return compiled if multi else compiled[last]


def _compile(
    source: str,
    filename: str,
    import_roots: Mapping[str, str | Path] | None,
    allow_paths: bool | None,
) -> tuple[dict[str, Graph], str]:
    """Compile source; return all graphs and the name of the last one defined."""
    tokens = tokenize(source, filename)
    ast_graphs = Parser(tokens, filename).parse_file()
    if not ast_graphs:
        raise GDSPSyntaxError("no graph definitions found", filename=filename)
    compiler = Compiler(
        ast_graphs, filename, import_roots=import_roots, allow_paths=allow_paths
    )
    return compiler.compile_all(), ast_graphs[-1].name


__all__ = [
    "EOF",
    "IDENT",
    "NEWLINE",
    "NUMBER",
    "OP",
    "STRING",
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
    "GDSPCompileError",
    "GDSPSyntaxError",
    "Parser",
    "Token",
    "parse",
    "parse_file",
    "parse_multi",
    "tokenize",
]
