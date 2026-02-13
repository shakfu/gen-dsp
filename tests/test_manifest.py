"""Tests for the Manifest IR and parameter parsing."""

import json
from pathlib import Path


from gen_dsp.core.manifest import (
    Manifest,
    ParamInfo,
    manifest_from_export_info,
    parse_params_from_export,
)
from gen_dsp.core.parser import GenExportParser
from gen_dsp.core.project import ProjectGenerator, ProjectConfig


class TestParamInfoSerialization:
    """Test ParamInfo to_dict / from_dict round-trips."""

    def test_round_trip(self):
        p = ParamInfo(
            index=3,
            name="bandwidth",
            has_minmax=True,
            min=0.0,
            max=1.0,
            default=0.0,
        )
        d = p.to_dict()
        p2 = ParamInfo.from_dict(d)
        assert p2.index == p.index
        assert p2.name == p.name
        assert p2.has_minmax == p.has_minmax
        assert p2.min == p.min
        assert p2.max == p.max
        assert p2.default == p.default

    def test_dict_keys(self):
        p = ParamInfo(
            index=0, name="x", has_minmax=False, min=0.0, max=1.0, default=0.0
        )
        d = p.to_dict()
        assert set(d.keys()) == {"index", "name", "has_minmax", "min", "max", "default"}


class TestManifestSerialization:
    """Test Manifest to_dict / from_dict / to_json / from_json round-trips."""

    def _make_manifest(self) -> Manifest:
        return Manifest(
            gen_name="gen_exported",
            num_inputs=2,
            num_outputs=2,
            params=[
                ParamInfo(
                    index=0,
                    name="bandwidth",
                    has_minmax=True,
                    min=0.0,
                    max=1.0,
                    default=0.0,
                ),
                ParamInfo(
                    index=1,
                    name="revtime",
                    has_minmax=True,
                    min=0.1,
                    max=1.0,
                    default=0.1,
                ),
            ],
            buffers=["sample"],
            source="gen~",
            version="0.8.0",
        )

    def test_num_params_property(self):
        m = self._make_manifest()
        assert m.num_params == 2

    def test_num_params_empty(self):
        m = Manifest(gen_name="x", num_inputs=0, num_outputs=1)
        assert m.num_params == 0

    def test_dict_round_trip(self):
        m = self._make_manifest()
        d = m.to_dict()
        m2 = Manifest.from_dict(d)
        assert m2.gen_name == m.gen_name
        assert m2.num_inputs == m.num_inputs
        assert m2.num_outputs == m.num_outputs
        assert m2.num_params == m.num_params
        assert len(m2.params) == len(m.params)
        assert m2.buffers == m.buffers
        assert m2.source == m.source
        assert m2.version == m.version

    def test_json_round_trip(self):
        m = self._make_manifest()
        j = m.to_json()
        m2 = Manifest.from_json(j)
        assert m2.gen_name == m.gen_name
        assert m2.num_params == m.num_params
        assert m2.params[1].name == "revtime"
        assert m2.params[1].min == 0.1

    def test_json_is_valid(self):
        m = self._make_manifest()
        j = m.to_json()
        parsed = json.loads(j)
        assert parsed["gen_name"] == "gen_exported"
        assert len(parsed["params"]) == 2
        # num_params should NOT be in the JSON (derived property)
        assert "num_params" not in parsed

    def test_from_dict_defaults(self):
        """Minimal dict should produce valid Manifest with defaults."""
        d = {"gen_name": "test", "num_inputs": 1, "num_outputs": 1}
        m = Manifest.from_dict(d)
        assert m.params == []
        assert m.buffers == []
        assert m.source == "gen~"
        assert m.version == "0.8.0"


