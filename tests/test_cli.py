"""Tests for gen_dsp.cli module."""

import json
from pathlib import Path

import pytest

from gen_dsp.cli import main


class TestVersionAndHelp:
    """Tests for --version and --help."""

    def test_version_flag(self, capsys):
        """Test --version prints version and exits 0."""
        result = main(["--version"])
        assert result == 0
        captured = capsys.readouterr()
        assert "gen-dsp" in captured.out

    def test_short_version_flag(self, capsys):
        """Test -V prints version and exits 0."""
        result = main(["-V"])
        assert result == 0
        captured = capsys.readouterr()
        assert "gen-dsp" in captured.out

    def test_help_flag(self, capsys):
        """Test --help prints help and exits 0."""
        result = main(["--help"])
        assert result == 0
        captured = capsys.readouterr()
        assert "gen-dsp" in captured.out

    def test_no_args_shows_help(self, capsys):
        """Test that running without args shows help."""
        result = main([])
        assert result == 0
        captured = capsys.readouterr()
        assert "gen-dsp" in captured.out


class TestDefaultCommand:
    """Tests for the default command (positional source)."""

    def test_dry_run_export(self, gigaverb_export: Path, tmp_path: Path, capsys):
        """Test dry run with gen~ export directory."""
        output_dir = tmp_path / "output"
        result = main(
            [
                str(gigaverb_export),
                "-p",
                "pd",
                "-n",
                "testverb",
                "-o",
                str(output_dir),
                "--no-build",
                "--dry-run",
            ]
        )

        assert result == 0
        captured = capsys.readouterr()
        assert "Would create project" in captured.out
        assert not output_dir.exists()

    def test_creates_project(self, gigaverb_export: Path, tmp_path: Path):
        """Test default command creates project from export dir."""
        output_dir = tmp_path / "testverb"
        result = main(
            [
                str(gigaverb_export),
                "-p",
                "pd",
                "-n",
                "testverb",
                "-o",
                str(output_dir),
                "--no-build",
            ]
        )

        assert result == 0
        assert output_dir.is_dir()
        assert (output_dir / "Makefile").is_file()
        assert (output_dir / "gen").is_dir()

    def test_with_buffers(self, gigaverb_export: Path, tmp_path: Path):
        """Test with explicit buffers."""
        output_dir = tmp_path / "testverb"
        result = main(
            [
                str(gigaverb_export),
                "-p",
                "pd",
                "-n",
                "testverb",
                "-o",
                str(output_dir),
                "--no-build",
                "--buffers",
                "buf1",
                "buf2",
            ]
        )

        assert result == 0
        buffer_h = (output_dir / "gen_buffer.h").read_text()
        assert "WRAPPER_BUFFER_COUNT 2" in buffer_h
        assert "WRAPPER_BUFFER_NAME_0 buf1" in buffer_h
        assert "WRAPPER_BUFFER_NAME_1 buf2" in buffer_h

    def test_shared_cache_on_by_default(self, gigaverb_export: Path, tmp_path: Path):
        """Test that shared cache is enabled by default for cmake platforms."""
        output_dir = tmp_path / "testverb"
        result = main(
            [
                str(gigaverb_export),
                "-p",
                "clap",
                "-n",
                "testverb",
                "-o",
                str(output_dir),
                "--no-build",
            ]
        )

        assert result == 0
        cmake = (output_dir / "CMakeLists.txt").read_text()
        assert "elseif(ON)" in cmake

    def test_no_shared_cache_disables(self, gigaverb_export: Path, tmp_path: Path):
        """Test --no-shared-cache produces OFF."""
        output_dir = tmp_path / "testverb"
        result = main(
            [
                str(gigaverb_export),
                "-p",
                "clap",
                "-n",
                "testverb",
                "-o",
                str(output_dir),
                "--no-build",
                "--no-shared-cache",
            ]
        )

        assert result == 0
        cmake = (output_dir / "CMakeLists.txt").read_text()
        assert "elseif(OFF)" in cmake

    def test_board_rejects_non_daisy(
        self, gigaverb_export: Path, tmp_path: Path, capsys
    ):
        """Test --board errors for non-daisy platforms."""
        output_dir = tmp_path / "testverb"
        result = main(
            [
                str(gigaverb_export),
                "-p",
                "pd",
                "-n",
                "testverb",
                "-o",
                str(output_dir),
                "--no-build",
                "--board",
                "pod",
            ]
        )

        assert result == 1
        captured = capsys.readouterr()
        assert "--board" in captured.err

    def test_invalid_name(self, gigaverb_export: Path, tmp_path: Path, capsys):
        """Test with invalid name."""
        result = main(
            [
                str(gigaverb_export),
                "-p",
                "pd",
                "-n",
                "123invalid",
                "-o",
                str(tmp_path / "output"),
                "--no-build",
            ]
        )

        assert result == 1
        captured = capsys.readouterr()
        assert "not a valid C identifier" in captured.err

    def test_invalid_export_path(self, tmp_path: Path, capsys):
        """Test with non-existent export path."""
        result = main(
            [
                str(tmp_path / "nonexistent"),
                "-p",
                "pd",
            ]
        )

        assert result == 1
        captured = capsys.readouterr()
        assert "Error" in captured.err


