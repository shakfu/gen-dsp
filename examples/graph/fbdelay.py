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
    parser.add_argument("-p", "--platform", required=True, help="Target platform (clap, vst3, au, ...)")
    parser.add_argument("-o", "--output", type=Path, default=None)
    args = parser.parse_args()

    graph = make_graph()
    output = args.output or Path(f"build/examples/{graph.name}_{args.platform}")
    config = ProjectConfig(name=graph.name, platform=args.platform)
    gen = ProjectGenerator.from_graph(graph, config)
    project_dir = gen.generate(output_dir=output)

    print(f"Project generated at: {project_dir}")
    print(f"Build with: cd {project_dir} && cmake -B build && cmake --build build")


if __name__ == "__main__":
    main()
