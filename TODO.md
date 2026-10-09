# TODO

gen-dsp can be consumed as a library by [dsp-graph](https://github.com/shakfu/dsp-graph), a React/FastAPI web IDE that imports `gen_dsp.graph.*` directly. Priorities in this document reflect both standalone CLI use and the requirements to work as a library (especially with dsp-graph).

Completed items are recorded in [CHANGELOG.md](CHANGELOG.md) rather than kept here.

---

## Critical

## High

- [ ] **Percussa SSP: JUCE format in rack** - `gvbj` (gigaverb) runs in Synthor. Load it in a
  rack slot and check the compact view and encoders; check preset save and reload.

- [ ] **Percussa SSP: JUCE format UI** - The version string overlaps the DSP readout at the top
  right of the full screen. Both are drawn by the SSP framework, not gen-dsp: the version in
  `plugins/common/ssp/EditorHost.cpp:112`, the readout in `plugins/common/engine/EngineEditor.cpp:165`.
  The fix goes in shakfu/ssp, and gen-dsp's pinned framework commit (`_FRAMEWORK_COMMIT` in
  `platforms/ssp.py`) then has to move to it.

- [ ] **Percussa SSP: remaining device checks** - silence on unpatched inputs; whether Synthor
  calls `prepare()` during playback; the JUCE format's `load into` choice (needs a patch with
  several buffers).

## Medium

### Update Dependencies

- [ ] Require making python 3.12 the minimally required version. Changes look like:

  ```text
  [project.optional-dependencies]
  graph = ["pydantic>=2.0"]
  sim = ["pydantic>=2.0", "numpy>=2.5"]
  tosc = ["py2tosc>=0.6.0"]

  [dependency-groups]
  dev = [
      "minihost>=0.11.0",
      "mypy>=2.4.0",
      "numpy>=2.5",
      "py2tosc>=0.6.0",
      "pydantic>=2.0",
      "pytest>=9.1.1",
      "pytest-cov>=7.1.0",
      "ruff>=0.16.0",
      "twine>=7.0.0",
  ]
  ```

### Web Audio backend follow-ups

- [ ] **Web Audio build integration tests** -- Currently gated by `emcc`
  availability (skipped in CI). Consider adding Emscripten to CI or a
  lightweight WASM validation step.

## Low

### Experimental

- [ ] **Drop the pydantic dependency from the graph frontend** -- Deprioritized:
  feasible, but the benefit is a truer "zero-dependency" claim rather than any
  functional gain, and dsp-graph (the primary consumer) already ships pydantic
  via FastAPI so it costs that consumer nothing today.

  Audit verified against the current tree: pydantic is used *only* as a
  tagged-union JSON codec. No validators, no `Field` constraints, no
  `ConfigDict`, no JSON-schema generation inside gen-dsp. Exactly one pydantic
  `Field` in `src/` -- `Field(discriminator="op")` (`graph/models.py:629`); the
  other ~49 `Field(` hits are an unrelated local class in the codegen layer.
  `graph/validate.py` and `core/graph.py` are already pydantic-free.

  Corrections to the earlier estimate:

  - **Test churn is smaller than assumed.** Only one test imports pydantic's
    `ValidationError` (`tests/graph/test_models.py:692`). The other 28
    references are `gen_dsp.errors.ValidationError`, which is unaffected.
  - **`model_copy(update=...)` was missed** -- 15 callsites in `transpile.py`,
    `optimize.py`, `subgraph.py`. `dataclasses.replace()` is close but not
    equivalent: `model_copy(update=)` bypasses `__init__`, `replace()` re-runs
    it. Needs a deliberate shim.
  - **`model_fields` introspection was missed** -- `dsl/lower.py:995`
    (`dataclasses.fields()` equivalent, minor).
  - **dsp-graph coupling was missed, but is survivable.** dsp-graph calls
    `TypeAdapter(Node).json_schema()` at two import-time sites
    (`convert.py:107`, `api/graph.py:167`) and uses `TypeAdapter(Node)` as a
    runtime parser (`convert.py:371`). Verified by probe: pydantic builds a
    discriminated union over stdlib dataclasses it does not own, preserving
    `$defs`, the `op` const, and int->float coercion. dsp-graph would need to
    wrap the exported bare `Node = Union[...]` as
    `Annotated[Node, Field(discriminator="op")]` itself, or it silently degrades
    to smart-union matching.

  Consequences for the plan: the 150-250 line estimate is low once `model_copy`
  semantics and a `model_dump`/`model_validate` compatibility shim are in scope,
  and this is a *coordinated* breaking change -- dsp-graph pins
  `gen-dsp[graph]>=0.3.1`, so the `[graph]` extra must survive as a no-op alias
  or that pin breaks on install. The one thing that cannot be recovered
  afterwards is pydantic's error-message quality; that is what a spike should
  actually measure.

### New Backends: Embedded / Hardware

- [ ] **Bela** - BeagleBone-based real-time audio platform. C++ API, ultra-low latency.

  - Docs: <https://learn.bela.io/>

- [ ] **Teensy Audio Library** - Arduino-compatible, popular for DIY synths.

  - Docs: <https://www.pjrc.com/teensy/td_libs_Audio.html>

- [ ] **OWL (Rebel Technology)** - Programmable guitar pedal platform with a C++ API. Similar to Daisy in concept, small but dedicated community.

  - Docs: <https://www.rebeltech.org/docs/>

### New Backends: Plugin Frameworks

- [ ] **DISTRHO Plugin Framework (DPF)** - Can build LADSPA, DSSI, LV2, VST2, VST3, and CLAP. Main value-add over current coverage is LADSPA/DSSI. JACK/Standalone mode useful for headless testing.

  - Docs: <https://distrho.github.io/DPF/>

- [ ] **JUCE (VST/AU/AAX)** - Abstracts plugin formats. AU, CLAP, VST3, and LV2 are already covered natively without JUCE, so the only real value-add is AAX (Pro Tools). Requires Avid NDA. Low priority unless Pro Tools support is specifically requested.

  - Docs: <https://juce.com/>

### New Backends: Hardware Platforms

- [ ] **Move Everything (Ableton Move)** - Unofficial framework for custom DSP on Ableton Move hardware. ARM64 Linux `.so` plugins via C plugin API v2. Key challenges: int16 stereo interleaved audio (not float), cross-compilation, stereo-only I/O. CC BY-NC-SA 4.0 license may constrain template code. Closest analog: Daisy backend.

  - Repo: <https://github.com/charlesvestal/move-everything>

  - Assessment: [docs/move-everything.md](docs/move-everything.md)

### New Backends: Game Audio

- [ ] **FMOD plugin** - Game audio middleware with a clean C DSP plugin API. Taps into game audio market that gen-dsp currently doesn't reach.

  - Docs: <https://www.fmod.com/docs/2.03/api/plugin-api.html>

- [ ] **Wwise plugin** - Audiokinetic's game audio middleware. C++ plugin API. Similar market to FMOD but different ecosystem (Unreal-heavy).

  - Docs: <https://www.audiokinetic.com/en/library/edge/?source=SDK>
