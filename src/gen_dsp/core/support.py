"""Build-host support and runtime targets for each platform.

Each ``Platform`` subclass declares ``kind``, ``build_hosts``, ``artifacts``
and ``runtime``. ``platform_support()`` collects them into the versioned JSON
that ``gen-dsp platforms --json`` prints, for consumers such as dsp-graph.
Host-dependent readiness (installed tools) stays in ``gen_dsp.core.doctor``.
"""

import sys
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from gen_dsp.version import __version__

# Bump on any incompatible change to the JSON shape.
SCHEMA_VERSION = 1

HOSTS = ("linux", "macos", "windows")

STATUSES = {
    "ci": "built in CI on this host",
    "verified": "built and confirmed by hand on this host; not in CI",
    "untested": "no known blocker, but never built on this host",
    "unsupported": "cannot be built on this host (see note)",
}

KINDS = {
    "native": "binary runs on the build host's OS, inside the listed runtime",
    "cross": "firmware or module for the listed devices",
    "web": "runs in a web browser",
}


@dataclass(frozen=True)
class HostSupport:
    """Build status of one platform on one build-host OS."""

    status: str
    note: str = ""


CI = HostSupport("ci")
UNTESTED = HostSupport("untested")


def verified(note: str) -> HostSupport:
    return HostSupport("verified", note)


def untested(note: str) -> HostSupport:
    return HostSupport("untested", note)


def unsupported(note: str) -> HostSupport:
    return HostSupport("unsupported", note)


def hosts(
    *, linux: HostSupport, macos: HostSupport, windows: HostSupport
) -> Mapping[str, HostSupport]:
    """Return a read-only build-host table covering every OS in HOSTS."""
    return MappingProxyType({"linux": linux, "macos": macos, "windows": windows})


def per_host(**exts: str) -> Mapping[str, str]:
    """Return a read-only artifact table keyed by HOSTS entries or "any"."""
    return MappingProxyType(exts)


@dataclass(frozen=True)
class Runtime:
    """What loads or runs a platform's build output."""

    name: str
    devices: tuple[str, ...] = ()
    note: str = ""


def host_os() -> str:
    """Return the current build host as one of HOSTS."""
    if sys.platform == "darwin":
        return "macos"
    if sys.platform == "win32":
        return "windows"
    return "linux"


def platform_support() -> dict[str, Any]:
    """Return the support metadata of every platform as a JSON-ready dict."""
    from gen_dsp.platforms import get_platform, list_platforms

    platforms: dict[str, Any] = {}
    for name in list_platforms():
        p = get_platform(name)
        hosts = {
            h: {"status": s.status, "note": s.note} for h, s in p.build_hosts.items()
        }
        devices = list(p.runtime.devices) or p.list_boards()
        platforms[name] = {
            "description": p.description,
            "build_system": p.build_system,
            "kind": p.kind,
            "build_hosts": hosts,
            "artifacts": {
                h: ext
                for h, ext in p.artifacts.items()
                if h == "any" or p.build_hosts[h].status != "unsupported"
            },
            "runtime": {
                "name": p.runtime.name,
                "devices": devices,
                "note": p.runtime.note,
            },
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "gen_dsp_version": __version__,
        "statuses": STATUSES,
        "kinds": KINDS,
        "platforms": platforms,
    }
