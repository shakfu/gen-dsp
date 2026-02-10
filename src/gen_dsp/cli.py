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
        description="Generate PureData and Max/MSP externals from Max gen~ exports",
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
        help="Daisy board variant: seed, pod, patch, patch_sm, field, petal, legio, versio (default: seed)",
    )
    init_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without creating files",
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

    return parser


def cmd_init(args: argparse.Namespace) -> int:
    """Handle the init command."""
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

    # Warn if --shared-cache used with non-CMake platform
    cmake_platforms = {"clap", "vst3", "lv2", "sc"}
    if (
        args.shared_cache
        and args.platform not in cmake_platforms
        and args.platform != "both"
    ):
        print(
            f"Warning: --shared-cache has no effect for platform '{args.platform}' "
            f"(only {', '.join(sorted(cmake_platforms))})",
            file=sys.stderr,
        )

    # Warn if --board used with non-daisy platform
    if args.board and args.platform != "daisy":
        print(
            f"Warning: --board has no effect for platform '{args.platform}' "
            f"(only daisy)",
            file=sys.stderr,
        )

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
    }

    handler = commands.get(args.command)
    if handler:
        return handler(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
