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
from typing import TYPE_CHECKING, Optional

from gen_dsp import __version__

if TYPE_CHECKING:
    from gen_dsp.graph.models import Graph

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
    "doctor",
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

  -p, --platform PLATFORM   Target platform(s) (required): a name, a
                            comma-separated list (clap,vst3,au), or 'all'.
                            Available: {platforms}
  -n, --name NAME           Plugin name (default: inferred from source)
  -o, --output DIR          Output directory (default: <name>_<platform>)
  --no-build                Skip building after project creation
  --dry-run                 Show what would be done without creating files
  --buffers NAME [NAME ...]
  --no-patch                Skip platform patches
  --no-shared-cache         Disable shared OS cache for FetchContent downloads
  --cache-dir DIR           Explicit FetchContent cache directory
  --board BOARD             Board variant (daisy, circle)
  --no-midi                 Disable MIDI note handling
  --midi-gate NAME          MIDI gate parameter name
  --midi-freq NAME          MIDI frequency parameter name
  --midi-vel NAME           MIDI velocity parameter name
  --midi-freq-unit {{hz,midi}}
  --voices N                Polyphony voices (default: 1)
  --inputs-as-params [NAME ...]
                            Remap signal inputs to params (all or named)

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
  doctor                    Check build prerequisites per platform
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
        nargs="?",
        default=None,
        help="Path to gen~ export directory, .gdsp file, or graph JSON file "
        "(may be set in gen-dsp.toml instead)",
    )
    parser.add_argument(
        "-p",
        "--platform",
        default=None,
        metavar="PLATFORM",
        help="Target platform(s): a name, a comma-separated list "
        "(e.g. clap,vst3,au), or 'all' (may be set in gen-dsp.toml instead)",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        metavar="PATH",
        help="Read defaults from a gen-dsp.toml file (default: ./gen-dsp.toml "
        "if present). CLI flags override config values.",
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
        "--cache-dir",
        type=Path,
        default=None,
        help="Explicit FetchContent cache directory (baked into CMakeLists.txt)",
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
        "--inputs-as-params",
        nargs="*",
        default=None,
        metavar="NAME",
        help="Remap signal inputs to parameters. "
        "No names = remap all; with names = remap only those inputs.",
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
    detect_parser = subparsers.add_parser(
        "detect", help="Analyze a gen~ export or a graph file"
    )
    detect_parser.add_argument(
        "export_path",
        type=Path,
        metavar="PATH",
        help="gen~ export directory, or a .gdsp / .json graph file",
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
    cache_parser = subparsers.add_parser(
        "cache", help="Show or prune cached SDKs and dependencies"
    )
    cache_parser.add_argument(
        "--prune",
        action="store_true",
        help="Delete the cached SDKs to reclaim disk space",
    )
    cache_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="With --prune, show what would be removed without deleting",
    )
    cache_parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="With --prune, skip the confirmation prompt",
    )

    # doctor command
    doctor_parser = subparsers.add_parser(
        "doctor", help="Check build prerequisites per platform"
    )
    doctor_parser.add_argument(
        "-p",
        "--platform",
        choices=list_platforms(),
        help="Check a single platform (default: all)",
    )
    doctor_parser.add_argument(
        "--json", action="store_true", help="Output in JSON format"
    )

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


def _resolve_platforms(spec: str) -> tuple[list[str], Optional[str]]:
    """Parse a ``--platform`` spec into an ordered, de-duplicated platform list.

    Accepts a single name, a comma-separated list, or ``all``. Returns
    ``(platforms, error)``; ``error`` is a message string when the spec is
    invalid (and ``platforms`` is empty).
    """
    valid = list_platforms()
    if spec.strip() == "all":
        return valid, None

    names = [p.strip() for p in spec.split(",") if p.strip()]
    if not names:
        return [], "no platform specified"

    invalid = [p for p in names if p not in valid]
    if invalid:
        return [], (
            f"unknown platform(s): {', '.join(invalid)}. "
            f"Available: {', '.join(valid)} (or 'all')"
        )

    seen: set[str] = set()
    ordered: list[str] = []
    for p in names:
        if p not in seen:
            seen.add(p)
            ordered.append(p)
    return ordered, None


