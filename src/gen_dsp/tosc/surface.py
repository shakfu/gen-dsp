"""Build a TouchOSC control surface from a gen-dsp manifest.

py2tosc ships its own :mod:`py2tosc.surface`, which turns a list of names into
a paged layout. This module exists because a manifest carries more than names:
each parameter has a range and an initial value, and a fader that sends a bare
0-1 is only useful to a receiver that already knows what to multiply it by.
Here the range goes into the message instead, so ``/gigaverb/roomsize`` carries
the room size, and the fader starts where the plugin does.

Requires py2tosc -- install with ``pip install gen-dsp[tosc]``.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Iterator, Optional, Sequence

import py2tosc
from py2tosc import Control, Document, Value, layout, ui
from py2tosc.enums import Conversion

from gen_dsp.errors import ValidationError
from gen_dsp.tosc.addresses import OscParam, osc_params, resolve_prefix

if TYPE_CHECKING:
    from gen_dsp.core.manifest import Manifest

#: Controls per page. Four across and three down reads well on a tablet and
#: matches py2tosc's own default.
COLUMNS, ROWS = 4, 3

#: The design canvas. TouchOSC scales a layout to whatever screen opens it, so
#: this is an aspect ratio and a coordinate space rather than a pixel count --
#: but font sizes and margins are absolute within it, so it is not arbitrary.
#: A parameter surface is faders side by side, which wants the landscape shape.
SIZE = (568, 320)

#: Caption text size as a fraction of the box holding it, and the range it is
#: clamped to. Captions are sized from their resolved frame rather than fixed,
#: so a different canvas or page density does not leave the text behind.
TEXT_RATIO = 0.55
TEXT_RANGE = (6, 32)

#: Faders are shaded across a page so that neighbours stay distinguishable at
#: a glance. The endpoints are py2tosc's.
GRADIENT = ("#264653", "#e76f51")


def build_surface(
    manifest: "Manifest",
    *,
    prefix: Optional[str] = None,
    osc: bool = True,
    midi: bool = True,
    columns: int = COLUMNS,
    rows: int = ROWS,
    size: tuple[int, int] = SIZE,
) -> Document:
    """Lay a manifest's parameters out across as many pages as they need.

    Each parameter becomes a fader captioned with its host name. An OSC
    binding sends the fader's position scaled into the parameter's declared
    range; a MIDI binding sends it as a control change, numbered by parameter
    index, which a host can MIDI-learn onto the same parameter.

    Args:
        manifest: The plugin manifest.
        prefix: OSC namespace for every address. Defaults to the manifest's
            ``gen_name``.
        osc: Whether to give each control an OSC address.
        midi: Whether to bind each control to a MIDI CC.
        columns: Controls across each page.
        rows: Controls down each page.
        size: The design canvas, as ``(width, height)``.

    Returns:
        The document, resolved and ready to save.

    Raises:
        ValidationError: If the manifest has no parameters, if neither binding
            is wanted, or if the page geometry is degenerate.
    """
    if not manifest.params:
        raise ValidationError(
            "the manifest has no parameters, so there is nothing to put on a "
            "control surface"
        )
    if not osc and not midi:
        raise ValidationError(
            "A surface with neither OSC nor MIDI bindings would do nothing."
        )
    if columns < 1 or rows < 1:
        raise ValidationError(
            f"Page geometry must be at least 1x1, got {columns}x{rows}."
        )
    width, height = size
    if width < 1 or height < 1:
        raise ValidationError(f"Canvas must be at least 1x1, got {width}x{height}.")

    params = osc_params(manifest, prefix)
    title = resolve_prefix(manifest, prefix).rsplit("/", 1)[-1] or manifest.gen_name

    pager = ui.pager(*_pages(params, osc, midi, columns, rows), name=title)
    # The pager cannot be the root: TouchOSC treats the root node as the canvas
    # and gives it none of its type's behaviour, so a PAGER there would draw a
    # tab bar and then stack every page instead of paging between them.
    doc = Document(
        root=ui.stack(pager, name=title, frame=(0, 0, width, height))
    ).resolve()
    _fit_text(doc)
    return doc


def write_surface(
    manifest: "Manifest",
    path: Path,
    **kwargs: object,
) -> Path:
    """Build a surface and write it to ``path``.

    The extension decides the format: ``.tosc`` writes the compressed binary
    TouchOSC opens, ``.xml`` writes the readable form. Keyword arguments are
    passed through to :func:`build_surface`.

    Returns:
        The path written.
    """
    doc = build_surface(manifest, **kwargs)  # type: ignore[arg-type]
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)
    return path


def _pages(
    params: Sequence[OscParam],
    osc: bool,
    midi: bool,
    columns: int,
    rows: int,
) -> Iterator[Control]:
    """Chunk the parameters into one tiled page each."""
    per_page = columns * rows
    shades = layout.gradient(*GRADIENT, per_page)

    for first in range(0, len(params), per_page):
        chunk = params[first : first + per_page]
        yield ui.tiles(
            *(_strip(param, osc, midi, shades[i]) for i, param in enumerate(chunk)),
            columns=columns,
            rows=rows,
            gap=8,
            pad=8,
            name=f"{first + 1}-{first + len(chunk)}",
        )


def _strip(param: OscParam, osc: bool, midi: bool, color: object) -> Control:
    """One parameter: a fader over a caption carrying its host name."""
    control = py2tosc.fader(
        name=param.slug,
        color=color,
        values=[
            Value("x", default=param.normalized_default),
            Value("touch", default=False),
        ],
    )
    if osc:
        control.messages.append(
            ui.osc(
                param.address,
                args=[
                    ui.value(
                        "x",
                        conversion=Conversion.FLOAT,
                        scale=(param.min, param.max),
                    )
                ],
            )
        )
    if midi and param.cc is not None:
        control.messages.append(ui.midi_cc(param.cc))

    caption = py2tosc.label(
        name=f"{param.slug}Caption",
        color=color,
        background=False,
        interactive=False,
        values=[Value("text", default=param.name), Value("touch", default=False)],
    )
    return ui.column(control, caption, sizes=(6, 1), name=param.slug, color=color)


def _fit_text(doc: Document) -> None:
    """Size every caption to the box ``resolve`` gave it.

    A fixed text size only suits one canvas, and the frames are not known until
    the layout resolves, so this runs afterwards and reads them.
    """
    low, high = TEXT_RANGE
    for control in doc.walk():
        if str(control.get("name", "")).endswith("Caption"):
            size = round(control.frame.h * TEXT_RATIO)
            control.text_size = max(low, min(high, size))
