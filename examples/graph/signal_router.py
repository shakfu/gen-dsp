"""Signal routing demo: gate (1-to-N demux) and selector (N-to-1 mux).

A mono input is routed to one of three processing paths via GateRoute:
  1. Clean pass-through
  2. Inverted signal (phase flip)
  3. Half-amplitude

A Selector then picks one of two oscillators based on a parameter.
Both outputs are mixed to demonstrate combined routing.

Demonstrates: GateRoute, GateOut, Selector, SinOsc, TriOsc.

Usage:
    python examples/graph/signal_router.py -p clap [-o OUTPUT_DIR]
"""

import argparse
from pathlib import Path

from gen_dsp.graph import (
    AudioInput,
    AudioOutput,
    BinOp,
    GateOut,
    GateRoute,
    Graph,
    Param,
    Selector,
    SinOsc,
    TriOsc,
    UnaryOp,
)
from gen_dsp.core.project import ProjectConfig, ProjectGenerator


def make_graph() -> Graph:
    return Graph(
        name="signal_router",
        inputs=[AudioInput(id="in1")],
        outputs=[
            AudioOutput(id="out1", source="final"),
        ],
        params=[
            # Gate index: 1=clean, 2=inverted, 3=half (0=mute)
            Param(name="gate_idx", min=0.0, max=3.0, default=1.0),
            # Selector index: 1=sine, 2=triangle (0=silence)
            Param(name="osc_select", min=0.0, max=2.0, default=1.0),
            Param(name="osc_freq", min=20.0, max=2000.0, default=440.0),
            Param(name="osc_level", min=0.0, max=0.5, default=0.1),
        ],
        nodes=[
            # -- Gate: route input to one of 3 paths --
            GateRoute(id="gate", a="in1", index="gate_idx", count=3),

            # Path 1: clean
            GateOut(id="path_clean", gate="gate", channel=1),

            # Path 2: inverted
            GateOut(id="path_inv_raw", gate="gate", channel=2),
            UnaryOp(id="path_inv", op="neg", a="path_inv_raw"),

            # Path 3: half amplitude
            GateOut(id="path_half_raw", gate="gate", channel=3),
            BinOp(id="path_half", op="mul", a="path_half_raw", b=0.5),

            # Sum the gate outputs (only one is non-zero at a time)
            BinOp(id="gate_sum1", op="add", a="path_clean", b="path_inv"),
            BinOp(id="gate_out", op="add", a="gate_sum1", b="path_half"),

            # -- Selector: pick one of two oscillators --
            SinOsc(id="sine", freq="osc_freq"),
            TriOsc(id="tri", freq="osc_freq"),
            Selector(id="osc_chosen", index="osc_select", inputs=["sine", "tri"]),
            BinOp(id="osc_scaled", op="mul", a="osc_chosen", b="osc_level"),

            # -- Combine routed signal + selected oscillator --
            BinOp(id="final", op="add", a="gate_out", b="osc_scaled"),
        ],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-p", "--platform", default=None, help="Target platform")
    parser.add_argument("-l", "--list", action="store_true", help="List available platforms")
    parser.add_argument("-b", "--build", action="store_true", help="Build after generating")
    parser.add_argument("-o", "--output", type=Path, default=None)
    parser.add_argument("-d", "--dot", action="store_true", help="Generate Graphviz DOT graph as PDF")
    args = parser.parse_args()

    if args.list:
        print("Available platforms:", ", ".join(ProjectConfig.list_platforms()))
        return
    graph = make_graph()
    if args.dot:
        from gen_dsp.graph.visualize import graph_to_dot_file
        dot_path = graph_to_dot_file(graph, args.output or Path("."))
        print(f"DOT: {dot_path}")
        return
    if not args.platform:
        parser.error("-p/--platform is required (use -l to list available platforms)")

    output = args.output or Path(f"build/examples/{graph.name}_{args.platform}")
    config = ProjectConfig(name=graph.name, platform=args.platform)
    gen = ProjectGenerator.from_graph(graph, config)
    project_dir = gen.generate(output_dir=output)

    print(f"Project generated at: {project_dir}")
    if args.build:
        from gen_dsp.core.builder import Builder
        result = Builder(project_dir).build(args.platform, verbose=True)
        print(f"Build {'succeeded' if result.success else 'failed'}: {result}")
    else:
        print(f"Build with: cd {project_dir} && cmake -B build && cmake --build build")


if __name__ == "__main__":
    main()