def _target_output_dir(
    args: argparse.Namespace, name: str, platform: str, multi: bool
) -> Path:
    """Resolve the output directory for one target.

    Single target with ``-o`` uses it verbatim (backwards compatible); with
    multiple targets ``-o`` is treated as a parent directory. Without ``-o`` the
    default is ``build/<name>_<platform>``.
    """
    if args.output:
        base = Path(args.output)
        return base / f"{name}_{platform}" if multi else base
    return Path.cwd() / "build" / f"{name}_{platform}"


def _print_target_summary(results: list[tuple[str, str]]) -> None:
    """Print a per-target summary for multi-target runs."""
    print()
    print("Summary:")
    for platform, status in results:
        print(f"  {platform:<10}  {status}")


# Keys accepted in gen-dsp.toml, mapped to default-command argparse destinations.
_CONFIG_PATH_KEYS = frozenset({"source", "output", "cache_dir"})
_CONFIG_BOOL_KEYS = frozenset(
    {"no_build", "no_patch", "no_shared_cache", "no_midi", "dry_run"}
)
_CONFIG_STR_KEYS = frozenset(
    {"name", "board", "midi_gate", "midi_freq", "midi_vel", "midi_freq_unit"}
)
_CONFIG_KEYS = (
    _CONFIG_PATH_KEYS
    | _CONFIG_BOOL_KEYS
    | _CONFIG_STR_KEYS
    | {"platform", "buffers", "voices", "inputs_as_params"}
)


def _load_config(path: Path) -> tuple[dict[str, object], Optional[str]]:
    """Load gen-dsp.toml into a mapping of default-command argparse defaults.

    Keys mirror the CLI options (hyphens or underscores accepted). Returns
    ``(defaults, error)``; ``error`` is set on a parse or validation failure.
    """
    try:
        import tomllib
    except ModuleNotFoundError:  # Python 3.10
        try:
            import tomli as tomllib  # type: ignore[import-not-found, no-redef]
        except ModuleNotFoundError:
            return {}, (
                "reading gen-dsp.toml requires Python 3.11+ or the 'tomli' "
                "package (pip install tomli)"
            )

    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except OSError as e:
        return {}, f"cannot read {path}: {e}"
    except tomllib.TOMLDecodeError as e:
        return {}, f"invalid TOML: {e}"

    mapped: dict[str, object] = {}
    for raw_key, value in data.items():
        key = raw_key.replace("-", "_")
        if key not in _CONFIG_KEYS:
            return {}, f"unknown key '{raw_key}'"

        if key == "platform":
            if isinstance(value, list):
                value = ",".join(str(v) for v in value)
            elif not isinstance(value, str):
                return {}, f"'{raw_key}' must be a string or list of strings"
        elif key in _CONFIG_PATH_KEYS:
            if not isinstance(value, str):
                return {}, f"'{raw_key}' must be a string path"
            value = Path(value)
        elif key in _CONFIG_BOOL_KEYS:
            if not isinstance(value, bool):
                return {}, f"'{raw_key}' must be a boolean"
        elif key in _CONFIG_STR_KEYS:
            if not isinstance(value, str):
                return {}, f"'{raw_key}' must be a string"
        elif key == "voices":
            if not isinstance(value, int) or isinstance(value, bool):
                return {}, "'voices' must be an integer"
        elif key == "buffers":
            if not (isinstance(value, list) and all(isinstance(v, str) for v in value)):
                return {}, "'buffers' must be a list of strings"
        elif key == "inputs_as_params":
            if value is True:
                value = []  # remap all inputs
            elif value is False:
                continue  # not remapping; keep argparse default (None)
            elif not (
                isinstance(value, list) and all(isinstance(v, str) for v in value)
            ):
                return {}, "'inputs_as_params' must be true or a list of strings"

        mapped[key] = value
    return mapped, None


