"""Tests for gen_dsp.core.parser module."""

from pathlib import Path

import pytest

from gen_dsp.core.parser import GenExportParser, ExportInfo
from gen_dsp.errors import ParseError


class TestGenExportParser:
    """Tests for GenExportParser class."""

    def test_parse_gigaverb_export(self, gigaverb_export: Path):
        """Test parsing gigaverb export (no buffers)."""
        parser = GenExportParser(gigaverb_export)
        info = parser.parse()

        assert info.name == "gen_exported"
        assert info.num_inputs == 2  # Stereo input
        assert info.num_outputs == 2
        assert info.num_params == 8
        assert info.buffers == []  # No buffers
        assert info.cpp_path is not None
        assert info.cpp_path.exists()
        assert info.h_path is not None
        assert info.h_path.exists()

    def test_parse_rampleplayer_export(self, rampleplayer_export: Path):
        """Test parsing RamplePlayer export (has buffer)."""
        parser = GenExportParser(rampleplayer_export)
        info = parser.parse()

        assert info.name == "RamplePlayer"
        assert info.num_inputs == 1
        assert info.num_outputs == 2
        assert info.num_params == 0
        assert "sample" in info.buffers
        assert len(info.buffers) >= 1

    def test_parse_spectraldelayfb_export(self, spectraldelayfb_export: Path):
        """Test parsing spectraldelayfb export."""
        parser = GenExportParser(spectraldelayfb_export)
        info = parser.parse()

        assert info.name == "gen_exported"
        assert info.num_inputs > 0
        assert info.num_outputs > 0

    def test_parse_fm_bells_export(self, fm_bells_export: Path):
        """Test parsing fm_bells export (no buffers, 2in/2out, 3 params)."""
        parser = GenExportParser(fm_bells_export)
        info = parser.parse()

        assert info.name == "gen_exported"
        assert info.num_inputs == 2
        assert info.num_outputs == 2
        assert info.num_params == 3
        assert info.buffers == []
        assert info.has_exp2f_issue is True

    def test_parse_slicer_export(self, slicer_export: Path):
        """Test parsing slicer export (Data member buffer, 1in/1out)."""
        parser = GenExportParser(slicer_export)
        info = parser.parse()

        assert info.name == "gen_exported"
        assert info.num_inputs == 1
        assert info.num_outputs == 1
        assert info.num_params == 3
        assert "storage" in info.buffers
        assert len(info.buffers) == 1

    def test_parse_invalid_path_raises_error(self, tmp_path: Path):
        """Test that parsing non-existent path raises ParseError."""
        with pytest.raises(ParseError, match="not a directory"):
            GenExportParser(tmp_path / "nonexistent")

    def test_parse_empty_dir_raises_error(self, tmp_path: Path):
        """Test that parsing empty directory raises ParseError."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        with pytest.raises(ParseError, match="No gen~ export"):
            parser = GenExportParser(empty_dir)
            parser.parse()

    def test_validate_buffer_names_valid(self, gigaverb_export: Path):
        """Test buffer name validation with valid names."""
        parser = GenExportParser(gigaverb_export)
        invalid = parser.validate_buffer_names(["sample", "buffer1", "_test"])
        assert invalid == []

    def test_validate_buffer_names_invalid(self, gigaverb_export: Path):
        """Test buffer name validation with invalid names."""
        parser = GenExportParser(gigaverb_export)
        invalid = parser.validate_buffer_names(["123invalid", "has space", "has-dash"])
        assert len(invalid) == 3
        assert "123invalid" in invalid
        assert "has space" in invalid
        assert "has-dash" in invalid


class TestExportInfo:
    """Tests for ExportInfo dataclass."""

    def test_export_info_defaults(self):
        """Test ExportInfo default values."""
        info = ExportInfo(name="test", path=Path("."))
        assert info.num_inputs == 0
        assert info.num_outputs == 0
        assert info.num_params == 0
        assert info.buffers == []
        assert info.has_exp2f_issue is False
        assert info.cpp_path is None
        assert info.h_path is None
        assert info.genlib_ops_path is None


class TestBufferDetection:
    """Unit tests for buffer detection (core/parser._detect_buffers)."""

    def _parser(self) -> GenExportParser:
        # _detect_buffers is a pure function of the C++ text; bypass __init__
        # (which requires a real export directory).
        return GenExportParser.__new__(GenExportParser)

    def test_codebox_data_args_not_overcounted(self):
        """Regression for issue #6: codebox functions that take ``Data`` buffers
        as arguments must not inflate the count. The real ``Data`` members are
        authoritative; the function-argument aliases (accessed via ``.read``)
        are ignored.
        """
        content = """
        struct State {
            Data m_xn1;
            Data m_Fn1;
            void reset() {
                m_xn1.reset("xn1", 4);
                m_Fn1.reset("Fn1", 4);
            }
            double myfunction(Data& xn1_arg, Data& Fn1_arg) {
                double a = xn1_arg.read(0);
                double b = Fn1_arg.read(0);
                return a + b;
            }
        };
        """
        # Two real buffers, not four (xn1_arg / Fn1_arg are aliases).
        assert self._parser()._detect_buffers(content) == ["Fn1", "xn1"]

    def test_data_members_authoritative_over_access_patterns(self):
        """With ``Data`` members present, the access-pattern fallback is skipped
        (so aliases accessed via ``.read`` are not added).
        """
        content = """
        Data m_buf;
        void reset() { m_buf.reset("buf", 8); }
        double f(Data& alias) { return alias.read(0); }
        """
        assert self._parser()._detect_buffers(content) == ["buf"]

    def test_access_pattern_fallback(self):
        """Exports with no ``Data``/.reset members fall back to access patterns."""
        content = "a = sample.dim; b = sample.read(0); c = table.channels;"
        assert self._parser()._detect_buffers(content) == ["sample", "table"]
