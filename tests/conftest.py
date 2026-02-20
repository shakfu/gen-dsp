"""Pytest configuration and fixtures for gen_dsp tests."""

import shutil
from pathlib import Path

import pytest

try:
    import minihost as _minihost
except ImportError:
    _minihost = None


def _validate_plugin_with_minihost(
    plugin_path,
    num_inputs,
    num_outputs,
    num_params=0,
    send_midi=False,
    check_energy=True,
):
    """Load a plugin via minihost, process audio, verify output energy.

    Silently returns if minihost is not installed.
    """
    if _minihost is None:
        return

    import numpy as np

    plugin = _minihost.Plugin(
        str(plugin_path),
        sample_rate=48000.0,
        max_block_size=512,
        in_channels=num_inputs,
        out_channels=num_outputs,
    )
    assert plugin.num_params >= num_params

    n_blocks = 8  # enough for FFT-based processors
    block_size = 512
    output = np.zeros((num_outputs, block_size), dtype=np.float32)
    energy = 0.0

    for i in range(n_blocks):
        if num_inputs > 0:
            inp = np.random.uniform(-0.5, 0.5, (num_inputs, block_size)).astype(
                np.float32
            )
        else:
            inp = np.zeros((0, block_size), dtype=np.float32)

        if send_midi and i == 0:
            events = [(0, 0x90, 60, 100)]  # note-on C4
            plugin.process_midi(inp, output, events)
        else:
            plugin.process(inp, output)

        energy += float(np.sum(output**2))

    if check_energy:
        assert energy > 1e-10, f"Plugin produced no audio output (energy={energy})"


@pytest.fixture
def validate_minihost():
    """Fixture providing the minihost validation helper."""
    return _validate_plugin_with_minihost


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
_FETCHCONTENT_CACHE = (
    Path(__file__).resolve().parent.parent / "build" / ".fetchcontent_cache"
)


@pytest.fixture(scope="session")
def fetchcontent_cache() -> Path:
    """Fixed-path FetchContent cache shared across all build tests.

    Persists across pytest sessions so large SDKs (e.g. VST3 ~50 MB)
    are only downloaded once.  Build/subbuild directories are cleared
    each session to avoid stale absolute paths from previous pytest
    temp directories baked into CMake state.
    """
    _FETCHCONTENT_CACHE.mkdir(parents=True, exist_ok=True)
    for d in _FETCHCONTENT_CACHE.iterdir():
        if d.is_dir() and (d.name.endswith("-build") or d.name.endswith("-subbuild")):
            shutil.rmtree(d, ignore_errors=True)
    return _FETCHCONTENT_CACHE