class TestAutoDetect:
    """Tests for source type auto-detection."""

    def test_detects_directory(self, gigaverb_export: Path, tmp_path: Path, capsys):
        """Directory source is detected as gen~ export."""
        result = main(
            [
                str(gigaverb_export),
                "-p",
                "pd",
                "-o",
                str(tmp_path / "out"),
                "--no-build",
                "--dry-run",
            ]
        )
        assert result == 0
        captured = capsys.readouterr()
        assert "Would create project" in captured.out
        assert "Export:" in captured.out

    def test_detects_gdsp_file(self, tmp_path: Path, capsys):
        """'.gdsp' file is detected as graph source."""
        pytest.importorskip("pydantic")
        graph_file = tmp_path / "lowpass.gdsp"
        graph_file.write_text(
            """
            graph lowpass {
                in input
                out output = filt
                param freq 20..20000 = 1000
                filt = onepole(input, freq / 44100)
            }
            """
        )
        result = main(
            [
                str(graph_file),
                "-p",
                "chuck",
                "--no-build",
                "--dry-run",
            ]
        )
        assert result == 0
        captured = capsys.readouterr()
        assert "graph" in captured.out

    def test_detects_json_file(self, tmp_path: Path, capsys):
        """'.json' file is detected as graph source."""
        pytest.importorskip("pydantic")
        graph_file = tmp_path / "test.json"
        data = {
            "name": "test_graph",
            "inputs": [{"id": "in1"}],
            "outputs": [{"id": "out1", "source": "scaled"}],
            "params": [{"name": "gain", "min": 0.0, "max": 2.0, "default": 1.0}],
            "nodes": [{"id": "scaled", "op": "mul", "a": "in1", "b": "gain"}],
        }
        graph_file.write_text(json.dumps(data))
        result = main(
            [
                str(graph_file),
                "-p",
                "pd",
                "--no-build",
                "--dry-run",
            ]
        )
        assert result == 0
        captured = capsys.readouterr()
        assert "graph" in captured.out

    def test_unrecognized_source(self, tmp_path: Path, capsys):
        """Unrecognized source type shows error."""
        bad_file = tmp_path / "something.txt"
        bad_file.write_text("hello")
        result = main(
            [
                str(bad_file),
                "-p",
                "pd",
            ]
        )
        assert result == 1
        captured = capsys.readouterr()
        assert "unrecognized" in captured.err.lower() or "Error" in captured.err


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


