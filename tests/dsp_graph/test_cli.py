"""Tests for the dsp-graph CLI."""

from __future__ import annotations

pydantic = __import__("pytest").importorskip("pydantic")
numpy = __import__("pytest").importorskip("numpy")
import json
import struct
from pathlib import Path

import numpy as np
import pytest

from gen_dsp.dsp_graph.cli import main


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

    def test_compile_gen_dsp(self, graph_json: Path, tmp_path: Path) -> None:
        out_dir = tmp_path / "gen_dsp_build"
        rc = main(
            ["compile", str(graph_json), "--gen-dsp", "chuck", "-o", str(out_dir)]
        )
        assert rc == 0
        assert (out_dir / "test_graph.cpp").exists()
        assert (out_dir / "_ext_chuck.cpp").exists()
        assert (out_dir / "manifest.json").exists()

    def test_compile_gen_dsp_requires_output(
        self,
        graph_json: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        rc = main(["compile", str(graph_json), "--gen-dsp", "chuck"])
        assert rc == 1
        err = capsys.readouterr().err
        assert "--gen-dsp requires -o" in err


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


class TestDot:
    def test_dot_to_stdout(
        self, graph_json: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = main(["dot", str(graph_json)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "digraph" in out

    def test_dot_to_dir(self, graph_json: Path, tmp_path: Path) -> None:
        out_dir = tmp_path / "dot_out"
        rc = main(["dot", str(graph_json), "-o", str(out_dir)])
        assert rc == 0
        dot_file = out_dir / "test_graph.dot"
        assert dot_file.exists()
        assert "digraph" in dot_file.read_text()


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

        rc = main(["simulate", str(p), "-n", "100", "-o", str(out_dir)])
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
                "simulate",
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
        from gen_dsp.dsp_graph.cli import _read_wav

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
                "simulate",
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

        from gen_dsp.dsp_graph.cli import _read_wav

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

        rc = main(["simulate", str(p), "-n", "100"])
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

        rc = main(["simulate", str(p)])
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

        rc = main(["simulate", str(p), "-n", "100", "-o", str(out_dir), "--optimize"])
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
