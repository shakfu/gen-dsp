# Validating GEN-DSP Plugins

## Tools

- [pluginval](https://github.com/Tracktion/pluginval) - AudioUnit, VST3, LV2 --  Cross-platform open-source plugin validation tool made by the company Tracktion.

- [clap-validator](https://github.com/free-audio/clap-validator) - An open-source CLAP plugin validation tool.

- [Plugalyzer](https://github.com/shakfu/Plugalyzer) - My fork of the Command-line VST3, AU and LADSPA plugin host for easier debugging of audio plugins.

- [minihost](https://github.com/shakfu/minihost) - Minimal audio plugin host library and CLI with Python bindings. Supports VST3, AudioUnit, and LV2. Useful for probing plugin metadata, inspecting parameters, and processing audio from the command line.

## Using minihost

Install the minihost wheel into your environment, then use the CLI:

```bash
# Probe plugin metadata (format, I/O, MIDI support)
minihost probe path/to/plugin.vst3
minihost probe path/to/plugin.component
minihost probe path/to/plugin.lv2

# Full instantiation: info, parameters, bus layout
minihost info path/to/plugin.vst3
minihost params path/to/plugin.vst3
minihost buses path/to/plugin.vst3

# Process audio through a plugin
minihost process path/to/plugin.vst3 input.wav output.wav

# Scan a directory for plugins
minihost scan /Library/Audio/Plug-Ins/
```

### Notes

- **AudioUnit** plugins must be installed to `~/Library/Audio/Plug-Ins/Components/` for CoreAudio discovery. Probing from an arbitrary path will fail.
- **VST3** probe may report 0 in/0 out channels due to a JUCE limitation with `moduleinfo.json` fast scanning. Use `minihost info` (full instantiation) for accurate channel counts.
- **LV2** bundles can be probed and loaded from any path.
