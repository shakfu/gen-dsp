"""The .gdsp example and component library.

Two import roots: ``std`` (this package: ``examples/`` and
``components/<category>/``) and ``user`` (``user_library_dir()``). Sources
reach them as ``import "std:components/filters/lpf.gdsp":lpf(...)``.
``library_index()`` is the JSON that ``gen-dsp library --json`` prints.
"""

from __future__ import annotations

import os
import platform
import re
import tempfile
from pathlib import Path
from typing import Any

from gen_dsp.version import __version__

# Bump on any incompatible change to the index JSON shape.
SCHEMA_VERSION = 1

STD_DIR = Path(__file__).resolve().parent

# Names usable as a component file name, graph name and category directory.
_NAME = re.compile(r"[a-z_][a-z0-9_]*")


def user_library_dir() -> Path:
    """Return the user library directory (``GEN_DSP_LIBRARY_DIR`` overrides).

    - macOS:   ~/Library/Application Support/gen-dsp/library/
    - Linux:   $XDG_DATA_HOME/gen-dsp/library/ (defaults to ~/.local/share/)
    - Windows: %APPDATA%/gen-dsp/library/
    """
    env = os.environ.get("GEN_DSP_LIBRARY_DIR")
    if env:
        return Path(env)
    system = platform.system()
    if system == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    elif system == "Windows":
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    else:
        xdg = os.environ.get("XDG_DATA_HOME")
        base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "gen-dsp" / "library"


def default_import_roots() -> dict[str, Path]:
    """Return the ``std`` and ``user`` import roots."""
    return {"std": STD_DIR, "user": user_library_dir()}


def _description(source: str) -> str:
    """Join the leading ``#`` comment block into one line."""
    lines = []
    for line in source.splitlines():
        stripped = line.strip()
        if not stripped.startswith("#"):
            break
        lines.append(stripped.lstrip("#").strip())
    return " ".join(x for x in lines if x)


def _entry(root: str, base: Path, path: Path) -> dict[str, Any]:
    from gen_dsp.graph.dsl import GDSPCompileError, GDSPSyntaxError, parse

    rel = path.relative_to(base).as_posix()
    parts = rel.split("/")
    if root == "std":
        kind = "example" if parts[0] == "examples" else "component"
        category = parts[1] if kind == "component" and len(parts) > 2 else ""
    else:
        kind = "component"
        category = parts[0] if len(parts) > 1 else ""
    source = path.read_text(encoding="utf-8")
    entry: dict[str, Any] = {
        "id": f"{root}:{rel.removesuffix('.gdsp')}",
        "root": root,
        "file": rel,
        "kind": kind,
        "category": category,
        "description": _description(source),
    }
    try:
        g = parse(source, filename=f"{root}:{rel}", import_roots=default_import_roots())
    except (GDSPSyntaxError, GDSPCompileError, ValueError) as e:
        # A broken user file must not hide the rest of the index.
        entry["error"] = str(e)
        return entry
    args = [f"{i.id}={i.id}" for i in g.inputs]
    args += [f"{p.name}={p.default:g}" for p in g.params]
    entry.update(
        graph=g.name,
        inputs=[i.id for i in g.inputs],
        outputs=[o.id for o in g.outputs],
        params=[
            {"name": p.name, "min": p.min, "max": p.max, "default": p.default}
            for p in g.params
        ],
        import_expr=f'import "{root}:{rel}":{g.name}({", ".join(args)})',
    )
    return entry


def library_index() -> dict[str, Any]:
    """Return every library file in the ``std`` and ``user`` roots.

    Each entry describes the file's last graph, as ``parse`` returns it.
    Entries whose file fails to parse carry an ``error`` instead.
    """
    entries = []
    for root, base in default_import_roots().items():
        if base.is_dir():
            for path in sorted(base.rglob("*.gdsp")):
                entries.append(_entry(root, base, path))
    return {
        "schema_version": SCHEMA_VERSION,
        "gen_dsp_version": __version__,
        "entries": entries,
    }


def save_user_component(
    name: str, source: str, *, category: str = "", overwrite: bool = False
) -> Path:
    """Validate ``source`` and write it to the user library.

    The file is ``<user dir>/[<category>/]<name>.gdsp``. ``source`` must parse
    with root imports only, pass graph validation, and define ``name`` as its
    last graph.

    Raises:
        ValueError: Bad name or category, or invalid source.
        FileExistsError: The component exists and ``overwrite`` is False.
    """
    from gen_dsp.graph.dsl import GDSPCompileError, GDSPSyntaxError, parse
    from gen_dsp.graph.validate import validate_graph

    for label, value in (("name", name), ("category", category)):
        if (value or label == "name") and not _NAME.fullmatch(value):
            raise ValueError(f"{label} must match [a-z_][a-z0-9_]*: {value!r}")
    try:
        graph = parse(
            source, filename=f"user:{name}", import_roots=default_import_roots()
        )
    except (GDSPSyntaxError, GDSPCompileError) as e:
        raise ValueError(str(e)) from e
    if graph.name != name:
        raise ValueError(f"the last graph is '{graph.name}', expected '{name}'")
    errors = validate_graph(graph)
    if errors:
        raise ValueError("; ".join(errors))

    directory = user_library_dir() / category
    target = directory / f"{name}.gdsp"
    if target.exists() and not overwrite:
        raise FileExistsError(f"user component exists: {target}")
    directory.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(source)
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return target
