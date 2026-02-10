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


def get_chuck_templates_dir() -> Path:
    """
    Get the path to ChucK chugin templates.

    Returns:
        Path to the chuck/ templates directory.
    """
    return get_templates_dir() / "chuck"


def list_chuck_templates() -> list[Path]:
    """
    List all ChucK chugin template files.

    Returns:
        List of paths to template files.
    """
    chuck_dir = get_chuck_templates_dir()
    if not chuck_dir.is_dir():
        return []
    return list(chuck_dir.glob("*"))


def get_au_templates_dir() -> Path:
    """
    Get the path to AudioUnit templates.

    Returns:
        Path to the au/ templates directory.
    """
    return get_templates_dir() / "au"


def list_au_templates() -> list[Path]:
    """
    List all AudioUnit template files.

    Returns:
        List of paths to template files.
    """
    au_dir = get_au_templates_dir()
    if not au_dir.is_dir():
        return []
    return list(au_dir.glob("*"))


def get_clap_templates_dir() -> Path:
    """
    Get the path to CLAP plugin templates.

    Returns:
        Path to the clap/ templates directory.
    """
    return get_templates_dir() / "clap"


def list_clap_templates() -> list[Path]:
    """
    List all CLAP plugin template files.

    Returns:
        List of paths to template files.
    """
    clap_dir = get_clap_templates_dir()
    if not clap_dir.is_dir():
        return []
    return list(clap_dir.glob("*"))


def get_vst3_templates_dir() -> Path:
    """
    Get the path to VST3 plugin templates.

    Returns:
        Path to the vst3/ templates directory.
    """
    return get_templates_dir() / "vst3"


def list_vst3_templates() -> list[Path]:
    """
    List all VST3 plugin template files.

    Returns:
        List of paths to template files.
    """
    vst3_dir = get_vst3_templates_dir()
    if not vst3_dir.is_dir():
        return []
    return list(vst3_dir.glob("*"))


def get_lv2_templates_dir() -> Path:
    """
    Get the path to LV2 plugin templates.

    Returns:
        Path to the lv2/ templates directory.
    """
    return get_templates_dir() / "lv2"


def list_lv2_templates() -> list[Path]:
    """
    List all LV2 plugin template files.

    Returns:
        List of paths to template files.
    """
    lv2_dir = get_lv2_templates_dir()
    if not lv2_dir.is_dir():
        return []
    return list(lv2_dir.glob("*"))


def get_sc_templates_dir() -> Path:
    """
    Get the path to SuperCollider UGen templates.

    Returns:
        Path to the sc/ templates directory.
    """
    return get_templates_dir() / "sc"


def list_sc_templates() -> list[Path]:
    """
    List all SuperCollider UGen template files.

    Returns:
        List of paths to template files.
    """
    sc_dir = get_sc_templates_dir()
    if not sc_dir.is_dir():
        return []
    return list(sc_dir.glob("*"))


def get_vcvrack_templates_dir() -> Path:
    """
    Get the path to VCV Rack module templates.

    Returns:
        Path to the vcvrack/ templates directory.
    """
    return get_templates_dir() / "vcvrack"


def list_vcvrack_templates() -> list[Path]:
    """
    List all VCV Rack module template files.

    Returns:
        List of paths to template files.
    """
    vcvrack_dir = get_vcvrack_templates_dir()
    if not vcvrack_dir.is_dir():
        return []
    return list(vcvrack_dir.glob("*"))
