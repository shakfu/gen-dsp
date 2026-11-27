"""cignal kernels called once per chunk (compile/staging.py) give the per-frame output, bit for bit."""

from __future__ import annotations

pydantic = __import__("pytest").importorskip("pydantic")
import shutil
import subprocess
from pathlib import Path

import pytest

import gen_dsp.graph.compile as compile_mod
from gen_dsp.graph import compile_graph
from gen_dsp.graph.compile import compile_graph_to_file
from gen_dsp.graph.dsl import parse

FIXTURES = Path(__file__).parents[1] / "fixtures"
GIGAVERB = FIXTURES / "cignal_gigaverb" / "gigaverb.cignal.json"
SYNTH = FIXTURES / "cignal_synth" / "synth.cignal.json"

_DRIVER = r"""
#include <stdio.h>
#include "g.h"
#define N 2000
static float x[N], y[8][N];
int main(int argc, char** argv) {
    int block = 0;
    (void)argc;
    sscanf(argv[1], "%d", &block);
    unsigned s = 1;
    for (int i = 0; i < N; i++) {
        s = s * 1664525u + 1013904223u;
        x[i] = i < 300 ? (float)(s >> 8) / 16777216.0f * 2.0f - 1.0f : 0.0f;
    }
    GState* g = g_create(48000.0f);
    int nout = g_num_outputs();
    for (int i0 = 0, m = 0; i0 < N; i0 += m) {
        int end = i0 < 1000 ? 1000 : N;  /* blocks split at the parameter change */
        m = end - i0 < block ? end - i0 : block;
        if (i0 == 1000) g_set_param(g, 0, 7.0f);
        float* ins[1] = {x + i0};
        float* outs[8];
        for (int c = 0; c < nout; c++) outs[c] = y[c] + i0;
        g_perform(g, ins, outs, m);
    }
    for (int c = 0; c < nout; c++)
        for (int i = 0; i < N; i++) printf("%a\n", (double)y[c][i]);
    g_destroy(g);
    return 0;
}
"""

FEEDFORWARD = """
graph g {
    in x
    out wet = rev
    out right = rev.out1 * h
    out dry = pre
    param room 1..50 = 20
    history h = 0.0
    pre = x * 0.5
    post = rev.out1 * 0.9 + h * 0.1
    h <- post
    rev = import "GIGAVERB"(in0=pre, roomsize=room, damping=0.3)
}
"""

CHAIN = """
graph g {
    in x
    out y = b.out1 + a
    param room 1..50 = 20
    delay d 100
    delay_write d (x)
    tap = delay_read d (37)
    a = import "GIGAVERB"(in0=tap + x, roomsize=room)
    b = import "GIGAVERB"(in0=a.out1 * 0.5, roomsize=10)
}
"""

FEEDBACK = """
graph g {
    in x
    out y = rev
    param room 1..50 = 20
    history fb = 0.0
    rev = import "GIGAVERB"(in0=x + fb * 0.3, roomsize=room)
    fb <- rev.out1
}
"""

SIGNAL_PARAM = """
graph g {
    in x
    out y = rev
    param room 1..50 = 20
    rev = import "GIGAVERB"(in0=x, roomsize=room, damping=x * 0.5 + 0.5)
}
"""

GENERATOR = """
graph g {
    in x
    out y = s + x
    param room 1..50 = 20
    s = import "SYNTH"()
}
"""

CASES = {  # source, kernels called per chunk, kernels called per frame
    "feedforward": (FEEDFORWARD, ["rev"], []),
    "chain-with-delay": (CHAIN, ["a", "b"], []),
    "feedback": (FEEDBACK, [], ["rev"]),
    "signal-rate-param": (SIGNAL_PARAM, [], ["rev"]),
    "generator": (GENERATOR, ["s"], []),
}


def _source(text: str) -> str:
    return text.replace("GIGAVERB", str(GIGAVERB)).replace("SYNTH", str(SYNTH))


def _run(source: str, out: Path, block_calls: bool, blocks: list[int]) -> list[str]:
    compile_mod.CIGNAL_BLOCK_CALLS = block_calls
    try:
        compile_graph_to_file(parse(source), out, "c")
    finally:
        compile_mod.CIGNAL_BLOCK_CALLS = True
    (out / "driver.c").write_text(_DRIVER)
    exe = out / "run"
    kernels = [str(GIGAVERB.parent / "gigaverb.c"), str(SYNTH.parent / "synth.c")]
    subprocess.run(
        ["cc", "-std=c99", "-O2", "-Wall", "-Wextra", "-Wshadow", "-Werror"]
        + [f"-I{out}", f"-I{GIGAVERB.parent}", f"-I{SYNTH.parent}"]
        + [str(out / "g.c"), str(out / "driver.c"), *kernels, "-lm", "-o", str(exe)],
        check=True,
    )
    return [
        subprocess.run(
            [str(exe), str(b)], check=True, capture_output=True, text=True
        ).stdout
        for b in blocks
    ]


@pytest.mark.parametrize("case", CASES.keys())
def test_chunk_calls_only_where_valid(case: str) -> None:
    text, chunked, framed = CASES[case]
    code = compile_graph(parse(_source(text)), "c")
    for k in chunked:
        assert f"_process(&self->m_{k}, " in code and f"_{k}_outs, _cn);" in code
    for k in framed:
        assert f"_{k}_outs, 1);" in code
    assert code.count("_process(&self->m_") == len(chunked) + len(framed)


@pytest.mark.skipif(shutil.which("cc") is None, reason="needs a C compiler")
@pytest.mark.parametrize("case", CASES.keys())
def test_chunk_calls_match_frame_calls(case: str, tmp_path: Path) -> None:
    source = _source(CASES[case][0])
    blocks = [1, 48, 64, 100, 2000]
    chunked = _run(source, tmp_path / "chunk", True, blocks)
    framed = _run(source, tmp_path / "frame", False, blocks)
    assert len(set(chunked + framed)) == 1  # every host block size, both modes
    assert any(float.fromhex(v) != 0.0 for v in chunked[0].split())
