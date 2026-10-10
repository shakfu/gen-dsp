"""Tests for platform support metadata (gen_dsp.core.support)."""

import json
import re
from pathlib import Path

import pytest

from gen_dsp.cli import main
from gen_dsp.core.support import HOSTS, KINDS, STATUSES, host_os, platform_support
from gen_dsp.platforms import get_platform, list_platforms

REPO_ROOT = Path(__file__).resolve().parent.parent

# README row label -> platform key
README_NAMES = {
    "PureData": "pd",
    "Max/MSP": "max",
    "ChucK": "chuck",
    "AudioUnit (AUv2)": "au",
    "AUv3": "auv3",
    "CLAP": "clap",
    "VST3": "vst3",
    "LV2": "lv2",
    "SuperCollider": "sc",
    "VCV Rack": "vcvrack",
    "Daisy": "daisy",
    "Circle": "circle",
    "Percussa SSP": "ssp",
    "Web Audio": "webaudio",
    "Standalone": "standalone",
    "Csound": "csound",
}

# build-examples.yml runner -> host
RUNNER_HOSTS = {
    "ubuntu-latest": "linux",
    "macos-latest": "macos",
    "windows-latest": "windows",
}


@pytest.mark.parametrize("name", list_platforms())
def test_platform_declares_support(name):
    p = get_platform(name)
    assert p.kind in KINDS
    assert set(p.build_hosts) == set(HOSTS)
    for support in p.build_hosts.values():
        assert support.status in STATUSES
        if support.status in ("unsupported", "verified"):
            assert support.note, f"{name}: {support.status} needs a note"
    assert set(p.artifacts) <= {*HOSTS, "any"}
    buildable = [h for h in HOSTS if p.build_hosts[h].status != "unsupported"]
    assert "any" in p.artifacts or set(buildable) <= set(p.artifacts)
    assert p.runtime.name
    if p.kind == "cross":
        assert p.runtime.devices or p.list_boards()


@pytest.mark.parametrize("name", list_platforms())
def test_extension_follows_artifacts(name):
    p = get_platform(name)
    assert p.extension == p.artifacts.get(host_os(), p.artifacts.get("any", ""))


def test_json_is_versioned_and_complete():
    data = json.loads(json.dumps(platform_support()))
    assert data["schema_version"] == 1
    assert set(data["platforms"]) == set(list_platforms())
    circle = data["platforms"]["circle"]
    assert "pi3-i2s" in circle["runtime"]["devices"]


def test_json_omits_artifacts_for_unsupported_hosts():
    max_ = platform_support()["platforms"]["max"]
    assert max_["build_hosts"]["linux"]["status"] == "unsupported"
    assert "linux" not in max_["artifacts"]


def test_cli_platforms_json(capsys):
    assert main(["platforms", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == platform_support()


def test_cli_platforms_table(capsys):
    assert main(["platforms"]) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0].split()[:5] == [
        "PLATFORM",
        "KIND",
        "LINUX",
        "MACOS",
        "WINDOWS",
    ]
    assert len(out.splitlines()) == len(list_platforms()) + 1


def test_readme_table_matches_metadata():
    """README's OS columns must show each platform's declared status."""
    plats = platform_support()["platforms"]
    seen = set()
    for line in (REPO_ROOT / "README.md").read_text().splitlines():
        cells = [c.strip() for c in line.split("|")]
        if len(cells) != 8 or cells[1] not in README_NAMES:
            continue
        key = README_NAMES[cells[1]]
        seen.add(key)
        hosts = plats[key]["build_hosts"]
        for col, host in ((2, "macos"), (3, "linux"), (4, "windows")):
            status = hosts[host]["status"]
            want = "--" if status == "unsupported" else status
            assert cells[col] == want, f"README {cells[1]} {host}"
    assert seen == set(list_platforms())


def test_build_examples_matrix_is_declared_ci():
    """Every (runner, platform) build-examples.yml runs must be declared 'ci'."""
    text = (REPO_ROOT / ".github" / "workflows" / "build-examples.yml").read_text()
    oses = re.search(r"^\s+os: \[(.*)\]$", text, re.MULTILINE)
    platforms = re.search(r"^\s+platform: \[(.*)\]$", text, re.MULTILINE)
    assert oses and platforms
    excluded = set(re.findall(r"- \{ os: ([\w-]+), platform: (\w+) \}", text))
    plats = platform_support()["platforms"]
    for runner in (o.strip() for o in oses.group(1).split(",")):
        for name in (p.strip() for p in platforms.group(1).split(",")):
            if (runner, name) in excluded:
                continue
            host = RUNNER_HOSTS[runner]
            assert plats[name]["build_hosts"][host]["status"] == "ci", (
                f"{name} is built on {runner} in CI"
            )
