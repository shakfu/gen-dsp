"""Tests for the graph CLI."""

from __future__ import annotations

pydantic = __import__("pytest").importorskip("pydantic")
numpy = __import__("pytest").importorskip("numpy")
import json
import struct
from pathlib import Path

import numpy as np
import pytest

from gen_dsp.graph.cli import main


@pytest.fixture
def graph_json(tmp_path: Path) -> Path:
    """Write a minimal valid graph JSON and return its path."""
    data = {
        "name": "test_graph",
        "inputs": [{"id": "in1"}],
        "outputs": [{"id": "out1", "source": "scaled"}],
        "params": [{"name": "gain", "min": 0.0, "max": 2.0, "default": 1.0}],
        "nodes": [{"id": "scaled", "op": "mul", "a": "in1", "b": "gain"}],
    }
    p = tmp_path / "graph.json"
    p.write_text(json.dumps(data))
    return p


@pytest.fixture
def invalid_graph_json(tmp_path: Path) -> Path:
    """Write a graph JSON with validation errors and return its path."""
    data = {
        "name": "bad",
        "nodes": [{"id": "a", "op": "add", "a": "missing", "b": 0.0}],
        "outputs": [{"id": "out1", "source": "a"}],
    }
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(data))
    return p


def _write_test_wav(path: Path, samples: list[float], sample_rate: int = 44100) -> None:
    """Write a mono float32 WAV file for testing."""
    raw = np.array(samples, dtype=np.float32).tobytes()
    n_channels = 1
    bits = 32
    byte_rate = sample_rate * n_channels * bits // 8
    block_align = n_channels * bits // 8
    data_size = len(raw)

    with open(path, "wb") as f:
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + data_size))
        f.write(b"WAVE")
        f.write(b"fmt ")
        f.write(struct.pack("<I", 16))
        f.write(struct.pack("<H", 3))  # IEEE float
        f.write(struct.pack("<H", n_channels))
        f.write(struct.pack("<I", sample_rate))
        f.write(struct.pack("<I", byte_rate))
        f.write(struct.pack("<H", block_align))
        f.write(struct.pack("<H", bits))
        f.write(b"data")
        f.write(struct.pack("<I", data_size))
        f.write(raw)


