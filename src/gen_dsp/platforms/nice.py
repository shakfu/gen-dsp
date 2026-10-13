"""
nice-plug platform implementation.

Generates a Cargo project for a CLAP/VST3 plugin built with nice-plug
(https://codeberg.org/RustAudio/nice-plug), a Rust plugin framework. The
gen~ code stays C++: ``build.rs`` compiles it with the ``cc`` crate behind
a small C ABI (``gen_ext_nice.cpp``), and ``src/engine.rs`` wraps that ABI
for Rust. Rust code can then add an editor, MIDI handling or extra DSP
around the gen~ core.
"""

import hashlib
import math
import os
import shutil
import tomllib
from collections.abc import Sequence
from pathlib import Path

from gen_dsp.core.builder import BuildResult
from gen_dsp.core.manifest import Manifest, _build_remap_defs
from gen_dsp.core.midi import MidiMapping, build_midi_defines
from gen_dsp.core.project import ProjectConfig
from gen_dsp.core.support import Runtime, hosts, per_host, untested, verified
from gen_dsp.errors import BuildError, ProjectError
from gen_dsp.platforms.base import Platform, PluginCategory
from gen_dsp.templates import get_templates_dir
from gen_dsp.version import __version__

# (source in templates/nice, destination in the project) copied verbatim.
_CRATE_FILES = (
    ("engine.rs", "src/engine.rs"),
    ("editor.rs", "src/editor.rs"),
    ("xtask/Cargo.toml", "xtask/Cargo.toml"),
    ("xtask/src/main.rs", "xtask/src/main.rs"),
    ("dot_cargo/config.toml", ".cargo/config.toml"),
    ("gitignore", ".gitignore"),
)

# Names Cargo refuses as package names: Rust keywords and built-in crates.
_RESERVED_CRATE_NAMES = frozenset(
    [
        "abstract",
        "as",
        "async",
        "await",
        "become",
        "box",
        "break",
        "const",
        "continue",
        "crate",
        "do",
        "dyn",
        "else",
        "enum",
        "extern",
        "false",
        "final",
        "fn",
        "for",
        "gen",
        "if",
        "impl",
        "in",
        "let",
        "loop",
        "macro",
        "match",
        "mod",
        "move",
        "mut",
        "override",
        "priv",
        "pub",
        "ref",
        "return",
        "self",
        "static",
        "struct",
        "super",
        "trait",
        "true",
        "try",
        "type",
        "typeof",
        "unsafe",
        "unsized",
        "use",
        "virtual",
        "where",
        "while",
        "yield",
        "alloc",
        "core",
        "proc_macro",
        "std",
        "test",
    ]
)


