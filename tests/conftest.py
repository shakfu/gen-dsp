"""Pytest configuration and fixtures for gen_ext tests."""

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
