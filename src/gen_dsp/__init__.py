"""
gen_dsp - Generate PureData and Max/MSP externals from Max gen~ exports.

This package provides tools to:
- Parse gen~ exports and detect buffers, I/O counts, and platform issues
- Generate project structures for PureData and Max/MSP externals
- Apply platform-specific patches (e.g., exp2f -> exp2 on macOS)
- Build externals using the appropriate build system
"""

from gen_dsp.core.parser import GenExportParser
from gen_dsp.core.project import ProjectGenerator
from gen_dsp.core.patcher import Patcher
from gen_dsp.core.builder import Builder
from gen_dsp.errors import GenExtError

__version__ = "0.1.11"

__all__ = [
    "__version__",
    "GenExportParser",
    "ProjectGenerator",
    "Patcher",
    "Builder",
    "GenExtError",
]
