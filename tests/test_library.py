"""Tests for the .gdsp library and import roots."""

import json
import platform
from pathlib import Path

import pytest

from gen_dsp.cli import main
from gen_dsp.graph.dsl import GDSPCompileError, parse, parse_file, parse_multi
from gen_dsp.graph.validate import validate_graph
from gen_dsp.library import (
    STD_DIR,
    default_import_roots,
    library_index,
    save_user_component,
    user_library_dir,
)

STD_FILES = sorted(STD_DIR.rglob("*.gdsp"))


@pytest.fixture(autouse=True)
def _user_dir(monkeypatch, tmp_path: Path) -> Path:
    user = tmp_path / "user"
    monkeypatch.setenv("GEN_DSP_LIBRARY_DIR", str(user))
    return user


def _importing(path: str) -> str:
    return f'graph g {{\n in x\n z = import "{path}"(input=x)\n out y = z\n}}\n'


# -- import roots -------------------------------------------------------------


class TestImportRoots:
    def test_root_import_resolves(self):
        g = parse(
            _importing("std:components/filters/lpf.gdsp"),
            import_roots=default_import_roots(),
        )
        assert g.name == "g"

    @pytest.mark.parametrize(
        "path",
        [
            "/etc/hostname",
            "../outside.gdsp",
            "sibling.gdsp",
            "nope:x.gdsp",
        ],
    )
    def test_plain_and_unknown_paths_refused(self, path):
        with pytest.raises(GDSPCompileError, match="import must be '<root>:<path>'"):
            parse(_importing(path), import_roots=default_import_roots())

    @pytest.mark.parametrize(
        "path", ["std:../../../../../../etc/hostname", "std:/etc/hostname"]
    )
    def test_escape_refused(self, path):
        with pytest.raises(GDSPCompileError, match="escapes the 'std' root"):
            parse(_importing(path), import_roots=default_import_roots())

    def test_outside_file_is_never_read(self, tmp_path: Path):
        """The original leak: a refused import must not echo the file's tokens."""
        secret = tmp_path / "secret.txt"
        secret.write_text("topsecret token\n")
        with pytest.raises(GDSPCompileError) as e:
            parse(_importing(str(secret)), import_roots={"std": STD_DIR})
        assert "topsecret" not in str(e.value)

    def test_symlink_escape_refused(self, tmp_path: Path):
        root = tmp_path / "root"
        root.mkdir()
        outside = tmp_path / "outside.gdsp"
        outside.write_text("graph o {\n in input\n out output = input\n}\n")
        (root / "link.gdsp").symlink_to(outside)
        with pytest.raises(GDSPCompileError, match="escapes"):
            parse(_importing("r:link.gdsp"), import_roots={"r": root})

    def test_nested_imports_are_checked(self, tmp_path: Path):
        root = tmp_path / "root"
        root.mkdir()
        (root / "a.gdsp").write_text(
            _importing("../b.gdsp").replace("graph g", "graph a")
        )
        with pytest.raises(GDSPCompileError, match="import must be"):
            parse(_importing("r:a.gdsp"), import_roots={"r": root})

    def test_missing_file_hides_resolved_path(self):
        with pytest.raises(GDSPCompileError) as e:
            parse(_importing("std:nope.gdsp"), import_roots=default_import_roots())
        assert str(STD_DIR) not in str(e.value)

    def test_without_roots_paths_still_work(self, tmp_path: Path):
        lib = tmp_path / "lpf.gdsp"
        lib.write_text((STD_DIR / "components/filters/lpf.gdsp").read_text())
        assert parse_multi(_importing(str(lib)))["g"].name == "g"

    def test_parse_file_registers_std_and_keeps_paths(self, tmp_path: Path):
        (tmp_path / "local.gdsp").write_text(
            "graph local {\n in input\n out output = input\n}\n"
        )
        main_src = (
            "graph g {\n in x\n"
            ' a = import "std:components/filters/lpf.gdsp"(input=x)\n'
            ' b = import "local.gdsp"(input=a)\n'
            " out y = b\n}\n"
        )
        (tmp_path / "main.gdsp").write_text(main_src)
        g = parse_file(tmp_path / "main.gdsp")
        assert g.name == "g"


# -- user library location ----------------------------------------------------


class TestUserLibraryDir:
    def test_env_override(self, _user_dir: Path):
        assert user_library_dir() == _user_dir

    @pytest.mark.parametrize(
        "system, env, expected",
        [
            ("Linux", {"XDG_DATA_HOME": "/xdg"}, "/xdg/gen-dsp/library"),
            ("Windows", {"APPDATA": "/appdata"}, "/appdata/gen-dsp/library"),
        ],
    )
    def test_os_defaults(self, monkeypatch, system, env, expected):
        monkeypatch.delenv("GEN_DSP_LIBRARY_DIR")
        monkeypatch.setattr(platform, "system", lambda: system)
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        assert user_library_dir() == Path(expected)

    def test_macos_default(self, monkeypatch):
        monkeypatch.delenv("GEN_DSP_LIBRARY_DIR")
        monkeypatch.setattr(platform, "system", lambda: "Darwin")
        assert user_library_dir() == (
            Path.home() / "Library" / "Application Support" / "gen-dsp" / "library"
        )


