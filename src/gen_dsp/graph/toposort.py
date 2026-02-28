"""Topological sort for DSP graphs."""

from __future__ import annotations

from collections import defaultdict

from gen_dsp.graph._deps import build_forward_deps
from gen_dsp.graph.models import Graph, Node


def toposort(graph: Graph) -> list[Node]:
    """Return graph nodes in topological order (Kahn's algorithm).

    Uses alphabetical tie-breaking for deterministic output.
    Raises ValueError if the graph contains a cycle (through non-feedback edges).
    """
    if not graph.nodes:
        return []

    deps = build_forward_deps(graph)
    node_map: dict[str, Node] = {node.id: node for node in graph.nodes}

    # Build in-degree and reverse adjacency
    in_degree: dict[str, int] = {nid: 0 for nid in node_map}
    reverse: dict[str, list[str]] = defaultdict(list)
    for nid, dep_set in deps.items():
        for dep in dep_set:
            if dep in in_degree:
                in_degree[nid] += 1
                reverse[dep].append(nid)

    # Kahn's with sorted queue for determinism
    queue = sorted(nid for nid, deg in in_degree.items() if deg == 0)
    result: list[Node] = []

    while queue:
        current = queue.pop(0)
        result.append(node_map[current])
        for dependent in reverse[current]:
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                # Insert into sorted position
                _insort(queue, dependent)

    if len(result) < len(node_map):
        cycle_nodes = sorted(nid for nid, deg in in_degree.items() if deg > 0)
        raise ValueError(
            f"Graph contains a cycle through nodes: {', '.join(cycle_nodes)}"
        )

    return result


def _insort(lst: list[str], val: str) -> None:
    """Insert val into sorted list lst, maintaining sort order."""
    lo, hi = 0, len(lst)
    while lo < hi:
        mid = (lo + hi) // 2
        if lst[mid] < val:
            lo = mid + 1
        else:
            hi = mid
    lst.insert(lo, val)
