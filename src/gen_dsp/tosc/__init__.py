"""TouchOSC control surfaces generated from a gen-dsp manifest.

A manifest already describes every parameter a plugin exposes -- name, range,
initial value -- which is most of what a control surface needs. This subpackage
turns that into a ``.tosc`` layout: one fader per parameter, each sending its
value over OSC scaled into the parameter's real range, and as a MIDI control
change numbered by parameter index for hosts that MIDI-learn.

Building the layout requires py2tosc::

    pip install gen-dsp[tosc]

The receiver half (:mod:`gen_dsp.tosc.receivers`) has no such requirement --
the Pd patch and the sclang script are plain text, and both are addressed from
:mod:`gen_dsp.tosc.addresses` so that they agree with the layout by
construction.
"""

from gen_dsp.tosc.addresses import (
    OscParam,
    default_prefix,
    osc_namespace,
    osc_params,
    osc_slug,
    resolve_prefix,
)
from gen_dsp.tosc.receivers import (
    DEFAULT_PORT,
    SC_LANG_PORT,
    generate_pd_receiver,
    generate_sc_receiver,
    receiver_for_platform,
)

_AVAILABLE = False

try:
    import py2tosc as _py2tosc  # noqa: F401
except ImportError:
    # py2tosc is this subpackage's only optional dependency. If it is missing,
    # layout generation is unavailable (handled gracefully by _require_tosc).
    # Import errors from the surface module itself are real bugs and must NOT
    # be swallowed, so its import happens in the else branch below.
    pass
else:
    from gen_dsp.tosc.surface import (
        COLUMNS,
        ROWS,
        SIZE,
        build_surface,
        write_surface,
    )

    _AVAILABLE = True


def _require_tosc() -> None:
    """Raise ImportError with install instructions if py2tosc is unavailable."""
    if not _AVAILABLE:
        raise ImportError(
            "TouchOSC layout generation requires py2tosc. "
            "Install with: pip install gen-dsp[tosc]"
        )


__all__ = [
    "_AVAILABLE",
    "_require_tosc",
    "COLUMNS",
    "DEFAULT_PORT",
    "OscParam",
    "ROWS",
    "SC_LANG_PORT",
    "SIZE",
    "build_surface",
    "default_prefix",
    "generate_pd_receiver",
    "generate_sc_receiver",
    "osc_namespace",
    "osc_params",
    "osc_slug",
    "receiver_for_platform",
    "resolve_prefix",
    "write_surface",
]
