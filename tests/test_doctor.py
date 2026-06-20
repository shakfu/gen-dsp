"""Tests for the build-prerequisite doctor."""

import shutil

from gen_dsp.cli import main
from gen_dsp.core import doctor
from gen_dsp.platforms import list_platforms


def test_requirements_cover_all_platforms():
    """Every registered platform must have a doctor requirements entry."""
    assert set(doctor.PLATFORM_REQUIREMENTS) == set(list_platforms())


def test_diagnose_returns_one_report_per_platform():
    reports = doctor.diagnose()
    assert {r.platform for r in reports} == set(list_platforms())


def test_diagnose_single_platform():
    reports = doctor.diagnose(["pd"])
    assert len(reports) == 1
    assert reports[0].platform == "pd"


def _fake_which(present):
    """Build a shutil.which replacement where only `present` names resolve."""

    def which(name):
        return f"/usr/bin/{name}" if name in present else None

    return which


def test_ready_when_all_tools_present(monkeypatch):
    # Everything on PATH; pd needs make + a C compiler.
    monkeypatch.setattr(
        doctor.shutil, "which", _fake_which({"make", "cc", "clang", "gcc"})
    )
    (report,) = doctor.diagnose(["pd"])
    assert report.ready is True
    assert report.missing == []
    assert any(label == "make" for label, _ in report.present)


def test_not_ready_lists_missing_with_hint(monkeypatch):
    # make + git present, but no ARM toolchain -> daisy not ready.
    monkeypatch.setattr(doctor.shutil, "which", _fake_which({"make", "git"}))
    (report,) = doctor.diagnose(["daisy"])
    assert report.ready is False
    assert any(t.key == "arm-none-eabi-gcc" for t in report.missing)

    text = doctor.format_report([report])
    assert "NOT READY" in text
    assert "ARM GNU toolchain" in text  # the install hint is shown


def test_circle_accepts_either_cross_compiler(monkeypatch):
    # Only the 64-bit toolchain present: circle's combined cross-gcc is satisfied.
    monkeypatch.setattr(
        doctor.shutil, "which", _fake_which({"make", "git", "aarch64-none-elf-gcc"})
    )
    (report,) = doctor.diagnose(["circle"])
    assert report.ready is True


def test_format_report_all_ready(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(doctor.sys, "platform", "darwin")
    text = doctor.format_report(doctor.diagnose())
    assert "All platforms are ready" in text


def test_cmd_doctor_exit_code_ready(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(doctor.sys, "platform", "darwin")
    assert main(["doctor", "-p", "pd"]) == 0


def test_cmd_doctor_exit_code_not_ready(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    monkeypatch.setattr(doctor.sys, "platform", "linux")
    assert main(["doctor", "-p", "daisy"]) == 1


def test_cmd_doctor_json(monkeypatch, capsys):
    monkeypatch.setattr(doctor.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(doctor.sys, "platform", "darwin")
    rc = main(["doctor", "-p", "clap", "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    import json

    data = json.loads(out)
    assert "clap" in data
    assert data["clap"]["ready"] is True


def test_which_helper_is_used_not_cached():
    """Sanity: probes resolve real tools (shutil is the real module)."""
    assert doctor.shutil is shutil
