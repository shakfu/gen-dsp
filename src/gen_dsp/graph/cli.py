"""Command-line interface for the gen-dsp graph frontend (internal module).

This module provides the graph subcommand implementations for gen-dsp's CLI.
It can also be used standalone via ``main()`` for testing.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

from pydantic import ValidationError

from gen_dsp.graph.compile import compile_graph, compile_graph_to_file
from gen_dsp.graph.models import Graph
from gen_dsp.graph.optimize import optimize_graph
from gen_dsp.graph.validate import validate_graph
from gen_dsp.graph.visualize import graph_to_dot, graph_to_dot_file


def _load_graph(path: str) -> Graph:
    """Load and parse a graph file (JSON or .gdsp).

    Auto-detects format by file extension: ``.gdsp`` files are parsed via
    the DSL parser; everything else is treated as JSON.
    """
    p = Path(path)
    if p.suffix == ".gdsp":
        from gen_dsp.graph.dsl import parse_file

        result = parse_file(p)
        assert isinstance(result, Graph)
        return result
    text = p.read_text()
    data = json.loads(text)
    return Graph.model_validate(data)


# ---------------------------------------------------------------------------
# WAV I/O helpers (float32 via RIFF, no external deps beyond numpy)
# ---------------------------------------------------------------------------


def _read_wav(path: str) -> tuple[list[list[float]], int]:
    """Read a WAV file and return (channels, sample_rate).

    Each channel is a list of float samples. Supports PCM16, PCM32 (tag 1)
    and float32 (tag 3).
    """
    import numpy as np

    with open(path, "rb") as f:
        data = f.read()

    if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError(f"Not a valid WAV file: {path}")

    # Parse chunks
    pos = 12
    fmt_tag = 0
    n_channels = 0
    sample_rate = 0
    bits_per_sample = 0
    audio_data = b""

    while pos < len(data) - 8:
        chunk_id = data[pos : pos + 4]
        chunk_size = struct.unpack_from("<I", data, pos + 4)[0]
        chunk_data = data[pos + 8 : pos + 8 + chunk_size]

        if chunk_id == b"fmt ":
            fmt_tag = struct.unpack_from("<H", chunk_data, 0)[0]
            n_channels = struct.unpack_from("<H", chunk_data, 2)[0]
            sample_rate = struct.unpack_from("<I", chunk_data, 4)[0]
            bits_per_sample = struct.unpack_from("<H", chunk_data, 14)[0]
        elif chunk_id == b"data":
            audio_data = chunk_data

        pos += 8 + chunk_size
        if chunk_size % 2 == 1:
            pos += 1  # pad byte

    if not audio_data:
        raise ValueError(f"No data chunk in WAV file: {path}")

    # Decode samples
    if fmt_tag == 1:  # PCM
        if bits_per_sample == 16:
            samples = (
                np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0
            )
        elif bits_per_sample == 32:
            samples = (
                np.frombuffer(audio_data, dtype=np.int32).astype(np.float32)
                / 2147483648.0
            )
        else:
            raise ValueError(f"Unsupported PCM bit depth: {bits_per_sample}")
    elif fmt_tag == 3:  # IEEE float
        samples = np.frombuffer(audio_data, dtype=np.float32).copy()
    else:
        raise ValueError(f"Unsupported WAV format tag: {fmt_tag}")

    # De-interleave channels
    n_frames = len(samples) // n_channels
    channels: list[list[float]] = []
    for ch in range(n_channels):
        channels.append(samples[ch::n_channels][:n_frames].tolist())

    if n_channels > 1:
        print(
            f"info: {path}: {n_channels} channels, using first channel ({n_frames} samples)",
            file=sys.stderr,
        )

    return channels, sample_rate


def _write_wav(path: str, data: list[float], sample_rate: int) -> None:
    """Write a mono float32 WAV file."""
    import numpy as np

    samples = np.array(data, dtype=np.float32)
    raw = samples.tobytes()
    n_channels = 1
    bits_per_sample = 32
    byte_rate = sample_rate * n_channels * bits_per_sample // 8
    block_align = n_channels * bits_per_sample // 8

    with open(path, "wb") as f:
        # RIFF header
        data_size = len(raw)
        file_size = 36 + data_size
        f.write(b"RIFF")
        f.write(struct.pack("<I", file_size))
        f.write(b"WAVE")
        # fmt chunk
        f.write(b"fmt ")
        f.write(struct.pack("<I", 16))  # chunk size
        f.write(struct.pack("<H", 3))  # IEEE float
        f.write(struct.pack("<H", n_channels))
        f.write(struct.pack("<I", sample_rate))
        f.write(struct.pack("<I", byte_rate))
        f.write(struct.pack("<H", block_align))
        f.write(struct.pack("<H", bits_per_sample))
        # data chunk
        f.write(b"data")
        f.write(struct.pack("<I", data_size))
        f.write(raw)


# ---------------------------------------------------------------------------
# Subcommand handlers (public)
# ---------------------------------------------------------------------------


def cmd_compile(args: argparse.Namespace) -> int:
    """Compile a graph to C++ (raw output, no platform adapter)."""
    try:
        graph = _load_graph(args.file)
        if args.optimize:
            graph, _stats = optimize_graph(graph)
        if args.output:
            compile_graph_to_file(graph, args.output)
        else:
            sys.stdout.write(compile_graph(graph))
        return 0
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as e:
        print(f"error: invalid JSON: {e}", file=sys.stderr)
        return 1
    except ValidationError as e:
        print(f"error: invalid graph: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except _gdsp_errors() as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def cmd_validate(args: argparse.Namespace) -> int:
    """Validate a graph file."""
    try:
        graph = _load_graph(args.file)
        warn = getattr(args, "warn_unmapped_params", False)
        errors = validate_graph(graph, warn_unmapped_params=warn)

        has_errors = any(e.severity == "error" for e in errors)
        has_warnings = any(e.severity == "warning" for e in errors)

        for err in errors:
            prefix = "warning" if err.severity == "warning" else "error"
            print(f"{prefix}: {err}", file=sys.stderr)

        if has_errors:
            return 1
        if has_warnings:
            print("valid (with warnings)")
        else:
            print("valid")
        return 0
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as e:
        print(f"error: invalid JSON: {e}", file=sys.stderr)
        return 1
    except ValidationError as e:
        print(f"error: invalid graph: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except _gdsp_errors() as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def cmd_viz(args: argparse.Namespace) -> int:
    """Generate a graph visualization (DOT format)."""
    if getattr(args, "command", None) == "dot":
        print(
            "warning: the 'dot' subcommand is deprecated; use 'viz' instead",
            file=sys.stderr,
        )
    try:
        graph = _load_graph(args.file)
        if args.output:
            graph_to_dot_file(graph, args.output)
        else:
            sys.stdout.write(graph_to_dot(graph))
        return 0
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as e:
        print(f"error: invalid JSON: {e}", file=sys.stderr)
        return 1
    except ValidationError as e:
        print(f"error: invalid graph: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except _gdsp_errors() as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def cmd_simulate(args: argparse.Namespace) -> int:
    """Simulate a graph (WAV in/out)."""
    try:
        import numpy as np
    except ImportError:
        print(
            "error: numpy is required for simulation. Install with: pip install gen-dsp[sim]",
            file=sys.stderr,
        )
        return 1

    try:
        from gen_dsp.graph.simulate import simulate

        graph = _load_graph(args.file)

        if args.optimize:
            graph, _stats = optimize_graph(graph)

        # Parse param overrides
        params: dict[str, float] = {}
        for spec in args.param or []:
            if "=" not in spec:
                print(
                    f"error: invalid param spec (expected NAME=VALUE): {spec}",
                    file=sys.stderr,
                )
                return 1
            name, val_str = spec.split("=", 1)
            try:
                params[name] = float(val_str)
            except ValueError:
                print(f"error: invalid param value: {val_str}", file=sys.stderr)
                return 1

        # Load input WAV files
        input_ids = {inp.id for inp in graph.inputs}
        inputs: dict[str, np.ndarray] | None = None
        wav_sr: int | None = None

        if args.input:
            inputs = {}
            for spec in args.input:
                if "=" in spec:
                    name, wav_path = spec.split("=", 1)
                else:
                    wav_path = spec
                    unmapped = input_ids - set(inputs.keys())
                    if not unmapped:
                        print(
                            f"error: no unmapped input for file: {wav_path}",
                            file=sys.stderr,
                        )
                        return 1
                    name = sorted(unmapped)[0]

                if name not in input_ids:
                    print(f"error: unknown input '{name}'", file=sys.stderr)
                    return 1

                try:
                    channels, sr = _read_wav(wav_path)
                except (ValueError, FileNotFoundError) as e:
                    print(f"error: {e}", file=sys.stderr)
                    return 1

                if wav_sr is None:
                    wav_sr = sr
                inputs[name] = np.array(channels[0], dtype=np.float32)

        # Determine sample count
        n_samples = args.samples or 0

        # Determine sample rate
        sample_rate = float(args.sample_rate) if args.sample_rate else 0.0
        if sample_rate == 0.0 and wav_sr:
            sample_rate = float(wav_sr)

        if not inputs and n_samples == 0:
            print(
                "error: -n/--samples is required when no input files are provided",
                file=sys.stderr,
            )
            return 1

        if input_ids and (not inputs or set(inputs.keys()) != input_ids):
            provided = set(inputs.keys()) if inputs else set()
            missing = input_ids - provided
            if missing:
                print(
                    f"error: missing input(s): {', '.join(sorted(missing))}",
                    file=sys.stderr,
                )
                return 1

        result = simulate(
            graph,
            inputs=inputs,
            n_samples=n_samples,
            params=params if params else None,
            sample_rate=sample_rate,
        )

        out_dir = Path(args.output) if args.output else Path(".")
        out_dir.mkdir(parents=True, exist_ok=True)

        sr_out = int(sample_rate) if sample_rate > 0.0 else int(graph.sample_rate)
        for out_id, arr in result.outputs.items():
            wav_path = out_dir / f"{out_id}.wav"
            _write_wav(str(wav_path), arr.tolist(), sr_out)
            print(f"wrote {wav_path} ({len(arr)} samples, {sr_out} Hz)")

        return 0
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as e:
        print(f"error: invalid JSON: {e}", file=sys.stderr)
        return 1
    except ValidationError as e:
        print(f"error: invalid graph: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except _gdsp_errors() as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def _gdsp_errors() -> tuple[type[Exception], ...]:
    """Return GDSP error types for exception handling."""
    from gen_dsp.graph.dsl import GDSPCompileError, GDSPSyntaxError

    return (GDSPSyntaxError, GDSPCompileError)


# ---------------------------------------------------------------------------
# Individual parser-builder functions for gen-dsp's CLI
# ---------------------------------------------------------------------------

_FILE_HELP = "Graph file (.gdsp or .json)"


def add_compile_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Add the 'compile' subcommand (raw C++ output, no platform adapter)."""
    p = subparsers.add_parser("compile", help="Compile graph to C++")
    p.add_argument("file", help=_FILE_HELP)
    p.add_argument("-o", "--output", help="Output directory")
    p.add_argument("--optimize", action="store_true", help="Apply optimization passes")


