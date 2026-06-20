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


def dir_size(path: Path) -> int:
    """Return the total size in bytes of all files under ``path`` (0 if absent).

    Symlinks are not followed (only real file sizes are counted).
    """
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    total = 0
    for p in path.rglob("*"):
        if p.is_file() and not p.is_symlink():
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return total


def format_size(num_bytes: int) -> str:
    """Format a byte count as a human-readable string (e.g. ``1.2 GB``)."""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024.0 or unit == "TB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"
