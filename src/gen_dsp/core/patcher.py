"""
Platform-specific patches for gen~ exports.

Handles issues like:
- exp2f -> exp2 for macOS compatibility
- GENLIB_USE_FLOAT32 guard: genlib_platform.h defines it on 32-bit ARM, and
  the build files also pass it with -D, so ARM builds warned on redefinition
"""

import re
from pathlib import Path

from gen_dsp.errors import PatchError


class PatchResult:
    """Result of applying a patch."""

    def __init__(
        self,
        file_path: Path,
        patch_name: str,
        applied: bool,
        message: str,
        original_content: str | None = None,
        new_content: str | None = None,
    ):
        self.file_path = file_path
        self.patch_name = patch_name
        self.applied = applied
        self.message = message
        self.original_content = original_content
        self.new_content = new_content

    def __repr__(self) -> str:
        status = "applied" if self.applied else "skipped"
        return f"PatchResult({self.patch_name}: {status})"


class Patcher:
    """Apply platform-specific patches to gen~ exports."""

    # Pattern to match exp2f calls
    EXP2F_PATTERN = re.compile(r"\bexp2f\s*\(")

    # An unguarded define of GENLIB_USE_FLOAT32 on its own line
    FLOAT32_DEFINE_PATTERN = re.compile(
        r"^([ \t]*)#define[ \t]+GENLIB_USE_FLOAT32[ \t]*$", re.MULTILINE
    )
    FLOAT32_GUARD = "#ifndef GENLIB_USE_FLOAT32"

    def __init__(self, target_path: Path | str):
        """
        Initialize patcher with target directory.

        Args:
            target_path: Path to the gen~ export or project directory.
        """
        self.target_path = Path(target_path).resolve()

    def apply_all(self, dry_run: bool = False) -> list[PatchResult]:
        """
        Apply all available patches.

        Args:
            dry_run: If True, don't modify files, just report what would be done.

        Returns:
            List of PatchResult objects.
        """
        results = []

        # Apply exp2f fix
        for patch in (self.apply_exp2f_fix, self.apply_float32_guard):
            result = patch(dry_run=dry_run)
            if result:
                results.append(result)

        return results

    def _find_genlib_file(self, name: str) -> Path | None:
        """Return the export's genlib header ``name``, or None if absent."""
        for path in (
            self.target_path / "gen_dsp" / name,
            self.target_path / "gen" / "gen_dsp" / name,
        ):
            if path.exists():
                return path
        return None

    def _float32_guard_needed(self, content: str) -> bool:
        return (
            self.FLOAT32_GUARD not in content
            and self.FLOAT32_DEFINE_PATTERN.search(content) is not None
        )

    def apply_float32_guard(self, dry_run: bool = False) -> PatchResult | None:
        """
        Guard genlib_platform.h's GENLIB_USE_FLOAT32 define with #ifndef.

        Args:
            dry_run: If True, don't modify the file, just report.

        Returns:
            PatchResult or None if file not found.
        """
        path = self._find_genlib_file("genlib_platform.h")
        if not path:
            return None

        content = path.read_text(encoding="utf-8")
        if not self._float32_guard_needed(content):
            return PatchResult(
                file_path=path,
                patch_name="float32_guard",
                applied=False,
                message="GENLIB_USE_FLOAT32 already guarded or not defined",
            )

        new_content = self.FLOAT32_DEFINE_PATTERN.sub(
            rf"\1{self.FLOAT32_GUARD}\n\1#define GENLIB_USE_FLOAT32\n\1#endif",
            content,
        )

        if dry_run:
            return PatchResult(
                file_path=path,
                patch_name="float32_guard",
                applied=False,
                message="Would guard GENLIB_USE_FLOAT32 with #ifndef (dry run)",
                original_content=content,
                new_content=new_content,
            )

        try:
            path.write_text(new_content, encoding="utf-8")
        except OSError as e:
            raise PatchError(f"Failed to write patched file: {e}") from e
        return PatchResult(
            file_path=path,
            patch_name="float32_guard",
            applied=True,
            message="Guarded GENLIB_USE_FLOAT32 with #ifndef",
            original_content=content,
            new_content=new_content,
        )

    def apply_exp2f_fix(self, dry_run: bool = False) -> PatchResult | None:
        """
        Apply the exp2f -> exp2 fix for macOS compatibility.

        On macOS, exp2f may not be found in the math library. The fix is to
        use exp2 instead, which works on all platforms.

        Args:
            dry_run: If True, don't modify the file, just report.

        Returns:
            PatchResult or None if file not found.
        """
        genlib_ops_path = self._find_genlib_file("genlib_ops.h")
        if not genlib_ops_path:
            return None

        content = genlib_ops_path.read_text(encoding="utf-8")

        # Check if exp2f is present
        if not self.EXP2F_PATTERN.search(content):
            return PatchResult(
                file_path=genlib_ops_path,
                patch_name="exp2f_fix",
                applied=False,
                message="No exp2f calls found (already patched or not needed)",
            )

        # Replace exp2f with exp2
        new_content = self.EXP2F_PATTERN.sub("exp2(", content)

        if dry_run:
            return PatchResult(
                file_path=genlib_ops_path,
                patch_name="exp2f_fix",
                applied=False,
                message="Would replace exp2f with exp2 (dry run)",
                original_content=content,
                new_content=new_content,
            )

        # Write the patched content
        try:
            genlib_ops_path.write_text(new_content, encoding="utf-8")
            return PatchResult(
                file_path=genlib_ops_path,
                patch_name="exp2f_fix",
                applied=True,
                message="Replaced exp2f with exp2",
                original_content=content,
                new_content=new_content,
            )
        except OSError as e:
            raise PatchError(f"Failed to write patched file: {e}") from e

    def check_patches_needed(self) -> dict[str, bool]:
        """
        Check which patches are needed without applying them.

        Returns:
            Dict mapping patch name to whether it's needed.
        """
        needed = {}

        ops = self._find_genlib_file("genlib_ops.h")
        needed["exp2f_fix"] = bool(
            ops and self.EXP2F_PATTERN.search(ops.read_text(encoding="utf-8"))
        )

        platform = self._find_genlib_file("genlib_platform.h")
        needed["float32_guard"] = bool(
            platform
            and self._float32_guard_needed(platform.read_text(encoding="utf-8"))
        )

        return needed
