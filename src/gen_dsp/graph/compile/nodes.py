"""Per-node compute emission for C++ code generation."""

from __future__ import annotations

import math as _math

from gen_dsp.graph.compile.common import _emit_ref, _float_lit, _Writer
from gen_dsp.graph.models import (
    ADSR,
    SVF,
    Accum,
    Allpass,
    BinOp,
    Biquad,
    Buffer,
    BufRead,
    BufSize,
    BufWrite,
    Change,
    Clamp,
    Compare,
    Constant,
    Counter,
    Cycle,
    DCBlock,
    DelayLine,
    DelayRead,
    DelayWrite,
    Delta,
    Elapsed,
    Fold,
    GateOut,
    GateRoute,
    History,
    Interp,
    Latch,
    Lookup,
    Mix,
    MulAccum,
    NamedConstant,
    Node,
    Noise,
    OnePole,
    Pass,
    Peek,
    Phasor,
    PulseOsc,
    RateDiv,
    SampleHold,
    SampleRate,
    SawOsc,
    Scale,
    Select,
    Selector,
    SinOsc,
    Slide,
    SmoothParam,
    Smoothstep,
    Splat,
    Train,
    TriOsc,
    UnaryOp,
    Wave,
    Wrap,
)

_BINOP_SYMBOLS: dict[str, str] = {
    "add": "+",
    "sub": "-",
    "mul": "*",
    "div": "/",
}


_BINOP_FUNCS: dict[str, str] = {
    "min": "fminf",
    "max": "fmaxf",
    "mod": "fmodf",
    "pow": "powf",
    "atan2": "atan2f",
    "hypot": "hypotf",
}


_UNARYOP_FUNCS: dict[str, str] = {
    "sin": "sinf",
    "cos": "cosf",
    "tanh": "tanhf",
    "exp": "expf",
    "log": "logf",
    "abs": "fabsf",
    "sqrt": "sqrtf",
    "floor": "floorf",
    "ceil": "ceilf",
    "round": "roundf",
    "atan": "atanf",
    "asin": "asinf",
    "acos": "acosf",
    "tan": "tanf",
    "sinh": "sinhf",
    "cosh": "coshf",
    "asinh": "asinhf",
    "acosh": "acoshf",
    "atanh": "atanhf",
    "exp2": "exp2f",
    "log2": "log2f",
    "log10": "log10f",
    "trunc": "truncf",
}


_COMPARE_SYMBOLS: dict[str, str] = {
    "gt": ">",
    "lt": "<",
    "gte": ">=",
    "lte": "<=",
    "eq": "==",
    "neq": "!=",
}


_NAMED_CONSTANT_VALUES: dict[str, float] = {
    "pi": _math.pi,
    "e": _math.e,
    "twopi": 2.0 * _math.pi,
    "halfpi": _math.pi / 2.0,
    "invpi": 1.0 / _math.pi,
    "degtorad": _math.pi / 180.0,
    "radtodeg": 180.0 / _math.pi,
    "sqrt2": _math.sqrt(2.0),
    "sqrt1_2": _math.sqrt(0.5),
    "ln2": _math.log(2.0),
    "ln10": _math.log(10.0),
    "log2e": _math.log2(_math.e),
    "log10e": _math.log10(_math.e),
    "phi": (1.0 + _math.sqrt(5.0)) / 2.0,
}