def _cmd_default(argv: list[str]) -> int:
    """Handle the default command: [source] -p <platform> [flags] (+ gen-dsp.toml)."""
    parser = _make_default_parser()

    # Resolve the config file: explicit --config, else ./gen-dsp.toml if present.
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--config", type=Path, default=None)
    pre_args, _ = pre.parse_known_args(argv)
    config_path: Optional[Path] = pre_args.config
    if config_path is None:
        default_cfg = Path.cwd() / "gen-dsp.toml"
        if default_cfg.is_file():
            config_path = default_cfg

    if config_path is not None:
        if not config_path.is_file():
            print(f"Error: config file not found: {config_path}", file=sys.stderr)
            return 1
        defaults, err = _load_config(config_path)
        if err:
            print(f"Error in {config_path}: {err}", file=sys.stderr)
            return 1
        parser.set_defaults(**defaults)
        print(f"Using config: {config_path}")

    args = parser.parse_args(argv)

    if args.source is None:
        print(
            "Error: no source given (pass a path, or set 'source' in gen-dsp.toml)",
            file=sys.stderr,
        )
        return 1
    if args.platform is None:
        print(
            "Error: no platform given (pass -p, or set 'platform' in gen-dsp.toml)",
            file=sys.stderr,
        )
        return 1

    source = Path(args.source).resolve()

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


def _build_or_next_steps(
    args: argparse.Namespace, platform: str, project_dir: Path
) -> int:
    """Build the generated project, or print next steps if --no-build.

    Shared tail of the gen~-export and graph default commands. Returns a
    process exit code (0 on success or when only printing next steps, 1 on
    build failure).
    """
    if args.no_build:
        print()
        print("Next steps:")
        print(f"  cd {project_dir}")
        for instruction in get_platform(platform).get_build_instructions():
            print(f"  {instruction}")
        return 0

    try:
        builder = Builder(project_dir)
        result = builder.build(target_platform=platform)
    except GenExtError as e:
        print(f"Build error: {e}", file=sys.stderr)
        return 1

    if result.success:
        print("Build successful!")
        if result.output_file:
            print(f"Output: {result.output_file}")
        return 0

    print("Build failed!", file=sys.stderr)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    return 1


