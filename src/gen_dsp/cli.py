"""
Command-line interface for gen_dsp.

Usage:
    gen-dsp <source> -p <platform> [--no-build] [--dry-run]
    gen-dsp compile <file>
    gen-dsp validate <file>
    gen-dsp dot <file>
    gen-dsp sim <file> [options]
    gen-dsp build [project-path] [-p <platform>]
    gen-dsp detect <export-path> [--json]
    gen-dsp patch <target-path> [--dry-run]
    gen-dsp chain <export-dir> --graph <chain.json> -n NAME [-p circle]
    gen-dsp list
    gen-dsp cache
    gen-dsp manifest <export-path>
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from gen_dsp import __version__

from gen_dsp.core.parser import GenExportParser
from gen_dsp.core.project import ProjectGenerator, ProjectConfig
from gen_dsp.core.patcher import Patcher
from gen_dsp.core.builder import Builder
from gen_dsp.errors import GenExtError
from gen_dsp.platforms import list_platforms, get_platform
from gen_dsp.platforms.base import Platform


# Known subcommands for two-phase dispatch.
SUBCOMMANDS = {
    "compile",
    "validate",
    "dot",
    "sim",
    "build",
    "detect",
    "patch",
    "list",
    "cache",
    "manifest",
    "chain",
}


def _print_help() -> None:
    """Print top-level help text."""
    platforms = ", ".join(list_platforms())
    print(f"""\
usage: gen-dsp <source> -p <platform> [options]
       gen-dsp <command> [args]

gen-dsp {__version__} -- generate buildable audio DSP plugins

Default command (auto-detects source type):
  gen-dsp <dir>           gen~ export directory
  gen-dsp <file.gdsp>     graph DSL file
  gen-dsp <file.json>     graph JSON file

  -p, --platform PLATFORM   Target platform (required): {platforms}
  -n, --name NAME           Plugin name (default: inferred from source)
  -o, --output DIR          Output directory (default: <name>_<platform>)
  --no-build                Skip building after project creation
  --dry-run                 Show what would be done without creating files
  --buffers NAME [NAME ...]
  --no-patch                Skip platform patches
  --no-shared-cache         Disable shared OS cache for FetchContent downloads
  --board BOARD             Board variant (daisy, circle)
  --no-midi                 Disable MIDI note handling
  --midi-gate NAME          MIDI gate parameter name
  --midi-freq NAME          MIDI frequency parameter name
  --midi-vel NAME           MIDI velocity parameter name
  --midi-freq-unit {{hz,midi}}
  --voices N                Polyphony voices (default: 1)

Subcommands:
  compile <file>            Compile graph to C++ (stdout or -o dir)
  validate <file>           Validate a graph file
  dot <file>                Generate DOT visualization
  sim <file>                Simulate graph (WAV in/out)
  build [dir]               Build an existing project
  detect <dir>              Analyze a gen~ export
  patch <dir>               Apply platform-specific patches
  chain <dir>               Multi-plugin chain mode (Circle)
  list                      List available platforms
  cache                     Show cached SDKs
  manifest <dir>            Emit JSON manifest for a gen~ export

Options:
  -V, --version             Show version
  -h, --help                Show this help
