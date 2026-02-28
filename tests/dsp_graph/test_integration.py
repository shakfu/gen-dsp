"""Integration tests for dsp-graph -> gen-dsp project generation."""

from __future__ import annotations

import json
import subprocess

import pytest

pydantic = pytest.importorskip("pydantic")

from gen_dsp.core.project import ProjectConfig, ProjectGenerator
from gen_dsp.dsp_graph import (
    AudioInput,
    AudioOutput,
    BinOp,
    Graph,
    Param,
)


@pytest.fixture
def simple_gain_graph() -> Graph:
    """Minimal mono gain graph for integration testing."""
    return Graph(
        name="gain",
        inputs=[AudioInput(id="in1")],
        outputs=[AudioOutput(id="out1", source="mul1")],
        params=[Param(name="volume", min=0.0, max=1.0, default=0.5)],
        nodes=[BinOp(id="mul1", op="mul", a="in1", b="volume")],
    )


class TestFromGraphProjectStructure:
    """Test that --from-graph produces correct project structure."""

    @pytest.mark.parametrize(
        "platform",
        ["clap", "pd", "chuck", "au", "vst3", "lv2", "sc", "max"],
    )
    def test_generates_project_files(self, simple_gain_graph, tmp_path, platform):
        """Each platform should produce key files without errors."""
        config = ProjectConfig(name="test_gain", platform=platform)
        gen = ProjectGenerator.from_graph(simple_gain_graph, config)
        out = gen.generate(output_dir=tmp_path / f"proj_{platform}")

        # Common files for all platforms
        assert (out / "gain.cpp").is_file(), "compiled graph C++ missing"
        assert (out / f"_ext_{platform}.cpp").is_file(), "adapter missing"
        assert (out / f"_ext_{platform}.h").is_file(), "ext header missing"
        assert (out / "manifest.json").is_file(), "manifest missing"
        assert (out / "gen_buffer.h").is_file(), "buffer header missing"

        # No gen/ subdirectory (dsp-graph path doesn't copy gen~ export)
        assert not (out / "gen").exists(), "gen/ dir should not exist"

    def test_manifest_content(self, simple_gain_graph, tmp_path):
        """Manifest should reflect graph metadata."""
        config = ProjectConfig(name="test_gain", platform="clap")
        gen = ProjectGenerator.from_graph(simple_gain_graph, config)
        out = gen.generate(output_dir=tmp_path / "proj")

        manifest = json.loads((out / "manifest.json").read_text())
        assert manifest["gen_name"] == "gain"
        assert manifest["num_inputs"] == 1
        assert manifest["num_outputs"] == 1
        assert manifest["source"] == "dsp-graph"
        assert len(manifest["params"]) == 1
        assert manifest["params"][0]["name"] == "volume"

    def test_compiled_cpp_contains_graph_code(self, simple_gain_graph, tmp_path):
        """The compiled .cpp should contain the graph's perform function."""
        config = ProjectConfig(name="test_gain", platform="clap")
        gen = ProjectGenerator.from_graph(simple_gain_graph, config)
        out = gen.generate(output_dir=tmp_path / "proj")

        cpp = (out / "gain.cpp").read_text()
        assert "perform" in cpp
        assert "gain" in cpp

    def test_no_genlib_references_in_build_file(self, simple_gain_graph, tmp_path):
        """dsp-graph build files should not reference genlib sources."""
        config = ProjectConfig(name="test_gain", platform="clap")
        gen = ProjectGenerator.from_graph(simple_gain_graph, config)
        out = gen.generate(output_dir=tmp_path / "proj")

        cmake = (out / "CMakeLists.txt").read_text()
        assert "genlib.cpp" not in cmake
        assert "json.c" not in cmake
        assert "gen/" not in cmake


class TestFromGraphCLI:
    """Test the --from-graph CLI option."""

    def test_init_from_graph_json(self, tmp_path):
        """gen-dsp init --from-graph should create a project."""
        graph_json = {
            "name": "cli_test",
            "inputs": [{"id": "in1"}],
            "outputs": [{"id": "out1", "source": "mul1"}],
            "params": [{"name": "vol", "min": 0.0, "max": 1.0, "default": 0.5}],
            "nodes": [{"op": "mul", "id": "mul1", "a": "in1", "b": "vol"}],
        }
        graph_file = tmp_path / "test.json"
        graph_file.write_text(json.dumps(graph_json))

        out_dir = tmp_path / "output"
        result = subprocess.run(
            [
                "gen-dsp",
                "init",
                "--from-graph",
                str(graph_file),
                "-n",
                "cli_test",
                "-p",
                "clap",
                "-o",
                str(out_dir),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"
        assert (out_dir / "cli_test.cpp").is_file()
        assert (out_dir / "CMakeLists.txt").is_file()
        assert (out_dir / "manifest.json").is_file()


class TestFromGraphBuild:
    """Build integration tests for dsp-graph projects."""

    @pytest.fixture
    def clap_project(self, simple_gain_graph, tmp_path):
        """Generate a CLAP project from a dsp-graph."""
        config = ProjectConfig(name="gain", platform="clap")
        gen = ProjectGenerator.from_graph(simple_gain_graph, config)
        return gen.generate(output_dir=tmp_path / "gain_clap")

    def test_build_clap_from_graph(self, clap_project):
        """Build a CLAP plugin from a dsp-graph definition."""
        # Configure
        result = subprocess.run(
            ["cmake", "-B", "build"],
            cwd=str(clap_project),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"cmake configure failed:\n{result.stderr}"

        # Build
        result = subprocess.run(
            ["cmake", "--build", "build"],
            cwd=str(clap_project),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"cmake build failed:\n{result.stderr}"

        # Check output exists
        clap_bundle = clap_project / "build" / "gain.clap"
        assert clap_bundle.exists(), "CLAP bundle not produced"
