"""
Template access utilities for gen_dsp.

Templates are bundled with the package and accessed via these utilities.
"""

from pathlib import Path

_TEMPLATES_ROOT = Path(__file__).parent


def get_templates_dir(platform: str = "") -> Path:
    """Get the path to a platform's templates directory.

    Args:
        platform: Platform subdirectory name (e.g. "pd", "clap").
                  If empty, returns the root templates directory.

    Returns:
        Path to the templates directory.
    """
    if platform:
        return _TEMPLATES_ROOT / platform
    return _TEMPLATES_ROOT


# Backward-compatible aliases (one per platform)
def get_pd_templates_dir() -> Path:
    return get_templates_dir("pd")


def get_max_templates_dir() -> Path:
    return get_templates_dir("max")


def get_chuck_templates_dir() -> Path:
    return get_templates_dir("chuck")


def get_au_templates_dir() -> Path:
    return get_templates_dir("au")


def get_clap_templates_dir() -> Path:
    return get_templates_dir("clap")


def get_vst3_templates_dir() -> Path:
    return get_templates_dir("vst3")


def get_lv2_templates_dir() -> Path:
    return get_templates_dir("lv2")


def get_sc_templates_dir() -> Path:
    return get_templates_dir("sc")


def get_vcvrack_templates_dir() -> Path:
    return get_templates_dir("vcvrack")


def get_daisy_templates_dir() -> Path:
    return get_templates_dir("daisy")


def get_circle_templates_dir() -> Path:
    return get_templates_dir("circle")