# -- std library --------------------------------------------------------------


@pytest.mark.parametrize("path", STD_FILES, ids=lambda p: p.stem)
def test_std_file_compiles_strictly(path: Path):
    """Library files use root imports only and form valid graphs."""
    g = parse(path.read_text(), import_roots=default_import_roots())
    assert validate_graph(g) == []


def test_std_has_examples_and_components():
    rels = {p.relative_to(STD_DIR).parts[0] for p in STD_FILES}
    assert rels == {"examples", "components"}


# -- index ----------------------------------------------------------------------


class TestIndex:
    def test_covers_every_std_file(self):
        entries = library_index()["entries"]
        assert len(entries) == len(STD_FILES)
        assert all("error" not in e for e in entries)

    def test_entry_shape(self):
        (lpf,) = [
            e
            for e in library_index()["entries"]
            if e["id"] == "std:components/filters/lpf"
        ]
        assert lpf["kind"] == "component"
        assert lpf["category"] == "filters"
        assert lpf["graph"] == "lpf"
        assert lpf["inputs"] == ["input"]
        assert lpf["params"] == [
            {"name": "coeff", "min": 0.0, "max": 1.0, "default": 0.3}
        ]
        assert lpf["description"].startswith("One-pole lowpass")

    @pytest.mark.parametrize(
        "entry",
        [e for e in library_index()["entries"] if e["root"] == "std"],
        ids=lambda e: e["id"],
    )
    def test_import_expr_compiles(self, entry):
        """Each ready-made import expression compiles inside a host graph."""
        decls = "".join(f" in {i}\n" for i in entry["inputs"])
        src = f"graph host {{\n{decls} z = {entry['import_expr']}\n out y = z\n}}\n"
        if len(entry["outputs"]) != 1:
            src = src.replace(" out y = z\n", f" out y = z.{entry['outputs'][0]}\n")
        parse(src, import_roots=default_import_roots())

    def test_user_entries_and_errors(self, _user_dir: Path):
        (_user_dir / "fx").mkdir(parents=True)
        (_user_dir / "fx" / "gain.gdsp").write_text(
            "# Gain.\ngraph gain {\n in input\n out output = y\n"
            " param g 0..2 = 1\n y = input * g\n}\n"
        )
        (_user_dir / "broken.gdsp").write_text("graph {")
        entries = {e["id"]: e for e in library_index()["entries"]}
        assert entries["user:fx/gain"]["category"] == "fx"
        assert entries["user:fx/gain"]["description"] == "Gain."
        assert "error" in entries["user:broken"]

    def test_cli_json(self, capsys):
        assert main(["library", "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["schema_version"] == 1
        assert data == library_index()


# -- saving -------------------------------------------------------------------

GAIN = (
    "graph gain {\n in input\n out output = y\n param g 0..2 = 1\n y = input * g\n}\n"
)


class TestSaveUserComponent:
    def test_save_and_import(self, _user_dir: Path):
        path = save_user_component("gain", GAIN, category="fx")
        assert path == _user_dir / "fx" / "gain.gdsp"
        g = parse(_importing("user:fx/gain.gdsp"), import_roots=default_import_roots())
        assert g.name == "g"

    @pytest.mark.parametrize("name", ["../gain", "a/b", "1x", "Gain", ""])
    def test_bad_name(self, name):
        with pytest.raises(ValueError, match="name"):
            save_user_component(name, GAIN)

    def test_bad_category(self):
        with pytest.raises(ValueError, match="category"):
            save_user_component("gain", GAIN, category="../x")

    def test_overwrite_needs_flag(self):
        save_user_component("gain", GAIN)
        with pytest.raises(FileExistsError):
            save_user_component("gain", GAIN)
        save_user_component("gain", GAIN.replace("= 1", "= 2"), overwrite=True)

    def test_last_graph_must_match_name(self):
        with pytest.raises(ValueError, match="expected 'other'"):
            save_user_component("other", GAIN)

    def test_path_import_refused(self, _user_dir: Path):
        with pytest.raises(ValueError, match="import must be"):
            save_user_component("g", _importing("/etc/hostname"))
        assert not _user_dir.exists()

    def test_syntax_error(self):
        with pytest.raises(ValueError):
            save_user_component("gain", "graph gain {")
