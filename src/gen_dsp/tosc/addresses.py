"""OSC naming shared by the TouchOSC layout and the receiver patches.

The layout and the receivers are generated separately but must agree on every
address, or the surface sends into nothing. Both sides therefore derive their
names from this module, which deliberately carries no dependency on py2tosc so
that the receivers remain available in a bare install.

A parameter's OSC name is not its host name. gen~ parameter names are arbitrary
text ("c/m ratio", "room size") while an OSC address reserves ``#``, ``*``,
``,``, ``/``, ``?``, ``[``, ``]``, ``{``, ``}`` and space. :func:`osc_slug`
resolves the difference, and :func:`osc_params` keeps the original name
alongside so the receivers can map an address back to the message name the
generated external actually answers to.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from gen_dsp.core.naming import uniquify_identifiers

if TYPE_CHECKING:
    from gen_dsp.core.manifest import Manifest

# MIDI control change numbers run 0-127. A parameter list can be longer than
# that; the parameters past the end go out over OSC alone.
CC_LIMIT = 128


def osc_slug(text: str, fallback: str = "param") -> str:
    """Return an OSC-safe camelCase name for one address segment.

    Anything that is not alphanumeric is dropped rather than substituted,
    because most of the punctuation gen~ allows in a parameter name is
    reserved by the OSC address grammar. ``fallback`` is returned when the
    name reduces to nothing (a parameter called ``"???"``).
    """
    words: list[str] = re.findall(r"[A-Za-z0-9]+", text)
    if not words:
        return fallback
    return words[0].lower() + "".join(word.capitalize() for word in words[1:])


def osc_namespace(text: str, fallback: str = "surface") -> str:
    """Return an OSC-safe address prefix, which may be several segments deep.

    Each segment is slugged on its own, so ``"Synth/Bank 1"`` survives as
    ``synth/bank1`` instead of collapsing into a single name.
    """
    parts = [osc_slug(part, "") for part in text.split("/") if part.strip()]
    parts = [p for p in parts if p]
    return "/".join(parts) if parts else fallback


@dataclass(frozen=True)
class OscParam:
    """One parameter as it appears on the control surface.

    Attributes:
        index: The parameter's index in the manifest.
        name: The host-side name -- the gen~ parameter name, which is also the
            message selector the Pd external answers to.
        slug: The OSC-safe, list-unique name used as the address's last segment.
        address: The full OSC address, ``/<prefix>/<slug>``.
        min: Low end of the parameter's range.
        max: High end of the parameter's range.
        default: The parameter's initial value, in range units.
        cc: The MIDI control change number, or None when the index runs past
            the 127 a CC allows.
    """

    index: int
    name: str
    slug: str
    address: str
    min: float
    max: float
    default: float
    cc: Optional[int]

    @property
    def normalized_default(self) -> float:
        """The default as a 0-1 fader position.

        A control's ``x`` value is always normalized; the range lives in the
        message's scaling, not in the control. A degenerate range (min == max,
        which gen~ emits for parameters declared without one) has no meaningful
        position, so the fader starts at the bottom.
        """
        span = self.max - self.min
        if span <= 0:
            return 0.0
        return max(0.0, min(1.0, (self.default - self.min) / span))


def default_prefix(manifest: "Manifest") -> str:
    """Return the OSC namespace a surface uses when none is given."""
    return osc_namespace(manifest.gen_name)


def resolve_prefix(manifest: "Manifest", prefix: Optional[str] = None) -> str:
    """Return the OSC namespace to use, normalized.

    Every consumer of a caller-supplied prefix goes through here. A prefix is
    user input -- ``"rig/voice 1"`` is a reasonable thing to type -- and an
    un-normalized one would reach the addresses as ``/rig/voice 1/gain`` and
    the Pd receiver as a ``route`` over two atoms. An empty string is a
    deliberate request to address at the root and survives as such.
    """
    return default_prefix(manifest) if prefix is None else osc_namespace(prefix, "")


def osc_params(manifest: "Manifest", prefix: Optional[str] = None) -> list[OscParam]:
    """Map a manifest's parameters onto OSC addresses and MIDI CC numbers.

    Slugs are disambiguated as a group: two parameters named ``"cutoff hz"``
    and ``"cutoff-hz"`` both slug to ``cutoffHz``, and two controls cannot
    share one address.

    Args:
        manifest: The plugin manifest.
        prefix: The OSC namespace to hang addresses off. Defaults to the
            manifest's ``gen_name``. An empty string addresses parameters at
            the root (``/cutoff``).

    Returns:
        One :class:`OscParam` per manifest parameter, in manifest order.
    """
    ns = resolve_prefix(manifest, prefix)
    slugs = uniquify_identifiers(
        [osc_slug(p.name, f"param{p.index}") for p in manifest.params]
    )
    result = []
    for param, slug in zip(manifest.params, slugs):
        result.append(
            OscParam(
                index=param.index,
                name=param.name,
                slug=slug,
                address=f"/{ns}/{slug}" if ns else f"/{slug}",
                min=param.min,
                max=param.max,
                default=param.default,
                cc=param.index if param.index < CC_LIMIT else None,
            )
        )
    return result
