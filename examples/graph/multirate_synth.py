"""Multi-rate synth: control-rate envelope with audio-rate oscillator.

A generator (no audio inputs) with two-tier processing:
  - Control-rate: SmoothParam tracks the amplitude target, updating
    every 32 samples.
  - Audio-rate: sine oscillator runs per-sample, scaled by the
    held envelope value.

Usage:
    python examples/graph/multirate_synth.py -p sc [-o OUTPUT_DIR]
"""

import argparse
from pathlib import Path

from gen_dsp.graph import (
    AudioOutput,
    BinOp,
    Graph,
    Param,
    SinOsc,
    SmoothParam,
)
from gen_dsp.core.project import ProjectConfig, ProjectGenerator


def make_graph() -> Graph:
    return Graph(
        name="multirate_synth",
        sample_rate=48000.0,
        control_interval=32,
        control_nodes=["env"],
        inputs=[],
        outputs=[AudioOutput(id="out1", source="scaled")],
        params=[
            Param(name="freq", min=20.0, max=20000.0, default=440.0),
            Param(name="amp", min=0.0, max=1.0, default=0.0),
        ],
        nodes=[
            # Control-rate: smooth amplitude envelope
            SmoothParam(id="env", a="amp", coeff=0.995),
            # Audio-rate: sine oscillator and gain
            SinOsc(id="osc", freq="freq"),
            BinOp(id="scaled", op="mul", a="osc", b="env"),
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
