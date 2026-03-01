"""FM synthesizer: carrier + modulator with ADSR envelope.

Two sine wavetable oscillators (Cycle) implement classic two-operator FM.
The modulator's output scales a frequency deviation added to the carrier
frequency. An ADSR envelope controlled by a gate parameter shapes the
output amplitude, enabling MIDI note-on/off control.

Demonstrates: Cycle, Buffer, Phasor, BinOp, ADSR, MIDI auto-detection.

Usage:
    python examples/graph/fm_synth.py -p clap [-o OUTPUT_DIR] [-b]
"""

import argparse
from pathlib import Path

from gen_dsp.graph import (
    ADSR,
    AudioOutput,
    BinOp,
    Buffer,
    Cycle,
    Graph,
    Param,
    Phasor,
)
from gen_dsp.core.project import ProjectConfig, ProjectGenerator


def make_graph() -> Graph:
    return Graph(
        name="fm_synth",
        inputs=[],  # generator -- no audio inputs
        outputs=[
            AudioOutput(id="out1", source="output"),
        ],
        params=[
            Param(name="gate", min=0.0, max=1.0, default=0.0),
            Param(name="freq", min=20.0, max=2000.0, default=440.0),
            Param(name="mod_ratio", min=0.5, max=8.0, default=2.0),
            Param(name="mod_index", min=0.0, max=10.0, default=3.0),
            Param(name="amp", min=0.0, max=1.0, default=0.3),
        ],
        nodes=[
            # Sine wavetable (512 samples, auto-filled with one sine cycle)
            Buffer(id="sine_tbl", size=512, fill="sine"),

            # -- Modulator oscillator --
            # mod_freq = freq * mod_ratio
            BinOp(id="mod_freq", op="mul", a="freq", b="mod_ratio"),

            # Modulator phasor and wavetable read
            Phasor(id="mod_phasor", freq="mod_freq"),
            Cycle(id="mod_osc", buffer="sine_tbl", phase="mod_phasor"),

            # -- Frequency deviation --
            # deviation = mod_osc * mod_index * mod_freq
            BinOp(id="dev_scale", op="mul", a="mod_osc", b="mod_index"),
            BinOp(id="deviation", op="mul", a="dev_scale", b="mod_freq"),

            # -- Carrier oscillator --
            # carrier_actual_freq = freq + deviation
            BinOp(id="car_freq", op="add", a="freq", b="deviation"),
            Phasor(id="car_phasor", freq="car_freq"),

            # Read carrier from sine table
            Cycle(id="car_osc", buffer="sine_tbl", phase="car_phasor"),

            # -- ADSR envelope --
            ADSR(id="env", gate="gate", attack=10.0, decay=100.0,
                 sustain=0.7, release=200.0),

            # Apply envelope and amplitude
            BinOp(id="env_scaled", op="mul", a="car_osc", b="env"),
            BinOp(id="output", op="mul", a="env_scaled", b="amp"),
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