class TestProjectMarkerAndAutoDetect:
    """`.gen-dsp.json` marker generation and `build` platform auto-detection."""

    def _make_marker(self, project: Path, **fields) -> None:
        project.mkdir(parents=True, exist_ok=True)
        (project / ".gen-dsp.json").write_text(json.dumps(fields), encoding="utf-8")

    def test_generation_writes_marker(
        self, gigaverb_export: Path, tmp_path: Path
    ):
        out = tmp_path / "proj"
        rc = main(
            [str(gigaverb_export), "-p", "clap", "-n", "gv", "-o", str(out), "--no-build"]
        )
        assert rc == 0
        marker = json.loads((out / ".gen-dsp.json").read_text())
        assert marker["platform"] == "clap"
        assert marker["tool"] == "gen-dsp"
        assert "version" in marker

    def test_detect_helper_reads_platform(self, tmp_path: Path):
        from gen_dsp.core.builder import Builder

        self._make_marker(tmp_path, platform="vst3")
        assert Builder(tmp_path).detect_platform() == "vst3"

    def test_detect_helper_missing_marker(self, tmp_path: Path):
        from gen_dsp.core.builder import Builder

        assert Builder(tmp_path).detect_platform() is None

    def test_detect_helper_unknown_platform(self, tmp_path: Path):
        from gen_dsp.core.builder import Builder

        self._make_marker(tmp_path, platform="not-a-real-platform")
        assert Builder(tmp_path).detect_platform() is None

    def test_detect_helper_malformed_json(self, tmp_path: Path):
        from gen_dsp.core.builder import Builder

        tmp_path.joinpath(".gen-dsp.json").write_text("{ not json", encoding="utf-8")
        assert Builder(tmp_path).detect_platform() is None

    def test_builder_build_auto_detects_when_platform_none(self, tmp_path: Path):
        # Builder.build(None) resolves the platform from the marker -- the value
        # that makes Builder more than a thin get_platform() wrapper.
        from gen_dsp.core.builder import Builder

        self._make_marker(tmp_path, platform="vst3")
        builder = Builder(tmp_path)
        assert builder._resolve_platform(None) == "vst3"
        # No marker -> falls back to pd.
        empty = tmp_path / "empty"
        empty.mkdir()
        assert Builder(empty)._resolve_platform(None) == "pd"

    def test_build_auto_detects_from_marker(self, tmp_path: Path, capsys):
        # No -p given; the marker selects 'clap'. The build then fails (no CMake
        # project present), but the auto-detection message proves clap (not the
        # 'pd' fallback) was chosen.
        self._make_marker(tmp_path, platform="clap")
        rc = main(["build", str(tmp_path)])
        assert rc == 1
        out = capsys.readouterr().out
        assert "Auto-detected platform 'clap'" in out

    def test_explicit_platform_overrides_marker(self, tmp_path: Path, capsys):
        self._make_marker(tmp_path, platform="clap")
        main(["build", str(tmp_path), "-p", "pd"])
        # Explicit -p wins: no auto-detect message emitted.
        assert "Auto-detected" not in capsys.readouterr().out


