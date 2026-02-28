"""One-pole lowpass filter using History feedback.

Demonstrates manual IIR filter construction with the History node
for single-sample feedback.

Usage:
    python examples/graph/onepole.py -p clap [-o OUTPUT_DIR]
"""

import argparse
from pathlib import Path

from gen_dsp.graph import (
    AudioInput,
    AudioOutput,
    BinOp,
    Graph,
    History,
    Param,
)
from gen_dsp.core.project import ProjectConfig, ProjectGenerator


def make_graph() -> Graph:
    return Graph(
        name="onepole",
        inputs=[AudioInput(id="in1")],
        outputs=[AudioOutput(id="out1", source="result")],
        params=[Param(name="coeff", min=0.0, max=0.999, default=0.5)],
        nodes=[
            BinOp(id="inv_coeff", op="sub", a=1.0, b="coeff"),
            BinOp(id="dry", op="mul", a="in1", b="inv_coeff"),
            History(id="prev", init=0.0, input="result"),
            BinOp(id="wet", op="mul", a="prev", b="coeff"),
            BinOp(id="result", op="add", a="dry", b="wet"),
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