class TestParamParsing:
    """Test parameter metadata extraction from gen~ exports.

    Migrated from TestScParamParsing and TestLv2ParamParsing.
    """

    def test_parse_gigaverb_params(self, gigaverb_export: Path):
        """Test parsing parameters from gigaverb (8 params)."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        params = parse_params_from_export(export_info)

        assert len(params) == 8
        # Check first param
        assert params[0].index == 0
        assert params[0].name == "bandwidth"
        # Check last param
        assert params[7].index == 7
        assert params[7].name == "tail"
        # All gigaverb params have hasminmax=true
        for p in params:
            assert p.has_minmax is True
            assert p.max >= p.min
        # Spot-check: revtime has min=0.1, others have min=0
        assert params[0].min == 0.0  # bandwidth
        assert params[0].max == 1.0
        revtime = next(p for p in params if p.name == "revtime")
        assert revtime.min == 0.1
        assert revtime.max == 1.0

    def test_parse_spectraldelayfb_params(self, spectraldelayfb_export: Path):
        """Test parsing parameters from spectraldelayfb (0 params)."""
        parser = GenExportParser(spectraldelayfb_export)
        export_info = parser.parse()

        params = parse_params_from_export(export_info)

        assert len(params) == 0

    def test_parse_params_sorted_by_index(self, gigaverb_export: Path):
        """Test that parsed params are sorted by index."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        params = parse_params_from_export(export_info)

        indices = [p.index for p in params]
        assert indices == sorted(indices)

    def test_param_names_are_valid_identifiers(self, gigaverb_export: Path):
        """Test that parsed param names are usable as identifiers."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        params = parse_params_from_export(export_info)

        for p in params:
            assert p.name.isidentifier(), f"{p.name} is not a valid identifier"

    def test_defaults_clamped_to_range(self, gigaverb_export: Path):
        """Test that defaults are clamped to [min, max] range."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        params = parse_params_from_export(export_info)

        for p in params:
            assert p.min <= p.default <= p.max, (
                f"{p.name}: default {p.default} outside [{p.min}, {p.max}]"
            )

    def test_defaults_from_gen_export(self, gigaverb_export: Path):
        """Test that defaults reflect actual gen~ initial values."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        params = parse_params_from_export(export_info)
        by_name = {p.name: p for p in params}

        # Known gigaverb initial values (from reset() in gen_exported.cpp)
        # Values that exceed range are clamped: revtime init=11 -> max=1,
        # roomsize init=75 -> max=300, spread init=23 -> max=100
        assert by_name["bandwidth"].default == 0.5
        assert by_name["damping"].default == 0.7
        assert by_name["dry"].default == 1.0
        assert by_name["early"].default == 0.25
        assert by_name["revtime"].default == 1.0  # init=11, clamped to max=1
        assert by_name["roomsize"].default == 75.0  # init=75, within [0.1, 300]
        assert by_name["spread"].default == 23.0  # init=23, within [0, 100]
        assert by_name["tail"].default == 0.25


class TestManifestFromExportInfo:
    """Test manifest_from_export_info() integration."""

    def test_gigaverb_manifest(self, gigaverb_export: Path):
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        manifest = manifest_from_export_info(export_info, [], "0.8.0")

        assert manifest.gen_name == "gen_exported"
        assert manifest.num_inputs == 2
        assert manifest.num_outputs == 2
        assert manifest.num_params == 8
        assert len(manifest.params) == 8
        assert manifest.buffers == []
        assert manifest.source == "gen~"
        assert manifest.version == "0.8.0"

    def test_rampleplayer_manifest_with_buffers(self, rampleplayer_export: Path):
        parser = GenExportParser(rampleplayer_export)
        export_info = parser.parse()

        manifest = manifest_from_export_info(export_info, ["sample"], "0.8.0")

        assert manifest.num_inputs == 1
        assert manifest.num_outputs == 2
        assert manifest.buffers == ["sample"]

    def test_spectraldelayfb_manifest(self, spectraldelayfb_export: Path):
        parser = GenExportParser(spectraldelayfb_export)
        export_info = parser.parse()

        manifest = manifest_from_export_info(export_info, [], "0.8.0")

        assert manifest.num_inputs == 3
        assert manifest.num_outputs == 2
        assert manifest.num_params == 0
        assert manifest.params == []

    def test_manifest_json_round_trip(self, gigaverb_export: Path):
        """Build manifest from export, serialize to JSON, deserialize, compare."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        m1 = manifest_from_export_info(export_info, [], "0.8.0")
        j = m1.to_json()
        m2 = Manifest.from_json(j)

        assert m2.gen_name == m1.gen_name
        assert m2.num_params == m1.num_params
        assert m2.params[0].name == m1.params[0].name


class TestManifestJsonEmission:
    """Test that manifest.json is emitted during project generation."""

    def test_manifest_json_emitted(self, gigaverb_export: Path, tmp_project: Path):
        """Verify manifest.json appears in generated project."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="clap")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        manifest_path = project_dir / "manifest.json"
        assert manifest_path.is_file()

        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert data["gen_name"] == "gen_exported"
        assert data["num_inputs"] == 2
        assert data["num_outputs"] == 2
        assert len(data["params"]) == 8
        assert data["buffers"] == []
        assert data["source"] == "gen~"

    def test_manifest_json_with_buffers(
        self, rampleplayer_export: Path, tmp_project: Path
    ):
        """Verify manifest.json includes buffers when present."""
        parser = GenExportParser(rampleplayer_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testsampler", platform="clap", buffers=["sample"])
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        data = json.loads((project_dir / "manifest.json").read_text(encoding="utf-8"))
        assert data["buffers"] == ["sample"]
