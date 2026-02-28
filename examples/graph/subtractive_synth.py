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
