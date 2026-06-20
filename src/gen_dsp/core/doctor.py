"""Build-prerequisite diagnostics for gen-dsp platforms.

``gen-dsp doctor`` surveys the host for the tools each platform needs to build
(compilers, CMake/Make, cross-toolchains, Emscripten, ...) and reports, per
platform, whether it is ready to build -- with install hints for anything
missing. SDKs that gen-dsp fetches automatically (CLAP/VST3/LV2/SC headers,
the Rack SDK, libDaisy, Circle, miniaudio) are reported as informational notes
rather than hard prerequisites.
"""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass(frozen=True)
class Tool:
    """A build prerequisite that can be probed on the host."""

    key: str
    label: str
    hint: str
    probe: Callable[[], Optional[str]]

    def locate(self) -> Optional[str]:
        """Return a path/identifier if the tool is present, else None."""
        return self.probe()


def _which(*names: str) -> Callable[[], Optional[str]]:
    """Probe that returns the path of the first available executable."""

    def probe() -> Optional[str]:
        for name in names:
            found = shutil.which(name)
            if found:
                return found
        return None

    return probe


def _macos_probe() -> Optional[str]:
    return "macOS" if sys.platform == "darwin" else None


# -- Shared tool definitions ---------------------------------------------------

MAKE = Tool(
    "make",
    "make",
    "Install build tools (Xcode Command Line Tools on macOS, build-essential on Linux).",
    _which("make"),
)
CMAKE = Tool(
    "cmake",
    "cmake",
    "Install CMake >= 3.15: https://cmake.org/download",
    _which("cmake"),
)
CXX = Tool(
    "c++",
    "C++ compiler",
    "Install clang++ or g++ (Xcode Command Line Tools / build-essential).",
    _which("clang++", "g++", "c++"),
)
CC = Tool(
    "cc",
    "C compiler",
    "Install clang or gcc (Xcode Command Line Tools / build-essential).",
    _which("cc", "clang", "gcc"),
)
GIT = Tool(
    "git",
    "git",
    "Install git (used to fetch SDKs on first build).",
    _which("git"),
)
EMCC = Tool(
    "emcc",
    "Emscripten (emcc)",
    "Install the Emscripten SDK: https://emscripten.org/docs/getting_started",
    _which("emcc"),
)
ARM_GCC = Tool(
    "arm-none-eabi-gcc",
    "ARM bare-metal GCC",
    "Install the ARM GNU toolchain (arm-none-eabi), e.g. from "
    "https://developer.arm.com/downloads/-/arm-gnu-toolchain-downloads",
    _which("arm-none-eabi-gcc"),
)
CIRCLE_XCC = Tool(
    "circle-cross-gcc",
    "ARM/AArch64 bare-metal GCC",
    "Install arm-none-eabi-gcc (32-bit Pi boards) or aarch64-none-elf-gcc "
    "(64-bit Pi boards) for your target board.",
    _which("arm-none-eabi-gcc", "aarch64-none-elf-gcc"),
)
MACOS = Tool(
    "macos",
    "macOS",
    "This platform builds on macOS only.",
    _macos_probe,
)
XCODE = Tool(
    "xcodebuild",
    "Xcode",
    "Install the full Xcode app (not just the Command Line Tools); the AUv3 "
    "build uses the CMake Xcode generator.",
    _which("xcodebuild"),
)


# Auto-fetched dependency note phrasing.
def _auto(name: str) -> str:
    return f"{name}: fetched automatically on first build (needs network)."


# -- Per-platform requirements -------------------------------------------------
#
# (required tools, informational notes). A platform is "ready" when every
# required tool is present; notes never affect readiness.
PLATFORM_REQUIREMENTS: dict[str, tuple[list[Tool], list[str]]] = {
    "pd": ([MAKE, CC], []),
    "max": ([MACOS, CMAKE, CXX], [_auto("max-sdk-base")]),
    "chuck": ([MAKE, CXX], []),
    "au": ([MACOS, CMAKE, CXX], []),
    "clap": ([CMAKE, CXX], [_auto("CLAP SDK")]),
    "vst3": ([CMAKE, CXX], [_auto("VST3 SDK (large)")]),
    "lv2": ([CMAKE, CXX], [_auto("LV2 headers")]),
    "sc": ([CMAKE, CXX], [_auto("SuperCollider headers")]),
    "vcvrack": ([MAKE, CXX], [_auto("VCV Rack SDK")]),
    "daisy": ([MAKE, ARM_GCC, GIT], [_auto("libDaisy (cloned and built)")]),
    "circle": (
        [MAKE, CIRCLE_XCC, GIT],
        [_auto("Circle SDK (cloned)")],
    ),
    "webaudio": ([MAKE, EMCC], []),
    "standalone": ([MAKE, CXX], [_auto("miniaudio")]),
    "csound": (
        [MAKE, CXX],
        ["Needs the Csound development headers (csdl.h); see docs/backends/csound.md"],
    ),
    "auv3": ([MACOS, CMAKE, XCODE], []),
}


@dataclass(frozen=True)
class PlatformReport:
    """Diagnosis result for a single platform."""

    platform: str
    ready: bool
    present: list[tuple[str, str]]  # (label, located value)
    missing: list[Tool]
    notes: list[str]


def diagnose(platforms: Optional[list[str]] = None) -> list[PlatformReport]:
    """Diagnose build readiness for the given platforms (default: all)."""
    if platforms is None:
        platforms = sorted(PLATFORM_REQUIREMENTS)

    reports: list[PlatformReport] = []
    for platform in platforms:
        required, notes = PLATFORM_REQUIREMENTS[platform]
        present: list[tuple[str, str]] = []
        missing: list[Tool] = []
        for tool in required:
            located = tool.locate()
            if located is None:
                missing.append(tool)
            else:
                present.append((tool.label, located))
        reports.append(
            PlatformReport(
                platform=platform,
                ready=not missing,
                present=present,
                missing=missing,
                notes=notes,
            )
        )
    return reports


def format_report(reports: list[PlatformReport]) -> str:
    """Render diagnosis results as a human-readable report."""
    lines: list[str] = []
    lines.append("gen-dsp doctor -- build prerequisite check")
    lines.append("")

    width = max((len(r.platform) for r in reports), default=8)
    missing_tools: dict[str, Tool] = {}

    for r in reports:
        if r.ready:
            detail = ", ".join(label for label, _ in r.present)
            status = "READY"
        else:
            detail = "missing: " + ", ".join(t.label for t in r.missing)
            status = "NOT READY"
            for t in r.missing:
                missing_tools[t.key] = t
        lines.append(f"  {r.platform:<{width}}  {status:<10}  {detail}")
        for note in r.notes:
            lines.append(f"  {'':<{width}}  {'':<10}  - {note}")

    if missing_tools:
        lines.append("")
        lines.append("Missing tools and how to install them:")
        for tool in sorted(missing_tools.values(), key=lambda t: t.key):
            lines.append(f"  {tool.label}: {tool.hint}")
    else:
        lines.append("")
        lines.append("All platforms are ready to build on this host.")

    return "\n".join(lines)


def report_to_dict(reports: list[PlatformReport]) -> dict[str, object]:
    """Build a JSON-serialisable view of the diagnosis."""
    return {
        r.platform: {
            "ready": r.ready,
            "present": {label: value for label, value in r.present},
            "missing": [{"tool": t.key, "hint": t.hint} for t in r.missing],
            "notes": r.notes,
        }
        for r in reports
    }