class TestListCommand:
    """Tests for list command."""

    def test_list_shows_all_platforms(self, capsys):
        """Test list command shows all registered platforms."""
        from gen_dsp.platforms import list_platforms

        result = main(["list"])
        assert result == 0
        captured = capsys.readouterr()
        for platform_name in list_platforms():
            assert platform_name in captured.out

    def test_list_output_one_per_line(self, capsys):
        """Test list outputs one platform per line."""
        result = main(["list"])
        assert result == 0
        captured = capsys.readouterr()
        lines = [line for line in captured.out.strip().split("\n") if line]
        from gen_dsp.platforms import list_platforms

        assert len(lines) == len(list_platforms())

    def test_list_verbose_shows_metadata(self, capsys):
        """`list -v` shows build system, extension, and description per row."""
        from gen_dsp.platforms import get_platform, list_platforms

        result = main(["list", "-v"])
        assert result == 0
        out = capsys.readouterr().out
        # Still one row per platform.
        lines = [line for line in out.strip().split("\n") if line]
        assert len(lines) == len(list_platforms())
        # Each row carries the platform's metadata.
        clap = get_platform("clap")
        assert clap.build_system in out
        assert clap.description in out

    def test_list_json_is_valid_and_complete(self, capsys):
        """`list --json` emits one object per platform with full metadata."""
        from gen_dsp.platforms import list_platforms

        result = main(["list", "--json"])
        assert result == 0
        data = json.loads(capsys.readouterr().out)
        assert {d["name"] for d in data} == set(list_platforms())
        for d in data:
            assert d["build_system"]  # non-empty
            assert d["description"]
            assert "extension" in d

    def test_every_platform_has_description_and_build_system(self):
        """No platform may ship without list metadata."""
        from gen_dsp.platforms import get_platform, list_platforms

        for name in list_platforms():
            p = get_platform(name)
            assert p.description, f"{name} missing description"
            assert p.build_system, f"{name} missing build_system"

    def test_list_boards_daisy(self, capsys):
        """`list --boards daisy` dynamically lists the Daisy board variants."""
        from gen_dsp.platforms.daisy import DAISY_BOARDS

        result = main(["list", "--boards", "daisy"])
        assert result == 0
        lines = [ln for ln in capsys.readouterr().out.strip().split("\n") if ln]
        assert lines == sorted(DAISY_BOARDS)

    def test_list_boards_circle(self, capsys):
        from gen_dsp.platforms.circle.boards import CIRCLE_BOARDS

        result = main(["list", "--boards", "circle"])
        assert result == 0
        lines = [ln for ln in capsys.readouterr().out.strip().split("\n") if ln]
        assert lines == sorted(CIRCLE_BOARDS)

    def test_list_boards_json(self, capsys):
        from gen_dsp.platforms.daisy import DAISY_BOARDS

        result = main(["list", "--boards", "daisy", "--json"])
        assert result == 0
        assert json.loads(capsys.readouterr().out) == sorted(DAISY_BOARDS)

    def test_list_boards_platform_without_boards(self, capsys):
        result = main(["list", "--boards", "clap"])
        assert result == 0
        assert "no board variants" in capsys.readouterr().out

    def test_list_boards_unknown_platform(self, capsys):
        result = main(["list", "--boards", "bogus"])
        assert result == 1
        assert "unknown platform" in capsys.readouterr().err

    def test_list_boards_matches_validation(self):
        """The advertised boards are exactly those `--board` accepts.

        Guards against the help/listing drifting from the validated set.
        """
        from gen_dsp.platforms import get_platform
        from gen_dsp.platforms.daisy import DAISY_BOARDS
        from gen_dsp.platforms.circle.boards import CIRCLE_BOARDS

        assert get_platform("daisy").list_boards() == sorted(DAISY_BOARDS)
        assert get_platform("circle").list_boards() == sorted(CIRCLE_BOARDS)


class TestCacheCommand:
    """Tests for cache command."""

    def test_cache_shows_cache_dir(self, capsys):
        """Test cache command shows cache directory."""
        result = main(["cache"])
        assert result == 0
        captured = capsys.readouterr()
        assert "Cache directory:" in captured.out

    def test_cache_shows_fetchcontent(self, capsys):
        """Test cache command shows FetchContent status."""
        result = main(["cache"])
        assert result == 0
        captured = capsys.readouterr()
        assert "FetchContent" in captured.out
        assert "clap" in captured.out
        assert "vst3" in captured.out

    def test_cache_shows_rack_sdk(self, capsys):
        """Test cache command shows Rack SDK status."""
        result = main(["cache"])
        assert result == 0
        captured = capsys.readouterr()
        assert "Rack SDK" in captured.out

    def test_cache_shows_libdaisy(self, capsys):
        """Test cache command shows libDaisy status."""
        result = main(["cache"])
        assert result == 0
        captured = capsys.readouterr()
        assert "libDaisy" in captured.out


