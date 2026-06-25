"""Tests for Web Audio (AudioWorklet + WASM) platform implementation."""

import shutil
import subprocess
from pathlib import Path

import pytest

from gen_dsp.core.parser import GenExportParser
from gen_dsp.core.project import ProjectGenerator, ProjectConfig
from gen_dsp.platforms import (
    PLATFORM_REGISTRY,
    WebAudioPlatform,
    get_platform,
)

# Skip integration tests if emcc not available
_has_emcc = shutil.which("emcc") is not None
_has_make = shutil.which("make") is not None
_has_node = shutil.which("node") is not None
_can_build = _has_emcc and _has_make
_can_validate = _can_build and _has_node
_skip_no_emcc = pytest.mark.skipif(not _can_build, reason="emcc or make not found")
_skip_no_validation = pytest.mark.skipif(
    not _can_validate, reason="emcc, make, or node not found"
)


_VALIDATE_JS = """\
// Node.js smoke test: load WASM module, create state, process audio,
// check for non-zero output energy and param introspection.
const path = require('path');

const LIB_NAME = process.argv[2];
const BUILD_DIR = process.argv[3];
const EXPECTED_PARAMS = parseInt(process.argv[4] || '0', 10);
const HAS_INPUTS = process.argv[5] === 'true';

async function main() {
    // Load Emscripten glue module
    const modulePath = path.join(BUILD_DIR, LIB_NAME + '.js');
    const factory = require(modulePath);
    const mod = await factory();

    // Query I/O counts
    const numInputs = mod._wa_get_num_inputs();
    const numOutputs = mod._wa_get_num_outputs();
    const numParams = mod._wa_get_num_params();

    console.log('INPUTS ' + numInputs);
    console.log('OUTPUTS ' + numOutputs);
    console.log('PARAMS ' + numParams);

    if (numParams !== EXPECTED_PARAMS) {
        console.log('PARAM_COUNT_FAIL expected=' + EXPECTED_PARAMS + ' got=' + numParams);
    }

    // Print param names
    const sr = 44100.0;
    const bs = 128;
    const statePtr = mod._wa_create(sr, bs);

    for (let i = 0; i < numParams; i++) {
        const namePtr = mod._wa_get_param_name(statePtr, i);
        const name = mod.UTF8ToString(namePtr);
        const min = mod._wa_get_param_min(statePtr, i);
        const max = mod._wa_get_param_max(statePtr, i);
        console.log('PARAM_' + i + ' ' + name + ' min=' + min + ' max=' + max);
    }

    // Allocate I/O buffers in WASM memory
    const ptrSize = 4;
    const bufBytes = bs * 4;

    let inPtrs = 0;
    const inBufs = [];
    if (numInputs > 0) {
        inPtrs = mod._malloc(numInputs * ptrSize);
        for (let i = 0; i < numInputs; i++) {
            const buf = mod._malloc(bufBytes);
            inBufs.push(buf);
            mod.HEAPU32[inPtrs / ptrSize + i] = buf;
        }
    }

    const outPtrs = mod._malloc(numOutputs * ptrSize);
    const outBufs = [];
    for (let i = 0; i < numOutputs; i++) {
        const buf = mod._malloc(bufBytes);
        outBufs.push(buf);
        mod.HEAPU32[outPtrs / ptrSize + i] = buf;
    }

    // Fill inputs with noise if this is an effect
    if (HAS_INPUTS && numInputs > 0) {
        for (let ch = 0; ch < numInputs; ch++) {
            for (let j = 0; j < bs; j++) {
                mod.HEAPF32[inBufs[ch] / 4 + j] = (Math.random() * 2 - 1) * 0.5;
            }
        }
    }

    // Process multiple blocks to let FFT/delay-based processors warm up
    const NUM_BLOCKS = 16;
    let energy = 0.0;
    for (let block = 0; block < NUM_BLOCKS; block++) {
        // Refill inputs each block for effects
        if (HAS_INPUTS && numInputs > 0) {
            for (let ch = 0; ch < numInputs; ch++) {
                for (let j = 0; j < bs; j++) {
                    mod.HEAPF32[inBufs[ch] / 4 + j] = (Math.random() * 2 - 1) * 0.5;
                }
            }
        }

        mod._wa_perform(statePtr, inPtrs, numInputs, outPtrs, numOutputs, bs);

        // Accumulate output energy from last few blocks
        if (block >= NUM_BLOCKS - 4) {
            for (let ch = 0; ch < numOutputs; ch++) {
                for (let j = 0; j < bs; j++) {
                    const s = mod.HEAPF32[outBufs[ch] / 4 + j];
                    energy += s * s;
                }
            }
        }
    }

    if (energy > 0.0) {
        console.log('AUDIO_OK energy=' + energy);
    } else {
        console.log('AUDIO_FAIL energy=' + energy);
    }

    // Cleanup
    mod._wa_destroy(statePtr);
    for (const b of inBufs) mod._free(b);
    for (const b of outBufs) mod._free(b);
    if (inPtrs) mod._free(inPtrs);
    mod._free(outPtrs);

    console.log('DONE');
}

main().catch(err => { console.error(err); process.exit(1); });
"""


