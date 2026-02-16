"""
Graph-based project initialization logic.

Extracted from cli.py to decouple orchestration from argparse. Functions
here accept explicit parameters instead of argparse.Namespace objects.
"""

import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from gen_dsp.core.graph import GraphConfig, ResolvedChainNode
    from gen_dsp.core.project import ProjectConfig


def resolve_export_dirs(
    base_dir: Path,
    graph: "GraphConfig",
    extra_exports: Optional[list[Path]] = None,
) -> dict[str, Path]:
    """Resolve export directories from base path and explicit overrides.

    For gen~ nodes only (mixer nodes have no export).

    Args:
        base_dir: Base directory to search for exports.
        graph: Parsed graph configuration.
        extra_exports: Optional list of explicit export path overrides.

    Returns:
        Dict mapping export names to their resolved directory paths.
    """
    export_dirs: dict[str, Path] = {}

    for _node_id, node_config in graph.nodes.items():
        if node_config.export is None:
            continue  # mixer nodes have no export
        candidate = base_dir / node_config.export / "gen"
        if candidate.is_dir():
            export_dirs[node_config.export] = candidate
        else:
            candidate = base_dir / node_config.export
            if candidate.is_dir():
                export_dirs[node_config.export] = candidate

    if extra_exports:
        for export_path in extra_exports:
            resolved = export_path.resolve()
            export_dirs[resolved.name] = resolved

    return export_dirs


def copy_and_patch_exports(
    nodes: "list[ResolvedChainNode]",
    output_dir: Path,
    apply_patches: bool = True,
) -> None:
    """Copy gen~ exports and apply patches for gen~ nodes.

    Args:
        nodes: List of resolved chain/DAG nodes.
        output_dir: Target directory for copied exports.
        apply_patches: If True, apply platform-specific patches.
    """
    for node in nodes:
        if node.config.node_type != "gen" or node.export_info is None:
            continue
        export_dest = output_dir / f"gen_{node.config.export}"
        if export_dest.exists():
            shutil.rmtree(export_dest)
        shutil.copytree(node.export_info.path, export_dest)

    if apply_patches:
        from gen_dsp.core.patcher import Patcher

        for node in nodes:
            if node.config.node_type != "gen" or node.export_info is None:
                continue
            export_dest = output_dir / f"gen_{node.config.export}"
            patcher = Patcher(export_dest)
            patcher.apply_all()


def init_chain_linear(
    graph: "GraphConfig",
    export_dirs: dict[str, Path],
    output_dir: Path,
    name: str,
    config: "ProjectConfig",
    apply_patches: bool = True,
    dry_run: bool = False,
    board: Optional[str] = None,
) -> int:
    """Generate a linear chain project (Phase 1 path).

    Args:
        graph: Parsed graph configuration.
        export_dirs: Mapping of export names to directories.
        output_dir: Target directory for the generated project.
        name: Project name.
        config: Project configuration.
        apply_patches: If True, apply platform-specific patches.
        dry_run: If True, only print what would be done.
        board: Optional board variant name.

    Returns:
        Exit code (0 for success, 1 for error).
    """
    import sys
    from gen_dsp.core.graph import resolve_chain
    from gen_dsp.platforms.circle import CirclePlatform
    from gen_dsp.platforms.base import Platform
    from gen_dsp.errors import GenExtError

    try:
        chain = resolve_chain(graph, export_dirs, Platform.GENEXT_VERSION)
    except GenExtError as e:
        print(f"Error resolving chain: {e}", file=sys.stderr)
        return 1

    if dry_run:
        print(f"Would create chain project at: {output_dir}")
        print("  Platform: circle (chain mode)")
        if board:
            print(f"  Board: {board}")
        print(f"  Nodes: {len(chain)}")
        for node in chain:
            export_label = node.config.export or "(built-in)"
            print(
                f"    [{node.index}] {node.config.id}: {export_label} "
                f"({node.manifest.num_inputs}in/{node.manifest.num_outputs}out, "
                f"{node.manifest.num_params} params, MIDI ch {node.config.midi_channel})"
            )
        return 0

    try:
        output_dir.mkdir(parents=True, exist_ok=True)

        platform = CirclePlatform()
        platform.generate_chain_project(chain, graph, output_dir, name, config)

        # Copy gen~ exports and apply patches
        copy_and_patch_exports(chain, output_dir, apply_patches)

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


def init_chain_dag(
    graph: "GraphConfig",
    export_dirs: dict[str, Path],
    output_dir: Path,
    name: str,
    config: "ProjectConfig",
    apply_patches: bool = True,
    dry_run: bool = False,
    board: Optional[str] = None,
) -> int:
    """Generate a DAG project (Phase 2 path).

    Args:
        graph: Parsed graph configuration.
        export_dirs: Mapping of export names to directories.
        output_dir: Target directory for the generated project.
        name: Project name.
        config: Project configuration.
        apply_patches: If True, apply platform-specific patches.
        dry_run: If True, only print what would be done.
        board: Optional board variant name.

    Returns:
        Exit code (0 for success, 1 for error).
    """
    import sys
    from gen_dsp.core.graph import resolve_dag, allocate_edge_buffers
    from gen_dsp.platforms.circle import CirclePlatform
    from gen_dsp.platforms.base import Platform
    from gen_dsp.errors import GenExtError

    try:
        dag_nodes = resolve_dag(graph, export_dirs, Platform.GENEXT_VERSION)
    except GenExtError as e:
        print(f"Error resolving DAG: {e}", file=sys.stderr)
        return 1

    resolved_map = {n.config.id: n for n in dag_nodes}
    topo_order = [n.config.id for n in dag_nodes]
    edge_buffers, num_buffers = allocate_edge_buffers(graph, resolved_map, topo_order)

    if dry_run:
        print(f"Would create DAG project at: {output_dir}")
        print("  Platform: circle (DAG mode)")
        if board:
            print(f"  Board: {board}")
        print(f"  Nodes: {len(dag_nodes)}")
        print(f"  Intermediate buffers: {num_buffers}")
        for node in dag_nodes:
            export_label = (
                node.config.export or f"(mixer, {node.config.mixer_inputs} inputs)"
            )
            print(
                f"    [{node.index}] {node.config.id}: {export_label} "
                f"({node.manifest.num_inputs}in/{node.manifest.num_outputs}out, "
                f"{node.manifest.num_params} params, MIDI ch {node.config.midi_channel})"
            )
        return 0

    try:
        output_dir.mkdir(parents=True, exist_ok=True)

        platform = CirclePlatform()
        platform.generate_dag_project(
            dag_nodes, graph, edge_buffers, num_buffers, output_dir, name, config
        )

        # Copy gen~ exports and apply patches (gen~ nodes only)
        copy_and_patch_exports(dag_nodes, output_dir, apply_patches)

        print(f"DAG project created at: {output_dir}")
        print("  Platform: circle (DAG mode)")
        print(f"  Nodes: {len(dag_nodes)}")
        print(f"  Intermediate buffers: {num_buffers}")
        for node in dag_nodes:
            ntype = "mixer" if node.config.node_type == "mixer" else node.config.export
            print(
                f"    [{node.index}] {node.config.id}: {ntype} "
                f"({node.manifest.num_inputs}in/{node.manifest.num_outputs}out)"
            )
        print()
        print("Next steps:")
        print(f"  cd {output_dir}")
        print("  make")
    except GenExtError as e:
        print(f"Error creating DAG project: {e}", file=sys.stderr)
        return 1

    return 0
