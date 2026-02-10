"""
SuperCollider UGen platform implementation.

Generates cross-platform SuperCollider UGens (.scx on macOS, .so on Linux)
using CMake and the SC plugin interface headers (fetched at configure time
via CMake FetchContent from the SC source tarball).

Output artifacts:
  - <name>.scx/.so     (compiled UGen binary)
  - <UgenName>.sc       (SuperCollider class file for sclang)
"""

import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Optional

from gen_dsp.core.builder import BuildResult
from gen_dsp.core.parser import ExportInfo
from gen_dsp.core.project import ProjectConfig
from gen_dsp.errors import BuildError, ProjectError
from gen_dsp.platforms.base import Platform
from gen_dsp.templates import get_sc_templates_dir


@dataclass
class ParamInfo:
    """Metadata for a single gen~ parameter, parsed from export .cpp."""

    index: int
    name: str
    has_minmax: bool
    output_min: float
    output_max: float


# Regex to extract parameter blocks from gen~ export create() function.
_PARAM_BLOCK_RE = re.compile(
    r"pi\s*=\s*self->__commonstate\.params\s*\+\s*(\d+)\s*;"
    r".*?"
    r'pi->name\s*=\s*"([^"]+)"\s*;'
    r".*?"
    r"pi->hasminmax\s*=\s*(true|false)\s*;"
    r".*?"
    r"pi->outputmin\s*=\s*([\d.eE+\-]+)\s*;"
    r".*?"
    r"pi->outputmax\s*=\s*([\d.eE+\-]+)\s*;",
    re.DOTALL,
)


