"""FAUST-style block diagram algebra for composing DSP graphs.

Provides four binary combinators -- ``series``, ``parallel``, ``split``,
``merge`` -- that compose :class:`Graph` objects into new :class:`Graph`
objects using :class:`Subgraph` wiring and expansion.

Importing this module monkey-patches ``Graph.__rshift__`` (``>>``) and
``Graph.__floordiv__`` (``//``) for operator-based composition::

    from gen_dsp.graph.algebra import series, parallel, split, merge

    chain = lpf >> hpf          # series
    stack = lpf // hpf          # parallel
"""

from __future__ import annotations

from gen_dsp.graph.models import (
    AudioInput,
    AudioOutput,
    BinOp,
    Graph,
    Node,
    Param,
    Subgraph,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pick_ids(a: Graph, b: Graph) -> tuple[str, str]:
    """Derive subgraph IDs from graph names, disambiguating if equal."""
    a_id = a.name
    b_id = b.name
    if a_id == b_id:
        b_id = b_id + "2"
    return a_id, b_id


def _merge_params(
    a: Graph,
    b: Graph,
    a_id: str,
    b_id: str,
) -> tuple[list[Param], dict[str, str | float], dict[str, str | float]]:
    """Build outer params and per-subgraph param maps.

    Returns:
        (outer_params, a_param_map, b_param_map) where each map is
        ``{inner_name: outer_name}`` suitable for ``Subgraph.params``.
    """
    outer_params: list[Param] = []
    a_map: dict[str, str | float] = {}
    b_map: dict[str, str | float] = {}

    for p in a.params:
        outer_name = f"{a_id}_{p.name}"
        outer_params.append(
            Param(name=outer_name, min=p.min, max=p.max, default=p.default)
        )
        a_map[p.name] = outer_name

    for p in b.params:
        outer_name = f"{b_id}_{p.name}"
        outer_params.append(
            Param(name=outer_name, min=p.min, max=p.max, default=p.default)
        )
        b_map[p.name] = outer_name

    return outer_params, a_map, b_map


# ---------------------------------------------------------------------------
# Combinators
# ---------------------------------------------------------------------------


def series(a: Graph, b: Graph) -> Graph:
    """Pipe *a*'s outputs into *b*'s inputs positionally.

    Requires ``len(a.outputs) == len(b.inputs)``.
    Result: inputs = a.inputs, outputs = b.outputs, params = merged(a+b).
    """
    if len(a.outputs) != len(b.inputs):
        raise ValueError(
            f"series: output count of '{a.name}' ({len(a.outputs)}) "
            f"!= input count of '{b.name}' ({len(b.inputs)})"
        )

    a_id, b_id = _pick_ids(a, b)
    outer_params, a_pmap, b_pmap = _merge_params(a, b, a_id, b_id)

    # a's inputs come from outer inputs (or literal 0.0 for generators)
    a_input_map: dict[str, str | float] = {}
    outer_inputs: list[AudioInput] = []
    for inp in a.inputs:
        outer_inputs.append(AudioInput(id=inp.id))
        a_input_map[inp.id] = inp.id

    # b's inputs come from a's outputs via compound refs
    b_input_map: dict[str, str | float] = {}
    for i, inp in enumerate(b.inputs):
        b_input_map[inp.id] = f"{a_id}__{a.outputs[i].id}"

    # Outer outputs mirror b's outputs via compound refs
    outer_outputs: list[AudioOutput] = []
    for out in b.outputs:
        outer_outputs.append(AudioOutput(id=out.id, source=f"{b_id}__{out.id}"))

    sg_a = Subgraph(id=a_id, graph=a, inputs=a_input_map, params=a_pmap)
    sg_b = Subgraph(id=b_id, graph=b, inputs=b_input_map, params=b_pmap)

    return Graph(
        name=f"{a.name}__{b.name}",
        sample_rate=a.sample_rate,
        inputs=outer_inputs,
        outputs=outer_outputs,
        params=outer_params,
        nodes=[sg_a, sg_b],
    )


def parallel(a: Graph, b: Graph) -> Graph:
    """Stack *a* and *b* side by side with independent I/O.

    No constraints on I/O counts.
    Result: inputs = a_prefixed + b_prefixed, outputs = a_prefixed + b_prefixed.
    """
    a_id, b_id = _pick_ids(a, b)
    outer_params, a_pmap, b_pmap = _merge_params(a, b, a_id, b_id)

    outer_inputs: list[AudioInput] = []
    a_input_map: dict[str, str | float] = {}
    for inp in a.inputs:
        outer_id = f"{a_id}_{inp.id}"
        outer_inputs.append(AudioInput(id=outer_id))
        a_input_map[inp.id] = outer_id

    b_input_map: dict[str, str | float] = {}
    for inp in b.inputs:
        outer_id = f"{b_id}_{inp.id}"
        outer_inputs.append(AudioInput(id=outer_id))
        b_input_map[inp.id] = outer_id

    outer_outputs: list[AudioOutput] = []
    for out in a.outputs:
        outer_outputs.append(
            AudioOutput(id=f"{a_id}_{out.id}", source=f"{a_id}__{out.id}")
        )
    for out in b.outputs:
        outer_outputs.append(
            AudioOutput(id=f"{b_id}_{out.id}", source=f"{b_id}__{out.id}")
        )

    sg_a = Subgraph(id=a_id, graph=a, inputs=a_input_map, params=a_pmap)
    sg_b = Subgraph(id=b_id, graph=b, inputs=b_input_map, params=b_pmap)

    return Graph(
        name=f"{a.name}__{b.name}",
        sample_rate=a.sample_rate,
        inputs=outer_inputs,
        outputs=outer_outputs,
        params=outer_params,
        nodes=[sg_a, sg_b],
    )


def split(a: Graph, b: Graph) -> Graph:
    """Fan-out: *a*'s outputs cyclically distributed to fill *b*'s inputs.

    Requires ``len(b.inputs) % len(a.outputs) == 0``.
    Result: inputs = a.inputs, outputs = b.outputs, params = merged(a+b).
    """
    n_a_out = len(a.outputs)
    n_b_in = len(b.inputs)
    if n_a_out == 0:
        raise ValueError(f"split: '{a.name}' has no outputs")
    if n_b_in % n_a_out != 0:
        raise ValueError(
            f"split: input count of '{b.name}' ({n_b_in}) "
            f"is not a multiple of output count of '{a.name}' ({n_a_out})"
        )

    a_id, b_id = _pick_ids(a, b)
    outer_params, a_pmap, b_pmap = _merge_params(a, b, a_id, b_id)

    a_input_map: dict[str, str | float] = {}
    outer_inputs: list[AudioInput] = []
    for inp in a.inputs:
        outer_inputs.append(AudioInput(id=inp.id))
        a_input_map[inp.id] = inp.id

    # b's inputs cyclically map to a's outputs
    b_input_map: dict[str, str | float] = {}
    for i, inp in enumerate(b.inputs):
        b_input_map[inp.id] = f"{a_id}__{a.outputs[i % n_a_out].id}"

    outer_outputs: list[AudioOutput] = []
    for out in b.outputs:
        outer_outputs.append(AudioOutput(id=out.id, source=f"{b_id}__{out.id}"))

    sg_a = Subgraph(id=a_id, graph=a, inputs=a_input_map, params=a_pmap)
    sg_b = Subgraph(id=b_id, graph=b, inputs=b_input_map, params=b_pmap)

    return Graph(
        name=f"{a.name}__{b.name}",
        sample_rate=a.sample_rate,
        inputs=outer_inputs,
        outputs=outer_outputs,
        params=outer_params,
        nodes=[sg_a, sg_b],
    )


def merge(a: Graph, b: Graph) -> Graph:
    """Fan-in: *a*'s outputs summed in groups to feed *b*'s inputs.

    Requires ``len(a.outputs) % len(b.inputs) == 0``.
    When k=1 (equal counts), degenerates to direct wiring (like series).
    For k>1, BinOp(op="add") chain nodes sum each group.
    """
    n_a_out = len(a.outputs)
    n_b_in = len(b.inputs)
    if n_b_in == 0:
        raise ValueError(f"merge: '{b.name}' has no inputs")
    if n_a_out % n_b_in != 0:
        raise ValueError(
            f"merge: output count of '{a.name}' ({n_a_out}) "
            f"is not a multiple of input count of '{b.name}' ({n_b_in})"
        )

    k = n_a_out // n_b_in
    a_id, b_id = _pick_ids(a, b)
    outer_params, a_pmap, b_pmap = _merge_params(a, b, a_id, b_id)

    a_input_map: dict[str, str | float] = {}
    outer_inputs: list[AudioInput] = []
    for inp in a.inputs:
        outer_inputs.append(AudioInput(id=inp.id))
        a_input_map[inp.id] = inp.id

    sum_nodes: list[BinOp] = []
    b_input_map: dict[str, str | float] = {}

    for j in range(n_b_in):
        group_start = j * k
        if k == 1:
            # Direct wiring, no sum node needed
            b_input_map[b.inputs[j].id] = f"{a_id}__{a.outputs[group_start].id}"
        else:
            # Build add chain: sum_j_0 = out[0] + out[1],
            #                   sum_j_1 = sum_j_0 + out[2], ...
            prev_id = f"{a_id}__{a.outputs[group_start].id}"
            for m in range(1, k):
                sum_id = f"_sum_{j}_{m - 1}"
                cur_ref = f"{a_id}__{a.outputs[group_start + m].id}"
                sum_nodes.append(BinOp(id=sum_id, op="add", a=prev_id, b=cur_ref))
                prev_id = sum_id
            b_input_map[b.inputs[j].id] = prev_id

    outer_outputs: list[AudioOutput] = []
    for out in b.outputs:
        outer_outputs.append(AudioOutput(id=out.id, source=f"{b_id}__{out.id}"))

    sg_a = Subgraph(id=a_id, graph=a, inputs=a_input_map, params=a_pmap)
    sg_b = Subgraph(id=b_id, graph=b, inputs=b_input_map, params=b_pmap)

    nodes: list[Node] = [sg_a]
    nodes.extend(sum_nodes)
    nodes.append(sg_b)

    return Graph(
        name=f"{a.name}__{b.name}",
        sample_rate=a.sample_rate,
        inputs=outer_inputs,
        outputs=outer_outputs,
        params=outer_params,
        nodes=nodes,
    )


# ---------------------------------------------------------------------------
# Operator overloading (active on import)
# ---------------------------------------------------------------------------

Graph.__rshift__ = lambda self, other: series(self, other)  # type: ignore[operator]
Graph.__floordiv__ = lambda self, other: parallel(self, other)  # type: ignore[operator]
