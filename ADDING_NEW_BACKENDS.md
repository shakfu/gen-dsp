# Adding New Backends to gen_dsp

This guide explains how to add support for a new audio platform (e.g., SuperCollider, VCV Rack, LV2) to gen_dsp.

## Overview

gen_dsp uses a platform registry system that makes adding new backends straightforward. Each platform is a Python class that implements the `Platform` interface, plus a set of C++ template files for the actual wrapper code.

**Required components:**
1. Platform class (Python) - handles project generation and build orchestration
2. C++ wrapper templates - the actual code that wraps gen~ exports
3. Build system configuration - Makefile, CMakeLists.txt, or similar
4. Registry entry - one line to register the new platform

## Step 1: Understand the Platform Interface

All platforms extend the `Platform` abstract base class in `src/gen_dsp/platforms/base.py`:

```python
class Platform(ABC):
    # Platform identifier (e.g., 'pd', 'max', 'supercollider')
    name: str = "base"

    # File extension for built externals (can be a @property for OS-dependent)
    extension: str = ""

    # Version string (inherited, typically don't override)
    GENEXT_VERSION = "0.8.0"

    @abstractmethod
    def generate_project(self, export_info, output_dir, lib_name, buffers) -> None:
        """Copy templates and generate config files."""
        pass

    @abstractmethod
    def build(self, project_dir, clean=False, verbose=False) -> BuildResult:
        """Invoke the build system."""
        pass

    @abstractmethod
    def clean(self, project_dir) -> None:
        """Remove build artifacts."""
        pass

    @abstractmethod
    def find_output(self, project_dir) -> Optional[Path]:
        """Locate the compiled external."""
        pass

    def get_build_instructions(self) -> list[str]:
        """Return CLI commands shown to user after project generation."""
        return ["# Build instructions not available"]
```

The base class also provides utility methods you can use:
- `generate_buffer_header()` - generates gen_buffer.h from template
- `run_command()` - runs subprocess with optional output streaming

## Step 2: Create the Platform Class

Create a new file `src/gen_dsp/platforms/yourplatform.py`:

```python
"""
YourPlatform implementation.
"""

import platform as sys_platform
import shutil
from pathlib import Path
from string import Template
from typing import Optional

from gen_dsp.core.builder import BuildResult
from gen_dsp.core.parser import ExportInfo
from gen_dsp.errors import BuildError, ProjectError
from gen_dsp.platforms.base import Platform
from gen_dsp.templates import get_templates_dir


class YourPlatform(Platform):
    """YourPlatform implementation."""

    name = "yourplatform"  # Used in CLI: gen-dsp init -p yourplatform

    @property
    def extension(self) -> str:
        """Get the file extension for the current OS."""
        system = sys_platform.system().lower()
        if system == "darwin":
            return ".yourext"
        elif system == "linux":
            return ".so"
        elif system == "windows":
            return ".dll"
        return ".so"

    def get_build_instructions(self) -> list[str]:
        """Return build commands shown to user."""
        return [
            "make",  # or cmake, scons, etc.
        ]

    def generate_project(
        self,
        export_info: ExportInfo,
        output_dir: Path,
        lib_name: str,
        buffers: list[str],
    ) -> None:
        """Generate project files."""
        templates_dir = get_templates_dir() / "yourplatform"
        if not templates_dir.is_dir():
            raise ProjectError(f"Templates not found at {templates_dir}")

        # Copy static C++ files
        static_files = [
            "gen_ext_yourplatform.cpp",
            "gen_ext_common_yourplatform.h",
            # ... other files
        ]
        for filename in static_files:
            src = templates_dir / filename
            if src.exists():
                shutil.copy2(src, output_dir / filename)

        # Generate build config (Makefile, CMakeLists.txt, etc.)
        self._generate_build_config(
            templates_dir / "Makefile.template",  # or CMakeLists.txt.template
            output_dir / "Makefile",
            export_info.name,
            lib_name,
        )

        # Generate gen_buffer.h using base class method
        self.generate_buffer_header(
            templates_dir / "gen_buffer.h.template",
            output_dir / "gen_buffer.h",
            buffers,
            header_comment="Buffer configuration for YourPlatform wrapper",
        )

    def _generate_build_config(
        self,
        template_path: Path,
        output_path: Path,
        gen_name: str,
        lib_name: str,
    ) -> None:
        """Generate build configuration from template."""
        if not template_path.exists():
            raise ProjectError(f"Build template not found: {template_path}")

        template_content = template_path.read_text()
        template = Template(template_content)
        content = template.safe_substitute(
            gen_name=gen_name,
            lib_name=lib_name,
            genext_version=self.GENEXT_VERSION,
        )
        output_path.write_text(content)

    def build(
        self,
        project_dir: Path,
        clean: bool = False,
        verbose: bool = False,
    ) -> BuildResult:
        """Build the external."""
        # Check for required files
        makefile = project_dir / "Makefile"
        if not makefile.exists():
            raise BuildError(f"Makefile not found in {project_dir}")

        # Clean if requested
        if clean:
            self.run_command(["make", "clean"], project_dir)

        # Build using base class run_command helper
        result = self.run_command(["make"], project_dir, verbose=verbose)

        # Find output
        output_file = self.find_output(project_dir)

        return BuildResult(
            success=result.returncode == 0,
            platform=self.name,
            output_file=output_file,
            stdout=result.stdout,
            stderr=result.stderr,
            return_code=result.returncode,
        )

    def clean(self, project_dir: Path) -> None:
        """Clean build artifacts."""
        self.run_command(["make", "clean"], project_dir)

    def find_output(self, project_dir: Path) -> Optional[Path]:
        """Find the built external."""
        for f in project_dir.glob(f"*{self.extension}"):
            return f
        return None
```

