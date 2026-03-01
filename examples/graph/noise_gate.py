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
