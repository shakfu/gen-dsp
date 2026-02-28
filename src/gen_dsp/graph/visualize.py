"""Graphviz DOT visualization for DSP graphs."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from gen_dsp.graph._deps import is_feedback_edge
from gen_dsp.graph.models import (
    SVF,
    Accum,
    Allpass,
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
    DCBlock,
    DelayLine,
    DelayRead,
    DelayWrite,
    Delta,
    Fold,
    Graph,
    History,
    Latch,
    Mix,
    Noise,
    OnePole,
    Peek,
    Phasor,
    PulseOsc,
    RateDiv,
    SampleHold,
    SawOsc,
    Scale,
    Select,
    SinOsc,
    SmoothParam,
    Subgraph,
    TriOsc,
    UnaryOp,
    Wrap,
)


def _node_attrs(node: object) -> tuple[str, str, str]:
    """Return (shape, fillcolor, label) for a graph node."""
    if isinstance(node, BinOp):
        return "box", "#fff3cd", f"{node.id}\\n{node.op}"
    if isinstance(node, UnaryOp):
        return "box", "#fff3cd", f"{node.id}\\n{node.op}"
    if isinstance(node, Clamp):
        return "box", "#fff3cd", f"{node.id}\\nclamp"
    if isinstance(node, Constant):
        return "box", "#e9ecef", f"{node.id}\\n{node.value}"
    if isinstance(node, History):
        return "box", "#fde0c8", f"{node.id}\\nz^-1"
    if isinstance(node, DelayLine):
        return "box3d", "#fde0c8", f"{node.id}\\ndelay[{node.max_samples}]"
    if isinstance(node, DelayRead):
        return "box", "#fde0c8", f"{node.id}\\nread"
    if isinstance(node, DelayWrite):
        return "box", "#fde0c8", f"{node.id}\\nwrite"
    if isinstance(node, Phasor):
        return "box", "#e2d5f1", f"{node.id}\\nphasor"
    if isinstance(node, Noise):
        return "box", "#e2d5f1", f"{node.id}\\nnoise"
    if isinstance(node, Compare):
        return "diamond", "#fff3cd", f"{node.id}\\n{node.op}"
    if isinstance(node, Select):
        return "diamond", "#fff3cd", f"{node.id}\\nselect"
    if isinstance(node, Wrap):
        return "box", "#fff3cd", f"{node.id}\\nwrap"
    if isinstance(node, Fold):
        return "box", "#fff3cd", f"{node.id}\\nfold"
    if isinstance(node, Mix):
        return "box", "#fff3cd", f"{node.id}\\nmix"
    if isinstance(node, Delta):
        return "box", "#fde0c8", f"{node.id}\\ndelta"
    if isinstance(node, Change):
        return "box", "#fde0c8", f"{node.id}\\nchange"
    if isinstance(node, Biquad):
        return "box", "#fde0c8", f"{node.id}\\nbiquad"
    if isinstance(node, SVF):
        return "box", "#fde0c8", f"{node.id}\\nsvf({node.mode})"
    if isinstance(node, OnePole):
        return "box", "#fde0c8", f"{node.id}\\nonepole"
    if isinstance(node, DCBlock):
        return "box", "#fde0c8", f"{node.id}\\ndcblock"
    if isinstance(node, Allpass):
        return "box", "#fde0c8", f"{node.id}\\nallpass"
    if isinstance(node, SinOsc):
        return "box", "#e2d5f1", f"{node.id}\\nsinosc"
    if isinstance(node, TriOsc):
        return "box", "#e2d5f1", f"{node.id}\\ntriosc"
    if isinstance(node, SawOsc):
        return "box", "#e2d5f1", f"{node.id}\\nsawosc"
    if isinstance(node, PulseOsc):
        return "box", "#e2d5f1", f"{node.id}\\npulseosc"
    if isinstance(node, SampleHold):
        return "box", "#fde0c8", f"{node.id}\\nsample_hold"
    if isinstance(node, Latch):
        return "box", "#fde0c8", f"{node.id}\\nlatch"
    if isinstance(node, Accum):
        return "box", "#fde0c8", f"{node.id}\\naccum"
    if isinstance(node, Counter):
        return "box", "#fde0c8", f"{node.id}\\ncounter"
    if isinstance(node, Buffer):
        return "box3d", "#fde0c8", f"{node.id}\\nbuffer[{node.size}]"
    if isinstance(node, BufRead):
        return "box", "#fde0c8", f"{node.id}\\nbuf_read"
    if isinstance(node, BufWrite):
        return "box", "#fde0c8", f"{node.id}\\nbuf_write"
    if isinstance(node, BufSize):
        return "box", "#fde0c8", f"{node.id}\\nbuf_size"
    if isinstance(node, RateDiv):
        return "box", "#fde0c8", f"{node.id}\\nrate_div"
    if isinstance(node, Scale):
        return "box", "#fff3cd", f"{node.id}\\nscale"
    if isinstance(node, SmoothParam):
        return "box", "#fde0c8", f"{node.id}\\nsmooth"
    if isinstance(node, Peek):
        return "box", "#d4edda", f"{node.id}\\npeek"
    if isinstance(node, Subgraph):
        n_in = len(node.graph.inputs)
        n_out = len(node.graph.outputs)
        return "box3d", "#cce5ff", f"{node.id}\\nsubgraph ({n_in}in/{n_out}out)"
    return "box", "#ffffff", str(getattr(node, "id", "?"))


def graph_to_dot(graph: Graph) -> str:
    """Convert a DSP graph to a Graphviz DOT string."""
    lines: list[str] = []
    w = lines.append

    w(f'digraph "{graph.name}" {{')
    w("    rankdir=LR;")
    w('    node [fontname="Helvetica" fontsize=10];')
    w("")

    # Build ID sets for reference resolution
    all_ids: set[str] = set()
    for inp in graph.inputs:
        all_ids.add(inp.id)
    for out in graph.outputs:
        all_ids.add(out.id)
    for p in graph.params:
        all_ids.add(p.name)
    for node in graph.nodes:
        all_ids.add(node.id)

    # Input nodes
    for inp in graph.inputs:
        w(
            f'    "{inp.id}" [shape=box style="rounded,filled"'
            f' fillcolor="#d4edda" label="{inp.id}"];'
        )

    # Output nodes
    for out in graph.outputs:
        w(
            f'    "{out.id}" [shape=box style="rounded,filled"'
            f' fillcolor="#f8d7da" label="{out.id}"];'
        )

    # Param nodes
    for p in graph.params:
        label = f"{p.name}\\n[{p.min}, {p.max}]\\ndefault={p.default}"
        w(
            f'    "{p.name}" [shape=ellipse style=filled fillcolor="#cce5ff" label="{label}"];'
        )

    # Processing nodes
    for node in graph.nodes:
        shape, color, label = _node_attrs(node)
        w(
            f'    "{node.id}" [shape={shape} style=filled fillcolor="{color}" label="{label}"];'
        )

    w("")

    # Edges from node fields
    for node in graph.nodes:
        for field_name, value in node.__dict__.items():
            if field_name in ("id", "op"):
                continue
            if isinstance(value, dict):
                for v in value.values():
                    if isinstance(v, str) and v in all_ids:
                        w(f'    "{v}" -> "{node.id}";')
                continue
            if not isinstance(value, str) or value not in all_ids:
                continue
            if is_feedback_edge(node, field_name):
                w(f'    "{value}" -> "{node.id}" [style=dashed label="z^-1"];')
            else:
                w(f'    "{value}" -> "{node.id}";')

    # Output edges: source -> output
    for out in graph.outputs:
        w(f'    "{out.source}" -> "{out.id}";')

    w("}")
    return "\n".join(lines) + "\n"


def graph_to_dot_file(graph: Graph, output_dir: str | Path) -> Path:
    """Write a DOT file for the graph to output_dir/{name}.dot.

    If the ``dot`` binary is on PATH, also renders a PDF to
    ``output_dir/{name}.pdf``.

    Returns the path to the written ``.dot`` file.
    """
    dot_src = graph_to_dot(graph)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    dot_path = out / f"{graph.name}.dot"
    dot_path.write_text(dot_src)

    dot_bin = shutil.which("dot")
    if dot_bin is not None:
        pdf_path = out / f"{graph.name}.pdf"
        subprocess.run(
            [dot_bin, "-Tpdf", str(dot_path), "-o", str(pdf_path)],
            check=True,
        )

    return dot_path
