"""Filter chain using graph algebra: two one-pole filters in series.

Demonstrates FAUST-style block diagram combinators:
  - Define reusable filter blocks as standalone Graph objects.
  - Compose with series() (or the >> operator).
  - Params are automatically namespaced (lpf_coeff, hpf_coeff).
  - expand_subgraphs() flattens the result for compilation.

Usage:
    python examples/graph/filter_chain.py -p clap [-o OUTPUT_DIR]
"""

import argparse
from pathlib import Path

from gen_dsp.graph import (
    AudioInput,
    AudioOutput,
    Graph,
    OnePole,
    Param,
    expand_subgraphs,
    series,
    validate_graph,
)
from gen_dsp.core.project import ProjectConfig, ProjectGenerator


def make_graph() -> Graph:
    lpf = Graph(
        name="lpf",
        inputs=[AudioInput(id="x")],
        outputs=[AudioOutput(id="y", source="filt")],
        params=[Param(name="coeff", min=0.0, max=1.0, default=0.8)],
        nodes=[OnePole(id="filt", a="x", coeff="coeff")],
    )

    hpf = Graph(
        name="hpf",
        inputs=[AudioInput(id="x")],
        outputs=[AudioOutput(id="y", source="filt")],
        params=[Param(name="coeff", min=0.0, max=1.0, default=0.1)],
        nodes=[OnePole(id="filt", a="x", coeff="coeff")],
    )

    # Compose: lpf >> hpf (output of lpf feeds input of hpf)
    combined = series(lpf, hpf)
    return expand_subgraphs(combined)


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


    errors = validate_graph(graph)
    if errors:
        for e in errors:
            print(f"  error: {e}")
        return

    output = args.output or Path(f"build/examples/{graph.name}_{args.platform}")
    config = ProjectConfig(name=graph.name, platform=args.platform)
    gen = ProjectGenerator.from_graph(graph, config)
    project_dir = gen.generate(output_dir=output)

    print(f"Project generated at: {project_dir}")
    print(f"  Parameters: {', '.join(p.name for p in graph.params)}")
    if args.build:
        from gen_dsp.core.builder import Builder
        result = Builder(project_dir).build(args.platform, verbose=True)
        print(f"Build {'succeeded' if result.success else 'failed'}: {result}")
    else:
        print(f"Build with: cd {project_dir} && cmake -B build && cmake --build build")


if __name__ == "__main__":
    main()