## Step 3: Create C++ Templates

Create directory `src/gen_dsp/templates/yourplatform/` with:

### Required Files

1. **gen_ext_yourplatform.cpp** - Main wrapper implementation
   - Object creation/destruction
   - DSP setup and perform routine
   - Parameter handling
   - Buffer management

2. **gen_ext_common_yourplatform.h** - Macro definitions
   - Name mangling macros
   - Platform-specific type definitions

3. **gen_buffer.h.template** - Buffer configuration template
   ```c
   // Buffer configuration for gen_dsp wrapper
   // Auto-generated by gen-dsp

   #define WRAPPER_BUFFER_COUNT $buffer_count

   $buffer_definitions
   ```

4. **Build configuration template** (e.g., `Makefile.template` or `CMakeLists.txt.template`)
   ```makefile
   # Makefile for $lib_name

   gen.name = $gen_name
   lib.name = $lib_name
   gendsp.version = $genext_version

   # ... platform-specific build rules
   ```

### C++ Wrapper Structure

Your wrapper needs to:

1. **Include gen~ export**: The exported code lives in `./gen/` directory
2. **Implement platform's plugin API**: Create the object type your platform expects
3. **Map gen~ I/O**: Connect platform's audio buffers to gen~'s perform function
4. **Handle parameters**: Route parameter messages to gen~'s `setparameter()` function
5. **Manage buffers**: If the platform supports audio buffers/tables, implement the `DataInterface<t_sample>` that gen~ expects

Example structure:
```cpp
#include "gen_ext_common_yourplatform.h"
#include "gen_buffer.h"

// Include the gen~ export (namespace setup done in _ext files)
#include "./gen/your_gen_export.cpp"

// Platform-specific object structure
typedef struct {
    // Platform's base object type
    YourPlatformObject base;

    // gen~ state
    CommonState* m_genObject;

    // I/O buffers for gen~
    t_sample** m_inputs;
    t_sample** m_outputs;

    // Buffer instances (if using buffers)
    // ...
} YourWrapper;

// Object creation
YourWrapper* yourwrapper_new(...) {
    YourWrapper* x = /* allocate */;

    // Initialize gen~ object
    x->m_genObject = (CommonState*)create(
        /* samplerate */, /* blocksize */);

    return x;
}

// DSP perform routine
void yourwrapper_perform(YourWrapper* x, /* platform args */) {
    // Get audio buffers from platform
    // Call gen~'s perform function
    perform(x->m_genObject, x->m_inputs, num_inputs,
            x->m_outputs, num_outputs, blocksize);
}

// Parameter handling
void yourwrapper_param(YourWrapper* x, const char* name, float value) {
    // Find parameter index and set it
    for (int i = 0; i < num_params(); i++) {
        if (strcmp(getparametername(x->m_genObject, i), name) == 0) {
            setparameter(x->m_genObject, i, value, NULL);
            break;
        }
    }
}
```