class NicePlatform(Platform):
    """nice-plug (Rust) CLAP/VST3 plugin platform."""

    name = "nice"
    description = "nice-plug (Rust) CLAP/VST3 plugin"
    build_system = "Cargo"
    kind = "native"
    build_hosts = hosts(
        linux=untested("nice-plug is tested upstream on Linux"),
        macos=verified("cargo xtask bundle, rustc 1.99"),
        windows=untested("nice-plug is tested upstream on Windows"),
    )
    artifacts = per_host(any=".clap")
    runtime = Runtime("CLAP or VST3 host")

    def generate_project(
        self,
        manifest: Manifest,
        output_dir: Path,
        lib_name: str,
        config: ProjectConfig | None = None,
    ) -> None:
        """Generate the Cargo project around a gen~ export."""
        templates_dir = get_templates_dir("nice")
        if not templates_dir.is_dir():
            raise ProjectError(f"nice-plug templates not found at {templates_dir}")

        for filename in (
            "gen_ext_nice.cpp",
            "gen_ext_common_nice.h",
            "_ext_nice.cpp",
            "nice_buffer.h",
        ):
            shutil.copy2(templates_dir / filename, output_dir / filename)

        self.generate_ext_header(output_dir, "nice")
        self.copy_remap_header(output_dir)
        self.copy_voice_alloc_header(output_dir, config)
        self.generate_buffer_header(
            templates_dir / "gen_buffer.h.template",
            output_dir / "gen_buffer.h",
            manifest.buffers,
            header_comment="Buffer configuration for gen_dsp nice-plug wrapper",
        )

        midi = config.midi_mapping if config else None
        defines = [
            "GEN_EXPORTED_NAME=" + manifest.gen_name,
            f'GEN_EXPORTED_HEADER="{manifest.gen_name}.h"',
            f'GEN_EXPORTED_CPP="{manifest.gen_name}.cpp"',
            *build_midi_defines(midi).split(),
            *_build_remap_defs(manifest),
        ]
        write_build_rs(
            output_dir,
            lib_name,
            cpp_sources=["gen_ext_nice.cpp", "_ext_nice.cpp", "gen/gen_dsp/genlib.cpp"],
            c_sources=["gen/gen_dsp/json.c", "gen/gen_dsp/json_builder.c"],
            includes=[".", "gen", "gen/gen_dsp"],
            defines=defines,
        )
        self.write_crate(manifest, output_dir, lib_name, midi)

    def _write_graph_platform_files(
        self,
        graph: object,
        manifest: Manifest,
        output_dir: Path,
        name: str,
        config: ProjectConfig,
    ) -> None:
        """Write the Rust crate; build.rs comes from generate_graph_build_file."""
        self.write_crate(manifest, output_dir, name, config.midi_mapping)

    def write_crate(
        self,
        manifest: Manifest,
        output_dir: Path,
        lib_name: str,
        midi: MidiMapping | None,
    ) -> None:
        """Write Cargo.toml, src/ and the xtask bundler."""
        if lib_name in _RESERVED_CRATE_NAMES:
            raise ProjectError(
                f"'{lib_name}' cannot be a Cargo package name; choose another -n"
            )
        templates_dir = get_templates_dir("nice")
        for src, dst in _CRATE_FILES:
            dest = output_dir / dst
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(templates_dir / src, dest)

        self.render_template(
            templates_dir / "Cargo.toml.template",
            output_dir / "Cargo.toml",
            label="Cargo.toml template",
            crate_name=lib_name,
            gen_name=manifest.gen_name,
            gendsp_version=__version__,
        )
        self.render_template(
            templates_dir / "lib.rs.template",
            output_dir / "src" / "lib.rs",
            label="lib.rs template",
            **_lib_rs_substitutions(manifest, lib_name, midi),
        )

    def build(
        self,
        project_dir: Path,
        clean: bool = False,
        verbose: bool = False,
    ) -> BuildResult:
        """Bundle .clap and .vst3 with ``cargo xtask bundle``."""
        if not (project_dir / "Cargo.toml").is_file():
            raise BuildError(f"Cargo.toml not found in {project_dir}")
        if clean:
            self.clean(project_dir)

        result = self.run_command(
            ["cargo", "xtask", "bundle", _crate_name(project_dir), "--release"],
            project_dir,
            verbose=verbose,
        )
        return BuildResult(
            success=result.returncode == 0,
            platform=self.name,
            output_file=self.find_output(project_dir),
            stdout=result.stdout,
            stderr=result.stderr,
            return_code=result.returncode,
        )

    def clean(self, project_dir: Path) -> None:
        """Remove this crate's build artifacts with ``cargo clean``."""
        if (project_dir / "Cargo.toml").is_file():
            self.run_command(
                ["cargo", "clean", "-p", _crate_name(project_dir)], project_dir
            )

    def find_output(self, project_dir: Path) -> Path | None:
        """Find the bundled CLAP plugin, honouring ``CARGO_TARGET_DIR``."""
        if not (project_dir / "Cargo.toml").is_file():
            return None
        target = project_dir / os.environ.get("CARGO_TARGET_DIR", "target")
        clap = target / "bundled" / f"{_crate_name(project_dir)}.clap"
        return clap if clap.exists() else None

    def get_build_instructions(self) -> list[str]:
        """Bundling commands; ``--features gui`` adds the egui editor."""
        return [
            "cargo xtask bundle <name> --release",
            "cargo xtask bundle <name> --release --features gui",
        ]


def _crate_name(project_dir: Path) -> str:
    cargo_toml = (project_dir / "Cargo.toml").read_text(encoding="utf-8")
    return str(tomllib.loads(cargo_toml)["package"]["name"])


def write_build_rs(
    output_dir: Path,
    lib_name: str,
    cpp_sources: Sequence[str],
    c_sources: Sequence[str],
    includes: Sequence[str],
    defines: Sequence[str],
) -> None:
    """Write build.rs, which compiles the C++ side with the ``cc`` crate.

    ``defines`` are ``KEY`` or ``KEY=VALUE`` strings, as for CMake.
    """
    common = ["GENLIB_USE_FLOAT32", f"NICE_EXT_NAME={lib_name}", *defines]

    def build(var: str, cpp: bool, sources: Sequence[str]) -> list[str]:
        lines = [f"    let mut {var} = cc::Build::new();"]
        lines.append(f"    {var}.cpp({'true' if cpp else 'false'})")
        if cpp:
            lines.append('        .std("c++17")')
        lines += [f"        .include({_rust_str(d)})" for d in includes]
        for d in common:
            key, sep, value = d.partition("=")
            arg = f"Some({_rust_str(value)})" if sep else "None"
            lines.append(f"        .define({_rust_str(key)}, {arg})")
        lines.append("        .warnings(false);")
        lines += [f"    {var}.file({_rust_str(s)});" for s in sources]
        lines.append(f"    {var}.compile({_rust_str(var)});")
        return lines

    body = build("gendsp", True, cpp_sources)
    if c_sources:
        body += build("gendsp_c", False, c_sources)
    # Watch the C/C++ files, not ".", which would include target/.
    watched = sorted(
        p.name for p in output_dir.iterdir() if p.suffix in (".c", ".cpp", ".h")
    )
    watched += [d for d in includes if d != "."]
    body += [f'    println!("cargo:rerun-if-changed={w}");' for w in watched]

    content = (
        f"// Compiles the gen~ C++ for {lib_name}. Generated by gen-dsp v{__version__}.\n"
        "fn main() {\n" + "\n".join(body) + "\n}\n"
    )
    (output_dir / "build.rs").write_text(content, encoding="utf-8")


