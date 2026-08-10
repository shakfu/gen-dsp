# TouchOSC Surfaces

gen-dsp can generate a [TouchOSC](https://hexler.net/touchosc) control surface
from a plugin's parameter list, so a project ships with a tablet or phone
interface alongside its build files. Layout generation is handled by
[py2tosc](https://github.com/shakfu/py2tosc), which is an optional dependency:

```bash
pip install gen-dsp[tosc]
```

## What gets generated

Every manifest parameter becomes a fader captioned with its name, laid out four
across and three down per page, paging automatically for longer lists. Each
fader carries two bindings:

- **OSC** -- addressed `/<plugin>/<param>`, sending the fader position scaled
  into the parameter's declared range. A room-size parameter declared over
  `[0.1, 300]` sends 150, not 0.5.
- **MIDI** -- a control change numbered by parameter index, so a host's MIDI
  learn lands on the matching parameter. Parameters past index 127 have no CC
  and go out over OSC alone.

Faders start at the parameter's default value rather than at zero, so the
surface opens showing what the plugin is actually doing.

## Generating with a project

Add `--tosc` to the usual generate command:

```bash
gen-dsp path/to/export -n gigaverb -p pd --tosc
```

This writes `gigaverb.tosc` into the project directory. Two options adjust it:

| Option | Effect |
| --- | --- |
| `--tosc-prefix NS` | OSC namespace, which may be several segments deep (`rig/voice1`). Defaults to the plugin name. |
| `--tosc-port PORT` | UDP port for the generated Pd receiver. Defaults to 8000. |

All three can also be set in `gen-dsp.toml`:

```toml
source = "exports/gigaverb"
platform = "pd"
tosc = true
tosc-port = 9000
```

## Generating on its own

The `tosc` subcommand builds a surface from anything that can produce a
manifest -- a generated project, a gen~ export, a `manifest.json`, or a graph
file:

```bash
gen-dsp tosc build/gigaverb_pd          # regenerate in place
gen-dsp tosc exports/gigaverb -n gigaverb
gen-dsp tosc patch.gdsp -o surfaces/patch.tosc
```

Pointing it at a generated project reuses the platform and plugin name recorded
in the project's `.gen-dsp.json`, and writes back into that directory. Other
sources write to the current directory unless `-o` says otherwise; an `-o`
ending in `.tosc` or `.xml` names the surface file directly, and anything else
is treated as a directory.

| Option | Effect |
| --- | --- |
| `--prefix NS`, `--port PORT` | As above. |
| `--columns N`, `--rows N` | Controls per page. Defaults to 4 x 3. |
| `--size WxH` | Design canvas. Defaults to 568x320, a landscape shape suited to a row of faders. TouchOSC scales the layout to whatever screen opens it, so this sets an aspect ratio and the space controls get, not a pixel count. |
| `--no-osc`, `--no-midi` | Emit one kind of binding only. |
| `--xml` | Write the readable XML form instead of the compressed `.tosc`. |
| `--receiver pd\|sc\|none` | Override which receiver glue is written. |

## Receiving the OSC

The generated plugins do not speak OSC themselves; the surface's MIDI bindings
are the way into a plugin host. Two backends can receive OSC with no new C++,
and for those a matching receiver is generated alongside the layout.

### Pure Data

`<name>_osc.pd` is a complete, playable patch: a `netreceive -u -b <port>` /
`oscparse` chain that routes each address onto the message the external already
answers to, the external itself, and `adc~`/`dac~` wiring around it. Open it in
the project directory once the external is built.

The routing works because the Pd external accepts a message named after each
gen~ parameter. A parameter whose name contains whitespace, `;`, `,` or `$`
cannot be addressed from a Pd message box at all, so it is left out of the
routing and listed in a comment at the bottom of the patch.

### SuperCollider

`<name>_osc.scd` boots the server, wraps the generated UGen in a SynthDef whose
controls carry the parameter defaults, starts one instance, and installs an
`OSCdef` per parameter. Unlike the Pd patch it has no port of its own: sclang
listens on `NetAddr.langPort` (57120 by default), and the script prints the
actual port when it runs. Point TouchOSC at that.

### Everything else

For the plugin formats -- CLAP, VST3, AudioUnit, LV2 and the rest -- no
receiver is generated. Use the MIDI bindings with TouchOSC's MIDI output (or
TouchOSC Bridge) and MIDI-learn them in the host, or route the OSC through a
translator of your own.

## Addresses

Parameter names are arbitrary text; OSC addresses are not. Each name is reduced
to an OSC-safe camelCase segment, dropping anything outside `[A-Za-z0-9]`
because most of the punctuation gen~ permits is reserved by the OSC address
grammar:

| Parameter | Address segment |
| --- | --- |
| `bandwidth` | `bandwidth` |
| `room size` | `roomSize` |
| `c/m ratio` | `cMRatio` |

Two names that reduce to the same segment are disambiguated as a group
(`cutoffHz`, `cutoffHz_2`), so no two controls can share an address. The
receivers derive their addresses from the same code as the layout, so the two
halves agree by construction.

## Library use

```python
from gen_dsp.core.manifest import Manifest
from gen_dsp.tosc import build_surface, write_surface, generate_pd_receiver

manifest = Manifest.from_json(open("manifest.json").read())

write_surface(manifest, Path("gigaverb.tosc"), prefix="rig/voice1")
patch = generate_pd_receiver(manifest, port=9000, lib_name="gigaverb")
```

`gen_dsp.tosc.emit.emit()` is the bundle-level entry point used by the CLI; it
writes the surface and any receiver together and returns the paths.

The receiver and address modules import no py2tosc, so `generate_pd_receiver`,
`generate_sc_receiver` and `osc_params` work in a bare install. Only
`build_surface` and `write_surface` need the extra.
