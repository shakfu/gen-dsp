"""Feedback delay with delay line, feedback scaling, and dry/wet mix.

Demonstrates DelayLine, DelayRead, and DelayWrite nodes for building
a classic feedback delay effect.

Usage:
    python examples/graph/fbdelay.py -p lv2 [-o OUTPUT_DIR]
"""

import argparse
from pathlib import Path

from gen_dsp.graph import (
    AudioInput,
    AudioOutput,
    BinOp,
    DelayLine,
    DelayRead,
    DelayWrite,
    Graph,
    Param,
)
from gen_dsp.core.project import ProjectConfig, ProjectGenerator


def make_graph() -> Graph:
    return Graph(
        name="fbdelay",
        inputs=[AudioInput(id="in1")],
        outputs=[AudioOutput(id="out1", source="mix_out")],
        params=[
            Param(name="delay_ms", min=1.0, max=1000.0, default=250.0),
            Param(name="feedback", min=0.0, max=0.95, default=0.5),
            Param(name="mix", min=0.0, max=1.0, default=0.5),
        ],
        nodes=[
            # Convert delay_ms to samples (assuming 44100 Hz)
            BinOp(id="sr_ms", op="div", a=44100.0, b=1000.0),
            BinOp(id="tap", op="mul", a="delay_ms", b="sr_ms"),

            # Delay line with feedback
            DelayLine(id="dline", max_samples=48000),
            DelayRead(id="delayed", delay="dline", tap="tap"),
            BinOp(id="fb_scaled", op="mul", a="delayed", b="feedback"),
            BinOp(id="write_val", op="add", a="in1", b="fb_scaled"),
            DelayWrite(id="dwrite", delay="dline", value="write_val"),

            # Dry/wet mix
            BinOp(id="inv_mix", op="sub", a=1.0, b="mix"),
            BinOp(id="dry", op="mul", a="in1", b="inv_mix"),
            BinOp(id="wet", op="mul", a="delayed", b="mix"),
            BinOp(id="mix_out", op="add", a="dry", b="wet"),
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