def _emit_node_compute(
    node: Node,
    input_ids: set[str],
    param_names: set[str],
    w: _Writer,
    history_nodes: list[History],
    delay_write_nodes: list[DelayWrite],
) -> None:
    def ref(r: str | float) -> str:
        return _emit_ref(r, input_ids, param_names)

    if isinstance(node, BinOp):
        if node.op in _BINOP_FUNCS:
            func = _BINOP_FUNCS[node.op]
            w(f"        float {node.id} = {func}({ref(node.a)}, {ref(node.b)});")
        elif node.op == "absdiff":
            w(f"        float {node.id} = fabsf({ref(node.a)} - {ref(node.b)});")
        elif node.op == "step":
            w(
                f"        float {node.id} = ({ref(node.a)} >= {ref(node.b)}) ? 1.0f : 0.0f;"
            )
        elif node.op == "and":
            w(
                f"        float {node.id} = (float)({ref(node.a)} != 0.0f && {ref(node.b)} != 0.0f);"
            )
        elif node.op == "or":
            w(
                f"        float {node.id} = (float)({ref(node.a)} != 0.0f || {ref(node.b)} != 0.0f);"
            )
        elif node.op == "xor":
            w(
                f"        float {node.id} = (float)(({ref(node.a)} != 0.0f) != ({ref(node.b)} != 0.0f));"
            )
        elif node.op == "rsub":
            w(f"        float {node.id} = {ref(node.b)} - {ref(node.a)};")
        elif node.op == "rdiv":
            w(f"        float {node.id} = {ref(node.b)} / {ref(node.a)};")
        elif node.op == "rmod":
            w(f"        float {node.id} = fmodf({ref(node.b)}, {ref(node.a)});")
        elif node.op == "gtp":
            a, b = ref(node.a), ref(node.b)
            w(f"        float {node.id} = ({a} > {b}) ? {a} : 0.0f;")
        elif node.op == "ltp":
            a, b = ref(node.a), ref(node.b)
            w(f"        float {node.id} = ({a} < {b}) ? {a} : 0.0f;")
        elif node.op == "gtep":
            a, b = ref(node.a), ref(node.b)
            w(f"        float {node.id} = ({a} >= {b}) ? {a} : 0.0f;")
        elif node.op == "ltep":
            a, b = ref(node.a), ref(node.b)
            w(f"        float {node.id} = ({a} <= {b}) ? {a} : 0.0f;")
        elif node.op == "eqp":
            a, b = ref(node.a), ref(node.b)
            w(f"        float {node.id} = ({a} == {b}) ? {a} : 0.0f;")
        elif node.op == "neqp":
            a, b = ref(node.a), ref(node.b)
            w(f"        float {node.id} = ({a} != {b}) ? {a} : 0.0f;")
        elif node.op == "fastpow":
            w(f"        float {node.id} = exp2f({ref(node.b)} * log2f({ref(node.a)}));")
        elif node.op == "bitand":
            w(
                f"        float {node.id} = (float)((int32_t)({ref(node.a)}) & (int32_t)({ref(node.b)}));"
            )
        elif node.op == "bitor":
            w(
                f"        float {node.id} = (float)((int32_t)({ref(node.a)}) | (int32_t)({ref(node.b)}));"
            )
        elif node.op == "bitxor":
            w(
                f"        float {node.id} = (float)((int32_t)({ref(node.a)}) ^ (int32_t)({ref(node.b)}));"
            )
        elif node.op == "bitshift":
            nid = node.id
            w(f"        int32_t _{nid}_v = (int32_t)({ref(node.a)});")
            w(f"        int32_t _{nid}_sh = (int32_t)({ref(node.b)});")
            w(
                f"        float {nid} = (float)(_{nid}_sh >= 0 "
                f"? (int32_t)((uint32_t)_{nid}_v << (_{nid}_sh & 31)) "
                f": (_{nid}_v >> ((-_{nid}_sh) & 31)));"
            )
        else:
            sym = _BINOP_SYMBOLS[node.op]
            w(f"        float {node.id} = {ref(node.a)} {sym} {ref(node.b)};")

    elif isinstance(node, UnaryOp):
        if node.op == "neg":
            w(f"        float {node.id} = -{ref(node.a)};")
        elif node.op == "sign":
            a = ref(node.a)
            w(
                f"        float {node.id} = ({a} > 0.0f ? 1.0f : ({a} < 0.0f ? -1.0f : 0.0f));"
            )
        elif node.op == "fract":
            a = ref(node.a)
            w(f"        float {node.id} = {a} - floorf({a});")
        elif node.op == "not":
            w(f"        float {node.id} = (float)({ref(node.a)} == 0.0f);")
        elif node.op == "bool":
            w(f"        float {node.id} = (float)({ref(node.a)} != 0.0f);")
        elif node.op == "mtof":
            a = ref(node.a)
            w(f"        float {node.id} = 440.0f * powf(2.0f, ({a} - 69.0f) / 12.0f);")
        elif node.op == "ftom":
            a = ref(node.a)
            w(
                f"        float {node.id} = 69.0f + 12.0f * log2f(fmaxf({a}, 1e-10f) / 440.0f);"
            )
        elif node.op == "atodb":
            a = ref(node.a)
            w(f"        float {node.id} = 20.0f * log10f(fmaxf({a}, 1e-10f));")
        elif node.op == "dbtoa":
            a = ref(node.a)
            w(f"        float {node.id} = powf(10.0f, {a} / 20.0f);")
        elif node.op == "phasewrap":
            a = ref(node.a)
            w(
                f"        float {node.id} = {a} - 6.28318530f * floorf({a} * 0.15915494f + 0.5f);"
            )
        elif node.op == "degrees":
            w(f"        float {node.id} = {ref(node.a)} * 57.29577951f;")
        elif node.op == "radians":
            w(f"        float {node.id} = {ref(node.a)} * 0.01745329f;")
        elif node.op == "mstosamps":
            w(f"        float {node.id} = {ref(node.a)} * sr / 1000.0f;")
        elif node.op == "sampstoms":
            w(f"        float {node.id} = {ref(node.a)} * 1000.0f / sr;")
        elif node.op == "t60":
            a = ref(node.a)
            w(f"        float {node.id} = expf(-6.9078f / ({a} * sr));")
        elif node.op == "t60time":
            a = ref(node.a)
            w(f"        float {node.id} = -6.9078f / (logf({a}) * sr);")
        elif node.op == "fixdenorm":
            a = ref(node.a)
            w(f"        float {node.id} = (fabsf({a}) < 1e-18f) ? 0.0f : {a};")
        elif node.op == "fixnan":
            a = ref(node.a)
            w(f"        float {node.id} = ({a} != {a}) ? 0.0f : {a};")
        elif node.op == "isdenorm":
            a = ref(node.a)
            w(
                f"        float {node.id} = (fabsf({a}) < 1e-18f && {a} != 0.0f) ? 1.0f : 0.0f;"
            )
        elif node.op == "isnan":
            a = ref(node.a)
            w(f"        float {node.id} = ({a} != {a}) ? 1.0f : 0.0f;")
        elif node.op == "fastsin":
            a = ref(node.a)
            # Bhaskara I approximation: 16x(pi-x) / (5pi^2 - 4x(pi-x))
            # First wrap to [0, pi] via abs(phasewrap)
            w(
                f"        float _{node.id}_x = {a} - 6.28318530f * floorf({a} * 0.15915494f + 0.5f);"
            )
            w(f"        float _{node.id}_sign = (_{node.id}_x < 0.0f) ? -1.0f : 1.0f;")
            w(f"        float _{node.id}_ax = fabsf(_{node.id}_x);")
            w(f"        float _{node.id}_pma = 3.14159265f - _{node.id}_ax;")
            w(
                f"        float {node.id} = _{node.id}_sign * 16.0f * _{node.id}_ax * _{node.id}_pma / (49.3480220f - 4.0f * _{node.id}_ax * _{node.id}_pma);"
            )
        elif node.op == "fastcos":
            a = ref(node.a)
            # fastcos(x) = fastsin(x + pi/2)
            w(f"        float _{node.id}_sh = {a} + 1.57079633f;")
            w(
                f"        float _{node.id}_x = _{node.id}_sh - 6.28318530f * floorf(_{node.id}_sh * 0.15915494f + 0.5f);"
            )
            w(f"        float _{node.id}_sign = (_{node.id}_x < 0.0f) ? -1.0f : 1.0f;")
            w(f"        float _{node.id}_ax = fabsf(_{node.id}_x);")
            w(f"        float _{node.id}_pma = 3.14159265f - _{node.id}_ax;")
            w(
                f"        float {node.id} = _{node.id}_sign * 16.0f * _{node.id}_ax * _{node.id}_pma / (49.3480220f - 4.0f * _{node.id}_ax * _{node.id}_pma);"
            )
        elif node.op == "fasttan":
            a = ref(node.a)
            w(f"        float {node.id} = sinf({a}) / cosf({a});")
        elif node.op == "fastexp":
            a = ref(node.a)
            # Schraudolph's method
            w(f"        union {{ float f; int32_t i; }} _{node.id}_u;")
            w(f"        _{node.id}_u.i = (int32_t)(12102203.0f * {a} + 1065353216.0f);")
            w(f"        float {node.id} = _{node.id}_u.f;")
        elif node.op == "bitnot":
            w(f"        float {node.id} = (float)(~(int32_t)({ref(node.a)}));")
        else:
            func = _UNARYOP_FUNCS[node.op]
            w(f"        float {node.id} = {func}({ref(node.a)});")

    elif isinstance(node, Clamp):
        a, lo, hi = ref(node.a), ref(node.lo), ref(node.hi)
        w(f"        float {node.id} = fminf(fmaxf({a}, {lo}), {hi});")

    elif isinstance(node, Constant):
        w(f"        float {node.id} = {_float_lit(node.value)};")

    elif isinstance(node, History):
        # Value already loaded pre-loop; track for write-back
        history_nodes.append(node)

    elif isinstance(node, DelayLine):
        # State-only node, no per-sample computation
        pass

    elif isinstance(node, DelayRead):
        dl = node.delay
        tap = ref(node.tap)
        if node.interp == "none":
            w(
                f"        int _{node.id}_pos = "
                f"((_{dl}_wr - (int)({tap})) % _{dl}_len + _{dl}_len) % _{dl}_len;"
            )
            w(f"        float {node.id} = _{dl}_buf[_{node.id}_pos];")
        elif node.interp == "nearest":
            w(
                f"        int _{node.id}_pos = "
                f"((_{dl}_wr - (int)floorf({tap} + 0.5f)) % _{dl}_len + _{dl}_len) % _{dl}_len;"
            )
            w(f"        float {node.id} = _{dl}_buf[_{node.id}_pos];")
        elif node.interp == "linear":
            nid = node.id
            _emit_interp_linear(nid, dl, tap, w)
        elif node.interp == "cubic":
            nid = node.id
            _emit_interp_cubic(nid, dl, tap, w)

    elif isinstance(node, DelayWrite):
        delay_write_nodes.append(node)
        val = ref(node.value)
        w(f"        _{node.delay}_buf[_{node.delay}_wr] = {val};")
        w(f"        _{node.delay}_wr = (_{node.delay}_wr + 1) % _{node.delay}_len;")

    elif isinstance(node, Phasor):
        freq = ref(node.freq)
        w(f"        float {node.id} = _{node.id}_phase;")
        w(f"        _{node.id}_phase += {freq} / sr;")
        w(f"        if (_{node.id}_phase >= 1.0f) _{node.id}_phase -= 1.0f;")

    elif isinstance(node, Train):
        nid = node.id
        freq = ref(node.freq)
        w(f"        _{nid}_phase += {freq} / sr;")
        w(f"        float {nid} = _{nid}_phase >= 1.0f ? 1.0f : 0.0f;")
        w(f"        if (_{nid}_phase >= 1.0f) _{nid}_phase -= 1.0f;")

    elif isinstance(node, Noise):
        w(f"        _{node.id}_seed = _{node.id}_seed * 1664525u + 1013904223u;")
        w(f"        float {node.id} = (float)(int32_t)_{node.id}_seed / 2147483648.0f;")

    elif isinstance(node, Compare):
        sym = _COMPARE_SYMBOLS[node.op]
        w(f"        float {node.id} = (float)({ref(node.a)} {sym} {ref(node.b)});")

    elif isinstance(node, Select):
        w(
            f"        float {node.id} = {ref(node.cond)} > 0.0f ? {ref(node.a)} : {ref(node.b)};"
        )

    elif isinstance(node, Wrap):
        nid = node.id
        a, lo, hi = ref(node.a), ref(node.lo), ref(node.hi)
        w(f"        float _{nid}_range = {hi} - {lo};")
        w(f"        float _{nid}_raw = fmodf({a} - {lo}, _{nid}_range);")
        raw_expr = f"_{nid}_raw < 0.0f ? _{nid}_raw + _{nid}_range : _{nid}_raw"
        w(f"        float {nid} = {lo} + ({raw_expr});")

    elif isinstance(node, Fold):
        nid = node.id
        a, lo, hi = ref(node.a), ref(node.lo), ref(node.hi)
        w(f"        float _{nid}_range = {hi} - {lo};")
        w(f"        float _{nid}_t = fmodf({a} - {lo}, 2.0f * _{nid}_range);")
        w(f"        if (_{nid}_t < 0.0f) _{nid}_t += 2.0f * _{nid}_range;")
        lo_branch = f"{lo} + _{nid}_t"
        hi_branch = f"{hi} - (_{nid}_t - _{nid}_range)"
        w(
            f"        float {nid} = _{nid}_t <= _{nid}_range ? {lo_branch} : {hi_branch};"
        )

    elif isinstance(node, Mix):
        a_r, b_r, t_r = ref(node.a), ref(node.b), ref(node.t)
        w(f"        float {node.id} = {a_r} + ({b_r} - {a_r}) * {t_r};")

    elif isinstance(node, Interp):
        nid = node.id
        a_r, b_r, t_r = ref(node.a), ref(node.b), ref(node.t)
        if node.mode == "linear":
            w(f"        float {nid} = {a_r} + ({b_r} - {a_r}) * {t_r};")
        else:  # cosine
            w(f"        float _{nid}_f = (1.0f - cosf(3.14159265f * {t_r})) * 0.5f;")
            w(f"        float {nid} = {a_r} + ({b_r} - {a_r}) * _{nid}_f;")

    elif isinstance(node, Delta):
        nid = node.id
        a = ref(node.a)
        w(f"        float _{nid}_cur = {a};")
        w(f"        float {nid} = _{nid}_cur - _{nid}_prev;")
        w(f"        _{nid}_prev = _{nid}_cur;")

    elif isinstance(node, Change):
        nid = node.id
        a = ref(node.a)
        w(f"        float _{nid}_cur = {a};")
        w(f"        float {nid} = (_{nid}_cur != _{nid}_prev) ? 1.0f : 0.0f;")
        w(f"        _{nid}_prev = _{nid}_cur;")

    elif isinstance(node, Biquad):
        nid = node.id
        a = ref(node.a)
        b0 = ref(node.b0)
        b1 = ref(node.b1)
        b2 = ref(node.b2)
        a1 = ref(node.a1)
        a2 = ref(node.a2)
        w(f"        float _{nid}_in = {a};")
        w(f"        float {nid} = {b0} * _{nid}_in + _{nid}_s1;")
        w(f"        _{nid}_s1 = {b1} * _{nid}_in - {a1} * {nid} + _{nid}_s2;")
        w(f"        _{nid}_s2 = {b2} * _{nid}_in - {a2} * {nid};")

    elif isinstance(node, SVF):
        nid = node.id
        a = ref(node.a)
        freq = ref(node.freq)
        q = ref(node.q)
        # The prewarp tangent diverges at Nyquist, so a cutoff at or above
        # sr/2 (easy to hit at low sample rates) would blow the filter up.
        w(f"        float _{nid}_fc = fminf(fmaxf({freq}, 0.0f), 0.49f * sr);")
        w(f"        float _{nid}_g = tanf(3.14159265f * _{nid}_fc / sr);")
        w(f"        float _{nid}_k = 1.0f / {q};")
        w(
            f"        float _{nid}_a1 = 1.0f / (1.0f + _{nid}_g * (_{nid}_g + _{nid}_k));"
        )
        w(f"        float _{nid}_a2 = _{nid}_g * _{nid}_a1;")
        w(f"        float _{nid}_a3 = _{nid}_g * _{nid}_a2;")
        w(f"        float _{nid}_v3 = {a} - _{nid}_s2;")
        w(f"        float _{nid}_v1 = _{nid}_a1 * _{nid}_s1 + _{nid}_a2 * _{nid}_v3;")
        w(
            f"        float _{nid}_v2 = _{nid}_s2 + _{nid}_a2 * _{nid}_s1 + _{nid}_a3 * _{nid}_v3;"
        )
        w(f"        _{nid}_s1 = 2.0f * _{nid}_v1 - _{nid}_s1;")
        w(f"        _{nid}_s2 = 2.0f * _{nid}_v2 - _{nid}_s2;")
        if node.mode == "lp":
            w(f"        float {nid} = _{nid}_v2;")
        elif node.mode == "hp":
            w(f"        float {nid} = {a} - _{nid}_k * _{nid}_v1 - _{nid}_v2;")
        elif node.mode == "bp":
            w(f"        float {nid} = _{nid}_v1;")
        elif node.mode == "notch":
            w(f"        float {nid} = {a} - _{nid}_k * _{nid}_v1;")

    elif isinstance(node, OnePole):
        nid = node.id
        a = ref(node.a)
        c = ref(node.coeff)
        w(f"        float {nid} = {c} * {a} + (1.0f - {c}) * _{nid}_prev;")
        w(f"        _{nid}_prev = {nid};")

    elif isinstance(node, DCBlock):
        nid = node.id
        a = ref(node.a)
        w(f"        float _{nid}_x = {a};")
        w(f"        float {nid} = _{nid}_x - _{nid}_xprev + 0.995f * _{nid}_yprev;")
        w(f"        _{nid}_xprev = _{nid}_x;")
        w(f"        _{nid}_yprev = {nid};")

    elif isinstance(node, Allpass):
        nid = node.id
        a = ref(node.a)
        c = ref(node.coeff)
        w(f"        float _{nid}_x = {a};")
        w(f"        float {nid} = {c} * (_{nid}_x - _{nid}_yprev) + _{nid}_xprev;")
        w(f"        _{nid}_xprev = _{nid}_x;")
        w(f"        _{nid}_yprev = {nid};")

    elif isinstance(node, SinOsc):
        nid = node.id
        freq = ref(node.freq)
        w(f"        float {nid} = sinf(6.28318530f * _{nid}_phase);")
        w(f"        _{nid}_phase += {freq} / sr;")
        w(f"        if (_{nid}_phase >= 1.0f) _{nid}_phase -= 1.0f;")

    elif isinstance(node, TriOsc):
        nid = node.id
        freq = ref(node.freq)
        w(f"        float {nid} = 4.0f * fabsf(_{nid}_phase - 0.5f) - 1.0f;")
        w(f"        _{nid}_phase += {freq} / sr;")
        w(f"        if (_{nid}_phase >= 1.0f) _{nid}_phase -= 1.0f;")

    elif isinstance(node, SawOsc):
        nid = node.id
        freq = ref(node.freq)
        w(f"        float {nid} = 2.0f * _{nid}_phase - 1.0f;")
        w(f"        _{nid}_phase += {freq} / sr;")
        w(f"        if (_{nid}_phase >= 1.0f) _{nid}_phase -= 1.0f;")

    elif isinstance(node, PulseOsc):
        nid = node.id
        freq = ref(node.freq)
        width = ref(node.width)
        w(f"        float {nid} = _{nid}_phase < {width} ? 1.0f : -1.0f;")
        w(f"        _{nid}_phase += {freq} / sr;")
        w(f"        if (_{nid}_phase >= 1.0f) _{nid}_phase -= 1.0f;")

    elif isinstance(node, SampleHold):
        nid = node.id
        a = ref(node.a)
        t = ref(node.trig)
        w(f"        float _{nid}_t = {t};")
        w(
            f"        if ((_{nid}_ptrig <= 0.0f && _{nid}_t > 0.0f) ||"
            f" (_{nid}_ptrig > 0.0f && _{nid}_t <= 0.0f))"
        )
        w(f"            _{nid}_held = {a};")
        w(f"        _{nid}_ptrig = _{nid}_t;")
        w(f"        float {nid} = _{nid}_held;")

    elif isinstance(node, Latch):
        nid = node.id
        a = ref(node.a)
        t = ref(node.trig)
        w(f"        float _{nid}_t = {t};")
        w(f"        if (_{nid}_ptrig <= 0.0f && _{nid}_t > 0.0f)")
        w(f"            _{nid}_held = {a};")
        w(f"        _{nid}_ptrig = _{nid}_t;")
        w(f"        float {nid} = _{nid}_held;")

    elif isinstance(node, Accum):
        nid = node.id
        incr = ref(node.incr)
        reset = ref(node.reset)
        w(f"        if ({reset} > 0.0f) _{nid}_sum = 0.0f;")
        w(f"        _{nid}_sum += {incr};")
        w(f"        float {nid} = _{nid}_sum;")

    elif isinstance(node, Counter):
        nid = node.id
        t = ref(node.trig)
        mx = ref(node.max)
        w(f"        float _{nid}_t = {t};")
        w(f"        if (_{nid}_ptrig <= 0.0f && _{nid}_t > 0.0f) {{")
        w(f"            _{nid}_count++;")
        w(f"            if (_{nid}_count >= (int){mx}) _{nid}_count = 0;")
        w("        }")
        w(f"        _{nid}_ptrig = _{nid}_t;")
        w(f"        float {nid} = (float)_{nid}_count;")

    elif isinstance(node, Elapsed):
        nid = node.id
        w(f"        float {nid} = (float)_{nid}_count;")
        w(f"        _{nid}_count++;")

    elif isinstance(node, MulAccum):
        nid = node.id
        incr = ref(node.incr)
        reset = ref(node.reset)
        w(f"        if ({reset} > 0.0f) _{nid}_prod = 1.0f;")
        w(f"        _{nid}_prod *= {incr};")
        w(f"        float {nid} = _{nid}_prod;")

    elif isinstance(node, Buffer):
        # State-only node, no per-sample computation
        pass

    elif isinstance(node, BufRead):
        nid = node.id
        buf = node.buffer
        idx = ref(node.index)
        if node.interp == "none":
            w(f"        int _{nid}_idx = (int)({idx});")
            w(f"        if (_{nid}_idx < 0) _{nid}_idx = 0;")
            w(f"        if (_{nid}_idx >= _{buf}_len) _{nid}_idx = _{buf}_len - 1;")
            w(f"        float {nid} = _{buf}_buf[_{nid}_idx];")
        elif node.interp == "nearest":
            w(f"        int _{nid}_idx = (int)floorf({idx} + 0.5f);")
            w(f"        if (_{nid}_idx < 0) _{nid}_idx = 0;")
            w(f"        if (_{nid}_idx >= _{buf}_len) _{nid}_idx = _{buf}_len - 1;")
            w(f"        float {nid} = _{buf}_buf[_{nid}_idx];")
        elif node.interp == "linear":
            _emit_buf_interp_linear(nid, buf, idx, w)
        elif node.interp == "cubic":
            _emit_buf_interp_cubic(nid, buf, idx, w)

    elif isinstance(node, BufWrite):
        nid = node.id
        buf = node.buffer
        idx = ref(node.index)
        val = ref(node.value)
        w(f"        int _{nid}_idx = (int)({idx});")
        w(f"        if (_{nid}_idx >= 0 && _{nid}_idx < _{buf}_len)")
        w(f"            _{buf}_buf[_{nid}_idx] = {val};")

    elif isinstance(node, Splat):
        nid = node.id
        buf = node.buffer
        idx = ref(node.index)
        val = ref(node.value)
        w(f"        int _{nid}_idx = (int)({idx});")
        w(f"        if (_{nid}_idx >= 0 && _{nid}_idx < _{buf}_len)")
        w(f"            _{buf}_buf[_{nid}_idx] += {val};")

    elif isinstance(node, BufSize):
        w(f"        float {node.id} = (float)self->m_{node.buffer}_len;")

    elif isinstance(node, Cycle):
        nid = node.id
        buf = node.buffer
        phase = ref(node.phase)
        # phase [0,1) wraps, linear interpolation
        w(f"        float _{nid}_p = {phase} - floorf({phase});")
        w(f"        float _{nid}_fidx = _{nid}_p * (float)_{buf}_len;")
        w(f"        int _{nid}_i0 = (int)_{nid}_fidx;")
        w(f"        float _{nid}_frac = _{nid}_fidx - (float)_{nid}_i0;")
        w(f"        int _{nid}_i1 = (_{nid}_i0 + 1) % _{buf}_len;")
        w(f"        _{nid}_i0 = _{nid}_i0 % _{buf}_len;")
        w(
            f"        float {nid} = _{buf}_buf[_{nid}_i0] + _{nid}_frac * (_{buf}_buf[_{nid}_i1] - _{buf}_buf[_{nid}_i0]);"
        )

    elif isinstance(node, Wave):
        nid = node.id
        buf = node.buffer
        phase = ref(node.phase)
        # phase [-1,1] maps to [0, len), clamped
        w(f"        float _{nid}_norm = ({phase} + 1.0f) * 0.5f;")
        w(f"        float _{nid}_fidx = _{nid}_norm * (float)(_{buf}_len - 1);")
        w(f"        if (_{nid}_fidx < 0.0f) _{nid}_fidx = 0.0f;")
        w(
            f"        if (_{nid}_fidx > (float)(_{buf}_len - 1)) _{nid}_fidx = (float)(_{buf}_len - 1);"
        )
        w(f"        int _{nid}_i0 = (int)_{nid}_fidx;")
        w(f"        float _{nid}_frac = _{nid}_fidx - (float)_{nid}_i0;")
        w(f"        int _{nid}_i1 = _{nid}_i0 + 1;")
        w(f"        if (_{nid}_i1 >= _{buf}_len) _{nid}_i1 = _{buf}_len - 1;")
        w(
            f"        float {nid} = _{buf}_buf[_{nid}_i0] + _{nid}_frac * (_{buf}_buf[_{nid}_i1] - _{buf}_buf[_{nid}_i0]);"
        )

    elif isinstance(node, Lookup):
        nid = node.id
        buf = node.buffer
        idx = ref(node.index)
        # index [0,1] clamped, linear interpolation
        w(f"        float _{nid}_ci = {idx};")
        w(f"        if (_{nid}_ci < 0.0f) _{nid}_ci = 0.0f;")
        w(f"        if (_{nid}_ci > 1.0f) _{nid}_ci = 1.0f;")
        w(f"        float _{nid}_fidx = _{nid}_ci * (float)(_{buf}_len - 1);")
        w(f"        int _{nid}_i0 = (int)_{nid}_fidx;")
        w(f"        float _{nid}_frac = _{nid}_fidx - (float)_{nid}_i0;")
        w(f"        int _{nid}_i1 = _{nid}_i0 + 1;")
        w(f"        if (_{nid}_i1 >= _{buf}_len) _{nid}_i1 = _{buf}_len - 1;")
        w(
            f"        float {nid} = _{buf}_buf[_{nid}_i0] + _{nid}_frac * (_{buf}_buf[_{nid}_i1] - _{buf}_buf[_{nid}_i0]);"
        )

    elif isinstance(node, RateDiv):
        nid = node.id
        a = ref(node.a)
        divisor = ref(node.divisor)
        w(f"        if (_{nid}_count == 0) _{nid}_held = {a};")
        w(f"        _{nid}_count++;")
        w(f"        if (_{nid}_count >= (int){divisor}) _{nid}_count = 0;")
        w(f"        float {nid} = _{nid}_held;")

    elif isinstance(node, Scale):
        nid = node.id
        a = ref(node.a)
        in_lo = ref(node.in_lo)
        in_hi = ref(node.in_hi)
        out_lo = ref(node.out_lo)
        out_hi = ref(node.out_hi)
        w(f"        float _{nid}_inrange = {in_hi} - {in_lo};")
        w(f"        float _{nid}_outrange = {out_hi} - {out_lo};")
        w(
            f"        float {nid} = {out_lo} + ({a} - {in_lo}) / _{nid}_inrange * _{nid}_outrange;"
        )

    elif isinstance(node, SmoothParam):
        nid = node.id
        a = ref(node.a)
        c = ref(node.coeff)
        w(f"        float {nid} = (1.0f - {c}) * {a} + {c} * _{nid}_prev;")
        w(f"        _{nid}_prev = {nid};")

    elif isinstance(node, Slide):
        nid = node.id
        a = ref(node.a)
        up = ref(node.up)
        down = ref(node.down)
        w(f"        float _{nid}_x = {a};")
        w(f"        float _{nid}_s = (_{nid}_x > _{nid}_prev) ? {up} : {down};")
        w(
            f"        float {nid} = _{nid}_prev + (_{nid}_x - _{nid}_prev) / ((_{nid}_s > 1.0f) ? _{nid}_s : 1.0f);"
        )
        w(f"        _{nid}_prev = {nid};")

    elif isinstance(node, ADSR):
        nid = node.id
        gate = ref(node.gate)
        attack = ref(node.attack)
        decay = ref(node.decay)
        sustain = ref(node.sustain)
        release = ref(node.release)
        w(f"        {{ // ADSR {nid}")
        w(f"            float _{nid}_gate = {gate};")
        w(f"            float _{nid}_sus = {sustain};")
        # Edge detection: gate on
        w(
            f"            if (_{nid}_gate > 0.0f && _{nid}_ptrig <= 0.0f) _{nid}_phase = 1;"
        )
        # Edge detection: gate off
        w(
            f"            if (_{nid}_gate <= 0.0f && _{nid}_ptrig > 0.0f) _{nid}_phase = 4;"
        )
        w(f"            _{nid}_ptrig = _{nid}_gate;")
        # Attack phase
        w(f"            if (_{nid}_phase == 1) {{")
        w(f"                float _{nid}_ams = {attack};")
        w(
            f"                float _{nid}_asamps = fmaxf(_{nid}_ams * sr * 0.001f, 1.0f);"
        )
        w(f"                _{nid}_output += 1.0f / _{nid}_asamps;")
        w(
            f"                if (_{nid}_output >= 1.0f) {{ _{nid}_output = 1.0f; _{nid}_phase = 2; }}"
        )
        w("            }")
        # Decay phase
        w(f"            if (_{nid}_phase == 2) {{")
        w(f"                float _{nid}_dms = {decay};")
        w(
            f"                float _{nid}_dsamps = fmaxf(_{nid}_dms * sr * 0.001f, 1.0f);"
        )
        w(f"                _{nid}_output -= (1.0f - _{nid}_sus) / _{nid}_dsamps;")
        w(
            f"                if (_{nid}_output <= _{nid}_sus) {{ _{nid}_output = _{nid}_sus; _{nid}_phase = 3; }}"
        )
        w("            }")
        # Sustain phase
        w(f"            if (_{nid}_phase == 3) _{nid}_output = _{nid}_sus;")
        # Release phase
        w(f"            if (_{nid}_phase == 4) {{")
        w(f"                float _{nid}_rms = {release};")
        w(
            f"                float _{nid}_rsamps = fmaxf(_{nid}_rms * sr * 0.001f, 1.0f);"
        )
        w(f"                _{nid}_output -= 1.0f / _{nid}_rsamps;")
        w(
            f"                if (_{nid}_output <= 0.0f) {{ _{nid}_output = 0.0f; _{nid}_phase = 0; }}"
        )
        w("            }")
        w("        }")
        w(f"        float {nid} = _{nid}_output;")

    elif isinstance(node, Peek):
        nid = node.id
        a = ref(node.a)
        w(f"        float {nid} = {a};")
        w(f"        _{nid}_value = {nid};")

    elif isinstance(node, Pass):
        w(f"        float {node.id} = {ref(node.a)};")

    elif isinstance(node, NamedConstant):
        w(f"        float {node.id} = {_float_lit(_NAMED_CONSTANT_VALUES[node.op])};")

    elif isinstance(node, SampleRate):
        # `sr` is already declared at perform-function scope (from self->sr),
        # so only emit an alias when the node uses a different id.
        if node.id != "sr":
            w(f"        float {node.id} = sr;")

    elif isinstance(node, Smoothstep):
        nid = node.id
        a = ref(node.a)
        e0 = ref(node.edge0)
        e1 = ref(node.edge1)
        w(
            f"        float _{nid}_t = fminf(fmaxf(({a} - {e0}) / ({e1} - {e0}), 0.0f), 1.0f);"
        )
        w(f"        float {nid} = _{nid}_t * _{nid}_t * (3.0f - 2.0f * _{nid}_t);")

    elif isinstance(node, GateRoute):
        nid = node.id
        idx = ref(node.index)
        a = ref(node.a)
        w(f"        int _{nid}_idx = (int)({idx});")
        w(f"        if (_{nid}_idx < 0) _{nid}_idx = 0;")
        w(f"        if (_{nid}_idx > {node.count}) _{nid}_idx = {node.count};")
        w(f"        float _{nid}_val = {a};")

    elif isinstance(node, GateOut):
        nid = node.id
        gate = node.gate
        w(
            f"        float {nid} = (_{gate}_idx == {node.channel}) ? _{gate}_val : 0.0f;"
        )

    elif isinstance(node, Selector):
        nid = node.id
        idx = ref(node.index)
        n = len(node.inputs)
        w(f"        int _{nid}_idx = (int)({idx});")
        w(f"        if (_{nid}_idx < 0) _{nid}_idx = 0;")
        w(f"        if (_{nid}_idx > {n}) _{nid}_idx = {n};")
        # Build cascading ternary
        expr = "0.0f"
        for i in range(n, 0, -1):
            input_ref = ref(node.inputs[i - 1])
            expr = f"_{nid}_idx == {i} ? {input_ref} : {expr}"
        w(f"        float {nid} = {expr};")


