"""Tests for the nice-plug (Rust) platform implementation."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from gen_dsp.core.manifest import Manifest, ParamInfo
from gen_dsp.core.midi import detect_midi_mapping
from gen_dsp.core.parser import GenExportParser
from gen_dsp.core.project import ProjectConfig, ProjectGenerator
from gen_dsp.errors import ProjectError
from gen_dsp.platforms import PLATFORM_REGISTRY, NicePlatform, get_platform
from gen_dsp.platforms.nice import _decimals, _rust_str
from tests.helpers import validate_clap, validate_pluginval

_has_cargo = shutil.which("cargo") is not None
_has_cxx = shutil.which("clang++") is not None or shutil.which("g++") is not None
_skip_no_cargo = pytest.mark.skipif(
    not (_has_cargo and _has_cxx), reason="cargo and a C++ compiler required"
)

# Shared across tests and sessions so nice-plug compiles once (build/ is gitignored).
_CARGO_TARGET = Path(__file__).resolve().parent.parent / "build" / ".cargo_target"


def _generate(export: Path, out: Path, name: str, **config_kw) -> Path:
    export_info = GenExportParser(export).parse()
    config = ProjectConfig(name=name, platform="nice", **config_kw)
    return ProjectGenerator(export_info, config).generate(out)


def _generate_manifest(
    manifest: Manifest, out: Path, name: str = "synth", **config_kw
) -> Path:
    out.mkdir()
    config = ProjectConfig(name=name, platform="nice", **config_kw)
    config.midi_mapping = detect_midi_mapping(
        manifest,
        midi_gate=config.midi_gate,
        midi_freq=config.midi_freq,
        midi_vel=config.midi_vel,
    )
    config.midi_mapping.num_voices = config.num_voices
    NicePlatform().generate_project(manifest, out, name, config=config)
    return out


def _synth_manifest() -> Manifest:
    return Manifest(
        gen_name="test_synth",
        num_inputs=0,
        num_outputs=2,
        params=[
            ParamInfo(index=0, name="gate", has_minmax=True, min=0, max=1, default=0),
            ParamInfo(
                index=1, name="freq", has_minmax=True, min=20, max=20000, default=440
            ),
        ],
    )


class TestNicePlatform:
    def test_registry(self):
        assert PLATFORM_REGISTRY["nice"] is NicePlatform
        assert isinstance(get_platform("nice"), NicePlatform)

    def test_extension(self):
        assert NicePlatform().extension == ".clap"

    def test_build_instructions_mention_gui_feature(self):
        assert any(
            "--features gui" in i for i in NicePlatform().get_build_instructions()
        )

    def test_find_output_without_project(self, tmp_path: Path):
        assert NicePlatform().find_output(tmp_path) is None


class TestNiceGeneration:
    def test_project_layout(self, gigaverb_export: Path, tmp_path: Path):
        project = _generate(gigaverb_export, tmp_path / "p", "gigaverb")
        for rel in (
            "Cargo.toml",
            "build.rs",
            "src/lib.rs",
            "src/engine.rs",
            "src/editor.rs",
            "xtask/Cargo.toml",
            "xtask/src/main.rs",
            ".cargo/config.toml",
            ".gitignore",
            "gen_ext_nice.cpp",
            "_ext_nice.cpp",
            "_ext_nice.h",
            "gen_ext_common_nice.h",
            "nice_buffer.h",
        ):
            assert (project / rel).is_file(), rel

    def test_cargo_toml(self, gigaverb_export: Path, tmp_path: Path):
        import tomllib

        project = _generate(gigaverb_export, tmp_path / "p", "gigaverb")
        cargo = tomllib.loads((project / "Cargo.toml").read_text())
        assert cargo["package"]["name"] == "gigaverb"
        assert cargo["lib"]["crate-type"] == ["cdylib", "lib"]
        assert "nice-plug" in cargo["dependencies"]
        assert cargo["features"]["gui"] == ["dep:nice-plug-egui", "dep:egui"]
        assert cargo["workspace"]["members"] == ["xtask"]

    def test_build_rs_export_defines(self, gigaverb_export: Path, tmp_path: Path):
        project = _generate(gigaverb_export, tmp_path / "p", "gigaverb")
        build_rs = (project / "build.rs").read_text()
        assert '.define("NICE_EXT_NAME", Some("gigaverb"))' in build_rs
        assert '.define("GEN_EXPORTED_CPP", Some("\\"gen_exported.cpp\\""))' in build_rs
        assert '.file("gen/gen_dsp/genlib.cpp")' in build_rs
        assert '.file("gen/gen_dsp/json.c")' in build_rs
        # Watching "." would rebuild on every change under target/.
        assert 'rerun-if-changed=.")' not in build_rs
        assert 'rerun-if-changed=gen")' in build_rs

    def test_lib_rs_effect(self, gigaverb_export: Path, tmp_path: Path):
        project = _generate(gigaverb_export, tmp_path / "p", "gigaverb")
        lib = (project / "src" / "lib.rs").read_text()
        assert "$" not in lib
        assert "pub const NUM_INPUTS: usize = 2;" in lib
        assert "pub const NUM_OUTPUTS: usize = 2;" in lib
        assert "pub const NUM_PARAMS: usize = 8;" in lib
        assert '#[id = "revtime"]' in lib
        assert "MidiConfig::None" in lib
        assert "ClapFeature::AudioEffect" in lib
        assert "pub struct GigaverbPlugin" in lib
        assert "aux_input_ports: &[]," in lib

    def test_vst3_class_id_is_16_bytes_and_stable(
        self, gigaverb_export: Path, tmp_path: Path
    ):
        ids = []
        for sub in ("a", "b"):
            lib = (
                _generate(gigaverb_export, tmp_path / sub, "gigaverb")
                / "src"
                / "lib.rs"
            ).read_text()
            line = next(ln for ln in lib.splitlines() if "VST3_CLASS_ID" in ln)
            ids.append(line.split('*b"')[1].split('"')[0])
        assert len(ids[0]) == 16
        assert ids[0] == ids[1]

    def test_extra_inputs_go_to_aux_port(
        self, spectraldelayfb_export: Path, tmp_path: Path
    ):
        project = _generate(spectraldelayfb_export, tmp_path / "p", "sdfb")
        lib = (project / "src" / "lib.rs").read_text()
        assert "pub const NUM_INPUTS: usize = 3;" in lib
        assert "const MAIN_INPUTS: usize = 2;" in lib
        assert "aux_input_ports: &[new_nonzero_u32(1)]," in lib

    def test_buffers(self, rampleplayer_export: Path, tmp_path: Path):
        project = _generate(
            rampleplayer_export, tmp_path / "p", "rample", buffers=["sample"]
        )
        assert "WRAPPER_BUFFER_NAME_0 sample" in (project / "gen_buffer.h").read_text()

    def test_inputs_as_params(self, gigaverb_export: Path, tmp_path: Path):
        project = _generate(
            gigaverb_export, tmp_path / "p", "gigaverb", inputs_as_params=[]
        )
        lib = (project / "src" / "lib.rs").read_text()
        build_rs = (project / "build.rs").read_text()
        assert "pub const NUM_INPUTS: usize = 0;" in lib
        assert "pub const NUM_PARAMS: usize = 10;" in lib
        assert '.define("REMAP_INPUT_COUNT", Some("2"))' in build_rs
        assert '.define("REMAP_INPUT_0_NAME", Some("\\"' in build_rs

    def test_midi_generator(self, tmp_path: Path):
        project = _generate_manifest(
            _synth_manifest(), tmp_path / "p", midi_gate="gate", midi_freq="freq"
        )
        lib = (project / "src" / "lib.rs").read_text()
        build_rs = (project / "build.rs").read_text()
        assert "MidiConfig::Basic" in lib
        assert "ClapFeature::Instrument" in lib
        assert '.define("MIDI_GATE_IDX", Some("0"))' in build_rs
        assert '.define("MIDI_FREQ_IDX", Some("1"))' in build_rs
        assert "NUM_VOICES" not in build_rs
        assert not (project / "voice_alloc.h").exists()

    def test_polyphony(self, tmp_path: Path):
        project = _generate_manifest(
            _synth_manifest(), tmp_path / "p", midi_gate="gate", num_voices=4
        )
        assert '.define("NUM_VOICES", Some("4"))' in (project / "build.rs").read_text()
        assert (project / "voice_alloc.h").is_file()

    def test_param_names_are_sanitized_and_unique(self, tmp_path: Path):
        manifest = Manifest(
            gen_name="m",
            num_inputs=1,
            num_outputs=1,
            params=[
                ParamInfo(
                    index=0, name="a b", has_minmax=True, min=0, max=1, default=0
                ),
                ParamInfo(
                    index=1, name="a-b", has_minmax=True, min=0, max=1, default=0
                ),
                ParamInfo(
                    index=2, name="type", has_minmax=True, min=0, max=1, default=0
                ),
            ],
        )
        lib = (_generate_manifest(manifest, tmp_path / "p") / "src/lib.rs").read_text()
        assert '#[id = "a_b"]' in lib
        assert '#[id = "a_b_2"]' in lib
        assert "pub p_type: FloatParam" in lib
        # Display names keep the gen~ spelling.
        assert 'FloatParam::new("a b"' in lib

    def test_zero_width_range_is_widened(self, tmp_path: Path):
        manifest = Manifest(
            gen_name="m",
            num_inputs=1,
            num_outputs=1,
            params=[
                ParamInfo(index=0, name="k", has_minmax=False, min=2, max=2, default=2)
            ],
        )
        lib = (_generate_manifest(manifest, tmp_path / "p") / "src/lib.rs").read_text()
        assert "FloatRange::Linear { min: 2.0, max: 3.0 }" in lib

    def test_non_finite_bound_is_rejected(self, tmp_path: Path):
        manifest = Manifest(
            gen_name="m",
            num_inputs=1,
            num_outputs=1,
            params=[
                ParamInfo(
                    index=0,
                    name="k",
                    has_minmax=True,
                    min=0,
                    max=float("inf"),
                    default=0,
                )
            ],
        )
        with pytest.raises(ProjectError, match="finite"):
            _generate_manifest(manifest, tmp_path / "p")

    def test_rust_keyword_name_is_rejected(self, gigaverb_export: Path, tmp_path: Path):
        with pytest.raises(ProjectError, match="Cargo package name"):
            _generate(gigaverb_export, tmp_path / "p", "impl")


class TestNiceGraph:
    def test_graph_project(self, tmp_path: Path):
        pytest.importorskip("pydantic")
        from gen_dsp.graph.models import Graph

        examples = Path(__file__).resolve().parent.parent / "examples" / "json"
        graph = Graph.model_validate(
            json.loads((examples / "fm_synth.json").read_text())
        )
        config = ProjectConfig(name="fmsynth", platform="nice", num_voices=4)
        project = ProjectGenerator.from_graph(graph, config).generate(tmp_path / "p")

        build_rs = (project / "build.rs").read_text()
        assert "genlib" not in build_rs
        assert '.define("NUM_VOICES", Some("4"))' in build_rs
        assert 'rerun-if-changed=fm_synth.cpp")' in build_rs
        lib = (project / "src" / "lib.rs").read_text()
        assert "MidiConfig::Basic" in lib
        assert '#[id = "gate"]' in lib


class TestHelpers:
    def test_rust_str(self):
        assert _rust_str('a"b\\c') == '"a\\"b\\\\c"'
        assert _rust_str("x\ny") == '"x\\u{a}y"'

    @pytest.mark.parametrize(
        ("lo", "hi", "want"),
        [(0, 1, 4), (20, 20000, 0), (0, 0.001, 6), (-100, 10, 2), (0, 0, 4)],
    )
    def test_decimals(self, lo: float, hi: float, want: int):
        assert _decimals(lo, hi) == want


def _cargo(project: Path, *args: str, timeout: int = 1800) -> None:
    env = {**os.environ, "CARGO_TARGET_DIR": str(_CARGO_TARGET)}
    fetch = subprocess.run(
        ["cargo", "fetch"],
        cwd=project,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if fetch.returncode != 0:
        pytest.skip(f"cargo fetch failed (offline?):\n{fetch.stderr}")
    result = subprocess.run(
        ["cargo", *args],
        cwd=project,
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
        check=False,
    )
    assert result.returncode == 0, f"cargo {' '.join(args)} failed:\n{result.stderr}"


@_skip_no_cargo
class TestNiceBuildIntegration:
    """Compile generated crates, run their tests, and validate CLAP and VST3 bundles."""

    def _bundle_and_validate(
        self,
        project: Path,
        crate: str,
        validator: Path | None,
        pluginval: Path | None,
        monkeypatch,
    ) -> None:
        _cargo(project, "test", "--release")
        monkeypatch.setenv("CARGO_TARGET_DIR", str(_CARGO_TARGET))
        result = NicePlatform().build(project)
        assert result.success, result.stderr
        assert result.output_file is not None
        assert result.output_file.name == f"{crate}.clap"
        vst3 = _CARGO_TARGET / "bundled" / f"{crate}.vst3"
        assert vst3.exists()
        validate_clap(validator, result.output_file)
        validate_pluginval(pluginval, vst3)

    def test_build_nice_gigaverb(
        self, gigaverb_export, tmp_path, clap_validator, pluginval, monkeypatch
    ):
        project = _generate(gigaverb_export, tmp_path / "p", "gigaverb_nice")
        self._bundle_and_validate(
            project, "gigaverb_nice", clap_validator, pluginval, monkeypatch
        )

    def test_build_nice_aux_inputs(
        self, spectraldelayfb_export, tmp_path, clap_validator, pluginval, monkeypatch
    ):
        project = _generate(spectraldelayfb_export, tmp_path / "p", "sdfb_nice")
        self._bundle_and_validate(
            project, "sdfb_nice", clap_validator, pluginval, monkeypatch
        )

    def test_build_nice_buffers(
        self, rampleplayer_export, tmp_path, clap_validator, pluginval, monkeypatch
    ):
        project = _generate(
            rampleplayer_export, tmp_path / "p", "rample_nice", buffers=["sample"]
        )
        self._bundle_and_validate(
            project, "rample_nice", clap_validator, pluginval, monkeypatch
        )

    def test_build_nice_graph_polyphony(
        self, tmp_path, clap_validator, pluginval, monkeypatch
    ):
        pytest.importorskip("pydantic")
        from gen_dsp.graph.models import Graph

        examples = Path(__file__).resolve().parent.parent / "examples" / "json"
        graph = Graph.model_validate(
            json.loads((examples / "fm_synth.json").read_text())
        )
        config = ProjectConfig(name="fm_nice", platform="nice", num_voices=4)
        project = ProjectGenerator.from_graph(graph, config).generate(tmp_path / "p")
        self._bundle_and_validate(
            project, "fm_nice", clap_validator, pluginval, monkeypatch
        )

    def test_build_nice_gui_feature(self, gigaverb_export, tmp_path):
        project = _generate(gigaverb_export, tmp_path / "p", "gigaverb_gui")
        _cargo(project, "build", "--release", "--features", "gui")
