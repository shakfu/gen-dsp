"""
Parser for gen~ exported code.

Analyzes gen~ exports to detect:
- Export name (from .cpp/.h filenames)
- Buffer names (via regex patterns)
- I/O counts (from gen_kernel_numins/numouts)
- Platform-specific issues (exp2f)
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from gen_dsp.errors import ParseError


@dataclass
class ExportInfo:
    """Information extracted from a gen~ export."""

    # Export name (base name of .cpp/.h files, also the namespace)
    name: str

    # Path to the export directory
    path: Path

    # Number of signal inputs
    num_inputs: int = 0

    # Number of signal outputs
    num_outputs: int = 0

    # Number of parameters
    num_params: int = 0

    # Detected buffer names (from buffer.dim, buffer.read(, buffer.write( patterns)
    buffers: list[str] = field(default_factory=list)

    # Whether exp2f issue is present (needs patching on macOS)
    has_exp2f_issue: bool = False

    # Path to the main .cpp file
    cpp_path: Optional[Path] = None

    # Path to the main .h file
    h_path: Optional[Path] = None

    # Path to genlib_ops.h (where exp2f issue occurs)
    genlib_ops_path: Optional[Path] = None


class GenExportParser:
    """Parser for gen~ exported code directories."""

    # Patterns for detecting buffer usage
    # These patterns match: buffer.dim, buffer.read(, buffer.write(, buffer.channels
    BUFFER_DIM_PATTERN = re.compile(r"\b(\w+)\.dim\b")
    BUFFER_READ_PATTERN = re.compile(r"\b(\w+)\.read\s*\(")
    BUFFER_WRITE_PATTERN = re.compile(r"\b(\w+)\.write\s*\(")
    BUFFER_CHANNELS_PATTERN = re.compile(r"\b(\w+)\.channels\b")

    # Pattern for I/O counts
    NUMINS_PATTERN = re.compile(r"int\s+gen_kernel_numins\s*=\s*(\d+)")
    NUMOUTS_PATTERN = re.compile(r"int\s+gen_kernel_numouts\s*=\s*(\d+)")

    # Pattern for num_params
    NUMPARAMS_PATTERN = re.compile(r"int\s+num_params\s*\(\s*\)\s*\{\s*return\s+(\d+)")

    # Pattern for exp2f issue
    EXP2F_PATTERN = re.compile(r"\bexp2f\s*\(")

    # Known non-buffer identifiers that match buffer patterns
    # These are genlib internal variables, not user buffers
    EXCLUDED_IDENTIFIERS = frozenset(
        {
            "m_delay",
            "index",
            "this",
            "self",
            "__commonstate",
        }
    )

    def __init__(self, export_path: str | Path):
        """
        Initialize parser with path to gen~ export directory.

        Args:
            export_path: Path to directory containing exported gen~ code.
                         Should contain a .cpp/.h file pair and gen_dsp/ subdirectory.
        """
        self.export_path = Path(export_path).resolve()
        if not self.export_path.is_dir():
            raise ParseError(f"Export path is not a directory: {self.export_path}")

    def parse(self) -> ExportInfo:
        """
        Parse the gen~ export and extract information.

        Returns:
            ExportInfo with detected information.

        Raises:
            ParseError: If export cannot be parsed.
        """
        # Find the main .cpp and .h files
        cpp_path, h_path = self._find_main_files()

        # Extract export name from filename
        name = cpp_path.stem

        # Create initial info
        info = ExportInfo(
            name=name,
            path=self.export_path,
            cpp_path=cpp_path,
            h_path=h_path,
        )

        # Read the .cpp file content
        cpp_content = cpp_path.read_text(encoding="utf-8")

        # Extract I/O counts
        info.num_inputs = self._extract_numins(cpp_content)
        info.num_outputs = self._extract_numouts(cpp_content)
        info.num_params = self._extract_numparams(cpp_content)

        # Detect buffers
        info.buffers = self._detect_buffers(cpp_content)

        # Check for exp2f issue in genlib_ops.h
        info.genlib_ops_path, info.has_exp2f_issue = self._check_exp2f_issue()

        return info

    def _find_main_files(self) -> tuple[Path, Path]:
        """
        Find the main .cpp and .h file pair in the export directory.

        Returns:
            Tuple of (cpp_path, h_path).

        Raises:
            ParseError: If files cannot be found.
        """
        # Look for .cpp files in the export directory (not genlib files)
        cpp_files = [
            f
            for f in self.export_path.glob("*.cpp")
            if f.name != "genlib.cpp" and f.parent.name != "gen_dsp"
        ]

        if not cpp_files:
            raise ParseError(
                f"No gen~ export .cpp file found in {self.export_path}. "
                "Expected a file like 'gen_exported.cpp' or similar."
            )

        if len(cpp_files) > 1:
            # Try to find the one that's not a genlib file
            cpp_files = [f for f in cpp_files if "genlib" not in f.name.lower()]

        if len(cpp_files) != 1:
            raise ParseError(
                f"Expected exactly one gen~ export .cpp file, found: "
                f"{[f.name for f in cpp_files]}"
            )

        cpp_path = cpp_files[0]
        h_path = cpp_path.with_suffix(".h")

        if not h_path.exists():
            raise ParseError(f"Header file not found: {h_path}")

        return cpp_path, h_path

    def _extract_numins(self, content: str) -> int:
        """Extract number of signal inputs from gen_kernel_numins."""
        match = self.NUMINS_PATTERN.search(content)
        if match:
            return int(match.group(1))
        return 0

    def _extract_numouts(self, content: str) -> int:
        """Extract number of signal outputs from gen_kernel_numouts."""
        match = self.NUMOUTS_PATTERN.search(content)
        if match:
            return int(match.group(1))
        return 0

    def _extract_numparams(self, content: str) -> int:
        """Extract number of parameters from num_params()."""
        match = self.NUMPARAMS_PATTERN.search(content)
        if match:
            return int(match.group(1))
        return 0

    def _detect_buffers(self, content: str) -> list[str]:
        """
        Detect buffer names from the gen~ export.

        Looks for patterns like:
        - buffer.dim (accessing buffer dimension)
        - buffer.read( (reading from buffer)
        - buffer.write( (writing to buffer)
        - buffer.channels (accessing channel count)

        Returns:
            List of unique buffer names found.
        """
        candidates: set[str] = set()

        # Find all potential buffer accesses
        for pattern in [
            self.BUFFER_DIM_PATTERN,
            self.BUFFER_READ_PATTERN,
            self.BUFFER_WRITE_PATTERN,
            self.BUFFER_CHANNELS_PATTERN,
        ]:
            for match in pattern.finditer(content):
                name = match.group(1)
                # Filter out known non-buffer identifiers
                if name not in self.EXCLUDED_IDENTIFIERS:
                    # Also filter out identifiers starting with common prefixes
                    if not name.startswith(("m_", "__", "gen_")):
                        candidates.add(name)

        # Sort for consistent ordering
        return sorted(candidates)

    def _check_exp2f_issue(self) -> tuple[Optional[Path], bool]:
        """
        Check for exp2f issue in genlib_ops.h.

        Returns:
            Tuple of (path_to_genlib_ops_h, has_exp2f_issue).
        """
        gen_dsp_path = self.export_path / "gen_dsp"
        if not gen_dsp_path.is_dir():
            return None, False

        genlib_ops_path = gen_dsp_path / "genlib_ops.h"
        if not genlib_ops_path.exists():
            return None, False

        content = genlib_ops_path.read_text(encoding="utf-8")
        has_issue = bool(self.EXP2F_PATTERN.search(content))

        return genlib_ops_path, has_issue

    def validate_buffer_names(self, buffer_names: list[str]) -> list[str]:
        """
        Validate that buffer names are valid C identifiers.

        Args:
            buffer_names: List of buffer names to validate.

        Returns:
            List of invalid buffer names (empty if all valid).
        """
        invalid = []
        identifier_pattern = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

        for name in buffer_names:
            if not identifier_pattern.match(name):
                invalid.append(name)

        return invalid