class TestNameInference:
    """Tests for name inference when -n is not provided."""

    def test_infers_name_from_export_dir(
        self, gigaverb_export: Path, tmp_path: Path, capsys
    ):
        """Infers name from export directory name when -n is omitted."""
        output_dir = tmp_path / "output"
        result = main(
            [
                str(gigaverb_export),
                "-p",
                "pd",
                "-o",
                str(output_dir),
                "--no-build",
                "--dry-run",
            ]
        )
        assert result == 0
        captured = capsys.readouterr()
        assert "Would create project" in captured.out

    def test_infers_name_from_graph_file(self, tmp_path: Path, capsys):
        """Infers name from graph file stem."""
        pytest.importorskip("pydantic")
        graph_file = tmp_path / "lowpass.gdsp"
        graph_file.write_text(
            """
            graph lowpass {
                in input
                out output = filt
                param freq 20..20000 = 1000
                filt = onepole(input, freq / 44100)
            }
            """
        )
        result = main(
            [
                str(graph_file),
                "-p",
                "chuck",
                "--no-build",
                "--dry-run",
            ]
        )
        assert result == 0
        captured = capsys.readouterr()
        assert "lowpass" in captured.out

    def test_explicit_name_overrides_inference(
        self, gigaverb_export: Path, tmp_path: Path, capsys
    ):
        """Explicit -n overrides inferred name."""
        output_dir = tmp_path / "output"
        result = main(
            [
                str(gigaverb_export),
                "-p",
                "pd",
                "-n",
                "myverb",
                "-o",
                str(output_dir),
                "--no-build",
                "--dry-run",
            ]
        )
        assert result == 0


class TestOutputDirInference:
    """Tests for default output directory {name}_{platform}."""

    def test_output_dir_includes_platform(
        self, gigaverb_export: Path, tmp_path: Path, capsys, monkeypatch
    ):
        """Default output dir is {name}_{platform}."""
        monkeypatch.chdir(tmp_path)
        result = main(
            [
                str(gigaverb_export),
                "-p",
                "chuck",
                "-n",
                "myverb",
                "--no-build",
                "--dry-run",
            ]
        )
        assert result == 0
        captured = capsys.readouterr()
        assert "myverb_chuck" in captured.out

    def test_graph_output_dir_includes_platform(
        self, tmp_path: Path, capsys, monkeypatch
    ):
        """Graph source default output dir is {stem}_{platform}."""
        pytest.importorskip("pydantic")
        monkeypatch.chdir(tmp_path)
        graph_file = tmp_path / "foo.gdsp"
        graph_file.write_text(
            """
            graph foo {
                in input
                out output = scaled
                param gain 0..2 = 1
                scaled = input * gain
            }
            """
        )
        result = main(
            [
                str(graph_file),
                "-p",
                "au",
                "--no-build",
                "--dry-run",
            ]
        )
        assert result == 0
        captured = capsys.readouterr()
        assert "foo_au" in captured.out


class TestNoBuildFlag:
    """Tests for --no-build flag (reversed polarity from old --build)."""

    def test_dry_run_shows_build_intent(
        self, gigaverb_export: Path, tmp_path: Path, capsys
    ):
        """Dry run without --no-build shows build intent."""
        output_dir = tmp_path / "output"
        result = main(
            [
                str(gigaverb_export),
                "-p",
                "pd",
                "-n",
                "testverb",
                "-o",
                str(output_dir),
                "--dry-run",
            ]
        )
        assert result == 0
        captured = capsys.readouterr()
        assert "Would build after creating" in captured.out
        assert not output_dir.exists()

    def test_no_build_dry_run_omits_build_intent(
        self, gigaverb_export: Path, tmp_path: Path, capsys
    ):
        """Dry run with --no-build does not show build intent."""
        output_dir = tmp_path / "output"
        result = main(
            [
                str(gigaverb_export),
                "-p",
                "pd",
                "-n",
                "testverb",
                "-o",
                str(output_dir),
                "--no-build",
                "--dry-run",
            ]
        )
        assert result == 0
        captured = capsys.readouterr()
        assert "Would build after creating" not in captured.out

    def test_graph_dry_run_shows_build_intent(self, tmp_path: Path, capsys):
        """Graph source dry run without --no-build shows build intent."""
        pytest.importorskip("pydantic")
        graph_file = tmp_path / "gain.gdsp"
        graph_file.write_text(
            """
            graph gain {
                in input
                out output = scaled
                param vol 0..2 = 1
                scaled = input * vol
            }
            """
        )
        result = main(
            [
                str(graph_file),
                "-p",
                "chuck",
                "--dry-run",
            ]
        )
        assert result == 0
        captured = capsys.readouterr()
        assert "Would build after creating" in captured.out