class TestCompile:
    def test_compile_to_stdout(
        self, graph_json: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = main(["compile", str(graph_json)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "TestGraphState" in out
        assert "test_graph_create" in out

    def test_compile_to_dir(self, graph_json: Path, tmp_path: Path) -> None:
        out_dir = tmp_path / "build"
        rc = main(["compile", str(graph_json), "-o", str(out_dir)])
        assert rc == 0
        cpp = out_dir / "test_graph.cpp"
        assert cpp.exists()
        assert "TestGraphState" in cpp.read_text()

    def test_compile_with_optimize(
        self, graph_json: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = main(["compile", str(graph_json), "--optimize"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "test_graph_perform" in out


class TestValidate:
    def test_validate_valid(
        self, graph_json: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = main(["validate", str(graph_json)])
        assert rc == 0
        assert "valid" in capsys.readouterr().out

    def test_validate_invalid_exits_1(
        self, invalid_graph_json: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = main(["validate", str(invalid_graph_json)])
        assert rc == 1
        err = capsys.readouterr().err
        assert "error:" in err


class TestValidateWarnUnmapped:
    def test_warn_unmapped_params_flag(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """--warn-unmapped-params produces warnings on stderr, exit 0."""
        data = {
            "name": "test",
            "inputs": [{"id": "in1"}],
            "outputs": [{"id": "out1", "source": "filt"}],
            "nodes": [
                {
                    "id": "filt",
                    "op": "subgraph",
                    "graph": {
                        "name": "inner",
                        "inputs": [{"id": "sig"}],
                        "outputs": [{"id": "y", "source": "lpf"}],
                        "params": [{"name": "coeff", "default": 0.5}],
                        "nodes": [
                            {"id": "lpf", "op": "onepole", "a": "sig", "coeff": "coeff"}
                        ],
                    },
                    "inputs": {"sig": "in1"},
                }
            ],
        }
        p = tmp_path / "subgraph.json"
        p.write_text(json.dumps(data))

        rc = main(["validate", str(p), "--warn-unmapped-params"])
        assert rc == 0
        captured = capsys.readouterr()
        assert "warning:" in captured.err
        assert "coeff" in captured.err
        assert "valid" in captured.out

    def test_no_warnings_without_flag(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Without the flag, unmapped params produce no output."""
        data = {
            "name": "test",
            "inputs": [{"id": "in1"}],
            "outputs": [{"id": "out1", "source": "filt"}],
            "nodes": [
                {
                    "id": "filt",
                    "op": "subgraph",
                    "graph": {
                        "name": "inner",
                        "inputs": [{"id": "sig"}],
                        "outputs": [{"id": "y", "source": "lpf"}],
                        "params": [{"name": "coeff", "default": 0.5}],
                        "nodes": [
                            {"id": "lpf", "op": "onepole", "a": "sig", "coeff": "coeff"}
                        ],
                    },
                    "inputs": {"sig": "in1"},
                }
            ],
        }
        p = tmp_path / "subgraph.json"
        p.write_text(json.dumps(data))

        rc = main(["validate", str(p)])
        assert rc == 0
        captured = capsys.readouterr()
        assert "warning:" not in captured.err
        assert "valid" in captured.out


class TestViz:
    def test_viz_to_stdout(
        self, graph_json: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = main(["viz", str(graph_json)])
        assert rc == 0
        captured = capsys.readouterr()
        assert "digraph" in captured.out
        # Primary name emits no deprecation warning.
        assert "deprecated" not in captured.err

    def test_viz_to_dir(self, graph_json: Path, tmp_path: Path) -> None:
        out_dir = tmp_path / "viz_out"
        rc = main(["viz", str(graph_json), "-o", str(out_dir)])
        assert rc == 0
        dot_file = out_dir / "test_graph.dot"
        assert dot_file.exists()
        assert "digraph" in dot_file.read_text()

    def test_dot_alias_still_works_but_warns(
        self, graph_json: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # 'dot' is retained as a deprecated alias for 'viz'.
        rc = main(["dot", str(graph_json)])
        assert rc == 0
        captured = capsys.readouterr()
        assert "digraph" in captured.out
        assert "deprecated" in captured.err
        assert "viz" in captured.err


class TestSimulate:
    def test_generator_no_inputs(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Simulate a generator graph (SinOsc, no audio inputs)."""
        data = {
            "name": "gen",
            "outputs": [{"id": "out1", "source": "osc"}],
            "params": [{"name": "freq", "default": 440.0}],
            "nodes": [{"id": "osc", "op": "sinosc", "freq": "freq"}],
        }
        p = tmp_path / "gen.json"
        p.write_text(json.dumps(data))
        out_dir = tmp_path / "sim_out"

        rc = main(["sim", str(p), "-n", "100", "-o", str(out_dir)])
        assert rc == 0
        wav_path = out_dir / "out1.wav"
        assert wav_path.exists()
        assert "wrote" in capsys.readouterr().out

    def test_wav_round_trip(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Feed a WAV through a gain graph and verify output WAV exists."""
        # Create input WAV
        input_wav = tmp_path / "input.wav"
        samples = [0.5] * 64
        _write_test_wav(input_wav, samples, sample_rate=48000)

        # Graph: in1 * gain -> out1
        data = {
            "name": "gain",
            "inputs": [{"id": "in1"}],
            "outputs": [{"id": "out1", "source": "scaled"}],
            "params": [{"name": "gain", "default": 0.5}],
            "nodes": [{"id": "scaled", "op": "mul", "a": "in1", "b": "gain"}],
        }
        p = tmp_path / "gain.json"
        p.write_text(json.dumps(data))
        out_dir = tmp_path / "wav_out"

        rc = main(
            [
                "sim",
                str(p),
                "-i",
                f"in1={input_wav}",
                "-o",
                str(out_dir),
            ]
        )
        assert rc == 0
        out_wav = out_dir / "out1.wav"
        assert out_wav.exists()

        # Read back and verify values are ~0.25 (0.5 * 0.5)
        from gen_dsp.graph.cli import _read_wav

        channels, sr = _read_wav(str(out_wav))
        assert sr == 48000
        assert len(channels[0]) == 64
        assert abs(channels[0][0] - 0.25) < 1e-6

    def test_param_override(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """--param overrides default param value."""
        input_wav = tmp_path / "input.wav"
        _write_test_wav(input_wav, [1.0] * 32, sample_rate=44100)

        data = {
            "name": "gain",
            "inputs": [{"id": "in1"}],
            "outputs": [{"id": "out1", "source": "scaled"}],
            "params": [{"name": "gain", "default": 0.5}],
            "nodes": [{"id": "scaled", "op": "mul", "a": "in1", "b": "gain"}],
        }
        p = tmp_path / "gain.json"
        p.write_text(json.dumps(data))
        out_dir = tmp_path / "param_out"

        rc = main(
            [
                "sim",
                str(p),
                "-i",
                f"in1={input_wav}",
                "-o",
                str(out_dir),
                "--param",
                "gain=0.75",
            ]
        )
        assert rc == 0

        from gen_dsp.graph.cli import _read_wav

        channels, _ = _read_wav(str(out_dir / "out1.wav"))
        assert abs(channels[0][0] - 0.75) < 1e-6

    def test_missing_input_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Graph with inputs but no -i should fail."""
        data = {
            "name": "gain",
            "inputs": [{"id": "in1"}],
            "outputs": [{"id": "out1", "source": "scaled"}],
            "nodes": [{"id": "scaled", "op": "mul", "a": "in1", "b": 1.0}],
        }
        p = tmp_path / "gain.json"
        p.write_text(json.dumps(data))

        rc = main(["sim", str(p), "-n", "100"])
        assert rc == 1
        assert "missing input" in capsys.readouterr().err

    def test_missing_n_samples_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Generator without -n should fail."""
        data = {
            "name": "gen",
            "outputs": [{"id": "out1", "source": "osc"}],
            "params": [{"name": "freq", "default": 440.0}],
            "nodes": [{"id": "osc", "op": "sinosc", "freq": "freq"}],
        }
        p = tmp_path / "gen.json"
        p.write_text(json.dumps(data))

        rc = main(["sim", str(p)])
        assert rc == 1
        assert "--samples" in capsys.readouterr().err

    def test_simulate_with_optimize(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """--optimize flag should work without errors."""
        data = {
            "name": "gen",
            "outputs": [{"id": "out1", "source": "osc"}],
            "params": [{"name": "freq", "default": 440.0}],
            "nodes": [{"id": "osc", "op": "sinosc", "freq": "freq"}],
        }
        p = tmp_path / "gen.json"
        p.write_text(json.dumps(data))
        out_dir = tmp_path / "opt_out"

        rc = main(["sim", str(p), "-n", "100", "-o", str(out_dir), "--optimize"])
        assert rc == 0
        assert (out_dir / "out1.wav").exists()


class TestErrorHandling:
    def test_no_command_exits_1(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = main([])
        assert rc == 1

    def test_missing_file_exits_1(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = main(["compile", "/nonexistent/graph.json"])
        assert rc == 1
        err = capsys.readouterr().err
        assert "error:" in err

    def test_malformed_json_exits_1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("{not valid json")
        rc = main(["compile", str(bad)])
        assert rc == 1
        err = capsys.readouterr().err
        assert "invalid JSON" in err

    def test_invalid_schema_exits_1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        bad = tmp_path / "bad_schema.json"
        bad.write_text(json.dumps({"name": 123}))
        rc = main(["compile", str(bad)])
        assert rc == 1
        err = capsys.readouterr().err
        assert "error:" in err


# ---------------------------------------------------------------------------
# .gdsp CLI integration tests
# ---------------------------------------------------------------------------


@pytest.fixture
def gdsp_file(tmp_path: Path) -> Path:
    """Write a minimal .gdsp file and return its path."""
    p = tmp_path / "gain.gdsp"
    p.write_text(
        """
        graph gain {
            in input
            out output = scaled
            param vol 0..2 = 1.0
            scaled = input * vol
        }
        """
    )
    return p


class TestGdspCompile:
    def test_compile_gdsp_to_stdout(
        self, gdsp_file: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = main(["compile", str(gdsp_file)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "GainState" in out
        assert "gain_perform" in out

    def test_compile_gdsp_to_dir(self, gdsp_file: Path, tmp_path: Path) -> None:
        out_dir = tmp_path / "build"
        rc = main(["compile", str(gdsp_file), "-o", str(out_dir)])
        assert rc == 0
        cpp = out_dir / "gain.cpp"
        assert cpp.exists()


class TestGdspValidate:
    def test_validate_gdsp(
        self, gdsp_file: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = main(["validate", str(gdsp_file)])
        assert rc == 0
        assert "valid" in capsys.readouterr().out

    def test_validate_gdsp_syntax_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        bad = tmp_path / "bad.gdsp"
        bad.write_text("graph t {")
        rc = main(["compile", str(bad)])
        assert rc == 1
        err = capsys.readouterr().err
        assert "error:" in err

    def test_validate_gdsp_compile_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        bad = tmp_path / "bad.gdsp"
        bad.write_text(
            """
            graph t {
                out o = y
                y = undefined_func(1)
            }
            """
        )
        rc = main(["compile", str(bad)])
        assert rc == 1
        err = capsys.readouterr().err
        assert "error:" in err


class TestGdspViz:
    def test_viz_gdsp(
        self, gdsp_file: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = main(["viz", str(gdsp_file)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "digraph" in out
        assert "gain" in out


class TestGdspMultiGraph:
    def test_compile_multi_graph_gdsp(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Multi-graph .gdsp uses last graph (which references earlier ones)."""
        p = tmp_path / "multi.gdsp"
        p.write_text(
            """
            graph inner {
                in x
                out output = y
                param coeff 0..1 = 0.5
                y = onepole(x, coeff)
            }
            graph outer {
                in input
                out output = result
                result = inner(x=input, coeff=0.3)
            }
            """
        )
        rc = main(["compile", str(p)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "OuterState" in out


class TestGenexprCommand:
    """Tests for the experimental 'genexpr' subcommand (gen~ codebox)."""

    def test_genexpr_to_stdout(
        self, graph_json: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = main(["genexpr", str(graph_json)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Generated by gen-dsp" in out
        assert "scaled = in1 * gain;" in out
        assert "out1 = scaled;" in out

    def test_genexpr_to_file(self, graph_json: Path, tmp_path: Path) -> None:
        out_file = tmp_path / "patch.genexpr"
        rc = main(["genexpr", str(graph_json), "-o", str(out_file)])
        assert rc == 0
        assert out_file.exists()
        assert "scaled = in1 * gain;" in out_file.read_text()

    def test_genexpr_unsupported_node_errors(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        data = {
            "name": "sinebuf",
            "outputs": [{"id": "out1", "source": "c"}],
            "nodes": [
                {"id": "b", "op": "buffer", "size": 64, "fill": "sine"},
                {"id": "c", "op": "cycle", "buffer": "b", "phase": 0.5},
            ],
        }
        p = tmp_path / "sinebuf.json"
        p.write_text(json.dumps(data))
        rc = main(["genexpr", str(p)])
        assert rc == 1
        assert "not supported by the gen~ transpiler" in capsys.readouterr().err

    def test_genexpr_invalid_graph_errors(
        self, invalid_graph_json: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = main(["genexpr", str(invalid_graph_json)])
        assert rc == 1
        assert "error" in capsys.readouterr().err

    def test_genexpr_noise_emits_native(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        data = {
            "name": "ng",
            "outputs": [{"id": "out1", "source": "n"}],
            "nodes": [{"id": "n", "op": "noise"}],
        }
        p = tmp_path / "noise.json"
        p.write_text(json.dumps(data))
        rc = main(["genexpr", str(p)])
        assert rc == 0
        assert "n = noise();" in capsys.readouterr().out
