"""Circle SDK acquisition (clone + build) and path resolution."""

import os
import re
import shutil
import subprocess
from pathlib import Path

from gen_dsp.core.cache import get_cache_dir
from gen_dsp.errors import BuildError

# Circle version (latest stable release)
CIRCLE_VERSION = "Step50.1"


_CIRCLE_CLONE_URL = "https://github.com/rsta2/circle.git"


# Subdirectory name inside the gen-dsp cache
_CIRCLE_CACHE_SUBDIR = "circle-src"


# Toolchain prefix per AArch width
_PREFIXES = {32: "arm-none-eabi-", 64: "aarch64-none-elf-"}


def circle_dir_name(rasppi: int = 3, aarch: int = 64) -> str:
    """Return the cache directory name for one RASPPI/AARCH build of Circle.

    libcircle.a bakes in the Pi model (peripheral base address) and the
    architecture, so each target needs its own configured tree.
    """
    return f"circle-r{rasppi}-a{aarch}"


def _get_default_circle_dir(rasppi: int = 3, aarch: int = 64) -> Path:
    """Return the default cached Circle path (OS-appropriate)."""

    return get_cache_dir() / _CIRCLE_CACHE_SUBDIR / circle_dir_name(rasppi, aarch)


def _resolve_circle_dir(rasppi: int = 3, aarch: int = 64) -> Path:
    """Resolve CIRCLE_DIR using the priority chain.

    1. CIRCLE_DIR env var (used as-is for every target)
    2. GEN_DSP_CACHE_DIR env var + circle-src/circle-r<RASPPI>-a<AARCH>
    3. OS-appropriate gen-dsp cache path
    """
    env_circle = os.environ.get("CIRCLE_DIR")
    if env_circle:
        return Path(env_circle)

    env_cache = os.environ.get("GEN_DSP_CACHE_DIR")
    if env_cache:
        return Path(env_cache) / _CIRCLE_CACHE_SUBDIR / circle_dir_name(rasppi, aarch)

    return _get_default_circle_dir(rasppi, aarch)


def read_makefile_target(makefile: Path) -> tuple[int, int]:
    """Return (RASPPI, AARCH) from a generated project Makefile's overrides."""
    text = makefile.read_text()
    found = {}
    for key in ("RASPPI", "AARCH"):
        m = re.search(rf"^override {key} = (\d+)$", text, re.MULTILINE)
        if not m:
            raise BuildError(f"{makefile} has no 'override {key} = ...' line")
        found[key] = int(m.group(1))
    return found["RASPPI"], found["AARCH"]


def _check_config(circle_dir: Path, rasppi: int, aarch: int) -> None:
    """Raise if circle_dir was configured for a different RASPPI/AARCH."""
    config = circle_dir / "Config.mk"
    if not config.is_file():
        return
    text = config.read_text()
    for key, want in (("RASPPI", rasppi), ("AARCH", aarch)):
        m = re.search(rf"^{key}\s*=\s*(\d+)", text, re.MULTILINE)
        if m and int(m.group(1)) != want:
            raise BuildError(
                f"Circle at {circle_dir} is configured for {key}={m.group(1)}, "
                f"but this project targets {key}={want}. libcircle.a would not "
                f"match the board. Unset CIRCLE_DIR, or point it at a Circle "
                f"tree configured with './configure -r {rasppi} -p "
                f"{_PREFIXES[aarch]}'."
            )


def ensure_circle(
    circle_dir: Path | None = None,
    verbose: bool = False,
    rasppi: int = 3,
    aarch: int = 64,
) -> Path:
    """Ensure Circle SDK is available, cloning and building if necessary.

    Args:
        circle_dir: Explicit path. If None, resolves via priority chain.
        verbose: Print progress messages.
        rasppi: Raspberry Pi model to configure Circle for.
        aarch: 32 or 64.

    Returns:
        Path to the Circle directory (containing Rules.mk).

    Raises:
        BuildError: If clone or build fails, or if git/toolchain
                    is not available.
    """
    if aarch not in _PREFIXES:
        raise BuildError(f"AARCH must be 32 or 64, got {aarch}")
    prefix = _PREFIXES[aarch]
    if circle_dir is None:
        circle_dir = _resolve_circle_dir(rasppi, aarch)

    # Already present and built?
    if (circle_dir / "Rules.mk").is_file() and (
        circle_dir / "lib" / "libcircle.a"
    ).is_file():
        _check_config(circle_dir, rasppi, aarch)
        return circle_dir

    # Check prerequisites
    if not shutil.which("git"):
        raise BuildError(
            "git is required to clone Circle. Install git and ensure it is on PATH."
        )

    if not shutil.which(f"{prefix}gcc"):
        raise BuildError(
            f"{prefix}gcc is required to build Circle SDK for AARCH={aarch}. "
            "Download the bare-metal toolchain from:\n"
            "  https://developer.arm.com/downloads/-/arm-gnu-toolchain-downloads\n"
            f"Select the '{prefix.rstrip('-')}' variant for your host OS, "
            "extract it,\nand add its bin/ directory to your PATH."
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
        _check_config(circle_dir, rasppi, aarch)
        if verbose:
            print("Configuring Circle ...")

        # configure and makeall are bash scripts: run them through bash so
        # hosts that cannot exec a shebang (native Windows) still work.
        try:
            subprocess.run(
                ["bash", "./configure", "-f", "-r", str(rasppi), "-p", prefix],
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
                ["bash", "./makeall", "clean"],
                cwd=circle_dir,
                check=True,
                capture_output=not verbose,
                text=True,
            )
        except subprocess.CalledProcessError:
            pass  # clean may fail on first build

        try:
            subprocess.run(
                ["bash", "./makeall"],
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