class SuperColliderPlatform(Platform):
    """SuperCollider UGen platform implementation using CMake."""

    name = "sc"

    @property
    def extension(self) -> str:
        """Get the extension for SC UGens."""
        if sys.platform == "darwin":
            return ".scx"
        return ".so"

    def get_build_instructions(self) -> list[str]:
        """Get build instructions for SuperCollider UGens."""
        return [
            "mkdir -p build && cd build && cmake .. && cmake --build .",
        ]

    def generate_project(
        self,
        export_info: ExportInfo,
        output_dir: Path,
        lib_name: str,
        buffers: list[str],
        config: Optional[ProjectConfig] = None,
    ) -> None:
        """Generate SuperCollider UGen project files."""
        templates_dir = get_sc_templates_dir()
        if not templates_dir.is_dir():
            raise ProjectError(f"SC templates not found at {templates_dir}")

        # Copy static files
        static_files = [
            "gen_ext_sc.cpp",
            "gen_ext_common_sc.h",
            "_ext_sc.cpp",
            "_ext_sc.h",
            "sc_buffer.h",
        ]
        for filename in static_files:
            src = templates_dir / filename
            if src.exists():
                shutil.copy2(src, output_dir / filename)

        # Parse parameter metadata from gen~ export
        params = self._parse_params(export_info)

        # UGen name (first letter capitalized, required by SC)
        ugen_name = self._capitalize_name(lib_name)

        # Generate .sc class file
        self._generate_sc_class(
            output_dir,
            lib_name,
            ugen_name,
            export_info.num_inputs,
            export_info.num_outputs,
            export_info.num_params,
            params,
        )

        # Resolve shared cache settings
        shared_cache = config is not None and config.shared_cache
        if shared_cache:
            from gen_dsp.core.cache import get_cache_dir

            cache_dir = str(get_cache_dir())
        else:
            cache_dir = ""

        # Generate CMakeLists.txt
        self._generate_cmakelists(
            templates_dir / "CMakeLists.txt.template",
            output_dir / "CMakeLists.txt",
            export_info.name,
            lib_name,
            ugen_name,
            export_info.num_inputs,
            export_info.num_outputs,
            export_info.num_params,
            use_shared_cache="ON" if shared_cache else "OFF",
            cache_dir=cache_dir,
        )

        # Generate gen_buffer.h using base class method
        self.generate_buffer_header(
            templates_dir / "gen_buffer.h.template",
            output_dir / "gen_buffer.h",
            buffers,
            header_comment="Buffer configuration for gen_dsp SuperCollider wrapper",
        )

        # Create build directory
        (output_dir / "build").mkdir(exist_ok=True)

    def _detect_plugin_type(self, num_inputs: int) -> str:
        """Detect SC UGen type from number of inputs.

        Returns 'effect' if inputs > 0, 'generator' if inputs == 0.
        """
        return "effect" if num_inputs > 0 else "generator"

    def _parse_params(self, export_info: ExportInfo) -> list[ParamInfo]:
        """Parse parameter metadata from the gen~ export .cpp file.

        Extracts parameter names and ranges from the structured
        getparameterinfo-style blocks in the gen~ exported code.
        Returns an empty list if parsing fails or no params exist.
        """
        if not export_info.cpp_path or not export_info.cpp_path.exists():
            return []

        content = export_info.cpp_path.read_text()
        params = []
        for m in _PARAM_BLOCK_RE.finditer(content):
            params.append(
                ParamInfo(
                    index=int(m.group(1)),
                    name=m.group(2),
                    has_minmax=(m.group(3) == "true"),
                    output_min=float(m.group(4)),
                    output_max=float(m.group(5)),
                )
            )
        params.sort(key=lambda p: p.index)
        return params

    @staticmethod
    def _capitalize_name(name: str) -> str:
        """Capitalize first letter for SC class name.

        SuperCollider class names must start with an uppercase letter.
        """
        if not name:
            return name
        return name[0].upper() + name[1:]

    def _generate_sc_class(
        self,
        output_dir: Path,
        lib_name: str,
        ugen_name: str,
        num_inputs: int,
        num_outputs: int,
        num_params: int,
        params: list[ParamInfo],
    ) -> None:
        """Generate SuperCollider class file (.sc).

        The class file tells sclang about the UGen's interface:
        argument names, default values, number of outputs, and
        input rate validation.
        """
        base_class = "MultiOutUGen" if num_outputs > 1 else "UGen"

        lines = [
            f"// {ugen_name}.sc - SuperCollider class for {lib_name}",
            "// Generated by gen-dsp",
            "",
            f"{ugen_name} : {base_class} {{",
        ]

        # Build argument list for *ar method
        args = []
        arg_names = []
        for i in range(num_inputs):
            args.append(f"in{i}")
            arg_names.append(f"in{i}")
        for i in range(num_params):
            if i < len(params):
                p = params[i]
                pname = self._sanitize_sc_arg(p.name)
                default = p.output_min
            else:
                pname = f"param{i}"
                default = 0.0
            default_str = self._format_sc_number(default)
            args.append(f"{pname}={default_str}")
            arg_names.append(pname)

        # *ar method
        if args:
            args_str = ", ".join(args)
            arg_names_str = ", ".join(arg_names)
            lines.append(f"    *ar {{ |{args_str}|")
            lines.append(f"        ^this.multiNew('audio', {arg_names_str})")
            lines.append("    }")
        else:
            lines.append("    *ar {")
            lines.append("        ^this.multiNew('audio')")
            lines.append("    }")

        # init method (only for MultiOutUGen)
        if num_outputs > 1:
            lines.append("")
            lines.append("    init { |... theInputs|")
            lines.append("        inputs = theInputs;")
            lines.append(f"        ^this.initOutputs({num_outputs}, rate);")
            lines.append("    }")

        # checkInputs (validate audio-rate inputs)
        if num_inputs > 0:
            lines.append("")
            lines.append("    checkInputs {")
            lines.append(f"        {num_inputs}.do {{ |i|")
            lines.append("            if(inputs[i].rate != 'audio') {")
            lines.append('                ^("input " ++ i ++ " is not audio rate");')
            lines.append("            };")
            lines.append("        };")
            lines.append("        ^this.checkValidInputs;")
            lines.append("    }")

        lines.append("}")

        content = "\n".join(lines) + "\n"
        (output_dir / f"{ugen_name}.sc").write_text(content)

    @staticmethod
    def _sanitize_sc_arg(name: str) -> str:
        """Sanitize a parameter name for use as an SC method argument.

        SC identifiers must start with a lowercase letter and contain
        only alphanumeric characters and underscores.
        """
        sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", name)
        if sanitized and sanitized[0].isupper():
            sanitized = sanitized[0].lower() + sanitized[1:]
        if sanitized and sanitized[0].isdigit():
            sanitized = "p_" + sanitized
        return sanitized or "param"

    @staticmethod
    def _format_sc_number(value: float) -> str:
        """Format a float for SC source (drop trailing .0 for integers)."""
        if value == int(value):
            return str(int(value))
        return str(value)

    def _generate_cmakelists(
        self,
        template_path: Path,
        output_path: Path,
        gen_name: str,
        lib_name: str,
        ugen_name: str,
        num_inputs: int,
        num_outputs: int,
        num_params: int,
        use_shared_cache: str = "OFF",
        cache_dir: str = "",
    ) -> None:
        """Generate CMakeLists.txt from template."""
        if not template_path.exists():
            raise ProjectError(f"CMakeLists.txt template not found at {template_path}")

        template_content = template_path.read_text()
        template = Template(template_content)
        content = template.safe_substitute(
            gen_name=gen_name,
            lib_name=lib_name,
            ugen_name=ugen_name,
            genext_version=self.GENEXT_VERSION,
            num_inputs=num_inputs,
            num_outputs=num_outputs,
            num_params=num_params,
            use_shared_cache=use_shared_cache,
            cache_dir=cache_dir,
        )
        output_path.write_text(content)

    def build(
        self,
        project_dir: Path,
        clean: bool = False,
        verbose: bool = False,
    ) -> BuildResult:
        """Build SuperCollider UGen using CMake."""
        cmakelists = project_dir / "CMakeLists.txt"
        if not cmakelists.exists():
            raise BuildError(f"CMakeLists.txt not found in {project_dir}")

        build_dir = project_dir / "build"

        # Clean if requested
        if clean and build_dir.exists():
            shutil.rmtree(build_dir)

        build_dir.mkdir(exist_ok=True)

        # Configure with CMake
        configure_result = self.run_command(["cmake", ".."], build_dir, verbose=verbose)
        if configure_result.returncode != 0:
            return BuildResult(
                success=False,
                platform="sc",
                output_file=None,
                stdout=configure_result.stdout,
                stderr=configure_result.stderr,
                return_code=configure_result.returncode,
            )

        # Build
        build_result = self.run_command(
            ["cmake", "--build", "."], build_dir, verbose=verbose
        )

        # Find output
        output_file = self.find_output(project_dir)

        return BuildResult(
            success=build_result.returncode == 0,
            platform="sc",
            output_file=output_file,
            stdout=build_result.stdout,
            stderr=build_result.stderr,
            return_code=build_result.returncode,
        )

    def clean(self, project_dir: Path) -> None:
        """Clean build artifacts."""
        build_dir = project_dir / "build"
        if build_dir.exists():
            shutil.rmtree(build_dir)

    def find_output(self, project_dir: Path) -> Optional[Path]:
        """Find the built SC UGen binary."""
        build_dir = project_dir / "build"
        if build_dir.is_dir():
            for ext in [".scx", ".so"]:
                for f in build_dir.glob(f"**/*{ext}"):
                    if f.is_file():
                        return f
        return None
