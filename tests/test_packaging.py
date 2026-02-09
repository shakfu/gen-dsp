"""Tests for packaging consistency and template inclusion."""

from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]

import gen_dsp


REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"
TEMPLATES_DIR = REPO_ROOT / "src" / "gen_dsp" / "templates"

# Every platform that ships templates
EXPECTED_PLATFORMS = {"au", "chuck", "clap", "lv2", "max", "pd", "vst3"}


class TestVersionConsistency:
    """Ensure __version__ and pyproject.toml stay in sync."""

    def test_version_matches_pyproject(self):
        with open(PYPROJECT, "rb") as f:
            meta = tomllib.load(f)
        assert gen_dsp.__version__ == meta["project"]["version"]


class TestTemplateInclusion:
    """Ensure template data files are present in the source tree."""

    def test_templates_dir_exists(self):
        assert TEMPLATES_DIR.is_dir()

    def test_all_platforms_have_template_dirs(self):
        actual = {
            d.name
            for d in TEMPLATES_DIR.iterdir()
            if d.is_dir() and d.name != "__pycache__"
        }
        assert EXPECTED_PLATFORMS.issubset(actual), (
            f"Missing template dirs: {EXPECTED_PLATFORMS - actual}"
        )

    def test_template_dirs_are_not_empty(self):
        for platform in EXPECTED_PLATFORMS:
            pdir = TEMPLATES_DIR / platform
            files = list(pdir.iterdir())
            assert len(files) > 0, f"Template dir {platform}/ is empty"


class TestEntryPoint:
    """Ensure the CLI entry point is importable."""

    def test_cli_main_importable(self):
        from gen_dsp.cli import main  # noqa: F401

    def test_cli_create_parser_importable(self):
        from gen_dsp.cli import create_parser  # noqa: F401
