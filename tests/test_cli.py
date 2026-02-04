"""Tests for gen_dsp.cli module."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from gen_dsp.cli import main, create_parser


class TestCreateParser:
    """Tests for create_parser function."""

    def test_parser_has_version(self):
        """Test parser has version argument."""
        parser = create_parser()
        # This should not raise
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["--version"])
        assert exc_info.value.code == 0

    def test_parser_has_subcommands(self):
        """Test parser has expected subcommands."""
        parser = create_parser()
        # Test that subcommands are recognized
        args = parser.parse_args(["init", ".", "-n", "test"])
        assert args.command == "init"

        args = parser.parse_args(["build", "."])
        assert args.command == "build"

        args = parser.parse_args(["detect", "."])
        assert args.command == "detect"

        args = parser.parse_args(["patch", "."])
        assert args.command == "patch"


class TestInitCommand:
    """Tests for init command."""

    def test_init_dry_run(self, gigaverb_export: Path, tmp_path: Path, capsys):
        """Test init command with --dry-run."""
        output_dir = tmp_path / "output"
        result = main([
            "init",
            str(gigaverb_export),
            "-n", "testverb",
            "-o", str(output_dir),
            "--dry-run",
        ])

        assert result == 0
        captured = capsys.readouterr()
        assert "Would create project" in captured.out
        assert not output_dir.exists()

    def test_init_creates_project(self, gigaverb_export: Path, tmp_path: Path):
        """Test init command creates project."""
        output_dir = tmp_path / "testverb"
        result = main([
            "init",
            str(gigaverb_export),
            "-n", "testverb",
            "-o", str(output_dir),
        ])

        assert result == 0
        assert output_dir.is_dir()
        assert (output_dir / "Makefile").is_file()
        assert (output_dir / "gen").is_dir()

    def test_init_with_buffers(self, gigaverb_export: Path, tmp_path: Path):
        """Test init command with explicit buffers."""
        output_dir = tmp_path / "testverb"
        result = main([
            "init",
            str(gigaverb_export),
            "-n", "testverb",
            "-o", str(output_dir),
            "--buffers", "buf1", "buf2",
        ])

        assert result == 0
        buffer_h = (output_dir / "gen_buffer.h").read_text()
        assert "WRAPPER_BUFFER_COUNT 2" in buffer_h
        assert "WRAPPER_BUFFER_NAME_0 buf1" in buffer_h
        assert "WRAPPER_BUFFER_NAME_1 buf2" in buffer_h

    def test_init_invalid_name(self, gigaverb_export: Path, tmp_path: Path, capsys):
        """Test init command with invalid name."""
        result = main([
            "init",
            str(gigaverb_export),
            "-n", "123invalid",
            "-o", str(tmp_path / "output"),
        ])

        assert result == 1
        captured = capsys.readouterr()
        assert "not a valid C identifier" in captured.err

    def test_init_invalid_export_path(self, tmp_path: Path, capsys):
        """Test init command with non-existent export path."""
        result = main([
            "init",
            str(tmp_path / "nonexistent"),
            "-n", "test",
        ])

        assert result == 1
        captured = capsys.readouterr()
        assert "Error" in captured.err


class TestDetectCommand:
    """Tests for detect command."""

    def test_detect_text_output(self, gigaverb_export: Path, capsys):
        """Test detect command text output."""
        result = main(["detect", str(gigaverb_export)])

        assert result == 0
        captured = capsys.readouterr()
        assert "gen_exported" in captured.out
        assert "Signal inputs:" in captured.out
        assert "Signal outputs:" in captured.out

    def test_detect_json_output(self, gigaverb_export: Path, capsys):
        """Test detect command JSON output."""
        result = main(["detect", str(gigaverb_export), "--json"])

        assert result == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["name"] == "gen_exported"
        assert "num_inputs" in data
        assert "num_outputs" in data
        assert "buffers" in data

    def test_detect_with_buffers(self, rampleplayer_export: Path, capsys):
        """Test detect command with export that has buffers."""
        result = main(["detect", str(rampleplayer_export), "--json"])

        assert result == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "sample" in data["buffers"]

    def test_detect_invalid_path(self, tmp_path: Path, capsys):
        """Test detect command with invalid path."""
        result = main(["detect", str(tmp_path / "nonexistent")])

        assert result == 1
        captured = capsys.readouterr()
        assert "Error" in captured.err


class TestPatchCommand:
    """Tests for patch command."""

    def test_patch_dry_run(self, gigaverb_export: Path, capsys):
        """Test patch command with --dry-run."""
        result = main(["patch", str(gigaverb_export), "--dry-run"])

        assert result == 0
        # Output depends on whether patches are needed

    def test_patch_invalid_path(self, tmp_path: Path, capsys):
        """Test patch command with invalid path."""
        result = main(["patch", str(tmp_path / "nonexistent")])

        assert result == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err


class TestBuildCommand:
    """Tests for build command."""

    def test_build_invalid_path(self, tmp_path: Path, capsys):
        """Test build command with invalid path."""
        result = main(["build", str(tmp_path / "nonexistent")])

        assert result == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err

    def test_build_no_makefile(self, tmp_path: Path, capsys):
        """Test build command with directory lacking Makefile."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        result = main(["build", str(empty_dir)])

        assert result == 1
        captured = capsys.readouterr()
        assert "Makefile" in captured.err or "Error" in captured.err


class TestMainNoCommand:
    """Tests for main with no command."""

    def test_no_command_shows_help(self, capsys):
        """Test that running without command shows help."""
        result = main([])
        assert result == 0
        captured = capsys.readouterr()
        assert "usage:" in captured.out.lower() or "gen-dsp" in captured.out
