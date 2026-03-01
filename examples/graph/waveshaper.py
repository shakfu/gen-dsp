"""Waveshaping distortion using a lookup table.

A tanh-like transfer curve is stored in a Buffer and applied via Lookup.
The drive parameter scales the input before the lookup, controlling
distortion intensity. Slide provides slew-limited drive changes to avoid
clicks. fixdenorm ensures no denormals leak through.

Demonstrates: Buffer, Lookup, Slide, UnaryOp (fixdenorm), Scale.

Usage:
    python examples/graph/waveshaper.py -p clap [-o OUTPUT_DIR]
"""

import argparse
from pathlib import Path

from gen_dsp.graph import (
    AudioInput,
    AudioOutput,
    BinOp,
    Buffer,
    Graph,
    Lookup,
    Param,
    Scale,
    Slide,
    UnaryOp,
)
from gen_dsp.core.project import ProjectConfig, ProjectGenerator


def make_graph() -> Graph:
    return Graph(
        name="waveshaper",
        inputs=[AudioInput(id="in1")],
        outputs=[AudioOutput(id="out1", source="clean")],
        params=[
            Param(name="drive", min=0.0, max=1.0, default=0.5),
            Param(name="output_gain", min=0.0, max=1.0, default=0.7),
        ],
        nodes=[
            # Slew-limit drive changes to avoid clicks (200-sample ramp)
            Slide(id="smooth_drive", a="drive", up=200.0, down=200.0),

            # Scale drive from [0,1] to [1,10] for input pre-gain
            Scale(id="pre_gain", a="smooth_drive",
                  in_lo=0.0, in_hi=1.0, out_lo=1.0, out_hi=10.0),

            # Apply pre-gain to input
            BinOp(id="driven", op="mul", a="in1", b="pre_gain"),

            # Map driven signal from roughly [-1,1] to [0,1] for Lookup index
            # (clamped internally by Lookup)
            BinOp(id="half", op="mul", a="driven", b=0.5),
            BinOp(id="idx", op="add", a="half", b=0.5),

            # Waveshaping table (256 samples, filled via set_buffer with tanh curve)
            Buffer(id="shape", size=256),
            Lookup(id="shaped", buffer="shape", index="idx"),

            # Remove denormals and apply output gain
            UnaryOp(id="safe", op="fixdenorm", a="shaped"),
            BinOp(id="clean", op="mul", a="safe", b="output_gain"),
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
    print("Note: fill the 'shape' buffer with a tanh transfer curve at runtime")
    if args.build:
        from gen_dsp.core.builder import Builder
        result = Builder(project_dir).build(args.platform, verbose=True)
        print(f"Build {'succeeded' if result.success else 'failed'}: {result}")
    else:
        print(f"Build with: cd {project_dir} && cmake -B build && cmake --build build")


if __name__ == "__main__":
    main()
