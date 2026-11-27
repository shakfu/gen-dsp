"""Tests for cignal kernels as graph nodes (``CignalKernel``, ``CignalOut``).

The kernel is ``tests/fixtures/cignal_gigaverb``: 1 input, 2 outputs, 8 parameters.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

pydantic = pytest.importorskip("pydantic")

from gen_dsp.core.project import ProjectConfig, ProjectGenerator
from gen_dsp.errors import ProjectError
from gen_dsp.graph import (
    AudioInput,
    AudioOutput,
    CignalKernel,
    CignalOut,
    CignalSpec,
    Graph,
    Subgraph,
    compile_graph,
    optimize_graph,
    validate_graph,
)
from gen_dsp.graph.compile import compile_graph_to_file
from gen_dsp.graph.dsl import GDSPCompileError, parse
from gen_dsp.graph.serialize import graph_to_gdsp

GIGAVERB_PARAMS = [
    "roomsize",
    "revtime",
    "damping",
    "spread",
    "bandwidth",
    "dry",
    "early",
    "tail",
]


@pytest.fixture
def manifest(fixtures_dir: Path) -> Path:
    return fixtures_dir / "cignal_gigaverb" / "gigaverb.cignal.json"


@pytest.fixture
def spec(manifest: Path) -> CignalSpec:
    return CignalSpec.load(manifest)


def _reverb_source(manifest: Path) -> str:
    # `out right` names rev.out1 before rev exists, as output declarations usually do.
    return f"""
graph verb {{
    in x
    out left = rev
    out right = rev.out1
    param room 1..50 = 20
    rev = import "{manifest}"(in0=x, roomsize=room, damping=0.2 + 0.1)
}}
"""


def _graph(spec: CignalSpec, **kernel: object) -> Graph:
    fields: dict[str, object] = {
        "inputs": ["x"],
        "params": [float(d) for d in spec.defaults],
    }
    fields.update(kernel)
    return Graph(
        name="g",
        inputs=[AudioInput(id="x")],
        outputs=[AudioOutput(id="y", source="rev")],
        nodes=[CignalKernel(id="rev", spec=spec, **fields)],  # type: ignore[arg-type]
    )


class TestSpec:
    def test_load(self, spec: CignalSpec, manifest: Path) -> None:
        assert spec.c_name == "Gigaverb"
        assert (spec.n_inputs, spec.n_outputs) == (1, 2)
        assert spec.params == GIGAVERB_PARAMS
        assert spec.defaults[0] == 10.0
        assert spec.directory == manifest.resolve().parent

    def test_rejects_names_unfit_for_c(self, spec: CignalSpec) -> None:
        data = spec.model_dump()
        with pytest.raises(pydantic.ValidationError):
            CignalSpec(**{**data, "c_name": "x; system()"})
        with pytest.raises(pydantic.ValidationError):
            CignalSpec(**{**data, "header": "../evil.h"})

    def test_json_round_trip(self, spec: CignalSpec) -> None:
        g = _graph(spec)
        assert Graph.model_validate_json(g.model_dump_json()) == g


class TestDsl:
    def test_lowering(self, manifest: Path, spec: CignalSpec) -> None:
        g = parse(_reverb_source(manifest))
        kernels = [n for n in g.nodes if isinstance(n, CignalKernel)]
        outs = [n for n in g.nodes if isinstance(n, CignalOut)]
        assert len(kernels) == 1 and len(outs) == 1
        rev = kernels[0]
        assert rev.inputs == ["x"]
        assert rev.params[0] == "room"
        assert isinstance(rev.params[2], str)  # damping: the `+` node
        assert rev.params[3:] == spec.defaults[3:]  # unbound params keep defaults
        assert outs[0].kernel == "rev" and outs[0].channel == 1
        assert {o.id: o.source for o in g.outputs} == {
            "left": "rev",
            "right": outs[0].id,
        }
        assert validate_graph(g) == []

    def test_one_cignal_out_per_channel(self, manifest: Path) -> None:
        g = parse(f"""
