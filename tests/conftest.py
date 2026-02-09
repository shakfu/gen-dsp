"""Pytest configuration and fixtures for gen_dsp tests."""

from pathlib import Path

import pytest


@pytest.fixture
def fixtures_dir() -> Path:
    """Path to the test fixtures directory."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def gigaverb_export(fixtures_dir: Path) -> Path:
    """Path to the gigaverb gen~ export (no buffers)."""
    return fixtures_dir / "gigaverb" / "gen"


@pytest.fixture
def rampleplayer_export(fixtures_dir: Path) -> Path:
    """Path to the RamplePlayer gen~ export (has buffers)."""
    return fixtures_dir / "RamplePlayer" / "gen"


@pytest.fixture
def spectraldelayfb_export(fixtures_dir: Path) -> Path:
    """Path to the spectraldelayfb gen~ export."""
    return fixtures_dir / "spectraldelayfb" / "gen"


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Temporary directory for project generation tests."""
    return tmp_path / "test_project"


# -- Shared FetchContent cache for CMake-based build integration tests --------

# Fixed path under build/ (gitignored) so SDK downloads persist across
# pytest sessions.  Both CLAP and VST3 build tests use this.
_FETCHCONTENT_CACHE = Path(__file__).resolve().parent.parent / "build" / ".fetchcontent_cache"


@pytest.fixture(scope="session")
def fetchcontent_cache() -> Path:
    """Fixed-path FetchContent cache shared across all build tests.

    Persists across pytest sessions so large SDKs (e.g. VST3 ~50 MB)
    are only downloaded once.
    """
    _FETCHCONTENT_CACHE.mkdir(parents=True, exist_ok=True)
    return _FETCHCONTENT_CACHE


