"""Shared test validation helpers for plugin build verification.

These functions validate built plugins by running external validator tools
(clap-validator, VST3 SDK validator, lilv-based LV2 validator) or headless
host applications (pd, chuck) against the built output.

All validators are optional -- if the tool is unavailable, validation is
silently skipped (the function returns immediately).
"""

import re
import shutil
import socket
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Network-reachability gating for SDK-download build tests
# ---------------------------------------------------------------------------
#
# Several build-integration tests fetch a platform SDK on first run (VCV Rack
# via urllib, Daisy/Circle via git clone, and the CMake FetchContent platforms
# clap/vst3/lv2/sc via git).  Those downloads hard-fail when offline.  The
# helpers below let such tests skip cleanly when -- and only when -- a download
# would actually be required: if the SDK is already cached the test runs offline
# as normal, and only an uncached SDK combined with an unreachable host triggers
# a skip.  This preserves coverage for the common offline-but-cached case.


# Path that exists once a given platform's SDK is cached locally, plus the host
# that must be reachable to download it.  Platforms absent from this map need no
# network access and are never gated.
def _sdk_sentinel(platform: str, cache: Path) -> Optional[tuple[Path, str]]:
    if platform == "vcvrack":
        return cache / "rack-sdk-src" / "Rack-SDK" / "plugin.mk", "vcvrack.com"
    if platform == "daisy":
        return cache / "libdaisy-src" / "libDaisy" / "core" / "Makefile", "github.com"
    if platform == "circle":
        return cache / "circle-src" / "circle" / "Rules.mk", "github.com"
    cmake_src = {
        "clap": "clap-src",
        "vst3": "vst3sdk-src",
        "lv2": "lv2-src",
        "sc": "supercollider-src",
    }
    if platform in cmake_src:
        return cache / cmake_src[platform], "github.com"
    return None