class TestMultiTarget:
    """Multi-target generation: -p a,b,c and -p all."""

    def test_resolve_platforms_single(self):
        from gen_dsp.cli import _resolve_platforms

        platforms, err = _resolve_platforms("clap")
        assert err is None
        assert platforms == ["clap"]

    def test_resolve_platforms_list_dedupes_in_order(self):
        from gen_dsp.cli import _resolve_platforms

        platforms, err = _resolve_platforms("vst3,clap,vst3")
        assert err is None
        assert platforms == ["vst3", "clap"]

    def test_resolve_platforms_all(self):
        from gen_dsp.cli import _resolve_platforms
        from gen_dsp.platforms import list_platforms

        platforms, err = _resolve_platforms("all")
        assert err is None
        assert platforms == list_platforms()

    def test_resolve_platforms_invalid(self):
        from gen_dsp.cli import _resolve_platforms

        platforms, err = _resolve_platforms("clap,bogus")
        assert platforms == []
        assert err is not None and "bogus" in err

    def test_multi_target_creates_per_platform_dirs(
        self, gigaverb_export: Path, tmp_path: Path
    ):
        out = tmp_path / "out"
        result = main(
            [
                str(gigaverb_export),
                "-n",
                "gv",
                "-p",
                "pd,chuck",
                "-o",
                str(out),
                "--no-build",
            ]
        )
        assert result == 0
        assert (out / "gv_pd").is_dir()
        assert (out / "gv_chuck").is_dir()

    def test_multi_target_summary_and_backward_compat(
        self, gigaverb_export: Path, tmp_path: Path, capsys
    ):
        # Single platform: no summary block (output unchanged).
        main(
            [
                str(gigaverb_export),
                "-n",
                "gv",
                "-p",
                "pd",
                "-o",
                str(tmp_path / "single"),
                "--no-build",
            ]
        )
        assert "Summary:" not in capsys.readouterr().out

        # Multiple platforms: summary block present, one line per target.
        main(
            [
                str(gigaverb_export),
                "-n",
                "gv",
                "-p",
                "pd,chuck",
                "-o",
                str(tmp_path / "multi"),
                "--no-build",
            ]
        )
        out = capsys.readouterr().out
        assert "Summary:" in out
        assert "=== pd ===" in out and "=== chuck ===" in out

    def test_multi_target_dry_run_creates_nothing(
        self, gigaverb_export: Path, tmp_path: Path, capsys
    ):
        out = tmp_path / "out"
        result = main(
            [
                str(gigaverb_export),
                "-n",
                "gv",
                "-p",
                "pd,chuck",
                "-o",
                str(out),
                "--dry-run",
            ]
        )
        assert result == 0
        assert not (out / "gv_pd").exists()
        assert "Would create project at:" in capsys.readouterr().out

    def test_invalid_platform_in_list_errors(
        self, gigaverb_export: Path, tmp_path: Path, capsys
    ):
        result = main(
            [
                str(gigaverb_export),
                "-n",
                "gv",
                "-p",
                "pd,bogus",
                "-o",
                str(tmp_path / "out"),
                "--no-build",
            ]
        )
        assert result == 1
        assert "bogus" in capsys.readouterr().err

    def test_board_allowed_when_any_embedded(
        self, gigaverb_export: Path, tmp_path: Path, capsys
    ):
        # --board with a mix incl. daisy must not error; board applies to daisy only.
        result = main(
            [
                str(gigaverb_export),
                "-n",
                "gv",
                "-p",
                "pd,daisy",
                "--board",
                "seed",
                "-o",
                str(tmp_path / "out"),
                "--dry-run",
            ]
        )
        assert result == 0
        out = capsys.readouterr().out
        assert "Board: seed" in out  # shown for daisy

    def test_board_rejected_when_no_embedded(
        self, gigaverb_export: Path, tmp_path: Path, capsys
    ):
        result = main(
            [
                str(gigaverb_export),
                "-n",
                "gv",
                "-p",
                "pd,clap",
                "--board",
                "seed",
                "-o",
                str(tmp_path / "out"),
                "--dry-run",
            ]
        )
        assert result == 1
        assert "--board is only valid" in capsys.readouterr().err


