from __future__ import annotations

import pytest

pydantic = pytest.importorskip("pydantic")

from gen_dsp.dsp_graph import (
    AudioInput,
    AudioOutput,
    BinOp,
    Buffer,
    BufRead,
    BufWrite,
    DelayLine,
    DelayRead,
    DelayWrite,
    Graph,
    History,
    OnePole,
    Param,
    SinOsc,
)


@pytest.fixture
def stereo_gain_graph() -> Graph:
    """Stateless stereo gain: in1 * gain -> out1, in2 * gain -> out2."""
    return Graph(
        name="stereo_gain",
        inputs=[AudioInput(id="in1"), AudioInput(id="in2")],
        outputs=[
            AudioOutput(id="out1", source="scaled1"),
            AudioOutput(id="out2", source="scaled2"),
        ],
        params=[Param(name="gain", min=0.0, max=2.0, default=1.0)],
        nodes=[
            BinOp(id="scaled1", op="mul", a="in1", b="gain"),
            BinOp(id="scaled2", op="mul", a="in2", b="gain"),
        ],
    )


@pytest.fixture
def onepole_graph() -> Graph:
    """One-pole lowpass filter with feedback via History."""
    return Graph(
        name="onepole",
        inputs=[AudioInput(id="in1")],
        outputs=[AudioOutput(id="out1", source="result")],
        params=[Param(name="coeff", min=0.0, max=0.999, default=0.5)],
        nodes=[
            BinOp(id="inv_coeff", op="sub", a=1.0, b="coeff"),
            BinOp(id="dry", op="mul", a="in1", b="inv_coeff"),
            History(id="prev", init=0.0, input="result"),
            BinOp(id="wet", op="mul", a="prev", b="coeff"),
            BinOp(id="result", op="add", a="dry", b="wet"),
        ],
    )


@pytest.fixture
def fbdelay_graph() -> Graph:
    """Feedback delay with delay line, feedback, and dry/wet mix."""
    return Graph(
        name="fbdelay",
        inputs=[AudioInput(id="in1")],
        outputs=[AudioOutput(id="out1", source="mix_out")],
        params=[
            Param(name="delay_ms", min=1.0, max=1000.0, default=250.0),
            Param(name="feedback", min=0.0, max=0.95, default=0.5),
            Param(name="mix", min=0.0, max=1.0, default=0.5),
        ],
        nodes=[
            BinOp(id="sr_ms", op="div", a=44100.0, b=1000.0),
            BinOp(id="tap", op="mul", a="delay_ms", b="sr_ms"),
            DelayLine(id="dline", max_samples=48000),
            DelayRead(id="delayed", delay="dline", tap="tap"),
            BinOp(id="fb_scaled", op="mul", a="delayed", b="feedback"),
            BinOp(id="write_val", op="add", a="in1", b="fb_scaled"),
            DelayWrite(id="dwrite", delay="dline", value="write_val"),
            BinOp(id="inv_mix", op="sub", a=1.0, b="mix"),
            BinOp(id="dry", op="mul", a="in1", b="inv_mix"),
            BinOp(id="wet", op="mul", a="delayed", b="mix"),
            BinOp(id="mix_out", op="add", a="dry", b="wet"),
        ],
    )


@pytest.fixture
def gen_dsp_graph() -> Graph:
    """Rich graph for gen-dsp adapter testing.

    2 inputs, 2 outputs, params, buffer, delay, oscillator, filter.
    Exercises the full adapter surface area.
    """
    return Graph(
        name="test_synth",
        inputs=[AudioInput(id="in1"), AudioInput(id="in2")],
        outputs=[
            AudioOutput(id="out1", source="mixed1"),
            AudioOutput(id="out2", source="filtered"),
        ],
        params=[
            Param(name="freq", min=20.0, max=20000.0, default=440.0),
            Param(name="gain", min=0.0, max=1.0, default=0.5),
            Param(name="cutoff", min=0.0, max=0.999, default=0.3),
        ],
        nodes=[
            # Oscillator
            SinOsc(id="osc1", freq="freq"),
            BinOp(id="osc_scaled", op="mul", a="osc1", b="gain"),
            # Mix oscillator with input
            BinOp(id="mixed1", op="add", a="in1", b="osc_scaled"),
            # Filter on second channel
            OnePole(id="lp", a="in2", coeff="cutoff"),
            # Delay line
            DelayLine(id="dly", max_samples=4800),
            DelayWrite(id="dly_wr", delay="dly", value="lp"),
            DelayRead(id="dly_rd", delay="dly", tap=2400.0),
            BinOp(id="filtered", op="add", a="lp", b="dly_rd"),
            # History for feedback
            History(id="prev_out", init=0.0, input="filtered"),
            # Buffer (wavetable)
            Buffer(id="wt", size=1024),
            BufRead(id="wt_rd", buffer="wt", index=0.0),
            BufWrite(id="wt_wr", buffer="wt", index=0.0, value="osc1"),
        ],
    )