def _validate_wasm(
    project_dir: Path,
    lib_name: str,
    expected_params: int,
    has_inputs: bool = True,
) -> None:
    """Load a built WASM module in Node.js and validate audio output.

    Writes a temporary JS script, runs it with node, and asserts:
    - Correct param count
    - Non-zero audio energy (AUDIO_OK)
    - Clean exit (DONE)
    """
    if not _has_node:
        return

    test_js = project_dir / "validate.js"
    test_js.write_text(_VALIDATE_JS)

    build_dir = str(project_dir / "build")
    result = subprocess.run(
        [
            "node",
            "validate.js",
            lib_name,
            build_dir,
            str(expected_params),
            "true" if has_inputs else "false",
        ],
        cwd=project_dir,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"node validate.js failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    output = result.stdout
    assert "PARAMS" in output
    assert str(expected_params) in output
    assert "AUDIO_OK" in output, f"No audio output detected:\n{output}"
    assert "DONE" in output


_VALIDATE_BUFFER_JS = """\
// Node.js test for the runtime buffer-loading bridge: introspect buffers and
// round-trip a block of samples through wa_load_buffer.
const path = require('path');

const LIB_NAME = process.argv[2];
const BUILD_DIR = process.argv[3];
const EXPECTED_BUFFERS = parseInt(process.argv[4] || '0', 10);
const EXPECTED_NAME = process.argv[5] || '';

async function main() {
    const factory = require(path.join(BUILD_DIR, LIB_NAME + '.js'));
    const mod = await factory();

    const n = mod._wa_get_num_buffers();
    console.log('NUM_BUFFERS ' + n);
    if (n !== EXPECTED_BUFFERS) {
        console.log('BUFFER_COUNT_FAIL expected=' + EXPECTED_BUFFERS + ' got=' + n);
    }

    if (n > 0) {
        const name = mod.UTF8ToString(mod._wa_get_buffer_name(0));
        console.log('BUFFER_0 ' + name);
        if (name !== EXPECTED_NAME) {
            console.log('BUFFER_NAME_FAIL expected=' + EXPECTED_NAME + ' got=' + name);
        }

        // Load a small interleaved (mono) block; must not crash.
        const frames = 64, channels = 1;
        const ptr = mod._malloc(frames * channels * 4);
        for (let i = 0; i < frames * channels; i++) {
            mod.HEAPF32[ptr / 4 + i] = Math.sin(i * 0.1);
        }
        mod._wa_load_buffer(0, ptr, frames, channels);
        mod._free(ptr);

        // Out-of-range index must be a safe no-op.
        mod._wa_load_buffer(999, ptr, frames, channels);
        console.log('LOAD_OK');
    }

    console.log('DONE');
}

main().catch(err => { console.error(err); process.exit(1); });
"""


def _validate_buffers(
    project_dir: Path,
    lib_name: str,
    expected_buffers: int,
    expected_name: str,
) -> None:
    """Build-time Node.js check of the buffer-loading bridge."""
    if not _has_node:
        return

    (project_dir / "validate_buffers.js").write_text(_VALIDATE_BUFFER_JS)
    result = subprocess.run(
        [
            "node",
            "validate_buffers.js",
            lib_name,
            str(project_dir / "build"),
            str(expected_buffers),
            expected_name,
        ],
        cwd=project_dir,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"node validate_buffers.js failed:\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    out = result.stdout
    assert "FAIL" not in out, out
    assert f"NUM_BUFFERS {expected_buffers}" in out
    if expected_buffers > 0:
        assert f"BUFFER_0 {expected_name}" in out
        assert "LOAD_OK" in out
    assert "DONE" in out


class TestWebAudioPlatform:
    """Test Web Audio platform registry and basic properties."""

    def test_registry_contains_webaudio(self):
        """Test that webaudio is in the registry."""
        assert "webaudio" in PLATFORM_REGISTRY
        assert PLATFORM_REGISTRY["webaudio"] == WebAudioPlatform

    def test_get_platform_webaudio(self):
        """Test getting Web Audio platform instance."""
        platform = get_platform("webaudio")
        assert isinstance(platform, WebAudioPlatform)
        assert platform.name == "webaudio"

    def test_webaudio_extension(self):
        """Test that extension is .wasm."""
        platform = WebAudioPlatform()
        assert platform.extension == ".wasm"

    def test_webaudio_build_instructions(self):
        """Test Web Audio build instructions."""
        platform = WebAudioPlatform()
        instructions = platform.get_build_instructions()
        assert isinstance(instructions, list)
        assert "make all" in instructions


class TestWebAudioProjectGeneration:
    """Test Web Audio project generation."""

    def test_generate_project_gigaverb(self, gigaverb_export: Path, tmp_project: Path):
        """Test generating Web Audio project from gigaverb (no buffers)."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="webaudio")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        assert project_dir.is_dir()

        # Check required files exist
        assert (project_dir / "Makefile").is_file()
        assert (project_dir / "gen_ext_webaudio.cpp").is_file()
        assert (project_dir / "_ext_webaudio.cpp").is_file()
        assert (project_dir / "_ext_webaudio.h").is_file()
        assert (project_dir / "gen_ext_common_webaudio.h").is_file()
        assert (project_dir / "webaudio_buffer.h").is_file()
        assert (project_dir / "gen_buffer.h").is_file()
        assert (project_dir / "_processor.js").is_file()
        assert (project_dir / "index.html").is_file()
        assert (project_dir / "gen").is_dir()

        # Check gen_buffer.h has 0 buffers
        buffer_h = (project_dir / "gen_buffer.h").read_text()
        assert "WRAPPER_BUFFER_COUNT 0" in buffer_h

    def test_generate_project_with_buffers(
        self, rampleplayer_export: Path, tmp_project: Path
    ):
        """Test generating Web Audio project with buffers."""
        parser = GenExportParser(rampleplayer_export)
        export_info = parser.parse()

        config = ProjectConfig(
            name="testsampler",
            platform="webaudio",
            buffers=["sample"],
        )
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        buffer_h = (project_dir / "gen_buffer.h").read_text()
        assert "WRAPPER_BUFFER_COUNT 1" in buffer_h
        assert "WRAPPER_BUFFER_NAME_0 sample" in buffer_h

    def test_buffer_loading_bridge_wired(
        self, rampleplayer_export: Path, tmp_project: Path
    ):
        """The runtime buffer-loading bridge is generated end to end."""
        export_info = GenExportParser(rampleplayer_export).parse()
        config = ProjectConfig(
            name="sampler", platform="webaudio", buffers=["sample"]
        )
        project_dir = ProjectGenerator(export_info, config).generate(tmp_project)

        # Emscripten export list includes the buffer entry points.
        makefile = (project_dir / "Makefile").read_text()
        for sym in ("_wa_load_buffer", "_wa_get_num_buffers", "_wa_get_buffer_name"):
            assert sym in makefile, f"{sym} missing from EXPORTED_FUNCTIONS"

        # C bridge defines the exports and the genlib-side loader.
        bridge = (project_dir / "gen_ext_webaudio.cpp").read_text()
        assert "void wa_load_buffer(" in bridge
        common = (project_dir / "gen_ext_common_webaudio.h").read_text()
        assert "wrapper_load_buffer" in common
        ext = (project_dir / "_ext_webaudio.cpp").read_text()
        assert "void wrapper_load_buffer(" in ext
        assert "buffer_ptrs[]" in ext

        # Worklet handles the load-buffer message; index.html builds the UI.
        procjs = (project_dir / "_processor.js").read_text()
        assert "load-buffer" in procjs
        assert "_loadBuffer" in procjs
        assert "_wa_load_buffer" in procjs
        html = (project_dir / "index.html").read_text()
        assert 'const BUFFER_NAMES = ["sample"];' in html
        assert "decodeAudioData" in html
        assert "loadBufferIntoNode" in html

    def test_no_buffer_ui_when_no_buffers(
        self, gigaverb_export: Path, tmp_project: Path
    ):
        """A patch with no buffers still wires the bridge but lists no buffers."""
        export_info = GenExportParser(gigaverb_export).parse()
        config = ProjectConfig(name="giga", platform="webaudio")
        project_dir = ProjectGenerator(export_info, config).generate(tmp_project)

        html = (project_dir / "index.html").read_text()
        assert "const BUFFER_NAMES = [];" in html
        # The export is still present (harmless), so buffer-capable patches work
        # without regenerating.
        assert "_wa_load_buffer" in (project_dir / "Makefile").read_text()

    def test_processor_js_has_param_descriptors(
        self, gigaverb_export: Path, tmp_project: Path
    ):
        """Test that _processor.js contains parameter descriptors."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="webaudio")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        processor_js = (project_dir / "_processor.js").read_text()
        assert "PARAM_DESCRIPTORS" in processor_js
        assert "registerProcessor" in processor_js
        assert "TestverbProcessor" in processor_js
        assert "'testverb'" in processor_js
        # gigaverb has params like roomsize, revtime, etc.
        assert "roomsize" in processor_js

    def test_processor_js_generator_no_inputs(
        self, gigaverb_export: Path, tmp_project: Path
    ):
        """Test _processor.js has correct I/O counts."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="webaudio")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        processor_js = (project_dir / "_processor.js").read_text()
        # gigaverb is stereo: 2 inputs, 2 outputs
        assert "NUM_INPUTS = 2" in processor_js
        assert "NUM_OUTPUTS = 2" in processor_js

    def test_makefile_has_emcc(self, gigaverb_export: Path, tmp_project: Path):
        """Test that Makefile references emcc."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="webaudio")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        makefile = (project_dir / "Makefile").read_text()
        assert "emcc" in makefile.lower()
        assert "GENLIB_USE_FLOAT32" in makefile
        assert "WEBAUDIO_EXT_NAME=testverb" in makefile
        assert "WASM=1" in makefile
        assert "MODULARIZE=1" in makefile
        assert "wa_create" in makefile
        assert "wa_perform" in makefile

    def test_gen_ext_webaudio_cpp_content(
        self, gigaverb_export: Path, tmp_project: Path
    ):
        """Test that gen_ext_webaudio.cpp has correct content."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="webaudio")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        content = (project_dir / "gen_ext_webaudio.cpp").read_text()
        assert "emscripten/emscripten.h" in content
        assert "EMSCRIPTEN_KEEPALIVE" in content
        assert "wa_create" in content
        assert "wa_destroy" in content
        assert "wa_perform" in content

    def test_index_html_content(self, gigaverb_export: Path, tmp_project: Path):
        """Test that index.html contains param sliders and audio setup."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="testverb", platform="webaudio")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        html = (project_dir / "index.html").read_text()
        assert "testverb" in html
        assert "AudioWorkletNode" in html
        assert "addModule" in html
        assert "roomsize" in html
        assert "Start Audio" in html

    def test_generate_copies_gen_export(self, gigaverb_export: Path, tmp_project: Path):
        """Test that gen~ export is copied to project."""
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="test", platform="webaudio")
        generator = ProjectGenerator(export_info, config)
        project_dir = generator.generate(tmp_project)

        gen_dir = project_dir / "gen"
        assert gen_dir.is_dir()
        assert (gen_dir / "gen_exported.cpp").is_file()
        assert (gen_dir / "gen_exported.h").is_file()
        assert (gen_dir / "gen_dsp").is_dir()
        assert (gen_dir / "gen_dsp" / "genlib.cpp").is_file()


class TestWebAudioBuildIntegration:
    """Integration tests that generate and compile to WASM.

    Skipped when emcc or make is not available.
    """

    @_skip_no_emcc
    def test_build_gigaverb(self, gigaverb_export: Path, tmp_path: Path):
        """Generate and compile gigaverb to WASM."""
        project_dir = tmp_path / "gigaverb_webaudio"
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="gigaverb", platform="webaudio")
        generator = ProjectGenerator(export_info, config)
        generator.generate(project_dir)

        result = subprocess.run(
            ["make", "all"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, (
            f"make all failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

        # Verify .wasm was produced
        wasm_files = list((project_dir / "build").glob("*.wasm"))
        assert len(wasm_files) == 1
        assert wasm_files[0].name == "gigaverb.wasm"
        assert wasm_files[0].stat().st_size > 0

        # Verify .js glue was also produced
        js_files = list((project_dir / "build").glob("*.js"))
        assert len(js_files) >= 1

    @_skip_no_emcc
    def test_build_spectraldelayfb(self, spectraldelayfb_export: Path, tmp_path: Path):
        """Generate and compile spectraldelayfb (3in/2out) to WASM."""
        project_dir = tmp_path / "spectraldelayfb_webaudio"
        parser = GenExportParser(spectraldelayfb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="spectraldelayfb", platform="webaudio")
        generator = ProjectGenerator(export_info, config)
        generator.generate(project_dir)

        result = subprocess.run(
            ["make", "all"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, (
            f"make all failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

        wasm_files = list((project_dir / "build").glob("*.wasm"))
        assert len(wasm_files) == 1
        assert wasm_files[0].stat().st_size > 0

    @_skip_no_validation
    def test_audio_gigaverb(self, gigaverb_export: Path, tmp_path: Path):
        """Build gigaverb WASM and validate audio output via Node.js."""
        project_dir = tmp_path / "gigaverb_validate"
        parser = GenExportParser(gigaverb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="gigaverb", platform="webaudio")
        generator = ProjectGenerator(export_info, config)
        generator.generate(project_dir)

        result = subprocess.run(
            ["make", "all"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, (
            f"make all failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

        _validate_wasm(project_dir, "gigaverb", expected_params=8, has_inputs=True)

    @_skip_no_validation
    def test_audio_spectraldelayfb(self, spectraldelayfb_export: Path, tmp_path: Path):
        """Build spectraldelayfb WASM (3in/2out) and validate audio via Node.js."""
        project_dir = tmp_path / "spectraldelayfb_validate"
        parser = GenExportParser(spectraldelayfb_export)
        export_info = parser.parse()

        config = ProjectConfig(name="spectraldelayfb", platform="webaudio")
        generator = ProjectGenerator(export_info, config)
        generator.generate(project_dir)

        result = subprocess.run(
            ["make", "all"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, (
            f"make all failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

        _validate_wasm(
            project_dir, "spectraldelayfb", expected_params=0, has_inputs=True
        )

    @_skip_no_validation
    def test_buffer_loading_rampleplayer(
        self, rampleplayer_export: Path, tmp_path: Path
    ):
        """Build a buffer-using patch and round-trip data through the bridge."""
        project_dir = tmp_path / "rample_buffers"
        export_info = GenExportParser(rampleplayer_export).parse()

        config = ProjectConfig(
            name="rample", platform="webaudio", buffers=["sample"]
        )
        ProjectGenerator(export_info, config).generate(project_dir)

        result = subprocess.run(
            ["make", "all"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, (
            f"make all failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

        _validate_buffers(
            project_dir, "rample", expected_buffers=1, expected_name="sample"
        )
