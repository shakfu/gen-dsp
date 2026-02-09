"""
Shared FetchContent cache directory resolution.

Provides an OS-appropriate cache path for CMake FetchContent downloads
so that multiple gen-dsp projects can share a single copy of fetched SDKs.
"""

import os
import platform
from pathlib import Path


def get_cache_dir() -> Path:
    """Return the OS-appropriate shared cache directory for FetchContent.

    - macOS:   ~/Library/Caches/gen-dsp/fetchcontent/
    - Linux:   $XDG_CACHE_HOME/gen-dsp/fetchcontent/ (defaults to ~/.cache/)
    - Windows: %LOCALAPPDATA%/gen-dsp/fetchcontent/
    """
    system = platform.system()
    if system == "Darwin":
        base = Path.home() / "Library" / "Caches"
    elif system == "Windows":
        local = os.environ.get("LOCALAPPDATA")
        base = Path(local) if local else Path.home() / "AppData" / "Local"
    else:
        xdg = os.environ.get("XDG_CACHE_HOME")
        base = Path(xdg) if xdg else Path.home() / ".cache"

    return base / "gen-dsp" / "fetchcontent"
