"""
Command-line interface for gen_dsp.

Usage:
    gen-dsp init <export-path> -n <name> [-p <platform>] [-o <output>]
    gen-dsp build [project-path] [-p <platform>] [--clean]
    gen-dsp detect <export-path> [--json]
    gen-dsp patch <target-path> [--dry-run]
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


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser."""
    parser = argparse.ArgumentParser(
        prog="gen-dsp",
        description="Generate buildable audio DSP externals from Max gen~ exports",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Initialize a new project from a gen~ export
  gen-dsp init ./my_export -n myeffect -p pd -o ./myeffect_project

  # Detect buffers and I/O in a gen~ export
  gen-dsp detect ./my_export

  # Build an existing project
  gen-dsp build ./myeffect_project

  # Apply platform patches (exp2f fix)
  gen-dsp patch ./myeffect_project

  # List available target platforms
  gen-dsp list

  # Show cached SDKs and dependencies
  gen-dsp cache
""",
    )

    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"gen-dsp {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # init command
    init_parser = subparsers.add_parser(
        "init",
        help="Create a new project from a gen~ export",
        description="Initialize a new gen_dsp project from exported gen~ code.",
    )
    init_parser.add_argument(
        "export_path",
        type=Path,
        help="Path to the gen~ export directory",
    )
    init_parser.add_argument(
        "-n",
        "--name",
        required=True,
        help="Name for the external (will be loaded as <name>~ in Pd)",
    )
    init_parser.add_argument(
        "-p",
        "--platform",
        choices=list_platforms() + ["both"],
        default="pd",
        help=f"Target platform: {', '.join(list_platforms())}, or 'both' (default: pd)",
    )
    init_parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output directory (default: ./<name>)",
    )
    init_parser.add_argument(
        "--buffers",
        nargs="+",
        help="Buffer names (overrides auto-detection)",
    )
    init_parser.add_argument(
        "--no-patch",
        action="store_true",
        help="Don't apply platform patches (exp2f fix)",
    )
    init_parser.add_argument(
        "--shared-cache",
        action="store_true",
        help="Use shared OS cache for FetchContent downloads (clap, vst3, lv2, sc)",
    )
    init_parser.add_argument(
        "--board",
        help="Board variant for embedded platforms. "
        "Daisy: seed, pod, patch, patch_sm, field, petal, legio, versio (default: seed). "
        "Circle: pi3-i2s, pi4-usb, pi5-hdmi, etc. (default: pi3-i2s)",
    )
    init_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without creating files",
    )
    init_parser.add_argument(
        "--graph",
        type=Path,
        help="JSON graph file for multi-plugin chain mode (Circle only)",
    )
    init_parser.add_argument(
        "--export",
        type=Path,
        action="append",
        dest="exports",
        help="Additional export path (can be repeated). "
        "Use with --graph to specify explicit paths for chain nodes.",
    )

    # build command
    build_parser = subparsers.add_parser(
        "build",
        help="Build an existing project",
        description="Compile the external for the target platform.",
    )
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
        help=f"Target platform: {', '.join(list_platforms())} (default: pd)",
    )
    build_parser.add_argument(
        "--clean",
        action="store_true",
        help="Clean before building",
    )
    build_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show build output in real-time",
    )

    # detect command
    detect_parser = subparsers.add_parser(
        "detect",
        help="Analyze a gen~ export",
        description="Detect buffers, I/O counts, and patches needed.",
    )
    detect_parser.add_argument(
        "export_path",
        type=Path,
        help="Path to the gen~ export directory",
    )
    detect_parser.add_argument(
        "--json",
        action="store_true",
        help="Output in JSON format",
    )

    # patch command
    patch_parser = subparsers.add_parser(
        "patch",
        help="Apply platform-specific patches",
        description="Apply patches like exp2f -> exp2 fix for macOS.",
    )
    patch_parser.add_argument(
        "target_path",
        type=Path,
        help="Path to the project or gen~ export directory",
    )
    patch_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without modifying files",
    )

    # list command
    subparsers.add_parser(
        "list",
        help="List available target platforms",
        description="Show all supported target platforms.",
    )

    # cache command
    subparsers.add_parser(
        "cache",
        help="Show cached SDKs and dependencies",
        description="Show paths and status of cached SDKs and dependencies.",
    )

    # manifest command
    manifest_parser = subparsers.add_parser(
        "manifest",
        help="Emit a JSON manifest for a gen~ export",
        description="Parse a gen~ export and emit the Manifest IR as JSON to stdout.",
    )
    manifest_parser.add_argument(
        "export_path",
        type=Path,
        help="Path to the gen~ export directory",
    )
    manifest_parser.add_argument(
        "--buffers",
        nargs="+",
        help="Buffer names (overrides auto-detection)",
    )

    return parser


def cmd_init(args: argparse.Namespace) -> int:
    """Handle the init command."""
    # Branch to chain mode if --graph is provided
    if args.graph:
        return cmd_init_chain(args)

    export_path = args.export_path.resolve()

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

    # Reject --shared-cache on non-CMake platforms
    cmake_platforms = {"clap", "vst3", "lv2", "sc"}
    if (
        args.shared_cache
        and args.platform not in cmake_platforms
        and args.platform != "both"
    ):
        print(
            f"Error: --shared-cache is only valid for {', '.join(sorted(cmake_platforms))}",
            file=sys.stderr,
        )
        return 1

    # Reject --board on non-embedded platforms
    if args.board and args.platform not in ("daisy", "circle"):
        print(
            "Error: --board is only valid for daisy and circle",
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
        shared_cache=args.shared_cache,
        board=args.board,
    )

    # Validate
    errors = config.validate()
    if errors:
        print("Configuration errors:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    # Determine output directory
    output_dir = args.output if args.output else Path.cwd() / args.name

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
        print()
        print("Next steps:")
        print(f"  cd {project_dir}")
        if args.platform == "both":
            # Show instructions for all platforms
            for platform_name in list_platforms():
                platform_impl = get_platform(platform_name)
                print(f"  # For {platform_name}:")
                for instruction in platform_impl.get_build_instructions():
                    print(f"  {instruction}")
        else:
            # Show instructions for specific platform
            platform_impl = get_platform(args.platform)
            for instruction in platform_impl.get_build_instructions():
                print(f"  {instruction}")
    except GenExtError as e:
        print(f"Error creating project: {e}", file=sys.stderr)
        return 1

    return 0


def cmd_init_chain(args: argparse.Namespace) -> int:
    """Handle init command in chain mode (--graph provided)."""
    from gen_dsp.core.graph import parse_graph, validate_linear_chain, resolve_chain
    from gen_dsp.core.project import ProjectGenerator
    from gen_dsp.platforms.circle import CirclePlatform

    # Validate platform
    if args.platform != "circle":
        print(
            "Error: --graph is currently only supported for the circle platform",
            file=sys.stderr,
        )
        return 1

    graph_path = args.graph.resolve()

    # Parse graph
    try:
        graph = parse_graph(graph_path)
    except GenExtError as e:
        print(f"Error parsing graph: {e}", file=sys.stderr)
        return 1

    # Validate linear chain
    errors = validate_linear_chain(graph)
    if errors:
        print("Graph validation errors:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    # Resolve export directories
    # Base directory: the positional export_path arg
    # Each node's 'export' field is resolved as a subdirectory
    # --export flags provide explicit overrides
    base_dir = args.export_path.resolve()
    export_dirs: dict[str, Path] = {}

    # First, try to resolve each node's export from the base directory
    for node_id, node_config in graph.nodes.items():
        candidate = base_dir / node_config.export / "gen"
        if candidate.is_dir():
            export_dirs[node_config.export] = candidate
        else:
            # Try without /gen suffix
            candidate = base_dir / node_config.export
            if candidate.is_dir():
                export_dirs[node_config.export] = candidate

    # Override with --export paths if provided
    if args.exports:
        for export_path in args.exports:
            resolved = export_path.resolve()
            # Use the directory name as the export key
            export_dirs[resolved.name] = resolved

    # Resolve chain
    try:
        chain = resolve_chain(graph, export_dirs, ProjectGenerator.GENEXT_VERSION)
    except GenExtError as e:
        print(f"Error resolving chain: {e}", file=sys.stderr)
        return 1

    # Determine output directory
    output_dir = args.output if args.output else Path.cwd() / args.name
    output_dir = Path(output_dir).resolve()

    if args.dry_run:
        print(f"Would create chain project at: {output_dir}")
        print("  Platform: circle (chain mode)")
        if args.board:
            print(f"  Board: {args.board}")
        print(f"  Nodes: {len(chain)}")
        for node in chain:
            print(
                f"    [{node.index}] {node.config.id}: {node.config.export} "
                f"({node.manifest.num_inputs}in/{node.manifest.num_outputs}out, "
                f"{node.manifest.num_params} params, MIDI ch {node.config.midi_channel})"
            )
        return 0

    # Generate chain project
    try:
        output_dir.mkdir(parents=True, exist_ok=True)

        config = ProjectConfig(
            name=args.name,
            platform="circle",
            buffers=[],
            apply_patches=not args.no_patch,
            output_dir=args.output,
            board=args.board,
        )

        platform = CirclePlatform()
        platform.generate_chain_project(chain, graph, output_dir, args.name, config)

        # Copy each node's gen~ export to gen_<export_name>/ subdirectories
        import shutil

        for node in chain:
            export_dest = output_dir / f"gen_{node.config.export}"
            if export_dest.exists():
                shutil.rmtree(export_dest)
            shutil.copytree(node.export_info.path, export_dest)

        # Apply patches if requested
        if not args.no_patch:
            from gen_dsp.core.patcher import Patcher

            for node in chain:
                export_dest = output_dir / f"gen_{node.config.export}"
                patcher = Patcher(export_dest)
                patcher.apply_all()

        print(f"Chain project created at: {output_dir}")
        print("  Platform: circle (chain mode)")
        print(f"  Nodes: {len(chain)}")
        for node in chain:
            print(
                f"    [{node.index}] {node.config.id}: {node.config.export} "
                f"({node.manifest.num_inputs}in/{node.manifest.num_outputs}out)"
            )
        print()
        print("Next steps:")
        print(f"  cd {output_dir}")
        print("  make")
    except GenExtError as e:
        print(f"Error creating chain project: {e}", file=sys.stderr)
        return 1

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
                # Show last lines of stdout for errors
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
    from gen_dsp.core.project import ProjectGenerator

    export_path = args.export_path.resolve()

    try:
        parser = GenExportParser(export_path)
        export_info = parser.parse()
    except GenExtError as e:
        print(f"Error parsing export: {e}", file=sys.stderr)
        return 1

    buffers = args.buffers if args.buffers else export_info.buffers

    manifest = manifest_from_export_info(
        export_info, buffers, ProjectGenerator.GENEXT_VERSION
    )
    print(manifest.to_json())
    return 0


def cmd_cache(args: argparse.Namespace) -> int:
    """Handle the cache command."""
    import os

    from gen_dsp.core.cache import get_cache_dir
    from gen_dsp.platforms.daisy import _resolve_libdaisy_dir, LIBDAISY_VERSION
    from gen_dsp.platforms.vcvrack import _resolve_rack_dir

    # Resolve effective cache dir (GEN_DSP_CACHE_DIR overrides OS default)
    env_cache = os.environ.get("GEN_DSP_CACHE_DIR")
    if env_cache:
        cache_dir = Path(env_cache)
        print(f"Cache directory: {cache_dir}  (GEN_DSP_CACHE_DIR)")
    else:
        cache_dir = get_cache_dir()
        print(f"Cache directory: {cache_dir}")
    print()

    # FetchContent cache (CMake platforms that fetch SDKs)
    print("FetchContent (clap, lv2, sc, vst3):")
    if cache_dir.is_dir():
        # FetchContent creates *-src, *-build, *-subbuild; only show -src
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

    # Rack SDK
    rack_dir = _resolve_rack_dir()
    rack_present = (rack_dir / "Makefile").is_file()
    print("Rack SDK (vcvrack):")
    print(f"  Path: {rack_dir}")
    print(f"  Status: {'present' if rack_present else 'not downloaded'}")
    print()

    # libDaisy
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


def main(argv: Optional[list[str]] = None) -> int:
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    commands = {
        "init": cmd_init,
        "build": cmd_build,
        "detect": cmd_detect,
        "patch": cmd_patch,
        "list": cmd_list,
        "cache": cmd_cache,
        "manifest": cmd_manifest,
    }

    handler = commands.get(args.command)
    if handler:
        return handler(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
