# Audio Unit v3 (AUv3)

Generates macOS AUv3 plugins as App Extensions (`.appex`) inside a host application (`.app`). Uses `cmake -G Xcode` to produce the nested bundle structure required by PluginKit for system-wide Audio Unit discovery.

**OS support:** macOS only (requires Xcode)

## Prerequisites

- Python >= 3.10
- macOS
- Xcode (full IDE, not just Command Line Tools -- needed for the CMake Xcode generator)
- CMake >= 3.19

## Quick Start

```bash
# From a gen~ export
gen-dsp ./my_export -n myeffect -p auv3
cd myeffect_auv3

# Build (uses Xcode generator)
cmake -G Xcode -B build
cmake --build build --config Release
```

## Output Structure

```text
build/Release/myeffect-Host.app/
  Contents/
    Info.plist
    MacOS/myeffect-Host
    PlugIns/
      myeffect-AUv3.appex/
        Contents/
          Info.plist          (NSExtension + AudioComponents)
          MacOS/myeffect-AUv3
```

## How It Works

1. `gen_ext_auv3.mm` (Objective-C++) implements `AUAudioUnit` subclass with `AUParameterTree` and `internalRenderBlock`
2. `_ext_auv3.cpp` wraps genlib (header isolation pattern, same as all platforms)
3. `GenDspAUv3Factory` conforms to `AUAudioUnitFactory` protocol (the extension's principal class)
4. Parameters are registered via `AUParameterTree` with bidirectional value sync; parameter events are processed in the realtime-safe render block
5. The render block pulls input (for effects) via `pullInputBlock`, processes parameter events from the linked list, then calls `wrapper_perform()`
6. Auto-detects `aufx` (effect), `augn` (generator), or `aumu` (MIDI instrument) from I/O configuration

## Discovery

After building, run the host app once to register the extension with PluginKit:

```bash
open build/Release/myeffect-Host.app
```

The AUv3 will then appear in `auval -a` and be discoverable by DAWs (Logic Pro, GarageBand, etc.).

## Differences from AUv2

| Aspect | AUv2 (`au`) | AUv3 (`auv3`) |
|--------|-------------|---------------|
| API | Raw C (`AudioComponentPlugInInterface`) | Objective-C++ (`AUAudioUnit` subclass) |
| Bundle | `.component` | `.appex` inside `.app` |
| Build | `cmake` (Makefiles) | `cmake -G Xcode` |
| Discovery | Drop into `~/Library/Audio/Plug-Ins/Components/` | Run host `.app` to register with PluginKit |
| Parameters | `kAudioUnitProperty_ParameterInfo` | `AUParameterTree` |

## Platform Key

```text
"auv3"
```
