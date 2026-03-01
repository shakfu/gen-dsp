"""Simple Schroeder-style reverb: allpass diffusers + comb delay with decay.

Four allpass filters in series provide diffusion. A feedback delay line
with a t60-derived decay coefficient creates the reverb tail. DCBlock
removes DC offset. fixdenorm prevents denormal buildup in the feedback path.
mstosamps converts the user-facing delay time from milliseconds to samples.

Demonstrates: Allpass, DelayLine, DelayRead, DelayWrite, DCBlock,
UnaryOp (t60, mstosamps, fixdenorm), BinOp (rsub for wet inversion).

Usage:
    python examples/graph/allpass_reverb.py -p vst3 [-o OUTPUT_DIR]
"""

import argparse
from pathlib import Path

from gen_dsp.graph import (
    Allpass,
    AudioInput,
    AudioOutput,
    BinOp,
    DCBlock,
    DelayLine,
    DelayRead,
    DelayWrite,
    Graph,
    Param,
    UnaryOp,
)
from gen_dsp.core.project import ProjectConfig, ProjectGenerator


def make_graph() -> Graph:
    return Graph(
        name="allpass_verb",
        inputs=[AudioInput(id="in1")],
        outputs=[AudioOutput(id="out1", source="mixed")],
        params=[
            Param(name="decay_time", min=0.1, max=10.0, default=2.0),
            Param(name="delay_ms", min=10.0, max=200.0, default=80.0),
            Param(name="diffusion", min=0.0, max=0.9, default=0.6),
            Param(name="mix", min=0.0, max=1.0, default=0.4),
        ],
        nodes=[
            # -- Diffusion: chain of 4 allpass filters --
            Allpass(id="ap1", a="in1", coeff="diffusion"),
            Allpass(id="ap2", a="ap1", coeff="diffusion"),
            Allpass(id="ap3", a="ap2", coeff="diffusion"),
            Allpass(id="ap4", a="ap3", coeff="diffusion"),

            # -- Decay coefficient from t60 --
            # t60(decay_time) = exp(-6.9078 / (decay_time * sr))
            UnaryOp(id="fb_coeff", op="t60", a="decay_time"),

            # -- Comb delay with feedback --
            # Convert delay_ms to samples
            UnaryOp(id="tap_samps", op="mstosamps", a="delay_ms"),

            DelayLine(id="comb", max_samples=48000),
            DelayRead(id="comb_out", delay="comb", tap="tap_samps"),

            # Feedback: scale delayed signal by decay coefficient
            BinOp(id="fb_scaled", op="mul", a="comb_out", b="fb_coeff"),

            # Kill denormals in feedback path
            UnaryOp(id="fb_safe", op="fixdenorm", a="fb_scaled"),

            # Write diffused input + feedback into delay
            BinOp(id="comb_in", op="add", a="ap4", b="fb_safe"),
            DelayWrite(id="comb_wr", delay="comb", value="comb_in"),

            # -- Output mixing --
            # Remove DC offset from reverb tail
            DCBlock(id="dc_clean", a="comb_out"),

            # Dry/wet mix using rsub for (1 - mix)
            BinOp(id="inv_mix", op="rsub", a="mix", b=1.0),
            BinOp(id="dry", op="mul", a="in1", b="inv_mix"),
            BinOp(id="wet", op="mul", a="dc_clean", b="mix"),
            BinOp(id="mixed", op="add", a="dry", b="wet"),
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
    if args.build:
        from gen_dsp.core.builder import Builder
        result = Builder(project_dir).build(args.platform, verbose=True)
        print(f"Build {'succeeded' if result.success else 'failed'}: {result}")
    else:
        print(f"Build with: cd {project_dir} && cmake -B build && cmake --build build")


if __name__ == "__main__":
    main()
