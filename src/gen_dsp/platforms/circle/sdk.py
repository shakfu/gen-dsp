"""Circle SDK acquisition (clone + build) and path resolution."""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from gen_dsp.core.cache import get_cache_dir
from gen_dsp.errors import BuildError


# Circle version (latest stable release)
CIRCLE_VERSION = "Step50.1"


_CIRCLE_CLONE_URL = "https://github.com/rsta2/circle.git"


# Subdirectory name inside the gen-dsp cache
_CIRCLE_CACHE_SUBDIR = "circle-src"


_CIRCLE_DIR_NAME = "circle"


def _get_default_circle_dir() -> Path:
    """Return the default cached Circle path (OS-appropriate)."""

    return get_cache_dir() / _CIRCLE_CACHE_SUBDIR / _CIRCLE_DIR_NAME


def _resolve_circle_dir() -> Path:
    """Resolve CIRCLE_DIR using the priority chain.

    1. CIRCLE_DIR env var
    2. GEN_DSP_CACHE_DIR env var + circle-src/circle
    3. OS-appropriate gen-dsp cache path
    """
    env_circle = os.environ.get("CIRCLE_DIR")
    if env_circle:
        return Path(env_circle)

    env_cache = os.environ.get("GEN_DSP_CACHE_DIR")
    if env_cache:
        return Path(env_cache) / _CIRCLE_CACHE_SUBDIR / _CIRCLE_DIR_NAME

    return _get_default_circle_dir()


def ensure_circle(circle_dir: Optional[Path] = None, verbose: bool = False) -> Path:
    """Ensure Circle SDK is available, cloning and building if necessary.

    Args:
        circle_dir: Explicit path. If None, resolves via priority chain.
        verbose: Print progress messages.

    Returns:
        Path to the Circle directory (containing Rules.mk).

    Raises:
        BuildError: If clone or build fails, or if git/toolchain
                    is not available.
    """
    if circle_dir is None:
        circle_dir = _resolve_circle_dir()

    # Already present and built?
    if (circle_dir / "Rules.mk").is_file() and (
        circle_dir / "lib" / "libcircle.a"
    ).is_file():
        return circle_dir

    # Check prerequisites
    if not shutil.which("git"):
        raise BuildError(
            "git is required to clone Circle. Install git and ensure it is on PATH."
        )

    if not shutil.which("aarch64-none-elf-gcc"):
        raise BuildError(
            "aarch64-none-elf-gcc is required to build Circle SDK. "
            "Download the AArch64 bare-metal toolchain from:\n"
            "  https://developer.arm.com/downloads/-/arm-gnu-toolchain-downloads\n"
            "Select the 'aarch64-none-elf' variant for your host OS, extract it,\n"
            "and add its bin/ directory to your PATH."
        )

    # Clone if not present
    if not (circle_dir / "Rules.mk").is_file():
        cache_parent = circle_dir.parent
        cache_parent.mkdir(parents=True, exist_ok=True)

        if verbose:
            print(f"Cloning Circle {CIRCLE_VERSION} from {_CIRCLE_CLONE_URL} ...")

        try:
            subprocess.run(
                [
                    "git",
                    "clone",
                    "--depth",
                    "1",
                    "--branch",
                    CIRCLE_VERSION,
                    _CIRCLE_CLONE_URL,
                    str(circle_dir),
                ],
                check=True,
                capture_output=not verbose,
                text=True,
                env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            )
        except subprocess.CalledProcessError as e:
            raise BuildError(f"Failed to clone Circle: {e}") from e

    # Configure and build Circle libraries if not already built
    if not (circle_dir / "lib" / "libcircle.a").is_file():
        if verbose:
            print("Configuring Circle ...")

        # Run ./configure to generate Config.mk
        # Use Pi 3 / AArch64 as the default SDK build target.
        # The per-project Makefile uses 'override' directives to set
        # the correct RASPPI/AARCH/PREFIX for the actual target board.
        try:
            subprocess.run(
                ["./configure", "-r", "3", "-p", "aarch64-none-elf-"],
                cwd=circle_dir,
                check=True,
                capture_output=not verbose,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            stderr = e.stderr or ""
            raise BuildError(f"Failed to configure Circle: {e}\n{stderr}") from e

        if verbose:
            print("Building Circle libraries ...")

        try:
            subprocess.run(
                ["./makeall", "clean"],
                cwd=circle_dir,
                check=True,
                capture_output=not verbose,
                text=True,
            )
        except subprocess.CalledProcessError:
            pass  # clean may fail on first build

        try:
            subprocess.run(
                ["./makeall"],
                cwd=circle_dir,
                check=True,
                capture_output=not verbose,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            stderr = e.stderr or ""
            raise BuildError(f"Failed to build Circle: {e}\n{stderr}") from e

    # Verify
    if not (circle_dir / "lib" / "libcircle.a").is_file():
        raise BuildError(
            f"Circle build completed but libcircle.a not found at "
            f"{circle_dir / 'lib' / 'libcircle.a'}"
        )

    return circle_dir
