"""Stateless stereo gain -- simplest possible graph.

Usage:
    python examples/graph/stereo_gain.py -p clap [-o OUTPUT_DIR]
"""

import argparse
from pathlib import Path

from gen_dsp.graph import (
    AudioInput,
    AudioOutput,
    BinOp,
    Graph,
    Param,
)
from gen_dsp.core.project import ProjectConfig, ProjectGenerator


def make_graph() -> Graph:
    return Graph(
        name="stereo_gain",
        inputs=[AudioInput(id="in1"), AudioInput(id="in2")],
        outputs=[
            AudioOutput(id="out1", source="scaled1"),
            AudioOutput(id="out2", source="scaled2"),
        ],
        params=[Param(name="gain", min=0.0, max=2.0, default=1.0)],
        nodes=[
            BinOp(id="scaled1", op="mul", a="in1", b="gain"),
            BinOp(id="scaled2", op="mul", a="in2", b="gain"),
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