graph g {{
    in x
    out a = rev.out1 + rev.out1
    rev = import "{manifest}"(in0=x)
}}
""")
        assert sum(isinstance(n, CignalOut) for n in g.nodes) == 1

    @pytest.mark.parametrize(
        ("call", "message"),
        [
            ("(in0=x, size=1)", "has no input or param 'size'"),
            ("(roomsize=1)", "unconnected inputs"),
            ("(x)", "keyword arguments only"),
            (":Gigaverb(in0=x)", "drop the ':NAME'"),
        ],
    )
    def test_bad_import(self, manifest: Path, call: str, message: str) -> None:
        with pytest.raises(GDSPCompileError, match=message):
            parse(
                f'graph g {{\n in x\n out y = rev\n rev = import "{manifest}"{call}\n}}'
            )

    @pytest.mark.parametrize("field", ["out2", "left", "out"])
    def test_bad_output(self, manifest: Path, field: str) -> None:
        with pytest.raises(GDSPCompileError, match="has outputs out0..out1"):
            parse(
                f'graph g {{\n in x\n rev = import "{manifest}"(in0=x)\n out y = rev.{field}\n}}'
            )

    def test_missing_manifest(self, tmp_path: Path) -> None:
        with pytest.raises(GDSPCompileError, match="cannot read cignal manifest"):
            parse(
                f'graph g {{\n in x\n out y = k\n k = import "{tmp_path / "k.cignal.json"}"(in0=x)\n}}'
            )

    def test_serialize_round_trip(self, manifest: Path) -> None:
        g = parse(_reverb_source(manifest))
        again = parse(graph_to_gdsp(g))
        assert compile_graph(again) == compile_graph(g)


class TestValidate:
    def test_arity(self, spec: CignalSpec) -> None:
        errors = validate_graph(_graph(spec, inputs=[], params=[1.0]))
        assert sorted(e.field_name for e in errors if e.kind == "cignal_arity") == [
            "inputs",
            "params",
        ]

    def test_cignal_out(self, spec: CignalSpec) -> None:
        g = _graph(spec)
        bad = g.model_copy(
            update={
                "nodes": [
                    *g.nodes,
                    CignalOut(id="o2", kernel="rev", channel=2),
                    CignalOut(id="o3", kernel="x", channel=0),
                ]
            }
        )
        kinds = {e.kind for e in validate_graph(bad)}
        assert {"cignal_channel_range", "missing_cignal_kernel"} <= kinds

    def test_conflict(self, spec: CignalSpec) -> None:
        g = _graph(spec)
        other = spec.model_copy(update={"manifest": "/elsewhere/gigaverb.cignal.json"})
        two = g.model_copy(
            update={
                "nodes": [
                    *g.nodes,
                    CignalKernel(
                        id="rev2", spec=other, inputs=["x"], params=list(spec.defaults)
                    ),
                ]
            }
        )
        assert "cignal_conflict" in {e.kind for e in validate_graph(two)}


class TestOptimize:
    def test_identical_kernels_are_not_merged(self, spec: CignalSpec) -> None:
        g = _graph(spec)
        two = g.model_copy(
            update={
                "nodes": [
                    *g.nodes,
                    CignalKernel(
                        id="rev2", spec=spec, inputs=["x"], params=list(spec.defaults)
                    ),
                ],
                "outputs": [*g.outputs, AudioOutput(id="z", source="rev2")],
            }
        )
        kept = optimize_graph(two).graph
        assert {n.id for n in kept.nodes} == {"rev", "rev2"}

    def test_unused_kernel_is_dead(self, spec: CignalSpec) -> None:
        g = _graph(spec).model_copy(update={"outputs": []})
        assert optimize_graph(g).graph.nodes == []


class TestCompile:
    def test_params_set_once_per_block_when_fixed(self, manifest: Path) -> None:
        code = compile_graph(parse(_reverb_source(manifest)))
        before, loop = code.split("for (int _c0 = 0; _c0 < n; _c0 += 64) {", 1)
        assert "Gigaverb_set_param(&self->m_rev, 0, room);" in before
        assert "Gigaverb_set_param(&self->m_rev, 2, _add_0);" in before
        assert "Gigaverb_set_param(&self->m_rev, 7, 0.25f);" in before
        assert "Gigaverb_set_param" not in loop
        assert "Gigaverb_process(&self->m_rev, _rev_ins, _rev_outs, _cn);" in loop
        assert '#include "gigaverb.h"' in code

    def test_signal_rate_param_is_set_per_sample(self, manifest: Path) -> None:
        code = compile_graph(
            parse(f"""