# ---------------------------------------------------------------------------
# Interpolation helpers
# ---------------------------------------------------------------------------


def _wrap_idx(expr: str, dl: str) -> str:
    """Wrap a delay index expression with positive modulo."""
    return f"(({expr}) % _{dl}_len + _{dl}_len) % _{dl}_len"


def _emit_interp_linear(nid: str, dl: str, tap: str, w: _Writer) -> None:
    w(f"        float _{nid}_ftap = {tap};")
    w(f"        int _{nid}_itap = (int)_{nid}_ftap;")
    w(f"        float _{nid}_frac = _{nid}_ftap - (float)_{nid}_itap;")
    i0 = _wrap_idx(f"_{dl}_wr - _{nid}_itap", dl)
    i1 = _wrap_idx(f"_{dl}_wr - _{nid}_itap - 1", dl)
    w(f"        int _{nid}_i0 = {i0};")
    w(f"        int _{nid}_i1 = {i1};")
    s0 = f"_{dl}_buf[_{nid}_i0]"
    s1 = f"_{dl}_buf[_{nid}_i1]"
    w(f"        float {nid} = {s0} + _{nid}_frac * ({s1} - {s0});")


def _emit_interp_cubic(nid: str, dl: str, tap: str, w: _Writer) -> None:
    w(f"        float _{nid}_ftap = {tap};")
    w(f"        int _{nid}_itap = (int)_{nid}_ftap;")
    w(f"        float _{nid}_frac = _{nid}_ftap - (float)_{nid}_itap;")
    i0 = _wrap_idx(f"_{dl}_wr - _{nid}_itap", dl)
    w(f"        int _{nid}_i0 = {i0};")
    w(f"        int _{nid}_im1 = (_{nid}_i0 + 1) % _{dl}_len;")
    i1 = _wrap_idx(f"_{dl}_wr - _{nid}_itap - 1", dl)
    i2 = _wrap_idx(f"_{dl}_wr - _{nid}_itap - 2", dl)
    w(f"        int _{nid}_i1 = {i1};")
    w(f"        int _{nid}_i2 = {i2};")
    w(f"        float _{nid}_ym1 = _{dl}_buf[_{nid}_im1];")
    w(f"        float _{nid}_y0 = _{dl}_buf[_{nid}_i0];")
    w(f"        float _{nid}_y1 = _{dl}_buf[_{nid}_i1];")
    w(f"        float _{nid}_y2 = _{dl}_buf[_{nid}_i2];")
    w(f"        float _{nid}_c0 = _{nid}_y0;")
    w(f"        float _{nid}_c1 = 0.5f * (_{nid}_y1 - _{nid}_ym1);")
    c2a = f"_{nid}_ym1 - 2.5f * _{nid}_y0"
    c2b = f"2.0f * _{nid}_y1 - 0.5f * _{nid}_y2"
    w(f"        float _{nid}_c2 = {c2a} + {c2b};")
    c3a = f"0.5f * (_{nid}_y2 - _{nid}_ym1)"
    c3b = f"1.5f * (_{nid}_y0 - _{nid}_y1)"
    w(f"        float _{nid}_c3 = {c3a} + {c3b};")
    horner = f"((_{nid}_c3 * _{nid}_frac + _{nid}_c2) * _{nid}_frac + _{nid}_c1) * _{nid}_frac + _{nid}_c0"
    w(f"        float {nid} = {horner};")


