"""
Template access utilities for gen_dsp.

Templates are bundled with the package and accessed via these utilities.
"""

from pathlib import Path


def get_templates_dir() -> Path:
    """
    Get the path to the templates directory.

    Returns:
        Path to the templates directory within the package.
    """
    return Path(__file__).parent


def get_pd_templates_dir() -> Path:
    """
    Get the path to PureData templates.

    Returns:
        Path to the pd/ templates directory.
    """
    return get_templates_dir() / "pd"


def get_max_templates_dir() -> Path:
    """
    Get the path to Max/MSP templates.

    Returns:
        Path to the max/ templates directory.
    """
    max_dir = get_templates_dir() / "max"
    if not max_dir.is_dir():
        max_dir.mkdir(parents=True, exist_ok=True)
    return max_dir


def list_pd_templates() -> list[Path]:
    """
    List all PureData template files.

    Returns:
        List of paths to template files.
    """
    pd_dir = get_pd_templates_dir()
    if not pd_dir.is_dir():
        return []
    return list(pd_dir.glob("*"))


def list_max_templates() -> list[Path]:
    """
    List all Max/MSP template files.

    Returns:
        List of paths to template files.
    """
    max_dir = get_max_templates_dir()
    if not max_dir.is_dir():
        return []
    return list(max_dir.glob("*"))