graph g {{
    in x
    out y = rev
    rev = import "{manifest}"(in0=x, damping=x * 0.5)
}}
""")
        )
        loop = code.split("for (int i = 0; i < n; i++) {", 1)[1]
        assert "Gigaverb_set_param(&self->m_rev, 2, _mul_0);" in loop

    def test_inside_subgraph(self, spec: CignalSpec) -> None:
        inner = _graph(spec)
        outer = Graph(
            name="outer",
            inputs=[AudioInput(id="a")],
            outputs=[AudioOutput(id="b", source="sg")],
            nodes=[Subgraph(id="sg", graph=inner, inputs={"x": "a"})],
        )
        code = compile_graph(outer)
        assert "    Gigaverb m_sg__rev;" in code
        assert (
            "Gigaverb_process(&self->m_sg__rev, _sg__rev_ins, _sg__rev_outs, _cn);"
            in code
        )

    def test_simulate_refuses(self, spec: CignalSpec) -> None:
        pytest.importorskip("numpy")
        from gen_dsp.graph.simulate import simulate

        with pytest.raises(ValueError, match="cannot simulate cignal kernels"):
            simulate(_graph(spec), n_samples=4)


_DRIVER = r"""
#include <stdio.h>
#include <string.h>
#include "verb.h"
#include "gigaverb.h"
#define N 9600
#define B 64
#define CHANGE 4800
static float x[N], l[N], r[N], rl[N], rr[N];
int main(void) {
    unsigned s = 1;
    for (int i = 0; i < N; i++) {
        s = s * 1664525u + 1013904223u;
        x[i] = i < 480 ? (float)(s >> 8) / 16777216.0f * 2.0f - 1.0f : 0.0f;
    }
    VerbState* g = verb_create(48000.0f);
    for (int i0 = 0; i0 < N; i0 += B) {
        if (i0 == CHANGE) verb_set_param(g, 0, 5.0f);
        float* ins[1] = {x + i0};
        float* outs[2] = {l + i0, r + i0};
        verb_perform(g, ins, outs, B);
    }
    Gigaverb k;
    Gigaverb_init(&k, 48000.0f);
    Gigaverb_set_param(&k, 0, 20.0f);
    Gigaverb_set_param(&k, 2, 0.2f + 0.1f);
    {
        const float* in[1] = {x};
        float* out[2] = {rl, rr};
        Gigaverb_process(&k, in, out, CHANGE);
    }
    Gigaverb_set_param(&k, 0, 5.0f);
    {
        const float* in[1] = {x + CHANGE};
        float* out[2] = {rl + CHANGE, rr + CHANGE};
        Gigaverb_process(&k, in, out, N - CHANGE);
    }
    int same = memcmp(l, rl, sizeof l) == 0 && memcmp(r, rr, sizeof r) == 0;
    float energy = 0.0f;
    for (int i = CHANGE; i < N; i++) energy += r[i] * r[i];
    printf("%d %g\n", same, energy);
    verb_destroy(g);
    return 0;
}
"""


@pytest.mark.skipif(shutil.which("cc") is None, reason="needs a C compiler")
def test_matches_kernel_run_alone(manifest: Path, tmp_path: Path) -> None:
    """Chunk calls from 64-frame host blocks give the kernel's own output, bit for bit."""
    compile_graph_to_file(parse(_reverb_source(manifest)), tmp_path, "c")
    (tmp_path / "driver.c").write_text(_DRIVER)
    kdir = manifest.parent
    exe = tmp_path / "driver"
    subprocess.run(
        [
            "cc",
            "-std=c99",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            f"-I{kdir}",
            f"-I{tmp_path}",
            str(tmp_path / "verb.c"),
            str(kdir / "gigaverb.c"),
            str(tmp_path / "driver.c"),
            "-lm",
            "-o",
            str(exe),
        ],
        check=True,
    )
    same, energy = subprocess.run(
        [str(exe)], check=True, capture_output=True, text=True
    ).stdout.split()
    assert same == "1"
    assert float(energy) > 0.0  # the tail reaches the second half


@pytest.mark.skipif(shutil.which("cc") is None, reason="needs a C compiler")
def test_kernel_without_inputs_compiles(fixtures_dir: Path, tmp_path: Path) -> None:
    synth = fixtures_dir / "cignal_synth" / "synth.cignal.json"
    g = parse(f'graph gen {{\n out y = s\n s = import "{synth}"()\n}}')
    assert "(const float* const*)0" in compile_graph(g, "c")
    compile_graph_to_file(g, tmp_path, "c")
    subprocess.run(
        ["cc", "-std=c99", "-Wall", "-Wextra", "-Werror", f"-I{synth.parent}", "-c"]
        + [str(tmp_path / "gen.c"), "-o", str(tmp_path / "gen.o")],
        check=True,
    )


class TestProject:
    def test_clap_project_builds_kernel_as_c(
        self, manifest: Path, tmp_path: Path
    ) -> None:
        g = parse(_reverb_source(manifest))
        out = tmp_path / "proj"
        out.mkdir()
        ProjectGenerator.from_graph(
            g, ProjectConfig(name="verb", platform="clap")
        ).generate(out)
        assert (out / "gigaverb.h").is_file() and (out / "gigaverb.c").is_file()
        assert (
            "target_sources(${PROJECT_NAME} PRIVATE gigaverb.c)"
            in (out / "CMakeLists.txt").read_text()
        )

    def test_unsupported_platform(self, manifest: Path, tmp_path: Path) -> None:
        g = parse(_reverb_source(manifest))
        with pytest.raises(ProjectError, match="not supported on 'pd'"):
            ProjectGenerator.from_graph(
                g, ProjectConfig(name="verb", platform="pd")
            ).generate(tmp_path / "proj")

    def test_stale_manifest(self, manifest: Path, tmp_path: Path) -> None:
        kdir = tmp_path / "k"
        shutil.copytree(manifest.parent, kdir)
        copied = kdir / manifest.name
        g = parse(_reverb_source(copied))
        data = json.loads(copied.read_text())
        data["params"][0]["default"] = 12.0
        copied.write_text(json.dumps(data))
        with pytest.raises(ProjectError, match="changed since the graph was built"):
            ProjectGenerator.from_graph(
                g, ProjectConfig(name="verb", platform="clap")
            ).generate(tmp_path / "proj")
