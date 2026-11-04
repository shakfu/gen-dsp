"""Tests for gen_dsp.core.patcher module."""

import shutil
import subprocess
from pathlib import Path

import pytest

from gen_dsp.core.patcher import Patcher, PatchResult


class TestPatcher:
    """Tests for Patcher class."""

    def test_check_patches_needed_no_exp2f(self, gigaverb_export: Path):
        """Test checking patches when exp2f is not present."""
        patcher = Patcher(gigaverb_export)
        needed = patcher.check_patches_needed()

        # The example fixtures may or may not have exp2f
        # Just verify the method returns a dict with the expected key
        assert "exp2f_fix" in needed
        assert isinstance(needed["exp2f_fix"], bool)

    def test_apply_exp2f_fix_dry_run(self, gigaverb_export: Path, tmp_path: Path):
        """Test exp2f fix in dry run mode."""
        # Copy export to temp dir so we can modify it
        test_export = tmp_path / "test_export"
        shutil.copytree(gigaverb_export, test_export)

        # Inject exp2f into genlib_ops.h for testing
        genlib_ops = test_export / "gen_dsp" / "genlib_ops.h"
        if genlib_ops.exists():
            content = genlib_ops.read_text()
            # Replace exp2 with exp2f to simulate the issue
            content = content.replace("exp2(", "exp2f(")
            genlib_ops.write_text(content)

            patcher = Patcher(test_export)
            result = patcher.apply_exp2f_fix(dry_run=True)

            if result:
                assert result.patch_name == "exp2f_fix"
                assert not result.applied  # Dry run doesn't apply
                assert "dry run" in result.message.lower() or "Would" in result.message

                # File should not be modified
                current_content = genlib_ops.read_text()
                assert "exp2f(" in current_content

    def test_apply_exp2f_fix_actual(self, gigaverb_export: Path, tmp_path: Path):
        """Test actually applying exp2f fix."""
        # Copy export to temp dir
        test_export = tmp_path / "test_export"
        shutil.copytree(gigaverb_export, test_export)

        # Inject exp2f into genlib_ops.h
        genlib_ops = test_export / "gen_dsp" / "genlib_ops.h"
        if genlib_ops.exists():
            content = genlib_ops.read_text()
            content = content.replace("exp2(", "exp2f(")
            genlib_ops.write_text(content)

            patcher = Patcher(test_export)
            result = patcher.apply_exp2f_fix(dry_run=False)

            if result and result.applied:
                # File should be modified
                current_content = genlib_ops.read_text()
                assert "exp2f(" not in current_content
                assert "exp2(" in current_content

    def test_apply_all_patches(self, gigaverb_export: Path, tmp_path: Path):
        """Test applying all patches."""
        # Copy export to temp dir
        test_export = tmp_path / "test_export"
        shutil.copytree(gigaverb_export, test_export)

        patcher = Patcher(test_export)
        results = patcher.apply_all(dry_run=True)

        # Should return a list of results
        assert isinstance(results, list)

    def test_patcher_with_nested_gen_dir(self, tmp_path: Path):
        """Test patcher finds genlib_ops.h in gen/gen_dsp/ path."""
        # Create nested structure like a project
        project = tmp_path / "project"
        gen_dsp = project / "gen" / "gen_dsp"
        gen_dsp.mkdir(parents=True)

        genlib_ops = gen_dsp / "genlib_ops.h"
        genlib_ops.write_text("static const t_sample X = exp2f(-23.f);")

        patcher = Patcher(project)
        needed = patcher.check_patches_needed()

        assert needed["exp2f_fix"] is True


class TestFloat32Guard:
    """Tests for the GENLIB_USE_FLOAT32 #ifndef guard."""

    def _export(self, gigaverb_export: Path, tmp_path: Path) -> Path:
        test_export = tmp_path / "test_export"
        shutil.copytree(gigaverb_export, test_export)
        return test_export

    def test_fixture_needs_guard(self, gigaverb_export: Path):
        assert Patcher(gigaverb_export).check_patches_needed()["float32_guard"] is True

    def test_dry_run_leaves_file(self, gigaverb_export: Path, tmp_path: Path):
        export = self._export(gigaverb_export, tmp_path)
        header = export / "gen_dsp" / "genlib_platform.h"
        before = header.read_text()

        result = Patcher(export).apply_float32_guard(dry_run=True)

        assert result is not None and not result.applied
        assert header.read_text() == before
        assert "#ifndef GENLIB_USE_FLOAT32" in result.new_content

    def test_apply_guards_define_once(self, gigaverb_export: Path, tmp_path: Path):
        export = self._export(gigaverb_export, tmp_path)
        header = export / "gen_dsp" / "genlib_platform.h"

        assert Patcher(export).apply_float32_guard().applied
        content = header.read_text()
        assert (
            "#ifndef GENLIB_USE_FLOAT32\n#define GENLIB_USE_FLOAT32\n#endif" in content
        )

        second = Patcher(export).apply_float32_guard()
        assert not second.applied
        assert header.read_text() == content
        assert Patcher(export).check_patches_needed()["float32_guard"] is False

    def test_apply_all_includes_guard(self, gigaverb_export: Path, tmp_path: Path):
        export = self._export(gigaverb_export, tmp_path)
        names = {r.patch_name for r in Patcher(export).apply_all() if r.applied}
        assert "float32_guard" in names

    def test_no_platform_header(self, tmp_path: Path):
        (tmp_path / "gen_dsp").mkdir()
        assert Patcher(tmp_path).apply_float32_guard() is None
        assert Patcher(tmp_path).check_patches_needed()["float32_guard"] is False

    def test_guarded_header_compiles_without_warning(
        self, gigaverb_export: Path, tmp_path: Path
    ):
        """The guarded define plus -DGENLIB_USE_FLOAT32 must not warn on ARM."""
        cxx = shutil.which("clang++")
        if cxx is None:
            pytest.skip("clang++ not found")
        export = self._export(gigaverb_export, tmp_path)
        Patcher(export).apply_float32_guard()
        src = tmp_path / "t.cpp"
        src.write_text('#include "genlib_platform.h"\n')
        proc = subprocess.run(
            [
                cxx,
                "--target=armv7a-linux-gnueabihf",
                "-fsyntax-only",
                "-Werror",
                "-DGENLIB_USE_FLOAT32",
                f"-I{export / 'gen_dsp'}",
                str(src),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, proc.stderr


class TestPatchResult:
    """Tests for PatchResult class."""

    def test_patch_result_repr_applied(self):
        """Test PatchResult repr when applied."""
        result = PatchResult(
            file_path=Path("/test/file.h"),
            patch_name="test_patch",
            applied=True,
            message="Applied successfully",
        )
        repr_str = repr(result)
        assert "test_patch" in repr_str
        assert "applied" in repr_str

    def test_patch_result_repr_skipped(self):
        """Test PatchResult repr when skipped."""
        result = PatchResult(
            file_path=Path("/test/file.h"),
            patch_name="test_patch",
            applied=False,
            message="Skipped",
        )
        repr_str = repr(result)
        assert "test_patch" in repr_str
        assert "skipped" in repr_str
