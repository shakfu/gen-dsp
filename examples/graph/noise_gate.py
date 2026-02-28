"""Noise gate using envelope following and threshold comparison.

Demonstrates Compare, Select, and OnePole nodes for dynamics processing.
The envelope follower smooths the rectified input; the gate opens when
the envelope exceeds the threshold.

Usage:
    python examples/graph/noise_gate.py -p clap [-o OUTPUT_DIR]
"""

import argparse
from pathlib import Path

from gen_dsp.graph import (
    AudioInput,
    AudioOutput,
    Compare,
    Graph,
    OnePole,
    Param,
    Select,
    UnaryOp,
)
from gen_dsp.core.project import ProjectConfig, ProjectGenerator


def make_graph() -> Graph:
    return Graph(
        name="noisegate",
        inputs=[AudioInput(id="in1")],
        outputs=[AudioOutput(id="out1", source="gated")],
        params=[
            Param(name="threshold", min=0.0, max=1.0, default=0.1),
            Param(name="smoothing", min=0.0, max=0.999, default=0.95),
        ],
        nodes=[
            # Envelope follower: lowpass of |input|
            UnaryOp(id="rectified", op="abs", a="in1"),
            OnePole(id="envelope", a="rectified", coeff="smoothing"),
            # Gate: open when envelope > threshold
            Compare(id="gate_open", op="gt", a="envelope", b="threshold"),
            # Output: pass signal or silence
            Select(id="gated", cond="gate_open", a=0.0, b="in1"),
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
