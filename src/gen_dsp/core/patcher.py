"""
Platform-specific patches for gen~ exports.

Handles issues like:
- exp2f -> exp2 for macOS compatibility
"""

import re
from pathlib import Path
from typing import Optional

from gen_dsp.errors import PatchError


class PatchResult:
    """Result of applying a patch."""

    def __init__(
        self,
        file_path: Path,
        patch_name: str,
        applied: bool,
        message: str,
        original_content: Optional[str] = None,
        new_content: Optional[str] = None,
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
        exp2f_result = self.apply_exp2f_fix(dry_run=dry_run)
        if exp2f_result:
            results.append(exp2f_result)

        return results

    def apply_exp2f_fix(self, dry_run: bool = False) -> Optional[PatchResult]:
        """
        Apply the exp2f -> exp2 fix for macOS compatibility.

        On macOS, exp2f may not be found in the math library. The fix is to
        use exp2 instead, which works on all platforms.

        Args:
            dry_run: If True, don't modify the file, just report.

        Returns:
            PatchResult or None if file not found.
        """
        # Look for genlib_ops.h in various locations
        possible_paths = [
            self.target_path / "gen_dsp" / "genlib_ops.h",
            self.target_path / "gen" / "gen_dsp" / "genlib_ops.h",
        ]

        genlib_ops_path = None
        for path in possible_paths:
            if path.exists():
                genlib_ops_path = path
                break

        if not genlib_ops_path:
            return None

        content = genlib_ops_path.read_text()

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
            genlib_ops_path.write_text(new_content)
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

        # Check exp2f
        possible_paths = [
            self.target_path / "gen_dsp" / "genlib_ops.h",
            self.target_path / "gen" / "gen_dsp" / "genlib_ops.h",
        ]

        for path in possible_paths:
            if path.exists():
                content = path.read_text()
                needed["exp2f_fix"] = bool(self.EXP2F_PATTERN.search(content))
                break
        else:
            needed["exp2f_fix"] = False

        return needed