# ---------------------------------------------------------------------------
# Buffer interpolation helpers
# ---------------------------------------------------------------------------


def _clamp_buf_idx(nid: str, suffix: str, buf: str, w: _Writer) -> None:
    """Emit clamping for a buffer index variable to [0, buf_len-1]."""
    var = f"_{nid}_{suffix}"
    w(f"        if ({var} < 0) {var} = 0;")
    w(f"        if ({var} >= _{buf}_len) {var} = _{buf}_len - 1;")


def _emit_buf_interp_linear(nid: str, buf: str, idx: str, w: _Writer) -> None:
    w(f"        float _{nid}_fidx = {idx};")
    w(f"        int _{nid}_i0 = (int)_{nid}_fidx;")
    w(f"        float _{nid}_frac = _{nid}_fidx - (float)_{nid}_i0;")
    w(f"        int _{nid}_i1 = _{nid}_i0 + 1;")
    _clamp_buf_idx(nid, "i0", buf, w)
    _clamp_buf_idx(nid, "i1", buf, w)
    w(f"        float _{nid}_s0 = _{buf}_buf[_{nid}_i0];")
    w(f"        float _{nid}_s1 = _{buf}_buf[_{nid}_i1];")
    w(f"        float {nid} = _{nid}_s0 + _{nid}_frac * (_{nid}_s1 - _{nid}_s0);")


