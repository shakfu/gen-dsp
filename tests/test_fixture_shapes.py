"""Parser/manifest coverage for DSP shapes the main fixtures do not exercise.

The real gen~ exports (gigaverb, RamplePlayer, spectraldelayfb) cover stereo
effects and a single-buffer player, but leave gaps the graph frontend hits in
practice: mono (1-in/1-out), high channel counts, multiple buffers, and
zero-parameter effects. These tests run the minimal hand-authored fixtures
(see tests/fixtures/{mono_gain,multitap,octoverb}) through the parser and the
manifest IR to pin those shapes.
"""

from pathlib import Path

from gen_dsp.core.manifest import manifest_from_export_info
from gen_dsp.core.parser import GenExportParser
from gen_dsp.version import __version__


def _manifest(export: Path):
    info = GenExportParser(export).parse()
    return info, manifest_from_export_info(info, info.buffers, __version__)


class TestMonoShape:
    """1-in/1-out export with a single ranged parameter."""

    def test_parse_io_and_params(self, mono_gain_export: Path):
        info = GenExportParser(mono_gain_export).parse()
        assert info.name == "mono_gain"
        assert info.num_inputs == 1
        assert info.num_outputs == 1
        assert info.num_params == 1
        assert info.buffers == []

    def test_manifest_param_metadata(self, mono_gain_export: Path):
        _, m = _manifest(mono_gain_export)
        assert m.num_inputs == 1 and m.num_outputs == 1
        assert len(m.params) == 1
        gain = m.params[0]
        assert gain.name == "gain"
        assert (gain.min, gain.max) == (0.0, 2.0)
        # Default is read from the reset() initializer and clamped to range.
        assert gain.default == 1.0

    def test_is_effect_not_generator(self, mono_gain_export: Path):
        # 1 input -> effect (auto-detection keys off input count).
        info = GenExportParser(mono_gain_export).parse()
        assert info.num_inputs > 0


class TestMultiBufferZeroParamShape:
    """Export referencing two buffers and declaring no parameters."""

    def test_parse_detects_both_buffers(self, multitap_export: Path):
        info = GenExportParser(multitap_export).parse()
        assert info.buffers == ["tapA", "tapB"]

    def test_zero_parameters(self, multitap_export: Path):
        info, m = _manifest(multitap_export)
        assert info.num_params == 0
        assert m.params == []

    def test_buffers_are_valid_identifiers(self, multitap_export: Path):
        parser = GenExportParser(multitap_export)
        info = parser.parse()
        assert parser.validate_buffer_names(info.buffers) == []

    def test_manifest_carries_buffers(self, multitap_export: Path):
        _, m = _manifest(multitap_export)
        assert m.buffers == ["tapA", "tapB"]


class TestHighChannelCountShape:
    """8-in/8-out export with two parameters."""

    def test_parse_eight_channels(self, octoverb_export: Path):
        info = GenExportParser(octoverb_export).parse()
        assert info.num_inputs == 8
        assert info.num_outputs == 8
        assert len(info.input_names) == 8
        assert info.input_names[0] == "in1"
        assert info.input_names[-1] == "in8"

    def test_manifest_params_sorted_by_index(self, octoverb_export: Path):
        _, m = _manifest(octoverb_export)
        assert [p.name for p in m.params] == ["mix", "size"]
        assert m.params[0].default == 0.5
        assert m.params[1].default == 0.7

    def test_manifest_json_round_trips(self, octoverb_export: Path):
        from gen_dsp.core.manifest import Manifest

        _, m = _manifest(octoverb_export)
        restored = Manifest.from_dict(m.to_dict())
        assert restored.num_inputs == 8
        assert restored.num_outputs == 8
        assert len(restored.params) == 2
