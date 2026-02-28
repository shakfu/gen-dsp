"""DSP signal graph DSL: define, validate, compile to C++, and optimize.

Provides 39 node types (arithmetic, filters, oscillators, delays, buffers,
state/timing, subgraph, utility), graph validation, topological sort, Graphviz
visualization, and a multi-pass optimizing compiler targeting standalone C++.

Requires pydantic >= 2.0.  Install with::

    pip install gen-dsp[graph]

A per-sample Python simulator is available via the ``simulate`` module
(requires numpy -- install with ``pip install gen-dsp[sim]``)::

    from gen_dsp.dsp_graph.simulate import simulate, SimState, SimResult
"""

__version__ = "0.1.6"

_AVAILABLE = False

try:
    from gen_dsp.dsp_graph.algebra import merge, parallel, series, split
    from gen_dsp.dsp_graph.compile import compile_graph, compile_graph_to_file
    from gen_dsp.dsp_graph.adapter import (
        compile_for_gen_dsp,
        generate_adapter_cpp,
        generate_manifest,
    )
    from gen_dsp.dsp_graph.models import (
        SVF,
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
        Node,
        Noise,
        OnePole,
        Param,
        Peek,
        Phasor,
        PulseOsc,
        RateDiv,
        Ref,
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
    from gen_dsp.dsp_graph.optimize import (
        OptimizeResult,
        OptimizeStats,
        constant_fold,
        eliminate_cse,
        eliminate_dead_nodes,
        optimize_graph,
        promote_control_rate,
    )
    from gen_dsp.dsp_graph.subgraph import expand_subgraphs
    from gen_dsp.dsp_graph.toposort import toposort
    from gen_dsp.dsp_graph.validate import GraphValidationError, validate_graph
    from gen_dsp.dsp_graph.visualize import graph_to_dot, graph_to_dot_file

    _AVAILABLE = True

except ImportError:
    pass


def _require_dsp_graph() -> None:
    """Raise ImportError with install instructions if pydantic is not available."""
    if not _AVAILABLE:
        raise ImportError(
            "dsp-graph functionality requires pydantic. "
            "Install with: pip install gen-dsp[graph]"
        )


__all__ = [
    "_AVAILABLE",
    "_require_dsp_graph",
    "Accum",
    "Allpass",
    "AudioInput",
    "AudioOutput",
    "BinOp",
    "Biquad",
    "BufRead",
    "BufSize",
    "BufWrite",
    "Buffer",
    "Change",
    "Clamp",
    "Compare",
    "Constant",
    "Counter",
    "DCBlock",
    "DelayLine",
    "DelayRead",
    "DelayWrite",
    "Delta",
    "Fold",
    "Graph",
    "GraphValidationError",
    "History",
    "Latch",
    "Mix",
    "Node",
    "Noise",
    "OnePole",
    "Param",
    "Peek",
    "Phasor",
    "PulseOsc",
    "RateDiv",
    "Ref",
    "SVF",
    "SampleHold",
    "SawOsc",
    "Scale",
    "Select",
    "SinOsc",
    "SmoothParam",
    "Subgraph",
    "TriOsc",
    "UnaryOp",
    "Wrap",
    "merge",
    "parallel",
    "series",
    "split",
    "compile_for_gen_dsp",
    "compile_graph",
    "compile_graph_to_file",
    "constant_fold",
    "expand_subgraphs",
    "eliminate_cse",
    "eliminate_dead_nodes",
    "generate_adapter_cpp",
    "generate_manifest",
    "graph_to_dot",
    "graph_to_dot_file",
    "OptimizeResult",
    "OptimizeStats",
    "optimize_graph",
    "promote_control_rate",
    "toposort",
    "validate_graph",
]