""")


def _make_default_parser() -> argparse.ArgumentParser:
    """Parser for the default command: <source> -p <platform> [flags]."""
    parser = argparse.ArgumentParser(
        prog="gen-dsp",
        add_help=False,
    )
    parser.add_argument(
        "source",
        type=Path,
        help="Path to gen~ export directory, .gdsp file, or graph JSON file",
    )
    parser.add_argument(
        "-p",
        "--platform",
        choices=list_platforms(),
        required=True,
        help="Target platform",
    )
    parser.add_argument(
        "-n",
        "--name",
        default=None,
        help="Name for the plugin (default: inferred from source)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output directory (default: ./<name>_<platform>)",
    )
    parser.add_argument(
        "--no-build",
        action="store_true",
        help="Skip building after project creation",
    )
    parser.add_argument(
        "--buffers",
        nargs="+",
        help="Buffer names (overrides auto-detection)",
    )
    parser.add_argument(
        "--no-patch",
        action="store_true",
        help="Don't apply platform patches (exp2f fix)",
    )
    parser.add_argument(
        "--no-shared-cache",
        action="store_true",
        help="Disable shared OS cache for FetchContent downloads (CMake-based platforms)",
    )
    parser.add_argument(
        "--board",
        help="Board variant for embedded platforms (daisy, circle)",
    )
    parser.add_argument(
        "--no-midi",
        action="store_true",
        help="Disable MIDI note handling even if gate/freq params are detected",
    )
    parser.add_argument(
        "--midi-gate",
        metavar="NAME",
        help="Parameter name to use as MIDI gate (implies MIDI enabled)",
    )
    parser.add_argument(
        "--midi-freq",
        metavar="NAME",
        help="Parameter name to use as MIDI frequency (implies MIDI enabled)",
    )
    parser.add_argument(
        "--midi-vel",
        metavar="NAME",
        help="Parameter name to use as MIDI velocity (implies MIDI enabled)",
    )
    parser.add_argument(
        "--midi-freq-unit",
        choices=["hz", "midi"],
        default="hz",
        help="Frequency unit: hz (mtof conversion, default) or midi (raw note number)",
    )
    parser.add_argument(
        "--voices",
        type=int,
        default=1,
        metavar="N",
        help="Number of polyphony voices (default: 1 = monophonic, requires MIDI)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without creating files",
    )
    return parser


def _make_subcommand_parser() -> argparse.ArgumentParser:
    """Parser with all subcommands registered."""
    parser = argparse.ArgumentParser(
        prog="gen-dsp",
        add_help=False,
    )
    subparsers = parser.add_subparsers(dest="command")

    # build command
    build_parser = subparsers.add_parser("build", help="Build an existing project")
    build_parser.add_argument(
        "project_path",
        type=Path,
        nargs="?",
        default=Path.cwd(),
        help="Path to the project directory (default: current directory)",
    )
    build_parser.add_argument(
        "-p",
        "--platform",
        choices=list_platforms(),
        default="pd",
        help="Target platform (default: pd)",
    )
    build_parser.add_argument(
        "--clean", action="store_true", help="Clean before building"
    )
    build_parser.add_argument(
        "-v", "--verbose", action="store_true", help="Show build output"
    )

    # detect command
    detect_parser = subparsers.add_parser("detect", help="Analyze a gen~ export")
    detect_parser.add_argument(
        "export_path", type=Path, help="Path to gen~ export directory"
    )
    detect_parser.add_argument(
        "--json", action="store_true", help="Output in JSON format"
    )

    # patch command
    patch_parser = subparsers.add_parser(
        "patch", help="Apply platform-specific patches"
    )
    patch_parser.add_argument(
        "target_path", type=Path, help="Path to project or gen~ export dir"
    )
    patch_parser.add_argument(
        "--dry-run", action="store_true", help="Show what would be done"
    )

    # list command
    subparsers.add_parser("list", help="List available target platforms")

    # cache command
    subparsers.add_parser("cache", help="Show cached SDKs and dependencies")

    # manifest command
    manifest_parser = subparsers.add_parser("manifest", help="Emit JSON manifest")
    manifest_parser.add_argument(
        "export_path", type=Path, help="Path to gen~ export directory"
    )
    manifest_parser.add_argument(
        "--buffers", nargs="+", help="Buffer names (overrides auto-detection)"
    )

    # chain command
    chain_parser = subparsers.add_parser(
        "chain", help="Multi-plugin chain mode (Circle)"
    )
    chain_parser.add_argument(
        "export_path",
        type=Path,
        help="Path to gen~ export directory (base for chain nodes)",
    )
    chain_parser.add_argument(
        "--graph",
        type=Path,
        required=True,
        help="JSON graph file for multi-plugin chain",
    )
    chain_parser.add_argument(
        "-n",
        "--name",
        required=True,
        help="Name for the chain project",
    )
    chain_parser.add_argument(
        "-p",
        "--platform",
        default="circle",
        help="Target platform (default: circle)",
    )
    chain_parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output directory (default: ./<name>)",
    )
    chain_parser.add_argument(
        "--export",
        type=Path,
        action="append",
        dest="exports",
        help="Additional export path (can be repeated)",
    )
    chain_parser.add_argument(
        "--no-patch", action="store_true", help="Skip platform patches"
    )
    chain_parser.add_argument("--board", help="Board variant")
    chain_parser.add_argument("--no-build", action="store_true", help="Skip building")
    chain_parser.add_argument(
        "--dry-run", action="store_true", help="Show what would be done"
    )

    # graph subcommands (compile, validate, dot, sim)
    try:
        from gen_dsp.graph.cli import (
            add_compile_parser,
            add_validate_parser,
            add_dot_parser,
            add_sim_parser,
        )

        add_compile_parser(subparsers)
        add_validate_parser(subparsers)
        add_dot_parser(subparsers)
        add_sim_parser(subparsers)
    except ImportError:
        pass

    return parser


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------


def _cmd_default(argv: list[str]) -> int:
    """Handle the default command: <source> -p <platform> [flags]."""
    parser = _make_default_parser()
    args = parser.parse_args(argv)

    source = args.source.resolve()

    # Auto-detect source type
    if source.is_file() and source.suffix in (".gdsp", ".json"):
        return _cmd_default_graph(args, source)
    elif source.is_dir():
        return _cmd_default_export(args, source)
    else:
        print(
            f"Error: source not found or unrecognized type: {source}", file=sys.stderr
        )
        print(
            "Expected: directory (gen~ export), .gdsp file, or .json file",
            file=sys.stderr,
        )
        return 1


def _cmd_default_graph(args: argparse.Namespace, graph_path: Path) -> int:
    """Handle default command with a graph file source."""
    try:
        from gen_dsp.graph import _require_dsp_graph

        _require_dsp_graph()
    except ImportError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    from gen_dsp.graph.models import Graph
    from gen_dsp.graph.validate import validate_graph

    # Infer name
    if args.name is None:
        args.name = graph_path.stem
        if not args.name:
            print("Error: could not infer name from graph file", file=sys.stderr)
            return 1

    # Load graph
    try:
        if graph_path.suffix == ".gdsp":
            from gen_dsp.graph.dsl import parse_file as parse_gdsp

            parsed = parse_gdsp(graph_path)
            assert isinstance(parsed, Graph)
            graph = parsed
        else:
            text = graph_path.read_text()
            data = json.loads(text)
            graph = Graph.model_validate(data)
    except Exception as e:
        print(f"Error loading graph: {e}", file=sys.stderr)
        return 1

    errors = validate_graph(graph)
    if errors:
        print("Graph validation errors:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    # Create config
    config = ProjectConfig(
        name=args.name,
        platform=args.platform,
        buffers=[],
        apply_patches=False,
        output_dir=args.output,
        shared_cache=not getattr(args, "no_shared_cache", False),
    )

    config_errors = config.validate()
    if config_errors:
        print("Configuration errors:", file=sys.stderr)
        for config_err in config_errors:
            print(f"  - {config_err}", file=sys.stderr)
        return 1

    output_dir = (
        args.output
        if args.output
        else Path.cwd() / "build" / f"{args.name}_{args.platform}"
    )

    if args.dry_run:
        print(f"Would create project at: {output_dir}")
        print(f"  Source: dsp-graph ({graph_path.name})")
        print(f"  Graph: {graph.name}")
        print(f"  Platform: {args.platform}")
        print(f"  Inputs: {len(graph.inputs)}")
        print(f"  Outputs: {len(graph.outputs)}")
        print(f"  Parameters: {len(graph.params)}")
        if not args.no_build:
            print("  Would build after creating")
        return 0

    # Generate project
    try:
        generator = ProjectGenerator.from_graph(graph, config)
        project_dir = generator.generate(output_dir)
        print(f"Project created at: {project_dir}")
        print("  Source: dsp-graph")
        print(f"  Platform: {args.platform}")
        if graph.params:
            print(f"  Parameters: {', '.join(p.name for p in graph.params)}")
    except Exception as e:
        print(f"Error creating project: {e}", file=sys.stderr)
        return 1

    # Build unless --no-build or --dry-run
    if not args.no_build:
        try:
            builder = Builder(project_dir)
            result = builder.build(target_platform=args.platform)
            if result.success:
                print("Build successful!")
                if result.output_file:
                    print(f"Output: {result.output_file}")
            else:
                print("Build failed!", file=sys.stderr)
                if result.stderr:
                    print(result.stderr, file=sys.stderr)
                return 1
        except GenExtError as e:
            print(f"Build error: {e}", file=sys.stderr)
            return 1
    else:
        print()
        print("Next steps:")
        print(f"  cd {project_dir}")
        platform_impl = get_platform(args.platform)
        for instruction in platform_impl.get_build_instructions():
            print(f"  {instruction}")

    return 0


def _cmd_default_export(args: argparse.Namespace, export_path: Path) -> int:
    """Handle default command with a gen~ export directory source."""
    # Infer name
    if args.name is None:
        args.name = export_path.name
        if not args.name:
            print("Error: could not infer name from export path", file=sys.stderr)
            return 1

    # Parse the export
    try:
        parser = GenExportParser(export_path)
        export_info = parser.parse()
    except GenExtError as e:
        print(f"Error parsing export: {e}", file=sys.stderr)
        return 1

    # Determine buffers
    buffers = args.buffers if args.buffers else export_info.buffers

    # Validate buffer names
    invalid = parser.validate_buffer_names(buffers)
    if invalid:
        print(f"Error: Invalid buffer names: {invalid}", file=sys.stderr)
        print("Buffer names must be valid C identifiers.", file=sys.stderr)
        return 1

    # Reject --board on non-embedded platforms
    if args.board and args.platform not in ("daisy", "circle"):
        print(
            "Error: --board is only valid for daisy and circle",
            file=sys.stderr,
        )
        return 1

    # Validate --voices
    if args.voices < 1:
        print("Error: --voices must be >= 1", file=sys.stderr)
        return 1
    if args.voices > 1 and args.no_midi:
        print(
            "Error: --voices > 1 requires MIDI (incompatible with --no-midi)",
            file=sys.stderr,
        )
        return 1

    # Create config
    config = ProjectConfig(
        name=args.name,
        platform=args.platform,
        buffers=buffers,
        apply_patches=not args.no_patch,
        output_dir=args.output,
        shared_cache=not args.no_shared_cache,
        board=args.board,
        no_midi=args.no_midi,
        midi_gate=args.midi_gate,
        midi_freq=args.midi_freq,
        midi_vel=args.midi_vel,
        midi_freq_unit=args.midi_freq_unit,
        num_voices=args.voices,
    )

    # Validate
    errors = config.validate()
    if errors:
        print("Configuration errors:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    # Determine output directory
    output_dir = (
        args.output
        if args.output
        else Path.cwd() / "build" / f"{args.name}_{args.platform}"
    )

    if args.dry_run:
        print(f"Would create project at: {output_dir}")
        print(f"  Export: {export_info.name}")
        print(f"  Platform: {args.platform}")
        if args.board:
            print(f"  Board: {args.board}")
        print(f"  Inputs: {export_info.num_inputs}")
        print(f"  Outputs: {export_info.num_outputs}")
        print(f"  Parameters: {export_info.num_params}")
        print(f"  Buffers: {buffers if buffers else '(none)'}")
        if export_info.has_exp2f_issue and not args.no_patch:
            print("  Would apply exp2f -> exp2 patch")
        if not args.no_build:
            print("  Would build after creating")
        return 0

    # Generate project
    try:
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(output_dir)
        print(f"Project created at: {project_dir}")
        print(f"  External name: {args.name}~")
        print(f"  Platform: {args.platform}")
        if buffers:
            print(f"  Buffers: {', '.join(buffers)}")
    except GenExtError as e:
        print(f"Error creating project: {e}", file=sys.stderr)
        return 1

    # Build unless --no-build or --dry-run
    if not args.no_build:
        try:
            builder = Builder(project_dir)
            result = builder.build(target_platform=args.platform)
            if result.success:
                print("Build successful!")
                if result.output_file:
                    print(f"Output: {result.output_file}")
            else:
                print("Build failed!", file=sys.stderr)
                if result.stderr:
                    print(result.stderr, file=sys.stderr)
                return 1
        except GenExtError as e:
            print(f"Build error: {e}", file=sys.stderr)
            return 1
    else:
        print()
        print("Next steps:")
        print(f"  cd {project_dir}")
        platform_impl = get_platform(args.platform)
        for instruction in platform_impl.get_build_instructions():
            print(f"  {instruction}")

    return 0


def cmd_build(args: argparse.Namespace) -> int:
    """Handle the build command."""
    project_path = args.project_path.resolve()

    if not project_path.is_dir():
        print(f"Error: Project directory not found: {project_path}", file=sys.stderr)
        return 1

    try:
        builder = Builder(project_path)
        result = builder.build(
            target_platform=args.platform,
            clean=args.clean,
            verbose=args.verbose,
        )

        if result.success:
            print("Build successful!")
            if result.output_file:
                print(f"Output: {result.output_file}")
            return 0
        else:
            print("Build failed!", file=sys.stderr)
            if not args.verbose and result.stderr:
                print(result.stderr, file=sys.stderr)
            elif not args.verbose and result.stdout:
                lines = result.stdout.strip().split("\n")
                for line in lines[-20:]:
                    print(line, file=sys.stderr)
            return 1
    except GenExtError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_detect(args: argparse.Namespace) -> int:
    """Handle the detect command."""
    export_path = args.export_path.resolve()

    try:
        parser = GenExportParser(export_path)
        info = parser.parse()
    except GenExtError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if args.json:
        data = {
            "name": info.name,
            "path": str(info.path),
            "num_inputs": info.num_inputs,
            "num_outputs": info.num_outputs,
            "num_params": info.num_params,
            "buffers": info.buffers,
            "has_exp2f_issue": info.has_exp2f_issue,
            "cpp_file": str(info.cpp_path) if info.cpp_path else None,
            "h_file": str(info.h_path) if info.h_path else None,
        }
        print(json.dumps(data, indent=2))
    else:
        print(f"Gen~ Export: {info.name}")
        print(f"  Path: {info.path}")
        print(f"  Signal inputs: {info.num_inputs}")
        print(f"  Signal outputs: {info.num_outputs}")
        print(f"  Parameters: {info.num_params}")
        print(f"  Buffers: {info.buffers if info.buffers else '(none detected)'}")
        if info.has_exp2f_issue:
            print("  Patch needed: exp2f -> exp2 (macOS compatibility)")

    return 0


def cmd_patch(args: argparse.Namespace) -> int:
    """Handle the patch command."""
    target_path = args.target_path.resolve()

    if not target_path.is_dir():
        print(f"Error: Directory not found: {target_path}", file=sys.stderr)
        return 1

    patcher = Patcher(target_path)

    if args.dry_run:
        needed = patcher.check_patches_needed()
        if not any(needed.values()):
            print("No patches needed.")
            return 0

        print("Patches that would be applied:")
        for name, is_needed in needed.items():
            if is_needed:
                print(f"  - {name}")
        return 0

    results = patcher.apply_all()

    if not results:
        print("No patches needed or applicable.")
        return 0

    for result in results:
        if result.applied:
            print(f"Applied: {result.patch_name}")
            print(f"  File: {result.file_path}")
            print(f"  {result.message}")
        else:
            print(f"Skipped: {result.patch_name}")
            print(f"  {result.message}")

    return 0


def cmd_list(args: argparse.Namespace) -> int:
    """Handle the list command."""
    for name in list_platforms():
        print(name)
    return 0


def cmd_manifest(args: argparse.Namespace) -> int:
    """Handle the manifest command."""
    from gen_dsp.core.manifest import manifest_from_export_info

    export_path = args.export_path.resolve()

    try:
        parser = GenExportParser(export_path)
        export_info = parser.parse()
    except GenExtError as e:
        print(f"Error parsing export: {e}", file=sys.stderr)
        return 1

    buffers = args.buffers if args.buffers else export_info.buffers

    manifest = manifest_from_export_info(export_info, buffers, Platform.GENEXT_VERSION)
    print(manifest.to_json())
    return 0


def cmd_cache(args: argparse.Namespace) -> int:
    """Handle the cache command."""
    import os

    from gen_dsp.core.cache import get_cache_dir
    from gen_dsp.platforms.daisy import _resolve_libdaisy_dir, LIBDAISY_VERSION
    from gen_dsp.platforms.vcvrack import _resolve_rack_dir

    env_cache = os.environ.get("GEN_DSP_CACHE_DIR")
    if env_cache:
        cache_dir = Path(env_cache)
        print(f"Cache directory: {cache_dir}  (GEN_DSP_CACHE_DIR)")
    else:
        cache_dir = get_cache_dir()
        print(f"Cache directory: {cache_dir}")
    print()

    print("FetchContent (clap, lv2, sc, vst3):")
    if cache_dir.is_dir():
        src_dirs = sorted(
            d.name
            for d in cache_dir.iterdir()
            if d.is_dir()
            and d.name.endswith("-src")
            and d.name not in ("rack-sdk-src", "libdaisy-src")
        )
        if src_dirs:
            for name in src_dirs:
                sdk_name = name.removesuffix("-src")
                print(f"  {sdk_name}  ({cache_dir / name})")
        else:
            print("  (empty)")
    else:
        print("  (not created)")
    print()

    rack_dir = _resolve_rack_dir()
    rack_present = (rack_dir / "Makefile").is_file()
    print("Rack SDK (vcvrack):")
    print(f"  Path: {rack_dir}")
    print(f"  Status: {'present' if rack_present else 'not downloaded'}")
    print()

    libdaisy_dir = _resolve_libdaisy_dir()
    libdaisy_present = (libdaisy_dir / "core" / "Makefile").is_file()
    libdaisy_built = (libdaisy_dir / "build" / "libdaisy.a").is_file()
    print(f"libDaisy {LIBDAISY_VERSION} (daisy):")
    print(f"  Path: {libdaisy_dir}")
    if libdaisy_built:
        print("  Status: built")
    elif libdaisy_present:
        print("  Status: cloned (not built)")
    else:
        print("  Status: not cloned")

    return 0


def cmd_chain(args: argparse.Namespace) -> int:
    """Handle the chain command (multi-plugin chain mode, Circle only)."""
    from gen_dsp.core.graph import (
        parse_graph,
        validate_linear_chain,
        validate_dag,
    )
    from gen_dsp.core.graph_init import (
        resolve_export_dirs,
        init_chain_linear,
        init_chain_dag,
    )

    if args.platform != "circle":
        print(
            "Error: chain command is currently only supported for the circle platform",
            file=sys.stderr,
        )
        return 1

    graph_path = args.graph.resolve()

    try:
        graph = parse_graph(graph_path)
    except GenExtError as e:
        print(f"Error parsing graph: {e}", file=sys.stderr)
        return 1

    linear_errors = validate_linear_chain(graph)
    is_linear = len(linear_errors) == 0

    if not is_linear:
        dag_errors = validate_dag(graph)
        if dag_errors:
            print("Graph validation errors:", file=sys.stderr)
            for err in dag_errors:
                print(f"  - {err}", file=sys.stderr)
            return 1

    export_dirs = resolve_export_dirs(args.export_path.resolve(), graph, args.exports)

    output_dir = args.output if args.output else Path.cwd() / "build" / args.name
    output_dir = Path(output_dir).resolve()

    config = ProjectConfig(
        name=args.name,
        platform="circle",
        buffers=[],
        apply_patches=not args.no_patch,
        output_dir=args.output,
        board=args.board,
    )

    if is_linear:
        return init_chain_linear(
            graph,
            export_dirs,
            output_dir,
            args.name,
            config,
            apply_patches=not args.no_patch,
            dry_run=args.dry_run,
            board=args.board,
        )
    else:
        return init_chain_dag(
            graph,
            export_dirs,
            output_dir,
            args.name,
            config,
            apply_patches=not args.no_patch,
            dry_run=args.dry_run,
            board=args.board,
        )


def _dispatch_subcommand(argv: list[str]) -> int:
    """Parse and dispatch a subcommand."""
    parser = _make_subcommand_parser()
    args = parser.parse_args(argv)

    handlers = {
        "build": cmd_build,
        "detect": cmd_detect,
        "patch": cmd_patch,
        "list": cmd_list,
        "cache": cmd_cache,
        "manifest": cmd_manifest,
        "chain": cmd_chain,
    }

    # Add graph subcommand handlers if available
    try:
        from gen_dsp.graph.cli import cmd_compile, cmd_validate, cmd_dot, cmd_simulate

        handlers["compile"] = cmd_compile
        handlers["validate"] = cmd_validate
        handlers["dot"] = cmd_dot
        handlers["sim"] = cmd_simulate
    except ImportError:
        pass

    handler = handlers.get(args.command)
    if handler:
        return handler(args)
    else:
        _print_help()
        return 1


def main(argv: Optional[list[str]] = None) -> int:
    """Main entry point."""
    argv = argv if argv is not None else sys.argv[1:]

    if not argv or argv[0] in ("-h", "--help"):
        _print_help()
        return 0

    if argv[0] in ("-V", "--version"):
        print(f"gen-dsp {__version__}")
        return 0

    if argv[0] in SUBCOMMANDS:
        return _dispatch_subcommand(argv)
    else:
        return _cmd_default(argv)


if __name__ == "__main__":
    sys.exit(main())
