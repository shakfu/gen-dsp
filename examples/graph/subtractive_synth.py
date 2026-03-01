"""Subtractive synthesizer: sawtooth through a one-pole lowpass.

A generator (no audio inputs) demonstrating SawOsc and OnePole nodes.
The cutoff parameter controls the filter brightness.

Usage:
    python examples/graph/subtractive_synth.py -p sc [-o OUTPUT_DIR]
"""

import argparse
from pathlib import Path

from gen_dsp.graph import (
    AudioOutput,
    BinOp,
    Graph,
    OnePole,
    Param,
    SawOsc,
)
from gen_dsp.core.project import ProjectConfig, ProjectGenerator


def make_graph() -> Graph:
    return Graph(
        name="subsynth",
        inputs=[],
        outputs=[AudioOutput(id="out1", source="filtered")],
        params=[
            Param(name="freq", min=20.0, max=20000.0, default=220.0),
            Param(name="cutoff", min=0.0, max=0.999, default=0.7),
            Param(name="amp", min=0.0, max=1.0, default=0.3),
        ],
        nodes=[
            SawOsc(id="saw", freq="freq"),
            OnePole(id="lp", a="saw", coeff="cutoff"),
            BinOp(id="filtered", op="mul", a="lp", b="amp"),
        ],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-p", "--platform", default=None, help="Target platform (clap, vst3, au, ...)")
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