def _emit_buf_interp_cubic(nid: str, buf: str, idx: str, w: _Writer) -> None:
    w(f"        float _{nid}_fidx = {idx};")
    w(f"        int _{nid}_i0 = (int)_{nid}_fidx;")
    w(f"        float _{nid}_frac = _{nid}_fidx - (float)_{nid}_i0;")
    w(f"        int _{nid}_im1 = _{nid}_i0 - 1;")
    w(f"        int _{nid}_i1 = _{nid}_i0 + 1;")
    w(f"        int _{nid}_i2 = _{nid}_i0 + 2;")
    _clamp_buf_idx(nid, "im1", buf, w)
    _clamp_buf_idx(nid, "i0", buf, w)
    _clamp_buf_idx(nid, "i1", buf, w)
    _clamp_buf_idx(nid, "i2", buf, w)
    w(f"        float _{nid}_ym1 = _{buf}_buf[_{nid}_im1];")
    w(f"        float _{nid}_y0 = _{buf}_buf[_{nid}_i0];")
    w(f"        float _{nid}_y1 = _{buf}_buf[_{nid}_i1];")
    w(f"        float _{nid}_y2 = _{buf}_buf[_{nid}_i2];")
    w(f"        float _{nid}_c0 = _{nid}_y0;")
    w(f"        float _{nid}_c1 = 0.5f * (_{nid}_y1 - _{nid}_ym1);")
    c2a = f"_{nid}_ym1 - 2.5f * _{nid}_y0"
    c2b = f"2.0f * _{nid}_y1 - 0.5f * _{nid}_y2"
    w(f"        float _{nid}_c2 = {c2a} + {c2b};")
    c3a = f"0.5f * (_{nid}_y2 - _{nid}_ym1)"
    c3b = f"1.5f * (_{nid}_y0 - _{nid}_y1)"
    w(f"        float _{nid}_c3 = {c3a} + {c3b};")
    horner = f"((_{nid}_c3 * _{nid}_frac + _{nid}_c2) * _{nid}_frac + _{nid}_c1) * _{nid}_frac + _{nid}_c0"
    w(f"        float {nid} = {horner};")