def _rust_str(s: str) -> str:
    """Quote ``s`` as a Rust string literal."""
    out = []
    for ch in s:
        if ch in ('"', "\\"):
            out.append("\\" + ch)
        elif ch.isprintable():
            out.append(ch)
        else:
            out.append(f"\\u{{{ord(ch):x}}}")
    return '"' + "".join(out) + '"'


def _rust_f32(x: float, what: str) -> str:
    if not math.isfinite(x):
        raise ProjectError(f"nice-plug needs finite parameter bounds; {what} is {x}")
    return repr(float(x))


def _decimals(lo: float, hi: float) -> int:
    """Decimals for about 5 significant digits over ``[lo, hi]``.

    Full f32 precision does not survive a normalize/denormalize round trip,
    so hosts (and clap-validator) see the display string change.
    """
    magnitude = max(abs(lo), abs(hi))
    if magnitude == 0.0:
        return 4
    return min(max(4 - math.floor(math.log10(magnitude)), 0), 6)


def _lib_rs_substitutions(
    manifest: Manifest, lib_name: str, midi: MidiMapping | None
) -> dict[str, object]:
    params = sorted(manifest.params, key=lambda p: p.index)
    idents = Platform.uniquify_identifiers(
        [Platform.sanitize_c_identifier(p.name) for p in params]
    )
    fields, inits, widgets = [], [], []
    for p, ident in zip(params, idents, strict=True):
        lo = _rust_f32(p.min, f"{p.name} min")
        # A zero-width range has no normalized form; widen it to keep the host happy.
        hi = _rust_f32(p.max if p.max > p.min else p.min + 1.0, f"{p.name} max")
        default = _rust_f32(p.default, f"{p.name} default")
        name = _rust_str(p.name)
        fields.append(
            f"    #[id = {_rust_str(ident)}]\n    pub p_{ident}: FloatParam,\n"
        )
        inits.append(
            f"            p_{ident}: FloatParam::new({name}, {default}, "
            f"FloatRange::Linear {{ min: {lo}, max: {hi} }})\n"
            "                .with_value_to_string(formatters::v2s_f32_rounded("
            f"{_decimals(float(lo), float(hi))})),\n"
        )
        widgets.append(
            f"    ui.label({name});\n"
            "    ui.add(nice_plug_egui::widgets::ParamSlider::for_param("
            f"&params.p_{ident}, setter));\n"
        )
    if not widgets:
        widgets.append(
            '    let _ = (params, setter);\n    ui.label("No parameters");\n'
        )

    num_in, num_out = manifest.num_inputs, manifest.num_outputs
    if num_out < 1:
        raise ProjectError("nice-plug needs at least one audio output")
    main_in = min(num_in, num_out)
    aux_in = num_in - main_in

    generator = PluginCategory.from_num_inputs(num_in) == PluginCategory.GENERATOR
    if generator:
        clap_features = "ClapFeature::Instrument, ClapFeature::Synthesizer"
        vst3_subcategories = "Vst3SubCategory::Instrument, Vst3SubCategory::Synth"
    else:
        clap_features = "ClapFeature::AudioEffect"
        vst3_subcategories = "Vst3SubCategory::Fx"

    pascal = "".join(part[:1].upper() + part[1:] for part in lib_name.split("_"))
    return {
        "plugin_name": lib_name,
        "gen_name": manifest.gen_name,
        "gendsp_version": __version__,
        "struct_name": f"{pascal or 'Gen'}Plugin",
        "num_inputs": num_in,
        "num_outputs": num_out,
        "num_params": len(params),
        "main_inputs": main_in,
        "aux_input_ports": f"new_nonzero_u32({aux_in})" if aux_in else "",
        "midi_config": "Basic" if midi and midi.enabled else "None",
        "param_fields": "".join(fields),
        "param_inits": "".join(inits),
        "param_values": ", ".join(f"self.p_{i}.value()" for i in idents),
        "param_widgets": "".join(widgets),
        "clap_id": f"com.gen-dsp.{lib_name}",
        # Stable per name; VST3 hosts key saved sessions on it.
        "vst3_class_id": hashlib.md5(
            f"gen-dsp.nice.{lib_name}".encode(), usedforsecurity=False
        ).hexdigest()[:16],
        "clap_features": clap_features,
        "vst3_subcategories": vst3_subcategories,
    }