class TestConfigFile:
    """gen-dsp.toml config support for the default command."""

    def test_load_config_maps_keys(self, tmp_path: Path):
        from gen_dsp.cli import _load_config

        cfg = tmp_path / "gen-dsp.toml"
        cfg.write_text(
            'source = "exp"\n'
            'platform = ["clap", "vst3"]\n'
            'name = "gv"\n'
            'buffers = ["sample"]\n'
            "voices = 2\n"
            "no-build = true\n"
            "inputs-as-params = true\n"
        )
        mapped, err = _load_config(cfg)
        assert err is None
        assert mapped["platform"] == "clap,vst3"
        assert mapped["name"] == "gv"
        assert mapped["buffers"] == ["sample"]
        assert mapped["voices"] == 2
        assert mapped["no_build"] is True
        assert mapped["inputs_as_params"] == []
        assert isinstance(mapped["source"], Path)

    def test_config_unknown_key(self, tmp_path: Path):
        from gen_dsp.cli import _load_config

        cfg = tmp_path / "gen-dsp.toml"
        cfg.write_text('platform = "pd"\nbogus = 1\n')
        _, err = _load_config(cfg)
        assert err is not None and "bogus" in err

    def test_config_bad_type(self, tmp_path: Path):
        from gen_dsp.cli import _load_config

        cfg = tmp_path / "gen-dsp.toml"
        cfg.write_text('platform = "pd"\nvoices = "two"\n')
        _, err = _load_config(cfg)
        assert err is not None and "voices" in err

    def test_config_provides_source_and_platform(
        self, gigaverb_export: Path, tmp_path: Path
    ):
        cfg = tmp_path / "gen-dsp.toml"
        cfg.write_text(
            f'source = "{gigaverb_export}"\n'
            'platform = "pd"\n'
            'name = "gv"\n'
            "no-build = true\n"
        )
        out = tmp_path / "out"
        result = main(["--config", str(cfg), "-o", str(out)])
        assert result == 0
        assert (out / "gv.cpp").exists() or (out).is_dir()

    def test_cli_overrides_config(self, gigaverb_export: Path, tmp_path: Path, capsys):
        cfg = tmp_path / "gen-dsp.toml"
        cfg.write_text(
            f'source = "{gigaverb_export}"\n'
            'platform = "pd,chuck"\n'
            'name = "gv"\n'
            "no-build = true\n"
        )
        # CLI -p clap should win over config's pd,chuck (single target, no summary).
        result = main(["--config", str(cfg), "-p", "clap", "-o", str(tmp_path / "o")])
        assert result == 0
        out = capsys.readouterr().out
        assert "Platform: clap" in out
        assert "Summary:" not in out

    def test_missing_source_errors(self, tmp_path: Path, capsys):
        cfg = tmp_path / "gen-dsp.toml"
        cfg.write_text('platform = "pd"\nno-build = true\n')
        result = main(["--config", str(cfg)])
        assert result == 1
        assert "no source given" in capsys.readouterr().err

    def test_config_not_found(self, tmp_path: Path, capsys):
        result = main(["--config", str(tmp_path / "nope.toml")])
        assert result == 1
        assert "not found" in capsys.readouterr().err

    def test_auto_load_cwd_config(
        self, gigaverb_export: Path, tmp_path: Path, monkeypatch
    ):
        cfg = tmp_path / "gen-dsp.toml"
        cfg.write_text(
            f'source = "{gigaverb_export}"\n'
            'platform = "pd"\n'
            'name = "gv"\n'
            "no-build = true\n"
        )
        monkeypatch.chdir(tmp_path)
        # Bare invocation picks up ./gen-dsp.toml.
        result = main([])
        assert result == 0
        assert (tmp_path / "build" / "gv_pd").is_dir()


