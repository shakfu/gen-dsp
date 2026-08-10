"""Write a surface and its receiver glue into a directory.

The one place that knows what a "TouchOSC bundle" consists of, so that
``gen-dsp <export> --tosc`` and ``gen-dsp tosc <export>`` cannot drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from gen_dsp.errors import ValidationError
from gen_dsp.tosc.addresses import osc_namespace
from gen_dsp.tosc.receivers import DEFAULT_PORT, receiver_for_platform

if TYPE_CHECKING:
    from gen_dsp.core.manifest import Manifest


@dataclass
class ToscOptions:
    """How to build a surface, and what to write alongside it.

    Attributes:
        prefix: OSC namespace. None uses the plugin's name.
        port: UDP port the Pd receiver listens on. Ignored by the sclang
            receiver, which is bound to ``NetAddr.langPort``.
        osc: Whether controls carry OSC bindings.
        midi: Whether controls carry MIDI CC bindings.
        columns: Controls across each page.
        rows: Controls down each page.
        size: Design canvas, as ``(width, height)``.
        xml: Write the readable ``.xml`` form instead of a ``.tosc``.
        receivers: Whether to write the platform's receiver glue, when it has
            any.
    """

    prefix: Optional[str] = None
    port: int = DEFAULT_PORT
    osc: bool = True
    midi: bool = True
    columns: Optional[int] = None
    rows: Optional[int] = None
    size: Optional[tuple[int, int]] = None
    xml: bool = False
    receivers: bool = True


@dataclass
class ToscResult:
    """What :func:`emit` wrote."""

    surface: Path
    receivers: list[Path] = field(default_factory=list)

    @property
    def paths(self) -> list[Path]:
        return [self.surface, *self.receivers]


def emit(
    manifest: "Manifest",
    output_dir: Path,
    lib_name: str,
    *,
    platform: Optional[str] = None,
    options: Optional[ToscOptions] = None,
    filename: Optional[str] = None,
) -> ToscResult:
    """Write ``<lib_name>.tosc`` into ``output_dir``, plus any receiver glue.

    Args:
        manifest: The plugin manifest.
        output_dir: Directory to write into. Created if absent.
        lib_name: The plugin's name. Names the generated files, the OSC
            namespace, and the external the Pd receiver instantiates.
        platform: The project's target platform, which decides whether a
            receiver can be generated. None writes the layout alone.
        options: Build options. Defaults to :class:`ToscOptions`.
        filename: Overrides the surface's filename only (extension included).
            The receiver and the OSC namespace stay tied to ``lib_name``.

    Returns:
        The paths written.

    Raises:
        ImportError: If py2tosc is not installed.
        ValidationError: If the manifest cannot produce a surface.
    """
    from gen_dsp.tosc import _require_tosc

    _require_tosc()

    from gen_dsp.tosc.surface import COLUMNS, ROWS, SIZE, build_surface

    opts = options or ToscOptions()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # The namespace follows the plugin's name rather than the manifest's
    # gen_name: a gen~ export's internal name is often an artifact of how it
    # was exported ("gen_exported"), while lib_name is what the user called it
    # and what every other generated file is named after. Resolved once here so
    # the layout and the receiver cannot disagree.
    prefix = opts.prefix if opts.prefix is not None else osc_namespace(lib_name)

    try:
        doc = build_surface(
            manifest,
            prefix=prefix,
            osc=opts.osc,
            midi=opts.midi,
            columns=opts.columns if opts.columns is not None else COLUMNS,
            rows=opts.rows if opts.rows is not None else ROWS,
            size=opts.size if opts.size is not None else SIZE,
        )
    except ValidationError as e:
        # build_surface knows nothing about the plugin the manifest came from.
        raise ValidationError(
            f"cannot build a control surface for '{lib_name}': {e}"
        ) from e
    surface_path = output_dir / (
        filename or f"{lib_name}.{'xml' if opts.xml else 'tosc'}"
    )
    doc.save(surface_path)

    written: list[Path] = []
    if opts.receivers and platform is not None and opts.osc:
        receiver = receiver_for_platform(
            platform,
            manifest,
            prefix=prefix,
            port=opts.port,
            lib_name=lib_name,
        )
        if receiver is not None:
            filename, contents = receiver
            path = output_dir / filename
            path.write_text(contents, encoding="utf-8")
            written.append(path)

    return ToscResult(surface=surface_path, receivers=written)
