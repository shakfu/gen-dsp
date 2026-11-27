"""Split the sample loop at cignal kernels, so each runs one `K_process` call per chunk.

A kernel called one frame at a time costs about twice its block cost: its state cannot stay in
registers across frames. When nothing feeds a kernel's output back to its input, the loop splits
into stages. Stage s computes the inputs of the stage-s kernels for a whole chunk, the kernels run
on the chunk, and stage s + 1 reads their outputs. cignal's output does not depend on block size,
so the split changes no sample.

Nodes that share state run in one stage, in their original order: the readers and writers of a
delay line or buffer, a GateRoute and its GateOuts, a per-frame kernel and its CignalOuts, and a
History with its input and its readers (a History's value is a state local, which a later stage
cannot read per sample). Feedback through a kernel then forces a stage past the number of
kernels, and that kernel stays per-frame.
"""

from __future__ import annotations

from dataclasses import dataclass

from gen_dsp.graph._deps import build_forward_deps
from gen_dsp.graph.compile.nodes import cignal_param_is_block_constant
from gen_dsp.graph.models import (
    Buffer,
    CignalKernel,
    CignalOut,
    DelayLine,
    GateRoute,
    Graph,
    History,
    Node,
)

CHUNK = 64  # frames per kernel call; a host block of any size runs as chunks of at most this


@dataclass
class Staging:
    block: list[CignalKernel]  # kernels called once per chunk, in topological order
    stage: dict[str, int]  # node ID -> stage, for nodes in the sample loop

    @property
    def last(self) -> int:
        return max([*self.stage.values(), *(self.stage[k.id] + 1 for k in self.block)])


def plan(
    graph: Graph,
    sorted_nodes: list[Node],
    invariant_ids: set[str],
    param_names: set[str],
) -> Staging | None:
    """Kernels to call per chunk and every node's stage, or None to keep one fused loop."""
    candidates = [
        n
        for n in sorted_nodes
        if isinstance(n, CignalKernel)
        and all(
            cignal_param_is_block_constant(r, param_names, invariant_ids)
            for r in n.params
        )
    ]
    if not candidates:
        return None
    best: Staging | None = None
    chosen: list[CignalKernel] = []
    for kernel in candidates:  # greedy: a kernel joins if the split stays valid
        stages = _stages(
            graph, sorted_nodes, invariant_ids, {k.id for k in [*chosen, kernel]}
        )
        if stages is not None:
            chosen.append(kernel)
            best = Staging(list(chosen), stages)
    return best


def _stages(
    graph: Graph,
    sorted_nodes: list[Node],
    invariant_ids: set[str],
    block_ids: set[str],
) -> dict[str, int] | None:
    loop = [n for n in sorted_nodes if n.id not in invariant_ids]
    ids = {n.id for n in loop}
    by_id = {n.id: n for n in loop}
    deps = {
        nid: {d for d in ds if d in ids}
        for nid, ds in build_forward_deps(graph).items()
    }

    parent = {nid: nid for nid in ids}

    def find(a: str) -> str:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a: str, b: str) -> None:
        if a in ids and b in ids:
            parent[find(a)] = find(b)

    for node in loop:
        if isinstance(node, History) and isinstance(node.input, str):
            union(node.id, node.input)
        for value in node.__dict__.values():
            for ref in value if isinstance(value, list) else [value]:
                target = by_id.get(ref) if isinstance(ref, str) else None
                if target is None or target is node:
                    continue
                if isinstance(target, (History, DelayLine, Buffer, GateRoute)) or (
                    isinstance(node, CignalOut) and target.id not in block_ids
                ):
                    union(node.id, target.id)

    groups: dict[str, list[str]] = {}
    for nid in ids:
        groups.setdefault(find(nid), []).append(nid)

    stage = dict.fromkeys(ids, 0)
    limit = len(block_ids)
    changed = True
    while changed:
        changed = False
        for node in loop:
            s = max(
                [stage[node.id]]
                + [stage[d] + (d in block_ids) for d in deps.get(node.id, ())]
            )
            if s != stage[node.id]:
                stage[node.id], changed = s, True
        for members in groups.values():
            top = max(stage[m] for m in members)
            for m in members:
                if stage[m] != top:
                    stage[m], changed = top, True
        if max(stage.values(), default=0) > limit:
            return None  # feedback through a kernel
    return stage