@lru_cache(maxsize=None)
def _host_reachable(host: str, port: int = 443, timeout: float = 3.0) -> bool:
    """Return True if a TCP connection to host:port succeeds (cached per host)."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def skip_if_sdk_download_needed(platform: str, cache: Path) -> None:
    """Skip the current test if building `platform` needs an offline SDK download.

    No-op when the platform needs no network access, or when its SDK is already
    cached.  Only an uncached SDK plus an unreachable host triggers the skip.
    """
    import pytest

    sentinel_host = _sdk_sentinel(platform, cache)
    if sentinel_host is None:
        return
    sentinel, host = sentinel_host
    if sentinel.exists():
        return
    if not _host_reachable(host):
        pytest.skip(
            f"{host} unreachable and {platform} SDK not cached at {sentinel}; "
            "skipping download-dependent build test"
        )


# FetchContent_Declare names used by the CMake platform templates (clap, vst3,
# lv2, sc), mapped to their cached source-tree subdirectory under the shared
# cache.  Used to point CMake at a pre-populated checkout.
_FETCHCONTENT_SDKS = ("clap", "vst3sdk", "lv2", "supercollider")


def fetchcontent_cmake_args(cache: Path) -> list[str]:
    """CMake args wiring FetchContent to the shared cache.

    Beyond the base dir, this passes ``-DFETCHCONTENT_SOURCE_DIR_<NAME>`` for
    every SDK already present in the cache so CMake consumes the cached checkout
    directly instead of re-running its download/populate step.  That avoids an
    intermittent FetchContent stamp-file failure seen when the ``-subbuild``
    state is wiped between sessions while ``-src`` is kept, and lets cached
    builds run offline.  Overrides for SDKs a project does not declare are
    ignored by CMake, so passing the full set everywhere is safe.  On a fresh
    cache (e.g. clean CI) no overrides are added and normal population runs.
    """
    args = [f"-DFETCHCONTENT_BASE_DIR={cache}"]
    for name in _FETCHCONTENT_SDKS:
        src = cache / f"{name}-src"
        if src.is_dir() and any(src.iterdir()):
            args.append(f"-DFETCHCONTENT_SOURCE_DIR_{name.upper()}={src}")
    # Disable the VST3 SDK's moduleinfotool utility.  It is unnecessary for the
    # plugin (which loads fine without moduleinfo.json) but pulls the SDK's
    # vst-hosting sources (validator, tests) into the shared SDK build tree,
    # where they intermittently fail to build ("No rule to make target
    # libsdk_hosting.a", missing .o.d files).  Harmless for non-VST3 projects,
    # which never read this variable.
    args.append("-DSMTG_ENABLE_MODULE_INFO=OFF")
    return args


# ---------------------------------------------------------------------------
# CLAP validation
# ---------------------------------------------------------------------------


_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

# "44 tests run, 33 passed, 0 failed, 0 warnings, 11 skipped"
_CLAP_SUMMARY_RE = re.compile(r"(\d+) failed")

# A panic inside the validator itself, which it reports as a failed test.  It
# self-diagnoses these: "param-conversions crashed: attempt to divide by zero.
# This is a bug in the validator".  The current pinned revision hits one on any
# plugin that exposes zero parameters (it divides by the parameter count), which
# says nothing about the plugin under test.
_CLAP_VALIDATOR_BUG_RE = re.compile(
    r"Test (\S+) crashed:[^\n]*This is a bug in the validator"
)


def validate_clap(validator: Optional[Path], clap_bundle: Path) -> None:
    """Run the CLAP validator against a plugin, if available."""
    if validator is None:
        return
    result = subprocess.run(
        [str(validator), "validate", str(clap_bundle)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    # clap-validator colours its summary line unconditionally (it honours
    # neither NO_COLOR nor a non-tty stdout), so the counts are only visible
    # once the escape sequences are stripped.
    stdout = _ANSI_ESCAPE_RE.sub("", result.stdout)
    stderr = _ANSI_ESCAPE_RE.sub("", result.stderr)
    summary = _CLAP_SUMMARY_RE.search(stdout)
    assert summary is not None, (
        f"could not find the clap-validator summary line:\n{stdout}\n{stderr}"
    )

    failed = int(summary.group(1))
    validator_bugs = set(_CLAP_VALIDATOR_BUG_RE.findall(stdout + stderr))
    assert failed <= len(validator_bugs), f"CLAP validation failed:\n{stdout}\n{stderr}"
    if not validator_bugs:
        assert result.returncode == 0, f"CLAP validation failed:\n{stdout}\n{stderr}"


# ---------------------------------------------------------------------------
# VST3 validation
# ---------------------------------------------------------------------------


def validate_vst3(
    validator: Optional[Path],
    vst3_bundle: Path,
    allow_crash_on_cleanup: bool = False,
) -> None:
    """Run the VST3 SDK validator against a bundle, if available."""
    if validator is None:
        return
    result = subprocess.run(
        [str(validator), str(vst3_bundle)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if allow_crash_on_cleanup:
        assert "[Failed]" not in result.stdout, (
            f"VST3 validation failed:\n{result.stdout}\n{result.stderr}"
        )
    else:
        assert result.returncode == 0, (
            f"VST3 validation failed:\n{result.stdout}\n{result.stderr}"
        )
        assert "[Failed]" not in result.stdout, (
            f"VST3 validation failed:\n{result.stdout}\n{result.stderr}"
        )


# ---------------------------------------------------------------------------
# LV2 validation
# ---------------------------------------------------------------------------


def validate_lv2(
    validator: Optional[Path],
    bundle_dir: Path,
    lib_name: str,
    expected_audio_in: int,
    expected_audio_out: int,
    expected_params: int,
) -> None:
    """Validate a built LV2 bundle by instantiating and processing audio."""
    if validator is None:
        return

    plugin_uri = f"http://gen-dsp.com/plugins/{lib_name}"

    with tempfile.TemporaryDirectory() as tmpdir:
        isolated = Path(tmpdir) / bundle_dir.name
        shutil.copytree(bundle_dir, isolated)

        result = subprocess.run(
            [
                str(validator),
                tmpdir,
                plugin_uri,
                str(expected_audio_in),
                str(expected_audio_out),
                str(expected_params),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"LV2 validation failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "PASS" in result.stdout, (
            f"LV2 validation did not PASS:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )


# ---------------------------------------------------------------------------
# PD validation
# ---------------------------------------------------------------------------

_has_pd = shutil.which("pd") is not None


def validate_pd_external(project_dir: Path, lib_name: str) -> None:
    """Load a built PD external in headless PD and verify it instantiates."""
    if not _has_pd:
        return

    test_pd = project_dir / "test_load.pd"
    test_pd.write_text(
        "#N canvas 0 0 450 300 10;\n"
        f"#X obj 10 10 {lib_name}~;\n"
        "#X obj 10 50 loadbang;\n"
        "#X msg 10 70 \\; pd quit;\n"
        "#X connect 1 0 2 0;\n"
    )

    result = subprocess.run(
        [
            "pd",
            "-nogui",
            "-noaudio",
            "-noadc",
            "-nodac",
            "-stderr",
            "-verbose",
            "-path",
            str(project_dir),
            str(test_pd),
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, f"pd failed (exit {result.returncode}):\n{output}"
    assert "couldn't create" not in output, (
        f"PD failed to load {lib_name}~ external:\n{output}"
    )
    assert f"{lib_name}~" in output


# ---------------------------------------------------------------------------
# ChucK validation
# ---------------------------------------------------------------------------

_has_chuck = shutil.which("chuck") is not None


def validate_chugin(
    project_dir: Path,
    class_name: str,
    expected_params: int,
    expect_audio: bool = False,
) -> None:
    """Load a built chugin in ChucK and validate it works."""
    if not _has_chuck:
        return

    test_ck = project_dir / "test.ck"

    lines = [f'@import "{class_name}"']

    if expect_audio:
        lines.append(f"Noise src => {class_name} eff => Gain g => blackhole;")
    else:
        lines.append(f"{class_name} eff => blackhole;")

    lines += [
        "eff.numParams() => int np;",
        '<<< "PARAMS", np >>>;',
    ]
    if expected_params > 0:
        lines += [
            "eff.paramName(0) => string pname;",
            '<<< "PNAME", pname >>>;',
        ]

    if expect_audio:
        lines += [
            "50::ms => now;",
            "0.0 => float energy;",
            "repeat(2205) {",
            "    1::samp => now;",
            "    g.last() * g.last() +=> energy;",
            "}",
            'if (energy > 0.0) <<< "AUDIO_OK" >>>;',
            'else <<< "AUDIO_FAIL", energy >>>;',
        ]
    else:
        lines.append("100::ms => now;")

    lines.append('<<< "DONE" >>>;')
    test_ck.write_text("\n".join(lines) + "\n")

    result = subprocess.run(
        ["chuck", "--chugin-path:.", "--silent", "test.ck"],
        cwd=project_dir,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"chuck failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    output = result.stderr
    assert "PARAMS" in output
    assert str(expected_params) in output
    if expect_audio:
        assert "AUDIO_OK" in output, f"No audio output detected:\n{output}"
    assert "DONE" in output