## Step 4: Add Template Accessor

Edit `src/gen_dsp/templates/__init__.py` to add a function for your templates:

```python
def get_yourplatform_templates_dir() -> Path:
    """Get the path to YourPlatform templates."""
    return get_templates_dir() / "yourplatform"
```

## Step 5: Register the Platform

Edit `src/gen_dsp/platforms/__init__.py`:

```python
from gen_dsp.platforms.yourplatform import YourPlatform

PLATFORM_REGISTRY: dict[str, Type[Platform]] = {
    "pd": PureDataPlatform,
    "max": MaxPlatform,
    "yourplatform": YourPlatform,  # Add this line
}

__all__ = [
    # ...
    "YourPlatform",  # Add this line
]
```

**That's it!** The CLI will automatically pick up the new platform:
- `gen-dsp init -p yourplatform` will work
- `gen-dsp build -p yourplatform` will work
- Help text will show the new platform option

## Step 6: Add Tests

Create `tests/test_yourplatform.py`:

```python
"""Tests for YourPlatform."""

import pytest
from gen_dsp.platforms import get_platform
from gen_dsp.platforms.yourplatform import YourPlatform


class TestYourPlatform:
    def test_platform_registered(self):
        """Test platform is in registry."""
        platform = get_platform("yourplatform")
        assert isinstance(platform, YourPlatform)

    def test_extension(self):
        """Test extension is valid."""
        platform = YourPlatform()
        assert platform.extension in [".yourext", ".so", ".dll"]

    def test_build_instructions(self):
        """Test build instructions are provided."""
        platform = YourPlatform()
        instructions = platform.get_build_instructions()
        assert len(instructions) > 0
```

## Reference: ExportInfo

The `export_info` parameter passed to `generate_project()` contains:

```python
@dataclass
class ExportInfo:
    name: str           # Name of the gen~ export (e.g., "gen_exported")
    path: Path          # Path to the export directory
    num_inputs: int     # Number of signal inputs
    num_outputs: int    # Number of signal outputs
    num_params: int     # Number of parameters
    buffers: list[str]  # Detected buffer names
    has_exp2f_issue: bool  # Whether exp2f patch is needed
    cpp_path: Path      # Path to the .cpp file
    h_path: Path        # Path to the .h file
```

## Reference: BuildResult

The `build()` method must return a `BuildResult`:

```python
@dataclass
class BuildResult:
    success: bool           # True if build succeeded
    platform: str           # Platform name
    output_file: Path|None  # Path to built external, or None
    stdout: str             # Captured stdout
    stderr: str             # Captured stderr
    return_code: int        # Process return code
```

## Platform-Specific Considerations

### SuperCollider UGens
- Uses scons or CMake
- UGen interface differs from genlib - may need adapter layer
- Single-sample or block processing modes
- Buffer access via `SndBuf`

### VCV Rack
- Uses CMake with Rack SDK
- Sample-by-sample processing
- Different parameter model (knobs, CV inputs)

### LV2
- Uses meson or CMake
- Standardized plugin format with TTL manifests
- Port-based I/O model

### JUCE (VST/AU/AAX)
- Uses CMake or Projucer
- Most complex but broadest reach
- Consider as a "meta-platform" generating multiple formats

### Embedded (Bela, Daisy)
- Cross-compilation considerations
- Fixed buffer sizes may be required
- Limited memory/CPU constraints

## Checklist

- [ ] Platform class implements all abstract methods
- [ ] Templates directory created with all required files
- [ ] C++ wrapper compiles and runs
- [ ] Platform registered in `PLATFORM_REGISTRY`
- [ ] Template accessor added to `templates/__init__.py`
- [ ] Tests added and passing
- [ ] `get_build_instructions()` returns useful commands
- [ ] Documentation updated (README, CHANGELOG)
