"""Tests for gen-dsp adapter: reset(), adapter C++, manifest, integration."""

from __future__ import annotations

pydantic = __import__("pytest").importorskip("pydantic")
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from gen_dsp.graph import (
    AudioInput,
    AudioOutput,
    Graph,
    History,
    Noise,
    Phasor,
    compile_graph,
)
from gen_dsp.graph.adapter import (
    compile_for_gen_dsp,
    generate_adapter_cpp,
    generate_manifest,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_HAS_GPP = shutil.which("g++") is not None

skip_no_gpp = pytest.mark.skipif(not _HAS_GPP, reason="g++ not found")


def _try_import_gen_dsp():
    try:
        import gen_dsp  # noqa: F401

        return True
    except ImportError:
        return False


_HAS_GEN_DSP = _try_import_gen_dsp()

skip_no_gen_dsp = pytest.mark.skipif(not _HAS_GEN_DSP, reason="gen_dsp not installed")


# ---------------------------------------------------------------------------
# TestReset
# ---------------------------------------------------------------------------


class TestReset:
    def test_reset_function_generated(self, stereo_gain_graph):
        code = compile_graph(stereo_gain_graph)
        assert "stereo_gain_reset" in code

    def test_reset_params_to_defaults(self, stereo_gain_graph):
        code = compile_graph(stereo_gain_graph)
        assert "self->p_gain = 1.0f;" in code

    def test_reset_history_to_init(self, onepole_graph):
        code = compile_graph(onepole_graph)
        # History(id="prev", init=0.0) -> reset should set m_prev = 0.0f
        assert "self->m_prev = 0.0f;" in code

    def test_reset_history_nonzero_init(self):
        g = Graph(
            name="h_test",
            inputs=[AudioInput(id="in1")],
            outputs=[AudioOutput(id="out1", source="h1")],
            nodes=[History(id="h1", init=0.5, input="in1")],
        )
        code = compile_graph(g)
        # Should appear in both create() and reset()
        assert code.count("self->m_h1 = 0.5f;") >= 2

    def test_reset_delay_to_zero(self, fbdelay_graph):
        code = compile_graph(fbdelay_graph)
        assert (
            "memset(self->m_dline_buf, 0, self->m_dline_len * sizeof(float));" in code
        )
        assert "self->m_dline_wr = 0;" in code

    def test_reset_buffer_to_zero(self, gen_dsp_graph):
        code = compile_graph(gen_dsp_graph)
        assert "memset(self->m_wt_buf, 0, self->m_wt_len * sizeof(float));" in code

    def test_reset_oscillator_phase(self, gen_dsp_graph):
        code = compile_graph(gen_dsp_graph)
        # SinOsc(id="osc1") -> m_osc1_phase
        assert "self->m_osc1_phase = 0.0f;" in code

    def test_reset_phasor_phase(self):
        g = Graph(
            name="ph_test",
            inputs=[],
            outputs=[AudioOutput(id="out1", source="p1")],
            nodes=[Phasor(id="p1", freq=440.0)],
        )
        code = compile_graph(g)
        assert "self->m_p1_phase = 0.0f;" in code

    def test_reset_noise_seed(self):
        g = Graph(
            name="noise_test",
            inputs=[],
            outputs=[AudioOutput(id="out1", source="n1")],
            nodes=[Noise(id="n1")],
        )
        code = compile_graph(g)
        # reset should restore seed to same initial value as create
        assert code.count("self->m_n1_seed = 123456789u;") >= 2

    def test_reset_onepole_prev(self, gen_dsp_graph):
        code = compile_graph(gen_dsp_graph)
        assert "self->m_lp_prev = 0.0f;" in code

    def test_reset_uses_memset(self, fbdelay_graph):
        code = compile_graph(fbdelay_graph)
        assert "#include <cstring>" in code
        assert "memset" in code

    @skip_no_gpp
    def test_reset_g_plus_plus_compiles(self, gen_dsp_graph, tmp_path):
        code = compile_graph(gen_dsp_graph)
        src = tmp_path / "test.cpp"
        src.write_text(code)
        result = subprocess.run(
            ["g++", "-std=c++11", "-c", "-o", str(tmp_path / "test.o"), str(src)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"g++ failed:\n{result.stderr}"


# ---------------------------------------------------------------------------
# TestAdapterCpp
# ---------------------------------------------------------------------------


class TestAdapterCpp:
    def test_adapter_includes_common_header(self, gen_dsp_graph):
        code = generate_adapter_cpp(gen_dsp_graph, "chuck")
        assert '#include "gen_ext_common_chuck.h"' in code

    def test_adapter_includes_graph_cpp(self, gen_dsp_graph):
        code = generate_adapter_cpp(gen_dsp_graph, "chuck")
        assert '#include "test_synth.cpp"' in code

    def test_adapter_wrapper_namespace(self, gen_dsp_graph):
        code = generate_adapter_cpp(gen_dsp_graph, "chuck")
        assert "namespace WRAPPER_NAMESPACE {" in code
        assert "} // namespace WRAPPER_NAMESPACE" in code

    def test_adapter_create_ignores_blocksize(self, gen_dsp_graph):
        code = generate_adapter_cpp(gen_dsp_graph, "chuck")
        assert "(void)bs;" in code

    def test_adapter_reset_calls_reset(self, gen_dsp_graph):
        code = generate_adapter_cpp(gen_dsp_graph, "chuck")
        assert "test_synth_reset(" in code

    def test_adapter_perform_ignores_counts(self, gen_dsp_graph):
        code = generate_adapter_cpp(gen_dsp_graph, "chuck")
        assert "(void)numins; (void)numouts;" in code

    def test_adapter_param_units_empty(self, gen_dsp_graph):
        code = generate_adapter_cpp(gen_dsp_graph, "chuck")
        assert 'return "";' in code

    def test_adapter_param_hasminmax_true(self, gen_dsp_graph):
        code = generate_adapter_cpp(gen_dsp_graph, "chuck")
        assert "return 1;" in code

    def test_adapter_buffers(self, gen_dsp_graph):
        code = generate_adapter_cpp(gen_dsp_graph, "chuck")
        assert "test_synth_num_buffers()" in code
        assert "test_synth_buffer_name(index)" in code

    def test_adapter_multiple_platforms(self, gen_dsp_graph):
        for plat in ("chuck", "clap", "au"):
            code = generate_adapter_cpp(gen_dsp_graph, plat)
            assert f'#include "gen_ext_common_{plat}.h"' in code

    def test_adapter_unknown_platform_raises(self, gen_dsp_graph):
        with pytest.raises(ValueError, match="Unknown platform"):
            generate_adapter_cpp(gen_dsp_graph, "nonexistent")


# ---------------------------------------------------------------------------
# TestManifest
# ---------------------------------------------------------------------------


class TestManifest:
    def test_manifest_json_valid(self, gen_dsp_graph):
        text = generate_manifest(gen_dsp_graph)
        data = json.loads(text)
        assert isinstance(data, dict)

    def test_manifest_source_dsp_graph(self, gen_dsp_graph):
        data = json.loads(generate_manifest(gen_dsp_graph))
        assert data["source"] == "dsp-graph"

    def test_manifest_io_counts(self, gen_dsp_graph):
        data = json.loads(generate_manifest(gen_dsp_graph))
        assert data["num_inputs"] == 2
        assert data["num_outputs"] == 2

    def test_manifest_params(self, gen_dsp_graph):
        data = json.loads(generate_manifest(gen_dsp_graph))
        params = data["params"]
        assert len(params) == 3
        names = [p["name"] for p in params]
        assert names == ["freq", "gain", "cutoff"]
        # Check freq param details
        freq = params[0]
        assert freq["min"] == 20.0
        assert freq["max"] == 20000.0
        assert freq["default"] == 440.0
        assert freq["has_minmax"] is True

    def test_manifest_buffers(self, gen_dsp_graph):
        data = json.loads(generate_manifest(gen_dsp_graph))
        assert data["buffers"] == ["wt"]

    def test_manifest_gen_name(self, gen_dsp_graph):
        data = json.loads(generate_manifest(gen_dsp_graph))
        assert data["gen_name"] == "test_synth"

    def test_manifest_version(self, gen_dsp_graph):
        from gen_dsp.graph import __version__

        data = json.loads(generate_manifest(gen_dsp_graph))
        assert data["version"] == __version__

    @skip_no_gen_dsp
    def test_manifest_gen_dsp_compatible(self, gen_dsp_graph):
        from gen_dsp.core.manifest import Manifest

        text = generate_manifest(gen_dsp_graph)
        m = Manifest.from_json(text)
        assert m.gen_name == "test_synth"
        assert m.num_inputs == 2
        assert m.num_outputs == 2
        assert len(m.params) == 3
        assert m.source == "dsp-graph"


# ---------------------------------------------------------------------------
# TestCompileForGenDsp
# ---------------------------------------------------------------------------


class TestCompileForGenDsp:
    def test_output_files(self, gen_dsp_graph, tmp_path):
        out = compile_for_gen_dsp(gen_dsp_graph, tmp_path / "proj", "chuck")
        assert (out / "test_synth.cpp").is_file()
        assert (out / "_ext_chuck.cpp").is_file()
        assert (out / "manifest.json").is_file()

    def test_creates_output_dir(self, gen_dsp_graph, tmp_path):
        target = tmp_path / "nested" / "deep" / "proj"
        out = compile_for_gen_dsp(gen_dsp_graph, target, "clap")
        assert out.is_dir()
        assert (out / "test_synth.cpp").is_file()

    def test_manifest_content_matches(self, gen_dsp_graph, tmp_path):
        out = compile_for_gen_dsp(gen_dsp_graph, tmp_path / "proj", "au")
        data = json.loads((out / "manifest.json").read_text())
        assert data["gen_name"] == "test_synth"
        assert data["num_inputs"] == 2


# ---------------------------------------------------------------------------
# Integration tests (gated on gen_dsp + g++)
# ---------------------------------------------------------------------------


class TestIntegration:
    @skip_no_gpp
    def test_adapter_compiles_standalone(self, gen_dsp_graph, tmp_path):
        """Compile adapter + dsp-graph code with g++ (no platform headers)."""
        out = compile_for_gen_dsp(gen_dsp_graph, tmp_path, "chuck")

        # Create minimal stubs for the headers the adapter includes
        _write_stub_headers(out, "chuck")

        result = subprocess.run(
            [
                "g++",
                "-std=c++11",
                "-c",
                "-I",
                str(out),
                "-o",
                str(out / "adapter.o"),
                str(out / "_ext_chuck.cpp"),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"g++ failed:\n{result.stderr}"

    @skip_no_gpp
    def test_adapter_compiles_clap(self, gen_dsp_graph, tmp_path):
        out = compile_for_gen_dsp(gen_dsp_graph, tmp_path, "clap")
        _write_stub_headers(out, "clap")

        result = subprocess.run(
            [
                "g++",
                "-std=c++11",
                "-c",
                "-I",
                str(out),
                "-o",
                str(out / "adapter.o"),
                str(out / "_ext_clap.cpp"),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"g++ failed:\n{result.stderr}"

    @skip_no_gpp
    def test_adapter_compiles_au(self, gen_dsp_graph, tmp_path):
        out = compile_for_gen_dsp(gen_dsp_graph, tmp_path, "au")
        _write_stub_headers(out, "au")

        result = subprocess.run(
            [
                "g++",
                "-std=c++11",
                "-c",
                "-I",
                str(out),
                "-o",
                str(out / "adapter.o"),
                str(out / "_ext_au.cpp"),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"g++ failed:\n{result.stderr}"

    @skip_no_gen_dsp
    @skip_no_gpp
    def test_assemble_chuck_project(self, gen_dsp_graph, tmp_path):
        """Assemble full project with real gen-dsp templates and compile."""
        from gen_dsp.core.project import ProjectConfig, ProjectGenerator

        config = ProjectConfig(name="test_synth", platform="chuck")
        gen = ProjectGenerator.from_graph(gen_dsp_graph, config)
        out = gen.generate(output_dir=tmp_path / "chuck_proj")

        # Verify key files exist
        assert (out / "test_synth.cpp").is_file()
        assert (out / "_ext_chuck.cpp").is_file()
        assert (out / "gen_ext_common_chuck.h").is_file()
        assert (out / "_ext_chuck.h").is_file()
        assert (out / "gen_buffer.h").is_file()
        assert (out / "manifest.json").is_file()

        # Compile the adapter object
        result = subprocess.run(
            [
                "g++",
                "-std=c++11",
                "-c",
                "-DCHUCK_EXT_NAME=test_synth",
                "-I",
                str(out),
                "-o",
                str(out / "adapter.o"),
                str(out / "_ext_chuck.cpp"),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"adapter compile failed:\n{result.stderr}"


def _write_stub_headers(output_dir: Path, platform: str) -> None:
    """Write minimal stub headers so the adapter compiles standalone."""
    # gen_buffer.h
    (output_dir / "gen_buffer.h").write_text(
        "#ifndef GEN_BUFFER_H\n#define GEN_BUFFER_H\n#define WRAPPER_BUFFER_COUNT 0\n#endif\n"
    )

    # Platform common header with WRAPPER_NAMESPACE defined to a real identifier
    platform_macros = {
        "chuck": ("CHUCK_EXT_NAME", "_chugin"),
        "clap": ("CLAP_EXT_NAME", "_clap"),
        "au": ("AU_EXT_NAME", "_au"),
    }
    macro_name, suffix = platform_macros[platform]

    (output_dir / f"gen_ext_common_{platform}.h").write_text(
        f"#ifndef GEN_EXT_COMMON_{platform.upper()}_H\n"
        f"#define GEN_EXT_COMMON_{platform.upper()}_H\n"
        f'#include "gen_buffer.h"\n'
        f"#define {macro_name} stub\n"
        f"#define WRAPPER_FUN(A, B) A ## B\n"
        f"#define WRAPPER_FUN2(A, B) WRAPPER_FUN(A, B)\n"
        f"#define WRAPPER_NAMESPACE WRAPPER_FUN2({macro_name}, {suffix})\n"
        f"#endif\n"
    )