class TestDetectGraph:
    """`gen-dsp detect` on graph files (parity with gen~ export detection)."""

    import json as _json

    _GAIN = {
        "name": "t",
        "inputs": [{"id": "in1"}],
        "outputs": [{"id": "out1", "source": "sc"}],
        "params": [{"name": "vol", "min": 0.0, "max": 1.0, "default": 0.5}],
        "nodes": [{"op": "mul", "id": "sc", "a": "in1", "b": "vol"}],
    }

    def _write(self, tmp_path: Path, data: dict, name: str = "g.json") -> Path:
        import json

        p = tmp_path / name
        p.write_text(json.dumps(data))
        return p

    def test_detect_graph_text(self, tmp_path: Path, capsys):
        p = self._write(tmp_path, self._GAIN)
        rc = main(["detect", str(p)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Graph: t (graph)" in out
        assert "Parameters: 1" in out
        assert "BinOp: 1" in out
        assert "Valid: yes" in out

    def test_detect_graph_json(self, tmp_path: Path, capsys):
        import json

        p = self._write(tmp_path, self._GAIN)
        rc = main(["detect", str(p), "--json"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["name"] == "t"
        assert data["source"] == "graph"
        assert data["num_inputs"] == 1
        assert data["num_params"] == 1
        assert data["node_types"] == {"BinOp": 1}
        assert data["valid"] is True

    def test_detect_graph_buffers_and_delaylines(self, tmp_path: Path, capsys):
        data = {
            "name": "buf",
            "inputs": [{"id": "in1"}],
            "outputs": [{"id": "out1", "source": "r"}],
            "params": [],
            "nodes": [
                {"op": "buffer", "id": "tbl", "size": 256},
                {"op": "buf_read", "id": "r", "buffer": "tbl", "index": "in1"},
            ],
        }
        p = self._write(tmp_path, data)
        rc = main(["detect", str(p)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Buffers: tbl" in out

    def test_detect_graph_invalid_reports_errors(self, tmp_path: Path, capsys):
        data = {
            "name": "bad",
            "inputs": [{"id": "in1"}],
            "outputs": [{"id": "out1", "source": "missing_node"}],
            "params": [],
            "nodes": [{"op": "mul", "id": "sc", "a": "in1", "b": "in1"}],
        }
        p = self._write(tmp_path, data)
        rc = main(["detect", str(p)])
        # detect is introspection -- it reports invalidity but does not fail.
        assert rc == 0
        assert "Valid: no" in capsys.readouterr().out

    def test_detect_missing_graph_file(self, tmp_path: Path, capsys):
        rc = main(["detect", str(tmp_path / "nope.json")])
        assert rc == 1
        assert "error loading graph" in capsys.readouterr().err

    def test_detect_export_still_works(self, gigaverb_export: Path, capsys):
        rc = main(["detect", str(gigaverb_export)])
        assert rc == 0
        assert "Gen~ Export:" in capsys.readouterr().out


class TestManifestCommand:
    """Integration tests for the `manifest` CLI command."""

    def test_manifest_emits_valid_json(self, gigaverb_export: Path, capsys):
        rc = main(["manifest", str(gigaverb_export)])
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)  # must be parseable JSON
        assert data["num_inputs"] == 2
        assert data["num_outputs"] == 2
        assert data["gen_name"]
        assert isinstance(data["params"], list) and data["params"]

    def test_manifest_buffers_override(self, gigaverb_export: Path, capsys):
        # gigaverb has no buffers; --buffers overrides auto-detection.
        rc = main(["manifest", str(gigaverb_export), "--buffers", "tail", "early"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["buffers"] == ["tail", "early"]

    def test_manifest_autodetects_buffers(self, rampleplayer_export: Path, capsys):
        # RamplePlayer declares buffers; manifest should report them.
        rc = main(["manifest", str(rampleplayer_export)])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["buffers"]  # non-empty

    def test_manifest_missing_export_errors(self, tmp_path: Path, capsys):
        rc = main(["manifest", str(tmp_path / "nonexistent")])
        assert rc == 1
        assert "Error parsing export" in capsys.readouterr().err
