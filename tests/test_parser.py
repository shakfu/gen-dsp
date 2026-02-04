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
