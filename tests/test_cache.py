"""Tests for gen_dsp.core.cache module."""

import platform
from pathlib import Path


from gen_dsp.core.cache import get_cache_dir


class TestGetCacheDir:
    """Tests for get_cache_dir()."""

    def test_returns_path(self):
        """Test that get_cache_dir returns a Path."""
        result = get_cache_dir()
        assert isinstance(result, Path)

    def test_contains_gen_dsp(self):
        """Test that path contains 'gen-dsp' component."""
        result = get_cache_dir()
        assert "gen-dsp" in result.parts

    def test_contains_fetchcontent(self):
        """Test that path ends with 'fetchcontent'."""
        result = get_cache_dir()
        assert result.name == "fetchcontent"

    def test_macos_path(self, monkeypatch):
        """Test macOS-specific cache path."""
        monkeypatch.setattr(platform, "system", lambda: "Darwin")
        result = get_cache_dir()
        assert "Library" in result.parts
        assert "Caches" in result.parts

    def test_linux_default_path(self, monkeypatch):
        """Test Linux default cache path (~/.cache)."""
        monkeypatch.setattr(platform, "system", lambda: "Linux")
        monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
        result = get_cache_dir()
        assert ".cache" in result.parts

    def test_linux_xdg_override(self, monkeypatch, tmp_path):
        """Test Linux respects XDG_CACHE_HOME."""
        monkeypatch.setattr(platform, "system", lambda: "Linux")
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "custom_cache"))
        result = get_cache_dir()
        assert str(result).startswith(str(tmp_path / "custom_cache"))
        assert "gen-dsp" in result.parts

    def test_windows_path(self, monkeypatch, tmp_path):
        """Test Windows cache path."""
        monkeypatch.setattr(platform, "system", lambda: "Windows")
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData" / "Local"))
        result = get_cache_dir()
        assert str(result).startswith(str(tmp_path / "AppData" / "Local"))
        assert "gen-dsp" in result.parts


class TestSizeHelpers:
    """Tests for dir_size() and format_size()."""

    def test_format_size_units(self):
        from gen_dsp.core.cache import format_size

        assert format_size(0) == "0 B"
        assert format_size(512) == "512 B"
        assert format_size(2048) == "2.0 KB"
        assert format_size(5 * 1024 * 1024) == "5.0 MB"

    def test_dir_size_counts_files(self, tmp_path: Path):
        from gen_dsp.core.cache import dir_size

        assert dir_size(tmp_path / "missing") == 0
        (tmp_path / "a").write_bytes(b"x" * 100)
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "b").write_bytes(b"y" * 50)
        assert dir_size(tmp_path) == 150


class TestCachePrune:
    """Tests for `gen-dsp cache --prune`."""

    def _populate(self, cache: Path) -> None:
        for name in ("clap-src", "vst3sdk-src", "clap-build"):
            d = cache / name
            d.mkdir(parents=True)
            (d / "f").write_bytes(b"z" * 1000)

    def test_prune_dry_run_keeps_files(self, tmp_path, monkeypatch, capsys):
        from gen_dsp.cli import main

        self._populate(tmp_path)
        monkeypatch.setenv("GEN_DSP_CACHE_DIR", str(tmp_path))
        rc = main(["cache", "--prune", "--dry-run"])
        assert rc == 0
        assert "Would remove" in capsys.readouterr().out
        assert (tmp_path / "clap-src").is_dir()  # nothing deleted

    def test_prune_yes_removes(self, tmp_path, monkeypatch, capsys):
        from gen_dsp.cli import main

        self._populate(tmp_path)
        monkeypatch.setenv("GEN_DSP_CACHE_DIR", str(tmp_path))
        rc = main(["cache", "--prune", "-y"])
        assert rc == 0
        assert "Reclaimed" in capsys.readouterr().out
        assert list(tmp_path.iterdir()) == []

    def test_prune_confirm_no_aborts(self, tmp_path, monkeypatch, capsys):
        from gen_dsp.cli import main

        self._populate(tmp_path)
        monkeypatch.setenv("GEN_DSP_CACHE_DIR", str(tmp_path))
        monkeypatch.setattr("builtins.input", lambda _prompt: "n")
        rc = main(["cache", "--prune"])
        assert rc == 0
        assert "Aborted." in capsys.readouterr().out
        assert (tmp_path / "clap-src").is_dir()

    def test_prune_confirm_yes_removes(self, tmp_path, monkeypatch):
        from gen_dsp.cli import main

        self._populate(tmp_path)
        monkeypatch.setenv("GEN_DSP_CACHE_DIR", str(tmp_path))
        monkeypatch.setattr("builtins.input", lambda _prompt: "y")
        rc = main(["cache", "--prune"])
        assert rc == 0
        assert list(tmp_path.iterdir()) == []

    def test_prune_empty_cache(self, tmp_path, monkeypatch, capsys):
        from gen_dsp.cli import main

        monkeypatch.setenv("GEN_DSP_CACHE_DIR", str(tmp_path))
        rc = main(["cache", "--prune", "-y"])
        assert rc == 0
        assert "already empty" in capsys.readouterr().out

    def test_cache_listing_shows_sizes(self, tmp_path, monkeypatch, capsys):
        from gen_dsp.cli import main

        self._populate(tmp_path)
        monkeypatch.setenv("GEN_DSP_CACHE_DIR", str(tmp_path))
        rc = main(["cache"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Total size:" in out
        assert "clap" in out
        assert "--prune" in out  # hint shown when cache non-empty
