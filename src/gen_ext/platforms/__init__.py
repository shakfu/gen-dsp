"""
Platform implementations for gen_ext.

Each platform (PureData, Max/MSP) has its own implementation
of the build and project generation logic.
"""

from gen_ext.platforms.base import Platform
from gen_ext.platforms.puredata import PureDataPlatform
from gen_ext.platforms.max import MaxPlatform

__all__ = [
    "Platform",
    "PureDataPlatform",
    "MaxPlatform",
]
