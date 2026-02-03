"""
gen_ext - Generate PureData and Max/MSP externals from Max gen~ exports.

This package provides tools to:
- Parse gen~ exports and detect buffers, I/O counts, and platform issues
- Generate project structures for PureData and Max/MSP externals
- Apply platform-specific patches (e.g., exp2f -> exp2 on macOS)
- Build externals using the appropriate build system
"""

__version__ = "0.8.0"

from gen_ext.core.parser import GenExportParser
from gen_ext.core.project import ProjectGenerator
from gen_ext.core.patcher import Patcher
from gen_ext.core.builder import Builder
from gen_ext.errors import GenExtError

__all__ = [
    "__version__",
    "GenExportParser",
    "ProjectGenerator",
    "Patcher",
    "Builder",
    "GenExtError",
]