def _cmd_default_graph(args: argparse.Namespace, graph_path: Path) -> int:
    """Handle default command with a graph file source."""
    # Infer name
    if args.name is None:
        args.name = graph_path.stem
        if not args.name:
            print("Error: could not infer name from graph file", file=sys.stderr)
            return 1

    # Load graph (handles the optional-pydantic guard and parse errors)
    graph, load_err = _load_graph_file(graph_path)
    if load_err:
        print(f"Error: {load_err}", file=sys.stderr)
        return 1
    assert graph is not None

    from gen_dsp.graph.validate import validate_graph

    errors = validate_graph(graph)
    if errors:
        print("Graph validation errors:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    # Resolve target platform(s)
    platforms, perr = _resolve_platforms(args.platform)
    if perr:
        print(f"Error: {perr}", file=sys.stderr)
        return 1
    multi = len(platforms) > 1

    results: list[tuple[str, str]] = []
    overall = 0
    for platform in platforms:
        if multi:
            print(f"=== {platform} ===")

        config = ProjectConfig(
            name=args.name,
            platform=platform,
            buffers=[],
            apply_patches=False,
            shared_cache=not getattr(args, "no_shared_cache", False),
            cache_dir=getattr(args, "cache_dir", None),
        )
        config_errors = config.validate()
        if config_errors:
            print("Configuration errors:", file=sys.stderr)
            for config_err in config_errors:
                print(f"  - {config_err}", file=sys.stderr)
            results.append((platform, "config error"))
            overall = 1
            continue

        output_dir = _target_output_dir(args, args.name, platform, multi)

        if args.dry_run:
            print(f"Would create project at: {output_dir}")
            print(f"  Source: dsp-graph ({graph_path.name})")
            print(f"  Graph: {graph.name}")
            print(f"  Platform: {platform}")
            print(f"  Inputs: {len(graph.inputs)}")
            print(f"  Outputs: {len(graph.outputs)}")
            print(f"  Parameters: {len(graph.params)}")
            if not args.no_build:
                print("  Would build after creating")
            results.append((platform, "dry-run"))
            continue

        try:
            generator = ProjectGenerator.from_graph(graph, config)
            project_dir = generator.generate(output_dir)
            print(f"Project created at: {project_dir}")
            print("  Source: dsp-graph")
            print(f"  Platform: {platform}")
            if graph.params:
                print(f"  Parameters: {', '.join(p.name for p in graph.params)}")
        except Exception as e:
            print(f"Error creating project: {e}", file=sys.stderr)
            results.append((platform, "generate error"))
            overall = 1
            continue

        rc = _build_or_next_steps(args, platform, project_dir)
        results.append((platform, "ok" if rc == 0 else "build failed"))
        if rc != 0:
            overall = 1

    if multi:
        _print_target_summary(results)
    return overall


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

    # Resolve target platform(s)
    platforms, perr = _resolve_platforms(args.platform)
    if perr:
        print(f"Error: {perr}", file=sys.stderr)
        return 1
    multi = len(platforms) > 1
    embedded = {"daisy", "circle"}

    # Reject --board when no selected platform can use it
    if args.board and not any(p in embedded for p in platforms):
        print(
            "Error: --board is only valid for daisy and circle",
            file=sys.stderr,
        )
        return 1

    # Validate --voices (platform-independent)
    if args.voices < 1:
        print("Error: --voices must be >= 1", file=sys.stderr)
        return 1
    if args.voices > 1 and args.no_midi:
        print(
            "Error: --voices > 1 requires MIDI (incompatible with --no-midi)",
            file=sys.stderr,
        )
        return 1

    results: list[tuple[str, str]] = []
    overall = 0
    for platform in platforms:
        if multi:
            print(f"=== {platform} ===")

        # --board only applies to the embedded platforms.
        board = args.board if platform in embedded else None

        config = ProjectConfig(
            name=args.name,
            platform=platform,
            buffers=buffers,
            apply_patches=not args.no_patch,
            shared_cache=not args.no_shared_cache,
            cache_dir=args.cache_dir,
            board=board,
            no_midi=args.no_midi,
            midi_gate=args.midi_gate,
            midi_freq=args.midi_freq,
            midi_vel=args.midi_vel,
            midi_freq_unit=args.midi_freq_unit,
            num_voices=args.voices,
            inputs_as_params=args.inputs_as_params,
        )
        errors = config.validate()
        if errors:
            print("Configuration errors:", file=sys.stderr)
            for err in errors:
                print(f"  - {err}", file=sys.stderr)
            results.append((platform, "config error"))
            overall = 1
            continue

        output_dir = _target_output_dir(args, args.name, platform, multi)

        if args.dry_run:
            print(f"Would create project at: {output_dir}")
            print(f"  Export: {export_info.name}")
            print(f"  Platform: {platform}")
            if board:
                print(f"  Board: {board}")
            print(f"  Inputs: {export_info.num_inputs}")
            print(f"  Outputs: {export_info.num_outputs}")
            print(f"  Parameters: {export_info.num_params}")
            print(f"  Buffers: {buffers if buffers else '(none)'}")
            if export_info.has_exp2f_issue and not args.no_patch:
                print("  Would apply exp2f -> exp2 patch")
            if not args.no_build:
                print("  Would build after creating")
            results.append((platform, "dry-run"))
            continue

        try:
            generator = ProjectGenerator(export_info, config)
            project_dir = generator.generate(output_dir)
            print(f"Project created at: {project_dir}")
            print(f"  External name: {args.name}~")
            print(f"  Platform: {platform}")
            if buffers:
                print(f"  Buffers: {', '.join(buffers)}")
        except GenExtError as e:
            print(f"Error creating project: {e}", file=sys.stderr)
            results.append((platform, "generate error"))
            overall = 1
            continue

        rc = _build_or_next_steps(args, platform, project_dir)
        results.append((platform, "ok" if rc == 0 else "build failed"))
        if rc != 0:
            overall = 1

    if multi:
        _print_target_summary(results)
    return overall


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


def _load_graph_file(
    graph_path: Path,
) -> tuple[Optional["Graph"], Optional[str]]:
    """Load a ``.gdsp`` or ``.json`` graph file.

    Returns ``(graph, error)``; ``error`` is a message string on failure
    (missing pydantic, parse/validation error) and ``graph`` is then None.
    """
    try:
        from gen_dsp.graph import _require_dsp_graph

        _require_dsp_graph()
    except ImportError as e:
        return None, str(e)

    from gen_dsp.graph.models import Graph

    try:
        if graph_path.suffix == ".gdsp":
            from gen_dsp.graph.dsl import parse_file

            parsed = parse_file(graph_path)
            if not isinstance(parsed, Graph):
                return None, "expected a single graph (multi-graph files unsupported)"
            graph = parsed
        else:
            graph = Graph.model_validate(json.loads(graph_path.read_text()))
    except Exception as e:
        return None, f"error loading graph: {e}"
    return graph, None


def cmd_detect(args: argparse.Namespace) -> int:
    """Handle the detect command (gen~ export directory or graph file)."""
    path = args.export_path.resolve()
    if path.suffix in (".gdsp", ".json"):
        return _detect_graph(args, path)
    return _detect_export(args, path)


def _detect_graph(args: argparse.Namespace, graph_path: Path) -> int:
    """Introspect a dsp-graph file (parity with gen~ export detection)."""
    from collections import Counter

    graph, err = _load_graph_file(graph_path)
    if err:
        print(f"Error: {err}", file=sys.stderr)
        return 1
    assert graph is not None

    from gen_dsp.graph.models import Buffer, DelayLine
    from gen_dsp.graph.validate import validate_graph

    errors = validate_graph(graph)
    type_counts = dict(sorted(Counter(type(n).__name__ for n in graph.nodes).items()))
    buffers = [n.id for n in graph.nodes if isinstance(n, Buffer)]
    delay_lines = [n.id for n in graph.nodes if isinstance(n, DelayLine)]

    if args.json:
        data = {
            "name": graph.name,
            "path": str(graph_path),
            "source": "dsp-graph",
            "num_inputs": len(graph.inputs),
            "num_outputs": len(graph.outputs),
            "num_params": len(graph.params),
            "params": [
                {"name": p.name, "min": p.min, "max": p.max, "default": p.default}
                for p in graph.params
            ],
            "num_nodes": len(graph.nodes),
            "node_types": type_counts,
            "buffers": buffers,
            "delay_lines": delay_lines,
            "valid": not errors,
            "errors": errors,
        }
        print(json.dumps(data, indent=2))
        return 0

    print(f"Graph: {graph.name} (dsp-graph)")
    print(f"  Path: {graph_path}")
    in_ids = ", ".join(i.id for i in graph.inputs)
    out_ids = ", ".join(o.id for o in graph.outputs)
    print(f"  Inputs: {len(graph.inputs)}" + (f" ({in_ids})" if in_ids else ""))
    print(f"  Outputs: {len(graph.outputs)}" + (f" ({out_ids})" if out_ids else ""))
    print(f"  Parameters: {len(graph.params)}")
    for p in graph.params:
        print(f"    - {p.name} [{p.min}, {p.max}] default {p.default}")
    print(f"  Nodes: {len(graph.nodes)}")
    for tname, count in type_counts.items():
        print(f"    {tname}: {count}")
    if buffers:
        print(f"  Buffers: {', '.join(buffers)}")
    if delay_lines:
        print(f"  Delay lines: {', '.join(delay_lines)}")
    if errors:
        print(f"  Valid: no ({len(errors)} error(s))")
        for e in errors:
            print(f"    - {e}")
    else:
        print("  Valid: yes")
    return 0


def _detect_export(args: argparse.Namespace, export_path: Path) -> int:
    """Introspect a gen~ export directory."""
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


def _resolve_cache_dir() -> tuple[Path, bool]:
    """Return (cache_dir, from_env) for the shared FetchContent cache."""
    import os

    from gen_dsp.core.cache import get_cache_dir

    env_cache = os.environ.get("GEN_DSP_CACHE_DIR")
    if env_cache:
        return Path(env_cache), True
    return get_cache_dir(), False


def _cache_prune(cache_dir: Path, dry_run: bool, assume_yes: bool) -> int:
    """Delete cached SDKs under ``cache_dir`` to reclaim disk space."""
    import shutil

    from gen_dsp.core.cache import dir_size, format_size

    if not cache_dir.is_dir():
        print(f"Nothing to prune; cache directory does not exist: {cache_dir}")
        return 0

    items = sorted(cache_dir.iterdir(), key=lambda p: p.name)
    if not items:
        print(f"Cache is already empty: {cache_dir}")
        return 0

    sized = [(item, dir_size(item)) for item in items]
    total = sum(size for _, size in sized)

    verb = "Would remove" if dry_run else "Removing"
    print(f"{verb} {len(sized)} item(s) from {cache_dir}:")
    for item, size in sized:
        print(f"  {item.name}  {format_size(size)}")
    print(f"Total: {format_size(total)}")

    if dry_run:
        return 0

    if not assume_yes:
        try:
            reply = input(f"Remove these and reclaim {format_size(total)}? [y/N] ")
        except EOFError:
            reply = ""
        if reply.strip().lower() not in ("y", "yes"):
            print("Aborted.")
            return 0

    for item, _ in sized:
        if item.is_dir() and not item.is_symlink():
            shutil.rmtree(item, ignore_errors=True)
        else:
            item.unlink(missing_ok=True)
    print(f"Reclaimed {format_size(total)}.")
    return 0


def cmd_cache(args: argparse.Namespace) -> int:
    """Handle the cache command (show or prune cached SDKs)."""
    from gen_dsp.core.cache import dir_size, format_size
    from gen_dsp.platforms.daisy import LIBDAISY_VERSION, _resolve_libdaisy_dir
    from gen_dsp.platforms.vcvrack import _resolve_rack_dir

    cache_dir, from_env = _resolve_cache_dir()

    if getattr(args, "prune", False):
        return _cache_prune(cache_dir, dry_run=args.dry_run, assume_yes=args.yes)

    suffix = "  (GEN_DSP_CACHE_DIR)" if from_env else ""
    print(f"Cache directory: {cache_dir}{suffix}")
    if cache_dir.is_dir():
        print(f"  Total size: {format_size(dir_size(cache_dir))}")
    print()

    print("FetchContent (clap, lv2, sc, vst3):")
    if cache_dir.is_dir():
        src_dirs = sorted(
            d
            for d in cache_dir.iterdir()
            if d.is_dir()
            and d.name.endswith("-src")
            and d.name not in ("rack-sdk-src", "libdaisy-src", "circle-src")
        )
        if src_dirs:
            for d in src_dirs:
                sdk_name = d.name.removesuffix("-src")
                print(f"  {sdk_name}  {format_size(dir_size(d))}  ({d})")
        else:
            print("  (empty)")
    else:
        print("  (not created)")
    print()

    rack_dir = _resolve_rack_dir()
    rack_present = (rack_dir / "Makefile").is_file()
    print("Rack SDK (vcvrack):")
    print(f"  Path: {rack_dir}")
    if rack_present:
        print(f"  Status: present  ({format_size(dir_size(rack_dir))})")
    else:
        print("  Status: not downloaded")
    print()

    libdaisy_dir = _resolve_libdaisy_dir()
    libdaisy_present = (libdaisy_dir / "core" / "Makefile").is_file()
    libdaisy_built = (libdaisy_dir / "build" / "libdaisy.a").is_file()
    print(f"libDaisy {LIBDAISY_VERSION} (daisy):")
    print(f"  Path: {libdaisy_dir}")
    if libdaisy_built:
        print(f"  Status: built  ({format_size(dir_size(libdaisy_dir))})")
    elif libdaisy_present:
        print(f"  Status: cloned (not built)  ({format_size(dir_size(libdaisy_dir))})")
    else:
        print("  Status: not cloned")

    if cache_dir.is_dir() and any(cache_dir.iterdir()):
        print()
        print("Run 'gen-dsp cache --prune' to reclaim space.")

    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    """Handle the doctor command (per-platform build prerequisite check)."""
    from gen_dsp.core import doctor

    platforms = [args.platform] if args.platform else None
    reports = doctor.diagnose(platforms)

    if args.json:
        print(json.dumps(doctor.report_to_dict(reports), indent=2))
    else:
        print(doctor.format_report(reports))

    # Exit non-zero if any requested platform is not ready, so the command is
    # usable as a CI gate.
    return 0 if all(r.ready for r in reports) else 1


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
        "doctor": cmd_doctor,
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

    if not argv:
        # Bare invocation: run from gen-dsp.toml if present, else show help.
        if (Path.cwd() / "gen-dsp.toml").is_file():
            return _cmd_default([])
        _print_help()
        return 0

    if argv[0] in ("-h", "--help"):
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