def add_validate_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Add the 'validate' subcommand."""
    p = subparsers.add_parser("validate", help="Validate graph")
    p.add_argument("file", help=_FILE_HELP)
    p.add_argument(
        "--warn-unmapped-params",
        action="store_true",
        help="Warn on unmapped subgraph params falling back to defaults",
    )


def _add_viz_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("file", help=_FILE_HELP)
    p.add_argument("-o", "--output", help="Output directory")


def add_viz_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Add the 'viz' subcommand, plus the deprecated 'dot' alias."""
    p = subparsers.add_parser("viz", help="Generate graph visualization (DOT)")
    _add_viz_args(p)
    # Backward-compatible hidden alias for the former 'dot' name.
    p_dot = subparsers.add_parser("dot", help=argparse.SUPPRESS)
    _add_viz_args(p_dot)


def add_sim_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Add the 'sim' subcommand."""
    p = subparsers.add_parser("sim", help="Simulate graph (WAV in/out)")
    p.add_argument("file", help=_FILE_HELP)
    p.add_argument(
        "-i",
        "--input",
        action="append",
        metavar="[NAME=]FILE",
        help="Map audio input to WAV file (repeatable)",
    )
    p.add_argument("-o", "--output", help="Output directory (default: current dir)")
    p.add_argument(
        "-n", "--samples", type=int, help="Number of samples (required for generators)"
    )
    p.add_argument(
        "--param",
        action="append",
        metavar="NAME=VALUE",
        help="Set parameter (repeatable)",
    )
    p.add_argument("--sample-rate", type=float, help="Override sample rate")
    p.add_argument("--optimize", action="store_true", help="Optimize before simulation")


# ---------------------------------------------------------------------------
# Standalone entry point (for testing)
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Standalone entry point for the gen-dsp graph CLI (for testing)."""
    parser = argparse.ArgumentParser(
        prog="gen-dsp-graph",
        description="Compile, validate, visualize, and simulate DSP signal graphs.",
    )
    sub = parser.add_subparsers(dest="command")

    # compile (no -p in standalone mode either)
    p_compile = sub.add_parser("compile", help="Compile graph to C++")
    p_compile.add_argument("file", help=_FILE_HELP)
    p_compile.add_argument("-o", "--output", help="Output directory")
    p_compile.add_argument(
        "--optimize", action="store_true", help="Apply optimization passes"
    )

    # validate
    p_validate = sub.add_parser("validate", help="Validate graph")
    p_validate.add_argument("file", help=_FILE_HELP)
    p_validate.add_argument(
        "--warn-unmapped-params",
        action="store_true",
        help="Warn on unmapped subgraph params falling back to defaults",
    )

    # viz (with deprecated 'dot' alias)
    p_viz = sub.add_parser("viz", help="Generate graph visualization (DOT)")
    _add_viz_args(p_viz)
    p_viz_dot = sub.add_parser("dot", help=argparse.SUPPRESS)
    _add_viz_args(p_viz_dot)

    # sim
    p_sim = sub.add_parser("sim", help="Simulate graph (WAV in/out)")
    p_sim.add_argument("file", help=_FILE_HELP)
    p_sim.add_argument(
        "-i",
        "--input",
        action="append",
        metavar="[NAME=]FILE",
        help="Map audio input to WAV file (repeatable)",
    )
    p_sim.add_argument("-o", "--output", help="Output directory (default: current dir)")
    p_sim.add_argument(
        "-n", "--samples", type=int, help="Number of samples (required for generators)"
    )
    p_sim.add_argument(
        "--param",
        action="append",
        metavar="NAME=VALUE",
        help="Set parameter (repeatable)",
    )
    p_sim.add_argument("--sample-rate", type=float, help="Override sample rate")
    p_sim.add_argument(
        "--optimize", action="store_true", help="Optimize before simulation"
    )

    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help(sys.stderr)
        return 1

    if args.command == "compile":
        return cmd_compile(args)
    elif args.command == "validate":
        return cmd_validate(args)
    elif args.command in ("viz", "dot"):
        return cmd_viz(args)
    elif args.command == "sim":
        return cmd_simulate(args)

    return 0  # pragma: no cover


if __name__ == "__main__":
    sys.exit(main())
