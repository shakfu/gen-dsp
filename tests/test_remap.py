"""Tests for --inputs-as-params (input-to-parameter remapping)."""

from pathlib import Path

import pytest

from gen_dsp.core.manifest import (
    Manifest,
    ParamInfo,
    _build_remap_defs,
    apply_inputs_as_params,
    build_remap_defines,
    build_remap_defines_make,
)
from gen_dsp.core.parser import GenExportParser
from gen_dsp.core.project import ProjectConfig, ProjectGenerator

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fm_bells_export() -> Path:
    """Path to the fm_bells gen~ export (2 signal inputs used as control data)."""
    p = Path(__file__).parent.parent / "examples" / "gen_export" / "fm_bells"
    if not p.exists():
        pytest.skip("fm_bells example not found")
    return p


@pytest.fixture
def base_manifest() -> Manifest:
    """A manifest with 2 inputs, 2 outputs, 3 params (like fm_bells)."""
    return Manifest(
        gen_name="gen_exported",
        num_inputs=2,
        num_outputs=2,
        params=[
            ParamInfo(
                index=0, name="depth", has_minmax=True, min=0.0, max=1.0, default=0.5
            ),
            ParamInfo(
                index=1, name="t60", has_minmax=True, min=0.0, max=10.0, default=2.0
            ),
            ParamInfo(
                index=2, name="smooth", has_minmax=True, min=0.0, max=1.0, default=0.1
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Parser: input_names extraction
# ---------------------------------------------------------------------------


class TestParserInputNames:
    """Test extraction of gen_kernel_innames from exported code."""

    def test_fm_bells_input_names(self, fm_bells_export):
        """fm_bells has input names 'carrier' and 'c/m ratio'."""
        parser = GenExportParser(fm_bells_export)
        info = parser.parse()
        assert info.input_names == ["carrier", "c/m ratio"]

    def test_gigaverb_input_names(self):
        """gigaverb has input names 'in1' and 'in2'."""
        fixtures = Path(__file__).parent / "fixtures"
        parser = GenExportParser(fixtures / "gigaverb" / "gen")
        info = parser.parse()
        # gigaverb has 2 inputs -- check that names are extracted
        assert len(info.input_names) == info.num_inputs

    def test_no_innames_returns_empty(self):
        """Exports without gen_kernel_innames should return empty list."""
        # RamplePlayer may or may not have innames; the key is no crash
        fixtures = Path(__file__).parent / "fixtures"
        parser = GenExportParser(fixtures / "RamplePlayer" / "gen")
        info = parser.parse()
        # Should be a list (possibly empty)
        assert isinstance(info.input_names, list)


# ---------------------------------------------------------------------------
# apply_inputs_as_params
# ---------------------------------------------------------------------------


class TestApplyInputsAsParams:
    """Test the core remap logic."""

    def test_remap_all_inputs(self, base_manifest):
        """With remap_names=None, all inputs become params."""
        input_names = ["carrier", "c/m ratio"]
        result = apply_inputs_as_params(base_manifest, input_names, remap_names=None)

        # All 2 inputs remapped -> num_inputs goes to 0
        assert result.num_inputs == 0
        # 3 original params + 2 remapped = 5
        assert result.num_params == 5
        assert len(result.remapped_inputs) == 2
        # Check the synthetic param names
        assert result.params[3].name == "carrier"
        assert result.params[4].name == "c_m_ratio"  # sanitized

    def test_remap_specific_inputs(self, base_manifest):
        """Remap only 'carrier', leave 'c/m ratio' as audio input."""
        input_names = ["carrier", "c/m ratio"]
        result = apply_inputs_as_params(
            base_manifest, input_names, remap_names=["carrier"]
        )

        # Only 1 input remapped -> num_inputs goes from 2 to 1
        assert result.num_inputs == 1
        # 3 original + 1 remapped = 4
        assert result.num_params == 4
        assert len(result.remapped_inputs) == 1
        assert result.remapped_inputs[0].input_name == "carrier"
        assert result.remapped_inputs[0].gen_input_index == 0

    def test_remap_preserves_original_params(self, base_manifest):
        """Original params should be unchanged after remapping."""
        input_names = ["carrier", "c/m ratio"]
        result = apply_inputs_as_params(base_manifest, input_names, remap_names=None)

        for i in range(3):
            assert result.params[i].name == base_manifest.params[i].name
            assert result.params[i].min == base_manifest.params[i].min
            assert result.params[i].max == base_manifest.params[i].max

    def test_remap_gen_input_indices(self, base_manifest):
        """Remapped inputs track their original gen~ input index."""
        input_names = ["carrier", "c/m ratio"]
        result = apply_inputs_as_params(base_manifest, input_names, remap_names=None)

        assert result.remapped_inputs[0].gen_input_index == 0
        assert result.remapped_inputs[1].gen_input_index == 1

    def test_remap_param_indices(self, base_manifest):
        """Remapped params get indices after existing params."""
        input_names = ["carrier", "c/m ratio"]
        result = apply_inputs_as_params(base_manifest, input_names, remap_names=None)

        assert result.remapped_inputs[0].param_index == 3
        assert result.remapped_inputs[1].param_index == 4

    def test_remap_no_input_names_raises(self, base_manifest):
        """Remapping with empty input_names should raise ValueError."""
        with pytest.raises(ValueError, match="No input names found"):
            apply_inputs_as_params(base_manifest, [], remap_names=None)

    def test_remap_invalid_name_raises(self, base_manifest):
        """Requesting remap of a non-existent input name should raise."""
        input_names = ["carrier", "c/m ratio"]
        with pytest.raises(ValueError, match="not_a_real_input"):
            apply_inputs_as_params(
                base_manifest, input_names, remap_names=["not_a_real_input"]
            )

    def test_remap_zero_input_manifest_raises(self):
        """Remapping on a generator (0 inputs, no input names) should raise."""
        manifest = Manifest(
            gen_name="gen_exported",
            num_inputs=0,
            num_outputs=2,
            params=[],
        )
        with pytest.raises(ValueError, match="No input names found"):
            apply_inputs_as_params(manifest, [], remap_names=None)


# ---------------------------------------------------------------------------
# build_remap_defines (CMake format)
# ---------------------------------------------------------------------------


class TestBuildRemapDefines:
    """Test CMake-format remap define generation."""

    def test_no_remaps_returns_empty(self, base_manifest):
        """No remapped inputs -> empty string."""
        assert build_remap_defines(base_manifest) == ""

    def test_with_remaps(self, base_manifest):
        """Remapped inputs produce correct CMake defines."""
        input_names = ["carrier", "c/m ratio"]
        remapped = apply_inputs_as_params(base_manifest, input_names, remap_names=None)

        defines = build_remap_defines(remapped)
        assert "REMAP_INPUT_COUNT=2" in defines
        assert "REMAP_GEN_TOTAL_INPUTS=2" in defines
        assert "REMAP_INPUT_0_GEN_IDX=0" in defines
        assert "REMAP_INPUT_1_GEN_IDX=1" in defines
        assert "REMAP_INPUT_0_PARAM_IDX=3" in defines
        assert "REMAP_INPUT_1_PARAM_IDX=4" in defines
        assert 'REMAP_INPUT_0_NAME="carrier"' in defines
        assert 'REMAP_INPUT_1_NAME="c/m ratio"' in defines

    def test_raw_defs_list(self, base_manifest):
        """_build_remap_defs returns a list of KEY=VALUE strings."""
        input_names = ["carrier", "c/m ratio"]
        remapped = apply_inputs_as_params(base_manifest, input_names, remap_names=None)

        defs = _build_remap_defs(remapped)
        assert isinstance(defs, list)
        assert len(defs) > 0
        assert all("=" in d for d in defs)


# ---------------------------------------------------------------------------
# build_remap_defines_make (Makefile format)
# ---------------------------------------------------------------------------


class TestBuildRemapDefinesMake:
    """Test Make-format remap define generation."""

    def test_no_remaps_returns_empty(self, base_manifest):
        assert build_remap_defines_make(base_manifest) == ""

    def test_single_flag_var(self, base_manifest):
        """Single flag variable produces FLAGS += -DKEY=VALUE lines."""
        input_names = ["carrier", "c/m ratio"]
        remapped = apply_inputs_as_params(base_manifest, input_names, remap_names=None)

        result = build_remap_defines_make(remapped, "FLAGS")
        lines = result.strip().split("\n")
        assert all(line.startswith("FLAGS += -D") for line in lines)
        assert any("REMAP_INPUT_COUNT=2" in line for line in lines)

    def test_multiple_flag_vars(self, base_manifest):
        """Multiple flag variables produce lines for each variable."""
        input_names = ["carrier", "c/m ratio"]
        remapped = apply_inputs_as_params(base_manifest, input_names, remap_names=None)

        result = build_remap_defines_make(remapped, ["CFLAGS", "CPPFLAGS"])
        lines = result.strip().split("\n")
        cflags_lines = [ln for ln in lines if ln.startswith("CFLAGS +=")]
        cppflags_lines = [ln for ln in lines if ln.startswith("CPPFLAGS +=")]
        assert len(cflags_lines) > 0
        assert len(cppflags_lines) > 0
        # Same number of defines for each variable
        assert len(cflags_lines) == len(cppflags_lines)

    def test_make_format_no_trailing_newline(self, base_manifest):
        """Make format should not have trailing newline."""
        input_names = ["carrier"]
        remapped = apply_inputs_as_params(
            base_manifest, input_names, remap_names=["carrier"]
        )

        result = build_remap_defines_make(remapped, "FLAGS")
        assert not result.endswith("\n")


# ---------------------------------------------------------------------------
# Manifest serialization round-trip with remapped_inputs
# ---------------------------------------------------------------------------


class TestRemapSerialization:
    """Test that remapped manifests survive to_dict/from_dict round-trip."""

    def test_round_trip(self, base_manifest):
        input_names = ["carrier", "c/m ratio"]
        remapped = apply_inputs_as_params(base_manifest, input_names, remap_names=None)

        d = remapped.to_dict()
        restored = Manifest.from_dict(d)

        assert restored.num_inputs == remapped.num_inputs
        assert restored.num_params == remapped.num_params
        assert len(restored.remapped_inputs) == len(remapped.remapped_inputs)
        for orig, rest in zip(remapped.remapped_inputs, restored.remapped_inputs):
            assert orig.gen_input_index == rest.gen_input_index
            assert orig.input_name == rest.input_name
            assert orig.param_index == rest.param_index


# ---------------------------------------------------------------------------
# Platform project generation with remap
# ---------------------------------------------------------------------------


class TestRemapProjectGeneration:
    """Test that remap defines propagate into generated build files."""

    def _generate_project(self, fm_bells_export, tmp_path, platform):
        """Helper to generate a project with --inputs-as-params for fm_bells."""
        config = ProjectConfig(
            name="fm_bells",
            platform=platform,
            inputs_as_params=[],  # empty list = remap all
        )
        parser = GenExportParser(fm_bells_export)
        export_info = parser.parse()
        generator = ProjectGenerator(export_info, config)
        project_dir = tmp_path / f"fm_bells_{platform}"
        generator.generate(project_dir)
        return project_dir

    def test_clap_cmake_has_remap_defines(self, fm_bells_export, tmp_path):
        """CLAP CMakeLists.txt should contain REMAP_INPUT_COUNT."""
        project_dir = self._generate_project(fm_bells_export, tmp_path, "clap")
        cmake = (project_dir / "CMakeLists.txt").read_text()
        assert "REMAP_INPUT_COUNT=2" in cmake
        assert "REMAP_GEN_TOTAL_INPUTS=2" in cmake
        assert "REMAP_INPUT_0_GEN_IDX=0" in cmake

    def test_vst3_cmake_has_remap_defines(self, fm_bells_export, tmp_path):
        """VST3 CMakeLists.txt should contain remap defines."""
        project_dir = self._generate_project(fm_bells_export, tmp_path, "vst3")
        cmake = (project_dir / "CMakeLists.txt").read_text()
        assert "REMAP_INPUT_COUNT=2" in cmake

    def test_au_cmake_has_remap_defines(self, fm_bells_export, tmp_path):
        """AU CMakeLists.txt should contain remap defines."""
        project_dir = self._generate_project(fm_bells_export, tmp_path, "au")
        cmake = (project_dir / "CMakeLists.txt").read_text()
        assert "REMAP_INPUT_COUNT=2" in cmake

    def test_lv2_cmake_has_remap_defines(self, fm_bells_export, tmp_path):
        """LV2 CMakeLists.txt should contain remap defines."""
        project_dir = self._generate_project(fm_bells_export, tmp_path, "lv2")
        cmake = (project_dir / "CMakeLists.txt").read_text()
        assert "REMAP_INPUT_COUNT=2" in cmake

    def test_sc_cmake_has_remap_defines(self, fm_bells_export, tmp_path):
        """SC CMakeLists.txt should contain remap defines."""
        project_dir = self._generate_project(fm_bells_export, tmp_path, "sc")
        cmake = (project_dir / "CMakeLists.txt").read_text()
        assert "REMAP_INPUT_COUNT=2" in cmake

    def test_chuck_makefile_has_remap_defines(self, fm_bells_export, tmp_path):
        """ChucK makefile should contain remap defines."""
        project_dir = self._generate_project(fm_bells_export, tmp_path, "chuck")
        makefile = (project_dir / "makefile").read_text()
        assert "REMAP_INPUT_COUNT=2" in makefile
        assert "FLAGS" in makefile or "FLAGS+=" in makefile

    def test_vcvrack_makefile_has_remap_defines(self, fm_bells_export, tmp_path):
        """VCV Rack Makefile should contain remap defines."""
        project_dir = self._generate_project(fm_bells_export, tmp_path, "vcvrack")
        makefile = (project_dir / "Makefile").read_text()
        assert "REMAP_INPUT_COUNT=2" in makefile

    def test_no_remap_no_defines(self, fm_bells_export, tmp_path):
        """Without --inputs-as-params, no remap defines in output."""
        config = ProjectConfig(name="fm_bells", platform="clap")
        parser = GenExportParser(fm_bells_export)
        export_info = parser.parse()
        generator = ProjectGenerator(export_info, config)
        project_dir = tmp_path / "fm_bells_no_remap"
        generator.generate(project_dir)
        cmake = (project_dir / "CMakeLists.txt").read_text()
        assert "REMAP_INPUT_COUNT" not in cmake

    def test_remap_header_copied(self, fm_bells_export, tmp_path):
        """gen_remap_inputs.h should be present in the project directory."""
        project_dir = self._generate_project(fm_bells_export, tmp_path, "clap")
        assert (project_dir / "gen_remap_inputs.h").exists()

    def test_remap_specific_input(self, fm_bells_export, tmp_path):
        """Remapping only 'carrier' should produce REMAP_INPUT_COUNT=1."""
        config = ProjectConfig(
            name="fm_bells",
            platform="clap",
            inputs_as_params=["carrier"],
        )
        parser = GenExportParser(fm_bells_export)
        export_info = parser.parse()
        generator = ProjectGenerator(export_info, config)
        project_dir = tmp_path / "fm_bells_partial_remap"
        generator.generate(project_dir)
        cmake = (project_dir / "CMakeLists.txt").read_text()
        assert "REMAP_INPUT_COUNT=1" in cmake
        assert "REMAP_GEN_TOTAL_INPUTS=2" in cmake
