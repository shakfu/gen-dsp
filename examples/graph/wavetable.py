"""Wavetable oscillator: Buffer + Phasor + BufRead with linear interpolation.

A generator (no audio inputs) that reads from a 1024-sample wavetable
at the specified frequency.

Usage:
    python examples/graph/wavetable.py -p sc [-o OUTPUT_DIR]
"""

import argparse
from pathlib import Path

from gen_dsp.graph import (
    AudioOutput,
    BinOp,
    Buffer,
    BufRead,
    BufSize,
    Graph,
    Param,
    Phasor,
)
from gen_dsp.core.project import ProjectConfig, ProjectGenerator


def make_graph() -> Graph:
    return Graph(
        name="wavetable",
        inputs=[],
        outputs=[AudioOutput(id="out1", source="sample")],
        params=[
            Param(name="freq", min=0.1, max=20000.0, default=440.0),
        ],
        nodes=[
            # Wavetable buffer (1024 samples, filled externally via set_buffer)
            Buffer(id="wt", size=1024),
            BufSize(id="wt_len", buffer="wt"),
            # Phasor produces 0..1 ramp at the desired frequency
            Phasor(id="phase", freq="freq"),
            # Scale phasor to buffer index range
            BinOp(id="idx", op="mul", a="phase", b="wt_len"),
            # Read from wavetable with linear interpolation
            BufRead(id="sample", buffer="wt", index="idx", interp="linear"),
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
