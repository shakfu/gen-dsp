"""
Platform implementations for gen_dsp.

Each platform (PureData, Max/MSP, etc.) has its own implementation
of the build and project generation logic.

The PLATFORM_REGISTRY provides dynamic lookup of platforms by name,
making it easy to add new backends without modifying multiple files.
"""

from typing import Type

from gen_dsp.platforms.base import Platform
from gen_dsp.platforms.puredata import PureDataPlatform
from gen_dsp.platforms.max import MaxPlatform
from gen_dsp.platforms.chuck import ChuckPlatform
from gen_dsp.platforms.audiounit import AudioUnitPlatform
from gen_dsp.platforms.clap import ClapPlatform
from gen_dsp.platforms.vst3 import Vst3Platform
from gen_dsp.platforms.lv2 import Lv2Platform


# Registry mapping platform names to their implementation classes.
# To add a new platform:
#   1. Create platforms/newplatform.py with a class extending Platform
#   2. Import it here
#   3. Add an entry to PLATFORM_REGISTRY
PLATFORM_REGISTRY: dict[str, Type[Platform]] = {
    "pd": PureDataPlatform,
    "max": MaxPlatform,
    "chuck": ChuckPlatform,
    "au": AudioUnitPlatform,
    "clap": ClapPlatform,
    "vst3": Vst3Platform,
    "lv2": Lv2Platform,
}


def get_platform(name: str) -> Platform:
    """
    Get a platform instance by name.

    Args:
        name: Platform identifier (e.g., 'pd', 'max').

    Returns:
        Platform instance.

    Raises:
        ValueError: If platform name is not recognized.
    """
    if name not in PLATFORM_REGISTRY:
        available = ", ".join(sorted(PLATFORM_REGISTRY.keys()))
        raise ValueError(f"Unknown platform: '{name}'. Available: {available}")
    return PLATFORM_REGISTRY[name]()


def get_platform_class(name: str) -> Type[Platform]:
    """
    Get a platform class by name.

    Args:
        name: Platform identifier (e.g., 'pd', 'max').

    Returns:
        Platform class (not instantiated).

    Raises:
        ValueError: If platform name is not recognized.
    """
    if name not in PLATFORM_REGISTRY:
        available = ", ".join(sorted(PLATFORM_REGISTRY.keys()))
        raise ValueError(f"Unknown platform: '{name}'. Available: {available}")
    return PLATFORM_REGISTRY[name]


def list_platforms() -> list[str]:
    """
    List all available platform names.

    Returns:
        Sorted list of platform identifiers.
    """
    return sorted(PLATFORM_REGISTRY.keys())


def is_valid_platform(name: str) -> bool:
    """
    Check if a platform name is valid.

    Args:
        name: Platform identifier to check.

    Returns:
        True if platform exists in registry.
    """
    return name in PLATFORM_REGISTRY


__all__ = [
    "Platform",
    "PureDataPlatform",
    "MaxPlatform",
    "ChuckPlatform",
    "AudioUnitPlatform",
    "ClapPlatform",
    "Vst3Platform",
    "Lv2Platform",
    "PLATFORM_REGISTRY",
    "get_platform",
    "get_platform_class",
    "list_platforms",
    "is_valid_platform",
]
